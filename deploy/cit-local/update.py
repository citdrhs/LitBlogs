"""Admit passing main revisions and update only the named LitBlogs application.

Run from the root-owned installed copy, through the LitBlogs systemd timer.
PostgreSQL is never recreated or restarted by this program.
"""

import argparse
import json
import os
import re
import stat
import subprocess
import tempfile
import urllib.request
from pathlib import Path

STATE = Path("/home/litblogs/.local/state/cit-deploy")
REPO = Path("/home/litblogs/www/LitBlogs")
PROJECT = "litblogs-cit"
REQUIRED_CHECKS = frozenset(
    {
        "Backend tests",
        "Frontend tests",
        "Frontend lint",
        "Frontend build",
        "Browser release journeys",
        "Secret scan",
        "Dependency audit",
        "SAST",
        "Fresh container startup and persistence",
    }
)
CLEAN_ENV = {
    "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
    "HOME": "/root",
    "LANG": "C.UTF-8",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_PAGER": "cat",
    "DOCKER_HOST": "unix:///var/run/docker.sock",
}


def run(argv, *, timeout=120, capture=True, **kwargs):
    return subprocess.run(
        argv,
        check=True,
        timeout=timeout,
        env=CLEAN_ENV,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        **kwargs,
    )


def git(*args):
    return (
        run(
            [
                "git",
                "-c",
                f"safe.directory={REPO}",
                "-c",
                "core.hooksPath=/dev/null",
                "-C",
                str(REPO),
                *args,
            ],
            # Git metadata belongs to the readable source checkout. Keep the
            # updater's private parent umask unchanged for secrets and records.
            umask=0o022,
        )
        .stdout.decode()
        .strip()
    )


def compose(*args, env_file=None, source=None, timeout=180):
    source = source or REPO
    return run(
        [
            "/usr/bin/docker",
            "compose",
            "--project-name",
            PROJECT,
            "--project-directory",
            str(source),
            "--env-file",
            str(env_file or STATE / ".env"),
            "-f",
            str(source / "docker-compose.yml"),
            "-f",
            str(STATE / "compose.yaml"),
            *args,
        ],
        timeout=timeout,
    )


def read_env(path):
    result = {}
    for line in path.read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Z][A-Z0-9_]*)='([^'\r\n]*)'", line)
        if not match or match[1] in result:
            raise ValueError("Unexpected private environment format")
        result[match[1]] = match[2]
    return result


def write_env(path, values):
    if any("'" in v or "\n" in v or "\r" in v for v in values.values()):
        raise ValueError("Invalid environment value")
    fd, temporary = tempfile.mkstemp(prefix=".env-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write("".join(f"{k}='{v}'\n" for k, v in values.items()))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


def write_record(path, record):
    """Publish a private durable record without leaving a partially written latch."""
    fd, temporary = tempfile.mkstemp(prefix=".update-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="ascii") as handle:
            json.dump(record, handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


def sync_directory(path):
    if os.name == "posix":
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def checks_pass(checks, sha):
    newest = {}
    for item in checks:
        if (
            item.get("head_sha") != sha
            or item.get("app", {}).get("slug") != "github-actions"
        ):
            continue
        name = item.get("name")
        if name not in newest or item.get("id", 0) > newest[name].get("id", 0):
            newest[name] = item
    return all(
        name in newest
        and newest[name].get("status") == "completed"
        and newest[name].get("conclusion") == "success"
        for name in REQUIRED_CHECKS
    )


def fetch_checks(sha):
    if re.fullmatch("[0-9a-f]{40}", sha) is None:
        raise ValueError("Check lookup requires an exact commit")
    request = urllib.request.Request(
        f"https://api.github.com/repos/citdrhs/LitBlogs/commits/{sha}/check-runs?per_page=100",
        headers={
            "User-Agent": "LitBlogs-CIT-updater",
            "Accept": "application/vnd.github+json",
        },
    )
    # Both the HTTPS GitHub origin and the hex-only commit path are fixed above.
    with urllib.request.urlopen(request, timeout=30) as response:  # nosec B310
        return json.load(response)["check_runs"]


def validate_compose(config, *, source=None):
    if config.get("name") != PROJECT:
        raise ValueError("Compose project changed")
    required = {
        "web",
        "app",
        "postgres",
        "clamav",
        "email",
        "reconcile",
        "initialize",
        "migrate",
    }
    permitted = required | {"bootstrap-admin", "invitation", "account"}
    if (
        not required.issubset(config.get("services", {}))
        or set(config["services"]) - permitted
    ):
        raise ValueError("Required services missing")
    if config.get("secrets") or config.get("configs"):
        raise ValueError("Unapproved configuration resource")
    source = source or REPO
    permitted_binds = {
        "web": {
            (STATE.as_posix() + "/haproxy.cfg", "/usr/local/etc/haproxy/haproxy.cfg"),
            (
                STATE.as_posix() + "/https/haproxy.pem",
                "/usr/local/etc/haproxy/haproxy.pem",
            ),
        },
        "postgres": {
            (
                source.as_posix() + "/deploy/container/postgres-init.sh",
                "/docker-entrypoint-initdb.d/10-litblogs.sh",
            ),
            (
                source.as_posix() + "/deploy/container/pg_hba.conf",
                "/etc/postgresql/pg_hba.conf",
            ),
        },
    }
    for name, service in config["services"].items():
        if (
            service.get("privileged")
            or service.get("network_mode") not in (None, "none")
            or any(
                service.get(key)
                for key in (
                    "pid",
                    "ipc",
                    "devices",
                    "device_cgroup_rules",
                    "volumes_from",
                    "container_name",
                    "use_api_socket",
                    "secrets",
                    "configs",
                    "cgroup",
                    "userns_mode",
                    "runtime",
                    "provider",
                )
            )
        ):
            raise ValueError("Host access requested")
        if name != "initialize" and service.get("cap_add"):
            raise ValueError("Additional container privileges requested")
        for volume in service.get("volumes", []):
            if volume.get("type") == "bind":
                if (
                    volume.get("source"),
                    volume.get("target"),
                ) not in permitted_binds.get(name, set()) or volume.get(
                    "read_only"
                ) is not True:
                    raise ValueError("Unapproved host mount")
            elif volume.get("type") != "volume" or volume.get(
                "source"
            ) not in config.get("volumes", {}):
                raise ValueError("Unapproved persistent mount")
        for port in service.get("ports", []):
            if (
                name != "web"
                or port.get("host_ip") != "127.0.0.1"
                or str(port.get("published")) != "18443"
                or port.get("target") != 5443
            ):
                raise ValueError("Unexpected published port")
    for kind in ("volumes", "networks"):
        for key, value in config.get(kind, {}).items():
            if (
                value.get("external")
                or value.get("name") != PROJECT + "_" + key
                or value.get("driver_opts")
                or value.get("driver") not in (None, "local", "bridge")
            ):
                raise ValueError("Shared or external resource requested")
    if not config["services"]["web"]["image"].startswith("haproxy:"):
        raise ValueError("Unexpected gateway")


def infrastructure_compatible(before, after):
    """Keep infrastructure changes out of a no-database-restart update."""
    for key in ("volumes", "networks"):
        if before.get(key) != after.get(key):
            return False
    for name in ("postgres", "clamav", "web"):
        if before["services"][name] != after["services"][name]:
            return False
    return True


def validate_changes(changes):
    """Allow new Alembic revisions; defer changes to historical or infrastructure code."""
    protected = {
        "deploy/container/postgres-init.sh",
        "deploy/container/pg_hba.conf",
        "deploy/container/initialize.py",
        "litblogs/alembic.ini",
        "litblogs/migrations/env.py",
        "litblogs/migrations/sqlite_contract.py",
        "litblogs/migrations/script.py.mako",
    }
    new_revisions = False
    for line in changes:
        fields = line.split("\t")
        if len(fields) != 2 or fields[0] not in {"A", "M", "D"}:
            raise ValueError("Unrecognized source change")
        status, path = fields
        if path in protected:
            raise ValueError(
                "Infrastructure or migration runner changed; operator review required"
            )
        if path.startswith("litblogs/migrations/versions/"):
            if (
                status != "A"
                or re.fullmatch(r"litblogs/migrations/versions/[A-Za-z0-9_]+\.py", path)
                is None
            ):
                raise ValueError(
                    "Historical migration changed; operator review required"
                )
            new_revisions = True
    return new_revisions


def stop_writers():
    compose("stop", "web", "app", "email", "reconcile", timeout=180)


def restart_previous(values, app_count):
    """Recover code-only failures; this helper never runs a schema migration."""
    stop_writers()
    git("switch", "--detach", values["LITBLOGS_IMAGE_TAG"])
    write_env(STATE / ".env", values)
    compose(
        "up",
        "-d",
        "--no-deps",
        "--no-build",
        "--wait",
        "--wait-timeout",
        "360",
        "--scale",
        f"app={app_count}",
        "app",
        "email",
        "reconcile",
        timeout=480,
    )
    compose(
        "up", "-d", "--no-deps", "--no-build", "--wait", "--wait-timeout", "90", "web"
    )
    run(["/usr/bin/python3", str(STATE / "verify.py")], timeout=120)


def deploy_candidate(
    candidate,
    values,
    candidate_env,
    source,
    app_count,
    database_id,
    *,
    has_migrations,
    backup_factory=None,
):
    """Hold a durable latch across backup, migration, activation and verification.

    The caller owns operation.lock. A crash or any maintenance failure requires an
    operator to inspect/remove the latch. Never infer a schema downgrade is safe.
    """
    if not 1 <= app_count <= 3 or not database_id:
        raise ValueError("Current application inventory is invalid")
    if backup_factory is None:
        from backup import create_backup

        backup_factory = create_backup
    latch = STATE / "update-blocked.json"
    record = {
        "previous": values["LITBLOGS_IMAGE_TAG"],
        "candidate": candidate,
        "phase": "backup",
        "migration_attempted": False,
        "previous_apps_recovered": False,
    }
    write_record(latch, record)
    try:
        backup_path = backup_factory(lock_held=True, resume=False)
        print("Consistent encrypted LitBlogs backup created.")
        if has_migrations:
            record.update(phase="migration", migration_attempted=True)
            write_record(latch, record)
            compose(
                "run",
                "--rm",
                "--no-deps",
                "migrate",
                source=source,
                env_file=candidate_env,
                timeout=1900,
            )
        record["phase"] = "activation"
        write_record(latch, record)
        git("switch", "--detach", candidate)
        write_env(STATE / ".env", {**values, "LITBLOGS_IMAGE_TAG": candidate})
        compose(
            "up",
            "-d",
            "--no-deps",
            "--no-build",
            "--wait",
            "--wait-timeout",
            "360",
            "--scale",
            f"app={app_count}",
            "app",
            "email",
            "reconcile",
            timeout=480,
        )
        compose(
            "up",
            "-d",
            "--no-deps",
            "--no-build",
            "--wait",
            "--wait-timeout",
            "90",
            "web",
        )
        run(["/usr/bin/python3", str(STATE / "verify.py")], timeout=120)
        if compose("ps", "-q", "postgres").stdout.decode().strip() != database_id:
            raise ValueError("Unexpected database container replacement")
        write_record(
            STATE / "last-update.json",
            {
                "commit": candidate,
                "previous": values["LITBLOGS_IMAGE_TAG"],
                "backup": str(backup_path),
                "database_container_preserved": True,
                "migration_applied": has_migrations,
            },
        )
        latch.unlink()
        sync_directory(STATE)
        print(
            f"LitBlogs updated to {candidate}; persistent database and uploads preserved."
        )
        return backup_path
    except Exception:
        try:
            if record["migration_attempted"]:
                stop_writers()
            else:
                restart_previous(values, app_count)
                record["previous_apps_recovered"] = True
        except Exception:  # noqa: BLE001 - retain the latch even if recovery fails
            record["previous_apps_recovered"] = False
        record["phase"] = "operator-review-required"
        write_record(latch, record)
        print(
            "Update stopped; automatic retries are blocked. Database and uploads preserved; operator review is required."
        )
        raise
    finally:
        candidate_env.unlink(missing_ok=True)


def main():
    import fcntl

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    if os.geteuid() != 0:
        parser.error("Use the installed LitBlogs service")
    for path, directory, modes in (
        (STATE, True, {0o700}),
        (STATE / ".env", False, {0o600}),
        (STATE / "compose.yaml", False, {0o600, 0o644}),
    ):
        metadata = path.lstat()
        expected_type = stat.S_ISDIR if directory else stat.S_ISREG
        if (
            not expected_type(metadata.st_mode)
            or metadata.st_uid != 0
            or metadata.st_gid != 0
            or stat.S_IMODE(metadata.st_mode) not in modes
            or path.resolve() != path
        ):
            raise ValueError("Deployment file custody is invalid")
    descriptor = os.open(
        STATE / "operation.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
    )
    with os.fdopen(descriptor, "a") as lock:
        metadata = os.fstat(lock.fileno())
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != 0
            or metadata.st_gid != 0
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != 0o600
        ):
            raise ValueError("Deployment lock custody is invalid")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Another LitBlogs operation is running; deferred.")
            return 0
        if (STATE / "update-blocked.json").exists():
            print(
                "Automatic updates are blocked pending operator review of the last maintenance operation."
            )
            return 1
        values = read_env(STATE / ".env")
        previous = values["LITBLOGS_IMAGE_TAG"]
        if (
            not re.fullmatch("[0-9a-f]{40}", previous)
            or git("status", "--porcelain=v1")
            or git("rev-parse", "HEAD") != previous
        ):
            raise ValueError("Deployment source must be clean and pinned")
        if git("remote", "get-url", "origin") not in {
            "https://github.com/citdrhs/LitBlogs",
            "https://github.com/citdrhs/LitBlogs.git",
        }:
            raise ValueError("Deployment upstream is unexpected")
        git("fetch", "--quiet", "origin", "main")
        candidate = git("rev-parse", "refs/remotes/origin/main")
        if not re.fullmatch("[0-9a-f]{40}", candidate):
            raise ValueError("Candidate revision is invalid")
        if candidate == previous:
            print("LitBlogs is already at the latest deployed main revision.")
            return 0
        git("merge-base", "--is-ancestor", previous, candidate)
        if not checks_pass(fetch_checks(candidate), candidate):
            print(
                "Candidate main revision is waiting for all required checks; current service preserved."
            )
            return 0
        if args.check_only:
            print(
                "A passing main revision is available; check-only mode made no deployment changes."
            )
            return 0
        changed = git(
            "diff", "--no-renames", "--name-status", previous, candidate
        ).splitlines()
        has_migrations = validate_changes(changed)
        before = json.loads(compose("config", "--format", "json").stdout)
        validate_compose(before)
        candidate_values = {**values, "LITBLOGS_IMAGE_TAG": candidate}
        candidate_env = STATE / ".candidate.env"
        write_env(candidate_env, candidate_values)
        releases = STATE / "releases"
        releases.mkdir(exist_ok=True)
        if releases.is_symlink() or releases.resolve() != releases:
            raise ValueError("Candidate release directory is invalid")
        source = releases / candidate
        if not source.exists():
            git("worktree", "add", "--detach", str(source), candidate)
        if source.is_symlink() or source.resolve() != source:
            raise ValueError("Candidate source path is invalid")
        candidate_git = ["git", "-c", "core.hooksPath=/dev/null", "-C", str(source)]
        if (
            run([*candidate_git, "rev-parse", "HEAD"], umask=0o022).stdout.decode().strip()
            != candidate
            or run([*candidate_git, "status", "--porcelain=v1"], umask=0o022).stdout.strip()
        ):
            raise ValueError("Candidate worktree must be clean and pinned")
        after = json.loads(
            compose(
                "config", "--format", "json", source=source, env_file=candidate_env
            ).stdout
        )
        validate_compose(after, source=source)
        # Bind-source paths differ because the candidate is built in an isolated checkout.
        for name in ("postgres", "clamav", "web"):
            for volume in after["services"][name].get("volumes", []):
                if volume.get("type") == "bind" and volume.get("source", "").startswith(
                    str(source) + "/"
                ):
                    volume["source"] = str(REPO) + volume["source"][len(str(source)) :]
        if not infrastructure_compatible(before, after):
            raise ValueError(
                "Infrastructure settings changed; automatic app update deferred"
            )
        (STATE / "logs").mkdir(exist_ok=True)
        with (STATE / "logs" / f"build-{candidate}.log").open("wb") as log:
            subprocess.run(
                [
                    "/usr/bin/docker",
                    "build",
                    "-t",
                    f"litblogs-app:{candidate}",
                    str(source),
                ],
                check=True,
                timeout=3600,
                env=CLEAN_ENV,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        running = (
            compose("ps", "--status", "running", "--services")
            .stdout.decode()
            .splitlines()
        )
        if not {"web", "app", "postgres", "clamav", "email", "reconcile"}.issubset(
            running
        ):
            raise ValueError("Current deployment is not fully running")
        run(["/usr/bin/python3", str(STATE / "verify.py")], timeout=120)
        app_count = len(compose("ps", "-q", "app").stdout.decode().splitlines())
        database_id = compose("ps", "-q", "postgres").stdout.decode().strip()
        deploy_candidate(
            candidate,
            values,
            candidate_env,
            source,
            app_count,
            database_id,
            has_migrations=has_migrations,
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:  # noqa: BLE001 - never emit secret-bearing subprocess diagnostics
        print(
            f"LitBlogs update stopped safely ({type(error).__name__}); inspect private deployment state."
        )
        raise SystemExit(1) from None
