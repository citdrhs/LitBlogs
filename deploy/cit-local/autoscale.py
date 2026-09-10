#!/usr/bin/env python3
"""One bounded, root-operated CPU sample for the dedicated LitBlogs CIT stack.

The systemd timer supplies the schedule. All deployment/backup operations must
use the same operation.lock. No Docker socket is exposed to an app container.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import stat
import subprocess
import tempfile
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from pathlib import Path

PROJECT = "litblogs-cit"
REPO = Path("/home/litblogs/www/LitBlogs")
STATE_DIR = Path("/home/litblogs/.local/state/cit-deploy")
ENV_FILE = STATE_DIR / ".env"
OVERLAY = STATE_DIR / "compose.yaml"
STATE_FILE = STATE_DIR / "autoscale-state.json"
LOCK_FILE = STATE_DIR / "operation.lock"
DOCKER = "/usr/bin/docker"
MIN_REPLICAS, MAX_REPLICAS = 1, 3
MIN_AVAILABLE_MEMORY = 2 * 1024**3
COOLDOWN_SECONDS = 300
MIN_SAMPLE_SECONDS, MAX_SAMPLE_GAP_SECONDS = 45, 180
COMMAND_TIMEOUT_SECONDS, SCALE_TIMEOUT_SECONDS = 20, 120
ID_PATTERN = re.compile(r"[0-9a-f]{64}")
INSPECT_FORMAT = (
    '{"Id":{{json .Id}},"Labels":{{json .Config.Labels}},'
    '"State":{{json .State.Status}},"Health":'
    "{{if .State.Health}}{{json .State.Health.Status}}{{else}}null{{end}},"
    '"Image":{{json .Config.Image}},"NanoCpus":{{json .HostConfig.NanoCpus}}}'
)


class AutoscaleError(RuntimeError):
    """Only fixed, non-sensitive diagnostics may cross the command boundary."""


@dataclass(frozen=True)
class State:
    high: int = 0
    low: int = 0
    last_sample: float = 0
    last_scale: float = 0
    replicas: int = 0


def decide(state, *, count, cpu, available_memory, healthy, now):
    """Return the next sample state and an optional one-replica adjustment."""
    if (
        type(count) is not int
        or not MIN_REPLICAS <= count <= MAX_REPLICAS
        or not math.isfinite(cpu)
        or not 0 <= cpu <= 1000
        or not math.isfinite(now)
        or now <= 0
        or available_memory < 0
    ):
        raise AutoscaleError("Invalid scaling sample")
    reset = replace(state, high=0, low=0, last_sample=now, replicas=count)
    if (
        not healthy
        or available_memory < MIN_AVAILABLE_MEMORY
        or now < state.last_sample
    ):
        return reset, None
    if state.last_sample and now - state.last_sample < MIN_SAMPLE_SECONDS:
        return state, None
    if state.replicas != count or now - state.last_sample > MAX_SAMPLE_GAP_SECONDS:
        state = reset
    high = min(state.high + 1, 2) if cpu >= 65 else 0
    low = min(state.low + 1, 5) if cpu < 20 else 0
    next_state = replace(state, high=high, low=low, last_sample=now, replicas=count)
    if now - state.last_scale < COOLDOWN_SECONDS:
        return next_state, None
    if high >= 2 and count < MAX_REPLICAS:
        return next_state, count + 1
    if low >= 5 and count > MIN_REPLICAS:
        return next_state, count - 1
    return next_state, None


def run_command(command, *, timeout=COMMAND_TIMEOUT_SECONDS):
    """Never use a shell, inherited Docker target, Compose override, or secret log."""
    try:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            env={
                "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                "HOME": "/root",
                "LANG": "C.UTF-8",
                "DOCKER_HOST": "unix:///var/run/docker.sock",
            },
        )
    except (OSError, subprocess.SubprocessError, UnicodeError):
        raise AutoscaleError("Docker operation failed") from None
    if result.returncode or len(result.stdout) > 131072:
        raise AutoscaleError("Docker operation failed")
    return result.stdout


def read_image_tag(path=ENV_FILE):
    """Accept only the explicitly deployed full commit, without interpreting .env."""
    try:
        matches = []
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("LITBLOGS_IMAGE_TAG="):
                value = line.strip().split("=", 1)[1]
                match = re.fullmatch(r"(?:'([0-9a-f]{40})'|([0-9a-f]{40}))", value)
                if match is None:
                    raise ValueError
                matches.append(match.group(1) or match.group(2))
        if len(matches) != 1:
            raise ValueError
        return matches[0]
    except (OSError, UnicodeError, ValueError):
        raise AutoscaleError("Deployment image setting is invalid") from None


def validate_container(record, identifier, image_tag):
    try:
        labels = record["Labels"]
        if (
            record["Id"] != identifier
            or labels.get("com.docker.compose.project") != PROJECT
            or labels.get("com.docker.compose.service") != "app"
            or labels.get("com.docker.compose.oneoff", "").lower() != "false"
            or record["Image"] != f"litblogs-app:{image_tag}"
            or record["NanoCpus"] != 1_000_000_000
        ):
            raise ValueError
        return record["State"] == "running" and record["Health"] == "healthy"
    except (KeyError, TypeError, AttributeError, ValueError):
        raise AutoscaleError("App container boundary is invalid") from None


def parse_cpu(output, identifiers):
    try:
        readings = {}
        for line in output.splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            identifier = record["ID"]
            if identifier not in identifiers or identifier in readings:
                raise ValueError
            percentage = record["CPUPerc"]
            if (
                not isinstance(percentage, str)
                or re.fullmatch(r"[0-9]+(?:\.[0-9]+)?%", percentage) is None
            ):
                raise ValueError
            readings[identifier] = float(percentage[:-1])
            if (
                not math.isfinite(readings[identifier])
                or not 0 <= readings[identifier] <= 1000
            ):
                raise ValueError
        if not identifiers or set(readings) != set(identifiers):
            raise ValueError
        return sum(readings.values()) / len(readings)
    except (KeyError, TypeError, ValueError):
        raise AutoscaleError("App CPU sample is invalid") from None


def available_memory(path=Path("/proc/meminfo")):
    try:
        matches = re.findall(
            r"^MemAvailable:\s+([0-9]+) kB$",
            path.read_text(encoding="ascii"),
            re.MULTILINE,
        )
        if len(matches) != 1:
            raise ValueError
        return int(matches[0]) * 1024
    except (OSError, UnicodeError, ValueError):
        raise AutoscaleError("Host memory sample is unavailable") from None


def read_sample():
    image_tag = read_image_tag()
    output = run_command(
        [
            DOCKER,
            "ps",
            "--all",
            "--no-trunc",
            "--filter",
            f"label=com.docker.compose.project={PROJECT}",
            "--filter",
            "label=com.docker.compose.service=app",
            "--format",
            "{{.ID}}",
        ]
    )
    identifiers = output.splitlines()
    if (
        not MIN_REPLICAS <= len(identifiers) <= MAX_REPLICAS
        or len(set(identifiers)) != len(identifiers)
        or any(ID_PATTERN.fullmatch(identifier) is None for identifier in identifiers)
    ):
        raise AutoscaleError("App inventory is invalid")
    healthy = True
    for identifier in identifiers:
        try:
            record = json.loads(
                run_command([DOCKER, "inspect", "--format", INSPECT_FORMAT, identifier])
            )
        except ValueError:
            raise AutoscaleError("App inspection is invalid") from None
        healthy = validate_container(record, identifier, image_tag) and healthy
    memory = available_memory()
    if not healthy or memory < MIN_AVAILABLE_MEMORY:
        return len(identifiers), 0.0, memory, healthy
    # Stats cannot filter labels: pass only IDs already verified above. The exact
    # full-ID JSON inventory is checked again, so a stale or partial sample fails.
    output = run_command(
        [
            DOCKER,
            "stats",
            "--no-stream",
            "--no-trunc",
            "--format",
            "{{json .}}",
            *identifiers,
        ]
    )
    return len(identifiers), parse_cpu(output, identifiers), memory, healthy


def scale_command(target):
    if type(target) is not int or not MIN_REPLICAS <= target <= MAX_REPLICAS:
        raise AutoscaleError("Invalid replica target")
    return [
        DOCKER,
        "compose",
        "--project-name",
        PROJECT,
        "--project-directory",
        str(REPO),
        "--env-file",
        str(ENV_FILE),
        "-f",
        str(REPO / "docker-compose.yml"),
        "-f",
        str(OVERLAY),
        "up",
        "-d",
        "--no-deps",
        "--no-build",
        "--scale",
        f"app={target}",
        "app",
    ]


def scale(target):
    count, _cpu, memory, healthy = read_sample()
    if not healthy or memory < MIN_AVAILABLE_MEMORY or abs(target - count) != 1:
        raise AutoscaleError("Scaling conditions changed; no action taken")
    run_command(scale_command(target), timeout=SCALE_TIMEOUT_SECONDS)


def load_state(path=STATE_FILE):
    try:
        if not path.exists():
            return State()
        if path.is_symlink() or path.stat().st_size > 4096:
            raise ValueError
        values = json.loads(path.read_text(encoding="ascii"))
        if not isinstance(values, dict) or set(values) != set(asdict(State())):
            raise ValueError
        state = State(**values)
        for value, maximum in (
            (state.high, 2),
            (state.low, 5),
            (state.replicas, MAX_REPLICAS),
        ):
            if type(value) is not int or not 0 <= value <= maximum:
                raise ValueError
        for value in (state.last_sample, state.last_scale):
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError
        return state
    except (OSError, UnicodeError, TypeError, ValueError):
        raise AutoscaleError("Autoscale state is invalid") from None


def save_state(state, path=STATE_FILE):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="ascii",
            dir=path.parent,
            prefix=".autoscale-",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            if os.name == "posix":
                os.fchmod(handle.fileno(), 0o600)
            json.dump(asdict(state), handle, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if os.name == "posix":
            descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    except (OSError, TypeError, ValueError):
        raise AutoscaleError("Autoscale state could not be saved") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def run_once(*, dry_run=False, now=None):
    now = time.time() if now is None else now
    state = load_state()
    try:
        count, cpu, memory, healthy = read_sample()
        next_state, target = decide(
            state,
            count=count,
            cpu=cpu,
            available_memory=memory,
            healthy=healthy,
            now=now,
        )
    except AutoscaleError:
        if not dry_run:
            save_state(replace(state, high=0, low=0, last_sample=now))
        raise
    if target is None:
        if not dry_run:
            save_state(next_state)
        return "held"
    direction = "up" if target > count else "down"
    if dry_run:
        return f"would-scale-{direction}"
    # Reserve cooldown durably BEFORE mutation: a timeout can follow a successful
    # Docker change. A subsequent run must not immediately repeat that action.
    save_state(replace(next_state, high=0, low=0, last_scale=now))
    scale(target)
    return f"scaled-{direction}"


def validate_paths():
    if os.name != "posix" or os.geteuid() != 0:
        raise AutoscaleError("Autoscaler requires its root service context")
    for path, directory, modes in (
        (STATE_DIR, True, {0o700}),
        (ENV_FILE, False, {0o600}),
        (OVERLAY, False, {0o600, 0o644}),
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
            raise AutoscaleError("Deployment file custody is invalid")


@contextmanager
def operation_lock():
    # Imported lazily so the pure decision tests also run on Windows.
    import fcntl

    descriptor = os.open(LOCK_FILE, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != 0
            or metadata.st_gid != 0
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != 0o600
        ):
            raise AutoscaleError("Deployment lock custody is invalid")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--once",
        action="store_true",
        required=True,
        help="Take one sample; the systemd timer owns scheduling",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Read and report without scaling or saving counters",
    )
    arguments = parser.parse_args(argv)
    try:
        validate_paths()
        with operation_lock() as acquired:
            action = run_once(dry_run=arguments.dry_run) if acquired else "busy"
        print(f"litblogs-autoscale: {action}", flush=True)
        return 0
    except Exception:  # noqa: BLE001 - suppress all secret-bearing CLI diagnostics
        print("litblogs-autoscale: failed", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
