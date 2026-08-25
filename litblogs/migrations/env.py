import os
import re
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool, text
from sqlalchemy.engine import make_url

import models  # noqa: F401 - model import registers every table with metadata
from base import Base
from config import _is_verified_postgresql_url


def _is_isolated_test_migration_url(value: str | None) -> bool:
    if (
        os.environ.get("APP_ENV") != "test"
        or not value
        or value != os.environ.get("TEST_DATABASE_URL")
    ):
        return False
    try:
        url = make_url(value)
    except (TypeError, ValueError):
        return False
    database = url.database or ""
    return (
        url.get_backend_name() == "postgresql"
        and url.host in {"localhost", "127.0.0.1", "::1"}
        and (
            database == "litblog_ci"
            or re.fullmatch(r"litblog_test_[a-z0-9][a-z0-9_]*", database)
            is not None
        )
        and not (set(url.query) & {"database", "dbname", "host", "hostaddr", "service"})
    )


def _is_local_development_migration_url(value: str | None) -> bool:
    if (
        os.environ.get("APP_ENV") != "development"
        or not value
        or value != os.environ.get("DATABASE_URL")
    ):
        return False
    try:
        url = make_url(value)
        backend_root = Path(__file__).resolve().parents[1]
        database_path = Path(url.database or "")
        candidate = (
            database_path
            if database_path.is_absolute()
            else backend_root / database_path
        )
        if candidate.is_symlink() or candidate.is_dir():
            return False
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(backend_root)
    except (OSError, TypeError, ValueError):
        return False
    suffix = resolved.suffix.lower()
    return (
        url.get_backend_name() == "sqlite"
        and url.username is None
        and url.password is None
        and url.host is None
        and not url.query
        and resolved.name not in {"", ".", ".."}
        and (suffix == ".db" or suffix.startswith(".sqlite"))
    )


config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

supplied_connection = config.attributes.get("connection")
migration_database_url = None
requires_migrator_verification = False
expected_migration_database = None
if supplied_connection is None:
    migration_database_url = os.environ.get("LITBLOGS_MIGRATION_DATABASE_URL")
    is_verified_postgresql = _is_verified_postgresql_url(migration_database_url)
    is_isolated_test_postgresql = _is_isolated_test_migration_url(
        migration_database_url
    )
    is_local_development = _is_local_development_migration_url(
        migration_database_url
    )
    if not (
        is_verified_postgresql
        or is_isolated_test_postgresql
        or is_local_development
    ):
        raise RuntimeError("The migration database URL is missing or invalid")
    requires_migrator_verification = (
        is_verified_postgresql or is_isolated_test_postgresql
    )
    if requires_migrator_verification:
        expected_migration_database = make_url(migration_database_url).database
    config.set_main_option(
        "sqlalchemy.url", migration_database_url.replace("%", "%%")
    )
target_metadata = Base.metadata


def _include_object(object_, _name, _type, reflected, _compare_to):
    """Exclude metadata DDL that is explicitly scoped to another dialect."""
    if reflected:
        return True
    ddl_condition = getattr(object_, "_ddl_if", None)
    scoped_dialects = getattr(ddl_condition, "dialect", None)
    if not scoped_dialects:
        return True
    if isinstance(scoped_dialects, str):
        scoped_dialects = (scoped_dialects,)
    return context.get_context().dialect.name in scoped_dialects


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def _verify_migrator_database_boundary(connection, expected_database: str) -> None:
    """Require the exact migration-only PostgreSQL identity and target."""

    expected_boundary = (
        "litblogs_migrator",
        "litblogs_migrator",
        expected_database,
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
    try:
        role_record = connection.execute(
            text(
                """
                SELECT
                    session_user,
                    current_user,
                    pg_catalog.current_database(),
                    roles.rolsuper,
                    roles.rolinherit,
                    roles.rolcreaterole,
                    roles.rolcreatedb,
                    roles.rolcanlogin,
                    roles.rolreplication,
                    roles.rolbypassrls,
                    (
                        (
                            SELECT
                                COUNT(*) = COUNT(*) FILTER (
                                    WHERE granted_role.rolname =
                                        'litblog_identity_owner'
                                      AND NOT memberships.admin_option
                                      AND memberships.inherit_option
                                      AND memberships.set_option
                                )
                                AND COUNT(*) <= 1
                            FROM pg_catalog.pg_auth_members AS memberships
                            JOIN pg_catalog.pg_roles AS granted_role
                              ON granted_role.oid = memberships.roleid
                            WHERE memberships.member = roles.oid
                        )
                        AND NOT EXISTS (
                            SELECT 1
                            FROM pg_catalog.pg_auth_members AS memberships
                            WHERE memberships.roleid = roles.oid
                        )
                    ) AS has_exact_role_membership,
                    schema_owner.rolname AS public_schema_owner,
                    pg_catalog.has_schema_privilege(
                        current_user,
                        'public',
                        'USAGE'
                    ) AS has_public_usage,
                    pg_catalog.has_schema_privilege(
                        current_user,
                        'public',
                        'CREATE'
                    ) AS has_public_create,
                    NOT EXISTS (
                        SELECT 1
                        FROM pg_catalog.aclexplode(
                            COALESCE(
                                public_schema.nspacl,
                                pg_catalog.acldefault(
                                    'n',
                                    public_schema.nspowner
                                )
                            )
                        ) AS schema_acl
                        WHERE schema_acl.grantee = 0
                          AND schema_acl.privilege_type = 'CREATE'
                    ) AS public_create_is_revoked,
                    pg_catalog.current_schemas(FALSE) = ARRAY['public'::name]
                        AS has_exact_search_path
                FROM pg_catalog.pg_roles AS roles
                LEFT JOIN pg_catalog.pg_namespace AS public_schema
                  ON public_schema.nspname = 'public'
                LEFT JOIN pg_catalog.pg_roles AS schema_owner
                  ON schema_owner.oid = public_schema.nspowner
                WHERE roles.rolname = current_user
                """
            )
        ).one()
        if tuple(role_record) != expected_boundary:
            raise RuntimeError("Database migration privilege boundary mismatch")
    except Exception:
        raise RuntimeError(
            "Database migration privilege boundary mismatch"
        ) from None


def run_migrations_online() -> None:
    if supplied_connection is not None:
        context.configure(
            connection=supplied_connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            include_object=_include_object,
        )
        with context.begin_transaction():
            context.run_migrations()
        return

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        if requires_migrator_verification:
            _verify_migrator_database_boundary(
                connection,
                expected_migration_database,
            )
            connection.rollback()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            include_object=_include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError(
        "Offline SQL generation is unsupported; migrations require live database preflights"
    )
else:
    run_migrations_online()
