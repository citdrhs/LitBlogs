import os
import secrets
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[2]
OPERATOR_SCRIPTS = ROOT_DIR / "deploy" / "scripts"
sys.path.insert(0, str(OPERATOR_SCRIPTS))

from backup_postgres import main as backup_main  # noqa: E402
from postgres_common import (  # noqa: E402
    POSTGRES_CLIENT_NAMES,
    POSTGRES_VERSION,
    build_pg_environment,
    parse_postgres_url,
    postgres_executable,
)
from restore_verify_postgres import (  # noqa: E402
    check_alembic_schema_drift,
)
from restore_verify_postgres import (  # noqa: E402
    main as restore_main,
)

CONTAINER_ID = os.environ.get("POSTGRES_OPERATOR_CONTAINER_ID", "")
DATABASE_URL = os.environ.get("POSTGRES_OPERATOR_DATABASE_URL", "")


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
    not CONTAINER_ID or not DATABASE_URL,
    reason="requires the pinned PostgreSQL CI service container",
)
def test_real_custom_backup_restore_and_integrity_round_trip(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    runner = PinnedContainerPostgresRunner(CONTAINER_ID)
    target = f"litblog_restore_verify_ci_{secrets.token_hex(6)}"
    sentinel = f"operator_{secrets.token_hex(8)}"
    client_validations = []

    def validate_clients():
        _container_client_validator(runner, DATABASE_URL)
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
        _seed_referential_sentinel(runner, DATABASE_URL, sentinel)
        monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
        assert backup_main(
            ["--output-dir", str(tmp_path)],
            runner=runner,
            client_validator=validate_clients,
            tls_custody_validator=validate_test_ca,
        ) == 0
        archive = next(tmp_path.glob("*.dump"))
        manifest = archive.with_name(f"{archive.name}.manifest.json")
        assert restore_main(
            [
                "--archive",
                str(archive),
                "--manifest",
                str(manifest),
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
            DATABASE_URL,
            target,
            "SELECT content FROM blogs WHERE title = :'sentinel';",
            sentinel=sentinel,
        )
        assert restored_value == sentinel
        assert client_validations == ["validated", "validated"]
    finally:
        _remove_referential_sentinel(runner, DATABASE_URL, sentinel)
        runner.drop_database(DATABASE_URL, target)
