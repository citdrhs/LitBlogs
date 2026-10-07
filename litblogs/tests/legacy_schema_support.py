"""Build the reviewed pre-recovery SQLite layout used by adoption tests."""

from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

BACKEND_DIR = Path(__file__).resolve().parents[1]
PRE_RECOVERY_REVISION = "b64a9c2e7d31"


def create_pre_recovery_tables(engine, *, omit: frozenset[str] = frozenset()) -> None:
    """Create the historical schema without stamping an adoption candidate.

    Tests stamp this schema at the baseline and replay later migrations to
    exercise their handling of tables that were already present. Building it
    from the reviewed revision keeps newer model fields out of the fixture.
    """
    if engine.dialect.name != "sqlite":
        raise RuntimeError("Pre-recovery adoption fixtures require SQLite")

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, PRE_RECOVERY_REVISION)

        for table_name in omit:
            sa.Table(table_name, sa.MetaData(), autoload_with=connection).drop(connection)
        sa.Table("alembic_version", sa.MetaData(), autoload_with=connection).drop(connection)
