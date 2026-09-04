import ast
import io
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text

BACKEND_DIR = Path(__file__).resolve().parents[1]
BOOTSTRAP_PATH = BACKEND_DIR / "bootstrap_admin.py"
GOOD_PASSWORD = "StrongAdminPassword!2026"


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one(self):
        return self.value


class _RecordingConnection:
    def __init__(self, engine):
        self.engine = engine

    def execute(self, statement, parameters=None):
        sql = " ".join(str(statement).split())
        self.engine.events.append(("sql", sql, parameters))
        lowered = sql.lower()
        if "count(*)" in lowered and "from public.users" in lowered:
            return _ScalarResult(self.engine.user_count)
        if lowered.startswith("insert into users"):
            self.engine.inserts.append(dict(parameters or {}))
            self.engine.user_count += 1
        return _ScalarResult(None)


class _RecordingTransaction:
    def __init__(self, engine):
        self.engine = engine
        self.connection = _RecordingConnection(engine)

    def __enter__(self):
        self.engine.events.append(("transaction", "begin", None))
        return self.connection

    def __exit__(self, exc_type, exc, traceback):
        del exc, traceback
        if exc_type is None:
            self.engine.commits += 1
            self.engine.events.append(("transaction", "commit", None))
        else:
            self.engine.rollbacks += 1
            self.engine.events.append(("transaction", "rollback", None))
        return False


class _RecordingEngine:
    def __init__(self, *, dialect="postgresql", user_count=0):
        self.dialect = SimpleNamespace(name=dialect)
        self.user_count = user_count
        self.events = []
        self.inserts = []
        self.commits = 0
        self.rollbacks = 0

    def begin(self):
        return _RecordingTransaction(self)


def _settings(**overrides):
    values = {
        "app_env": "production",
        "allowed_email_domains": ("school.edu",),
        "upload_registry_schema_ready": True,
        "upload_legacy_import_complete": True,
        "upload_backup_restore_verified": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _answers(*values):
    answers = iter(values)
    return lambda _prompt: next(answers)


def _run_bootstrap(
    module,
    *,
    engine=None,
    settings=None,
    input_fn=None,
    password_fn=None,
    password_hasher=lambda _password: "reviewed-password-hash",
    now_fn=lambda: datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc),
    readiness_check=lambda _engine: None,
    identity_check=lambda _connection: None,
    head_check=lambda _connection: None,
):
    stdout = io.StringIO()
    stderr = io.StringIO()
    selected_engine = engine or _RecordingEngine()
    result = module.main(
        ["--confirm-empty-install"],
        app_settings=settings or _settings(),
        candidate_engine=selected_engine,
        readiness_check=readiness_check,
        identity_check=identity_check,
        head_check=head_check,
        input_fn=input_fn or _answers("RootAdmin", "admin@school.edu"),
        password_fn=password_fn or _answers(GOOD_PASSWORD, GOOD_PASSWORD),
        password_hasher=password_hasher,
        now_fn=now_fn,
        stdout=stdout,
        stderr=stderr,
    )
    return result, stdout.getvalue(), stderr.getvalue(), selected_engine


def test_bootstrap_admin_module_exists():
    assert BOOTSTRAP_PATH.is_file()


def test_bootstrap_accepts_only_the_explicit_empty_install_confirmation():
    bootstrap_admin = import_module("bootstrap_admin")

    for argv in (
        [],
        ["--confirm-empty-install=true"],
        ["--confirm-empty-install", "extra"],
        ["--confirm-empty-install", "--email", "private@school.edu"],
    ):
        stdout = io.StringIO()
        stderr = io.StringIO()

        result = bootstrap_admin.main(
            argv,
            input_fn=lambda _prompt: pytest.fail("invalid arguments must not prompt"),
            password_fn=lambda _prompt: pytest.fail("invalid arguments must not prompt"),
            stdout=stdout,
            stderr=stderr,
        )

        assert result == 1
        assert stdout.getvalue() == ""
        assert stderr.getvalue() == ("bootstrap-admin: failed code=arguments_invalid\n")
        assert "private@school.edu" not in stderr.getvalue()


def test_bootstrap_is_standalone_and_never_reads_admin_credentials_from_environment():
    source = BOOTSTRAP_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        alias.name for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom)) for alias in node.names
    }

    assert "main" not in imports
    assert "from main import" not in source
    assert "import main" not in source
    assert "os.getenv" not in source
    assert "os.environ" not in source
    assert "ADMIN_PASSWORD" not in source
    assert "ADMIN_EMAIL" not in source


@pytest.mark.parametrize(
    ("settings", "engine", "expected_code"),
    [
        (_settings(app_env="test"), _RecordingEngine(), "config_invalid"),
        (_settings(), _RecordingEngine(dialect="sqlite"), "database_invalid"),
        (
            _settings(upload_registry_schema_ready=False),
            _RecordingEngine(),
            "config_invalid",
        ),
    ],
)
def test_bootstrap_requires_production_postgresql_and_runtime_attestations(settings, engine, expected_code):
    bootstrap_admin = import_module("bootstrap_admin")
    prompted = []

    result, stdout, stderr, selected_engine = _run_bootstrap(
        bootstrap_admin,
        settings=settings,
        engine=engine,
        input_fn=lambda prompt: prompted.append(prompt),
    )

    assert result == 1
    assert stdout == ""
    assert stderr == f"bootstrap-admin: failed code={expected_code}\n"
    assert prompted == []
    assert selected_engine.commits == 0


def test_bootstrap_runs_database_readiness_before_opening_creation_transaction():
    bootstrap_admin = import_module("bootstrap_admin")
    engine = _RecordingEngine()
    events = []

    result, stdout, stderr, _ = _run_bootstrap(
        bootstrap_admin,
        engine=engine,
        readiness_check=lambda candidate: events.append(("ready", candidate)),
        identity_check=lambda _connection: events.append(("identity", None)),
        head_check=lambda _connection: events.append(("head", None)),
    )

    assert result == 0
    assert stdout == "bootstrap-admin: created\n"
    assert stderr == ""
    assert events[0] == ("ready", engine)
    assert engine.events[0] == ("transaction", "begin", None)
    assert [event[0] for event in events] == ["ready", "identity", "head"]


def test_bootstrap_readiness_failure_is_bounded_and_never_prompts():
    bootstrap_admin = import_module("bootstrap_admin")
    sensitive = "synthetic-database-password"

    def fail_readiness(_engine):
        raise RuntimeError(sensitive)

    result, stdout, stderr, engine = _run_bootstrap(
        bootstrap_admin,
        readiness_check=fail_readiness,
        input_fn=lambda _prompt: pytest.fail("unready database must not prompt"),
    )

    assert result == 1
    assert stdout == ""
    assert stderr == "bootstrap-admin: failed code=database_unready\n"
    assert sensitive not in stderr
    assert engine.events == []


@pytest.mark.parametrize(
    ("failure_point", "expected_code"),
    [("identity", "database_unready"), ("head", "schema_mismatch")],
)
def test_bootstrap_rechecks_runtime_identity_and_head_inside_the_transaction(failure_point, expected_code):
    bootstrap_admin = import_module("bootstrap_admin")
    secret = "private-driver-diagnostic"

    def identity_check(_connection):
        if failure_point == "identity":
            raise RuntimeError(secret)

    def head_check(_connection):
        if failure_point == "head":
            raise RuntimeError(secret)

    result, stdout, stderr, engine = _run_bootstrap(
        bootstrap_admin,
        identity_check=identity_check,
        head_check=head_check,
        input_fn=lambda _prompt: pytest.fail("failed checks must not prompt"),
    )

    assert result == 1
    assert stdout == ""
    assert stderr == f"bootstrap-admin: failed code={expected_code}\n"
    assert secret not in stderr
    assert engine.rollbacks == 1
    assert engine.inserts == []


def test_dynamic_head_check_compares_the_live_connection_to_current_script_head(
    monkeypatch,
):
    bootstrap_admin = import_module("bootstrap_admin")
    connection = object()
    observed = {}

    class Scripts:
        @staticmethod
        def get_current_head():
            return "reviewed-head"

    class Context:
        @staticmethod
        def get_current_revision():
            return "reviewed-head"

    def scripts_from_config(config):
        observed["config"] = config
        return Scripts()

    def context_from_connection(selected):
        observed["connection"] = selected
        return Context()

    monkeypatch.setattr(
        bootstrap_admin.ScriptDirectory,
        "from_config",
        scripts_from_config,
    )
    monkeypatch.setattr(
        bootstrap_admin.MigrationContext,
        "configure",
        context_from_connection,
    )

    bootstrap_admin._verify_alembic_head(connection)

    assert observed["connection"] is connection
    assert observed["config"].config_file_name.endswith("alembic.ini")


def test_dynamic_head_check_rejects_missing_or_mismatched_revisions(monkeypatch):
    bootstrap_admin = import_module("bootstrap_admin")

    for expected, current in ((None, None), ("head", None), ("head", "old")):
        scripts = SimpleNamespace(get_current_head=lambda expected=expected: expected)
        context = SimpleNamespace(get_current_revision=lambda current=current: current)
        monkeypatch.setattr(
            bootstrap_admin.ScriptDirectory,
            "from_config",
            lambda _config, scripts=scripts: scripts,
        )
        monkeypatch.setattr(
            bootstrap_admin.MigrationContext,
            "configure",
            lambda _connection, context=context: context,
        )

        with pytest.raises(RuntimeError, match="schema"):
            bootstrap_admin._verify_alembic_head(object())


def test_bootstrap_serializes_then_locks_users_and_checks_empty_before_prompting():
    bootstrap_admin = import_module("bootstrap_admin")
    engine = _RecordingEngine(user_count=1)
    prompted = []

    result, stdout, stderr, _ = _run_bootstrap(
        bootstrap_admin,
        engine=engine,
        identity_check=lambda _connection: engine.events.append(("check", "identity", None)),
        head_check=lambda _connection: engine.events.append(("check", "head", None)),
        input_fn=lambda prompt: prompted.append(prompt),
    )

    assert result == 1
    assert stdout == ""
    assert stderr == "bootstrap-admin: failed code=users_exist\n"
    assert prompted == []
    assert engine.rollbacks == 1
    assert engine.inserts == []

    flattened = [event[1].lower() for event in engine.events]
    advisory = next(index for index, sql in enumerate(flattened) if "pg_advisory_xact_lock" in sql)
    table_lock = next(
        index for index, sql in enumerate(flattened) if "lock table public.users in share row exclusive mode" in sql
    )
    identity = flattened.index("identity")
    head = flattened.index("head")
    count = next(index for index, sql in enumerate(flattened) if "count(*)" in sql and "public.users" in sql)

    assert advisory < table_lock < identity < head < count
    advisory_event = engine.events[advisory]
    assert advisory_event[2] == {"lock_id": bootstrap_admin.BOOTSTRAP_LOCK_ID}
    assert -(2**63) <= bootstrap_admin.BOOTSTRAP_LOCK_ID < 2**63


def test_success_creates_only_one_active_verified_admin_with_normalized_identity():
    bootstrap_admin = import_module("bootstrap_admin")
    import models

    engine = _RecordingEngine()
    local_time = datetime(
        2026,
        9,
        4,
        12,
        30,
        45,
        123456,
        tzinfo=timezone(timedelta(hours=-4)),
    )

    result, stdout, stderr, _ = _run_bootstrap(
        bootstrap_admin,
        engine=engine,
        input_fn=_answers(" RootAdmin ", " Admin@SCHOOL.EDU "),
        now_fn=lambda: local_time,
    )

    assert result == 0
    assert stdout == "bootstrap-admin: created\n"
    assert stderr == ""
    assert engine.commits == 1
    assert engine.rollbacks == 0
    assert len(engine.inserts) == 1
    assert engine.inserts[0] == {
        "username": "RootAdmin",
        "email": "admin@school.edu",
        "password": "reviewed-password-hash",
        "role": models.UserRole.ADMIN,
        "is_admin": True,
        "disabled_at": None,
        "email_verified_at": datetime(2026, 9, 4, 16, 30, 45, 123456),
    }
    all_sql = "\n".join(event[1] for event in engine.events if event[0] == "sql")
    assert "email_verifications" not in all_sql
    assert "browser_sessions" not in all_sql
    assert "password_resets" not in all_sql


@pytest.mark.parametrize(
    ("username", "email", "password", "confirmation"),
    [
        ("ab", "admin@school.edu", GOOD_PASSWORD, GOOD_PASSWORD),
        ("RootAdmin", "not-an-email", GOOD_PASSWORD, GOOD_PASSWORD),
        ("RootAdmin", "admin@outside.edu", GOOD_PASSWORD, GOOD_PASSWORD),
        ("RootAdmin", "admin@school.edu", "weak", "weak"),
        ("RootAdmin", "admin@school.edu", GOOD_PASSWORD, GOOD_PASSWORD + "x"),
    ],
)
def test_invalid_admin_credentials_rollback_without_inserting(username, email, password, confirmation):
    bootstrap_admin = import_module("bootstrap_admin")

    result, stdout, stderr, engine = _run_bootstrap(
        bootstrap_admin,
        input_fn=_answers(username, email),
        password_fn=_answers(password, confirmation),
    )

    assert result == 1
    assert stdout == ""
    assert stderr == "bootstrap-admin: failed code=credentials_invalid\n"
    assert engine.inserts == []
    assert engine.commits == 0
    assert engine.rollbacks == 1


@pytest.mark.parametrize("failure", ["cancel", "hash"])
def test_cancellation_and_hash_failure_rollback_with_bounded_output(failure):
    bootstrap_admin = import_module("bootstrap_admin")
    sensitive = "NeverEchoThisAdminPassword!2026"

    def cancelled(_prompt):
        raise KeyboardInterrupt(sensitive)

    def failed_hash(_password):
        raise RuntimeError(sensitive)

    result, stdout, stderr, engine = _run_bootstrap(
        bootstrap_admin,
        input_fn=(cancelled if failure == "cancel" else _answers("RootAdmin", "admin@school.edu")),
        password_fn=_answers(sensitive, sensitive),
        password_hasher=(failed_hash if failure == "hash" else lambda value: value),
    )

    assert result == 1
    assert stdout == ""
    expected_code = "cancelled" if failure == "cancel" else "creation_failed"
    assert stderr == f"bootstrap-admin: failed code={expected_code}\n"
    assert sensitive not in stdout + stderr
    assert engine.inserts == []
    assert engine.commits == 0
    assert engine.rollbacks == 1


def test_failures_never_log_or_reflect_prompted_secrets(caplog):
    bootstrap_admin = import_module("bootstrap_admin")
    private_email = "admin-secret@school.edu"
    private_password = "NeverReflectThisPassword!2026"

    def failed_hash(_password):
        raise RuntimeError(f"{private_email} {private_password}")

    result, stdout, stderr, _ = _run_bootstrap(
        bootstrap_admin,
        input_fn=_answers("RootAdmin", private_email),
        password_fn=_answers(private_password, private_password),
        password_hasher=failed_hash,
    )

    assert result == 1
    assert stdout == ""
    assert stderr == "bootstrap-admin: failed code=creation_failed\n"
    assert private_email not in stdout + stderr + caplog.text
    assert private_password not in stdout + stderr + caplog.text


@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL", "").startswith("postgresql"),
    reason="requires the guarded disposable PostgreSQL test database",
)
def test_postgresql_bootstrap_rolls_back_failures_and_allows_one_concurrent_winner(
    database_guard,
):
    bootstrap_admin = import_module("bootstrap_admin")
    auth_security = import_module("auth_security")
    base = import_module("base")
    database = import_module("database")
    models = import_module("models")
    engine = database.engine
    database_guard(engine)

    base.Base.metadata.drop_all(bind=engine)
    base.Base.metadata.create_all(bind=engine)

    settings = _settings()

    def invoke(index, *, password_fn=None, input_fn=None, password_hasher=None):
        return _run_bootstrap(
            bootstrap_admin,
            engine=engine,
            settings=settings,
            input_fn=input_fn or _answers(f"RootAdmin{index}", f"admin{index}@school.edu"),
            password_fn=password_fn or _answers(GOOD_PASSWORD, GOOD_PASSWORD),
            password_hasher=password_hasher or auth_security.hash_password,
            readiness_check=lambda _engine: None,
            identity_check=lambda _connection: None,
            head_check=lambda _connection: None,
        )[:3]

    try:
        mismatch = invoke(
            0,
            password_fn=_answers(GOOD_PASSWORD, GOOD_PASSWORD + "mismatch"),
        )
        assert mismatch == (
            1,
            "",
            "bootstrap-admin: failed code=credentials_invalid\n",
        )

        cancelled = invoke(
            0,
            input_fn=lambda _prompt: (_ for _ in ()).throw(KeyboardInterrupt()),
        )
        assert cancelled == (
            1,
            "",
            "bootstrap-admin: failed code=cancelled\n",
        )

        failed = invoke(
            0,
            password_hasher=lambda _password: (_ for _ in ()).throw(RuntimeError("private hashing diagnostic")),
        )
        assert failed == (
            1,
            "",
            "bootstrap-admin: failed code=creation_failed\n",
        )

        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM public.users")).scalar_one() == 0

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(invoke, (1, 2)))

        assert sorted(result[0] for result in results) == [0, 1]
        assert sum(result[1] == "bootstrap-admin: created\n" for result in results) == 1
        assert sum(result[2] == "bootstrap-admin: failed code=users_exist\n" for result in results) == 1

        with engine.connect() as connection:
            users = connection.execute(select(models.User)).mappings().all()
            assert len(users) == 1
            user = users[0]
            assert user["role"] is models.UserRole.ADMIN
            assert user["is_admin"] is True
            assert user["disabled_at"] is None
            assert user["email_verified_at"] is not None
            assert auth_security.verify_password(GOOD_PASSWORD, user["password"])
            for table_name in (
                "email_verifications",
                "browser_sessions",
                "password_resets",
            ):
                assert connection.execute(text(f"SELECT count(*) FROM public.{table_name}")).scalar_one() == 0
    finally:
        database_guard(engine)
        base.Base.metadata.drop_all(bind=engine)
