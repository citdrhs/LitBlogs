from __future__ import annotations

from dataclasses import dataclass

import pytest

from e2e.support import database


@dataclass
class _ScalarResult:
    values: tuple[str, ...]

    def scalars(self):
        return iter(self.values)


class _RecordingConnection:
    def __init__(self, *, roles=(), version="170006"):
        self.roles = tuple(roles)
        self.version = version
        self.commands: list[str] = []

    def execute(self, _statement, _parameters):
        return _ScalarResult(self.roles)

    def exec_driver_sql(self, statement, _parameters=None):
        self.commands.append(statement)
        if statement == "SHOW server_version_num":
            return _VersionResult(self.version)
        return None


@dataclass
class _VersionResult:
    version: str

    def scalar_one(self):
        return self.version


def test_admin_url_requires_explicit_loopback_postgres_disposal(monkeypatch):
    monkeypatch.setenv(
        "E2E_ADMIN_DATABASE_URL",
        "postgresql+psycopg2://cluster-admin:strong-password@127.0.0.1:5432/postgres",
    )
    monkeypatch.delenv("E2E_DISPOSABLE_DATABASE_CONFIRMED", raising=False)
    with pytest.raises(RuntimeError, match="not explicitly confirmed"):
        database._validated_admin_url()

    monkeypatch.setenv(
        "E2E_DISPOSABLE_DATABASE_CONFIRMED",
        database.DISPOSABLE_CONFIRMATION,
    )
    assert database._validated_admin_url().database == "postgres"

    monkeypatch.setenv(
        "E2E_ADMIN_DATABASE_URL",
        "postgresql+psycopg2://cluster-admin:strong-password@localhost:5432/postgres",
    )
    with pytest.raises(RuntimeError, match="loopback postgres database"):
        database._validated_admin_url()

    monkeypatch.setenv(
        "E2E_ADMIN_DATABASE_URL",
        "postgresql+psycopg2://cluster-admin:strong-password@db.school.edu/litblogs",
    )
    with pytest.raises(RuntimeError, match="loopback postgres database"):
        database._validated_admin_url()


@pytest.mark.parametrize("version", ["160012", "180000"])
def test_postgres_version_guard_rejects_non_17(version):
    with pytest.raises(RuntimeError, match="exact PostgreSQL 17"):
        database._require_postgres_17(_RecordingConnection(version=version))


def test_postgres_version_guard_accepts_17():
    database._require_postgres_17(_RecordingConnection(version="170006"))


def test_partial_bootstrap_cleanup_drops_only_roles_that_exist():
    connection = _RecordingConnection(
        roles=("litblogs_migrator", "litblogs_runtime"),
    )

    database._drop_roles(connection, database.APPLICATION_ROLES)

    assert connection.commands == [
        'DROP ROLE IF EXISTS "litblogs_runtime"',
        'DROP ROLE IF EXISTS "litblogs_migrator"',
    ]


def test_complete_cleanup_revokes_temporary_membership_before_drop():
    connection = _RecordingConnection(roles=database.APPLICATION_ROLES)

    database._drop_roles(connection, database.APPLICATION_ROLES)

    assert connection.commands[0] == (
        "REVOKE litblog_identity_owner FROM litblogs_migrator"
    )
    assert connection.commands[1:] == [
        f'DROP ROLE IF EXISTS "{role}"'
        for role in reversed(database.APPLICATION_ROLES)
    ]
