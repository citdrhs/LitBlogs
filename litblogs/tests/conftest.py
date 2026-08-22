import os
import re
import sys
from importlib import import_module
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url

BACKEND_DIR = Path(__file__).resolve().parents[1]
TEST_TEMP_DIR = TemporaryDirectory(prefix="litblogs-tests-")
TEST_DATABASE_PATH = Path(TEST_TEMP_DIR.name) / "litblogs-test.db"
DEFAULT_TEST_DATABASE_URL = f"sqlite:///{TEST_DATABASE_PATH.as_posix()}"
EXPLICIT_TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")
EXPLICIT_TEST_POSTGRES_DATABASE = os.environ.get("TEST_POSTGRES_DATABASE", "")
EXPLICIT_ALLOW_TEST_DATABASE_DDL = os.environ.get("ALLOW_TEST_DATABASE_DDL", "")
SELECTED_TEST_DATABASE_URL = EXPLICIT_TEST_DATABASE_URL or DEFAULT_TEST_DATABASE_URL
LOOPBACK_DATABASE_HOSTS = {"localhost", "127.0.0.1", "::1"}
SYNTHETIC_POSTGRES_DATABASE = re.compile(r"^litblog_test_[a-z0-9][a-z0-9_]*$")

TEST_ENVIRONMENT = {
    "APP_ENV": "test",
    "DATABASE_URL": SELECTED_TEST_DATABASE_URL,
    "TEST_DATABASE_URL": EXPLICIT_TEST_DATABASE_URL,
    "TEST_POSTGRES_DATABASE": EXPLICIT_TEST_POSTGRES_DATABASE,
    "ALLOW_TEST_DATABASE_DDL": EXPLICIT_ALLOW_TEST_DATABASE_DDL,
    "SECRET_KEY": "test-only-secret-key-" + ("x" * 64),
    "TEACHER_INVITE_HMAC_KEY": "test-only-teacher-invite-hmac-key-" + ("y" * 64),
    "JWT_ISSUER": "litblog-test",
    "JWT_AUDIENCE": "litblog-test-clients",
    "ACCESS_TOKEN_EXPIRE_MINUTES": "30",
    "RESET_DATABASE_ON_STARTUP": "false",
    "ADMIN_ACCESS_CODE": "test-only-admin-access-code",
    "ADMIN_CODE": "test-only-admin-code",
    "FRONTEND_URL": "http://testserver",
    "BASE_URL": "http://testserver",
    "CORS_ALLOWED_ORIGINS": "http://testserver",
    "ALLOWED_EMAIL_DOMAINS": "example.com,example.test",
    "GOOGLE_CLIENT_ID": "test-google-client-id",
    "MICROSOFT_CLIENT_ID": "test-microsoft-client-id",
    "MICROSOFT_TENANT_ID": "871bd3e0-2dc0-4a40-9b07-9d03068c2364",
    "MICROSOFT_ALLOWED_TENANT_IDS": "871bd3e0-2dc0-4a40-9b07-9d03068c2364",
    "OAUTH_HTTP_TIMEOUT_SECONDS": "2",
    "OAUTH_JWKS_CACHE_SECONDS": "300",
    "SESSION_COOKIE_NAME": "test-litblog-session",
    "CSRF_COOKIE_NAME": "test-litblog-csrf",
    "SESSION_COOKIE_SECURE": "false",
    "VAPID_PUBLIC_KEY": "",
    "VAPID_PRIVATE_KEY": "",
    "VAPID_SUBJECT": "mailto:tests@example.com",
    "PUSH_REMINDER_INTERVAL_SECONDS": "3600",
    "EMAIL_HOST": "localhost",
    "EMAIL_PORT": "1025",
    "EMAIL_USERNAME": "test-email-user",
    "EMAIL_PASSWORD": "test-email-password",
    "EMAIL_FROM": "tests@example.com",
    "PASSWORD_RESET_WORKER_ENABLED": "false",
}


def _assert_test_database_engine(candidate_engine):
    dialect_name = getattr(getattr(candidate_engine, "dialect", None), "name", None)
    candidate_url = getattr(candidate_engine, "url", None)

    if dialect_name == "sqlite":
        configured_database = getattr(candidate_url, "database", None)
        if not configured_database:
            raise RuntimeError("Refusing test DDL because the SQLite database path is missing")

        configured_path = Path(configured_database).resolve()
        expected_path = TEST_DATABASE_PATH.resolve()
        if configured_path != expected_path:
            raise RuntimeError(
                f"Refusing test DDL for {configured_path}; expected test database {expected_path}"
            )
        return

    if dialect_name != "postgresql":
        raise RuntimeError(f"Refusing unsupported test database dialect: {dialect_name!r}")

    test_database_url = os.environ.get("TEST_DATABASE_URL")
    if not test_database_url:
        raise RuntimeError("Refusing PostgreSQL test DDL without explicit TEST_DATABASE_URL")
    if candidate_url != make_url(test_database_url):
        raise RuntimeError("Refusing PostgreSQL test DDL because engine URL differs from TEST_DATABASE_URL")
    if os.environ.get("ALLOW_TEST_DATABASE_DDL") != "true":
        raise RuntimeError("Refusing PostgreSQL test DDL without ALLOW_TEST_DATABASE_DDL=true")

    query_keys = set(candidate_url.query)
    if query_keys & {"host", "hostaddr", "service"}:
        raise RuntimeError("Refusing PostgreSQL test DDL with a connection target override")
    if query_keys & {"database", "dbname"}:
        raise RuntimeError("Refusing PostgreSQL test DDL with a database target override")

    if candidate_url.host not in LOOPBACK_DATABASE_HOSTS:
        raise RuntimeError("Refusing PostgreSQL test DDL unless the host is an exact loopback address")

    expected_database = os.environ.get("TEST_POSTGRES_DATABASE")
    if not expected_database:
        raise RuntimeError("Refusing PostgreSQL test DDL without explicit TEST_POSTGRES_DATABASE")
    if candidate_url.database != expected_database:
        raise RuntimeError(
            "Refusing PostgreSQL test DDL because the engine database differs from "
            "TEST_POSTGRES_DATABASE"
        )
    if expected_database != "litblog_ci" and not SYNTHETIC_POSTGRES_DATABASE.fullmatch(
        expected_database
    ):
        raise RuntimeError("Refusing PostgreSQL DDL for a non-synthetic test database name")


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
    main.upload_admission.reset()
    _assert_test_database_engine(database.engine)
    base.Base.metadata.drop_all(bind=database.engine)

    _assert_test_database_engine(database.engine)
    with TestClient(main.app) as test_client:
        yield test_client

    _assert_test_database_engine(database.engine)
    base.Base.metadata.drop_all(bind=database.engine)
    main.upload_admission.reset()


@pytest.fixture(scope="session")
def database_existed_after_import():
    return DATABASE_EXISTED_AFTER_IMPORT


@pytest.fixture(scope="session")
def database_guard():
    return _assert_test_database_engine
