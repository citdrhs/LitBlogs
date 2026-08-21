import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, create_mock_engine
from sqlalchemy.engine import make_url

BACKEND_DIR = Path(__file__).resolve().parents[1]
SAFE_POSTGRES_URL = (
    "postgresql://test-only-user:test-only-password@127.0.0.1:1/litblog_ci"
)


def _postgresql_mock_engine(database_url):
    executed_statements = []
    engine = create_mock_engine(
        database_url,
        lambda *args, **kwargs: executed_statements.append((args, kwargs)),
    )
    engine.url = make_url(database_url)
    return engine, executed_statements


def _configure_postgresql_guard(
    monkeypatch,
    *,
    database_url=SAFE_POSTGRES_URL,
    allow_ddl="true",
    database_name="litblog_ci",
):
    if database_url is None:
        monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    else:
        monkeypatch.setenv("TEST_DATABASE_URL", database_url)

    if allow_ddl is None:
        monkeypatch.delenv("ALLOW_TEST_DATABASE_DDL", raising=False)
    else:
        monkeypatch.setenv("ALLOW_TEST_DATABASE_DDL", allow_ddl)

    if database_name is None:
        monkeypatch.delenv("TEST_POSTGRES_DATABASE", raising=False)
    else:
        monkeypatch.setenv("TEST_POSTGRES_DATABASE", database_name)


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


def test_explicit_test_database_url_selects_guarded_postgresql_without_connecting():
    process_environment = os.environ.copy()
    process_environment.update(
        {
            "APP_ENV": "test",
            "DATABASE_URL": "sqlite:///must-not-be-selected.db",
            "TEST_DATABASE_URL": SAFE_POSTGRES_URL,
            "TEST_POSTGRES_DATABASE": "litblog_ci",
            "ALLOW_TEST_DATABASE_DDL": "true",
            "RESET_DATABASE_ON_STARTUP": "true",
        }
    )
    probe = """
import json
import os
import sys

sys.path.insert(0, os.path.join(os.getcwd(), "tests"))
import conftest

print(json.dumps({
    "database_url": conftest.database.DATABASE_URL,
    "dialect": conftest.database.engine.dialect.name,
    "database_name": conftest.database.engine.url.database,
    "reset_database_on_startup": os.environ["RESET_DATABASE_ON_STARTUP"],
}))
"""

    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=BACKEND_DIR,
        env=process_environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "database_url": SAFE_POSTGRES_URL,
        "dialect": "postgresql",
        "database_name": "litblog_ci",
        "reset_database_on_startup": "false",
    }


def test_dotenv_cannot_supply_postgresql_ddl_opt_in():
    process_environment = os.environ.copy()
    for variable in (
        "TEST_DATABASE_URL",
        "TEST_POSTGRES_DATABASE",
        "ALLOW_TEST_DATABASE_DDL",
    ):
        process_environment.pop(variable, None)
    process_environment["APP_ENV"] = "test"
    probe = """
import json
import os
import sys

import dotenv

dotenv.dotenv_values = lambda *_args, **_kwargs: {}

def poison_test_environment(*_args, **_kwargs):
    os.environ.setdefault("TEST_DATABASE_URL", "postgresql://fake:fake@db.invalid/poison")
    os.environ.setdefault("TEST_POSTGRES_DATABASE", "poison")
    os.environ.setdefault("ALLOW_TEST_DATABASE_DDL", "true")

dotenv.load_dotenv = poison_test_environment
sys.path.insert(0, os.path.join(os.getcwd(), "tests"))
import conftest

print(json.dumps({
    "test_database_url": os.environ["TEST_DATABASE_URL"],
    "test_postgres_database": os.environ["TEST_POSTGRES_DATABASE"],
    "allow_test_database_ddl": os.environ["ALLOW_TEST_DATABASE_DDL"],
    "database_dialect": conftest.database.engine.dialect.name,
}))
"""

    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=BACKEND_DIR,
        env=process_environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "test_database_url": "",
        "test_postgres_database": "",
        "allow_test_database_ddl": "",
        "database_dialect": "sqlite",
    }


@pytest.mark.parametrize(
    ("host", "database_name"),
    [
        ("localhost", "litblog_ci"),
        ("127.0.0.1", "litblog_test_guard"),
        ("[::1]", "litblog_test_ipv6"),
    ],
)
def test_database_guard_accepts_explicit_loopback_postgresql_without_ddl(
    database_guard, monkeypatch, host, database_name
):
    database_url = (
        f"postgresql://test-only-user:test-only-password@{host}:1/{database_name}"
    )
    _configure_postgresql_guard(
        monkeypatch,
        database_url=database_url,
        database_name=database_name,
    )
    postgresql_engine, executed_statements = _postgresql_mock_engine(database_url)

    database_guard(postgresql_engine)

    assert executed_statements == []


@pytest.mark.parametrize("allow_ddl", [None, "false", "true-ish"])
def test_database_guard_rejects_postgresql_without_explicit_ddl_flag(
    database_guard, monkeypatch, allow_ddl
):
    _configure_postgresql_guard(monkeypatch, allow_ddl=allow_ddl)
    postgresql_engine, executed_statements = _postgresql_mock_engine(SAFE_POSTGRES_URL)

    with pytest.raises(RuntimeError, match="ALLOW_TEST_DATABASE_DDL"):
        database_guard(postgresql_engine)

    assert executed_statements == []


@pytest.mark.parametrize(
    "host",
    [
        "db.invalid",
        "localhost.example.invalid",
        "127.0.0.2",
        "[::ffff:127.0.0.1]",
    ],
)
def test_database_guard_rejects_remote_and_loopback_lookalike_hosts_without_ddl(
    database_guard, monkeypatch, host
):
    database_url = (
        f"postgresql://test-only-user:test-only-password@{host}:1/litblog_ci"
    )
    _configure_postgresql_guard(monkeypatch, database_url=database_url)
    postgresql_engine, executed_statements = _postgresql_mock_engine(database_url)

    with pytest.raises(RuntimeError, match="loopback"):
        database_guard(postgresql_engine)

    assert executed_statements == []


@pytest.mark.parametrize(
    "query_override",
    ["host=db.invalid", "hostaddr=203.0.113.10", "service=non-test-service"],
)
def test_database_guard_rejects_postgresql_host_query_overrides_without_ddl(
    database_guard, monkeypatch, query_override
):
    database_url = f"{SAFE_POSTGRES_URL}?{query_override}"
    _configure_postgresql_guard(monkeypatch, database_url=database_url)
    postgresql_engine, executed_statements = _postgresql_mock_engine(database_url)

    with pytest.raises(RuntimeError, match="connection target override"):
        database_guard(postgresql_engine)

    assert executed_statements == []


@pytest.mark.parametrize(
    "database_name",
    [
        "litblog",
        "litblog_ci_prod",
        "LITBLOG_CI",
        "litblog_test",
        "litblog_test_",
        "prod_litblog_test_case",
    ],
)
def test_database_guard_rejects_non_synthetic_database_names_without_ddl(
    database_guard, monkeypatch, database_name
):
    database_url = (
        "postgresql://test-only-user:test-only-password@localhost:1/"
        f"{database_name}"
    )
    _configure_postgresql_guard(
        monkeypatch,
        database_url=database_url,
        database_name=database_name,
    )
    postgresql_engine, executed_statements = _postgresql_mock_engine(database_url)

    with pytest.raises(RuntimeError, match="synthetic test database"):
        database_guard(postgresql_engine)

    assert executed_statements == []


def test_database_guard_rejects_database_name_mismatch_without_ddl(
    database_guard, monkeypatch
):
    database_url = (
        "postgresql://test-only-user:test-only-password@localhost:1/litblog_test_actual"
    )
    _configure_postgresql_guard(
        monkeypatch,
        database_url=database_url,
        database_name="litblog_test_expected",
    )
    postgresql_engine, executed_statements = _postgresql_mock_engine(database_url)

    with pytest.raises(RuntimeError, match="TEST_POSTGRES_DATABASE"):
        database_guard(postgresql_engine)

    assert executed_statements == []


@pytest.mark.parametrize("query_key", ["dbname", "database"])
def test_database_guard_rejects_postgresql_database_query_overrides_without_ddl(
    database_guard, monkeypatch, query_key
):
    database_url = f"{SAFE_POSTGRES_URL}?{query_key}=production"
    _configure_postgresql_guard(monkeypatch, database_url=database_url)
    postgresql_engine, executed_statements = _postgresql_mock_engine(database_url)

    with pytest.raises(RuntimeError, match="database target override"):
        database_guard(postgresql_engine)

    assert executed_statements == []


def test_database_guard_rejects_missing_explicit_database_name_without_ddl(
    database_guard, monkeypatch
):
    _configure_postgresql_guard(monkeypatch, database_name=None)
    postgresql_engine, executed_statements = _postgresql_mock_engine(SAFE_POSTGRES_URL)

    with pytest.raises(RuntimeError, match="TEST_POSTGRES_DATABASE"):
        database_guard(postgresql_engine)

    assert executed_statements == []


def test_database_guard_rejects_engine_url_mismatch_without_ddl(
    database_guard, monkeypatch
):
    _configure_postgresql_guard(monkeypatch)
    mismatched_url = (
        "postgresql://different-test-user:test-only-password@127.0.0.1:1/litblog_ci"
    )
    postgresql_engine, executed_statements = _postgresql_mock_engine(mismatched_url)

    with pytest.raises(RuntimeError, match="TEST_DATABASE_URL"):
        database_guard(postgresql_engine)

    assert executed_statements == []


def test_database_guard_rejects_missing_explicit_database_url_without_ddl(
    database_guard, monkeypatch
):
    _configure_postgresql_guard(monkeypatch, database_url=None)
    postgresql_engine, executed_statements = _postgresql_mock_engine(SAFE_POSTGRES_URL)

    with pytest.raises(RuntimeError, match="TEST_DATABASE_URL"):
        database_guard(postgresql_engine)

    assert executed_statements == []


def test_database_guard_rejects_unsupported_dialect_without_ddl(database_guard, monkeypatch):
    mysql_url = "mysql://test-only-user:test-only-password@localhost:1/litblog_ci"
    _configure_postgresql_guard(monkeypatch, database_url=mysql_url)
    mysql_engine, executed_statements = _postgresql_mock_engine(mysql_url)

    with pytest.raises(RuntimeError, match="unsupported test database dialect"):
        database_guard(mysql_engine)

    assert executed_statements == []


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

    with pytest.raises(RuntimeError, match="TEST_DATABASE_URL"):
        database_guard(postgresql_engine)

    assert executed_statements == []
