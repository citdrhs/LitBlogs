"""Run one reviewed maintenance job repeatedly in bounded, isolated children."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

JOBS = {"email": ("auth_email_job", 60.0), "reconcile": ("upload_reconciliation_job", 900.0)}
CHILD_TIMEOUT_SECONDS = 300.0
SHUTDOWN_GRACE_SECONDS = 10.0
# /tmp is this container's private tmpfs; publication uses atomic replacement
# from a securely created temporary file, never following a destination symlink.
HEARTBEAT_PATH = Path("/tmp/litblogs-worker-heartbeat")  # nosec B108


def stop_child(child: subprocess.Popen, *, grace_seconds: float = SHUTDOWN_GRACE_SECONDS) -> None:
    """Terminate, then if necessary kill and reap only this supervisor's child."""
    if child.poll() is not None:
        return
    try:
        child.terminate()
    except ProcessLookupError:
        pass
    try:
        child.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        try:
            child.kill()
        except ProcessLookupError:
            pass
        child.wait(timeout=grace_seconds)


def run_child(
    command: list[str],
    stop_event: threading.Event,
    *,
    timeout_seconds: float = CHILD_TIMEOUT_SECONDS,
    grace_seconds: float = SHUTDOWN_GRACE_SECONDS,
) -> int:
    """Inherit runtime.py's sanitized environment without forwarding job output."""
    if stop_event.is_set():
        return 0
    child = subprocess.Popen(
        command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True,
    )
    deadline = time.monotonic() + timeout_seconds
    try:
        while True:
            if stop_event.is_set():
                return 0
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return 1
            try:
                return child.wait(timeout=min(0.25, remaining))
            except subprocess.TimeoutExpired:
                continue
    finally:
        stop_child(child, grace_seconds=grace_seconds)


def write_heartbeat(path: Path) -> None:
    """Publish a completed-run marker atomically within the container's own tmpfs."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="ascii", dir=path.parent, prefix=".litblogs-heartbeat-",
                                         delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(f"{time.time():.6f}\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def run(mode: str, *, stop_event: threading.Event | None = None, heartbeat_path: Path = HEARTBEAT_PATH) -> int:
    if mode not in JOBS:
        print("litblogs-worker: failed", file=sys.stderr, flush=True)
        return 2
    stop = stop_event if stop_event is not None else threading.Event()
    module, interval = JOBS[mode]
    try:
        heartbeat_path.unlink(missing_ok=True)
        while not stop.is_set():
            result = run_child([sys.executable, "-m", module], stop)
            if stop.is_set():
                return 0
            if result != 0:
                print("litblogs-worker: failed", file=sys.stderr, flush=True)
                return 1
            write_heartbeat(heartbeat_path)
            print("litblogs-worker: completed", flush=True)
            stop.wait(interval)
        return 0
    except Exception:
        print("litblogs-worker: failed", file=sys.stderr, flush=True)
        return 1
    finally:
        try:
            heartbeat_path.unlink(missing_ok=True)
        except OSError:
            pass


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 1 or arguments[0] not in JOBS:
        print("litblogs-worker: failed", file=sys.stderr, flush=True)
        return 2
    stop = threading.Event()
    previous_handlers = {}
    try:
        for name in (signal.SIGTERM, signal.SIGINT):
            previous_handlers[name] = signal.signal(name, lambda _signum, _frame: stop.set())
        return run(arguments[0], stop_event=stop)
    except Exception:
        print("litblogs-worker: failed", file=sys.stderr, flush=True)
        return 1
    finally:
        for name, handler in previous_handlers.items():
            signal.signal(name, handler)


if __name__ == "__main__":
    sys.exit(main())
