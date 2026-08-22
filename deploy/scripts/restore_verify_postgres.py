#!/usr/bin/env python3
"""Restore a backup only into a synthetic verification database."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import io
import json
import os
import re
import stat
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from postgres_common import (
    PostgresConnection,
    PostgresOperatorError,
    build_pg_environment,
    parse_postgres_url,
    postgres_executable,
    validate_postgres_client_installation,
    validate_postgres_tls_custody,
    validate_private_operator_directory,
    validate_restore_database_name,
)
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.pool import NullPool

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]
DriftChecker = Callable[[PostgresConnection, str], None]
MANIFEST_FORMAT = "litblogs-postgresql-custom-v1"
MANIFEST_KEYS = frozenset({"archive", "created_at", "format", "sha256", "size_bytes"})
SHA256 = re.compile(r"^[0-9a-f]{64}$")
UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
IDENTITY_RESULT = re.compile(r"^ok:([0-9]+)$")
PSQL_VARIABLE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
MAX_MANIFEST_BYTES = 16 * 1024
EXPECTED_ALEMBIC_HEAD = "b7c41f0e2d19"

SCHEMA_INTEGRITY_SQL = """
WITH required_tables(name) AS (
    VALUES
        ('users'),
        ('password_resets'),
        ('push_subscriptions'),
        ('teachers'),
        ('user_settings'),
        ('classes'),
        ('assignments'),
        ('blogs'),
        ('class_enrollments'),
        ('assignment_drafts'),
        ('assignment_reminder_notifications'),
        ('assignment_submissions'),
        ('comments'),
        ('post_likes'),
        ('saved_posts'),
        ('assignment_submission_replies'),
        ('comment_likes')
),
expected_foreign_keys(
    table_name,
    column_name,
    foreign_table_name,
    foreign_column_name
) AS (
    VALUES
        ('password_resets', 'user_id', 'users', 'id'),
        ('push_subscriptions', 'user_id', 'users', 'id'),
        ('teachers', 'user_id', 'users', 'id'),
        ('user_settings', 'user_id', 'users', 'id'),
        ('classes', 'teacher_id', 'teachers', 'id'),
        ('assignments', 'class_id', 'classes', 'id'),
        ('assignments', 'created_by', 'users', 'id'),
        ('blogs', 'class_id', 'classes', 'id'),
        ('blogs', 'owner_id', 'users', 'id'),
        ('class_enrollments', 'class_id', 'classes', 'id'),
        ('class_enrollments', 'student_id', 'users', 'id'),
        ('assignment_drafts', 'assignment_id', 'assignments', 'id'),
        ('assignment_drafts', 'student_id', 'users', 'id'),
        ('assignment_reminder_notifications', 'assignment_id', 'assignments', 'id'),
        ('assignment_reminder_notifications', 'user_id', 'users', 'id'),
        ('assignment_submissions', 'assignment_id', 'assignments', 'id'),
        ('assignment_submissions', 'student_id', 'users', 'id'),
        ('comments', 'blog_id', 'blogs', 'id'),
        ('comments', 'parent_id', 'comments', 'id'),
        ('comments', 'user_id', 'users', 'id'),
        ('post_likes', 'post_id', 'blogs', 'id'),
        ('post_likes', 'user_id', 'users', 'id'),
        ('saved_posts', 'post_id', 'blogs', 'id'),
        ('saved_posts', 'user_id', 'users', 'id'),
        ('assignment_submission_replies', 'submission_id', 'assignment_submissions', 'id'),
        ('assignment_submission_replies', 'user_id', 'users', 'id'),
        ('comment_likes', 'comment_id', 'comments', 'id'),
        ('comment_likes', 'user_id', 'users', 'id')
),
actual_foreign_keys AS (
    SELECT
        constraint_table.table_name,
        key_column.column_name,
        foreign_column.table_name AS foreign_table_name,
        foreign_column.column_name AS foreign_column_name
    FROM information_schema.table_constraints AS constraint_table
    JOIN information_schema.key_column_usage AS key_column
      ON key_column.constraint_schema = constraint_table.constraint_schema
     AND key_column.constraint_name = constraint_table.constraint_name
    JOIN information_schema.constraint_column_usage AS foreign_column
      ON foreign_column.constraint_schema = constraint_table.constraint_schema
     AND foreign_column.constraint_name = constraint_table.constraint_name
    WHERE constraint_table.constraint_type = 'FOREIGN KEY'
      AND constraint_table.table_schema = 'public'
      AND foreign_column.table_schema = 'public'
)
SELECT CASE WHEN COUNT(to_regclass('public.' || name)) = COUNT(*)
                 AND BOOL_AND(to_regclass('public.' || name) IS NOT NULL)
                 AND NOT EXISTS (
                     SELECT 1
                     FROM expected_foreign_keys AS expected
                     WHERE NOT EXISTS (
                         SELECT 1
                         FROM actual_foreign_keys AS actual
                         WHERE actual.table_name = expected.table_name
                           AND actual.column_name = expected.column_name
                           AND actual.foreign_table_name = expected.foreign_table_name
                           AND actual.foreign_column_name = expected.foreign_column_name
                     )
                 )
                 AND (
                     to_regclass('public.federated_identities') IS NULL
                     OR (
                         EXISTS (
                             SELECT 1
                             FROM actual_foreign_keys AS identity_foreign_key
                             WHERE identity_foreign_key.table_name = 'federated_identities'
                               AND identity_foreign_key.column_name = 'user_id'
                               AND identity_foreign_key.foreign_table_name = 'users'
                               AND identity_foreign_key.foreign_column_name = 'id'
                         )
                         AND EXISTS (
                             SELECT 1
                             FROM pg_constraint AS identity_constraint
                             WHERE identity_constraint.conrelid =
                                   to_regclass('public.federated_identities')
                               AND identity_constraint.contype = 'p'
                         )
                         AND EXISTS (
                             SELECT 1
                             FROM pg_constraint AS identity_constraint
                             WHERE identity_constraint.conrelid =
                                   to_regclass('public.federated_identities')
                               AND identity_constraint.conname =
                                   'ck_federated_identity_provider'
                               AND identity_constraint.contype = 'c'
                         )
                         AND EXISTS (
                             SELECT 1
                             FROM pg_constraint AS identity_constraint
                             WHERE identity_constraint.conrelid =
                                   to_regclass('public.federated_identities')
                               AND identity_constraint.conname =
                                   'uq_federated_identity_subject'
                               AND identity_constraint.contype = 'u'
                         )
                         AND EXISTS (
                             SELECT 1
                             FROM pg_constraint AS identity_constraint
                             WHERE identity_constraint.conrelid =
                                   to_regclass('public.federated_identities')
                               AND identity_constraint.conname =
                                   'uq_federated_identity_provider_user'
                               AND identity_constraint.contype = 'u'
                         )
                         AND to_regclass(
                             'public.ix_federated_identities_user_id'
                         ) IS NOT NULL
                     )
                 )
                 AND NOT EXISTS (
                     SELECT 1
                     FROM pg_constraint AS constraint_record
                     JOIN pg_class AS constrained_table
                       ON constrained_table.oid = constraint_record.conrelid
                     JOIN pg_namespace AS constrained_schema
                       ON constrained_schema.oid = constrained_table.relnamespace
                     WHERE constrained_schema.nspname = 'public'
                       AND constraint_record.contype IN ('c', 'f')
                       AND NOT constraint_record.convalidated
                 )
            THEN 'ok' ELSE 'failed' END
FROM required_tables;
""".strip()

MIGRATION_STATE_SQL = """
SELECT CASE
    WHEN to_regclass('public.alembic_version') IS NULL
     AND to_regclass('public.federated_identities') IS NULL
        THEN 'pre_alembic'
    WHEN to_regclass('public.alembic_version') IS NOT NULL
     AND to_regclass('public.federated_identities') IS NOT NULL
        THEN 'versioned'
    ELSE 'mixed'
END;
""".strip()

CORE_DATA_INTEGRITY_SQL = """
SELECT CASE WHEN
    (SELECT COUNT(*) FROM users) >= 0
    AND (SELECT COUNT(*) FROM password_resets) >= 0
    AND (SELECT COUNT(*) FROM push_subscriptions) >= 0
    AND (SELECT COUNT(*) FROM teachers) >= 0
    AND (SELECT COUNT(*) FROM user_settings) >= 0
    AND (SELECT COUNT(*) FROM classes) >= 0
    AND (SELECT COUNT(*) FROM assignments) >= 0
    AND (SELECT COUNT(*) FROM blogs) >= 0
    AND (SELECT COUNT(*) FROM class_enrollments) >= 0
    AND (SELECT COUNT(*) FROM assignment_drafts) >= 0
    AND (SELECT COUNT(*) FROM assignment_reminder_notifications) >= 0
    AND (SELECT COUNT(*) FROM assignment_submissions) >= 0
    AND (SELECT COUNT(*) FROM comments) >= 0
    AND (SELECT COUNT(*) FROM post_likes) >= 0
    AND (SELECT COUNT(*) FROM saved_posts) >= 0
    AND (SELECT COUNT(*) FROM assignment_submission_replies) >= 0
    AND (SELECT COUNT(*) FROM comment_likes) >= 0
    AND NOT EXISTS (
        SELECT 1
        FROM blogs AS blog
        LEFT JOIN users AS owner ON owner.id = blog.owner_id
        LEFT JOIN classes AS class_record ON class_record.id = blog.class_id
        WHERE owner.id IS NULL OR class_record.id IS NULL
    )
    AND NOT EXISTS (
        SELECT 1
        FROM class_enrollments AS enrollment
        LEFT JOIN users AS student ON student.id = enrollment.student_id
        LEFT JOIN classes AS class_record ON class_record.id = enrollment.class_id
        WHERE student.id IS NULL OR class_record.id IS NULL
    )
THEN 'ok' ELSE 'failed' END;
""".strip()

IDENTITY_DATA_INTEGRITY_SQL = """
SELECT CASE WHEN
    (SELECT COUNT(*) FROM federated_identities) >= 0
    AND NOT EXISTS (
        SELECT 1
        FROM federated_identities AS identity
        LEFT JOIN users AS identity_user ON identity_user.id = identity.user_id
        WHERE identity_user.id IS NULL
           OR identity.provider IS NULL
           OR identity.provider NOT IN ('google', 'microsoft')
           OR identity.issuer IS NULL
           OR BTRIM(identity.issuer) = ''
           OR identity.subject IS NULL
           OR BTRIM(identity.subject) = ''
    )
    AND NOT EXISTS (
        SELECT 1
        FROM federated_identities
        GROUP BY provider, issuer, subject
        HAVING COUNT(*) > 1
    )
    AND NOT EXISTS (
        SELECT 1
        FROM federated_identities
        GROUP BY provider, user_id
        HAVING COUNT(*) > 1
    )
THEN 'ok:' || (SELECT COUNT(*) FROM federated_identities)::text
ELSE 'failed' END;
""".strip()


@dataclass(frozen=True)
class RestoreVerificationResult:
    target_database: str
    migration_state: str
    alembic_revision: str | None
    federated_identity_count: int | None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as backup_file:
        for chunk in iter(lambda: backup_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    manifest_object: dict[str, object] = {}
    for key, value in pairs:
        if key in manifest_object:
            raise ValueError("duplicate manifest key")
        manifest_object[key] = value
    return manifest_object


def _valid_utc_timestamp(value: object) -> bool:
    if not isinstance(value, str) or not UTC_TIMESTAMP.fullmatch(value):
        return False
    try:
        parsed = datetime.fromisoformat(f"{value[:-1]}+00:00")
    except ValueError:
        return False
    return parsed.tzinfo == UTC


def _require_private_custody(path: Path) -> None:
    """Require restore inputs to be owned and accessible only by this operator."""

    if os.name != "posix":
        return
    try:
        if not path.is_absolute() or path.resolve(strict=True) != path:
            raise ValueError
        metadata = path.stat(follow_symlinks=False)
    except (OSError, ValueError) as exc:
        raise PostgresOperatorError(
            "Backup input custody could not be verified"
        ) from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_mode & 0o077
    ):
        raise PostgresOperatorError(
            "Backup archive and manifest custody must be owner-only"
        )


def _load_and_verify_manifest(archive: Path, manifest: Path) -> None:
    if archive.parent != manifest.parent:
        raise PostgresOperatorError(
            "Backup archive and manifest must share one private staging directory"
        )
    validate_private_operator_directory(
        archive.parent, purpose="restore staging directory"
    )
    if archive.is_symlink() or not archive.is_file():
        raise PostgresOperatorError("The backup archive must be a regular file")
    if manifest.is_symlink() or not manifest.is_file():
        raise PostgresOperatorError("The backup manifest must be a regular file")
    _require_private_custody(archive)
    _require_private_custody(manifest)
    if manifest.stat().st_size > MAX_MANIFEST_BYTES:
        raise PostgresOperatorError("The backup manifest is malformed")
    try:
        payload = json.loads(
            manifest.read_text(encoding="utf-8"),
            object_pairs_hook=_manifest_object,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PostgresOperatorError("The backup manifest is malformed") from exc
    if not isinstance(payload, dict) or set(payload) != MANIFEST_KEYS:
        raise PostgresOperatorError("The backup manifest is malformed")

    archive_name = payload.get("archive")
    created_at = payload.get("created_at")
    manifest_format = payload.get("format")
    checksum = payload.get("sha256")
    size_bytes = payload.get("size_bytes")
    if (
        not isinstance(archive_name, str)
        or Path(archive_name).name != archive_name
        or archive_name != archive.name
        or not _valid_utc_timestamp(created_at)
        or manifest_format != MANIFEST_FORMAT
        or not isinstance(checksum, str)
        or not SHA256.fullmatch(checksum)
        or type(size_bytes) is not int
        or size_bytes < 5
    ):
        raise PostgresOperatorError("The backup manifest is malformed")
    try:
        actual_size = archive.stat().st_size
        with archive.open("rb") as backup_file:
            magic = backup_file.read(5)
        actual_checksum = _sha256(archive)
    except OSError as exc:
        raise PostgresOperatorError("The backup archive could not be verified") from exc
    if magic != b"PGDMP":
        raise PostgresOperatorError("The backup archive is not custom-format")
    if actual_size != size_bytes or not hmac.compare_digest(actual_checksum, checksum):
        raise PostgresOperatorError("The backup checksum does not match its manifest")


def _run(
    command: list[str],
    *,
    environment: dict[str, str],
    runner: CommandRunner,
    capture_stdout: bool = False,
) -> subprocess.CompletedProcess[str]:
    try:
        return runner(
            command,
            env=environment,
            check=False,
            shell=False,
            stdout=subprocess.PIPE if capture_stdout else subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
    except OSError as exc:
        raise PostgresOperatorError(
            "A required PostgreSQL operator command could not start"
        ) from exc


def _psql_command(
    sql: str,
    *,
    variables: Mapping[str, str] | None = None,
) -> list[str]:
    command = [
        postgres_executable("psql"),
        "--no-psqlrc",
        "--no-password",
        "--tuples-only",
        "--no-align",
        "--set=ON_ERROR_STOP=1",
    ]
    for name, value in sorted((variables or {}).items()):
        if not PSQL_VARIABLE_NAME.fullmatch(name):
            raise PostgresOperatorError("The psql variable name is invalid")
        command.append(f"--set={name}={value}")
    command.extend(["--command", sql])
    return command


def _require_success(
    result: subprocess.CompletedProcess[str],
    operator_message: str,
) -> None:
    if result.returncode != 0:
        raise PostgresOperatorError(operator_message)


def check_alembic_schema_drift(
    connection: PostgresConnection,
    target_database: str,
) -> None:
    """Compare the target schema to model metadata without exposing DB details."""

    from alembic import command
    from alembic.config import Config

    backend_root = Path(__file__).resolve().parents[2] / "litblogs"
    query = {
        "connect_timeout": "10",
        "sslmode": connection.sslmode,
    }
    if connection.sslrootcert is not None:
        query["sslrootcert"] = connection.sslrootcert
    if connection.sslcert is not None:
        query["sslcert"] = connection.sslcert
    if connection.sslkey is not None:
        query["sslkey"] = connection.sslkey
    database_url = URL.create(
        "postgresql+psycopg2",
        username=connection.user,
        password=connection.password,
        host=connection.host,
        port=connection.port,
        database=target_database,
        query=query,
    )
    engine = create_engine(database_url, poolclass=NullPool)
    migration_output = io.StringIO()
    config = Config(stdout=migration_output, output_buffer=migration_output)
    config.set_main_option("script_location", str(backend_root / "migrations"))
    config.set_main_option("prepend_sys_path", str(backend_root))
    try:
        with engine.connect() as database_connection:
            config.attributes["connection"] = database_connection
            with redirect_stdout(migration_output), redirect_stderr(migration_output):
                command.check(config)
    except Exception:
        raise PostgresOperatorError(
            "The restored database failed the Alembic schema drift check"
        ) from None
    finally:
        engine.dispose()


def _verify_database_integrity(
    target: str,
    connection: PostgresConnection,
    *,
    runner: CommandRunner,
    require_current_head: bool,
    drift_checker: DriftChecker,
    expected_federated_identities: int | None = None,
) -> RestoreVerificationResult:
    target_environment = build_pg_environment(connection, database=target)
    schema_check = _run(
        _psql_command(SCHEMA_INTEGRITY_SQL),
        environment=target_environment,
        runner=runner,
        capture_stdout=True,
    )
    _require_success(schema_check, "Post-restore schema integrity checks failed")
    if (schema_check.stdout or "").strip() != "ok":
        raise PostgresOperatorError("Post-restore schema integrity checks failed")

    state_check = _run(
        _psql_command(MIGRATION_STATE_SQL),
        environment=target_environment,
        runner=runner,
        capture_stdout=True,
    )
    _require_success(state_check, "Post-restore migration state check failed")
    database_state = (state_check.stdout or "").strip()
    if database_state == "mixed":
        raise PostgresOperatorError(
            "Post-restore migration state is mixed or partially applied"
        )
    if database_state not in {"pre_alembic", "versioned"}:
        raise PostgresOperatorError(
            "Post-restore migration state could not be classified"
        )
    if database_state == "pre_alembic" and require_current_head:
        raise PostgresOperatorError(
            "The verification database is not at the current head"
        )

    revision: str | None = None
    if database_state == "versioned":
        revision_check = _run(
            _psql_command("SELECT version_num FROM alembic_version;"),
            environment=target_environment,
            runner=runner,
            capture_stdout=True,
        )
        _require_success(
            revision_check,
            "Post-restore migration ledger check failed",
        )
        revision = (revision_check.stdout or "").strip()
        if revision != EXPECTED_ALEMBIC_HEAD:
            raise PostgresOperatorError(
                "The verification database is not at the current head"
            )

    data_check = _run(
        _psql_command(CORE_DATA_INTEGRITY_SQL),
        environment=target_environment,
        runner=runner,
        capture_stdout=True,
    )
    _require_success(data_check, "Post-restore data integrity checks failed")
    if (data_check.stdout or "").strip() != "ok":
        raise PostgresOperatorError("Post-restore data integrity checks failed")

    identity_count: int | None = None
    if database_state == "versioned":
        identity_check = _run(
            _psql_command(IDENTITY_DATA_INTEGRITY_SQL),
            environment=target_environment,
            runner=runner,
            capture_stdout=True,
        )
        _require_success(
            identity_check,
            "Post-restore federated identity integrity checks failed",
        )
        identity_result = IDENTITY_RESULT.fullmatch(
            (identity_check.stdout or "").strip()
        )
        if identity_result is None:
            raise PostgresOperatorError(
                "Post-restore federated identity integrity checks failed"
            )
        identity_count = int(identity_result.group(1))
        if (
            expected_federated_identities is not None
            and identity_count != expected_federated_identities
        ):
            raise PostgresOperatorError(
                "Federated identity mappings do not match the approved inventory"
            )
        try:
            drift_checker(connection, target)
        except Exception:
            raise PostgresOperatorError(
                "The restored database failed the Alembic schema drift check"
            ) from None

    return RestoreVerificationResult(
        target_database=target,
        migration_state=(
            "pre_alembic" if database_state == "pre_alembic" else "current_head"
        ),
        alembic_revision=revision,
        federated_identity_count=identity_count,
    )


def restore_and_verify(
    archive_path: str | Path,
    manifest_path: str | Path,
    target_database: str,
    *,
    confirmation: str,
    database_url: str,
    runner: CommandRunner = subprocess.run,
    drift_checker: DriftChecker = check_alembic_schema_drift,
    tls_custody_validator=None,
) -> RestoreVerificationResult:
    """Restore to a newly created synthetic database and verify core integrity."""

    target = validate_restore_database_name(target_database)
    if not hmac.compare_digest(confirmation, target):
        raise PostgresOperatorError(
            "The restore confirmation must exactly match the target"
        )
    archive = Path(archive_path)
    manifest = Path(manifest_path)
    _load_and_verify_manifest(archive, manifest)
    connection = parse_postgres_url(database_url)
    (tls_custody_validator or validate_postgres_tls_custody)(connection)

    source_environment = build_pg_environment(connection)
    tool_environment = {
        key: value
        for key, value in source_environment.items()
        if not key.startswith("PG")
    }
    archive_check = _run(
        [postgres_executable("pg_restore"), "--list", str(archive)],
        environment=tool_environment,
        runner=runner,
    )
    _require_success(archive_check, "The backup archive failed structural validation")

    maintenance_environment = build_pg_environment(connection, database="postgres")
    existence_sql = (
        "SELECT CASE WHEN EXISTS (SELECT 1 FROM pg_database WHERE datname = "
        ":'target_database') THEN 'exists' ELSE 'absent' END;"
    )
    existence = _run(
        _psql_command(existence_sql, variables={"target_database": target}),
        environment=maintenance_environment,
        runner=runner,
        capture_stdout=True,
    )
    _require_success(existence, "The verification database existence check failed")
    if (existence.stdout or "").strip() != "absent":
        if (existence.stdout or "").strip() == "exists":
            raise PostgresOperatorError(
                "The verification database already exists; refusing restore"
            )
        raise PostgresOperatorError(
            "The verification database existence check was inconclusive"
        )

    creation = _run(
        [
            postgres_executable("createdb"),
            "--maintenance-db=postgres",
            "--no-password",
            "--encoding=UTF8",
            "--template=template0",
            target,
        ],
        environment=maintenance_environment,
        runner=runner,
    )
    _require_success(
        creation,
        "The verification database could not be created; no database was dropped",
    )

    access_lockdown = _run(
        _psql_command(
            'REVOKE CONNECT, TEMPORARY ON DATABASE :"target_database" FROM PUBLIC;',
            variables={"target_database": target},
        ),
        environment=maintenance_environment,
        runner=runner,
    )
    _require_success(
        access_lockdown,
        "The verification database could not be isolated; it was retained and was not dropped",
    )

    # Recheck owner-only custody, manifest binding, and the full archive hash
    # immediately before pg_restore. The mode-0700 staging directory prevents
    # another identity from swapping a verified pathname between checks.
    _load_and_verify_manifest(archive, manifest)
    target_environment = build_pg_environment(connection, database=target)
    restoration = _run(
        [
            postgres_executable("pg_restore"),
            "--exit-on-error",
            "--single-transaction",
            "--no-owner",
            "--no-acl",
            "--no-password",
            "--dbname",
            target,
            str(archive),
        ],
        environment=target_environment,
        runner=runner,
    )
    _require_success(
        restoration,
        "Restore failed; the verification database was retained and was not dropped",
    )

    return _verify_database_integrity(
        target,
        connection,
        runner=runner,
        require_current_head=False,
        drift_checker=drift_checker,
    )


def verify_existing_database(
    target_database: str,
    *,
    confirmation: str,
    expected_federated_identities: int,
    database_url: str,
    runner: CommandRunner = subprocess.run,
    drift_checker: DriftChecker = check_alembic_schema_drift,
    tls_custody_validator=None,
) -> RestoreVerificationResult:
    """Read only checks for a migrated synthetic verification database."""

    target = validate_restore_database_name(target_database)
    if not hmac.compare_digest(confirmation, target):
        raise PostgresOperatorError(
            "The verification confirmation must exactly match the target"
        )
    if (
        type(expected_federated_identities) is not int
        or expected_federated_identities < 0
    ):
        raise PostgresOperatorError(
            "The approved federated identity inventory count is invalid"
        )

    connection = parse_postgres_url(database_url)
    (tls_custody_validator or validate_postgres_tls_custody)(connection)
    maintenance_environment = build_pg_environment(connection, database="postgres")
    existence_sql = (
        "SELECT CASE WHEN EXISTS (SELECT 1 FROM pg_database WHERE datname = "
        ":'target_database') THEN 'exists' ELSE 'absent' END;"
    )
    existence = _run(
        _psql_command(existence_sql, variables={"target_database": target}),
        environment=maintenance_environment,
        runner=runner,
        capture_stdout=True,
    )
    _require_success(existence, "The verification database existence check failed")
    existence_status = (existence.stdout or "").strip()
    if existence_status != "exists":
        if existence_status == "absent":
            raise PostgresOperatorError(
                "The synthetic verification database does not exist"
            )
        raise PostgresOperatorError(
            "The verification database existence check was inconclusive"
        )

    return _verify_database_integrity(
        target,
        connection,
        runner=runner,
        require_current_head=True,
        drift_checker=drift_checker,
        expected_federated_identities=expected_federated_identities,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Restore a LitBlogs backup into a new synthetic verification database."
    )
    parser.add_argument("--archive")
    parser.add_argument("--manifest")
    parser.add_argument("--target-database", required=True)
    parser.add_argument(
        "--confirm-target",
        required=True,
        help="Repeat the exact synthetic target database name.",
    )
    parser.add_argument(
        "--verify-existing",
        action="store_true",
        help="Run read-only post-migration checks against an existing synthetic database.",
    )
    parser.add_argument(
        "--expected-federated-identities",
        type=int,
        help="Approved inventory count; required only with --verify-existing.",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    runner: CommandRunner = subprocess.run,
    client_validator=None,
    drift_checker: DriftChecker = check_alembic_schema_drift,
    tls_custody_validator=None,
) -> int:
    args = _parser().parse_args(argv)
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print(
            "ERROR: DATABASE_URL is required in the operator environment",
            file=sys.stderr,
        )
        return 2
    if args.verify_existing:
        if (
            args.archive is not None
            or args.manifest is not None
            or args.expected_federated_identities is None
        ):
            print(
                "ERROR: verify-existing requires only the approved identity count",
                file=sys.stderr,
            )
            return 2
    elif (
        args.archive is None
        or args.manifest is None
        or args.expected_federated_identities is not None
    ):
        print(
            "ERROR: restore requires an archive and manifest",
            file=sys.stderr,
        )
        return 2
    try:
        (client_validator or validate_postgres_client_installation)()
        if args.verify_existing:
            result = verify_existing_database(
                args.target_database,
                confirmation=args.confirm_target,
                expected_federated_identities=args.expected_federated_identities,
                database_url=database_url,
                runner=runner,
                drift_checker=drift_checker,
                tls_custody_validator=tls_custody_validator,
            )
        else:
            result = restore_and_verify(
                args.archive,
                args.manifest,
                args.target_database,
                confirmation=args.confirm_target,
                database_url=database_url,
                runner=runner,
                drift_checker=drift_checker,
                tls_custody_validator=tls_custody_validator,
            )
    except PostgresOperatorError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if args.verify_existing:
        print("Existing synthetic database verification: current_head")
    else:
        print(f"Verified restore database: {result.target_database}")
        print(f"Migration state: {result.migration_state}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
