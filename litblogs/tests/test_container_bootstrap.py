"""Container bootstrap behavior; POSIX custody checks run as root in Linux CI."""

import importlib.util
import inspect
import os
import signal
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, unquote, urlsplit

import pytest

CONTAINER_DIR = Path(__file__).resolve().parents[2] / "deploy" / "container"
LINUX_ROOT = os.name == "posix" and os.geteuid() == 0


def load_script(name):
    script = CONTAINER_DIR / f"{name}.py"
    assert script.is_file(), f"Missing container {name} implementation"
    spec = importlib.util.spec_from_file_location(f"container_{name}", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def volumes():
    if not LINUX_ROOT:
        pytest.skip("Real Unix ownership and permissions require a Linux root test container")
    with tempfile.TemporaryDirectory(prefix="litblogs-bootstrap-test-", dir="/run") as temporary:
        parent = Path(temporary)
        roots = tuple(parent / name for name in ("uploads", "postgres-tls", "public-ca"))
        for root in roots:
            root.mkdir(mode=0o755)
        yield roots


def facts(path):
    metadata = path.lstat()
    return metadata.st_uid, metadata.st_gid, stat.S_IMODE(metadata.st_mode)


def test_initializer_is_available_without_importing_web_settings():
    module = load_script("initialize")
    assert callable(module.initialize)


def test_initialization_preserves_tls_and_upload_bytes_on_redeploy(volumes):
    module = load_script("initialize")
    uploads, tls, ca = volumes
    module.initialize(uploads, tls, ca)
    assert facts(uploads) == (10001, 10001, 0o750)
    assert facts(uploads / "objects") == (10001, 10001, 0o700)
    assert facts(uploads / ".incoming") == (10001, 10001, 0o700)
    assert facts(tls / "server.key") == (999, 999, 0o600)
    assert facts(ca / "postgres-root-ca.pem") == (0, 0, 0o644)
    asset = uploads / ".incoming" / ("a" * 32 + ".part")
    asset.write_bytes(b"existing private upload")
    os.chown(asset, 10001, 10001)
    asset.chmod(0o600)
    preserved = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in (
        asset, tls / "server.crt", tls / "server.key", ca / "postgres-root-ca.pem"
    )}
    module.initialize(uploads, tls, ca)
    assert preserved == {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in preserved}
    verification = subprocess.run([
        "openssl", "verify", "-purpose", "sslserver", "-verify_hostname", "postgres.internal",
        "-CAfile", str(ca / "postgres-root-ca.pem"), str(tls / "server.crt"),
    ], capture_output=True, check=False)
    assert verification.returncode == 0


@pytest.mark.parametrize("mutation", ["key_missing", "ca_missing", "key_symlink", "ca_symlink",
                                     "bad_key", "bad_certificate", "wrong_owner", "public_key",
                                     "upload_symlink", "upload_unknown", "unsafe_parent",
                                     "tls_inaccessible", "ca_inaccessible"])
def test_initialized_storage_rejects_tampering_without_repair(volumes, mutation):
    module = load_script("initialize")
    uploads, tls, ca = volumes
    module.initialize(uploads, tls, ca)
    key = tls / "server.key"
    certificate = tls / "server.crt"
    public_ca = ca / "postgres-root-ca.pem"
    if mutation == "key_missing":
        key.unlink()
    elif mutation == "ca_missing":
        public_ca.unlink()
    elif mutation == "key_symlink":
        key.unlink()
        key.symlink_to(certificate)
    elif mutation == "ca_symlink":
        public_ca.unlink()
        public_ca.symlink_to(certificate)
    elif mutation == "bad_key":
        key.write_bytes(b"not a private key")
    elif mutation == "bad_certificate":
        certificate.write_bytes(b"not a certificate")
    elif mutation == "wrong_owner":
        os.chown(uploads, 1234, 1234)
    elif mutation == "public_key":
        key.chmod(0o644)
    elif mutation == "upload_symlink":
        (uploads / "objects" / "escape").symlink_to(ca, target_is_directory=True)
    elif mutation == "upload_unknown":
        (uploads / "unexpected").write_text("unknown data")
    elif mutation == "unsafe_parent":
        uploads.parent.chmod(0o777)
    elif mutation == "tls_inaccessible":
        tls.chmod(0o700)
    elif mutation == "ca_inaccessible":
        ca.chmod(0o700)
    before = certificate.read_bytes()
    with pytest.raises(module.BootstrapError):
        module.initialize(uploads, tls, ca)
    assert certificate.read_bytes() == before


def test_initialization_rejects_nonempty_unknown_volume(volumes):
    module = load_script("initialize")
    (volumes[0] / "unknown-data").write_bytes(b"preserve me")
    with pytest.raises(module.BootstrapError):
        module.initialize(*volumes)
    assert (volumes[0] / "unknown-data").read_bytes() == b"preserve me"


def test_migration_url_encodes_password_and_pins_verified_tls():
    module = load_script("migrate")
    password = "synthetic:@/ ?#%+'\\password"
    url = urlsplit(module.database_url("litblogs_migrator", password))
    assert url.scheme == "postgresql+psycopg2"
    assert unquote(url.password) == password
    assert url.username == "litblogs_migrator"
    assert (url.hostname, url.port, url.path) == ("postgres.internal", 5432, "/litblogs")
    assert parse_qs(url.query) == {
        "sslmode": ["verify-full"], "sslrootcert": ["/etc/litblogs/postgres-root-ca.pem"]
    }


class AdminConnection:
    def __init__(self):
        self.commands = []
        self.closed = False
        self.autocommit = False

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement):
        self.commands.append(statement)

    def fetchone(self):
        return "postgres", "postgres", "litblogs"

    def close(self):
        self.closed = True


@pytest.mark.parametrize("returncode", [0, 1])
def test_migration_separates_secrets_and_revokes_privilege_after_child_exit(returncode):
    module = load_script("migrate")
    connection = AdminConnection()
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "POSTGRES_PASSWORD": "synthetic admin secret",
        "LITBLOGS_MIGRATOR_PASSWORD": "synthetic migrator secret:@/#",
        "LITBLOGS_DB_PASSWORD": "runtime-must-not-reach-migrations",
        "LITBLOGS_ACCOUNT_OPERATOR_PASSWORD": "operator-must-not-reach-migrations",
        "DATABASE_URL": "fixture-runtime-url-must-not-reach-migrations",
        "LITBLOGS_BACKUP_RESTORE_VERIFIED": "true",
    }
    calls = []

    def connect(**parameters):
        assert parameters["user"] == "postgres"
        assert parameters["password"] == environment["POSTGRES_PASSWORD"]
        assert parameters["sslmode"] == "verify-full"
        assert parameters["sslrootcert"] == "/etc/litblogs/postgres-root-ca.pem"
        return connection

    def run(command, **parameters):
        calls.append((command, parameters))
        assert any(statement.startswith("GRANT litblog_identity_owner") for statement in connection.commands)
        return SimpleNamespace(returncode=returncode)

    if returncode:
        with pytest.raises(module.BootstrapError, match="migration failed"):
            module.run_migrations(environment, connect=connect, run=run)
    else:
        module.run_migrations(environment, connect=connect, run=run)
    command, parameters = calls[0]
    assert command[1:] == ["-m", "alembic", "upgrade", "head"]
    assert parameters["cwd"] == "/opt/litblogs/litblogs"
    child_environment = parameters["env"]
    assert set(child_environment) <= {"PATH", "LANG", "LC_ALL", "APP_ENV", "LITBLOGS_MIGRATION_DATABASE_URL"}
    assert unquote(urlsplit(child_environment["LITBLOGS_MIGRATION_DATABASE_URL"]).password) == environment[
        "LITBLOGS_MIGRATOR_PASSWORD"
    ]
    assert parameters["stdout"] == subprocess.DEVNULL
    assert parameters["stderr"] == subprocess.DEVNULL
    assert "REVOKE litblog_identity_owner FROM litblogs_migrator" in connection.commands
    assert connection.closed


def test_migration_revokes_after_launch_exception_and_redacts_failure(capsys, monkeypatch):
    module = load_script("migrate")
    connection = AdminConnection()
    secret = "synthetic-super-secret-should-never-be-printed"
    environment = {"POSTGRES_PASSWORD": secret, "LITBLOGS_MIGRATOR_PASSWORD": secret}

    def failing_run(*_args, **_kwargs):
        raise OSError(secret)

    with pytest.raises(module.BootstrapError) as error:
        module.run_migrations(environment, connect=lambda **_kwargs: connection, run=failing_run)
    assert secret not in str(error.value)
    assert "REVOKE litblog_identity_owner FROM litblogs_migrator" in connection.commands
    monkeypatch.setattr(module, "run_migrations", lambda: (_ for _ in ()).throw(error.value))
    assert module.main() == 1
    output = capsys.readouterr()
    assert secret not in output.out + output.err
    assert "Traceback" not in output.err


@pytest.mark.skipif(os.name != "posix", reason="POSIX container termination signal")
def test_migration_termination_uses_safe_cleanup_path():
    script = CONTAINER_DIR / "migrate.py"
    assert script.is_file()
    program = (
        "import importlib.util, os, signal\n"
        f"spec = importlib.util.spec_from_file_location('migration', {str(script)!r})\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(module)\n"
        "module.run_migrations = lambda: os.kill(os.getpid(), signal.SIGTERM)\n"
        "raise SystemExit(module.main())\n"
    )
    result = subprocess.run([sys.executable, "-c", program], capture_output=True, text=True, check=False)
    assert result.returncode == 1
    assert "interrupted" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.skipif(os.name != "posix", reason="Real POSIX process termination and child cleanup")
def test_sigterm_kills_real_migration_child_before_revoking_membership(tmp_path):
    child_pid_file = tmp_path / "child.pid"
    audit_file = tmp_path / "admin-audit.log"
    script = CONTAINER_DIR / "migrate.py"
    child_program = (
        "import os, time\nfrom pathlib import Path\n"
        f"Path({str(child_pid_file)!r}).write_text(str(os.getpid()))\n"
        "print('private-subprocess-credential', flush=True)\ntime.sleep(120)\n"
    )
    program = (
        "import importlib.util, os, signal, subprocess, sys\n"
        "from pathlib import Path\nfrom types import SimpleNamespace\n"
        f"spec = importlib.util.spec_from_file_location('migration', {str(script)!r})\n"
        "module = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(module)\n"
        + inspect.getsource(AdminConnection)
        + f"\naudit_file = Path({str(audit_file)!r})\nchild_pid_file = Path({str(child_pid_file)!r})\n"
        "class RecordingAdmin(AdminConnection):\n"
        "    def execute(self, statement):\n"
        "        if statement.startswith('REVOKE '):\n"
        "            try:\n"
        "                os.kill(int(child_pid_file.read_text()), 0)\n"
        "            except ProcessLookupError:\n"
        "                with audit_file.open('a') as output:\n"
        "                    output.write('CHILD_STOPPED_BEFORE_REVOKE\\n')\n"
        "            else:\n"
        "                raise RuntimeError('The migration child is still running')\n"
        "        with audit_file.open('a') as output:\n"
        "            output.write(statement + '\\n')\n"
        "        super().execute(statement)\n"
        "    def close(self):\n"
        "        with audit_file.open('a') as output:\n"
        "            output.write('CLOSED\\n')\n"
        "        super().close()\n"
        "connection = RecordingAdmin()\n"
        "sys.modules['psycopg2'] = SimpleNamespace(connect=lambda **kwargs: connection)\n"
        "original_run = subprocess.run\n"
        "def blocking_child(command, **parameters):\n"
        "    assert command[1:] == ['-m', 'alembic', 'upgrade', 'head']\n"
        f"    parameters['cwd'] = {str(tmp_path)!r}\n"
        f"    return original_run([sys.executable, '-c', {child_program!r}], **parameters)\n"
        "module.subprocess.run = blocking_child\n"
        "os.environ.update(POSTGRES_PASSWORD='private-subprocess-credential', "
        "LITBLOGS_MIGRATOR_PASSWORD='private-subprocess-credential')\n"
        "raise SystemExit(module.main())\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", program], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if child_pid_file.exists() and child_pid_file.read_text():
                break
            if process.poll() is not None:
                break
            time.sleep(0.025)
        assert child_pid_file.exists() and child_pid_file.read_text(), "Real migration child did not become ready"
        child_pid = int(child_pid_file.read_text())
        os.kill(process.pid, signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 1
        assert "private-subprocess-credential" not in stdout + stderr
        assert "Traceback" not in stderr
        assert "temporary privileges were revoked" in stderr
        with pytest.raises(ProcessLookupError):
            os.kill(child_pid, 0)
        audit = audit_file.read_text().splitlines()
        assert "REVOKE litblog_identity_owner FROM litblogs_migrator" in audit
        assert audit.index("CHILD_STOPPED_BEFORE_REVOKE") < audit.index(
            "REVOKE litblog_identity_owner FROM litblogs_migrator"
        )
        assert audit[-1] == "CLOSED"
    finally:
        # This unique process group belongs only to this disposable subprocess test.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate(timeout=10)


@pytest.mark.parametrize("failure", ["grant", "revoke"])
def test_database_privilege_failures_redact_driver_error_and_fail_closed(failure, monkeypatch, capsys):
    module = load_script("migrate")
    secret = "private-driver-error-credential"
    connection = AdminConnection()
    executed = connection.execute
    child_started = []

    def execute(statement):
        executed(statement)
        if statement.startswith("GRANT " if failure == "grant" else "REVOKE "):
            raise RuntimeError(secret)

    def run(*_args, **_kwargs):
        child_started.append(True)
        return SimpleNamespace(returncode=0)

    connection.execute = execute
    environment = {"POSTGRES_PASSWORD": secret, "LITBLOGS_MIGRATOR_PASSWORD": secret}
    run_migrations = module.run_migrations
    monkeypatch.setattr(module, "run_migrations", lambda: run_migrations(
        environment, connect=lambda **_kwargs: connection, run=run
    ))
    assert module.main() == 1
    output = capsys.readouterr()
    assert secret not in output.out + output.err
    assert "Traceback" not in output.err
    assert "REVOKE litblog_identity_owner FROM litblogs_migrator" in connection.commands
    assert connection.closed
    if failure == "grant":
        assert not child_started
        assert "migration failed" in output.err
    else:
        assert child_started
        assert "revocation failed" in output.err
        assert "administrator review is required" in output.err
        assert "privileges were revoked" not in output.err


def test_postgres_bootstrap_has_literal_safe_secrets_and_exact_role_contract():
    script = CONTAINER_DIR / "postgres-init.sh"
    assert script.is_file(), "Missing fresh PostgreSQL bootstrap"
    content = script.read_text()
    for role in ("litblogs_migrator", "litblogs_runtime", "litblog_account_operator", "litblog_invitation_operator"):
        assert f"CREATE ROLE {role} LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS" in content
    assert "CREATE ROLE litblog_identity_owner NOLOGIN NOINHERIT NOSUPERUSER" in content
    assert "GRANT pg_read_all_data TO litblogs_backup WITH ADMIN FALSE, INHERIT TRUE, SET TRUE" in content
    assert "ALTER DATABASE litblogs OWNER TO litblogs_migrator" in content
    assert "ALTER SCHEMA public OWNER TO litblogs_migrator" in content
    assert "REVOKE ALL ON DATABASE litblogs FROM PUBLIC" in content
    assert "REVOKE CREATE ON SCHEMA public FROM PUBLIC" in content
    for variable in ("LITBLOGS_DB_PASSWORD", "LITBLOGS_MIGRATOR_PASSWORD", "LITBLOGS_ACCOUNT_OPERATOR_PASSWORD",
                     "LITBLOGS_INVITATION_OPERATOR_PASSWORD", "LITBLOGS_BACKUP_PASSWORD"):
        assert f"\\getenv {variable.lower()} {variable}" in content
        assert f":'{variable.lower()}'" in content
    assert "%L" in content and "\\gexec" in content
    assert "set -x" not in content
    assert "--echo-errors" not in content
