import pytest
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

EXPECTED_RUNTIME_BOUNDARY = (
    "litblogs_runtime",
    "litblogs_runtime",
    False,
    False,
    False,
    False,
    True,
    False,
    False,
    False,
    True,
    False,
    False,
    False,
    True,
)


class _RoleResult:
    def __init__(self, record):
        self._record = record

    def one(self):
        return self._record


class _RecordingConnection:
    def __init__(self, record=EXPECTED_RUNTIME_BOUNDARY):
        self.record = record
        self.statements = []

    def execute(self, statement):
        self.statements.append(str(statement))
        return _RoleResult(self.record)


class _ReadinessConnection:
    def __init__(self):
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.closed = True

    def execute(self, _statement):
        return None


class _ReadinessEngine:
    def __init__(self, connection):
        self.connection = connection
        self.dialect = type("Dialect", (), {"name": "postgresql"})()

    def connect(self):
        return self.connection


def test_runtime_database_identity_accepts_only_the_exact_runtime_boundary():
    import database

    connection = _RecordingConnection()

    database.verify_runtime_database_identity(connection)

    statement = " ".join(connection.statements[0].lower().split())
    assert "session_user" in statement
    assert "current_user" in statement
    assert "pg_catalog.pg_auth_members" in statement
    assert "pg_catalog.has_schema_privilege" in statement
    assert "pg_catalog.has_database_privilege" in statement
    assert "pg_catalog.current_schemas(false)" in statement


@pytest.mark.parametrize("field_index", range(len(EXPECTED_RUNTIME_BOUNDARY)))
def test_runtime_database_identity_rejects_every_boundary_mismatch(field_index):
    import database

    mismatched = list(EXPECTED_RUNTIME_BOUNDARY)
    value = mismatched[field_index]
    mismatched[field_index] = not value if isinstance(value, bool) else "unexpected_role"

    with pytest.raises(RuntimeError, match="privilege boundary"):
        database.verify_runtime_database_identity(_RecordingConnection(tuple(mismatched)))


def test_postgresql_readiness_invokes_runtime_identity_verification(monkeypatch):
    import database

    calls = []
    connection = _ReadinessConnection()
    candidate_engine = _ReadinessEngine(connection)

    monkeypatch.setattr(database, "verify_runtime_database_identity", calls.append)
    monkeypatch.setattr(
        database,
        "verify_database_schema",
        lambda engine: calls.append((engine, connection.closed)),
    )
    monkeypatch.setattr(
        ScriptDirectory,
        "from_config",
        lambda _config: type("Scripts", (), {"get_current_head": lambda _self: "head"})(),
    )
    monkeypatch.setattr(
        MigrationContext,
        "configure",
        lambda _connection: type(
            "Context",
            (),
            {"get_current_revision": lambda _self: "head"},
        )(),
    )

    database.check_database_readiness(candidate_engine)

    assert calls == [connection, (candidate_engine, True)]
