"""Operate only on validated, existing CIT containers, never Compose dependencies."""

import json
import re
import subprocess
import time

PROJECT = "litblogs-cit"
DOCKER = ["/usr/bin/docker", "--host", "unix:///var/run/docker.sock"]
SERVICES = ("postgres", "clamav", "app", "email", "reconcile", "web")
WRITERS = ("web", "app", "email", "reconcile")
OPERATORS = ("initialize", "migrate", "bootstrap-admin", "invitation", "account")
ACTIVE = {"running", "restarting", "paused"}
IDENTITY = ("Id", "Image", "Project", "Service", "Oneoff")
PROJECTION = (
    '{"Id":{{json .Id}},"Image":{{json .Image}},'
    '"Project":{{json (index .Config.Labels "com.docker.compose.project")}},'
    '"Service":{{json (index .Config.Labels "com.docker.compose.service")}},'
    '"Oneoff":{{json (index .Config.Labels "com.docker.compose.oneoff")}},'
    '"State":{{json .State.Status}},"StartedAt":{{json .State.StartedAt}},'
    '"Health":{{with (index .State "Health")}}{{json .Status}}{{else}}null{{end}}}'
)


class LifecycleError(RuntimeError):
    """Fixed diagnostics only; Docker output may contain private information."""


def run(arguments, *, timeout=120):
    try:
        result = subprocess.run(
            [*DOCKER, *arguments], check=False, timeout=timeout,
            stdin=subprocess.DEVNULL, capture_output=True,
            env={"PATH": "/usr/bin:/bin", "HOME": "/root", "LANG": "C.UTF-8"},
        )
        if result.returncode or len(result.stdout) > 131072:
            raise LifecycleError("Existing-container operation failed.")
        return result.stdout
    except (OSError, subprocess.SubprocessError):
        raise LifecycleError("Existing-container operation could not complete.") from None


def validate_inventory(records):
    counts = dict.fromkeys(SERVICES, 0)
    if not isinstance(records, dict) or not 6 <= len(records) <= 32:
        raise LifecycleError("The container inventory has an unexpected size.")
    for identifier, row in records.items():
        if not isinstance(row, dict):
            raise LifecycleError("The container inventory is invalid.")
        service = row.get("Service")
        if (not isinstance(identifier, str) or not re.fullmatch(r"[0-9a-f]{64}", identifier)
                or row.get("Id") != identifier or row.get("Project") != PROJECT
                or service not in (*SERVICES, *OPERATORS)
                or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(row.get("Image", "")))
                or str(row.get("Oneoff", "")).lower() not in {"true", "false"}
                or row.get("State") not in {"created", "running", "exited", "paused", "restarting", "dead", "removing"}
                or not isinstance(row.get("StartedAt"), str)):
            raise LifecycleError("A container identity is outside the fixed deployment.")
        if service in counts:
            if str(row["Oneoff"]).lower() != "false":
                raise LifecycleError("A one-off container cannot represent a service.")
            counts[service] += 1
    if not 1 <= counts["app"] <= 3 or any(counts[name] != 1 for name in SERVICES if name != "app"):
        raise LifecycleError("The existing service counts are invalid.")


def capture(*, timeout=20):
    """Return a secret-free projection of this project's existing containers."""
    try:
        identifiers = run(["container", "ls", "--all", "--no-trunc", "--filter",
                           f"label=com.docker.compose.project={PROJECT}", "--format", "{{.ID}}"], timeout=timeout / 2).decode().splitlines()
        if (not 6 <= len(identifiers) <= 32 or len(set(identifiers)) != len(identifiers)
                or any(re.fullmatch(r"[0-9a-f]{64}", value) is None for value in identifiers)):
            raise LifecycleError("The container identifiers are invalid.")
        rows = [json.loads(line) for line in run(
            ["container", "inspect", "--format", PROJECTION, *identifiers], timeout=timeout / 2,
        ).decode().splitlines()]
        if len(rows) != len(identifiers) or any(not isinstance(row, dict) for row in rows):
            raise LifecycleError("The container inspection is incomplete.")
        records = {row.get("Id"): row for row in rows}
        if set(records) != set(identifiers):
            raise LifecycleError("The inspected containers do not match the inventory.")
        validate_inventory(records)
        return records
    except (UnicodeError, ValueError, TypeError):
        raise LifecycleError("The container inventory could not be decoded.") from None


def revalidate(original, *, timeout=20):
    validate_inventory(original)
    current = capture(timeout=timeout)
    if set(original) != set(current) or any(
        any(original[key][field] != current[key][field] for field in IDENTITY) for key in original
    ):
        raise LifecycleError("The existing containers changed during the operation.")
    return current


def assert_operators_idle(records):
    if any(row["Service"] in OPERATORS and row["State"] not in {"created", "exited"} for row in records.values()):
        raise LifecycleError("An active database operator prevents this operation.")


def selected_ids(records, services, *, running_only=False):
    return [key for key, row in records.items()
            if row["Service"] in services and (not running_only or row["State"] == "running")]


def validate_targets(original, identifiers):
    if len(set(identifiers)) != len(identifiers) or any(
        key not in original or original[key]["Service"] not in SERVICES for key in identifiers
    ):
        raise LifecycleError("An unapproved container mutation was requested.")


def remaining(deadline, maximum):
    duration = deadline - time.monotonic()
    if duration <= 0:
        raise LifecycleError("The existing-container operation deadline expired.")
    return min(maximum, duration)


def wait_healthy(original, identifiers, deadline):
    while time.monotonic() < deadline:
        current = revalidate(original, timeout=remaining(deadline, 20))
        assert_operators_idle(current)
        if all(current[key]["State"] == "running" and current[key]["Health"] == "healthy" for key in identifiers):
            return
        time.sleep(min(2, max(0, deadline - time.monotonic())))
    raise LifecycleError("Existing containers did not become healthy before the deadline.")


def start_existing(original, identifiers, *, timeout=900):
    """Preserve container identity and order startup without starting dependencies."""
    validate_targets(original, identifiers)
    deadline = time.monotonic() + timeout
    for services in (("postgres", "clamav"), ("app", "email", "reconcile"), ("web",)):
        group = [key for key in identifiers if original[key]["Service"] in services]
        if not group:
            continue
        current = revalidate(original, timeout=remaining(deadline, 20))
        assert_operators_idle(current)
        if any(current[key]["State"] not in {"running", "exited", "created"} for key in group):
            raise LifecycleError("A container cannot safely be started in its current state.")
        stopped = [key for key in group if current[key]["State"] != "running"]
        if time.monotonic() >= deadline:
            raise LifecycleError("The existing-container startup deadline expired.")
        if stopped:
            run(["container", "start", *stopped], timeout=remaining(deadline, 120))
        wait_healthy(original, group, deadline)
    if identifiers:
        wait_healthy(original, identifiers, deadline)


def stop_existing(original, identifiers, *, timeout=150):
    """Finish writer shutdown before stopping any explicitly selected infrastructure."""
    validate_targets(original, identifiers)
    deadline = time.monotonic() + timeout
    for services in (WRITERS, ("clamav", "postgres")):
        group = [key for key in identifiers if original[key]["Service"] in services]
        if not group:
            continue
        current = revalidate(original, timeout=remaining(deadline, 20))
        assert_operators_idle(current)
        if any(current[key]["State"] not in {"running", "exited", "created"} for key in group):
            raise LifecycleError("A container cannot safely be stopped in its current state.")
        running = [key for key in group if current[key]["State"] == "running"]
        if running:
            run(["container", "stop", "--time", "60", *running], timeout=remaining(deadline, 70))
        current = revalidate(original, timeout=remaining(deadline, 20))
        if any(current[key]["State"] in ACTIVE for key in group):
            raise LifecycleError("Selected containers did not stop.")


def assert_quiesced(original):
    current = revalidate(original)
    assert_operators_idle(current)
    if any(row["Service"] in WRITERS and row["State"] in ACTIVE for row in current.values()):
        raise LifecycleError("Database and upload writers did not stop.")
    assert_database_preserved(original, current)


def assert_database_preserved(original, current=None):
    current = revalidate(original) if current is None else current
    for key in selected_ids(original, ("postgres",)):
        if (current[key]["State"] != "running" or current[key]["Health"] != "healthy"
                or current[key]["StartedAt"] != original[key]["StartedAt"]):
            raise LifecycleError("PostgreSQL did not remain healthy and running.")
