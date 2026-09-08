import importlib.util
import os
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

CONTAINER_DIRECTORY = Path(__file__).resolve().parents[2] / "deploy" / "container"


def load_container_module(name):
    spec = importlib.util.spec_from_file_location(f"container_{name}_test", CONTAINER_DIRECTORY / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_worker_has_only_the_reviewed_bounded_job_modes():
    assert (CONTAINER_DIRECTORY / "worker.py").is_file(), "Container worker is not implemented"
    worker = load_container_module("worker")
    assert worker.JOBS == {"email": ("auth_email_job", 60.0), "reconcile": ("upload_reconciliation_job", 900.0)}
    assert worker.CHILD_TIMEOUT_SECONDS == 300.0
    assert worker.HEARTBEAT_PATH == Path("/tmp/litblogs-worker-heartbeat")


@pytest.fixture
def worker():
    return load_container_module("worker")


@pytest.fixture
def healthcheck():
    return load_container_module("healthcheck")


@pytest.mark.parametrize("arguments", [[], ["unknown-secret"], ["email", "extra-secret"]])
def test_unknown_worker_mode_is_rejected_with_fixed_output(worker, arguments, capsys):
    assert worker.main(arguments) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "litblogs-worker: failed\n"


def test_child_output_is_suppressed_and_failure_is_preserved(worker, capfd):
    code = "import sys; print('private stdout'); print('private stderr', file=sys.stderr); sys.exit(7)"
    assert worker.run_child([sys.executable, "-c", code], threading.Event()) == 7
    assert capfd.readouterr() == ("", "")


def test_child_deadline_terminates_and_reaps_the_owned_process(worker, monkeypatch):
    children = []
    real_popen = subprocess.Popen

    def record_child(*args, **kwargs):
        child = real_popen(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(worker.subprocess, "Popen", record_child)
    started = time.monotonic()
    result = worker.run_child(
        [sys.executable, "-c", "import time; time.sleep(60)"], threading.Event(), timeout_seconds=0.15, grace_seconds=0.2,
    )
    assert result != 0
    assert time.monotonic() - started < 5
    assert len(children) == 1
    assert children[0].poll() is not None


def test_shutdown_terminates_and_reaps_child_promptly(worker, monkeypatch):
    children = []
    real_popen = subprocess.Popen
    stop = threading.Event()

    def record_child(*args, **kwargs):
        child = real_popen(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(worker.subprocess, "Popen", record_child)
    timer = threading.Timer(0.15, stop.set)
    timer.start()
    try:
        assert worker.run_child(
            [sys.executable, "-c", "import time; time.sleep(60)"], stop, grace_seconds=0.2,
        ) == 0
    finally:
        timer.cancel()
        timer.join(timeout=2)
    assert stop.is_set()
    assert len(children) == 1
    assert children[0].poll() is not None


def test_stubborn_child_is_killed_only_after_terminate_grace(worker):
    calls = []

    class StubbornChild:
        def poll(self):
            return None

        def terminate(self):
            calls.append("terminate")

        def wait(self, *, timeout):
            calls.append(("wait", timeout))
            if "kill" not in calls:
                raise subprocess.TimeoutExpired("owned-child", timeout)
            return -9

        def kill(self):
            calls.append("kill")

    worker.stop_child(StubbornChild(), grace_seconds=0.2)
    assert calls == ["terminate", ("wait", 0.2), "kill", ("wait", 0.2)]


@pytest.mark.parametrize("mode,interval", [("email", 60.0), ("reconcile", 900.0)])
def test_successful_worker_writes_heartbeat_and_waits_its_interval(worker, mode, interval, tmp_path, monkeypatch, capsys):
    module_name, _ = worker.JOBS[mode]
    (tmp_path / f"{module_name}.py").write_text("print('private job details')", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    heartbeat = tmp_path / "heartbeat"
    stop = threading.Event()
    waits = []

    def finish_after_success(seconds):
        waits.append(seconds)
        assert heartbeat.is_file()
        assert float(heartbeat.read_text()) > 0
        stop.set()
        return True

    monkeypatch.setattr(stop, "wait", finish_after_success)
    assert worker.run(mode, stop_event=stop, heartbeat_path=heartbeat) == 0
    assert waits == [interval]
    assert not heartbeat.exists()
    captured = capsys.readouterr()
    assert captured.out == "litblogs-worker: completed\n"
    assert captured.err == ""


def test_worker_failure_exits_nonzero_without_heartbeat_or_secret_logs(worker, tmp_path, monkeypatch, capsys):
    (tmp_path / "auth_email_job.py").write_text("raise RuntimeError('secret database URI')", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    heartbeat = tmp_path / "heartbeat"
    heartbeat.write_text("stale", encoding="utf-8")
    assert worker.run("email", heartbeat_path=heartbeat) == 1
    assert not heartbeat.exists()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "litblogs-worker: failed\n"


def test_worker_catches_spawn_errors_without_exposing_details(worker, tmp_path, monkeypatch, capsys):
    def broken_spawn(*args, **kwargs):
        raise OSError("sensitive environment details")

    monkeypatch.setattr(worker.subprocess, "Popen", broken_spawn)
    assert worker.run("email", heartbeat_path=tmp_path / "heartbeat") == 1
    assert capsys.readouterr() == ("", "litblogs-worker: failed\n")


def test_worker_installs_shutdown_handlers_and_restores_them(worker, monkeypatch):
    previous = {name: signal.getsignal(name) for name in (signal.SIGTERM, signal.SIGINT)}

    def request_shutdown(mode, *, stop_event):
        handler = signal.getsignal(signal.SIGTERM)
        assert callable(handler)
        handler(signal.SIGTERM, None)
        assert stop_event.is_set()
        assert mode == "email"
        return 0

    monkeypatch.setattr(worker, "run", request_shutdown)
    assert worker.main(["email"]) == 0
    assert {name: signal.getsignal(name) for name in previous} == previous


def test_heartbeat_is_published_atomically(worker, tmp_path, monkeypatch):
    heartbeat = tmp_path / "heartbeat"
    heartbeat.write_text("old", encoding="utf-8")
    real_replace = os.replace
    replacements = []

    def inspect_replace(source, destination):
        source = Path(source)
        assert source.parent == tmp_path
        assert heartbeat.read_text() == "old"
        assert float(source.read_text()) > 0
        replacements.append(destination)
        real_replace(source, destination)

    monkeypatch.setattr(worker.os, "replace", inspect_replace)
    worker.write_heartbeat(heartbeat)
    assert replacements == [heartbeat]
    assert list(tmp_path.iterdir()) == [heartbeat]


def test_worker_health_rejects_missing_stale_future_or_non_file_heartbeat(healthcheck, tmp_path):
    heartbeat = tmp_path / "heartbeat"
    assert not healthcheck.worker_healthy(heartbeat)
    heartbeat.mkdir()
    assert not healthcheck.worker_healthy(heartbeat)
    heartbeat.rmdir()
    heartbeat.write_text("ok", encoding="utf-8")
    assert healthcheck.worker_healthy(heartbeat)
    now = time.time()
    os.utime(heartbeat, (now - 1501, now - 1501))
    assert not healthcheck.worker_healthy(heartbeat)
    os.utime(heartbeat, (now + 100, now + 100))
    assert not healthcheck.worker_healthy(heartbeat)


@pytest.mark.parametrize(
    "origin,expected",
    [
        ("https://litblogs.school.example", "litblogs.school.example"),
        ("https://litblogs.school.example:8443/", "litblogs.school.example:8443"),
        ("https://[::1]:443", "[::1]:443"),
    ],
)
def test_health_host_is_derived_from_valid_root_https_origin(healthcheck, origin, expected):
    assert healthcheck.origin_host(origin) == expected


@pytest.mark.parametrize(
    "origin",
    [
        "", "http://school.example", "https://user:secret@school.example", "https://school.example/shared",
        "https://school.example?secret=1", "https://school.example#fragment", "https://school.example\r\nSecret: value",
        "https://school.example:99999", "https://bad..example", "https://school.example%0d%0aHost:evil",
    ],
)
def test_health_host_rejects_ambiguous_or_unsafe_origin(healthcheck, origin):
    with pytest.raises(ValueError):
        healthcheck.origin_host(origin)


def test_web_health_uses_loopback_correct_host_and_ignores_proxy_environment(healthcheck, monkeypatch, capsys):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append((self.path, self.headers["Host"]))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(healthcheck, "WEB_PORT", server.server_address[1])
    monkeypatch.setenv("LITBLOGS_ORIGIN", "https://litblogs.school.example")
    monkeypatch.setenv("FRONTEND_URL", "https://fallback.school.example")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:1")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "")
    try:
        assert healthcheck.main(["web"]) == 0
        monkeypatch.delenv("LITBLOGS_ORIGIN")
        assert healthcheck.main(["web"]) == 0
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert requests == [
        ("/api/health/ready", "litblogs.school.example"),
        ("/api/health/ready", "fallback.school.example"),
    ]
    assert capsys.readouterr() == ("", "")


def test_health_cli_failure_is_silent(healthcheck, monkeypatch, capsys):
    monkeypatch.setenv("LITBLOGS_ORIGIN", "https://user:secret@school.example")
    assert healthcheck.main(["web"]) == 1
    assert healthcheck.main(["unknown-secret"]) == 1
    assert healthcheck.main([]) == 1
    assert capsys.readouterr() == ("", "")


def test_unexpected_health_probe_failure_is_also_silent(healthcheck, monkeypatch, capsys):
    def broken_probe():
        raise RuntimeError("sensitive socket or environment details")

    monkeypatch.setattr(healthcheck, "web_healthy", broken_probe)
    assert healthcheck.main(["web"]) == 1
    assert capsys.readouterr() == ("", "")
