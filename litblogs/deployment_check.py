"""Fail-closed production release admission and database readiness checks."""

from __future__ import annotations

import io
import os
import re
import stat
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Callable

from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from config import get_settings

REQUIRED_PYTHON = (3, 13)
ALLOWED_MODES = frozenset({"preflight", "postflight"})
COMMIT_PATTERN = re.compile(r"commit=[0-9a-f]{40}")
EPOCH_PATTERN = re.compile(r"built_at_epoch=[1-9][0-9]{8,}")
RUNTIME_CONFIG_ENDPOINT = b"/api/runtime-config"
OBSOLETE_BUILD_CONFIG_KEYS = (
    b"VITE_CSRF_COOKIE_NAME",
    b"VITE_GOOGLE_CLIENT_ID",
    b"VITE_MICROSOFT_CLIENT_ID",
    b"VITE_MICROSOFT_TENANT_ID",
)
MAX_FRONTEND_ASSET_BYTES = 8 * 1024 * 1024
MAX_FRONTEND_TOTAL_BYTES = 24 * 1024 * 1024
REQUIRED_RELEASE_FILES = (
    "deploy/README.md",
    "deploy/logging.json",
    "deploy/nginx/litblogs.conf",
    "deploy/scripts/backup_postgres.py",
    "deploy/scripts/postgres_common.py",
    "deploy/scripts/release_switch.py",
    "deploy/scripts/restore_verify_postgres.py",
    "deploy/scripts/upload_snapshot_common.py",
    "deploy/systemd/litblogs-password-reset.service",
    "deploy/systemd/litblogs-password-reset.timer",
    "deploy/systemd/litblogs-reminders.service",
    "deploy/systemd/litblogs-reminders.timer",
    "deploy/systemd/litblogs-upload-reconciliation.service",
    "deploy/systemd/litblogs-upload-reconciliation.timer",
    "deploy/systemd/litblogs-web.service",
    "docs/operations/production-runbook.md",
    "litblogs/access_control.py",
    "litblogs/alembic.ini",
    "litblogs/auth_security.py",
    "litblogs/base.py",
    "litblogs/config.py",
    "litblogs/database.py",
    "litblogs/deployment_check.py",
    "litblogs/identity_controls.py",
    "litblogs/main.py",
    "litblogs/manage_accounts.py",
    "litblogs/manage_teacher_invitations.py",
    "litblogs/migrations/env.py",
    "litblogs/migrations/sqlite_contract.py",
    "litblogs/migrations/script.py.mako",
    "litblogs/models.py",
    "litblogs/oauth_security.py",
    "litblogs/observability.py",
    "litblogs/operator_runtime.py",
    "litblogs/password_reset_delivery.py",
    "litblogs/password_reset_job.py",
    "litblogs/rich_text_contract.json",
    "litblogs/rich_text_contract.py",
    "litblogs/reminder_job.py",
    "litblogs/requirements.in",
    "litblogs/requirements-lock.in",
    "litblogs/requirements-lock.txt",
    "litblogs/requirements.txt",
    "litblogs/runtime_database_identity.py",
    "litblogs/schemas.py",
    "litblogs/security_utils.py",
    "litblogs/upload_assets.py",
    "litblogs/upload_legacy_inventory.py",
    "litblogs/upload_reconciliation_job.py",
    "litblogs/upload_scanner.py",
)


class _DeploymentFailure(Exception):
    """Internal failure carrying only an allowlisted operator reason code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def validate_rich_text_contract(path: Path) -> object:
    """Load the contract lazily so import failures remain bounded preflight errors."""

    from rich_text_contract import validate_rich_text_contract as validate

    return validate(path)


def _safe_release_file(root: Path, relative_path: str) -> Path:
    candidate = root / relative_path
    cursor = root
    for component in Path(relative_path).parts:
        cursor /= component
        if cursor.is_symlink():
            raise _DeploymentFailure("manifest_invalid")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError):
        raise _DeploymentFailure("manifest_invalid") from None
    if not resolved.is_file():
        raise _DeploymentFailure("manifest_invalid")
    return resolved


def _validate_release_manifest(root: Path) -> None:
    manifest_path = _safe_release_file(root, "RELEASE-MANIFEST")
    try:
        lines = manifest_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        raise _DeploymentFailure("manifest_invalid") from None
    if (
        len(lines) != 2
        or COMMIT_PATTERN.fullmatch(lines[0]) is None
        or EPOCH_PATTERN.fullmatch(lines[1]) is None
    ):
        raise _DeploymentFailure("manifest_invalid")

    for relative_path in REQUIRED_RELEASE_FILES:
        _safe_release_file(root, relative_path)

    contract_path = _safe_release_file(root, "litblogs/rich_text_contract.json")
    try:
        validate_rich_text_contract(contract_path)
    except Exception:
        raise _DeploymentFailure("manifest_invalid") from None

    versions_dir = root / "litblogs" / "migrations" / "versions"
    try:
        migration_files = tuple(versions_dir.glob("*.py"))
    except OSError:
        raise _DeploymentFailure("manifest_invalid") from None
    if not migration_files:
        raise _DeploymentFailure("manifest_invalid")
    for migration_file in migration_files:
        _safe_release_file(root, migration_file.relative_to(root).as_posix())


def _validate_frontend_contract(root: Path) -> None:
    _safe_release_file(root, "litblogs/dist/index.html")
    assets_dir = root / "litblogs" / "dist" / "assets"
    try:
        javascript_assets = tuple(assets_dir.rglob("*.js"))
    except OSError:
        raise _DeploymentFailure("frontend_contract_invalid") from None
    if not javascript_assets:
        raise _DeploymentFailure("frontend_contract_invalid")

    endpoint_found = False
    total_size = 0
    for asset in javascript_assets:
        try:
            safe_asset = _safe_release_file(root, asset.relative_to(root).as_posix())
            size = safe_asset.stat().st_size
            if size <= 0 or size > MAX_FRONTEND_ASSET_BYTES:
                raise _DeploymentFailure("frontend_contract_invalid")
            total_size += size
            if total_size > MAX_FRONTEND_TOTAL_BYTES:
                raise _DeploymentFailure("frontend_contract_invalid")
            content = safe_asset.read_bytes()
        except (OSError, ValueError):
            raise _DeploymentFailure("frontend_contract_invalid") from None
        if any(key in content for key in OBSOLETE_BUILD_CONFIG_KEYS):
            raise _DeploymentFailure("frontend_contract_invalid")
        endpoint_found = endpoint_found or RUNTIME_CONFIG_ENDPOINT in content

    if not endpoint_found:
        raise _DeploymentFailure("frontend_contract_invalid")


def _database_check(selected_check: Callable[[], None]) -> None:
    try:
        selected_check()
    except (ConnectionError, OSError, TimeoutError, SQLAlchemyError):
        raise _DeploymentFailure("database_unreachable") from None
    except Exception:
        raise _DeploymentFailure("migration_mismatch") from None


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


def _validate_postgres_ca_custody(
    database_url: str | None,
    *,
    required_owner_uid: int = 0,
    required_group_gid: int = 0,
    required_mode: int = 0o644,
    trusted_ancestor: str | Path = Path("/"),
) -> None:
    """Require the reviewed CA file with production-safe POSIX custody."""

    try:
        root_certificate = make_url(database_url or "").query["sslrootcert"]
        certificate = Path(root_certificate)
        if os.name != "posix" or not certificate.is_absolute():
            raise ValueError
        if certificate.is_symlink():
            raise ValueError
        resolved = certificate.resolve(strict=True)
        if str(resolved) != root_certificate:
            raise ValueError
        metadata = resolved.stat(follow_symlinks=False)
        if not _postgres_ca_metadata_matches_contract(
            metadata,
            required_owner_uid=required_owner_uid,
            required_group_gid=required_group_gid,
            required_mode=required_mode,
        ):
            raise ValueError
        boundary_path = Path(trusted_ancestor)
        if not boundary_path.is_absolute():
            raise ValueError
        boundary = boundary_path.resolve(strict=True)
        directory = resolved.parent
        if boundary != boundary_path or directory.resolve(strict=True) != directory:
            raise ValueError
        directory.relative_to(boundary)
        cursor = directory
        while True:
            directory_metadata = cursor.stat(follow_symlinks=False)
            if (
                stat.S_ISLNK(directory_metadata.st_mode)
                or not stat.S_ISDIR(directory_metadata.st_mode)
                or directory_metadata.st_uid != required_owner_uid
                or directory_metadata.st_mode & 0o022
            ):
                raise ValueError
            if cursor == boundary:
                break
            cursor = cursor.parent

    except (KeyError, OSError, TypeError, ValueError):
        raise _DeploymentFailure("config_invalid") from None


def _check_alembic_schema_drift(release_root: Path) -> None:
    """Run Alembic's read-only autogeneration drift check without emitting details."""

    from alembic import command
    from alembic.config import Config

    from database import engine

    backend_root = release_root / "litblogs"
    migration_output = io.StringIO()
    config = Config(stdout=migration_output, output_buffer=migration_output)
    config.set_main_option("script_location", str(backend_root / "migrations"))
    config.set_main_option("prepend_sys_path", str(backend_root))
    with engine.connect() as connection:
        config.attributes["connection"] = connection
        with redirect_stdout(migration_output), redirect_stderr(migration_output):
            command.check(config)


def run(
    *,
    app_settings=None,
    release_root=None,
    database_check=None,
    migration_drift_check=None,
    ca_custody_check=None,
    interpreter_version=None,
    mode: str = "postflight",
) -> int:
    """Run a pre-migration artifact check or a post-migration DB-head check."""

    try:
        version = tuple(interpreter_version or sys.version_info[:2])
        if version != REQUIRED_PYTHON:
            raise _DeploymentFailure("interpreter_invalid")
        if mode not in ALLOWED_MODES:
            raise _DeploymentFailure("config_invalid")

        try:
            selected_settings = app_settings or get_settings()
            if selected_settings.app_env != "production":
                raise ValueError
        except Exception:
            raise _DeploymentFailure("config_invalid") from None

        selected_ca_check = ca_custody_check or _validate_postgres_ca_custody
        selected_ca_check(selected_settings.database_url)

        try:
            root = Path(release_root or Path(__file__).resolve().parents[1]).resolve(
                strict=True
            )
        except (OSError, ValueError):
            raise _DeploymentFailure("manifest_invalid") from None
        _validate_release_manifest(root)
        _validate_frontend_contract(root)

        if mode == "postflight":
            if database_check is None:
                from database import check_database_readiness

                selected_database_check = check_database_readiness
            else:
                selected_database_check = database_check
            _database_check(selected_database_check)
            selected_drift_check = migration_drift_check or (
                lambda: _check_alembic_schema_drift(root)
            )
            _database_check(selected_drift_check)
    except _DeploymentFailure as failure:
        print(f"deployment-check: failed code={failure.code}", file=sys.stderr)
        return 1
    except Exception:
        # Keep unexpected faults bounded and non-reflective as a configuration failure.
        print("deployment-check: failed code=config_invalid", file=sys.stderr)
        return 1

    print("deployment-check: ready")
    return 0


def main(argv=None) -> int:
    """Parse the one allowlisted flag without reflecting unknown arguments."""

    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        return run(mode="postflight")
    if arguments == ["--preflight"]:
        return run(mode="preflight")
    print("deployment-check: failed code=config_invalid", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
