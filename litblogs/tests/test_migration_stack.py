from __future__ import annotations

import importlib.util
import io
import os
import runpy
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.engine import make_url

import database

BACKEND_DIR = Path(__file__).resolve().parents[1]
VERSIONS_DIR = BACKEND_DIR / "migrations" / "versions"
EXPECTED_REVISIONS = (
    "985a04df032a",
    "b7c41f0e2d19",
    "d4e4539c0418",
    "c5136f36e302",
    "f0684bf8ff2e",
    "b983b7aebe7b",
    "f1ad78b2035f",
)
EXPECTED_TABLES = (
    "assignment_drafts",
    "assignment_reminder_notifications",
    "assignment_submission_replies",
    "assignment_submissions",
    "assignments",
    "blogs",
    "browser_sessions",
    "class_enrollments",
    "classes",
    "comment_likes",
    "comments",
    "federated_identities",
    "operator_audit_events",
    "password_resets",
    "post_likes",
    "push_subscriptions",
    "saved_posts",
    "teacher_invitations",
    "teachers",
    "upload_assets",
    "user_settings",
    "users",
)

EXPECTED_PRODUCTION_MIGRATOR_BOUNDARY = (
    "litblogs_migrator",
    "litblogs_migrator",
    "litblogs",
    False,
    False,
    False,
    False,
    True,
    False,
    False,
    True,
    "litblogs_migrator",
    True,
    True,
    True,
    True,
)


class _MigrationEnvironmentConfig:
    config_file_name = None
    config_ini_section = "alembic"

    def __init__(self, supplied_connection=None):
        self.attributes = {}
        if supplied_connection is not None:
            self.attributes["connection"] = supplied_connection
        self.options = {}

    def set_main_option(self, name, value):
        self.options[name] = value

    def get_main_option(self, name):
        return self.options.get(name)

    def get_section(self, _name, default):
        return {**default, **self.options}


class _MigrationBoundaryResult:
    def __init__(self, record):
        self.record = record

    def one(self):
        return self.record


class _MigrationBoundaryConnection:
    def __init__(self, calls, record=None, execute_error=None):
        self.calls = calls
        self.record = record
        self.execute_error = execute_error

    def execute(self, statement):
        self.calls.append(("verify", str(statement).lower()))
        if self.execute_error is not None:
            raise self.execute_error
        return _MigrationBoundaryResult(self.record)

    def rollback(self):
        self.calls.append(("rollback", None))


class _MigrationBoundaryEngine:
    def __init__(self, calls, connection):
        self.calls = calls
        self.connection = connection

    @contextmanager
    def connect(self):
        self.calls.append(("connect", None))
        yield self.connection
        self.calls.append(("disconnect", None))


def _run_unsupplied_migration_environment(
    monkeypatch,
    *,
    record=EXPECTED_PRODUCTION_MIGRATOR_BOUNDARY,
    execute_error=None,
    migration_url=(
        "postgresql+psycopg2://litblogs_migrator:correct-horse-battery-staple@"
        "db.litblogs.com/litblogs?sslmode=verify-full&"
        "sslrootcert=/etc/litblogs/postgres-root-ca.pem"
    ),
    app_env="production",
    test_database_url=None,
):
    import alembic.context as alembic_context

    calls = []
    fake_config = _MigrationEnvironmentConfig()
    connection = _MigrationBoundaryConnection(
        calls,
        record=record,
        execute_error=execute_error,
    )
    engine = _MigrationBoundaryEngine(calls, connection)

    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setenv("LITBLOGS_MIGRATION_DATABASE_URL", migration_url)
    if app_env == "test":
        monkeypatch.setenv(
            "TEST_DATABASE_URL",
            test_database_url or migration_url,
        )
    elif app_env == "development":
        monkeypatch.setenv("DATABASE_URL", migration_url)
    monkeypatch.setattr(alembic_context, "config", fake_config, raising=False)
    monkeypatch.setattr(alembic_context, "is_offline_mode", lambda: False)
    monkeypatch.setattr(
        alembic_context,
        "configure",
        lambda **_kwargs: calls.append(("configure", None)),
    )

    @contextmanager
    def migration_transaction():
        calls.append(("transaction", None))
        yield

    monkeypatch.setattr(
        alembic_context,
        "begin_transaction",
        migration_transaction,
    )
    monkeypatch.setattr(
        alembic_context,
        "run_migrations",
        lambda: calls.append(("migrate", None)),
    )
    monkeypatch.setattr(sa, "engine_from_config", lambda *_args, **_kwargs: engine)

    runpy.run_path(str(BACKEND_DIR / "migrations" / "env.py"))
    return calls


def _alembic_config(connection=None) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    if connection is not None:
        config.attributes["connection"] = connection
    return config


def _upgrade(engine: sa.Engine, revision: str = "head") -> None:
    with engine.begin() as connection:
        command.upgrade(_alembic_config(connection), revision)


def _downgrade(engine: sa.Engine, revision: str = "base") -> None:
    with engine.begin() as connection:
        command.downgrade(_alembic_config(connection), revision)


def _stamp(engine: sa.Engine, revision: str) -> None:
    with engine.begin() as connection:
        command.stamp(_alembic_config(connection), revision)


def _current_revision(engine: sa.Engine) -> str:
    with engine.connect() as connection:
        return connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one()


def test_reviewed_revision_chain_is_linear_and_has_one_head():
    scripts = ScriptDirectory.from_config(_alembic_config())
    revisions = tuple(revision.revision for revision in reversed(tuple(scripts.walk_revisions("base", "heads"))))

    assert revisions == EXPECTED_REVISIONS
    assert scripts.get_heads() == [EXPECTED_REVISIONS[-1]]


def test_semantic_sql_references_are_not_parallel_migration_paths():
    version_source = "\n".join(path.read_text(encoding="utf-8") for path in sorted(VERSIONS_DIR.glob("*.py")))

    assert "0002_add_authorization_constraints.sql" not in version_source
    assert "0003_add_identity_controls.sql" not in version_source
    assert "0004_assignment_draft_revisions.sql" not in version_source
    assert "0005_upload_asset_registry.sql" not in version_source
    assert ".read_text(" not in version_source
    assert "open(" not in version_source


def test_final_acl_revision_uses_explicit_runtime_grants_and_operator_boundaries():
    source = (VERSIONS_DIR / "f1ad78b2035f_exact_runtime_acl.py").read_text(encoding="utf-8")
    normalized = " ".join(source.lower().split())

    assert "grant select, insert, update, delete on all tables" not in normalized
    assert "grant usage, select on all sequences" not in normalized
    assert "grant create on schema public to litblogs_runtime" not in normalized
    assert "litblog_identity_owner" in source
    assert "litblog_account_operator" in source
    assert "litblog_invitation_operator" in source
    assert "operator_set_account_status" in source
    assert "operator_create_teacher_invitation" in source
    assert "operator_revoke_teacher_invitation" in source
    assert "pg_catalog.pg_shdepend" in source
    assert "REASSIGN OWNED" not in source
    assert "ALTER FUNCTION {function_signature} OWNER TO CURRENT_USER" in source
    assert "WITH ADMIN FALSE, INHERIT TRUE, SET TRUE" in source
    assert "ALTER DEFAULT PRIVILEGES FOR ROLE litblogs_migrator" in source
    assert "REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC" in source
    assert (
        "ALTER DEFAULT PRIVILEGES FOR ROLE litblogs_migrator IN SCHEMA public"
        not in source
    )
    for table_name in EXPECTED_TABLES:
        assert table_name in source


def test_final_acl_publishes_the_exact_pre_upgrade_role_contract():
    path = VERSIONS_DIR / "f1ad78b2035f_exact_runtime_acl.py"
    spec = importlib.util.spec_from_file_location("reviewed_acl_revision", path)
    assert spec is not None and spec.loader is not None
    revision_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision_module)

    login_attributes = "LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
    owner_attributes = "NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
    assert revision_module.REQUIRED_ROLE_ATTRIBUTES == {
        "litblogs_runtime": login_attributes,
        "litblog_identity_owner": owner_attributes,
        "litblog_account_operator": login_attributes,
        "litblog_invitation_operator": login_attributes,
    }
    assert revision_module.TEMPORARY_IDENTITY_OWNER_MEMBERSHIP == (
        "litblogs_migrator",
        "litblog_identity_owner",
    )


def test_identity_draft_and_upload_revisions_preserve_security_invariants():
    identity = (VERSIONS_DIR / "c5136f36e302_identity_controls.py").read_text(
        encoding="utf-8"
    )
    drafts = (
        VERSIONS_DIR / "f0684bf8ff2e_assignment_draft_revisions.py"
    ).read_text(encoding="utf-8")
    uploads = (VERSIONS_DIR / "b983b7aebe7b_upload_asset_registry.py").read_text(
        encoding="utf-8"
    )

    assert identity.count("SECURITY DEFINER") == 3
    assert identity.count("SET search_path = pg_catalog, pg_temp") == 3
    for field_name in (
        "disabled_at",
        "delivery_claim_digest",
        "browser_sessions",
        "teacher_invitations",
        "operator_audit_events",
    ):
        assert field_name in identity
    assert "revision >= 0 AND revision <= 2147483647" in drafts
    assert 'nullable=False' in drafts
    for constraint_name in (
        "fk_upload_assets_owner_user",
        "fk_upload_assets_blog",
        "ck_upload_assets_storage_key_prefix",
        "ck_upload_assets_storage_key_format",
        "ck_upload_assets_state_shape",
        "uq_upload_assets_active_profile_purpose",
    ):
        assert constraint_name in uploads


def test_sqlite_upgrade_matches_models_and_has_no_autogenerate_drift(tmp_path):
    from base import Base

    engine = sa.create_engine(f"sqlite:///{(tmp_path / 'migration-stack.db').as_posix()}")
    try:
        _upgrade(engine)

        tables = set(sa.inspect(engine).get_table_names())
        assert tables == set(Base.metadata.tables) | {"alembic_version"}
        with engine.connect() as connection:
            command.check(_alembic_config(connection))

        _downgrade(engine)
        assert set(sa.inspect(engine).get_table_names()) == {"alembic_version"}
    finally:
        engine.dispose()


def test_offline_sql_generation_fails_before_emitting_partial_migration_sql(
    monkeypatch,
):
    output = io.StringIO()
    config = _alembic_config()
    config.output_buffer = output
    monkeypatch.setenv(
        "LITBLOGS_MIGRATION_DATABASE_URL",
        "postgresql://litblogs_migrator:correct-horse-battery-staple@"
        "db.litblogs.com/litblogs?sslmode=verify-full&"
        "sslrootcert=/etc/litblogs/postgres-root-ca.pem",
    )

    with pytest.raises(
        RuntimeError,
        match="Offline SQL generation is unsupported; migrations require live database preflights",
    ):
        command.upgrade(config, "head", sql=True)

    assert output.getvalue() == ""


def test_production_migration_verifies_exact_migrator_before_configuration(
    monkeypatch,
):
    calls = _run_unsupplied_migration_environment(monkeypatch)

    call_names = [name for name, _value in calls]
    assert call_names == [
        "connect",
        "verify",
        "rollback",
        "configure",
        "transaction",
        "migrate",
        "disconnect",
    ]
    verification_sql = calls[1][1]
    for required_fragment in (
        "session_user",
        "current_user",
        "current_database()",
        "pg_catalog.pg_roles",
        "pg_catalog.pg_auth_members",
        "pg_catalog.pg_namespace",
        "admin_option",
        "inherit_option",
        "set_option",
        "litblog_identity_owner",
        "pg_catalog.has_schema_privilege",
        "pg_catalog.current_schemas(false)",
    ):
        assert required_fragment in verification_sql


@pytest.mark.parametrize(
    "field_index",
    range(len(EXPECTED_PRODUCTION_MIGRATOR_BOUNDARY)),
)
def test_production_migration_rejects_every_boundary_mismatch_before_ddl(
    monkeypatch,
    field_index,
):
    mismatched = list(EXPECTED_PRODUCTION_MIGRATOR_BOUNDARY)
    original = mismatched[field_index]
    if isinstance(original, bool):
        mismatched[field_index] = not original
    else:
        mismatched[field_index] = f"unexpected-{original}"

    with pytest.raises(
        RuntimeError,
        match="Database migration privilege boundary mismatch",
    ):
        _run_unsupplied_migration_environment(
            monkeypatch,
            record=tuple(mismatched),
        )


def test_production_migration_sanitizes_catalog_verification_errors(
    monkeypatch,
):
    with pytest.raises(
        RuntimeError,
        match="^Database migration privilege boundary mismatch$",
    ) as exc_info:
        _run_unsupplied_migration_environment(
            monkeypatch,
            execute_error=RuntimeError("driver secret detail"),
        )

    assert exc_info.value.__cause__ is None
    assert "driver secret detail" not in str(exc_info.value)


def test_local_development_migration_does_not_require_production_role_catalogs(
    monkeypatch,
):
    calls = _run_unsupplied_migration_environment(
        monkeypatch,
        app_env="development",
        migration_url="sqlite:///migration-boundary.sqlite3",
        execute_error=AssertionError("production verifier must not execute"),
    )

    assert [name for name, _value in calls] == [
        "connect",
        "configure",
        "transaction",
        "migrate",
        "disconnect",
    ]


def test_isolated_test_migration_verifies_equal_migrator_url_before_ddl(
    monkeypatch,
):
    migration_url = (
        "postgresql://litblogs_migrator:ci-only-migrator-password@"
        "localhost:5432/litblog_test_migration_boundary"
    )
    expected_boundary = list(EXPECTED_PRODUCTION_MIGRATOR_BOUNDARY)
    expected_boundary[2] = "litblog_test_migration_boundary"
    calls = _run_unsupplied_migration_environment(
        monkeypatch,
        app_env="test",
        test_database_url=migration_url,
        migration_url=migration_url,
        record=tuple(expected_boundary),
    )

    assert [name for name, _value in calls] == [
        "connect",
        "verify",
        "rollback",
        "configure",
        "transaction",
        "migrate",
        "disconnect",
    ]


def test_isolated_test_migration_rejects_distinct_admin_and_migrator_urls(
    monkeypatch,
):
    with pytest.raises(
        RuntimeError,
        match="The migration database URL is missing or invalid",
    ):
        _run_unsupplied_migration_environment(
            monkeypatch,
            app_env="test",
            test_database_url=(
                "postgresql://litblog_ci:ci-only-admin-password@localhost:5432/"
                "litblog_test_migration_boundary"
            ),
            migration_url=(
                "postgresql://litblogs_migrator:ci-only-migrator-password@"
                "localhost:5432/litblog_test_migration_boundary"
            ),
        )


def test_d4_sqlite_preflight_is_retry_safe_for_duplicate_password_resets(tmp_path):
    engine = sa.create_engine(f"sqlite:///{(tmp_path / 'd4-retry.db').as_posix()}")
    try:
        _upgrade(engine, "b7c41f0e2d19")
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "INSERT INTO users (id, username, email, password, role) "
                "VALUES (1, 'student', 'student@example.com', 'hash', 'STUDENT')"
            )
            connection.exec_driver_sql(
                "INSERT INTO password_resets "
                "(id, user_id, token, expires_at, used) VALUES "
                "(1, 1, :first_token, '2099-01-01 00:00:00', 0), "
                "(2, 1, :second_token, '2099-01-01 00:00:00', 0)",
                {
                    "first_token": "a" * 64,
                    "second_token": "b" * 64,
                },
            )

        with pytest.raises(RuntimeError, match="authorization constraint preflight"):
            _upgrade(engine, "d4e4539c0418")

        assert _current_revision(engine) == "b7c41f0e2d19"
        inspector = sa.inspect(engine)
        assert "notes" not in {
            column["name"] for column in inspector.get_columns("class_enrollments")
        }
        assert {
            "delivery_status",
            "delivery_attempted_at",
        }.isdisjoint(
            column["name"] for column in inspector.get_columns("password_resets")
        )

        with engine.begin() as connection:
            connection.exec_driver_sql("DELETE FROM password_resets WHERE id = 2")
        _upgrade(engine, "d4e4539c0418")
        assert _current_revision(engine) == "d4e4539c0418"
    finally:
        engine.dispose()


def test_c513_sqlite_preflight_is_retry_safe_for_unmapped_teachers(tmp_path):
    engine = sa.create_engine(f"sqlite:///{(tmp_path / 'c513-retry.db').as_posix()}")
    try:
        _upgrade(engine, "d4e4539c0418")
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "INSERT INTO teachers (id, name, email, hashed_password, user_id) "
                "VALUES (1, 'Legacy Teacher', NULL, 'hash', NULL)"
            )

        with pytest.raises(RuntimeError, match="identity control preflight"):
            _upgrade(engine, "c5136f36e302")

        assert _current_revision(engine) == "d4e4539c0418"
        inspector = sa.inspect(engine)
        assert "disabled_at" not in {
            column["name"] for column in inspector.get_columns("users")
        }
        assert "browser_sessions" not in inspector.get_table_names()

        with engine.begin() as connection:
            connection.exec_driver_sql("DELETE FROM teachers WHERE id = 1")
        _upgrade(engine, "c5136f36e302")
        assert _current_revision(engine) == "c5136f36e302"
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("prior_revision", "target_revision", "create_marker", "remove_marker"),
    (
        (
            "b7c41f0e2d19",
            "d4e4539c0418",
            "ALTER TABLE class_enrollments ADD COLUMN notes TEXT",
            "ALTER TABLE class_enrollments DROP COLUMN notes",
        ),
        (
            "d4e4539c0418",
            "c5136f36e302",
            "ALTER TABLE users ADD COLUMN disabled_at DATETIME",
            "ALTER TABLE users DROP COLUMN disabled_at",
        ),
        (
            "c5136f36e302",
            "f0684bf8ff2e",
            "ALTER TABLE assignment_drafts "
            "ADD COLUMN revision INTEGER DEFAULT 0 NOT NULL",
            "ALTER TABLE assignment_drafts DROP COLUMN revision",
        ),
        (
            "f0684bf8ff2e",
            "b983b7aebe7b",
            "CREATE TABLE upload_assets (id INTEGER PRIMARY KEY NOT NULL)",
            "DROP TABLE upload_assets",
        ),
    ),
)
def test_sqlite_marker_only_adoption_is_rejected_and_repair_is_retryable(
    tmp_path,
    prior_revision,
    target_revision,
    create_marker,
    remove_marker,
):
    engine = sa.create_engine(
        f"sqlite:///{(tmp_path / f'partial-{target_revision}.db').as_posix()}"
    )
    try:
        _upgrade(engine, prior_revision)
        with engine.begin() as connection:
            connection.exec_driver_sql(create_marker)

        with pytest.raises(RuntimeError, match="partial SQLite schema"):
            _upgrade(engine, target_revision)
        assert _current_revision(engine) == prior_revision

        with engine.begin() as connection:
            connection.exec_driver_sql(remove_marker)
        _upgrade(engine, target_revision)
        assert _current_revision(engine) == target_revision
    finally:
        engine.dispose()


def test_populated_current_sqlite_adoption_runs_identity_data_transitions(tmp_path):
    from base import Base

    engine = sa.create_engine(
        f"sqlite:///{(tmp_path / 'populated-current-adoption.db').as_posix()}"
    )
    try:
        current_tables = [
            table
            for name, table in Base.metadata.tables.items()
            if name != "federated_identities"
        ]
        Base.metadata.create_all(bind=engine, tables=current_tables)
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "INSERT INTO users (id, username, email, password, role) "
                "VALUES (1, 'teacher', ' Teacher@Example.com ', 'hash', 'TEACHER')"
            )
            connection.exec_driver_sql(
                "INSERT INTO teachers (id, name, email, hashed_password, user_id) "
                "VALUES (1, 'Teacher', 'teacher@example.COM', 'hash', 1)"
            )
            connection.exec_driver_sql(
                "INSERT INTO password_resets "
                "(id, user_id, token, expires_at, used, delivery_status, "
                "delivery_claim_digest) VALUES "
                "(1, 1, :token, '2099-01-01 00:00:00', 0, 'PROCESSING', :claim)",
                {"token": "a" * 64, "claim": "b" * 64},
            )
        _stamp(engine, "985a04df032a")

        _upgrade(engine)

        with engine.connect() as connection:
            assert connection.exec_driver_sql(
                "SELECT email FROM users WHERE id = 1"
            ).scalar_one() == "teacher@example.com"
            teacher = connection.exec_driver_sql(
                "SELECT email, user_id FROM teachers WHERE id = 1"
            ).one()
            assert teacher == ("teacher@example.com", 1)
            reset = connection.exec_driver_sql(
                "SELECT token, expires_at, used, delivery_status, "
                "delivery_attempted_at, delivery_claim_digest "
                "FROM password_resets WHERE id = 1"
            ).one()
            assert reset.token is None
            assert reset.expires_at is None
            assert bool(reset.used) is True
            assert reset.delivery_status == "FAILED"
            assert reset.delivery_attempted_at is not None
            assert reset.delivery_claim_digest is None
    finally:
        engine.dispose()


@pytest.mark.parametrize("starting_revision", EXPECTED_REVISIONS[3:])
def test_invalidated_password_reset_secrets_block_downgrade_before_schema_changes(
    tmp_path,
    starting_revision,
):
    engine = sa.create_engine(
        f"sqlite:///{(tmp_path / f'irreversible-reset-{starting_revision}.db').as_posix()}"
    )
    try:
        _upgrade(engine, "d4e4539c0418")
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "INSERT INTO users (id, username, email, password, role) "
                "VALUES (1, 'student', 'student@example.com', 'hash', 'STUDENT')"
            )
            connection.exec_driver_sql(
                "INSERT INTO password_resets "
                "(id, user_id, token, expires_at, used, delivery_status) "
                "VALUES (1, 1, :token, '2099-01-01 00:00:00', 0, 'DELIVERED')",
                {"token": "a" * 64},
            )
        _upgrade(engine, starting_revision)
        inspector = sa.inspect(engine)
        tables_before = set(inspector.get_table_names())
        columns_before = {
            table_name: tuple(
                column["name"] for column in inspector.get_columns(table_name)
            )
            for table_name in tables_before
        }

        with pytest.raises(RuntimeError, match="irreversibly invalidated"):
            _downgrade(engine, "b7c41f0e2d19")

        assert _current_revision(engine) == starting_revision
        inspector = sa.inspect(engine)
        assert set(inspector.get_table_names()) == tables_before
        assert {
            table_name: tuple(
                column["name"] for column in inspector.get_columns(table_name)
            )
            for table_name in tables_before
        } == columns_before
    finally:
        engine.dispose()


def test_postgresql_upgrade_has_exact_schema_and_acl_when_available(
    database_guard,
    monkeypatch,
):
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url or make_url(database_url).get_backend_name() != "postgresql":
        pytest.skip("an explicitly guarded PostgreSQL test database is unavailable")

    admin_url = make_url(database_url)
    admin_engine = sa.create_engine(admin_url)
    database_guard(admin_engine)
    role_names = (
        "litblogs_runtime",
        "litblog_identity_owner",
        "litblog_account_operator",
        "litblog_invitation_operator",
        "litblogs_migrator",
    )
    role_attributes = {
        "litblogs_runtime": ("LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"),
        "litblog_identity_owner": ("NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"),
        "litblog_account_operator": ("LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"),
        "litblog_invitation_operator": (
            "LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
        ),
        "litblogs_migrator": ("LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"),
    }
    role_password = "integration-role-credential-8f341e927"
    created_roles: list[str] = []
    previous_public_owner: str | None = None
    public_owned_by_migrator = False
    migrator_engine: sa.Engine | None = None
    runtime_engine: sa.Engine | None = None
    try:
        with admin_engine.begin() as connection:
            is_superuser = connection.exec_driver_sql(
                "SELECT rolsuper FROM pg_roles WHERE rolname = CURRENT_USER"
            ).scalar_one()
            if not is_superuser:
                pytest.skip(
                    "the guarded PostgreSQL integration database requires a role-admin bootstrap connection"
                )
            existing_roles = {
                row[0]
                for row in connection.exec_driver_sql(
                    "SELECT rolname FROM pg_roles WHERE rolname IN ("
                    "'litblogs_runtime', 'litblog_identity_owner', "
                    "'litblog_account_operator', 'litblog_invitation_operator', "
                    "'litblogs_migrator')"
                )
            }
            if existing_roles:
                pytest.skip("the isolated PostgreSQL cluster already contains reviewed role names")
            previous_public_owner = connection.exec_driver_sql(
                "SELECT owner.rolname FROM pg_namespace AS namespace "
                "JOIN pg_roles AS owner ON owner.oid = namespace.nspowner "
                "WHERE namespace.nspname = 'public'"
            ).scalar_one()
            connection.exec_driver_sql(
                "DROP FUNCTION IF EXISTS public.operator_set_account_status(VARCHAR, BOOLEAN, VARCHAR, VARCHAR) CASCADE"
            )
            connection.exec_driver_sql(
                "DROP FUNCTION IF EXISTS public.operator_create_teacher_invitation("
                "VARCHAR, VARCHAR, TIMESTAMPTZ, VARCHAR, VARCHAR) CASCADE"
            )
            connection.exec_driver_sql(
                "DROP FUNCTION IF EXISTS public.operator_revoke_teacher_invitation(VARCHAR, VARCHAR, VARCHAR) CASCADE"
            )
            connection.exec_driver_sql("DROP TABLE IF EXISTS alembic_version CASCADE")
            for table in reversed(tuple(__import__("base").Base.metadata.sorted_tables)):
                connection.exec_driver_sql(f'DROP TABLE IF EXISTS "{table.name}" CASCADE')
            for role_name in role_names:
                password_clause = (
                    f" PASSWORD '{role_password}'"
                    if role_attributes[role_name].startswith("LOGIN")
                    else ""
                )
                connection.exec_driver_sql(
                    f"CREATE ROLE {role_name} {role_attributes[role_name]}{password_clause}"
                )
                created_roles.append(role_name)
            quoted_database = connection.dialect.identifier_preparer.quote(
                admin_url.database
            )
            connection.exec_driver_sql(
                f"REVOKE CONNECT, CREATE, TEMPORARY ON DATABASE {quoted_database} "
                "FROM PUBLIC"
            )
            connection.exec_driver_sql(
                f"GRANT CONNECT ON DATABASE {quoted_database} TO "
                "litblogs_runtime, litblogs_migrator, "
                "litblog_account_operator, litblog_invitation_operator"
            )
            connection.exec_driver_sql(
                "GRANT litblog_identity_owner TO litblogs_migrator "
                "WITH ADMIN TRUE, INHERIT FALSE, SET FALSE"
            )
            connection.exec_driver_sql(
                "ALTER SCHEMA public OWNER TO litblogs_migrator"
            )
            public_owned_by_migrator = True

        migrator_engine = sa.create_engine(
            admin_url.set(username="litblogs_migrator", password=role_password)
        )
        runtime_engine = sa.create_engine(
            admin_url.set(username="litblogs_runtime", password=role_password)
        )

        migrator_database_url = admin_url.set(
            username="litblogs_migrator",
            password=role_password,
        ).render_as_string(hide_password=False)
        with monkeypatch.context() as migration_environment:
            migration_environment.setenv("APP_ENV", "test")
            migration_environment.setenv(
                "TEST_DATABASE_URL",
                migrator_database_url,
            )
            migration_environment.setenv(
                "LITBLOGS_MIGRATION_DATABASE_URL",
                migrator_database_url,
            )
            with pytest.raises(
                RuntimeError,
                match="Database migration privilege boundary mismatch",
            ):
                command.current(_alembic_config(), check_heads=True)

        with admin_engine.begin() as connection:
            membership_options = connection.exec_driver_sql(
                "SELECT membership.admin_option, membership.inherit_option, "
                "membership.set_option "
                "FROM pg_auth_members AS membership "
                "JOIN pg_roles AS granted_role "
                "ON granted_role.oid = membership.roleid "
                "JOIN pg_roles AS member_role "
                "ON member_role.oid = membership.member "
                "WHERE granted_role.rolname = 'litblog_identity_owner' "
                "AND member_role.rolname = 'litblogs_migrator'"
            ).one()
            assert tuple(membership_options) == (True, False, False)
            connection.exec_driver_sql(
                "GRANT litblog_identity_owner TO litblogs_migrator "
                "WITH ADMIN FALSE, INHERIT TRUE, SET TRUE"
            )
            normalized_membership_options = connection.exec_driver_sql(
                "SELECT membership.admin_option, membership.inherit_option, "
                "membership.set_option "
                "FROM pg_auth_members AS membership "
                "JOIN pg_roles AS granted_role "
                "ON granted_role.oid = membership.roleid "
                "JOIN pg_roles AS member_role "
                "ON member_role.oid = membership.member "
                "WHERE granted_role.rolname = 'litblog_identity_owner' "
                "AND member_role.rolname = 'litblogs_migrator'"
            ).one()
            assert tuple(normalized_membership_options) == (False, True, True)

        with monkeypatch.context() as migration_environment:
            migration_environment.setenv("APP_ENV", "test")
            migration_environment.setenv(
                "TEST_DATABASE_URL",
                migrator_database_url,
            )
            migration_environment.setenv(
                "LITBLOGS_MIGRATION_DATABASE_URL",
                migrator_database_url,
            )
            command.upgrade(_alembic_config(), "head")
        with admin_engine.connect() as connection:
            assert (
                connection.exec_driver_sql(
                    "SELECT pg_catalog.to_regclass('public.users')::text"
                ).scalar_one()
                == "users"
            )
            assert (
                connection.exec_driver_sql(
                    "SELECT version_num FROM public.alembic_version"
                ).scalar_one()
                == EXPECTED_REVISIONS[-1]
            )
        with admin_engine.begin() as connection:
            connection.exec_driver_sql(
                "REVOKE litblog_identity_owner FROM litblogs_migrator"
            )

        admin_database_url = admin_url.render_as_string(hide_password=False)
        with monkeypatch.context() as migration_environment:
            migration_environment.setenv("APP_ENV", "test")
            migration_environment.setenv("TEST_DATABASE_URL", admin_database_url)
            migration_environment.setenv(
                "LITBLOGS_MIGRATION_DATABASE_URL",
                admin_database_url,
            )
            with pytest.raises(
                RuntimeError,
                match="Database migration privilege boundary mismatch",
            ):
                command.current(_alembic_config(), check_heads=True)

        with monkeypatch.context() as migration_environment:
            migration_environment.setenv("APP_ENV", "test")
            migration_environment.setenv(
                "TEST_DATABASE_URL",
                migrator_database_url,
            )
            migration_environment.setenv(
                "LITBLOGS_MIGRATION_DATABASE_URL",
                migrator_database_url,
            )
            command.current(_alembic_config(), check_heads=True)
            command.check(_alembic_config())
            cli_check = subprocess.run(
                [sys.executable, "-m", "alembic", "check"],
                cwd=BACKEND_DIR,
                env=os.environ.copy(),
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            assert cli_check.returncode == 0
            assert "No new upgrade operations detected." in cli_check.stdout

        database.check_database_readiness(runtime_engine)

        with migrator_engine.begin() as connection:
            connection.exec_driver_sql(
                "INSERT INTO public.users (username, email, password, role) VALUES "
                "('opclass-hyphen', 'identity-a@example.com', 'hash', 'STUDENT'), "
                "('opclass-underscore', 'identity_a@example.com', 'hash', 'STUDENT')"
            )
        with pytest.raises(sa.exc.IntegrityError):
            with migrator_engine.begin() as connection:
                connection.exec_driver_sql(
                    "INSERT INTO public.users (username, email, password, role) VALUES "
                    "('opclass-duplicate', 'identity-a@example.com', 'hash', 'STUDENT')"
                )

        with migrator_engine.connect() as connection:
            reflected_email_index = next(
                index
                for index in sa.inspect(connection).get_indexes("users")
                if index["name"] == "uq_users_email_normalized"
            )
            assert reflected_email_index["unique"] is True
            assert reflected_email_index["column_names"] == ["email"]
            assert reflected_email_index["dialect_options"]["postgresql_ops"] == {
                "email": "varchar_pattern_ops"
            }
            command.check(_alembic_config(connection))
            database.verify_database_schema(migrator_engine)
            current = connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
            assert current == EXPECTED_REVISIONS[-1]

        with admin_engine.connect() as connection:
            assert (
                connection.exec_driver_sql(
                    "SELECT has_schema_privilege('litblogs_runtime', 'public', 'CREATE')"
                ).scalar_one()
                is False
            )
            assert (
                connection.exec_driver_sql(
                    "SELECT has_table_privilege('litblogs_runtime', 'public.users', 'SELECT,INSERT,UPDATE,DELETE')"
                ).scalar_one()
                is True
            )
            assert (
                connection.exec_driver_sql(
                    "SELECT bool_and(has_column_privilege("
                    "'litblogs_runtime', 'public.teacher_invitations', "
                    "column_name, privilege_name)) "
                    "FROM (VALUES "
                    "('id', 'SELECT'), ('token_digest', 'SELECT'), "
                    "('email_digest', 'SELECT'), ('expires_at', 'SELECT'), "
                    "('consumed_at', 'SELECT'), ('revoked_at', 'SELECT'), "
                    "('consumed_at', 'UPDATE'), ('revoked_at', 'UPDATE')"
                    ") AS required(column_name, privilege_name)"
                ).scalar_one()
                is True
            )
            assert (
                connection.exec_driver_sql(
                    "SELECT has_table_privilege('litblogs_runtime', 'public.teacher_invitations', 'INSERT,DELETE')"
                ).scalar_one()
                is False
            )
            assert (
                connection.exec_driver_sql(
                    "SELECT bool_and(has_column_privilege("
                    "'litblogs_runtime', 'public.operator_audit_events', "
                    "column_name, 'INSERT')) FROM unnest(ARRAY["
                    "'actor_identifier', 'action', 'outcome', 'resource_digest'"
                    "]) AS required(column_name)"
                ).scalar_one()
                is True
            )
            assert (
                connection.exec_driver_sql(
                    "SELECT has_table_privilege('litblogs_runtime', 'public.operator_audit_events', 'UPDATE')"
                ).scalar_one()
                is False
            )
            assert (
                connection.execute(
                    sa.text(
                        "SELECT owners.rolname FROM pg_proc AS routines "
                        "JOIN pg_namespace AS namespaces ON namespaces.oid = routines.pronamespace "
                        "JOIN pg_roles AS owners ON owners.oid = routines.proowner "
                        "WHERE namespaces.nspname = 'public' "
                        "AND routines.proname LIKE :operator_prefix "
                        "GROUP BY owners.rolname"
                    ),
                    {"operator_prefix": "operator_%"},
                ).scalar_one()
                == "litblog_identity_owner"
            )
            assert (
                connection.exec_driver_sql(
                    "SELECT has_function_privilege("
                    "'litblog_account_operator', "
                    "'public.operator_set_account_status(character varying,boolean,"
                    "character varying,character varying)', 'EXECUTE')"
                ).scalar_one()
                is True
            )
            assert (
                connection.exec_driver_sql(
                    "SELECT has_function_privilege("
                    "'litblog_account_operator', "
                    "'public.operator_create_teacher_invitation(character varying,"
                    "character varying,timestamp with time zone,character varying,"
                    "character varying)', 'EXECUTE')"
                ).scalar_one()
                is False
            )

        with runtime_engine.begin() as connection:
            connection.execute(
                sa.text(
                    "INSERT INTO public.operator_audit_events "
                    "(actor_identifier, action, outcome, resource_digest) "
                    "VALUES ('runtime-smoke', 'ACCOUNT_ENABLED', 'SUCCEEDED', :digest)"
                ),
                {"digest": "a" * 64},
            )
        denied_audit_statements = (
            "SELECT id FROM public.operator_audit_events",
            "UPDATE public.operator_audit_events SET outcome = 'NOT_FOUND'",
            "DELETE FROM public.operator_audit_events",
            "INSERT INTO public.operator_audit_events "
            "(actor_identifier, action, outcome, resource_digest, created_at) "
            "VALUES ('runtime-smoke', 'ACCOUNT_ENABLED', 'SUCCEEDED', "
            f"'{('b' * 64)}', CURRENT_TIMESTAMP)",
            "INSERT INTO public.operator_audit_events "
            "(id, actor_identifier, action, outcome, resource_digest) "
            "VALUES (999, 'runtime-smoke', 'ACCOUNT_ENABLED', 'SUCCEEDED', "
            f"'{('c' * 64)}')",
        )
        for statement in denied_audit_statements:
            with pytest.raises(sa.exc.DBAPIError):
                with runtime_engine.begin() as connection:
                    connection.exec_driver_sql(statement)

        with migrator_engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE FUNCTION public.migration_default_acl_probe() "
                "RETURNS integer LANGUAGE SQL AS 'SELECT 1'"
            )
        with admin_engine.connect() as connection:
            public_can_execute_probe = connection.exec_driver_sql(
                "SELECT EXISTS ("
                "SELECT 1 FROM pg_proc AS routine "
                "JOIN pg_namespace AS namespace ON namespace.oid = routine.pronamespace "
                "CROSS JOIN LATERAL aclexplode("
                "COALESCE(routine.proacl, acldefault('f', routine.proowner))) AS acl "
                "WHERE namespace.nspname = 'public' "
                "AND routine.proname = 'migration_default_acl_probe' "
                "AND acl.grantee = 0 AND acl.privilege_type = 'EXECUTE')"
            ).scalar_one()
            assert public_can_execute_probe is False
        with migrator_engine.begin() as connection:
            connection.exec_driver_sql(
                "DROP FUNCTION public.migration_default_acl_probe()"
            )

        with pytest.raises(
            RuntimeError,
            match="ACL downgrade requires exact temporary membership",
        ):
            _downgrade(migrator_engine, "b983b7aebe7b")
        assert _current_revision(migrator_engine) == EXPECTED_REVISIONS[-1]

        with admin_engine.begin() as connection:
            connection.exec_driver_sql(
                "GRANT litblog_identity_owner TO litblogs_migrator "
                "WITH ADMIN FALSE, INHERIT TRUE, SET TRUE"
            )

            connection.exec_driver_sql(
                "CREATE TABLE public.identity_owner_downgrade_tamper "
                "(id integer PRIMARY KEY)"
            )
            connection.exec_driver_sql(
                "ALTER TABLE public.identity_owner_downgrade_tamper "
                "OWNER TO litblog_identity_owner"
            )
        with pytest.raises(
            RuntimeError,
            match="ACL downgrade ownership boundary mismatch",
        ):
            _downgrade(migrator_engine, "b983b7aebe7b")
        assert _current_revision(migrator_engine) == EXPECTED_REVISIONS[-1]
        with admin_engine.connect() as connection:
            assert (
                connection.exec_driver_sql(
                    "SELECT owner.rolname FROM pg_class AS relation "
                    "JOIN pg_roles AS owner ON owner.oid = relation.relowner "
                    "WHERE relation.oid = "
                    "'public.identity_owner_downgrade_tamper'::regclass"
                ).scalar_one()
                == "litblog_identity_owner"
            )
            assert (
                connection.execute(
                    sa.text(
                        "SELECT count(*) FROM pg_proc AS routine "
                        "JOIN pg_namespace AS namespace "
                        "ON namespace.oid = routine.pronamespace "
                        "JOIN pg_roles AS owner ON owner.oid = routine.proowner "
                        "WHERE namespace.nspname = 'public' "
                        "AND routine.proname LIKE :operator_prefix "
                        "AND owner.rolname = 'litblog_identity_owner'"
                    ),
                    {"operator_prefix": "operator_%"},
                ).scalar_one()
                == 3
            )
        with admin_engine.begin() as connection:
            connection.exec_driver_sql(
                "DROP TABLE public.identity_owner_downgrade_tamper"
            )
        _downgrade(migrator_engine, "b983b7aebe7b")
        assert _current_revision(migrator_engine) == "b983b7aebe7b"
        with admin_engine.connect() as connection:
            assert (
                connection.exec_driver_sql(
                    "SELECT count(*) FROM pg_shdepend AS dependency "
                    "JOIN pg_roles AS owner "
                    "ON owner.oid = dependency.refobjid "
                    "WHERE dependency.refclassid = 'pg_authid'::regclass "
                    "AND dependency.deptype = 'o' "
                    "AND owner.rolname = 'litblog_identity_owner'"
                ).scalar_one()
                == 0
            )
            assert (
                connection.execute(
                    sa.text(
                        "SELECT count(*) FROM pg_proc AS routine "
                        "JOIN pg_namespace AS namespace "
                        "ON namespace.oid = routine.pronamespace "
                        "JOIN pg_roles AS owner ON owner.oid = routine.proowner "
                        "WHERE namespace.nspname = 'public' "
                        "AND routine.proname LIKE :operator_prefix "
                        "AND owner.rolname = 'litblogs_migrator'"
                    ),
                    {"operator_prefix": "operator_%"},
                ).scalar_one()
                == 3
            )
        _downgrade(migrator_engine)
    finally:
        if runtime_engine is not None:
            runtime_engine.dispose()
        if migrator_engine is not None:
            try:
                with admin_engine.begin() as connection:
                    connection.exec_driver_sql(
                        "GRANT litblog_identity_owner TO litblogs_migrator "
                        "WITH ADMIN FALSE, INHERIT TRUE, SET TRUE"
                    )
                _downgrade(migrator_engine)
            except (RuntimeError, sa.exc.DBAPIError):
                pass
            migrator_engine.dispose()
        with admin_engine.begin() as connection:
            connection.exec_driver_sql(
                "DROP FUNCTION IF EXISTS public.migration_default_acl_probe() CASCADE"
            )
            if public_owned_by_migrator and previous_public_owner is not None:
                quoted_owner = connection.dialect.identifier_preparer.quote(
                    previous_public_owner
                )
                connection.exec_driver_sql(
                    f"ALTER SCHEMA public OWNER TO {quoted_owner}"
                )
            for role_name in reversed(created_roles):
                connection.exec_driver_sql(f"DROP OWNED BY {role_name} CASCADE")
                connection.exec_driver_sql(f"DROP ROLE {role_name}")
            quoted_database = connection.dialect.identifier_preparer.quote(
                admin_url.database
            )
            connection.exec_driver_sql(
                f"GRANT CONNECT, TEMPORARY ON DATABASE {quoted_database} TO PUBLIC"
            )
        admin_engine.dispose()
