import hmac
import os
import re
import stat
from functools import lru_cache
from ipaddress import ip_address
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from dotenv import dotenv_values
from pydantic import EmailStr, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

BASE_DIR = Path(__file__).resolve().parent
CANONICAL_PRODUCTION_UPLOAD_ROOT = Path("/var/lib/litblogs/uploads")
PRODUCTION_UPLOAD_ROOT = CANONICAL_PRODUCTION_UPLOAD_ROOT
PRODUCTION_UPLOAD_USER = "litblogs"
PRODUCTION_UPLOAD_GROUP = "litblogs"
PRODUCTION_UPLOAD_ROOT_MODE = 0o750
PRODUCTION_POSTGRES_ROOT_CA = PurePosixPath(
    "/etc/litblogs/postgres-root-ca.pem"
)
VALID_APP_ENVIRONMENTS = frozenset({"development", "test", "production"})
SECRET_KEY_MIN_BYTES = 32
DEFAULT_PUSH_ENDPOINT_HOSTS = (
    "fcm.googleapis.com",
    "updates.push.services.mozilla.com",
    "web.push.apple.com",
    ".notify.windows.com",
)
_PLACEHOLDER_FRAGMENTS = (
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
_GOOGLE_CLIENT_ID_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*\.apps\.googleusercontent\.com$"
)
_EMAIL_DOMAIN_PATTERN = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$"
)
_LOCAL_SCANNER_HOST_PATTERN = re.compile(
    r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)
_POSIX_UPLOAD_CUSTODY = os.name == "posix"
_HOST_COOKIE_PATTERN = re.compile(r"^__Host-[A-Za-z0-9!#$%&'*+.^_`|~-]{1,64}$")
_RESERVED_DNS_SUFFIXES = frozenset({"example", "invalid", "localhost", "test"})


def _csv_tuple(value: Any, *, lowercase: bool = False, strip_slash: bool = False) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        values = value.split(",")
    elif isinstance(value, (list, tuple, set, frozenset)):
        values = value
    else:
        raise ValueError("value must be a comma-separated string or sequence")

    normalized = []
    for item in values:
        text = str(item).strip()
        if strip_slash:
            text = text.rstrip("/")
        if lowercase:
            text = text.lower()
        if text and text not in normalized:
            normalized.append(text)
    return tuple(normalized)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        case_sensitive=False,
        enable_decoding=False,
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
        hide_input_in_errors=True,
    )

    app_env: str = "development"
    database_url: str | None = Field(default=None, repr=False)
    secret_key: SecretStr | None = None
    jwt_issuer: str | None = None
    jwt_audience: str | None = None
    jwt_clock_skew_seconds: int = Field(default=5, ge=0, le=60)
    access_token_expire_minutes: int = Field(default=30, ge=1, le=60)

    frontend_url: str | None = None
    base_url: str | None = None
    cors_allowed_origins: tuple[str, ...] = ()
    allowed_hosts: tuple[str, ...] = ()
    allowed_email_domains: tuple[str, ...] = ()
    microsoft_allowed_tenant_ids: tuple[str, ...] = ()

    google_client_id: str | None = None
    microsoft_client_id: str | None = None
    microsoft_tenant_id: str | None = None
    oauth_http_timeout_seconds: float = Field(default=5.0, ge=0.5, le=10.0)
    oauth_jwks_cache_seconds: int = Field(default=300, ge=60, le=3_600)

    session_cookie_name: str | None = None
    csrf_cookie_name: str | None = None
    session_cookie_secure: bool = False
    api_docs_enabled: bool = False

    db_pool_size: int = Field(default=5, ge=1, le=20)
    db_max_overflow: int = Field(default=5, ge=0, le=20)
    db_pool_timeout_seconds: int = Field(default=10, ge=1, le=30)
    db_pool_recycle_seconds: int = Field(default=900, ge=60, le=3_600)
    db_connect_timeout_seconds: int = Field(default=5, ge=1, le=10)
    db_statement_timeout_ms: int = Field(default=15_000, ge=1_000, le=60_000)
    db_lock_timeout_ms: int = Field(default=5_000, ge=500, le=30_000)

    teacher_invite_hmac_key: SecretStr | None = None
    admin_access_code: SecretStr | None = None
    admin_code: SecretStr | None = None
    local_password_registration_enabled: bool = False

    reset_database_on_startup: bool = False
    push_notifications_enabled: bool = False
    vapid_public_key: str = ""
    vapid_private_key: SecretStr | None = None
    vapid_subject: str = "mailto:admin@litblogs.local"
    push_reminder_interval_seconds: int = Field(default=300, ge=60, le=86_400)
    push_allowed_endpoint_hosts: tuple[str, ...] = DEFAULT_PUSH_ENDPOINT_HOSTS
    push_delivery_timeout_seconds: float = Field(default=5.0, ge=0.5, le=10.0)
    email_host: str | None = None
    email_port: int = Field(default=587, ge=1, le=65_535)
    email_smtp_timeout_seconds: float = Field(default=5.0, ge=0.5, le=10.0)
    email_username: str | None = None
    email_password: SecretStr | None = None
    email_from: EmailStr | None = None
    password_reset_worker_enabled: bool = True
    password_reset_worker_interval_seconds: int = Field(default=5, ge=1, le=60)
    password_reset_claim_timeout_seconds: int = Field(default=120, ge=60, le=600)
    upload_root: Path | None = None
    upload_scanner_required: bool = False
    upload_scanner_host: str | None = None
    upload_scanner_allowed_hosts: tuple[str, ...] = ()
    upload_scanner_port: int = Field(default=3310, ge=1, le=65_535)
    upload_scanner_timeout_seconds: float = Field(default=5.0, ge=0.5, le=30.0)
    upload_registry_schema_ready: bool = False
    upload_legacy_import_complete: bool = False
    upload_backup_restore_verified: bool = False

    @field_validator("app_env", mode="before")
    @classmethod
    def normalize_app_env(cls, value: Any) -> str:
        normalized = str(value or "development").strip().lower()
        if normalized not in VALID_APP_ENVIRONMENTS:
            allowed = ", ".join(sorted(VALID_APP_ENVIRONMENTS))
            raise ValueError(f"APP_ENV must be one of: {allowed}")
        return normalized

    @field_validator("local_password_registration_enabled", mode="before")
    @classmethod
    def validate_local_password_registration_flag(cls, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if value == "true":
            return True
        if value == "false":
            return False
        raise ValueError(
            "LOCAL_PASSWORD_REGISTRATION_ENABLED must be literal true or false"
        )

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def normalize_origins(cls, value: Any) -> tuple[str, ...]:
        return _csv_tuple(value, strip_slash=True)

    @field_validator(
        "allowed_email_domains",
        "microsoft_allowed_tenant_ids",
        "push_allowed_endpoint_hosts",
        "upload_scanner_allowed_hosts",
        mode="before",
    )
    @classmethod
    def normalize_lowercase_csv(cls, value: Any) -> tuple[str, ...]:
        return _csv_tuple(value, lowercase=True)

    @field_validator("allowed_hosts", mode="before")
    @classmethod
    def normalize_allowed_hosts(cls, value: Any) -> tuple[str, ...]:
        return _csv_tuple(value, lowercase=True)

    @field_validator(
        "database_url",
        "jwt_issuer",
        "jwt_audience",
        "frontend_url",
        "base_url",
        "google_client_id",
        "microsoft_client_id",
        "microsoft_tenant_id",
        "session_cookie_name",
        "csrf_cookie_name",
        "email_host",
        "email_username",
        "email_from",
        "upload_scanner_host",
        mode="before",
    )
    @classmethod
    def strip_optional_text(cls, value: Any) -> Any:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_production_safety(self):
        if self.upload_scanner_required and not self.upload_scanner_host:
            raise ValueError("UPLOAD_SCANNER_HOST is required when upload scanning is required")
        if self.upload_scanner_host:
            normalized_scanner_host = self.upload_scanner_host.lower()
            if not _is_local_or_private_scanner_host(normalized_scanner_host):
                raise ValueError("UPLOAD_SCANNER_HOST must identify a local or private service")
            if normalized_scanner_host not in self.upload_scanner_allowed_hosts:
                raise ValueError(
                    "UPLOAD_SCANNER_ALLOWED_HOSTS must include UPLOAD_SCANNER_HOST"
                )

        if self.app_env != "production":
            return self

        if self.reset_database_on_startup:
            raise ValueError("RESET_DATABASE_ON_STARTUP must be false in production")

        secret = self.secret_key.get_secret_value() if self.secret_key else ""
        if len(secret.encode("utf-8")) < SECRET_KEY_MIN_BYTES:
            raise ValueError("SECRET_KEY must contain at least 32 bytes in production")
        lowered_secret = secret.lower()
        if any(fragment in lowered_secret for fragment in _PLACEHOLDER_FRAGMENTS):
            raise ValueError("SECRET_KEY must not be a placeholder in production")
        if len(set(secret)) < 12:
            raise ValueError("SECRET_KEY must be randomly generated in production")

        required = {
            "DATABASE_URL": self.database_url,
            "JWT_ISSUER": self.jwt_issuer,
            "JWT_AUDIENCE": self.jwt_audience,
            "FRONTEND_URL": self.frontend_url,
            "CORS_ALLOWED_ORIGINS": self.cors_allowed_origins,
            "ALLOWED_HOSTS": self.allowed_hosts,
            "ALLOWED_EMAIL_DOMAINS": self.allowed_email_domains,
            "GOOGLE_CLIENT_ID": self.google_client_id,
            "MICROSOFT_CLIENT_ID": self.microsoft_client_id,
            "MICROSOFT_TENANT_ID": self.microsoft_tenant_id,
            "MICROSOFT_ALLOWED_TENANT_IDS": self.microsoft_allowed_tenant_ids,
            "SESSION_COOKIE_NAME": self.session_cookie_name,
            "CSRF_COOKIE_NAME": self.csrf_cookie_name,
            "TEACHER_INVITE_HMAC_KEY": self.teacher_invite_hmac_key,
            "ADMIN_ACCESS_CODE": self.admin_access_code,
            "EMAIL_HOST": self.email_host,
            "EMAIL_USERNAME": self.email_username,
            "EMAIL_PASSWORD": self.email_password,
            "EMAIL_FROM": self.email_from,
            "UPLOAD_ROOT": self.upload_root,
            "UPLOAD_SCANNER_HOST": self.upload_scanner_host,
            "UPLOAD_SCANNER_ALLOWED_HOSTS": self.upload_scanner_allowed_hosts,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(f"Missing required production setting: {missing[0]}")
        database_scheme = urlsplit(self.database_url or "").scheme.lower()
        if database_scheme.split("+", 1)[0] != "postgresql":
            raise ValueError("DATABASE_URL must use PostgreSQL in production")

        placeholder_checked = {
            "JWT_ISSUER": self.jwt_issuer,
            "JWT_AUDIENCE": self.jwt_audience,
            "GOOGLE_CLIENT_ID": self.google_client_id,
            "MICROSOFT_CLIENT_ID": self.microsoft_client_id,
            "MICROSOFT_TENANT_ID": self.microsoft_tenant_id,
            "SESSION_COOKIE_NAME": self.session_cookie_name,
            "CSRF_COOKIE_NAME": self.csrf_cookie_name,
            "TEACHER_INVITE_HMAC_KEY": _reveal_secret(self.teacher_invite_hmac_key),
            "ADMIN_ACCESS_CODE": _reveal_secret(self.admin_access_code),
            "EMAIL_PASSWORD": _reveal_secret(self.email_password),
        }
        if self.admin_code is not None:
            placeholder_checked["ADMIN_CODE"] = _reveal_secret(self.admin_code)
        for name, value in placeholder_checked.items():
            if any(fragment in str(value).lower() for fragment in _PLACEHOLDER_FRAGMENTS):
                raise ValueError(f"{name} must not be a placeholder in production")

        minimum_lengths = {
            "GOOGLE_CLIENT_ID": (self.google_client_id, 8),
            "MICROSOFT_CLIENT_ID": (self.microsoft_client_id, 8),
            "MICROSOFT_TENANT_ID": (self.microsoft_tenant_id, 8),
            "TEACHER_INVITE_HMAC_KEY": (
                _reveal_secret(self.teacher_invite_hmac_key),
                SECRET_KEY_MIN_BYTES,
            ),
            "ADMIN_ACCESS_CODE": (_reveal_secret(self.admin_access_code), 16),
            "EMAIL_PASSWORD": (_reveal_secret(self.email_password), 16),
        }
        if self.admin_code is not None:
            minimum_lengths["ADMIN_CODE"] = (_reveal_secret(self.admin_code), 16)
        for name, (value, minimum_bytes) in minimum_lengths.items():
            if len(str(value).encode("utf-8")) < minimum_bytes:
                raise ValueError(f"{name} must contain at least {minimum_bytes} bytes in production")

        invitation_key = _reveal_secret(self.teacher_invite_hmac_key)
        if len(set(invitation_key)) < 12:
            raise ValueError(
                "TEACHER_INVITE_HMAC_KEY must be randomly generated in production"
            )
        if hmac.compare_digest(
            invitation_key.encode("utf-8"),
            secret.encode("utf-8"),
        ):
            raise ValueError("TEACHER_INVITE_HMAC_KEY must differ from SECRET_KEY")

        if not _GOOGLE_CLIENT_ID_PATTERN.fullmatch(self.google_client_id or ""):
            raise ValueError("GOOGLE_CLIENT_ID must be a valid Google OAuth client ID in production")
        if not _is_uuid(self.microsoft_client_id):
            raise ValueError("MICROSOFT_CLIENT_ID must be a UUID in production")
        if not _is_uuid(self.microsoft_tenant_id):
            raise ValueError("MICROSOFT_TENANT_ID must be a fixed tenant UUID in production")
        if any(not _is_uuid(tenant_id) for tenant_id in self.microsoft_allowed_tenant_ids):
            raise ValueError("MICROSOFT_ALLOWED_TENANT_IDS must contain only tenant UUIDs in production")
        if self.microsoft_tenant_id.lower() not in self.microsoft_allowed_tenant_ids:
            raise ValueError(
                "MICROSOFT_ALLOWED_TENANT_IDS must include MICROSOFT_TENANT_ID in production"
            )
        if any(not _is_email_domain(domain) for domain in self.allowed_email_domains):
            raise ValueError("ALLOWED_EMAIL_DOMAINS must contain valid DNS domains in production")
        if any(not _is_email_domain(host) for host in self.allowed_hosts):
            raise ValueError("ALLOWED_HOSTS must contain exact DNS hostnames in production")
        if not _is_network_host(self.email_host):
            raise ValueError("EMAIL_HOST must be an exact DNS hostname or IP address in production")
        email_from_domain = str(self.email_from or "").rsplit("@", 1)[-1]
        if _is_reserved_dns_name(email_from_domain):
            raise ValueError("EMAIL_FROM must not use a reserved example domain in production")
        if not _HOST_COOKIE_PATTERN.fullmatch(self.session_cookie_name or ""):
            raise ValueError("SESSION_COOKIE_NAME must use a valid __Host- prefix in production")
        if not _HOST_COOKIE_PATTERN.fullmatch(self.csrf_cookie_name or ""):
            raise ValueError("CSRF_COOKIE_NAME must use a valid __Host- prefix in production")
        if self.session_cookie_name == self.csrf_cookie_name:
            raise ValueError("Session and CSRF cookie names must differ in production")
        if self.push_notifications_enabled:
            raise ValueError(
                "PUSH_NOTIFICATIONS_ENABLED must remain false until endpoint SSRF controls exist"
            )

        if not self.session_cookie_secure:
            raise ValueError("SESSION_COOKIE_SECURE must be true in production")
        if self.api_docs_enabled:
            raise ValueError("API_DOCS_ENABLED must be false in production")
        if not _is_verified_postgresql_url(self.database_url):
            raise ValueError(
                "DATABASE_URL must use PostgreSQL with sslmode=verify-full and no target overrides"
            )
        if not _is_https_url(self.jwt_issuer):
            raise ValueError("JWT_ISSUER must use an unambiguous HTTPS URL in production")
        if _is_reserved_dns_name(self.jwt_audience or ""):
            raise ValueError("JWT_AUDIENCE must not use a reserved example domain in production")
        if (
            not _is_https_url(self.frontend_url)
            or urlsplit(self.frontend_url or "").path not in {"", "/"}
        ):
            raise ValueError(
                "FRONTEND_URL must use the root HTTPS origin in production"
            )
        if any(origin == "*" or not _is_https_origin(origin) for origin in self.cors_allowed_origins):
            raise ValueError("CORS_ALLOWED_ORIGINS must contain explicit HTTPS origins in production")
        frontend_origin = _canonical_https_origin(self.frontend_url)
        configured_origins = {
            _canonical_https_origin(origin) for origin in self.cors_allowed_origins
        }
        if frontend_origin not in configured_origins:
            raise ValueError("CORS_ALLOWED_ORIGINS must include the FRONTEND_URL origin")
        frontend_host = urlsplit(self.frontend_url or "").hostname or ""
        if frontend_host.lower() not in self.allowed_hosts:
            raise ValueError("ALLOWED_HOSTS must include the FRONTEND_URL hostname")
        if not self.password_reset_worker_enabled:
            raise ValueError("PASSWORD_RESET_WORKER_ENABLED must be true in production")
        if self.local_password_registration_enabled:
            raise ValueError(
                "LOCAL_PASSWORD_REGISTRATION_ENABLED must be false in production"
            )
        if not self.upload_scanner_required:
            raise ValueError("UPLOAD_SCANNER_REQUIRED must be true in production")
        if not _is_canonical_production_upload_root(self.upload_root):
            raise ValueError(
                "UPLOAD_ROOT must be /var/lib/litblogs/uploads in production"
            )
        if not _has_valid_upload_root_custody(self.upload_root):
            raise ValueError("UPLOAD_ROOT custody validation failed")
        if not self.upload_registry_schema_ready:
            raise ValueError("UPLOAD_REGISTRY_SCHEMA_READY must be explicitly confirmed")
        if not self.upload_legacy_import_complete:
            raise ValueError("UPLOAD_LEGACY_IMPORT_COMPLETE must be explicitly confirmed")
        if not self.upload_backup_restore_verified:
            raise ValueError("UPLOAD_BACKUP_RESTORE_VERIFIED must be explicitly confirmed")
        return self


def _is_https_url(value: str | None) -> bool:
    try:
        parsed = urlsplit(value or "")
        _ = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and not _is_reserved_dns_name(parsed.hostname or "")
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
    )


def _is_verified_postgresql_url(value: str | None) -> bool:
    try:
        url = make_url(value or "")
    except (TypeError, ValueError):
        return False

    if (
        url.drivername not in {"postgresql", "postgresql+psycopg2"}
        or not _is_network_host(url.host)
        or not url.username
        or not url.database
    ):
        return False
    password = url.password or ""
    if len(password.encode("utf-8")) < 16 or any(
        fragment in password.lower() for fragment in _PLACEHOLDER_FRAGMENTS
    ):
        return False
    if set(url.query) != {"sslmode", "sslrootcert"}:
        return False
    if url.query.get("sslmode") != "verify-full":
        return False

    root_certificate = url.query.get("sslrootcert")
    if not isinstance(root_certificate, str) or len(root_certificate) > 4_096:
        return False
    certificate_path = PurePosixPath(root_certificate)
    return (
        certificate_path == PRODUCTION_POSTGRES_ROOT_CA
        and str(certificate_path) == root_certificate
    )


def _is_uuid(value: str | None) -> bool:
    try:
        UUID(str(value or ""))
    except (TypeError, ValueError, AttributeError):
        return False
    return True


def _is_email_domain(value: str) -> bool:
    return bool(_EMAIL_DOMAIN_PATTERN.fullmatch(value)) and not _is_reserved_dns_name(value)


def _is_reserved_dns_name(value: str) -> bool:
    normalized = str(value or "").strip().lower().rstrip(".")
    if not normalized:
        return False
    return normalized.rsplit(".", 1)[-1] in _RESERVED_DNS_SUFFIXES


def _is_network_host(value: str | None) -> bool:
    normalized = str(value or "").strip().lower()
    if _is_email_domain(normalized):
        return True
    try:
        ip_address(normalized)
    except ValueError:
        return False
    return True


def _reveal_secret(value: SecretStr | None) -> str:
    return value.get_secret_value() if value else ""


def _is_https_origin(value: str) -> bool:
    return _canonical_https_origin(value) is not None


def _canonical_https_origin(value: str | None) -> str | None:
    try:
        parsed = urlsplit(value or "")
        port = parsed.port
    except ValueError:
        return None
    hostname = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or not hostname
        or _is_reserved_dns_name(hostname)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        return None
    port_suffix = "" if port in {None, 443} else f":{port}"
    return f"https://{hostname}{port_suffix}"


def _is_local_or_private_scanner_host(value: str) -> bool:
    try:
        address = ip_address(value)
    except ValueError:
        return value == "localhost" or bool(_LOCAL_SCANNER_HOST_PATTERN.fullmatch(value))
    return bool(address.is_private or address.is_loopback or address.is_link_local)


def _upload_root_metadata_matches_contract(
    metadata: os.stat_result,
    *,
    required_owner_uid: int,
    required_group_gid: int,
    required_mode: int = PRODUCTION_UPLOAD_ROOT_MODE,
) -> bool:
    """Return whether the upload leaf has exact service custody."""

    return (
        stat.S_ISDIR(metadata.st_mode)
        and metadata.st_uid == required_owner_uid
        and metadata.st_gid == required_group_gid
        and stat.S_IMODE(metadata.st_mode) == required_mode
    )


def _upload_ancestor_metadata_matches_contract(
    metadata: os.stat_result,
    *,
    required_owner_uids: frozenset[int] = frozenset({0}),
) -> bool:
    """Return whether an upload ancestor is immutable by the service identity."""

    return (
        stat.S_ISDIR(metadata.st_mode)
        and metadata.st_uid in required_owner_uids
        and not metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
    )


def _production_upload_identity() -> tuple[int, int] | None:
    if not _POSIX_UPLOAD_CUSTODY:
        return None
    try:
        import grp
        import pwd

        owner_uid = pwd.getpwnam(PRODUCTION_UPLOAD_USER).pw_uid
        group_gid = grp.getgrnam(PRODUCTION_UPLOAD_GROUP).gr_gid
    except (ImportError, KeyError):
        return None
    return owner_uid, group_gid


def _has_valid_upload_root_custody(
    upload_root: Path | None,
    *,
    required_owner_uid: int | None = None,
    required_group_gid: int | None = None,
) -> bool:
    if upload_root is None or not upload_root.is_absolute():
        return False
    try:
        absolute_root = upload_root.absolute()
        synthetic_test_contract = (
            PRODUCTION_UPLOAD_ROOT != CANONICAL_PRODUCTION_UPLOAD_ROOT
            and absolute_root == PRODUCTION_UPLOAD_ROOT
            and required_owner_uid is None
            and required_group_gid is None
        )
        if _POSIX_UPLOAD_CUSTODY:
            if synthetic_test_contract:
                required_owner_uid = os.geteuid()
                required_group_gid = os.getegid()
                required_mode = 0o700
                required_ancestor_owner_uids = frozenset({0, os.geteuid()})
            else:
                required_mode = PRODUCTION_UPLOAD_ROOT_MODE
                required_ancestor_owner_uids = frozenset({0})
            if (required_owner_uid is None) != (required_group_gid is None):
                return False
            if required_owner_uid is None or required_group_gid is None:
                identity = _production_upload_identity()
                if identity is None:
                    return False
                required_owner_uid, required_group_gid = identity

        for candidate in tuple(reversed(absolute_root.parents)) + (absolute_root,):
            is_junction = getattr(candidate, "is_junction", lambda: False)
            if candidate.is_symlink() or is_junction():
                return False

        if _POSIX_UPLOAD_CUSTODY:
            for ancestor in absolute_root.parents:
                if not _upload_ancestor_metadata_matches_contract(
                    ancestor.stat(follow_symlinks=False),
                    required_owner_uids=required_ancestor_owner_uids,
                ):
                    return False

        if not absolute_root.exists() or not absolute_root.is_dir():
            return False
        resolved_root = absolute_root.resolve(strict=True)
        if resolved_root.is_relative_to(BASE_DIR.resolve()):
            return False

        root_stat = resolved_root.stat()
        if _POSIX_UPLOAD_CUSTODY:
            if required_owner_uid is None or required_group_gid is None:
                return False
            if not _upload_root_metadata_matches_contract(
                root_stat,
                required_owner_uid=required_owner_uid,
                required_group_gid=required_group_gid,
                required_mode=required_mode,
            ):
                return False
            access_mode = os.W_OK | os.X_OK
        else:
            access_mode = os.W_OK
        return os.access(resolved_root, access_mode)
    except OSError:
        return False


def _is_canonical_production_upload_root(upload_root: Path | None) -> bool:
    return upload_root is not None and upload_root == PRODUCTION_UPLOAD_ROOT


def _selected_app_env(base_dir: Path) -> str:
    process_value = os.getenv("APP_ENV")
    if process_value is not None:
        raw_value = process_value
    else:
        raw_value = dotenv_values(base_dir / ".env").get("APP_ENV", "development")
    normalized = str(raw_value or "development").strip().lower()
    if normalized not in VALID_APP_ENVIRONMENTS:
        allowed = ", ".join(sorted(VALID_APP_ENVIRONMENTS))
        raise ValueError(f"APP_ENV must be one of: {allowed}")
    return normalized


def load_settings(*, base_dir: Path | str = BASE_DIR) -> Settings:
    resolved_base_dir = Path(base_dir).resolve()
    app_env = _selected_app_env(resolved_base_dir)
    env_files = tuple(
        path
        for path in (
            resolved_base_dir / ".env",
            resolved_base_dir / f".env.{app_env}",
        )
        if path.exists()
    )
    return Settings(
        app_env=app_env,
        _env_file=env_files or None,
        _env_file_encoding="utf-8",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
