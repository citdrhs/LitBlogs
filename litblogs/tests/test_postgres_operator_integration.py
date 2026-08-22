import hashlib
import os
import secrets
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import NullPool

ROOT_DIR = Path(__file__).resolve().parents[2]
OPERATOR_SCRIPTS = ROOT_DIR / "deploy" / "scripts"
sys.path.insert(0, str(OPERATOR_SCRIPTS))

from backup_postgres import main as backup_main  # noqa: E402
from backup_postgres import validate_backup_principal  # noqa: E402
from postgres_common import (  # noqa: E402
    POSTGRES_CLIENT_NAMES,
    POSTGRES_VERSION,
    PostgresOperatorError,
    build_pg_environment,
    parse_postgres_url,
    postgres_executable,
)
from restore_verify_postgres import (  # noqa: E402
    EXPECTED_OPERATOR_ROUTINE_CONTRACT,
    IDENTITY_DATA_INTEGRITY_SQL,
    check_alembic_schema_drift,
)
from restore_verify_postgres import (  # noqa: E402
    main as restore_main,
)
from upload_snapshot_common import synthetic_upload_custody  # noqa: E402

CONTAINER_ID = os.environ.get("POSTGRES_OPERATOR_CONTAINER_ID", "")
BACKUP_DATABASE_URL = os.environ.get("POSTGRES_OPERATOR_BACKUP_DATABASE_URL", "")
RESTORE_DATABASE_URL = os.environ.get("POSTGRES_OPERATOR_RESTORE_DATABASE_URL", "")


class PinnedContainerPostgresRunner:
    """Run the scripts' exact pg argv with clients from the pinned service image."""

    def __init__(self, container_id: str):
        self.container_id = container_id

    def _docker_command(self, command, environment):
        docker_command = ["docker", "exec"]
        for name, value in sorted(environment.items()):
            if name.startswith("PG"):
                # The pinned CI service is loopback-only and has no TLS listener.
                # Production parsing stays verify-full; only this test transport
                # adapts libpq after the strict URL has been validated.
                if name == "PGSSLMODE":
                    value = "disable"
                docker_command.extend(["--env", f"{name}={value}"])
        docker_command.extend([self.container_id, *command])
        return docker_command

    def __call__(
        self,
        command,
        *,
        env,
        check,
        shell,
        stdout,
        stderr,
        text,
    ):
        assert check is False
        assert shell is False
        assert stderr == subprocess.PIPE
        assert text is True

        selected_command = list(command)
        host_executable = selected_command[0]
        assert host_executable.startswith("/usr/lib/postgresql/17/bin/")
        executable = Path(host_executable).name
        selected_command[0] = executable
        if "--version" in selected_command:
            result = subprocess.run(  # noqa: S603
                self._docker_command(selected_command, env),
                check=False,
                shell=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            return subprocess.CompletedProcess(
                command,
                result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        if executable == "pg_dump":
            file_index = selected_command.index("--file") + 1
            host_output = Path(selected_command[file_index])
            selected_command[file_index] = "/dev/stdout"
            with host_output.open("wb") as output_file:
                result = subprocess.run(  # noqa: S603
                    self._docker_command(selected_command, env),
                    check=False,
                    shell=False,
                    stdout=output_file,
                    stderr=subprocess.PIPE,
                )
            return subprocess.CompletedProcess(
                command,
                result.returncode,
                stdout=None,
                stderr=result.stderr.decode("utf-8", errors="replace"),
            )

        container_archive = None
        if executable == "pg_restore":
            archive = Path(selected_command[-1])
            container_archive = f"/tmp/litblogs-operator-{secrets.token_hex(12)}.dump"
            copy_result = subprocess.run(  # noqa: S603
                ["docker", "cp", str(archive), f"{self.container_id}:{container_archive}"],
                check=False,
                shell=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
            if copy_result.returncode != 0:
                return subprocess.CompletedProcess(
                    command,
                    copy_result.returncode,
                    stdout=None,
                    stderr="PostgreSQL archive transport failed",
                )
            selected_command[-1] = container_archive

        try:
            result = subprocess.run(  # noqa: S603
                self._docker_command(selected_command, env),
                check=False,
                shell=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            return subprocess.CompletedProcess(
                command,
                result.returncode,
                stdout=result.stdout if stdout == subprocess.PIPE else None,
                stderr=result.stderr,
            )
        finally:
            if container_archive:
                subprocess.run(  # noqa: S603
                    ["docker", "exec", self.container_id, "rm", "-f", container_archive],
                    check=False,
                    shell=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

    def drop_database(self, database_url: str, database_name: str) -> None:
        connection = parse_postgres_url(database_url)
        environment = build_pg_environment(connection, database="postgres")
        subprocess.run(  # noqa: S603
            self._docker_command(
                [
                    "dropdb",
                    "--if-exists",
                    "--maintenance-db=postgres",
                    "--no-password",
                    database_name,
                ],
                environment,
            ),
            check=False,
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )


def _run_psql(runner, database_url: str, database: str, sql: str, *, sentinel: str):
    connection = parse_postgres_url(database_url)
    environment = build_pg_environment(connection, database=database)
    result = runner(
        [
            postgres_executable("psql"),
            "--no-psqlrc",
            "--no-password",
            "--tuples-only",
            "--no-align",
            "--set=ON_ERROR_STOP=1",
            f"--set=sentinel={sentinel}",
            "--command",
            sql,
        ],
        env=environment,
        check=False,
        shell=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert result.returncode == 0, "synthetic PostgreSQL sentinel operation failed"
    return (result.stdout or "").strip()


def _ci_database_url(
    database_url: str,
    database: str,
    *,
    username: str | None = None,
    password: str | None = None,
):
    url = make_url(database_url).difference_update_query(
        ["sslmode", "sslrootcert"]
    )
    return url.update_query_dict(
        {"connect_timeout": "5", "sslmode": "disable"}
    ).set(
        database=database,
        username=username or url.username,
        password=password if password is not None else url.password,
    )


def _seed_referential_sentinel(runner, database_url: str, sentinel: str) -> None:
    sql = """
WITH new_user AS (
    INSERT INTO users (username, email, password, first_name, last_name, role, is_admin)
    VALUES (:'sentinel', :'sentinel' || '@school.invalid', 'synthetic-not-a-login',
            'Operator', 'Sentinel', 'TEACHER', FALSE)
    RETURNING id
), new_teacher AS (
    INSERT INTO teachers (name, email, hashed_password, user_id)
    SELECT 'Operator Sentinel', :'sentinel' || '@school.invalid',
           'synthetic-not-a-login', id FROM new_user
    RETURNING id
), new_class AS (
    INSERT INTO classes (name, description, access_code, teacher_id, status, posts_visibility)
    SELECT :'sentinel', 'backup restore sentinel', SUBSTRING(:'sentinel' FROM 1 FOR 6),
           id, 'active', 'class' FROM new_teacher
    RETURNING id
)
INSERT INTO blogs (title, content, owner_id, class_id)
SELECT :'sentinel', :'sentinel', new_user.id, new_class.id
FROM new_user CROSS JOIN new_class;
"""
    source_database = parse_postgres_url(database_url).database
    _run_psql(runner, database_url, source_database, sql, sentinel=sentinel)


def _remove_referential_sentinel(runner, database_url: str, sentinel: str) -> None:
    sql = """
DELETE FROM upload_assets WHERE original_filename = :'sentinel';
DELETE FROM blogs WHERE title = :'sentinel';
DELETE FROM classes WHERE name = :'sentinel';
DELETE FROM teachers WHERE email = :'sentinel' || '@school.invalid';
DELETE FROM users WHERE username = :'sentinel';
"""
    source_database = parse_postgres_url(database_url).database
    _run_psql(runner, database_url, source_database, sql, sentinel=sentinel)


def _container_client_validator(runner, database_url: str) -> None:
    environment = build_pg_environment(parse_postgres_url(database_url))
    for command_name in sorted(POSTGRES_CLIENT_NAMES):
        result = runner(
            [postgres_executable(command_name), "--version"],
            env=environment,
            check=False,
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert result.returncode == 0
        assert POSTGRES_VERSION.fullmatch(result.stdout or "") is not None


@pytest.mark.skipif(
    not CONTAINER_ID or not BACKUP_DATABASE_URL or not RESTORE_DATABASE_URL,
    reason="requires the pinned PostgreSQL CI service container",
)
def test_real_custom_backup_restore_and_integrity_round_trip(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    runner = PinnedContainerPostgresRunner(CONTAINER_ID)
    target = f"litblog_restore_verify_ci_{secrets.token_hex(6)}"
    rogue_role = f"litblog_test_rogue_{secrets.token_hex(6)}"
    rogue_schema = f"litblog_test_extra_{secrets.token_hex(6)}"
    sentinel = f"operator_{secrets.token_hex(8)}"
    upload_payload = b"coupled operator recovery sentinel"
    storage_key = "objects/aa/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.txt"
    upload_root = tmp_path / "source-uploads"
    (upload_root / "objects" / "aa").mkdir(parents=True, mode=0o700)
    (upload_root / ".incoming").mkdir(mode=0o700)
    upload_path = upload_root / storage_key
    upload_path.write_bytes(upload_payload)
    upload_root.chmod(0o700)
    (upload_root / "objects").chmod(0o700)
    (upload_root / "objects" / "aa").chmod(0o700)
    (upload_root / ".incoming").chmod(0o700)
    upload_path.chmod(0o600)
    restore_upload_root = tmp_path / f"litblog_restore_uploads_ci_{secrets.token_hex(6)}"
    restore_upload_root.mkdir(mode=0o700)
    client_validations = []

    def validate_clients():
        _container_client_validator(runner, RESTORE_DATABASE_URL)
        client_validations.append("validated")

    def validate_test_ca(_connection):
        # The pinned CI PostgreSQL service has no TLS listener. Parser syntax is
        # still strict; production CA custody is covered by POSIX unit tests.
        return None

    def check_test_drift(connection, database):
        check_alembic_schema_drift(
            replace(connection, sslmode="disable", sslrootcert=None),
            database,
        )

    try:
        _seed_referential_sentinel(runner, RESTORE_DATABASE_URL, sentinel)
        source_database = parse_postgres_url(RESTORE_DATABASE_URL).database
        upload_insert = f"""
INSERT INTO upload_assets (
    storage_key, owner_user_id, blog_id, purpose, state,
    original_filename, media_type, size_bytes, sha256_digest,
    bound_at, scan_completed_at
)
SELECT
    '{storage_key}', users.id, blogs.id, 'POST', 'ACTIVE',
    :'sentinel', 'text/plain', {len(upload_payload)},
    '{hashlib.sha256(upload_payload).hexdigest()}', NOW(), NOW()
FROM users
JOIN blogs ON blogs.owner_id = users.id
WHERE users.username = :'sentinel' AND blogs.title = :'sentinel';
"""
        _run_psql(
            runner,
            RESTORE_DATABASE_URL,
            source_database,
            upload_insert,
            sentinel=sentinel,
        )
        monkeypatch.setenv("DATABASE_URL", BACKUP_DATABASE_URL)
        assert backup_main(
            [
                "--output-dir",
                str(tmp_path),
                "--upload-root",
                str(upload_root),
                "--confirm-writes-quiesced",
            ],
            runner=runner,
            client_validator=validate_clients,
            tls_custody_validator=validate_test_ca,
            upload_custody=synthetic_upload_custody(),
        ) == 0
        backup_connection = parse_postgres_url(BACKUP_DATABASE_URL)
        for apply_tamper, revert_tamper in (
            (
                "GRANT TEMPORARY ON DATABASE postgres TO litblogs_backup;",
                "REVOKE TEMPORARY ON DATABASE postgres FROM litblogs_backup;",
            ),
            (
                f"GRANT TEMPORARY ON DATABASE {source_database} TO litblogs_backup;",
                f"REVOKE TEMPORARY ON DATABASE {source_database} FROM litblogs_backup;",
            ),
            (
                "GRANT pg_monitor TO litblogs_backup;",
                "REVOKE pg_monitor FROM litblogs_backup;",
            ),
            (
                "GRANT pg_write_all_data TO pg_read_all_data;",
                "REVOKE pg_write_all_data FROM pg_read_all_data;",
            ),
            (
                "CREATE TYPE public.litblog_backup_owner_tamper AS ENUM ('x'); "
                "ALTER TYPE public.litblog_backup_owner_tamper "
                "OWNER TO pg_read_all_data;",
                "DROP TYPE public.litblog_backup_owner_tamper;",
            ),
        ):
            _run_psql(
                runner,
                RESTORE_DATABASE_URL,
                source_database,
                apply_tamper,
                sentinel=sentinel,
            )
            try:
                with pytest.raises(PostgresOperatorError, match="backup principal"):
                    validate_backup_principal(backup_connection, runner)
            finally:
                _run_psql(
                    runner,
                    RESTORE_DATABASE_URL,
                    source_database,
                    revert_tamper,
                    sentinel=sentinel,
                )
            validate_backup_principal(backup_connection, runner)
        archive = next(tmp_path.glob("*.dump"))
        manifest = next(tmp_path.glob("*.manifest.json"))
        monkeypatch.setenv("DATABASE_URL", RESTORE_DATABASE_URL)
        assert restore_main(
            [
                "--manifest",
                str(manifest),
                "--upload-target",
                str(restore_upload_root),
                "--target-database",
                target,
                "--confirm-target",
                target,
            ],
            runner=runner,
            client_validator=validate_clients,
            drift_checker=check_test_drift,
            tls_custody_validator=validate_test_ca,
        ) == 0

        assert archive.read_bytes().startswith(b"PGDMP")
        restored_value = _run_psql(
            runner,
            RESTORE_DATABASE_URL,
            target,
            "SELECT content FROM blogs WHERE title = :'sentinel';",
            sentinel=sentinel,
        )
        assert restored_value == sentinel
        assert (restore_upload_root / storage_key).read_bytes() == upload_payload

        def run_target_sql(sql):
            return _run_psql(
                runner,
                RESTORE_DATABASE_URL,
                target,
                sql,
                sentinel=sentinel,
            )

        def assert_integrity(expected):
            assert run_target_sql(IDENTITY_DATA_INTEGRITY_SQL) == expected

        assert_integrity("ok:0")
        run_target_sql(f"CREATE ROLE {rogue_role} NOLOGIN;")

        tamper_cycles = (
            (
                f"GRANT CONNECT, TEMPORARY ON DATABASE {target} TO {rogue_role};",
                f"REVOKE CONNECT, TEMPORARY ON DATABASE {target} FROM {rogue_role};",
            ),
            (
                "GRANT SELECT ON TABLE public.users TO PUBLIC;",
                "REVOKE SELECT ON TABLE public.users FROM PUBLIC;",
            ),
            (
                "ALTER DEFAULT PRIVILEGES FOR ROLE litblogs_migrator "
                f"GRANT EXECUTE ON FUNCTIONS TO {rogue_role};",
                "ALTER DEFAULT PRIVILEGES FOR ROLE litblogs_migrator "
                f"REVOKE EXECUTE ON FUNCTIONS FROM {rogue_role};",
            ),
            (
                "ALTER DEFAULT PRIVILEGES FOR ROLE litblogs_migrator "
                "IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO "
                f"{rogue_role};",
                "ALTER DEFAULT PRIVILEGES FOR ROLE litblogs_migrator "
                "IN SCHEMA public REVOKE EXECUTE ON FUNCTIONS FROM "
                f"{rogue_role};",
            ),
            (
                "ALTER DEFAULT PRIVILEGES FOR ROLE litblog_identity_owner "
                f"GRANT SELECT ON TABLES TO {rogue_role};",
                "ALTER DEFAULT PRIVILEGES FOR ROLE litblog_identity_owner "
                f"REVOKE SELECT ON TABLES FROM {rogue_role};",
            ),
            (
                f"CREATE SCHEMA {rogue_schema} AUTHORIZATION {rogue_role};",
                f"DROP SCHEMA {rogue_schema};",
            ),
        )
        for apply_tamper, revert_tamper in tamper_cycles:
            run_target_sql(apply_tamper)
            assert_integrity("failed")
            run_target_sql(revert_tamper)
            assert_integrity("ok:0")

        default_acl_tamper = (
            "ALTER DEFAULT PRIVILEGES FOR ROLE litblogs_migrator "
            f"GRANT EXECUTE ON FUNCTIONS TO {rogue_role};"
        )
        run_target_sql(default_acl_tamper)
        assert_integrity("failed")
        assert restore_main(
            [
                "--verify-existing",
                "--manifest",
                str(manifest),
                "--upload-target",
                str(restore_upload_root),
                "--target-database",
                target,
                "--confirm-target",
                target,
                "--expected-federated-identities",
                "0",
            ],
            runner=runner,
            client_validator=validate_clients,
            drift_checker=check_test_drift,
            tls_custody_validator=validate_test_ca,
        ) == 1
        run_target_sql(
            "ALTER DEFAULT PRIVILEGES FOR ROLE litblogs_migrator "
            f"REVOKE EXECUTE ON FUNCTIONS FROM {rogue_role};"
        )
        assert_integrity("ok:0")

        revoke_signature = (
            "operator_revoke_teacher_invitation(character varying, character "
            "varying, character varying)"
        )
        altered_routine = """
CREATE OR REPLACE FUNCTION public.operator_revoke_teacher_invitation(
    p_email_digest VARCHAR(64),
    p_actor_identifier VARCHAR(100),
    p_resource_digest VARCHAR(64)
)
RETURNS VARCHAR(16)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $operator_revoke_teacher_invitation_tamper$
BEGIN
    RETURN 'NOT_FOUND';
END
$operator_revoke_teacher_invitation_tamper$;
"""
        run_target_sql(altered_routine)
        assert_integrity("ok:0")
        assert restore_main(
            [
                "--verify-existing",
                "--manifest",
                str(manifest),
                "--upload-target",
                str(restore_upload_root),
                "--target-database",
                target,
                "--confirm-target",
                target,
                "--expected-federated-identities",
                "0",
            ],
            runner=runner,
            client_validator=validate_clients,
            drift_checker=check_test_drift,
            tls_custody_validator=validate_test_ca,
        ) == 1
        reviewed_body = EXPECTED_OPERATOR_ROUTINE_CONTRACT[revoke_signature]["source"]
        run_target_sql(
            """
CREATE OR REPLACE FUNCTION public.operator_revoke_teacher_invitation(
    p_email_digest VARCHAR(64),
    p_actor_identifier VARCHAR(100),
    p_resource_digest VARCHAR(64)
)
RETURNS VARCHAR(16)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $operator_revoke_teacher_invitation_restore$"""
            + str(reviewed_body)
            + "$operator_revoke_teacher_invitation_restore$;"
        )
        assert_integrity("ok:0")
        assert restore_main(
            [
                "--verify-existing",
                "--manifest",
                str(manifest),
                "--upload-target",
                str(restore_upload_root),
                "--target-database",
                target,
                "--confirm-target",
                target,
                "--expected-federated-identities",
                "0",
            ],
            runner=runner,
            client_validator=validate_clients,
            drift_checker=check_test_drift,
            tls_custody_validator=validate_test_ca,
        ) == 0

        runtime_password = secrets.token_urlsafe(32)
        wrong_password = secrets.token_urlsafe(32)
        admin_engine = create_engine(
            _ci_database_url(RESTORE_DATABASE_URL, target),
            poolclass=NullPool,
        )
        runtime_transition_applied = False
        try:
            with admin_engine.begin() as connection:
                connection.execute(
                    text(
                        "ALTER ROLE litblogs_runtime LOGIN NOINHERIT "
                        "NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION "
                        "NOBYPASSRLS PASSWORD :password"
                    ),
                    {"password": runtime_password},
                )
                runtime_transition_applied = True
                connection.execute(
                    text(f'GRANT CONNECT ON DATABASE "{target}" TO litblogs_runtime')
                )
                assert connection.execute(
                    text(
                        "SELECT rolpassword LIKE 'SCRAM-SHA-256$%' "
                        "FROM pg_catalog.pg_authid "
                        "WHERE rolname = 'litblogs_runtime'"
                    )
                ).scalar_one()
                assert connection.execute(
                    text(
                        "SELECT COUNT(*) = 4 AND BOOL_AND(NOT rolcanlogin) "
                        "FROM pg_catalog.pg_roles WHERE rolname IN ("
                        "'litblogs_migrator', 'litblog_identity_owner', "
                        "'litblog_account_operator', "
                        "'litblog_invitation_operator')"
                    )
                ).scalar_one()
                assert not connection.execute(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_auth_members "
                        "AS membership JOIN pg_catalog.pg_roles AS granted_role "
                        "ON granted_role.oid = membership.roleid JOIN "
                        "pg_catalog.pg_roles AS member_role ON member_role.oid = "
                        "membership.member WHERE granted_role.rolname IN ("
                        "'litblogs_migrator', 'litblogs_runtime', "
                        "'litblog_identity_owner', 'litblog_account_operator', "
                        "'litblog_invitation_operator') OR member_role.rolname IN ("
                        "'litblogs_migrator', 'litblogs_runtime', "
                        "'litblog_identity_owner', 'litblog_account_operator', "
                        "'litblog_invitation_operator'))"
                    )
                ).scalar_one()

            wrong_engine = create_engine(
                _ci_database_url(
                    RESTORE_DATABASE_URL,
                    target,
                    username="litblogs_runtime",
                    password=wrong_password,
                ),
                poolclass=NullPool,
            )
            try:
                with pytest.raises(OperationalError):
                    with wrong_engine.connect() as connection:
                        connection.execute(text("SELECT 1"))
            finally:
                wrong_engine.dispose()

            runtime_engine = create_engine(
                _ci_database_url(
                    RESTORE_DATABASE_URL,
                    target,
                    username="litblogs_runtime",
                    password=runtime_password,
                ),
                poolclass=NullPool,
            )
            try:
                from database import check_database_readiness

                check_database_readiness(runtime_engine)
            finally:
                runtime_engine.dispose()
        finally:
            if runtime_transition_applied:
                with admin_engine.begin() as connection:
                    connection.execute(
                        text(
                            f'REVOKE CONNECT ON DATABASE "{target}" '
                            "FROM litblogs_runtime"
                        )
                    )
                    connection.execute(
                        text("ALTER ROLE litblogs_runtime NOLOGIN PASSWORD NULL")
                    )
            admin_engine.dispose()

        assert client_validations == ["validated"] * 5
    finally:
        try:
            _remove_referential_sentinel(
                runner,
                RESTORE_DATABASE_URL,
                sentinel,
            )
        finally:
            runner.drop_database(RESTORE_DATABASE_URL, target)
            _run_psql(
                runner,
                RESTORE_DATABASE_URL,
                "postgres",
                f"DROP ROLE IF EXISTS {rogue_role};",
                sentinel=sentinel,
            )
