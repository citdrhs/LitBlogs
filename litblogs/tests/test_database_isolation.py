import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, create_mock_engine

BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_process_environment_wins_over_environment_specific_file(tmp_path):
    isolated_backend = tmp_path / "isolated-backend"
    isolated_backend.mkdir()
    shutil.copy2(BACKEND_DIR / "base.py", isolated_backend / "base.py")
    shutil.copy2(BACKEND_DIR / "database.py", isolated_backend / "database.py")

    safe_database_path = tmp_path / "safe-test.db"
    safe_database_url = f"sqlite:///{safe_database_path.as_posix()}"
    (isolated_backend / ".env").write_text(
        "\n".join(
            [
                "APP_ENV=development",
                "DATABASE_URL=sqlite:///base.db",
                "RESET_DATABASE_ON_STARTUP=true",
                "PRECEDENCE_MARKER=base",
            ]
        ),
        encoding="utf-8",
    )
    (isolated_backend / ".env.test").write_text(
        "\n".join(
            [
                "DATABASE_URL=postgresql://fake-user:fake-password@db.invalid/poison",
                "RESET_DATABASE_ON_STARTUP=true",
                "PRECEDENCE_MARKER=environment-specific",
            ]
        ),
        encoding="utf-8",
    )

    process_environment = os.environ.copy()
    process_environment.update(
        {
            "APP_ENV": "test",
            "DATABASE_URL": safe_database_url,
            "RESET_DATABASE_ON_STARTUP": "false",
        }
    )
    process_environment.pop("PRECEDENCE_MARKER", None)
    probe = """
import json
import os

import database

print(json.dumps({
    "database_url": database.DATABASE_URL,
    "dialect": database.engine.dialect.name,
    "database_path": database.engine.url.database,
    "app_env": os.environ["APP_ENV"],
    "precedence_marker": os.environ["PRECEDENCE_MARKER"],
    "reset_database_on_startup": os.environ["RESET_DATABASE_ON_STARTUP"],
}))
"""

    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=isolated_backend,
        env=process_environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "database_url": safe_database_url,
        "dialect": "sqlite",
        "database_path": safe_database_path.as_posix(),
        "app_env": "test",
        "precedence_marker": "environment-specific",
        "reset_database_on_startup": "false",
    }
    assert not safe_database_path.exists()


def test_database_guard_rejects_different_sqlite_without_ddl(database_guard, tmp_path):
    different_database_path = tmp_path / "different-test.db"
    different_engine = create_engine(f"sqlite:///{different_database_path.as_posix()}")

    try:
        with pytest.raises(RuntimeError, match="expected test database"):
            database_guard(different_engine)
    finally:
        different_engine.dispose()

    assert not different_database_path.exists()


def test_database_guard_rejects_postgresql_mock_without_ddl(database_guard):
    executed_statements = []
    postgresql_engine = create_mock_engine(
        "postgresql://fake-user:fake-password@db.invalid/poison",
        lambda *args, **kwargs: executed_statements.append((args, kwargs)),
    )

    with pytest.raises(RuntimeError, match="SQLite"):
        database_guard(postgresql_engine)

    assert executed_statements == []
