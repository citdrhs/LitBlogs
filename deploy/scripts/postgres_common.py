#!/usr/bin/env python3
"""Shared safety primitives for PostgreSQL operator commands."""

from __future__ import annotations

import os
import re
import stat
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, field
from ipaddress import ip_address
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qsl, unquote, urlsplit

RESTORE_DATABASE_PREFIX = "litblog_restore_verify_"
POSTGRES_CLIENT_PREFIX = "/usr/lib/postgresql/17/bin"
POSTGRES_CLIENT_ROOT = Path(POSTGRES_CLIENT_PREFIX)
POSTGRES_CLIENT_NAMES = frozenset({"createdb", "pg_dump", "pg_restore", "psql"})
POSTGRES_VERSION = re.compile(
    r"^[a-z_]+ \(PostgreSQL\) 17\.[0-9]+(?:[^\r\n]*)?[\r\n]*$"
)
SAFE_OPERATOR_PATH = "/usr/bin:/bin"
POSTGRES_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,62}$")
POSTGRES_DNS_NAME = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$"
)
POSTGRES_CERTIFICATE_DIRECTORY = PurePosixPath("/etc/litblogs")
POSTGRES_ROOT_CA = POSTGRES_CERTIFICATE_DIRECTORY / "postgres-root-ca.pem"
RESTORE_DATABASE = re.compile(
    rf"^{RESTORE_DATABASE_PREFIX}[a-z0-9](?:[a-z0-9_]*[a-z0-9])?$"
)
INVALID_PERCENT_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")
ALLOWED_QUERY_KEYS = frozenset({"sslmode", "sslrootcert", "sslcert", "sslkey"})
POSTGRES_PASSWORD_MIN_BYTES = 16
POSTGRES_PASSWORD_PLACEHOLDER_FRAGMENTS = (
    "changeme",
    "change-me",
    "placeholder",
    "replace-me",
    "replace-with",
    "replace_with",
    "test-",
    "test-only",
    "your-secret",
)
PASSTHROUGH_ENVIRONMENT_KEYS = frozenset(
    {
        "HOME",
        "LANG",
        "LC_ALL",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "WINDIR",
    }
)


class PostgresOperatorError(RuntimeError):
    """An operator-safe error that intentionally excludes connection details."""


@dataclass(frozen=True)
class PostgresConnection:
    """Validated libpq connection fields with a redacted representation."""

    host: str
    port: int
    user: str
    database: str
    sslmode: str
    password: str | None = field(default=None, repr=False)
    sslrootcert: str | None = None
    sslcert: str | None = None
    sslkey: str | None = field(default=None, repr=False)


def _validate_trusted_directory_chain(
    directory: str | Path,
    *,
    purpose: str,
    trusted_ancestor: str | Path,
    approved_owner_uids: frozenset[int],
    allow_root_owned_sticky_ancestor: bool = False,
) -> tuple[Path, ...]:
    """Validate every directory that can rename a security-sensitive path."""

    path = Path(directory)
    boundary_path = Path(trusted_ancestor)
    try:
        if not path.is_absolute() or not boundary_path.is_absolute():
            raise ValueError
        boundary = boundary_path.resolve(strict=True)
        resolved = path.resolve(strict=True)
        if boundary != boundary_path or resolved != path:
            raise ValueError
        resolved.relative_to(boundary)
    except (OSError, ValueError) as exc:
        raise PostgresOperatorError(
            f"The {purpose} custody path must be canonical and contain no symlinks"
        ) from exc

    chain: list[Path] = []
    cursor = path
    while True:
        chain.append(cursor)
        if cursor == boundary:
            break
        cursor = cursor.parent
    for component in chain:
        descriptor = purpose if component == path else f"{purpose} ancestor"
        try:
            metadata = component.stat(follow_symlinks=False)
        except OSError as exc:
            raise PostgresOperatorError(
                f"The {descriptor} custody could not be verified"
            ) from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise PostgresOperatorError(
                f"The {descriptor} custody path must contain no symlinks"
            )
        if not stat.S_ISDIR(metadata.st_mode):
            raise PostgresOperatorError(f"The {descriptor} must be a directory")
        if metadata.st_uid not in approved_owner_uids:
            raise PostgresOperatorError(f"The {descriptor} has an untrusted owner")
        if metadata.st_mode & 0o022:
            root_owned_sticky_boundary = (
                allow_root_owned_sticky_ancestor
                and component != path
                and metadata.st_uid == 0
                and bool(metadata.st_mode & stat.S_ISVTX)
            )
            if not root_owned_sticky_boundary:
                raise PostgresOperatorError(
                    f"The {descriptor} has unsafe permissions"
                )
    return tuple(chain)


def validate_private_operator_directory(
    directory: str | Path,
    *,
    purpose: str,
    required_owner_uid: int | None = None,
    trusted_ancestor: str | Path = Path("/"),
) -> Path:
    """Require owner-only custody under an immutable POSIX ancestor chain."""

    path = Path(directory)
    if os.name != "posix":
        return path
    expected_uid = os.geteuid() if required_owner_uid is None else required_owner_uid
    try:
        metadata = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise PostgresOperatorError(
            f"The {purpose} custody could not be verified"
        ) from exc
    if metadata.st_uid != expected_uid:
        raise PostgresOperatorError(
            f"The {purpose} must be owned by the effective operator"
        )
    _validate_trusted_directory_chain(
        path,
        purpose=purpose,
        trusted_ancestor=trusted_ancestor,
        approved_owner_uids=frozenset({0, expected_uid}),
        # A root-owned sticky system boundary such as /tmp cannot rename an
        # operator-owned child. Production paths under /srv should not rely on it.
        allow_root_owned_sticky_ancestor=True,
    )
    metadata = path.stat(follow_symlinks=False)
    if metadata.st_uid != expected_uid:
        raise PostgresOperatorError(
            f"The {purpose} must be owned by the effective operator"
        )
    if stat.S_IMODE(metadata.st_mode) != 0o700:
        raise PostgresOperatorError(
            f"The {purpose} must use exact owner-only mode 0700"
        )
    return path


def postgres_executable(command_name: str) -> str:
    """Return an allowlisted absolute PostgreSQL 17 client path."""

    if command_name not in POSTGRES_CLIENT_NAMES:
        raise PostgresOperatorError("The PostgreSQL client command is not allowlisted")
    return f"{POSTGRES_CLIENT_PREFIX}/{command_name}"


def is_immutable_client_root_mode(mode: int) -> bool:
    """Return whether a client directory cannot be replaced by group/other."""

    return mode & 0o022 == 0


def validate_postgres_client_installation(
    *,
    client_root: str | Path = POSTGRES_CLIENT_ROOT,
    runner=subprocess.run,
    required_owner_uid: int | None = 0,
    trusted_ancestor: str | Path = Path("/"),
) -> None:
    """Verify immutable absolute PostgreSQL 17 clients before secrets are supplied."""

    root = Path(client_root)
    if not root.is_absolute():
        raise PostgresOperatorError("The PostgreSQL client root must be absolute")
    try:
        if root.is_symlink():
            raise PostgresOperatorError(
                "The PostgreSQL client root must not be a symlink"
            )
        resolved_root = root.resolve(strict=True)
        boundary = Path(trusted_ancestor).resolve(strict=True)
        resolved_root.relative_to(boundary)
        if resolved_root != root or boundary != Path(trusted_ancestor):
            raise PostgresOperatorError(
                "The PostgreSQL client root path must have no symlink ancestors"
            )
        root_metadata = root.stat(follow_symlinks=False)
    except (OSError, ValueError) as exc:
        raise PostgresOperatorError(
            "The pinned PostgreSQL 17 client installation is unavailable"
        ) from exc
    if not stat.S_ISDIR(root_metadata.st_mode):
        raise PostgresOperatorError(
            "The PostgreSQL client root must be a directory"
        )
    if os.name == "posix":
        chain = []
        cursor = root
        while True:
            chain.append(cursor)
            if cursor == boundary:
                break
            cursor = cursor.parent
        for component in chain:
            descriptor = (
                "PostgreSQL client root"
                if component == root
                else "PostgreSQL client root ancestor"
            )
            try:
                metadata = component.stat(follow_symlinks=False)
            except OSError as exc:
                raise PostgresOperatorError(
                    f"The {descriptor} custody could not be verified"
                ) from exc
            if stat.S_ISLNK(metadata.st_mode):
                raise PostgresOperatorError(
                    f"The {descriptor} must not be a symlink"
                )
            if not stat.S_ISDIR(metadata.st_mode):
                raise PostgresOperatorError(
                    f"The {descriptor} must be a directory"
                )
            if not is_immutable_client_root_mode(metadata.st_mode):
                raise PostgresOperatorError(
                    f"The {descriptor} has unsafe permissions"
                )
            if (
                required_owner_uid is not None
                and metadata.st_uid != required_owner_uid
            ):
                raise PostgresOperatorError(
                    f"The {descriptor} has an untrusted owner"
                )

    safe_environment = {
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": SAFE_OPERATOR_PATH,
    }
    for command_name in sorted(POSTGRES_CLIENT_NAMES):
        executable = root / command_name
        try:
            if executable.is_symlink():
                raise PostgresOperatorError(
                    "A pinned PostgreSQL 17 client must not be a symlink"
                )
            resolved = executable.resolve(strict=True)
            resolved.relative_to(resolved_root)
            metadata = resolved.stat()
        except (OSError, ValueError) as exc:
            raise PostgresOperatorError(
                "A pinned PostgreSQL 17 client is unavailable"
            ) from exc
        if not stat.S_ISREG(metadata.st_mode) or (
            os.name == "posix" and metadata.st_mode & 0o022
        ):
            raise PostgresOperatorError(
                "A pinned PostgreSQL 17 client has unsafe permissions"
            )
        if (
            os.name == "posix"
            and required_owner_uid is not None
            and metadata.st_uid != required_owner_uid
        ):
            raise PostgresOperatorError(
                "A pinned PostgreSQL 17 client has an untrusted owner"
            )
        try:
            result = runner(
                [str(resolved), "--version"],
                env=safe_environment,
                check=False,
                shell=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise PostgresOperatorError(
                "A pinned PostgreSQL 17 client could not be verified"
            ) from exc
        if result.returncode != 0 or POSTGRES_VERSION.fullmatch(result.stdout or "") is None:
            raise PostgresOperatorError(
                "Every operator client must be from the pinned PostgreSQL 17 installation"
            )


def _decode_component(value: str | None, *, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise PostgresOperatorError(
                "The PostgreSQL URL is missing a required field"
            )
        return None
    if INVALID_PERCENT_ESCAPE.search(value):
        raise PostgresOperatorError("The PostgreSQL URL contains an invalid escape")
    decoded = unquote(value)
    if (required and not decoded) or any(ord(character) < 32 for character in decoded):
        raise PostgresOperatorError("The PostgreSQL URL contains an invalid field")
    return decoded


def _validate_identifier(value: str) -> str:
    if not POSTGRES_IDENTIFIER.fullmatch(value):
        raise PostgresOperatorError("The PostgreSQL database identifier is invalid")
    return value


def _is_single_network_host(value: str) -> bool:
    normalized = value.lower()
    if POSTGRES_DNS_NAME.fullmatch(normalized):
        return True
    try:
        ip_address(normalized)
    except ValueError:
        return False
    return True


def parse_postgres_url(database_url: str) -> PostgresConnection:
    """Parse a strict TLS PostgreSQL URL without retaining the original URL."""

    if not database_url or INVALID_PERCENT_ESCAPE.search(database_url):
        raise PostgresOperatorError("DATABASE_URL is not a valid PostgreSQL URL")
    try:
        parsed = urlsplit(database_url)
        parsed_port = parsed.port
        port = 5432 if parsed_port is None else parsed_port
        hostname = parsed.hostname
    except ValueError as exc:
        raise PostgresOperatorError(
            "DATABASE_URL is not a valid PostgreSQL URL"
        ) from exc

    if parsed.scheme not in {"postgres", "postgresql", "postgresql+psycopg2"}:
        raise PostgresOperatorError("DATABASE_URL must use PostgreSQL")
    if parsed.fragment or not hostname or not parsed.username:
        raise PostgresOperatorError(
            "DATABASE_URL is missing a required PostgreSQL field"
        )
    if parsed.netloc.rsplit("@", 1)[-1].endswith(":"):
        raise PostgresOperatorError("DATABASE_URL contains an invalid port")
    if not 1 <= port <= 65535:
        raise PostgresOperatorError("DATABASE_URL contains an invalid port")
    if not parsed.path.startswith("/") or parsed.path == "/":
        raise PostgresOperatorError("DATABASE_URL must name a database")

    database = _decode_component(parsed.path[1:], required=True)
    user = _decode_component(parsed.username, required=True)
    password = _decode_component(parsed.password)
    host = _decode_component(hostname, required=True)
    if database is None or user is None or host is None:
        raise PostgresOperatorError(
            "DATABASE_URL is missing a required PostgreSQL field"
        )
    if password is None or len(password.encode("utf-8")) < POSTGRES_PASSWORD_MIN_BYTES:
        raise PostgresOperatorError(
            "DATABASE_URL requires an explicit managed PostgreSQL password"
        )
    if any(
        fragment in password.lower()
        for fragment in POSTGRES_PASSWORD_PLACEHOLDER_FRAGMENTS
    ):
        raise PostgresOperatorError(
            "DATABASE_URL requires a non-placeholder PostgreSQL password"
        )
    if "/" in database or "\\" in database:
        raise PostgresOperatorError("DATABASE_URL contains an invalid database name")
    _validate_identifier(database)
    if not POSTGRES_IDENTIFIER.fullmatch(user):
        raise PostgresOperatorError("DATABASE_URL contains an invalid user name")
    if not _is_single_network_host(host):
        raise PostgresOperatorError("DATABASE_URL contains an invalid host")

    try:
        query_items = parse_qsl(
            parsed.query, keep_blank_values=True, strict_parsing=True
        )
    except ValueError as exc:
        raise PostgresOperatorError("DATABASE_URL contains an invalid query") from exc
    query: dict[str, str] = {}
    for key, value in query_items:
        if key in query or key not in ALLOWED_QUERY_KEYS:
            raise PostgresOperatorError(
                "DATABASE_URL contains a disallowed connection override"
            )
        query[key] = value
    if set(query) != {"sslmode", "sslrootcert"} or query.get("sslmode") != "verify-full":
        raise PostgresOperatorError(
            "PostgreSQL operator connections require sslmode=verify-full"
        )

    root_certificate = query["sslrootcert"]
    certificate_path = PurePosixPath(root_certificate)
    if (
        not root_certificate
        or any(ord(character) < 32 for character in root_certificate)
        or not certificate_path.is_absolute()
        or not certificate_path.is_relative_to(POSTGRES_CERTIFICATE_DIRECTORY)
        or certificate_path != POSTGRES_ROOT_CA
        or ".." in certificate_path.parts
        or str(certificate_path) != root_certificate
    ):
        raise PostgresOperatorError("DATABASE_URL contains an invalid TLS path")

    return PostgresConnection(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        sslmode="verify-full",
        sslrootcert=root_certificate,
    )


def _postgres_ca_metadata_matches_contract(
    metadata: os.stat_result,
    *,
    required_owner_uid: int = 0,
    required_group_gid: int = 0,
    required_mode: int = 0o644,
) -> bool:
    """Return whether a CA has the exact reviewed public-file custody."""

    return (
        stat.S_ISREG(metadata.st_mode)
        and metadata.st_uid == required_owner_uid
        and metadata.st_gid == required_group_gid
        and stat.S_IMODE(metadata.st_mode) == required_mode
    )


def validate_postgres_tls_custody(
    connection: PostgresConnection,
    *,
    required_owner_uid: int = 0,
    required_group_gid: int = 0,
    required_mode: int = 0o644,
    trusted_ancestor: str | Path = Path("/"),
) -> None:
    """Require the canonical CA with exact public-file production custody."""

    if os.name != "posix" or connection.sslrootcert is None:
        raise PostgresOperatorError("The PostgreSQL root CA custody check failed")
    certificate = Path(connection.sslrootcert)
    try:
        if certificate.is_symlink():
            raise OSError
        resolved = certificate.resolve(strict=True)
        metadata = resolved.stat(follow_symlinks=False)
    except OSError:
        raise PostgresOperatorError(
            "The PostgreSQL root CA custody check failed"
        ) from None
    if str(resolved) != connection.sslrootcert:
        raise PostgresOperatorError("The PostgreSQL root CA custody check failed")
    try:
        _validate_trusted_directory_chain(
            resolved.parent,
            purpose="PostgreSQL root CA directory",
            trusted_ancestor=trusted_ancestor,
            approved_owner_uids=frozenset({required_owner_uid}),
        )
    except PostgresOperatorError:
        raise PostgresOperatorError(
            "The PostgreSQL root CA custody check failed"
        ) from None
    if not _postgres_ca_metadata_matches_contract(
        metadata,
        required_owner_uid=required_owner_uid,
        required_group_gid=required_group_gid,
        required_mode=required_mode,
    ):
        raise PostgresOperatorError("The PostgreSQL root CA custody check failed")


def validate_restore_database_name(database_name: str) -> str:
    """Allow only fresh, disposable verification database names."""

    if len(database_name) > 63 or not RESTORE_DATABASE.fullmatch(database_name):
        raise PostgresOperatorError(
            f"Restore targets must use the {RESTORE_DATABASE_PREFIX}<identifier> namespace"
        )
    return database_name


def build_pg_environment(
    connection: PostgresConnection,
    *,
    database: str | None = None,
    base_environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build a minimal libpq environment with no inherited target overrides."""

    selected_database = _validate_identifier(database or connection.database)
    inherited = os.environ if base_environment is None else base_environment
    environment = {
        key: value
        for key, value in inherited.items()
        if key.upper() in PASSTHROUGH_ENVIRONMENT_KEYS and value
    }
    environment["PATH"] = SAFE_OPERATOR_PATH
    environment.update(
        {
            "PGHOST": connection.host,
            "PGPORT": str(connection.port),
            "PGUSER": connection.user,
            "PGDATABASE": selected_database,
            "PGSSLMODE": connection.sslmode,
            "PGCONNECT_TIMEOUT": "10",
        }
    )
    if connection.password is not None:
        environment["PGPASSWORD"] = connection.password
    if connection.sslrootcert is not None:
        environment["PGSSLROOTCERT"] = connection.sslrootcert
    if connection.sslcert is not None:
        environment["PGSSLCERT"] = connection.sslcert
    if connection.sslkey is not None:
        environment["PGSSLKEY"] = connection.sslkey
    return environment
