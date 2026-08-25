from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import stat
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

ROLE_PASSWORD_ENV = {
    "litblogs_migrator": "E2E_MIGRATOR_PASSWORD",
    "litblogs_runtime": "E2E_RUNTIME_PASSWORD",
    "litblog_account_operator": "E2E_ACCOUNT_OPERATOR_PASSWORD",
    "litblog_invitation_operator": "E2E_INVITATION_OPERATOR_PASSWORD",
}
IDENTITY_OWNER_ROLE = "litblog_identity_owner"
APPLICATION_ROLES = (
    "litblogs_migrator",
    "litblogs_runtime",
    IDENTITY_OWNER_ROLE,
    "litblog_account_operator",
    "litblog_invitation_operator",
)
DATABASE_NAME_PATTERN = re.compile(r"^litblog_test_e2e_[a-z0-9]{16,40}$")
DISPOSABLE_CONFIRMATION = "litblogs-e2e-only"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1"})


def _database_name() -> str:
    name = os.environ["E2E_DATABASE_NAME"]
    if not DATABASE_NAME_PATTERN.fullmatch(name):
        raise RuntimeError("E2E database name is outside the disposable namespace")
    return name


def _postgres_url(raw_url: str):
    url = make_url(raw_url)
    if not url.drivername.startswith("postgresql"):
        raise RuntimeError("E2E admin database URL must use PostgreSQL")
    return url.set(drivername="postgresql+psycopg2")


def _validated_admin_url():
    if os.environ.get("E2E_DISPOSABLE_DATABASE_CONFIRMED") != DISPOSABLE_CONFIRMATION:
        raise RuntimeError("E2E PostgreSQL disposal was not explicitly confirmed")
    url = _postgres_url(os.environ["E2E_ADMIN_DATABASE_URL"])
    if (
        url.host not in LOOPBACK_HOSTS
        or url.database != "postgres"
        or not url.username
        or set(url.query) & {"database", "dbname", "host", "hostaddr", "service"}
    ):
        raise RuntimeError(
            "E2E admin URL must target the loopback postgres database without overrides"
        )
    if url.username in APPLICATION_ROLES:
        raise RuntimeError("E2E admin URL cannot use an application role")
    return url


def _engine(raw_url: str):
    return create_engine(
        _postgres_url(raw_url),
        isolation_level="AUTOCOMMIT",
        pool_pre_ping=True,
        connect_args={"connect_timeout": 5},
    )


def _require_postgres_17(connection) -> None:
    version_number = int(
        connection.exec_driver_sql("SHOW server_version_num").scalar_one()
    )
    if not 170_000 <= version_number < 180_000:
        raise RuntimeError("Browser journeys require an exact PostgreSQL 17 service")


def _role_url(admin_url: str, *, role: str, password: str, database: str) -> str:
    return _postgres_url(admin_url).set(
        username=role,
        password=password,
        database=database,
    ).render_as_string(hide_password=False)


def _drop_database(connection, database_name: str) -> None:
    connection.exec_driver_sql(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        "WHERE datname = %s AND pid <> pg_backend_pid()",
        (database_name,),
    )
    connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{database_name}"')


def _drop_roles(connection, roles: list[str] | tuple[str, ...]) -> None:
    existing_roles = set(
        connection.execute(
            text(
                "SELECT rolname FROM pg_roles "
                "WHERE rolname = ANY(CAST(:roles AS text[]))"
            ),
            {"roles": list(roles)},
        ).scalars()
    )
    if {IDENTITY_OWNER_ROLE, "litblogs_migrator"} <= existing_roles:
        connection.exec_driver_sql(
            "REVOKE litblog_identity_owner FROM litblogs_migrator"
        )
    for role in reversed(tuple(roles)):
        if role not in existing_roles:
            continue
        connection.exec_driver_sql(f'DROP ROLE IF EXISTS "{role}"')


def bootstrap() -> None:
    admin_url = _validated_admin_url().render_as_string(hide_password=False)
    database_name = _database_name()
    metadata_path = Path(os.environ["E2E_DATABASE_METADATA_FILE"]).resolve()
    passwords = {
        role: os.environ[environment_name]
        for role, environment_name in ROLE_PASSWORD_ENV.items()
    }
    if any(len(value.encode("utf-8")) < 32 for value in passwords.values()):
        raise RuntimeError("E2E database role password is too short")

    created_roles: list[str] = []
    database_created = False
    admin_engine = _engine(admin_url)
    try:
        with admin_engine.connect() as connection:
            _require_postgres_17(connection)
            existing_roles = connection.execute(
                text(
                    "SELECT rolname FROM pg_roles "
                    "WHERE rolname = ANY(CAST(:roles AS text[]))"
                ),
                {"roles": list(APPLICATION_ROLES)},
            ).scalars().all()
            if existing_roles:
                raise RuntimeError(
                    "E2E PostgreSQL service is not disposable: application roles already exist"
                )
            database_exists = connection.execute(
                text("SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname = :name)"),
                {"name": database_name},
            ).scalar_one()
            if database_exists:
                raise RuntimeError("E2E database name unexpectedly already exists")

            for role in (
                "litblogs_migrator",
                "litblogs_runtime",
                "litblog_account_operator",
                "litblog_invitation_operator",
            ):
                connection.exec_driver_sql(
                    f'CREATE ROLE "{role}" LOGIN NOINHERIT NOSUPERUSER '
                    "NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD %s",
                    (passwords[role],),
                )
                created_roles.append(role)
            connection.exec_driver_sql(
                f'CREATE ROLE "{IDENTITY_OWNER_ROLE}" NOLOGIN NOINHERIT '
                "NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
            )
            created_roles.append(IDENTITY_OWNER_ROLE)
            connection.exec_driver_sql(
                "GRANT litblog_identity_owner TO litblogs_migrator "
                "WITH ADMIN FALSE, INHERIT TRUE, SET TRUE"
            )
            connection.exec_driver_sql(
                f'CREATE DATABASE "{database_name}" OWNER litblogs_migrator '
                "TEMPLATE template0 ENCODING 'UTF8'"
            )
            database_created = True
            connection.exec_driver_sql(
                f'REVOKE CONNECT, TEMPORARY ON DATABASE "{database_name}" FROM PUBLIC'
            )
            connection.exec_driver_sql(
                f'GRANT CONNECT ON DATABASE "{database_name}" TO litblogs_runtime'
            )
            connection.exec_driver_sql(
                "ALTER ROLE litblogs_runtime SET search_path = public"
            )

        target_admin_url = _postgres_url(admin_url).set(database=database_name)
        target_engine = _engine(target_admin_url.render_as_string(hide_password=False))
        try:
            with target_engine.connect() as connection:
                connection.exec_driver_sql(
                    "ALTER SCHEMA public OWNER TO litblogs_migrator"
                )
        finally:
            target_engine.dispose()

        metadata = {
            "database_name": database_name,
            "migrator_url": _role_url(
                admin_url,
                role="litblogs_migrator",
                password=passwords["litblogs_migrator"],
                database=database_name,
            ),
            "runtime_url": _role_url(
                admin_url,
                role="litblogs_runtime",
                password=passwords["litblogs_runtime"],
                database=database_name,
            ),
        }
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        try:
            metadata_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
    except Exception:
        with admin_engine.connect() as connection:
            if database_created:
                _drop_database(connection, database_name)
            if created_roles:
                _drop_roles(connection, created_roles)
        raise
    finally:
        admin_engine.dispose()


def finalize_acl() -> None:
    admin_url = _validated_admin_url().render_as_string(hide_password=False)
    database_name = _database_name()
    metadata = json.loads(
        Path(os.environ["E2E_DATABASE_METADATA_FILE"]).read_text(encoding="utf-8")
    )
    admin_engine = _engine(admin_url)
    try:
        with admin_engine.connect() as connection:
            _require_postgres_17(connection)
            connection.exec_driver_sql(
                "REVOKE litblog_identity_owner FROM litblogs_migrator"
            )
            role_rows = connection.execute(
                text(
                    "SELECT rolname, rolsuper, rolinherit, rolcreaterole, "
                    "rolcreatedb, rolcanlogin, rolreplication, rolbypassrls, "
                    "COALESCE(rolpassword LIKE 'SCRAM-SHA-256$%', FALSE) AS scram "
                    "FROM pg_authid WHERE rolname = ANY(CAST(:roles AS text[])) "
                    "ORDER BY rolname"
                ),
                {"roles": list(APPLICATION_ROLES)},
            ).all()
            if len(role_rows) != len(APPLICATION_ROLES):
                raise RuntimeError("E2E application role set is incomplete")
            expected_login_roles = set(ROLE_PASSWORD_ENV)
            for row in role_rows:
                expected_login = row.rolname in expected_login_roles
                if tuple(row[1:8]) != (
                    False,
                    False,
                    False,
                    False,
                    expected_login,
                    False,
                    False,
                ):
                    raise RuntimeError("E2E application role attributes are not exact")
                if expected_login and not row.scram:
                    raise RuntimeError("E2E application credentials are not stored as SCRAM")
            membership_count = connection.execute(
                text(
                    "SELECT COUNT(*) FROM pg_auth_members AS membership "
                    "JOIN pg_roles AS granted ON granted.oid = membership.roleid "
                    "JOIN pg_roles AS member ON member.oid = membership.member "
                    "WHERE granted.rolname = ANY(CAST(:roles AS text[])) "
                    "OR member.rolname = ANY(CAST(:roles AS text[]))"
                ),
                {"roles": list(APPLICATION_ROLES)},
            ).scalar_one()
            if membership_count != 0:
                raise RuntimeError("E2E application role membership was not removed")
            database_acl = connection.execute(
                text(
                    "SELECT "
                    "has_database_privilege('litblogs_runtime', :database, 'CONNECT'), "
                    "has_database_privilege('litblogs_runtime', :database, 'CREATE'), "
                    "has_database_privilege('litblogs_runtime', :database, 'TEMPORARY'), "
                    "EXISTS(SELECT 1 FROM pg_database AS database, "
                    "LATERAL aclexplode(COALESCE(database.datacl, "
                    "acldefault('d', database.datdba))) AS privilege "
                    "WHERE database.datname = :database "
                    "AND privilege.grantee = 0 "
                    "AND privilege.privilege_type = 'CONNECT'), "
                    "EXISTS(SELECT 1 FROM pg_database AS database, "
                    "LATERAL aclexplode(COALESCE(database.datacl, "
                    "acldefault('d', database.datdba))) AS privilege "
                    "WHERE database.datname = :database "
                    "AND privilege.grantee = 0 "
                    "AND privilege.privilege_type = 'TEMPORARY')"
                ),
                {"database": database_name},
            ).one()
            if tuple(database_acl) != (True, False, False, False, False):
                raise RuntimeError("E2E runtime database privileges are not exact")

        wrong_password_url = _postgres_url(metadata["runtime_url"]).set(
            password=secrets.token_urlsafe(48)
        )
        wrong_password_engine = _engine(
            wrong_password_url.render_as_string(hide_password=False)
        )
        try:
            try:
                with wrong_password_engine.connect() as connection:
                    connection.execute(text("SELECT 1"))
            except OperationalError:
                pass
            else:
                raise RuntimeError("E2E PostgreSQL accepted an invalid runtime password")
        finally:
            wrong_password_engine.dispose()

        runtime_engine = _engine(metadata["runtime_url"])
        try:
            with runtime_engine.connect() as connection:
                identity = connection.execute(
                    text("SELECT session_user, current_user")
                ).one()
                if tuple(identity) != ("litblogs_runtime", "litblogs_runtime"):
                    raise RuntimeError("E2E runtime database identity is incorrect")
        finally:
            runtime_engine.dispose()
    finally:
        admin_engine.dispose()


def cleanup() -> None:
    admin_url = _validated_admin_url().render_as_string(hide_password=False)
    database_name = _database_name()
    admin_engine = _engine(admin_url)
    try:
        with admin_engine.connect() as connection:
            _require_postgres_17(connection)
            _drop_database(connection, database_name)
            _drop_roles(connection, APPLICATION_ROLES)
            remaining = connection.execute(
                text(
                    "SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname = :database) "
                    "OR EXISTS(SELECT 1 FROM pg_roles "
                    "WHERE rolname = ANY(CAST(:roles AS text[])))"
                ),
                {"database": database_name, "roles": list(APPLICATION_ROLES)},
            ).scalar_one()
            if remaining:
                raise RuntimeError("E2E PostgreSQL cleanup was incomplete")
    finally:
        admin_engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("bootstrap", "finalize-acl", "cleanup"))
    args = parser.parse_args()
    if args.command == "bootstrap":
        bootstrap()
    elif args.command == "finalize-acl":
        finalize_acl()
    else:
        cleanup()


if __name__ == "__main__":
    main()
