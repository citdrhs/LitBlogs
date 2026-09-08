"""Disposable Linux CI smoke: build, verify, recreate, and remove only owned state.

Run from the repository root: python deploy/container/smoke.py
Needs Docker Compose and roughly 6 GiB available for the app, PostgreSQL and ClamAV.
This is not a school deployment or evidence of production backup/restore readiness.
"""

import http.client
import json
import os
import re
import secrets
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

HOST = "litblogs-smoke.school.edu"
PROJECT_PATTERN = re.compile(r"litblogs-smoke-[0-9a-f]{12}")
ROOT = Path(__file__).resolve().parents[2]

RUNTIME_PROBE = r'''
import json, os, socket, stat
from pathlib import Path
import psycopg2
assert os.geteuid() == os.getegid() == 10001
root = Path("/var/lib/litblogs/uploads")
metadata = root.lstat()
assert stat.S_ISDIR(metadata.st_mode)
assert (metadata.st_uid, metadata.st_gid, stat.S_IMODE(metadata.st_mode)) == (10001, 10001, 0o750)
for name in ("objects", ".incoming"):
    child = (root / name).lstat()
    assert stat.S_ISDIR(child.st_mode)
    assert (child.st_uid, child.st_gid, stat.S_IMODE(child.st_mode)) == (10001, 10001, 0o700)
ca = Path("/etc/litblogs/postgres-root-ca.pem")
metadata = ca.lstat()
assert stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1
assert (metadata.st_uid, metadata.st_gid, stat.S_IMODE(metadata.st_mode)) == (0, 0, 0o644)
with psycopg2.connect(host="postgres.internal", port=5432, dbname="litblogs", user="litblogs_runtime",
                      password=os.environ["LITBLOGS_DB_PASSWORD"], sslmode="verify-full",
                      sslrootcert=str(ca), connect_timeout=10) as connection:
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_user, session_user, current_database(), ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()")
        assert cursor.fetchone() == ("litblogs_runtime", "litblogs_runtime", "litblogs", True)
        cursor.execute("SELECT rolsuper, rolcreaterole, rolcreatedb, rolreplication, rolbypassrls FROM pg_roles WHERE rolname = current_user")
        assert cursor.fetchone() == (False, False, False, False, False)
with socket.create_connection(("clamav", 3310), timeout=10) as scanner:
    scanner.sendall(b"zPING\0")
    assert scanner.recv(32).rstrip(b"\0\n") == b"PONG"
dist = Path("/opt/litblogs/litblogs/dist")
videos = sorted(path for path in (dist / "assets").glob("*.mp4") if path.is_file() and not path.is_symlink())
assert videos, "Bundled tutorial video is missing"
print(json.dumps({"video": "/" + videos[0].relative_to(dist).as_posix()}))
'''

CREATE_SENTINEL_SQL = """
BEGIN;
CREATE SCHEMA litblogs_container_smoke AUTHORIZATION postgres;
REVOKE ALL ON SCHEMA litblogs_container_smoke FROM PUBLIC;
CREATE TABLE litblogs_container_smoke.persistence (value text NOT NULL);
INSERT INTO litblogs_container_smoke.persistence (value) VALUES (:'sentinel');
COMMIT;
"""
READ_SENTINEL_SQL = "SELECT value FROM litblogs_container_smoke.persistence;"

UPLOAD_SENTINEL_PROBE = r'''
import os, stat, sys
from pathlib import Path
token, operation = sys.argv[1:]
assert len(token) == 32 and all(character in "0123456789abcdef" for character in token)
path = Path("/var/lib/litblogs/uploads/.incoming") / (token + ".part")
expected = ("container-persistence-" + token).encode()
if operation == "create":
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(expected)
        output.flush()
        os.fsync(output.fileno())
metadata = path.lstat()
assert stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1
assert (metadata.st_uid, metadata.st_gid, stat.S_IMODE(metadata.st_mode)) == (10001, 10001, 0o600)
assert path.read_bytes() == expected
print("verified")
'''


class SmokeError(RuntimeError):
    """Only constant, operator-safe messages may cross the CLI boundary."""


@contextmanager
def private_environment(project, port):
    if not PROJECT_PATTERN.fullmatch(project) or not 1024 <= port <= 65535:
        raise SmokeError("Invalid disposable smoke project or port.")
    values = {
        "LITBLOGS_IMAGE_TAG": project,
        "LITBLOGS_HTTP_PORT": str(port),
        "LITBLOGS_ORIGIN": f"https://{HOST}",
        "EMAIL_HOST": "127.0.0.1",  # No SMTP service and no outbound mail in this empty fixture.
        "EMAIL_PORT": "587",
        "EMAIL_FROM": "smoke@school.edu",
        "ALLOWED_EMAIL_DOMAINS": "school.edu",
        "GOOGLE_OAUTH_ENABLED": "false",
        # Synthetic attestations are scoped to brand-new, disposable CI volumes.
        # These values MUST NOT be copied to a production environment or report.
        "UPLOAD_LEGACY_IMPORT_COMPLETE": "true",
        "UPLOAD_BACKUP_RESTORE_VERIFIED": "true",
    }
    values["EMAIL_USERNAME"] = f"smoke-{secrets.token_hex(6)}@school.edu"
    for key in (
        "POSTGRES_PASSWORD", "LITBLOGS_DB_PASSWORD", "LITBLOGS_MIGRATOR_PASSWORD",
        "LITBLOGS_ACCOUNT_OPERATOR_PASSWORD", "LITBLOGS_INVITATION_OPERATOR_PASSWORD",
        "LITBLOGS_BACKUP_PASSWORD", "SECRET_KEY", "TEACHER_INVITE_HMAC_KEY", "EMAIL_PASSWORD",
    ):
        values[key] = secrets.token_urlsafe(48)
        if key.startswith("LITBLOGS_") and key.endswith("PASSWORD"):
            values[key] += ":@/%?#"  # Exercise real libpq URL encoding, not just simple passwords.
    with tempfile.TemporaryDirectory(prefix="litblogs-container-smoke-") as temporary:
        path = Path(temporary) / "environment"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            for key, value in values.items():
                handle.write(f"{key}='{value}'\n")
        if os.name == "posix" and stat.S_IMODE(path.stat().st_mode) != 0o600:
            raise SmokeError("Disposable credential file is not private.")
        yield path


def check_routes(fetch):
    status, headers, body = fetch("/help")
    if status != 200 or "text/html" not in headers.get("content-type", "") or b"<" not in body:
        raise SmokeError("The help route did not return the frontend HTML.")
    if fetch("/api/missing")[0] != 404:
        raise SmokeError("An unknown API route did not remain a 404.")
    status, _headers, body = fetch("/api/runtime-config")
    try:
        config = json.loads(body)
    except (ValueError, TypeError):
        raise SmokeError("Public runtime configuration was not valid JSON.") from None
    if (
        status != 200 or config.get("local_password_registration_enabled") is not True
        or config.get("google_oauth_enabled") is not False
    ):
        raise SmokeError("Public runtime configuration did not preserve password-only signup.")


class SmokeSession:
    def __init__(self, root, project, env_file, port, *, run=None):
        if not PROJECT_PATTERN.fullmatch(project):
            raise SmokeError("Refusing a project outside the disposable smoke namespace.")
        self.root = Path(root).resolve()
        self.project = project
        self.image = f"litblogs-app:{project}"
        self.port = port
        self.claimed = False
        self.run = subprocess.run if run is None else run
        self.prefix = [
            "compose", "--project-name", project, "--env-file", str(env_file),
            "--file", str(self.root / "docker-compose.yml"),
        ]
        # Do not inherit a developer's Compose files, secrets, profiles, or ports.
        self.environment = {key: os.environ[key] for key in ("PATH", "HOME", "DOCKER_CONFIG", "XDG_RUNTIME_DIR")
                            if key in os.environ}

    def docker(self, arguments, *, stage, timeout=180, input_text=None):
        try:
            result = self.run(
                ["docker", *arguments], cwd=self.root, env=self.environment,
                input=input_text, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, check=False, timeout=timeout,
            )
        except Exception:
            raise SmokeError(f"Container smoke command failed during {stage}; diagnostics were suppressed.") from None
        if result.returncode:
            raise SmokeError(f"Container smoke command failed during {stage}; diagnostics were suppressed.")
        return result.stdout.strip()

    def compose(self, arguments, *, stage, timeout=180, input_text=None):
        return self.docker([*self.prefix, *arguments], stage=stage, timeout=timeout, input_text=input_text)

    def claim(self):
        if self.docker(["info", "--format", "{{.OSType}}"], stage="Docker availability") != "linux":
            raise SmokeError("The smoke fixture requires a Linux Docker engine.")
        label = f"label=com.docker.compose.project={self.project}"
        queries = [
            ["container", "ls", "--all", "--quiet", "--filter", label],
            ["volume", "ls", "--quiet", "--filter", label],
            ["network", "ls", "--quiet", "--filter", label],
            ["image", "ls", "--quiet", "--filter", f"reference={self.image}"],
        ]
        for query in queries:
            if self.docker(query, stage="project ownership check"):
                raise SmokeError("The disposable project or image already exists; no cleanup was authorized.")
        self.claimed = True

    def cleanup(self):
        if not self.claimed:
            return
        self.compose(["down", "--volumes", "--remove-orphans", "--timeout", "30"], stage="owned project cleanup", timeout=240)
        if self.docker(["image", "ls", "--quiet", "--filter", f"reference={self.image}"], stage="owned image lookup"):
            self.docker(["image", "rm", self.image], stage="owned image cleanup")
        self.claimed = False

    def http(self, path, *, headers=None):
        if not path.startswith("/") or path.startswith("//"):
            raise SmokeError("Smoke HTTP checks must target the local fixture.")
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            connection.request("GET", path, headers={"Host": HOST, **(headers or {})})
            response = connection.getresponse()
            return response.status, dict((key.lower(), value) for key, value in response.getheaders()), response.read(1048576)
        finally:
            connection.close()

    def wait_ready(self, timeout=600):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                status, _headers, body = self.http("/api/health/ready")
                if status == 200 and json.loads(body).get("status") == "ready":
                    return
            except (OSError, ValueError, http.client.HTTPException):
                pass
            time.sleep(2)
        raise SmokeError("The disposable application did not become ready within the smoke deadline.")

    def runtime_probe(self):
        output = self.compose(["exec", "-T", "app", "python", "-c", RUNTIME_PROBE], stage="runtime TLS and custody probe")
        try:
            video = json.loads(output)["video"]
        except (ValueError, TypeError, KeyError):
            raise SmokeError("The runtime probe returned an unexpected result.") from None
        if not isinstance(video, str) or not re.fullmatch(r"/assets/[A-Za-z0-9_.-]+\.mp4", video):
            raise SmokeError("The bundled tutorial video path was unexpected.")
        status, headers, body = self.http(video, headers={"Range": "bytes=0-15"})
        if status != 206 or len(body) != 16 or not re.fullmatch(r"bytes 0-15/\d+", headers.get("content-range", "")):
            raise SmokeError("The bundled tutorial video did not support a byte-range response.")
        key_facts = self.compose([
            "exec", "-T", "--user", "postgres", "postgres", "stat", "-c", "%u:%g:%a",
            "/var/lib/litblogs/postgres-tls/server.key",
        ], stage="private TLS key custody")
        if key_facts != "999:999:600":
            raise SmokeError("PostgreSQL private-key custody did not match the pinned image identity.")

    def postgres(self, sql, *, sentinel=None):
        command = ["exec", "-T", "--user", "postgres", "postgres", "psql", "--no-psqlrc",
                   "--no-password", "--host=/var/run/postgresql", "--username=postgres", "--dbname=litblogs",
                   "--set=ON_ERROR_STOP=1", "--tuples-only", "--no-align"]
        if sentinel is not None:
            command.append(f"--set=sentinel={sentinel}")  # Synthetic random marker, not a password.
        return self.compose(command, stage="disposable database persistence check", input_text=sql)

    def upload(self, sentinel, operation):
        output = self.compose(["exec", "-T", "app", "python", "-c", UPLOAD_SENTINEL_PROBE, sentinel, operation],
                              stage="disposable upload persistence check")
        if output != "verified":
            raise SmokeError("The private upload sentinel was not verified.")

    def report_status(self):
        # Never print docker logs, inspect environments, or expanded Compose config.
        try:
            output = self.compose(["ps", "--all", "--format", "json"], stage="sanitized service status")
            records = json.loads(output) if output.startswith("[") else [json.loads(line) for line in output.splitlines()]
            for record in records:
                service, state = record.get("Service"), record.get("State")
                if service in {"web", "app", "postgres", "initialize", "migrate", "clamav", "email", "reconcile"} and state in {
                    "running", "exited", "created", "restarting", "dead", "paused", "removing"
                }:
                    print(f"Smoke service {service}: {state}", flush=True)
        except Exception:
            print("Sanitized service status was unavailable.", flush=True)


def run_session(session):
    session.claim()
    try:
        print("Building and starting the disposable container fixture.", flush=True)
        session.compose(["up", "--detach", "--build"], stage="service startup", timeout=2400)
        session.wait_ready()
        check_routes(session.http)
        session.runtime_probe()
        sentinel = secrets.token_hex(16)
        session.postgres(CREATE_SENTINEL_SQL, sentinel=sentinel)
        session.upload(sentinel, "create")
        if session.postgres(READ_SENTINEL_SQL) != sentinel:
            raise SmokeError("The initial database sentinel did not match.")
        print("Recreating PostgreSQL and app behind the gateway to verify persistent state.", flush=True)
        session.compose(["up", "--detach", "--no-deps", "--force-recreate", "postgres", "app"],
                        stage="service recreation", timeout=240)
        session.wait_ready()
        check_routes(session.http)
        session.runtime_probe()
        if session.postgres(READ_SENTINEL_SQL) != sentinel:
            raise SmokeError("Database data did not survive service recreation.")
        session.upload(sentinel, "verify")
    except Exception:
        session.report_status()
        raise
    finally:
        session.cleanup()


def main():
    previous_handlers = {}

    def interrupted(_signum, _frame):
        raise SmokeError("The disposable smoke run was interrupted; owned-resource cleanup was attempted.")

    try:
        if os.name != "posix":
            raise SmokeError("Run this disposable container smoke on a Linux CI host.")
        if Path.cwd().resolve() != ROOT:
            raise SmokeError("Run the container smoke command from the repository root.")
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous_handlers[signum] = signal.signal(signum, interrupted)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        project = f"litblogs-smoke-{secrets.token_hex(6)}"
        with private_environment(project, port) as environment:
            run_session(SmokeSession(ROOT, project, environment, port))
    except SmokeError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception:
        print("Container smoke failed; sensitive diagnostics were suppressed.", file=sys.stderr)
        return 1
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
    print("Disposable container smoke passed: routes, TLS, custody, and recreation persistence; owned resources removed.")
    print("This synthetic fixture does not attest to production deployment or backup/restore readiness.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
