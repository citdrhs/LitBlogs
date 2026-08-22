# database.py
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from config import Settings, get_settings

settings = get_settings()
DATABASE_URL = settings.database_url
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is required")

def engine_options(app_settings: Settings) -> dict:
    if not app_settings.database_url:
        raise RuntimeError("DATABASE_URL is required")

    if app_settings.database_url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}

    return {
        "pool_pre_ping": True,
        "pool_size": app_settings.db_pool_size,
        "max_overflow": app_settings.db_max_overflow,
        "pool_timeout": app_settings.db_pool_timeout_seconds,
        "pool_recycle": app_settings.db_pool_recycle_seconds,
        "connect_args": {
            "connect_timeout": app_settings.db_connect_timeout_seconds,
            "application_name": "litblogs-web",
            "options": (
                f"-c statement_timeout={app_settings.db_statement_timeout_ms} "
                f"-c lock_timeout={app_settings.db_lock_timeout_ms}"
            ),
        },
    }


engine = create_engine(DATABASE_URL, **engine_options(settings))
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def check_database_readiness(candidate_engine: Engine = engine) -> None:
    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    config = Config(str(Path(__file__).resolve().parent / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    expected_revision = scripts.get_current_head()
    if not expected_revision:
        raise RuntimeError("Database migration head is unavailable")

    with candidate_engine.connect() as connection:
        connection.execute(text("SELECT 1"))
        current_revision = MigrationContext.configure(connection).get_current_revision()
    if current_revision != expected_revision:
        raise RuntimeError("Database migration revision is not current")
