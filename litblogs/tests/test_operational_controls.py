import hashlib
import json
import logging
import os
import stat
import subprocess
import sys
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT_DIR = Path(__file__).resolve().parents[2]
SCRIPT_DIR = ROOT_DIR / "deploy" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

postgres_common = import_module("postgres_common")
backup_postgres = import_module("backup_postgres")
restore_verify_postgres = import_module("restore_verify_postgres")
release_switch = import_module("release_switch")
upload_snapshot_common = import_module("upload_snapshot_common")


DATABASE_URL = (
    "postgresql://litblogs_backup:backup-4R%21v9nK2sQ7x@db.school.edu/"
    "litblogs?sslmode=verify-full&sslrootcert="
    "%2Fetc%2Flitblogs%2Fpostgres-root-ca.pem"
)


def test_operator_postgres_ca_metadata_contract_is_exact_root_root_0644():
    valid = SimpleNamespace(st_mode=stat.S_IFREG | 0o644, st_uid=0, st_gid=0)
    assert postgres_common._postgres_ca_metadata_matches_contract(valid)

    for invalid in (
        SimpleNamespace(st_mode=stat.S_IFREG | 0o640, st_uid=0, st_gid=0),
        SimpleNamespace(st_mode=stat.S_IFREG | 0o664, st_uid=0, st_gid=0),
        SimpleNamespace(st_mode=stat.S_IFREG | 0o644, st_uid=1, st_gid=0),
        SimpleNamespace(st_mode=stat.S_IFREG | 0o644, st_uid=0, st_gid=1),
        SimpleNamespace(st_mode=stat.S_IFDIR | 0o644, st_uid=0, st_gid=0),
    ):
        assert not postgres_common._postgres_ca_metadata_matches_contract(invalid)


@pytest.fixture(autouse=True)
def _isolate_operator_ca_custody_from_the_test_host(monkeypatch):
    """Unit tests validate CA custody separately from their synthetic commands."""

    monkeypatch.setattr(backup_postgres, "validate_postgres_tls_custody", lambda _connection: None)
    monkeypatch.setattr(
        restore_verify_postgres,
        "validate_postgres_tls_custody",
        lambda _connection: None,
    )


class RecordingRunner:
    def __init__(self, *, responses=None, pg_dump_payload=b"PGDMP-test-archive"):
        self.calls = []
        self.responses = list(responses or [])
        self.pg_dump_payload = pg_dump_payload

    def __call__(self, command, **kwargs):
        command = [str(item) for item in command]
        self.calls.append((command, kwargs))
        if Path(command[0]).name == "psql":
            sql = kwargs.get("input")
            if sql is None:
                sql = command[command.index("--command") + 1]
            if sql == backup_postgres.BACKUP_ROLE_PRECHECK_SQL:
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout="ok\n",
                    stderr="",
                )
        if Path(command[0]).name == "pg_dump" and self.pg_dump_payload is not None:
            output_path = Path(command[command.index("--file") + 1])
            output_path.write_bytes(self.pg_dump_payload)
        if self.responses:
            response = self.responses.pop(0)
            return subprocess.CompletedProcess(command, **response)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")


def _operator_routine_catalog_response() -> str:
    records = []
    for signature, expected in (
        restore_verify_postgres.EXPECTED_OPERATOR_ROUTINE_CONTRACT.items()
    ):
        record = {key: value for key, value in expected.items() if key != "source"}
        record["signature"] = signature
        record["source_hex"] = expected["source"].encode("utf-8").hex()
        records.append(record)
    return json.dumps(records) + "\n"


def test_restore_psql_uses_stdin_for_quoted_variable_substitution():
    calls = []
    sql = "SELECT :'sentinel';"
    sentinel = "operator_'; SELECT 'injected"

    def runner(command, **kwargs):
        calls.append(([str(item) for item in command], kwargs))
        return subprocess.CompletedProcess(command, 0, stdout=sentinel, stderr="")

    result = restore_verify_postgres._run_psql(
        sql,
        variables={"sentinel": sentinel},
        environment={},
        runner=runner,
        capture_stdout=True,
    )

    assert result.stdout == sentinel
    command, kwargs = calls[0]
    assert "--file=-" in command
    assert "--command" not in command
    assert f"--set=sentinel={sentinel}" in command
    assert sql not in command
    assert kwargs["input"] == sql


def _create_coupled_backup(output_directory, database_url, **kwargs):
    output = Path(output_directory)
    absolute_output = output if output.is_absolute() else (Path.cwd() / output)
    upload_root = absolute_output.parent / f".{output.name}-upload-fixture"
    upload_root.mkdir(mode=0o700, exist_ok=True)
    (upload_root / "objects").mkdir(mode=0o700, exist_ok=True)
    (upload_root / ".incoming").mkdir(mode=0o700, exist_ok=True)
    if os.name == "posix":
        upload_root.chmod(0o700)
        (upload_root / "objects").chmod(0o700)
        (upload_root / ".incoming").chmod(0o700)
    return backup_postgres.create_backup(
        output_directory,
        database_url,
        upload_root=upload_root,
        writes_quiesced=True,
        inventory_reader=lambda _connection, _runner: (),
        upload_custody=upload_snapshot_common.synthetic_upload_custody(),
        **kwargs,
    )


def _write_backup_pair(directory, *, payload=b"PGDMP-test-archive"):
    archive = directory / "litblogs-20260821T220000Z-a1b2c3d4.dump"
    archive.write_bytes(payload)
    archive.chmod(0o600)
    manifest = archive.with_name(f"{archive.name}.manifest.json")
    manifest.write_text(
        json.dumps(
            {
                "archive": archive.name,
                "created_at": "2026-08-21T22:00:00Z",
                "format": "litblogs-postgresql-custom-v1",
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size_bytes": len(payload),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    manifest.chmod(0o600)
    return archive, manifest


def _write_release(root, short_sha, *, full_sha=None):
    release_id = f"litblogs-{short_sha}"
    release = root / "releases" / release_id
    release.mkdir(parents=True)
    commit = full_sha or (short_sha + ("a" * (40 - len(short_sha))))
    (release / "RELEASE-MANIFEST").write_text(
        f"commit={commit}\nbuilt_at_epoch=1787359200\n",
        encoding="utf-8",
    )
    if os.name == "posix":
        python_bin = release / ".venv" / "bin"
        python_bin.mkdir(parents=True)
        (python_bin / "python").symlink_to(Path(sys.executable).resolve(strict=True))
    return release_id, release


def _release_commit(short_sha):
    return short_sha + ("a" * (40 - len(short_sha)))


def _stat_result_with(metadata, *, owner_uid=None, mode=None):
    fields = list(metadata)
    if owner_uid is not None:
        fields[stat.ST_UID] = owner_uid
    if mode is not None:
        fields[stat.ST_MODE] = mode
    return os.stat_result(fields)


@pytest.fixture
def synthetic_trusted_release_python(monkeypatch):
    """Keep unit tests independent of hosted-runner Python custody."""

    trusted_python = Path(sys.executable).resolve(strict=True)
    monkeypatch.setattr(release_switch, "_trusted_python", lambda: trusted_python)
    return trusted_python


@pytest.fixture
def root_owned_release_lock_metadata(monkeypatch, synthetic_trusted_release_python):
    """Exercise pointer behavior while preserving the real lock and flock path."""

    if os.name != "posix":
        return
    real_fstat = os.fstat

    def report_root_owned_lock(descriptor):
        metadata = real_fstat(descriptor)
        return _stat_result_with(metadata, owner_uid=0)

    monkeypatch.setattr(release_switch.os, "fstat", report_root_owned_lock)


def test_operator_scripts_are_tracked_as_portable_python_entry_points():
    expected_scripts = {
        "postgres_common.py",
        "backup_postgres.py",
        "restore_verify_postgres.py",
        "upload_snapshot_common.py",
        "release_switch.py",
    }

    assert {path.name for path in SCRIPT_DIR.glob("*.py")} >= expected_scripts


def test_postgres_url_is_parsed_without_exposing_its_password():
    connection = postgres_common.parse_postgres_url(
        "postgresql://backup%5Fuser:backup-4R%21v9nK2sQ7x@db.school.edu:5433/"
        "litblogs?sslmode=verify-full&sslrootcert="
        "%2Fetc%2Flitblogs%2Fpostgres-root-ca.pem"
    )

    assert connection.host == "db.school.edu"
    assert connection.port == 5433
    assert connection.user == "backup_user"
    assert connection.password == "backup-4R!v9nK2sQ7x"
    assert connection.database == "litblogs"
    assert connection.sslmode == "verify-full"
    assert connection.sslrootcert == "/etc/litblogs/postgres-root-ca.pem"
    assert "backup-4R!v9nK2sQ7x" not in repr(connection)
    assert "backup-4R%21v9nK2sQ7x" not in repr(connection)


def test_postgres_operator_url_requires_the_canonical_root_ca_path():
    with pytest.raises(postgres_common.PostgresOperatorError, match="invalid TLS path"):
        postgres_common.parse_postgres_url(
            "postgresql://backup_user:backup-4R%21v9nK2sQ7x@db.school.edu/"
            "litblogs?sslmode=verify-full&sslrootcert="
            "%2Fetc%2Flitblogs%2Falternate-root-ca.pem"
        )


@pytest.mark.parametrize(
    "database_url",
    [
        "",
        "sqlite:///litblogs.db",
        "http://user:password@db.school.example/litblogs?sslmode=verify-full",
        "postgresql://user:password@/litblogs?sslmode=verify-full",
        "postgresql://db.school.example/litblogs?sslmode=verify-full",
        "postgresql://user:password@db.school.example/?sslmode=verify-full",
        "postgresql://user:password@db.school.example/a/b?sslmode=verify-full",
        "postgresql://user:password@db.school.example/litblogs#fragment?sslmode=verify-full",
        "postgresql://user:password@db.school.example:/litblogs?sslmode=verify-full",
        "postgresql://user:password@db.school.example:0/litblogs?sslmode=verify-full",
        "postgresql://user:password@db.school.example:70000/litblogs?sslmode=verify-full",
        "postgresql://user%ZZ:password@db.school.example/litblogs?sslmode=verify-full",
        "postgresql://user:password@db.school.example/litblogs?sslmode=disable",
        "postgresql://user:password@db.school.example/litblogs?sslmode=require",
        "postgresql://user:password@db.school.example/litblogs?sslmode=verify-full&host=other",
        "postgresql://user:password@db.school.example/litblogs?sslmode=verify-full&hostaddr=1.2.3.4",
        "postgresql://user:password@db.school.example/litblogs?sslmode=verify-full&service=prod",
        "postgresql://user:password@db.school.example/litblogs?sslmode=verify-full&dbname=other",
        "postgresql://user:password@db.school.example/litblogs?sslmode=verify-full&database=other",
        "postgresql://user:password@db.school.example/litblogs?sslmode=verify-full&options=-cfoo",
        "postgresql://user:password@db.school.example/litblogs?sslmode=verify-full&sslmode=verify-full",
        "postgresql://user:password@db.school.edu/litblogs?sslmode=verify-full",
        "postgresql://user:password@db1.school.edu,db2.school.edu/litblogs?sslmode=verify-full&sslrootcert=/etc/litblogs/postgres-root-ca.pem",
        "postgresql://user:password@db1.school.edu%2Cdb2.school.edu/litblogs?sslmode=verify-full&sslrootcert=/etc/litblogs/postgres-root-ca.pem",
    ],
)
def test_postgres_url_rejects_malformed_plaintext_and_override_targets(database_url):
    with pytest.raises(postgres_common.PostgresOperatorError):
        postgres_common.parse_postgres_url(database_url)


@pytest.mark.parametrize(
    "authority",
    [
        "backup_user",
        "backup_user:short",
        "backup_user:replace-with-managed-password",
    ],
)
def test_postgres_url_requires_an_explicit_strong_nonplaceholder_password(authority):
    database_url = (
        f"postgresql://{authority}@db.school.edu/litblogs?sslmode=verify-full"
        "&sslrootcert=%2Fetc%2Flitblogs%2Fpostgres-root-ca.pem"
    )

    with pytest.raises(postgres_common.PostgresOperatorError):
        postgres_common.parse_postgres_url(database_url)


def test_libpq_environment_is_minimal_and_cannot_inherit_target_overrides():
    connection = postgres_common.parse_postgres_url(
        "postgresql://backup_user:backup-4R%21v9nK2sQ7x@db.school.edu/"
        "litblogs?sslmode=verify-full&sslrootcert="
        "%2Fetc%2Flitblogs%2Fpostgres-root-ca.pem"
    )
    inherited = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "DATABASE_URL": "test-database-url-placeholder",
        "PGSERVICE": "production-override",
        "PGHOSTADDR": "203.0.113.8",
        "PGPASSWORD": "old-secret",
        "UNRELATED_SECRET": "must-not-be-forwarded",
    }

    child = postgres_common.build_pg_environment(
        connection,
        database="litblog_restore_verify_20260821",
        base_environment=inherited,
    )

    assert child["PGHOST"] == "db.school.edu"
    assert child["PGPORT"] == "5432"
    assert child["PGUSER"] == "backup_user"
    assert child["PGPASSWORD"] == "backup-4R!v9nK2sQ7x"
    assert child["PGDATABASE"] == "litblog_restore_verify_20260821"
    assert child["PGSSLMODE"] == "verify-full"
    assert child["PGSSLROOTCERT"] == "/etc/litblogs/postgres-root-ca.pem"
    assert child["PGCONNECT_TIMEOUT"] == "10"
    assert child["PATH"] == "/usr/bin:/bin"
    assert child["PATH"] != inherited["PATH"]
    assert "DATABASE_URL" not in child
    assert "PGSERVICE" not in child
    assert "PGHOSTADDR" not in child
    assert "UNRELATED_SECRET" not in child


@pytest.mark.skipif(os.name != "posix", reason="POSIX ownership and modes required")
def test_postgres_ca_custody_allows_read_only_ca_and_rejects_mutable_ca(tmp_path):
    trust_root = tmp_path / "managed-trust"
    certificate_directory = trust_root / "etc" / "litblogs"
    certificate_directory.mkdir(parents=True)
    certificate = certificate_directory / "postgres-root-ca.pem"
    certificate.write_text("synthetic test CA", encoding="utf-8")
    certificate.chmod(0o644)
    metadata = certificate.stat()
    connection = postgres_common.PostgresConnection(
        host="db.school.edu",
        port=5432,
        user="backup_user",
        password="private",
        database="litblogs",
        sslmode="verify-full",
        sslrootcert=str(certificate),
    )

    postgres_common.validate_postgres_tls_custody(
        connection,
        required_owner_uid=metadata.st_uid,
        required_group_gid=metadata.st_gid,
        trusted_ancestor=tmp_path,
    )

    certificate.chmod(0o640)
    with pytest.raises(postgres_common.PostgresOperatorError, match="custody"):
        postgres_common.validate_postgres_tls_custody(
            connection,
            required_owner_uid=metadata.st_uid,
            required_group_gid=metadata.st_gid,
            trusted_ancestor=tmp_path,
        )

    certificate.chmod(0o644)
    trust_root.chmod(0o775)
    with pytest.raises(postgres_common.PostgresOperatorError, match="custody"):
        postgres_common.validate_postgres_tls_custody(
            connection,
            required_owner_uid=metadata.st_uid,
            required_group_gid=metadata.st_gid,
            trusted_ancestor=tmp_path,
        )


def test_postgres_clients_are_absolute_pinned_pg17_paths_and_version_checked(tmp_path):
    client_root = tmp_path / "postgresql" / "17" / "bin"
    client_root.mkdir(parents=True)
    for command_name in ("createdb", "pg_dump", "pg_restore", "psql"):
        command = client_root / command_name
        command.write_text("reviewed pg17 client\n", encoding="utf-8")
        command.chmod(0o755)
    calls = []

    def version_runner(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=f"{Path(command[0]).name} (PostgreSQL) 17.11\n",
            stderr="",
        )

    postgres_common.validate_postgres_client_installation(
        client_root=client_root,
        runner=version_runner,
        required_owner_uid=os.getuid() if hasattr(os, "getuid") else None,
        trusted_ancestor=tmp_path,
    )

    assert {Path(command[0]).name for command, _kwargs in calls} == {
        "createdb",
        "pg_dump",
        "pg_restore",
        "psql",
    }
    assert all(Path(command[0]).is_absolute() for command, _kwargs in calls)
    assert all(command[1:] == ["--version"] for command, _kwargs in calls)
    assert all(
        kwargs["env"] == {"LANG": "C", "LC_ALL": "C", "PATH": "/usr/bin:/bin"}
        for _command, kwargs in calls
    )
    assert postgres_common.postgres_executable("pg_dump") == (
        "/usr/lib/postgresql/17/bin/pg_dump"
    )
    assert postgres_common.is_immutable_client_root_mode(0o755)
    assert postgres_common.is_immutable_client_root_mode(0o750)
    assert not postgres_common.is_immutable_client_root_mode(0o775)
    assert not postgres_common.is_immutable_client_root_mode(0o757)


@pytest.mark.skipif(os.name != "posix", reason="POSIX ownership and modes required")
def test_postgres_client_validation_rejects_mutable_or_noncanonical_client_root(
    tmp_path,
):
    real_parent = tmp_path / "real"
    client_root = real_parent / "17" / "bin"
    client_root.mkdir(parents=True)
    for command_name in ("createdb", "pg_dump", "pg_restore", "psql"):
        command = client_root / command_name
        command.write_text("reviewed pg17 client\n", encoding="utf-8")
        command.chmod(0o755)

    def valid_version(command, **_kwargs):
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=f"{Path(command[0]).name} (PostgreSQL) 17.11\n",
            stderr="",
        )

    client_root.chmod(0o775)
    with pytest.raises(postgres_common.PostgresOperatorError, match="root.*permissions"):
        postgres_common.validate_postgres_client_installation(
            client_root=client_root,
            runner=valid_version,
            required_owner_uid=client_root.stat().st_uid,
            trusted_ancestor=tmp_path,
        )

    client_root.chmod(0o755)
    mutable_ancestor = real_parent
    mutable_ancestor.chmod(0o775)
    with pytest.raises(
        postgres_common.PostgresOperatorError, match="ancestor.*permissions"
    ):
        postgres_common.validate_postgres_client_installation(
            client_root=client_root,
            runner=valid_version,
            required_owner_uid=client_root.stat().st_uid,
            trusted_ancestor=tmp_path,
        )

    mutable_ancestor.chmod(0o755)
    alias = tmp_path / "alias"
    alias.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(postgres_common.PostgresOperatorError, match="root.*symlink"):
        postgres_common.validate_postgres_client_installation(
            client_root=alias / "17" / "bin",
            runner=valid_version,
            required_owner_uid=client_root.stat().st_uid,
            trusted_ancestor=tmp_path,
        )


def test_postgres_client_validation_rejects_wrong_major_and_unsafe_roots(tmp_path):
    client_root = tmp_path / "postgresql" / "17" / "bin"
    client_root.mkdir(parents=True)
    for command_name in ("createdb", "pg_dump", "pg_restore", "psql"):
        command = client_root / command_name
        command.write_text("untrusted client\n", encoding="utf-8")
        command.chmod(0o755)

    def wrong_version(command, **_kwargs):
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=f"{Path(command[0]).name} (PostgreSQL) 16.9\n",
            stderr="",
        )

    with pytest.raises(postgres_common.PostgresOperatorError, match="PostgreSQL 17"):
        postgres_common.validate_postgres_client_installation(
            client_root=client_root,
            runner=wrong_version,
            required_owner_uid=os.getuid() if hasattr(os, "getuid") else None,
            trusted_ancestor=tmp_path,
        )
    with pytest.raises(postgres_common.PostgresOperatorError, match="absolute"):
        postgres_common.validate_postgres_client_installation(
            client_root=Path("relative/pg17/bin"),
            runner=wrong_version,
        )
    with pytest.raises(postgres_common.PostgresOperatorError):
        postgres_common.postgres_executable("../pg_dump")


@pytest.mark.parametrize(
    "database_name",
    [
        "postgres",
        "template0",
        "template1",
        "litblogs",
        "production",
        "litblog_restore_verify_",
        "litblog_restore_verify_UPPER",
        "litblog_restore_verify_has-hyphen",
        "litblog_restore_verify_x;drop_database_litblogs",
        "litblog_restore_verify_" + ("x" * 64),
    ],
)
def test_restore_database_name_rejects_defaults_production_and_injection(database_name):
    with pytest.raises(postgres_common.PostgresOperatorError):
        postgres_common.validate_restore_database_name(database_name)


def test_restore_database_name_accepts_only_the_explicit_synthetic_namespace():
    assert (
        postgres_common.validate_restore_database_name("litblog_restore_verify_20260821_a1")
        == "litblog_restore_verify_20260821_a1"
    )


def test_restore_verifier_expected_head_matches_the_release_migration_graph():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(ROOT_DIR / "litblogs" / "alembic.ini"))
    config.set_main_option(
        "script_location",
        str(ROOT_DIR / "litblogs" / "migrations"),
    )
    migration_head = ScriptDirectory.from_config(config).get_current_head()

    assert restore_verify_postgres.EXPECTED_ALEMBIC_HEAD == migration_head


def test_backup_publishes_custom_archive_and_matching_checksum_manifest(tmp_path):
    runner = RecordingRunner()

    result = _create_coupled_backup(tmp_path, DATABASE_URL, runner=runner)

    assert result.database_archive.is_file()
    assert result.database_archive.read_bytes().startswith(b"PGDMP")
    assert result.upload_archive.is_file()
    assert result.asset_inventory.is_file()
    assert result.manifest.is_file()
    manifest = json.loads(result.manifest.read_text(encoding="utf-8"))
    assert manifest["format"] == "litblogs-coupled-recovery-v1"
    assert manifest["created_at"] == result.created_at
    assert manifest["writes_quiesced"] is True
    assert manifest["asset_records"] == manifest["file_backed_assets"] == 0
    assert manifest["artifacts"]["database"] == {
        "format": "postgresql-custom",
        "name": result.database_archive.name,
        "sha256": hashlib.sha256(result.database_archive.read_bytes()).hexdigest(),
        "size_bytes": result.database_archive.stat().st_size,
    }
    recovery_set = upload_snapshot_common.load_coupled_recovery_set(result.manifest)
    assert recovery_set.inventory == ()
    command, kwargs = next(
        call for call in runner.calls if Path(call[0][0]).name == "pg_dump"
    )
    assert command[0] == "/usr/lib/postgresql/17/bin/pg_dump"
    assert command[1] == "--format=custom"
    assert "--no-owner" not in command
    assert "--no-acl" not in command
    assert "--no-password" in command
    assert "--file" in command
    assert kwargs["shell"] is False
    assert kwargs["check"] is False
    assert kwargs["stdout"] is subprocess.DEVNULL
    assert kwargs["stderr"] is subprocess.PIPE
    flattened_command = " ".join(command)
    assert "backup-4R!v9nK2sQ7x" not in flattened_command
    assert "backup-4R%21v9nK2sQ7x" not in flattened_command
    assert "postgresql://" not in flattened_command
    assert kwargs["env"]["PGPASSWORD"] == "backup-4R!v9nK2sQ7x"
    assert not list(tmp_path.glob(".*.partial"))


def test_backup_failure_is_redacted_and_retains_unpublished_private_work(tmp_path):
    runner = RecordingRunner(
        responses=[
            {
                "returncode": 1,
                "stdout": "",
                "stderr": "connection failed for password backup-4R!v9nK2sQ7x",
            }
        ]
    )

    with pytest.raises(postgres_common.PostgresOperatorError) as failure:
        _create_coupled_backup(tmp_path, DATABASE_URL, runner=runner)

    assert "backup-4R!v9nK2sQ7x" not in str(failure.value)
    assert "backup-4R%21v9nK2sQ7x" not in str(failure.value)
    assert not list(tmp_path.glob("*.manifest.json"))
    assert list(tmp_path.glob(".*.partial"))


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits required")
def test_backup_partial_file_is_private_before_pg_dump_writes_student_data(tmp_path):
    observed_modes = []

    def inspect_partial_mode(command, **kwargs):
        if Path(command[0]).name == "psql":
            return subprocess.CompletedProcess(command, 0, stdout="ok\n", stderr="")
        output_path = Path(command[command.index("--file") + 1])
        observed_modes.append(stat.S_IMODE(output_path.stat().st_mode))
        output_path.write_bytes(b"PGDMP-test-archive")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    _create_coupled_backup(tmp_path, DATABASE_URL, runner=inspect_partial_mode)

    assert observed_modes == [0o600]


def test_backup_fsyncs_archive_manifest_and_directory_before_acknowledging(
    tmp_path, monkeypatch
):
    events = []
    original_file_sync = backup_postgres._fsync_file
    original_directory_sync = backup_postgres._fsync_directory

    def record_file_sync(path):
        events.append(("file", Path(path).name))
        original_file_sync(path)

    def record_directory_sync(path):
        events.append(("directory", Path(path).name))
        original_directory_sync(path)

    monkeypatch.setattr(backup_postgres, "_fsync_file", record_file_sync)
    monkeypatch.setattr(backup_postgres, "_fsync_directory", record_directory_sync)

    result = _create_coupled_backup(
        tmp_path, DATABASE_URL, runner=RecordingRunner()
    )

    file_events = [event for event in events if event[0] == "file"]
    assert any(event[1].endswith(".assets.jsonl.partial") for event in file_events)
    assert any(event[1].endswith(".dump.partial") for event in file_events)
    assert any(event[1].endswith(".manifest.json.partial") for event in file_events)
    assert any(event[1].endswith(".uploads.tar.partial") for event in file_events)
    manifest_sync = next(
        event for event in file_events if event[1].endswith(".manifest.json.partial")
    )
    assert next(
        index for index, event in enumerate(events) if event[0] == "directory"
    ) < events.index(manifest_sync)
    assert result.archive.is_file()
    assert result.manifest.is_file()
    assert not list(tmp_path.glob(".*.partial"))


def test_backup_publish_collision_never_deletes_an_unowned_destination(
    tmp_path, monkeypatch
):
    foreign_payload = b"foreign-operator-file"

    def collide(_source, destination):
        Path(destination).write_bytes(foreign_payload)
        raise FileExistsError

    monkeypatch.setattr(backup_postgres.os, "link", collide)

    with pytest.raises(postgres_common.PostgresOperatorError, match="published safely"):
        _create_coupled_backup(
            tmp_path, DATABASE_URL, runner=RecordingRunner()
        )

    published = list(tmp_path.glob("*.dump"))
    assert len(published) == 1
    assert published[0].read_bytes() == foreign_payload
    assert list(tmp_path.glob(".*.partial"))


def test_backup_rejects_non_custom_output_without_publishing_it(tmp_path):
    runner = RecordingRunner(pg_dump_payload=b"not-a-postgresql-custom-archive")

    with pytest.raises(postgres_common.PostgresOperatorError, match="custom-format"):
        _create_coupled_backup(tmp_path, DATABASE_URL, runner=runner)

    assert not list(tmp_path.glob("*.manifest.json"))
    assert list(tmp_path.glob(".*.partial"))


def test_backup_requires_an_existing_private_directory(tmp_path):
    missing = tmp_path / "missing"

    with pytest.raises(postgres_common.PostgresOperatorError, match="directory"):
        _create_coupled_backup(missing, DATABASE_URL, runner=RecordingRunner())


def test_backup_directory_mode_rejects_group_or_world_writers():
    assert backup_postgres.is_private_directory_mode(0o700)
    assert not backup_postgres.is_private_directory_mode(0o750)
    assert not backup_postgres.is_private_directory_mode(0o500)
    assert not backup_postgres.is_private_directory_mode(0o770)
    assert not backup_postgres.is_private_directory_mode(0o707)
    assert not backup_postgres.is_private_directory_mode(0o777)


def test_backup_rejects_relative_output_directory(tmp_path, monkeypatch):
    (tmp_path / "backups").mkdir()
    monkeypatch.chdir(tmp_path)

    with pytest.raises(postgres_common.PostgresOperatorError, match="absolute"):
        _create_coupled_backup("backups", DATABASE_URL, runner=RecordingRunner())


@pytest.mark.skipif(os.name != "posix", reason="POSIX ownership and modes required")
def test_backup_rejects_noncanonical_or_non_owner_only_output_custody(tmp_path):
    real_parent = tmp_path / "real"
    output = real_parent / "backups"
    output.mkdir(parents=True, mode=0o700)
    alias = tmp_path / "alias"
    alias.symlink_to(real_parent, target_is_directory=True)

    with pytest.raises(postgres_common.PostgresOperatorError, match="custody"):
        _create_coupled_backup(
            alias / "backups", DATABASE_URL, runner=RecordingRunner()
        )

    output.chmod(0o750)
    with pytest.raises(postgres_common.PostgresOperatorError, match="owner-only"):
        _create_coupled_backup(
            output, DATABASE_URL, runner=RecordingRunner()
        )

    output.chmod(0o700)
    real_parent.chmod(0o775)
    runner = RecordingRunner()
    with pytest.raises(postgres_common.PostgresOperatorError, match="ancestor.*permissions"):
        _create_coupled_backup(output, DATABASE_URL, runner=runner)
    assert runner.calls == []


@pytest.mark.skipif(os.name != "posix", reason="POSIX ownership required")
def test_private_operator_directory_requires_the_effective_operator_owner(tmp_path):
    tmp_path.chmod(0o700)

    with pytest.raises(postgres_common.PostgresOperatorError, match="operator"):
        postgres_common.validate_private_operator_directory(
            tmp_path,
            purpose="backup output directory",
            required_owner_uid=tmp_path.stat().st_uid + 1,
        )


def test_backup_entry_point_requires_database_url_without_echoing_it(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    upload_root = tmp_path.parent / f".{tmp_path.name}-entry-upload-root"
    upload_root.mkdir()
    exit_code = backup_postgres.main(
        [
            "--output-dir",
            str(tmp_path),
            "--upload-root",
            str(upload_root),
            "--confirm-writes-quiesced",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "DATABASE_URL" in captured.err
    assert captured.out == ""


def test_restore_creates_only_a_new_synthetic_database_and_runs_integrity_checks(tmp_path):
    archive, manifest = _write_backup_pair(tmp_path)
    target = "litblog_restore_verify_20260821_a1"
    runner = RecordingRunner(
        responses=[
            {"returncode": 0, "stdout": "", "stderr": ""},
            {"returncode": 0, "stdout": "absent\n", "stderr": ""},
            {"returncode": 0, "stdout": "", "stderr": ""},
            {"returncode": 0, "stdout": "", "stderr": ""},
            {"returncode": 0, "stdout": "", "stderr": ""},
            {"returncode": 0, "stdout": "ok\n", "stderr": ""},
            {"returncode": 0, "stdout": "versioned\n", "stderr": ""},
            {"returncode": 0, "stdout": "f1ad78b2035f\n", "stderr": ""},
            {"returncode": 0, "stdout": "ok\n", "stderr": ""},
            {"returncode": 0, "stdout": "ok:3\n", "stderr": ""},
            {
                "returncode": 0,
                "stdout": _operator_routine_catalog_response(),
                "stderr": "",
            },
        ]
    )
    drift_checks = []

    result = restore_verify_postgres.restore_and_verify(
        archive,
        manifest,
        target,
        confirmation=target,
        database_url=DATABASE_URL,
        runner=runner,
        drift_checker=lambda connection, database: drift_checks.append(
            (connection.database, database)
        ),
    )

    assert result.target_database == target
    assert result.migration_state == "current_head"
    assert result.alembic_revision == "f1ad78b2035f"
    assert result.federated_identity_count == 3
    assert drift_checks == [("litblogs", target)]
    commands = [call[0] for call in runner.calls]
    assert [Path(command[0]).name for command in commands] == [
        "pg_restore",
        "psql",
        "createdb",
        "psql",
        "pg_restore",
        "psql",
        "psql",
        "psql",
        "psql",
        "psql",
        "psql",
    ]
    assert "--list" in commands[0]
    assert commands[2][-1] == target
    assert "--maintenance-db=postgres" in commands[2]
    existence_sql = runner.calls[1][1]["input"]
    assert "--file=-" in commands[1]
    assert "--command" not in commands[1]
    assert target not in existence_sql
    assert ":'target_database'" in existence_sql
    assert f"--set=target_database={target}" in commands[1]
    lockdown_sql = runner.calls[3][1]["input"]
    assert "--file=-" in commands[3]
    assert "--command" not in commands[3]
    assert target not in lockdown_sql
    assert ':"target_database"' in lockdown_sql
    assert f"--set=target_database={target}" in commands[3]
    assert "REVOKE CONNECT, TEMPORARY" in lockdown_sql
    assert "FROM PUBLIC" in lockdown_sql
    assert "--single-transaction" in commands[4]
    assert "--exit-on-error" in commands[4]
    assert "--no-owner" not in commands[4]
    assert "--no-acl" not in commands[4]
    assert commands[4][commands[4].index("--dbname") + 1] == target
    assert all("--no-password" in command for command in commands[1:])
    assert "--create" not in commands[4]
    all_arguments = "\n".join(" ".join(command) for command in commands)
    assert "backup-4R!v9nK2sQ7x" not in all_arguments
    assert "backup-4R%21v9nK2sQ7x" not in all_arguments
    assert "postgresql://" not in all_arguments
    assert "dropdb" not in all_arguments.lower()
    assert "drop database" not in all_arguments.lower()
    assert "expected_foreign_keys" in " ".join(commands[5])
    assert "uq_federated_identity_subject" in " ".join(commands[5])
    assert "ck_federated_identity_provider" in " ".join(commands[5])
    assert "alembic_version" in " ".join(commands[6])
    assert "federated_identities" in " ".join(commands[6])
    assert "version_num" in " ".join(commands[7])
    assert "users" in " ".join(commands[8])
    assert "blogs" in " ".join(commands[8])
    assert "LEFT JOIN public.users" in " ".join(commands[8])
    assert "LEFT JOIN public.classes" in " ".join(commands[8])
    assert "federated_identities" in " ".join(commands[9])
    assert "pg_catalog.btrim(identity.issuer)" in " ".join(commands[9])
    assert "pg_catalog.btrim(identity.subject)" in " ".join(commands[9])
    assert "source_hex" in " ".join(commands[10])
    assert runner.calls[1][1]["env"]["PGDATABASE"] == "postgres"
    assert runner.calls[4][1]["env"]["PGDATABASE"] == target
    assert all(call[1]["shell"] is False for call in runner.calls)
    assert all(call[1]["check"] is False for call in runner.calls)


def test_restore_reports_only_a_complete_unmixed_legacy_schema_as_pre_alembic(tmp_path):
    archive, manifest = _write_backup_pair(tmp_path)
    target = "litblog_restore_verify_legacy"
    runner = RecordingRunner(
        responses=[
            {"returncode": 0, "stdout": "", "stderr": ""},
            {"returncode": 0, "stdout": "absent\n", "stderr": ""},
            {"returncode": 0, "stdout": "", "stderr": ""},
            {"returncode": 0, "stdout": "", "stderr": ""},
            {"returncode": 0, "stdout": "", "stderr": ""},
            {"returncode": 0, "stdout": "ok\n", "stderr": ""},
            {"returncode": 0, "stdout": "pre_alembic\n", "stderr": ""},
            {"returncode": 0, "stdout": "ok\n", "stderr": ""},
        ]
    )

    result = restore_verify_postgres.restore_and_verify(
        archive,
        manifest,
        target,
        confirmation=target,
        database_url=DATABASE_URL,
        runner=runner,
    )

    assert result.migration_state == "pre_alembic"
    assert result.alembic_revision is None
    assert result.federated_identity_count is None
    assert len(runner.calls) == 8
    assert "expected_foreign_keys" in " ".join(runner.calls[5][0])
    assert "federated_identities" in " ".join(runner.calls[6][0])
    assert "alembic_version" in " ".join(runner.calls[6][0])


def test_restore_rejects_partial_alembic_or_identity_state(tmp_path):
    archive, manifest = _write_backup_pair(tmp_path)
    target = "litblog_restore_verify_mixed"
    runner = RecordingRunner(
        responses=[
            {"returncode": 0, "stdout": "", "stderr": ""},
            {"returncode": 0, "stdout": "absent\n", "stderr": ""},
            {"returncode": 0, "stdout": "", "stderr": ""},
            {"returncode": 0, "stdout": "", "stderr": ""},
            {"returncode": 0, "stdout": "", "stderr": ""},
            {"returncode": 0, "stdout": "ok\n", "stderr": ""},
            {"returncode": 0, "stdout": "mixed\n", "stderr": ""},
        ]
    )

    with pytest.raises(postgres_common.PostgresOperatorError, match="mixed"):
        restore_verify_postgres.restore_and_verify(
            archive,
            manifest,
            target,
            confirmation=target,
            database_url=DATABASE_URL,
            runner=runner,
        )

    assert len(runner.calls) == 7


def test_restore_rejects_a_versioned_database_that_is_not_at_current_head(tmp_path):
    archive, manifest = _write_backup_pair(tmp_path)
    target = "litblog_restore_verify_old_revision"
    runner = RecordingRunner(
        responses=[
            {"returncode": 0, "stdout": "", "stderr": ""},
            {"returncode": 0, "stdout": "absent\n", "stderr": ""},
            {"returncode": 0, "stdout": "", "stderr": ""},
            {"returncode": 0, "stdout": "", "stderr": ""},
            {"returncode": 0, "stdout": "", "stderr": ""},
            {"returncode": 0, "stdout": "ok\n", "stderr": ""},
            {"returncode": 0, "stdout": "versioned\n", "stderr": ""},
            {"returncode": 0, "stdout": "985a04df032a\n", "stderr": ""},
        ]
    )

    with pytest.raises(postgres_common.PostgresOperatorError, match="current head"):
        restore_verify_postgres.restore_and_verify(
            archive,
            manifest,
            target,
            confirmation=target,
            database_url=DATABASE_URL,
            runner=runner,
        )

    assert len(runner.calls) == 8


def test_verify_existing_is_read_only_and_requires_current_head_and_mapping_count(tmp_path):
    target = "litblog_restore_verify_migrated"
    runner = RecordingRunner(
        responses=[
            {"returncode": 0, "stdout": "exists\n", "stderr": ""},
            {"returncode": 0, "stdout": "ok\n", "stderr": ""},
            {"returncode": 0, "stdout": "versioned\n", "stderr": ""},
            {"returncode": 0, "stdout": "f1ad78b2035f\n", "stderr": ""},
            {"returncode": 0, "stdout": "ok\n", "stderr": ""},
            {"returncode": 0, "stdout": "ok:4\n", "stderr": ""},
            {
                "returncode": 0,
                "stdout": _operator_routine_catalog_response(),
                "stderr": "",
            },
        ]
    )
    drift_checks = []

    result = restore_verify_postgres.verify_existing_database(
        target,
        confirmation=target,
        expected_federated_identities=4,
        database_url=DATABASE_URL,
        runner=runner,
        drift_checker=lambda connection, database: drift_checks.append(
            (connection.database, database)
        ),
    )

    assert result.migration_state == "current_head"
    assert result.alembic_revision == "f1ad78b2035f"
    assert result.federated_identity_count == 4
    assert drift_checks == [("litblogs", target)]
    assert [Path(call[0][0]).name for call in runner.calls] == ["psql"] * 7
    executables = [Path(command[0]).name for command, _ in runner.calls]
    assert "createdb" not in executables
    assert "pg_restore" not in executables
    assert "dropdb" not in executables
    assert runner.calls[0][1]["env"]["PGDATABASE"] == "postgres"
    assert all(call[1]["env"]["PGDATABASE"] == target for call in runner.calls[1:])


def test_current_head_restore_aborts_when_alembic_detects_schema_drift(tmp_path):
    archive, manifest = _write_backup_pair(tmp_path)
    target = "litblog_restore_verify_schema_drift"
    runner = RecordingRunner(
        responses=[
            {"returncode": 0, "stdout": "", "stderr": ""},
            {"returncode": 0, "stdout": "absent\n", "stderr": ""},
            {"returncode": 0, "stdout": "", "stderr": ""},
            {"returncode": 0, "stdout": "", "stderr": ""},
            {"returncode": 0, "stdout": "", "stderr": ""},
            {"returncode": 0, "stdout": "ok\n", "stderr": ""},
            {"returncode": 0, "stdout": "versioned\n", "stderr": ""},
            {"returncode": 0, "stdout": "f1ad78b2035f\n", "stderr": ""},
            {"returncode": 0, "stdout": "ok\n", "stderr": ""},
            {"returncode": 0, "stdout": "ok:0\n", "stderr": ""},
            {
                "returncode": 0,
                "stdout": _operator_routine_catalog_response(),
                "stderr": "",
            },
        ]
    )

    with pytest.raises(postgres_common.PostgresOperatorError, match="schema drift"):
        restore_verify_postgres.restore_and_verify(
            archive,
            manifest,
            target,
            confirmation=target,
            database_url=DATABASE_URL,
            runner=runner,
            drift_checker=lambda _connection, _database: (_ for _ in ()).throw(
                RuntimeError("private schema detail; password=secret")
            ),
        )


def test_verify_existing_rejects_mapping_count_mismatch_without_mutation(tmp_path):
    target = "litblog_restore_verify_mapping_mismatch"
    runner = RecordingRunner(
        responses=[
            {"returncode": 0, "stdout": "exists\n", "stderr": ""},
            {"returncode": 0, "stdout": "ok\n", "stderr": ""},
            {"returncode": 0, "stdout": "versioned\n", "stderr": ""},
            {"returncode": 0, "stdout": "f1ad78b2035f\n", "stderr": ""},
            {"returncode": 0, "stdout": "ok\n", "stderr": ""},
            {"returncode": 0, "stdout": "ok:3\n", "stderr": ""},
        ]
    )

    with pytest.raises(postgres_common.PostgresOperatorError, match="approved inventory"):
        restore_verify_postgres.verify_existing_database(
            target,
            confirmation=target,
            expected_federated_identities=4,
            database_url=DATABASE_URL,
            runner=runner,
        )

    assert [Path(call[0][0]).name for call in runner.calls] == ["psql"] * 6


def test_verify_existing_rejects_pre_alembic_and_invalid_count_before_mutation(tmp_path):
    target = "litblog_restore_verify_not_migrated"
    runner = RecordingRunner(
        responses=[
            {"returncode": 0, "stdout": "exists\n", "stderr": ""},
            {"returncode": 0, "stdout": "ok\n", "stderr": ""},
            {"returncode": 0, "stdout": "pre_alembic\n", "stderr": ""},
        ]
    )

    with pytest.raises(postgres_common.PostgresOperatorError, match="current head"):
        restore_verify_postgres.verify_existing_database(
            target,
            confirmation=target,
            expected_federated_identities=0,
            database_url=DATABASE_URL,
            runner=runner,
        )
    assert [Path(call[0][0]).name for call in runner.calls] == ["psql"] * 3

    no_calls = RecordingRunner()
    with pytest.raises(postgres_common.PostgresOperatorError, match="count"):
        restore_verify_postgres.verify_existing_database(
            target,
            confirmation=target,
            expected_federated_identities=-1,
            database_url=DATABASE_URL,
            runner=no_calls,
        )
    assert no_calls.calls == []


def test_restore_refuses_an_existing_database_before_any_create_or_restore(tmp_path):
    archive, manifest = _write_backup_pair(tmp_path)
    target = "litblog_restore_verify_existing"
    runner = RecordingRunner(
        responses=[
            {"returncode": 0, "stdout": "", "stderr": ""},
            {"returncode": 0, "stdout": "exists\n", "stderr": ""},
        ]
    )

    with pytest.raises(postgres_common.PostgresOperatorError, match="already exists"):
        restore_verify_postgres.restore_and_verify(
            archive,
            manifest,
            target,
            confirmation=target,
            database_url=DATABASE_URL,
            runner=runner,
        )

    assert [Path(call[0][0]).name for call in runner.calls] == [
        "pg_restore",
        "psql",
    ]


def test_restore_requires_exact_confirmation_before_running_any_command(tmp_path):
    archive, manifest = _write_backup_pair(tmp_path)
    runner = RecordingRunner()

    with pytest.raises(postgres_common.PostgresOperatorError, match="confirmation"):
        restore_verify_postgres.restore_and_verify(
            archive,
            manifest,
            "litblog_restore_verify_20260821",
            confirmation="litblog_restore_verify_wrong",
            database_url=DATABASE_URL,
            runner=runner,
        )

    assert runner.calls == []


def test_restore_rejects_checksum_mismatch_before_contacting_postgres(tmp_path):
    archive, manifest = _write_backup_pair(tmp_path)
    archive.write_bytes(b"PGDMP-tampered")
    runner = RecordingRunner()
    target = "litblog_restore_verify_20260821"

    with pytest.raises(postgres_common.PostgresOperatorError, match="checksum"):
        restore_verify_postgres.restore_and_verify(
            archive,
            manifest,
            target,
            confirmation=target,
            database_url=DATABASE_URL,
            runner=runner,
        )

    assert runner.calls == []


@pytest.mark.skipif(os.name != "posix", reason="POSIX custody bits required")
@pytest.mark.parametrize(("artifact", "mode"), [("archive", 0o640), ("manifest", 0o604)])
def test_restore_rejects_group_or_world_readable_copies_before_hash_or_database(
    tmp_path, artifact, mode
):
    archive, manifest = _write_backup_pair(tmp_path)
    selected = archive if artifact == "archive" else manifest
    selected.chmod(mode)
    runner = RecordingRunner()

    with pytest.raises(postgres_common.PostgresOperatorError, match="custody"):
        restore_verify_postgres.restore_and_verify(
            archive,
            manifest,
            "litblog_restore_verify_private_custody",
            confirmation="litblog_restore_verify_private_custody",
            database_url=DATABASE_URL,
            runner=runner,
        )

    assert runner.calls == []


@pytest.mark.parametrize(
    "manifest_payload",
    [
        "not-json",
        "{}",
        json.dumps(
            {
                "archive": "../production.dump",
                "created_at": "2026-08-21T22:00:00Z",
                "format": "litblogs-postgresql-custom-v1",
                "sha256": "0" * 64,
                "size_bytes": 5,
            }
        ),
        json.dumps(
            {
                "archive": "litblogs.dump",
                "created_at": "not-a-time",
                "format": "unknown",
                "sha256": "not-a-checksum",
                "size_bytes": -1,
            }
        ),
    ],
)
def test_restore_rejects_malformed_manifests_without_running_commands(tmp_path, manifest_payload):
    archive, manifest = _write_backup_pair(tmp_path)
    manifest.write_text(manifest_payload, encoding="utf-8")
    runner = RecordingRunner()
    target = "litblog_restore_verify_20260821"

    with pytest.raises(postgres_common.PostgresOperatorError, match="manifest"):
        restore_verify_postgres.restore_and_verify(
            archive,
            manifest,
            target,
            confirmation=target,
            database_url=DATABASE_URL,
            runner=runner,
        )

    assert runner.calls == []


def test_restore_rejects_semantically_invalid_manifest_time_and_duplicate_keys(tmp_path):
    archive, manifest = _write_backup_pair(tmp_path)
    target = "litblog_restore_verify_bad_manifest"

    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["created_at"] = "2026-02-31T22:00:00Z"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    runner = RecordingRunner()
    with pytest.raises(postgres_common.PostgresOperatorError, match="manifest"):
        restore_verify_postgres.restore_and_verify(
            archive,
            manifest,
            target,
            confirmation=target,
            database_url=DATABASE_URL,
            runner=runner,
        )
    assert runner.calls == []

    duplicate_manifest = json.dumps(payload | {"created_at": "2026-08-21T22:00:00Z"})
    duplicate_manifest = duplicate_manifest[:-1] + ', "format": "litblogs-postgresql-custom-v1"}'
    manifest.write_text(duplicate_manifest, encoding="utf-8")
    with pytest.raises(postgres_common.PostgresOperatorError, match="manifest"):
        restore_verify_postgres.restore_and_verify(
            archive,
            manifest,
            target,
            confirmation=target,
            database_url=DATABASE_URL,
            runner=runner,
        )
    assert runner.calls == []


def test_restore_failure_redacts_child_output_and_never_runs_a_drop(tmp_path):
    archive, manifest = _write_backup_pair(tmp_path)
    target = "litblog_restore_verify_20260821"
    runner = RecordingRunner(
        responses=[
            {"returncode": 0, "stdout": "", "stderr": ""},
            {"returncode": 0, "stdout": "absent\n", "stderr": ""},
            {"returncode": 0, "stdout": "", "stderr": ""},
            {"returncode": 0, "stdout": "", "stderr": ""},
            {
                "returncode": 1,
                "stdout": "",
                "stderr": "restore failed with backup-4R!v9nK2sQ7x",
            },
        ]
    )

    with pytest.raises(postgres_common.PostgresOperatorError) as failure:
        restore_verify_postgres.restore_and_verify(
            archive,
            manifest,
            target,
            confirmation=target,
            database_url=DATABASE_URL,
            runner=runner,
        )

    assert "backup-4R!v9nK2sQ7x" not in str(failure.value)
    assert Path(runner.calls[4][0][0]).name == "pg_restore"
    all_arguments = " ".join(argument for command, _ in runner.calls for argument in command).lower()
    assert "dropdb" not in all_arguments
    assert "drop database" not in all_arguments


def test_restore_script_contains_no_database_drop_primitive():
    source = (SCRIPT_DIR / "restore_verify_postgres.py").read_text(encoding="utf-8").lower()

    assert "dropdb" not in source
    assert "drop database" not in source
    assert "shell=true" not in source


@pytest.mark.skipif(os.name != "posix", reason="POSIX ownership and modes required")
def test_restore_rejects_noncanonical_or_shared_staging_custody_before_database_contact(
    tmp_path,
):
    staging = tmp_path / "staging"
    staging.mkdir(mode=0o700)
    archive, manifest = _write_backup_pair(staging)
    staging.chmod(0o750)
    runner = RecordingRunner()

    with pytest.raises(postgres_common.PostgresOperatorError, match="owner-only"):
        restore_verify_postgres.restore_and_verify(
            archive,
            manifest,
            "litblog_restore_verify_20260822_custody",
            confirmation="litblog_restore_verify_20260822_custody",
            database_url=DATABASE_URL,
            runner=runner,
        )
    assert runner.calls == []

    staging.chmod(0o700)
    alias = tmp_path / "staging-alias"
    alias.symlink_to(staging, target_is_directory=True)
    runner = RecordingRunner()
    with pytest.raises(postgres_common.PostgresOperatorError, match="custody"):
        restore_verify_postgres.restore_and_verify(
            alias / archive.name,
            alias / manifest.name,
            "litblog_restore_verify_20260822_alias",
            confirmation="litblog_restore_verify_20260822_alias",
            database_url=DATABASE_URL,
            runner=runner,
        )
    assert runner.calls == []

    mutable_parent = tmp_path / "mutable-parent"
    mutable_staging = mutable_parent / "staging"
    mutable_staging.mkdir(parents=True, mode=0o700)
    mutable_archive, mutable_manifest = _write_backup_pair(mutable_staging)
    mutable_parent.chmod(0o775)
    runner = RecordingRunner()
    with pytest.raises(postgres_common.PostgresOperatorError, match="ancestor.*permissions"):
        restore_verify_postgres.restore_and_verify(
            mutable_archive,
            mutable_manifest,
            "litblog_restore_verify_20260822_mutable_parent",
            confirmation="litblog_restore_verify_20260822_mutable_parent",
            database_url=DATABASE_URL,
            runner=runner,
        )
    assert runner.calls == []


@pytest.mark.parametrize(
    "release_id",
    [
        "",
        "main",
        "litblogs-latest",
        "litblogs-ABCDEF123456",
        "litblogs-abcdef12345",
        "litblogs-abcdef1234567",
        "litblogs-abcdef12345/../production",
        "../litblogs-abcdef123456",
    ],
)
def test_release_identifier_accepts_only_artifact_commit_names(release_id):
    with pytest.raises(release_switch.ReleaseSwitchError):
        release_switch.validate_release_id(release_id)


def test_release_mode_rejects_group_or_world_writable_artifacts():
    assert release_switch.is_immutable_release_mode(0o700)
    assert release_switch.is_immutable_release_mode(0o750)
    assert release_switch.is_immutable_release_mode(0o755)
    assert release_switch.is_immutable_release_mode(0o644)
    assert not release_switch.is_immutable_release_mode(0o775)
    assert not release_switch.is_immutable_release_mode(0o757)
    assert not release_switch.is_immutable_release_mode(0o666)


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits required")
def test_trusted_release_python_rejects_group_writable_custody(tmp_path, monkeypatch):
    runtime = tmp_path / "python3.13"
    runtime.write_bytes(b"synthetic interpreter")
    runtime.chmod(0o775)
    monkeypatch.setattr(release_switch.sys, "executable", str(runtime))
    monkeypatch.setattr(
        release_switch.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail(
            "unsafe interpreter custody must fail before execution"
        ),
    )

    with pytest.raises(release_switch.ReleaseSwitchError, match="unsafe custody"):
        release_switch._trusted_python()


def test_trusted_release_python_rejects_wrong_interpreter_version(tmp_path, monkeypatch):
    runtime = tmp_path / "python3.13"
    runtime.write_bytes(b"synthetic interpreter")
    runtime.chmod(0o755)
    monkeypatch.setattr(release_switch.sys, "executable", str(runtime))

    def wrong_version(command, **_kwargs):
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="Python 3.12.10\n",
            stderr="",
        )

    monkeypatch.setattr(release_switch.subprocess, "run", wrong_version)

    with pytest.raises(release_switch.ReleaseSwitchError, match="reviewed Python 3.13"):
        release_switch._trusted_python()


@pytest.mark.skipif(os.name != "posix", reason="POSIX ownership required")
def test_release_lock_rejects_non_root_ownership(tmp_path, monkeypatch):
    root = tmp_path / "litblogs"
    root.mkdir()
    real_fstat = os.fstat

    def report_non_root_owner(descriptor):
        return _stat_result_with(
            real_fstat(descriptor),
            owner_uid=max(1, os.geteuid()),
        )

    monkeypatch.setattr(release_switch.os, "fstat", report_non_root_owner)

    with pytest.raises(release_switch.ReleaseSwitchError, match="unsafe custody"):
        with release_switch._release_lock(root):
            pytest.fail("a non-root release lock must never be acquired")


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits required")
def test_release_lock_rejects_group_writable_mode(tmp_path, monkeypatch):
    root = tmp_path / "litblogs"
    root.mkdir()
    real_fstat = os.fstat

    def report_group_writable_mode(descriptor):
        metadata = real_fstat(descriptor)
        return _stat_result_with(
            metadata,
            owner_uid=0,
            mode=metadata.st_mode | stat.S_IWGRP,
        )

    monkeypatch.setattr(release_switch.os, "fstat", report_group_writable_mode)

    with pytest.raises(release_switch.ReleaseSwitchError, match="unsafe custody"):
        with release_switch._release_lock(root):
            pytest.fail("a group-writable release lock must never be acquired")


def test_release_tree_rejects_unreviewed_application_symlinks(
    tmp_path, synthetic_trusted_release_python
):
    release = tmp_path / "release"
    (release / "litblogs").mkdir(parents=True)
    outside = tmp_path / "outside.py"
    outside.write_text("unreviewed", encoding="utf-8")
    try:
        (release / "litblogs" / "main.py").symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable in this test environment: {exc}")

    with pytest.raises(release_switch.ReleaseSwitchError, match="symlink"):
        release_switch._validate_release_tree(release)


def test_release_activation_fsyncs_the_pointer_directory(
    tmp_path, monkeypatch, root_owned_release_lock_metadata
):
    root = tmp_path / "litblogs"
    (root / "releases").mkdir(parents=True)
    release_id, _release = _write_release(root, "123456789abc")
    events = []
    real_replace = os.replace

    def record_replace(source, destination):
        events.append(("replace", Path(destination)))
        real_replace(source, destination)

    monkeypatch.setattr(release_switch.os, "replace", record_replace)
    monkeypatch.setattr(
        release_switch,
        "_fsync_directory",
        lambda directory: events.append(("fsync", Path(directory))),
    )

    try:
        release_switch.activate_release(
            root,
            release_id,
            confirmation=release_id,
            expected_commit=_release_commit("123456789abc"),
        )
    except OSError as exc:
        pytest.skip(f"symlinks unavailable in this test environment: {exc}")

    expected_events = [
        *(([("fsync", root)]) if os.name == "posix" else []),
        ("replace", root / "current"),
        ("fsync", root),
    ]
    assert events == expected_events


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits required")
def test_release_activation_rejects_a_group_writable_release_root(tmp_path):
    root = tmp_path / "litblogs"
    release_id, _ = _write_release(root, "090909090909")
    root.chmod(0o775)

    with pytest.raises(release_switch.ReleaseSwitchError, match="writable"):
        release_switch.activate_release(
            root,
            release_id,
            confirmation=release_id,
            expected_commit=_release_commit("090909090909"),
        )

    assert not (root / "current").exists()


def test_release_activation_is_atomic_and_rollback_targets_last_known_release(
    tmp_path, root_owned_release_lock_metadata
):
    root = tmp_path / "litblogs"
    first_id, first_release = _write_release(root, "111111111111")
    second_id, second_release = _write_release(root, "222222222222")

    try:
        first = release_switch.activate_release(
            root,
            first_id,
            confirmation=first_id,
            expected_commit=_release_commit("111111111111"),
        )
    except OSError as exc:
        pytest.skip(f"symlinks unavailable in this test environment: {exc}")

    assert first.active_release == first_id
    assert first.previous_release is None
    assert (root / "current").is_symlink()
    assert (root / "current").resolve() == first_release.resolve()

    second = release_switch.activate_release(
        root,
        second_id,
        confirmation=second_id,
        expected_commit=_release_commit("222222222222"),
    )
    assert second.active_release == second_id
    assert second.previous_release == first_id
    assert (root / "current").resolve() == second_release.resolve()
    assert (root / "previous").is_symlink()
    assert (root / "previous").resolve() == first_release.resolve()

    rolled_back = release_switch.rollback_release(root, confirmation=first_id)
    assert rolled_back.active_release == first_id
    assert rolled_back.previous_release == first_id
    assert (root / "current").resolve() == first_release.resolve()


def test_release_activation_rejects_an_orphan_previous_pointer(
    tmp_path, root_owned_release_lock_metadata
):
    root = tmp_path / "litblogs"
    stale_id, stale_release = _write_release(root, "121212121212")
    next_id, _next_release = _write_release(root, "343434343434")
    try:
        (root / "previous").symlink_to(
            Path("releases") / stale_id, target_is_directory=True
        )
    except OSError as exc:
        pytest.skip(f"symlinks unavailable in this test environment: {exc}")

    with pytest.raises(release_switch.ReleaseSwitchError, match="previous.*current"):
        release_switch.activate_release(
            root,
            next_id,
            confirmation=next_id,
            expected_commit=_release_commit("343434343434"),
        )

    assert not (root / "current").exists()
    assert (root / "previous").resolve() == stale_release.resolve()


def test_release_activation_refuses_to_overwrite_a_real_current_path(
    tmp_path, root_owned_release_lock_metadata
):
    root = tmp_path / "litblogs"
    release_id, _ = _write_release(root, "333333333333")
    (root / "current").mkdir()

    with pytest.raises(release_switch.ReleaseSwitchError, match="symlink"):
        release_switch.activate_release(
            root,
            release_id,
            confirmation=release_id,
            expected_commit=_release_commit("333333333333"),
        )

    assert (root / "current").is_dir()
    assert not (root / "current").is_symlink()


def test_release_activation_rejects_manifest_commit_mismatch(
    tmp_path, root_owned_release_lock_metadata
):
    root = tmp_path / "litblogs"
    release_id, release = _write_release(
        root,
        "444444444444",
        full_sha="555555555555" + ("5" * 28),
    )

    with pytest.raises(release_switch.ReleaseSwitchError, match="manifest"):
        release_switch.activate_release(
            root,
            release_id,
            confirmation=release_id,
            expected_commit="555555555555" + ("5" * 28),
        )

    assert not (root / "current").exists()


def test_release_activation_requires_exact_confirmation_before_pointer_changes(tmp_path):
    root = tmp_path / "litblogs"
    release_id, _ = _write_release(root, "666666666666")

    with pytest.raises(release_switch.ReleaseSwitchError, match="confirmation"):
        release_switch.activate_release(
            root,
            release_id,
            confirmation="litblogs-777777777777",
            expected_commit=_release_commit("666666666666"),
        )

    assert not (root / "current").exists()


def test_release_activation_requires_the_exact_reviewed_main_commit(
    tmp_path, root_owned_release_lock_metadata
):
    root = tmp_path / "litblogs"
    release_id, _ = _write_release(root, "999999999999")

    with pytest.raises(release_switch.ReleaseSwitchError, match="reviewed main"):
        release_switch.activate_release(
            root,
            release_id,
            confirmation=release_id,
            expected_commit="e" * 40,
        )

    assert not (root / "current").exists()


def test_release_rollback_refuses_pointer_that_escapes_release_root(
    tmp_path, root_owned_release_lock_metadata
):
    root = tmp_path / "litblogs"
    root.mkdir()
    (root / "releases").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "RELEASE-MANIFEST").write_text(
        f"commit={'8' * 40}\nbuilt_at_epoch=1787359200\n",
        encoding="utf-8",
    )
    try:
        (root / "previous").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable in this test environment: {exc}")

    with pytest.raises(release_switch.ReleaseSwitchError, match="outside"):
        release_switch.rollback_release(root, confirmation="litblogs-888888888888")


def test_production_runbook_covers_recovery_privacy_and_identity_blockers():
    runbook_path = ROOT_DIR / "docs" / "operations" / "production-runbook.md"
    assert runbook_path.is_file()
    runbook = runbook_path.read_text(encoding="utf-8").lower()

    required_topics = {
        "recovery point objective (rpo)",
        "recovery time objective (rto)",
        "retention",
        "legal hold",
        "quarterly restore drill",
        "incident response",
        "secret rotation",
        "legacy oauth",
        "upload store",
        "school it responsibilities",
        "litblog_restore_verify_",
        "release_switch.py activate",
        "release_switch.py rollback",
    }
    assert required_topics <= {topic for topic in required_topics if topic in runbook}


def test_runbook_supersedes_raw_identity_sql_and_orders_safe_alembic_adoption():
    runbook = (ROOT_DIR / "docs" / "operations" / "production-runbook.md").read_text(encoding="utf-8").lower()

    assert "migrations/0001_create_federated_identities.sql" in runbook
    assert "superseded" in runbook
    assert "/.venv/bin/python -m alembic -c " in runbook
    assert "alembic.ini stamp 985a04df032a" in runbook
    assert "alembic.ini upgrade head" in runbook
    assert "never run both" in runbook
    assert "abort" in runbook
    assert "disposable" in runbook
    assert "email-only" in runbook
    assert "--verify-existing" in runbook
    assert "--expected-federated-identities" in runbook
    assert "pre_alembic" in runbook
    assert "current_head" in runbook
    assert "second verifier" in runbook


def test_deploy_readme_documents_hardened_installation_and_least_privilege_paths():
    readme_path = ROOT_DIR / "deploy" / "README.md"
    assert readme_path.is_file()
    readme = readme_path.read_text(encoding="utf-8").lower()

    for required in (
        "systemd",
        "nginx -t",
        "/etc/litblogs/litblogs.env",
        "/opt/litblogs/releases",
        "/var/lib/litblogs/uploads",
        "root:litblogs",
        "0640",
        "least privilege",
        "tls",
    ):
        assert required in readme


def test_operator_docs_require_unambiguous_managed_database_authentication():
    documents = [
        (ROOT_DIR / "deploy" / "README.md").read_text(encoding="utf-8").lower(),
        (ROOT_DIR / "docs" / "operations" / "production-runbook.md").read_text(
            encoding="utf-8"
        ).lower(),
    ]

    for document in documents:
        assert "percent-encode" in document
        assert "at least 16 utf-8 bytes" in document
        assert "passwordless" in document
        assert "trust authentication" in document
        assert "pg_hba.conf" in document
        assert "hostssl" in document
        assert "scram-sha-256" in document
        assert "wrong-password probe" in document
        assert "rotated-old password" in document


def test_operator_docs_define_dedicated_reset_identity_environment_and_ca_custody():
    documents = [
        (ROOT_DIR / "deploy" / "README.md").read_text(encoding="utf-8"),
        (ROOT_DIR / "docs" / "operations" / "production-runbook.md").read_text(
            encoding="utf-8"
        ),
    ]

    for document in documents:
        for required in (
            "`litblogs-reset`",
            "`/usr/sbin/nologin`",
            "no supplementary groups",
            "`/etc/litblogs/password-reset.env`",
            "`root:litblogs-reset` mode `0640`",
            "`InaccessiblePaths=/etc/litblogs/litblogs.env /var/lib/litblogs/uploads`",
            "`root:root` mode `0644`",
            "runuser -u litblogs-reset -- test -r /etc/litblogs/postgres-root-ca.pem",
            "runuser -u litblogs -- test -r /etc/litblogs/postgres-root-ca.pem",
            "service-context read and write probes",
        ):
            assert required in document
        assert "root:litblogs` mode `0640` or" not in document
        assert "or `root:litblogs` `0640`" not in document


def test_operator_docs_define_full_path_custody_and_nginx_header_inheritance_gates():
    documents = [
        (ROOT_DIR / "deploy" / "README.md").read_text(encoding="utf-8").lower(),
        (ROOT_DIR / "docs" / "operations" / "production-runbook.md").read_text(
            encoding="utf-8"
        ).lower(),
    ]

    for document in documents:
        assert "every parent directory" in document
        assert "non-sticky" in document
        assert "nginx add_header inheritance" in document
        assert "cache-control" in document


def test_operator_docs_match_release_local_systemd_runtime():
    documents = [
        (ROOT_DIR / "deploy" / "README.md").read_text(encoding="utf-8").lower(),
        (ROOT_DIR / "docs" / "operations" / "production-runbook.md").read_text(encoding="utf-8").lower(),
    ]

    for document in documents:
        assert "type=simple" in document
        assert "/opt/litblogs/current/.venv/bin/uvicorn" in document
        assert "/opt/litblogs/current/.venv/bin/python -m deployment_check" in document
        assert "/opt/litblogs/current/.venv/bin/python -m reminder_job" in document

    assert "add a reviewed systemd drop-in" not in documents[0]
    assert "notification-type" not in documents[0]


def test_operator_docs_order_candidate_build_preflight_migration_and_postflight():
    runbook = (
        ROOT_DIR / "docs" / "operations" / "production-runbook.md"
    ).read_text(encoding="utf-8").lower()

    venv = runbook.index("python3.13 -m venv")
    install = runbook.index(
        "python -m pip install --require-hashes --only-binary=:all: -r ",
        venv,
    )
    preflight = runbook.index("deployment_check --preflight", install)
    seal = runbook.index("final root-owned seal", preflight)
    migration_role = runbook.index("litblogs_migration_database_url", seal)
    upgrade = runbook.index("alembic.ini upgrade head", migration_role)
    runtime_role = runbook.index("least-privilege runtime database_url", upgrade)
    postflight = runbook.index("python -m deployment_check", runtime_role)
    service_start = runbook.index("systemctl restart litblogs-web.service", postflight)

    assert venv < install < preflight < seal
    assert seal < migration_role < upgrade < runtime_role < postflight < service_start
    assert "remove the migration-only credential" in runbook
    assert "database check is deliberately skipped" in runbook


def test_runbook_bootstraps_roles_before_migration_and_verifies_exact_acl():
    runbook = (
        ROOT_DIR / "docs" / "operations" / "production-runbook.md"
    ).read_text(encoding="utf-8").lower()
    normalized = " ".join(runbook.replace("`", "").split())

    role_bootstrap = runbook.index(
        "create or reconcile the migrator and four fixed application roles"
    )
    temporary_membership = runbook.index(
        "grant litblog_identity_owner to litblogs_migrator",
        role_bootstrap,
    )
    upgrade = runbook.index("alembic.ini upgrade head", temporary_membership)
    membership_revoke = runbook.index(
        "revoke litblog_identity_owner from litblogs_migrator",
        upgrade,
    )

    assert role_bootstrap < temporary_membership < upgrade < membership_revoke
    for role_name in (
        "litblogs_migrator",
        "litblogs_runtime",
        "litblog_identity_owner",
        "litblog_account_operator",
        "litblog_invitation_operator",
    ):
        assert role_name in runbook

    assert "with login noinherit nosuperuser" in normalized
    assert "with nologin noinherit nosuperuser" in normalized
    assert "no memberships" in runbook
    assert "missing fixed role" in runbook


def test_runbook_has_one_guarded_migration_path_and_guarded_f1_downgrade():
    runbook = (
        ROOT_DIR / "docs" / "operations" / "production-runbook.md"
    ).read_text(encoding="utf-8").lower()

    classification = runbook.index("this section classifies adoption state only")
    role_bootstrap = runbook.index(
        "create or reconcile the migrator and four fixed application roles"
    )
    temporary_membership = runbook.index(
        "grant litblog_identity_owner to litblogs_migrator",
        role_bootstrap,
    )
    stamp = runbook.index("alembic.ini stamp 985a04df032a", role_bootstrap)
    upgrade = runbook.index("alembic.ini upgrade head", temporary_membership)

    assert "not a runnable migration path" in runbook
    assert "do not execute alembic from this earlier section" in runbook
    assert runbook.count("alembic.ini upgrade head") == 1
    assert classification < role_bootstrap < stamp < temporary_membership < upgrade

    rollback = runbook[runbook.index("## rollback") :]
    assert "downgrade across `f1ad78b2035f`" in rollback
    assert "grant the exact direct `litblog_identity_owner` membership" in rollback
    assert "revoke litblog_identity_owner from litblogs_migrator" in rollback
    assert "prove both membership directions are empty" in rollback


def test_runbook_matches_the_runtime_database_identity_postflight():
    runbook = (
        ROOT_DIR / "docs" / "operations" / "production-runbook.md"
    ).read_text(encoding="utf-8").lower()
    normalized = " ".join(runbook.replace("`", "").split())

    for phrase in (
        "`session_user` and `current_user` are both exactly `litblogs_runtime`",
        "exact non-admin `login noinherit` attributes",
        "no membership in either direction",
        "pg_catalog.current_schemas(false) = array['public']",
        "grants `usage` but no `create`",
        "neither `create` nor `temporary`",
    ):
        assert phrase in runbook

    assert "runtime crud tables" in runbook
    for table_name in (
        "assignment_drafts",
        "assignment_reminder_notifications",
        "assignment_submission_replies",
        "assignment_submissions",
        "assignments",
        "blogs",
        "browser_sessions",
        "class_enrollments",
        "classes",
        "comment_likes",
        "comments",
        "federated_identities",
        "password_resets",
        "post_likes",
        "push_subscriptions",
        "saved_posts",
        "teachers",
        "upload_assets",
        "user_settings",
        "users",
    ):
        assert table_name in runbook

    assert (
        "teacher_invitations | select (id, token_digest, email_digest, expires_at, "
        "consumed_at, revoked_at), update (consumed_at, revoked_at)" in normalized
    )
    assert (
        "operator_audit_events | insert (actor_identifier, action, outcome, "
        "resource_digest)" in normalized
    )
    assert "alembic_version | select" in normalized
    assert "execute only" in normalized
    assert "has_column_privilege" in runbook
    assert "has_function_privilege" in runbook
    assert "has_table_privilege" in runbook
    assert "has_sequence_privilege" in runbook
    assert "blanket table, sequence, and default-privilege grants are prohibited" in (
        runbook
    )

    assert "grant select, insert, update, delete on all tables" not in runbook
    assert "grant usage, select on all sequences" not in runbook
    assert "grant select, insert, update, delete on tables to litblogs_runtime" not in (
        runbook
    )
    assert "must fail with insufficient_privilege" in runbook
    assert "create table litblogs_runtime_privilege_probe" in runbook


def test_runtime_browser_configuration_is_backend_owned_and_checked_in_the_bundle():
    documentation = "\n".join(
        [
            (ROOT_DIR / "deploy" / "README.md").read_text(encoding="utf-8"),
            (ROOT_DIR / "docs" / "operations" / "production-runbook.md").read_text(
                encoding="utf-8"
            ),
        ]
    ).lower()

    assert "/api/runtime-config" in documentation
    assert "backend settings at runtime" in documentation
    assert "vite_google_client_id" not in documentation


def test_operator_docs_require_hash_locked_runtime_and_lock_tool_installs():
    documentation = "\n".join(
        [
            (ROOT_DIR / "deploy" / "README.md").read_text(encoding="utf-8"),
            (ROOT_DIR / "docs" / "operations" / "production-runbook.md").read_text(encoding="utf-8"),
        ]
    ).lower()

    assert (
        "python -m pip install --require-hashes --only-binary=:all: "
        "-r requirements.txt" in documentation
    )
    assert (
        "python -m pip install --require-hashes --only-binary=:all: "
        "-r requirements-lock.txt" in documentation
    )
    assert "requirements-lock.txt" in documentation
    assert "unhashed" in documentation


def test_operator_docs_verify_release_checksum_provenance_and_reviewed_commit():
    documentation = "\n".join(
        [
            (ROOT_DIR / "deploy" / "README.md").read_text(encoding="utf-8"),
            (ROOT_DIR / "docs" / "operations" / "production-runbook.md").read_text(encoding="utf-8"),
        ]
    ).lower()

    assert "sha256sum --check sha256sums" in documentation
    assert "gh attestation verify" in documentation
    assert "--repo citdrhs/litblogs" in documentation
    assert "--predicate-type https://cyclonedx.org/bom" in documentation
    assert "--source-digest <reviewed-main-40-character-sha>" in documentation
    assert "--signer-workflow" in documentation
    assert "--deny-self-hosted-runners" in documentation
    assert "before extraction" in documentation
    assert "reviewed main sha" in documentation
    assert "two sbom" in documentation


def test_operator_docs_describe_the_least_privilege_release_attestation_split():
    documents = [
        (ROOT_DIR / "deploy" / "README.md").read_text(encoding="utf-8").lower(),
        (ROOT_DIR / "docs" / "operations" / "production-runbook.md").read_text(encoding="utf-8").lower(),
    ]

    for document in documents:
        assert "build, test, and package" in document
        assert "`build-release`" in document
        assert "least privilege" in document
        assert "`attest-release`" in document
        assert "protected environment" in document
        assert "only after `attest-release` succeeds" in document


def test_operator_docs_make_backup_encryption_and_custody_deployment_gates():
    documentation = "\n".join(
        [
            (ROOT_DIR / "deploy" / "README.md").read_text(encoding="utf-8"),
            (ROOT_DIR / "docs" / "operations" / "production-runbook.md").read_text(encoding="utf-8"),
        ]
    ).lower()

    for required in (
        "encrypted at rest",
        "encrypted transport",
        "sslmode=verify-full",
        "least-privilege backup",
        "root-controlled backup wrapper",
        "0600",
        "web `litblogs` service cannot read or write the backup mount",
        "access logging",
        "managed secret",
        "file descriptor",
        "fail the deployment",
        "checksum",
        "retention",
        "legal hold",
    ):
        assert required in documentation


def test_operator_docs_enumerate_the_production_environment_contract():
    readme = (ROOT_DIR / "deploy" / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT_DIR / "docs" / "operations" / "production-runbook.md").read_text(encoding="utf-8")
    documents = [readme, runbook]
    required_settings = {
        "APP_ENV",
        "DATABASE_URL",
        "SECRET_KEY",
        "JWT_ISSUER",
        "JWT_AUDIENCE",
        "FRONTEND_URL",
        "CORS_ALLOWED_ORIGINS",
        "ALLOWED_HOSTS",
        "ALLOWED_EMAIL_DOMAINS",
        "GOOGLE_CLIENT_ID",
        "MICROSOFT_CLIENT_ID",
        "MICROSOFT_TENANT_ID",
        "MICROSOFT_ALLOWED_TENANT_IDS",
        "SESSION_COOKIE_NAME",
        "CSRF_COOKIE_NAME",
        "SESSION_COOKIE_SECURE",
        "LOCAL_PASSWORD_REGISTRATION_ENABLED",
        "ADMIN_ACCESS_CODE",
        "TEACHER_INVITE_HMAC_KEY",
        "RESET_DATABASE_ON_STARTUP",
        "API_DOCS_ENABLED",
        "EMAIL_HOST",
        "EMAIL_PORT",
        "EMAIL_USERNAME",
        "EMAIL_PASSWORD",
        "EMAIL_FROM",
        "PASSWORD_RESET_WORKER_ENABLED",
        "PUSH_NOTIFICATIONS_ENABLED",
        "UPLOAD_ROOT",
        "UPLOAD_SCANNER_REQUIRED",
        "UPLOAD_SCANNER_HOST",
        "UPLOAD_SCANNER_ALLOWED_HOSTS",
        "UPLOAD_REGISTRY_SCHEMA_READY",
        "UPLOAD_LEGACY_IMPORT_COMPLETE",
        "UPLOAD_BACKUP_RESTORE_VERIFIED",
        "VAPID_PUBLIC_KEY",
        "VAPID_PRIVATE_KEY",
        "VAPID_SUBJECT",
    }

    for document in documents:
        assert required_settings <= {setting for setting in required_settings if setting in document}
        assert "JWT_ISSUER=https://<school-approved-host>" in document
        assert "JWT_AUDIENCE=litblogs-production" in document
        assert "ALLOWED_HOSTS=<school-approved-host>" in document
        assert "SESSION_COOKIE_NAME=__Host-litblogs-session" in document
        assert "CSRF_COOKIE_NAME=__Host-litblogs-csrf" in document
        assert "SESSION_COOKIE_SECURE=true" in document
        assert "PUSH_NOTIFICATIONS_ENABLED=false" in document
        assert "development-only" in document.lower()
        assert "reserved documentation domains" in document.lower()
        assert "JWT_ISSUER=https://litblogs.school.example" not in document

    assert "/opt/litblogs/releases/<release-id>/.venv/bin/python -m deployment_check" in runbook


def test_operator_docs_define_the_privacy_preserving_logging_gate():
    documents = [
        (ROOT_DIR / "deploy" / "README.md").read_text(encoding="utf-8").lower(),
        (ROOT_DIR / "docs" / "operations" / "production-runbook.md").read_text(encoding="utf-8").lower(),
    ]

    for document in documents:
        for required in (
            "query strings",
            "referrers",
            "route templates",
            "request bodies",
            "tokens",
            "email addresses",
            "student content",
            "ip addresses",
            "user agents",
            "request ids",
            "siem access",
            "encrypted transport",
            "encrypted storage",
            "retention",
            "deletion",
            "legal hold",
            "redaction",
            "alerting",
        ):
            assert required in document

        assert "uvicorn access logger" in document
        assert "--no-access-log" in document
        assert "ordinary 4xx and upstream warnings" in document
        assert "critical nginx error logs" in document
        assert "path identifier" in document
        assert "upload filename" in document


def test_push_dispatch_and_timer_remain_deliberately_disabled_in_production():
    readme = (ROOT_DIR / "deploy" / "README.md").read_text(encoding="utf-8").lower()
    runbook = (
        ROOT_DIR / "docs" / "operations" / "production-runbook.md"
    ).read_text(encoding="utf-8").lower()
    job = (
        ROOT_DIR / "deploy" / "systemd" / "litblogs-reminders.service"
    ).read_text(encoding="utf-8")

    for document in (readme, runbook):
        assert "push_notifications_enabled=false" in document
        assert "deliberately disabled" in document
        assert "do not enable litblogs-reminders.timer" in document
    assert "RuntimeMaxSec=300" in job


def test_packaged_legacy_sql_readme_is_an_unmistakable_superseded_notice():
    legacy_doc = (
        ROOT_DIR / "litblogs" / "migrations" / "README-federated-identities.md"
    ).read_text(encoding="utf-8").lower()

    assert "superseded" in legacy_doc
    assert "development history only" in legacy_doc
    assert "docs/operations/production-runbook.md" in legacy_doc
    assert "do not execute" in legacy_doc
    assert "psql" not in legacy_doc
    assert "on_error_stop" not in legacy_doc


def test_operator_python_is_in_every_shared_static_analysis_gate():
    ruff_runner = (ROOT_DIR / "scripts" / "run-backend-ruff.py").read_text(
        encoding="utf-8"
    )
    bandit_runner = (ROOT_DIR / "scripts" / "run-backend-bandit.py").read_text(
        encoding="utf-8"
    )
    ci = (ROOT_DIR / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    pre_commit = (ROOT_DIR / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    validator = (
        ROOT_DIR / "scripts" / "validate-repository-policy.py"
    ).read_text(encoding="utf-8")

    for runner in (ruff_runner, bandit_runner):
        assert '"litblogs"' in runner
        assert '"deploy/scripts"' in runner
        assert "REPOSITORY_ROOT" in runner
    assert '"litblogs/pyproject.toml"' in ruff_runner
    assert "run: python scripts/run-backend-ruff.py" in ci
    assert "run: python -m ruff check ." not in ci
    assert "deploy/scripts" in pre_commit
    assert "BACKEND_RUFF_COMMAND" in validator
    assert "deploy/scripts" in validator


def test_policy_validator_enforces_real_postgres_operator_and_migration_drift_gates():
    validator = (
        ROOT_DIR / "scripts" / "validate-repository-policy.py"
    ).read_text(encoding="utf-8")

    assert "tests/test_postgres_operator_integration.py" in validator
    assert "job.services.postgres.id" in validator
    assert "?sslmode=verify-full" in validator
    assert '"python -m alembic check"' in validator


def test_release_rollback_is_one_way_and_reactivation_requires_fresh_verification():
    runbook = (
        ROOT_DIR / "docs" / "operations" / "production-runbook.md"
    ).read_text(encoding="utf-8").lower()

    assert "one-way and idempotent" in runbook
    assert "does not swap" in runbook
    assert "fresh `activate`" in runbook
    assert "--expected-commit" in runbook


def _nginx_server_directives() -> list[list[str]]:
    nginx_config = (ROOT_DIR / "deploy" / "nginx" / "litblogs.conf").read_text(
        encoding="utf-8"
    )
    server_directives: list[list[str]] = []
    current_directives: list[str] | None = None
    depth = 0

    for line in nginx_config.splitlines():
        directive = line.split("#", 1)[0].strip()
        if current_directives is None:
            if directive == "server {":
                current_directives = []
                depth = 1
            continue

        if depth == 1 and directive and directive != "}":
            current_directives.append(directive)
        depth += directive.count("{") - directive.count("}")
        if depth == 0:
            server_directives.append(current_directives)
            current_directives = None

    assert current_directives is None
    return server_directives


def test_every_nginx_server_uses_the_privacy_log_or_disables_access_logging():
    server_directives = _nginx_server_directives()

    assert len(server_directives) >= 2
    for directives in server_directives:
        access_logs = [
            directive
            for directive in directives
            if directive.startswith("access_log ")
        ]
        assert any(
            directive == "access_log off;"
            or directive.endswith(" litblogs_privacy;")
            for directive in access_logs
        )


def test_nginx_http_redirect_rejects_unknown_hosts_and_uses_the_canonical_name():
    nginx_config = (ROOT_DIR / "deploy" / "nginx" / "litblogs.conf").read_text(
        encoding="utf-8"
    )

    assert "listen 80 default_server;" in nginx_config
    assert "listen [::]:80 default_server;" in nginx_config
    assert "server_name _;" in nginx_config
    assert "return 444;" in nginx_config
    assert "return 301 https://$server_name$request_uri;" in nginx_config
    assert "https://$host$request_uri" not in nginx_config


def test_nginx_tls_default_server_rejects_unknown_sni_before_content_routing():
    server_directives = _nginx_server_directives()
    tls_defaults = [
        directives
        for directives in server_directives
        if "listen 443 ssl default_server;" in directives
    ]

    assert len(tls_defaults) == 1
    assert "listen [::]:443 ssl default_server;" in tls_defaults[0]
    assert "server_name _;" in tls_defaults[0]
    assert "ssl_reject_handshake on;" in tls_defaults[0]


def test_every_nginx_server_suppresses_query_bearing_noncritical_error_logs():
    for directives in _nginx_server_directives():
        error_logs = [
            directive
            for directive in directives
            if directive.startswith("error_log ")
        ]
        assert error_logs
        assert all(directive.endswith(" crit;") for directive in error_logs)


def test_systemd_disables_uvicorns_query_string_access_logger():
    unit = (ROOT_DIR / "deploy" / "systemd" / "litblogs-web.service").read_text(
        encoding="utf-8"
    )
    exec_start = next(
        line for line in unit.splitlines() if line.startswith("ExecStart=")
    )

    assert "/opt/litblogs/current/.venv/bin/uvicorn" in exec_start
    assert "--no-access-log" in exec_start.split()


def test_unhandled_request_errors_emit_correlated_safe_diagnostics(caplog):
    from fastapi.testclient import TestClient
    from starlette.applications import Starlette
    from starlette.routing import Route

    from observability import RequestObservabilityMiddleware

    exception_secret = "exception-message-private-token"
    body_secret = "request-body-private-token"
    query_secret = "query-private-token"

    async def fail(_request):
        local_secret = "local-variable-private-token"
        assert local_secret
        raise RuntimeError(exception_secret)

    error_app = Starlette(routes=[Route("/boom", fail, methods=["POST"])])
    error_app.add_middleware(RequestObservabilityMiddleware)
    with caplog.at_level(logging.INFO):
        response = TestClient(error_app, raise_server_exceptions=False).post(
            f"/boom?token={query_secret}",
            content=body_secret,
        )

    request_id = response.headers["x-request-id"]
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    error_events = [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "litblogs.errors"
    ]
    request_events = [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "litblogs.requests"
    ]
    assert len(error_events) == 1
    error_event = error_events[0]
    assert set(error_event) == {
        "event",
        "exception_class",
        "request_id",
        "stack",
    }
    assert error_event["event"] == "request_exception"
    assert error_event["exception_class"] == "builtins.RuntimeError"
    assert error_event["request_id"] == request_id
    assert error_event["stack"]
    assert all(set(frame) == {"file", "function", "line"} for frame in error_event["stack"])
    assert all(not Path(frame["file"]).is_absolute() for frame in error_event["stack"])
    assert any(
        event.get("event") == "request_failed"
        and event.get("request_id") == request_id
        and event.get("route") == "unmatched"
        for event in request_events
    )
    relevant_log_text = "\n".join(
        record.message
        for record in caplog.records
        if record.name in {"litblogs.errors", "litblogs.requests"}
    )
    for secret in (
        exception_secret,
        body_secret,
        query_secret,
        "local-variable-private-token",
    ):
        assert secret not in relevant_log_text


def test_production_logging_config_emits_safe_app_events_and_redacts_fallback_exceptions():
    logging_config = ROOT_DIR / "deploy" / "logging.json"
    unit = (ROOT_DIR / "deploy" / "systemd" / "litblogs-web.service").read_text(
        encoding="utf-8"
    )
    assert logging_config.is_file()
    assert (
        "--log-config /opt/litblogs/current/deploy/logging.json" in unit
    )

    smoke = """
import json
import logging
import logging.config
import sys

with open(sys.argv[1], encoding="utf-8") as config_file:
    logging.config.dictConfig(json.load(config_file))
logging.getLogger("litblogs.requests").info('{"event":"request_config_smoke"}')
logging.getLogger("litblogs.errors").error('{"event":"error_config_smoke"}')
logging.getLogger("third.party").warning(
    "student_private_token=%s", "third-party-warning-private-argument"
)
try:
    raise RuntimeError("fallback-exception-private-token")
except RuntimeError:
    logging.getLogger("uvicorn.error").exception(
        "unsafe-fallback-message %s", "fallback-argument-private-token"
    )
try:
    raise RuntimeError("third-party-exception-private-token")
except RuntimeError:
    logging.getLogger("third.party").exception(
        "third-party-private-message %s", "third-party-private-argument"
    )
"""
    completed = subprocess.run(
        [sys.executable, "-c", smoke, str(logging_config)],
        cwd=ROOT_DIR / "litblogs",
        check=False,
        shell=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert '"event":"request_config_smoke"' in completed.stderr
    assert '"event":"error_config_smoke"' in completed.stderr
    assert "server_exception_redacted" in completed.stderr
    assert "fallback-exception-private-token" not in completed.stderr
    assert "fallback-argument-private-token" not in completed.stderr
    assert "third-party-exception-private-token" not in completed.stderr
    assert "third-party-private-message" not in completed.stderr
    assert "third-party-private-argument" not in completed.stderr
    assert "third-party-warning-private-argument" not in completed.stderr
    assert "untrusted_logger_event_redacted" in completed.stderr
