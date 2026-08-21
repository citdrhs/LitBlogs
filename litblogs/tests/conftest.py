import os
import sys
from importlib import import_module
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
TEST_TEMP_DIR = TemporaryDirectory(prefix="litblogs-tests-")
TEST_DATABASE_PATH = Path(TEST_TEMP_DIR.name) / "litblogs-test.db"

TEST_ENVIRONMENT = {
    "APP_ENV": "test",
    "DATABASE_URL": f"sqlite:///{TEST_DATABASE_PATH.as_posix()}",
    "SECRET_KEY": "test-only-secret-key-" + ("x" * 64),
    "ALGORITHM": "HS256",
    "ACCESS_TOKEN_EXPIRE_MINUTES": "30",
    "RESET_DATABASE_ON_STARTUP": "false",
    "ADMIN_ACCESS_CODE": "test-only-admin-access-code",
    "TEACHER_ACCESS_CODE": "test-only-teacher-access-code",
    "ADMIN_CODE": "test-only-admin-code",
    "FRONTEND_URL": "http://testserver",
    "BASE_URL": "http://testserver",
    "CORS_ALLOWED_ORIGINS": "http://testserver",
    "MICROSOFT_REDIRECT_URI": "http://testserver",
    "GOOGLE_CLIENT_ID": "test-google-client-id",
    "MICROSOFT_CLIENT_ID": "test-microsoft-client-id",
    "MICROSOFT_CLIENT_SECRET": "test-microsoft-client-secret",
    "VAPID_PUBLIC_KEY": "",
    "VAPID_PRIVATE_KEY": "",
    "VAPID_SUBJECT": "mailto:tests@example.com",
    "PUSH_REMINDER_INTERVAL_SECONDS": "3600",
    "EMAIL_HOST": "localhost",
    "EMAIL_PORT": "1025",
    "EMAIL_USERNAME": "test-email-user",
    "EMAIL_PASSWORD": "test-email-password",
    "EMAIL_FROM": "tests@example.com",
}


def _assert_test_database_engine(candidate_engine):
    dialect_name = getattr(getattr(candidate_engine, "dialect", None), "name", None)
    if dialect_name != "sqlite":
        raise RuntimeError(f"Refusing test DDL for non-SQLite database dialect: {dialect_name!r}")

    configured_database = getattr(getattr(candidate_engine, "url", None), "database", None)
    if not configured_database:
        raise RuntimeError("Refusing test DDL because the SQLite database path is missing")

    configured_path = Path(configured_database).resolve()
    expected_path = TEST_DATABASE_PATH.resolve()
    if configured_path != expected_path:
        raise RuntimeError(
            f"Refusing test DDL for {configured_path}; expected test database {expected_path}"
        )


os.environ.update(TEST_ENVIRONMENT)
sys.path.insert(0, str(BACKEND_DIR))

database = import_module("database")
_assert_test_database_engine(database.engine)
main = import_module("main")
base = import_module("base")


DATABASE_EXISTED_AFTER_IMPORT = TEST_DATABASE_PATH.exists()


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_environment():
    yield
    database.engine.dispose()
    TEST_TEMP_DIR.cleanup()


@pytest.fixture
def client():
    _assert_test_database_engine(database.engine)
    base.Base.metadata.drop_all(bind=database.engine)

    _assert_test_database_engine(database.engine)
    with TestClient(main.app) as test_client:
        yield test_client

    _assert_test_database_engine(database.engine)
    base.Base.metadata.drop_all(bind=database.engine)


@pytest.fixture(scope="session")
def database_existed_after_import():
    return DATABASE_EXISTED_AFTER_IMPORT


@pytest.fixture(scope="session")
def database_guard():
    return _assert_test_database_engine
