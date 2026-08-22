import os
import re
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool
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
if supplied_connection is None:
    migration_database_url = os.environ.get("LITBLOGS_MIGRATION_DATABASE_URL")
    if not (
        _is_verified_postgresql_url(migration_database_url)
        or _is_isolated_test_migration_url(migration_database_url)
        or _is_local_development_migration_url(migration_database_url)
    ):
        raise RuntimeError("The migration database URL is missing or invalid")
    config.set_main_option(
        "sqlalchemy.url", migration_database_url.replace("%", "%%")
    )
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    if supplied_connection is not None:
        context.configure(
            connection=supplied_connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
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
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
