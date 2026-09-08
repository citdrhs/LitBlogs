from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace


def test_auth_email_job_uses_one_shared_runtime_and_alternates_single_deliveries(
    monkeypatch,
):
    import auth_email_delivery
    import auth_email_job
    import email_verification_delivery
    import password_reset_delivery

    calls = []
    settings = SimpleNamespace(password_reset_claim_timeout_seconds=120)
    engine = SimpleNamespace(dispose=lambda: calls.append("dispose"))
    session_factory = object()
    email_settings = object()
    monkeypatch.setattr(
        auth_email_delivery,
        "load_auth_email_worker_settings",
        lambda: calls.append("load") or settings,
    )
    monkeypatch.setattr(
        auth_email_delivery,
        "create_auth_email_engine",
        lambda received: calls.append(("engine", received)) or engine,
    )
    monkeypatch.setattr(
        auth_email_delivery,
        "check_auth_email_database_readiness",
        lambda received: calls.append(("ready", received)),
    )
    monkeypatch.setattr(
        auth_email_delivery,
        "create_auth_email_session_factory",
        lambda received: calls.append(("sessions", received)) or session_factory,
    )
    monkeypatch.setattr(
        auth_email_delivery,
        "auth_email_settings_from_worker",
        lambda received: calls.append(("smtp", received)) or email_settings,
    )
    reset_outcomes = iter(
        (
            auth_email_delivery.AuthEmailDispatchOutcome.COMPLETED,
            auth_email_delivery.AuthEmailDispatchOutcome.EMPTY_QUEUE,
        )
    )
    verification_outcomes = iter(
        (
            auth_email_delivery.AuthEmailDispatchOutcome.COMPLETED,
            auth_email_delivery.AuthEmailDispatchOutcome.EMPTY_QUEUE,
        )
    )

    def dispatch_reset(**kwargs):
        calls.append(("reset", kwargs))
        return next(reset_outcomes)

    def dispatch_verification(**kwargs):
        calls.append(("verification", kwargs))
        return next(verification_outcomes)

    monkeypatch.setattr(
        password_reset_delivery,
        "dispatch_password_reset_batch_once",
        dispatch_reset,
    )
    monkeypatch.setattr(
        email_verification_delivery,
        "dispatch_email_verification_batch_once",
        dispatch_verification,
    )

    assert auth_email_job.run() == 0

    assert [call[0] if isinstance(call, tuple) else call for call in calls] == [
        "load",
        "engine",
        "ready",
        "sessions",
        "smtp",
        "verification",
        "reset",
        "verification",
        "reset",
        "dispose",
    ]
    dispatch_kwargs = [
        call[1]
        for call in calls
        if isinstance(call, tuple)
        and call[0] in {"reset", "verification"}
    ]
    for kwargs in dispatch_kwargs:
        assert kwargs == {
            "session_factory": session_factory,
            "email_settings": email_settings,
            "claim_timeout_seconds": 120,
            "batch_size": 1,
        }


def test_auth_email_job_round_robin_caps_each_active_queue_at_25():
    import auth_email_delivery
    import auth_email_job

    calls = []

    assert auth_email_job.run(
        reset_dispatch=lambda: calls.append("reset")
        or auth_email_delivery.AuthEmailDispatchOutcome.COMPLETED,
        verification_dispatch=lambda: calls.append("verification")
        or auth_email_delivery.AuthEmailDispatchOutcome.COMPLETED,
        monotonic_clock=lambda: 0.0,
    ) == 0

    assert auth_email_job.AUTH_EMAIL_JOB_PER_QUEUE_CAP == 25
    assert calls == ["verification", "reset"] * 25


def test_auth_email_job_stops_at_soft_deadline_after_servicing_both_queues():
    import auth_email_delivery
    import auth_email_job

    class ManualClock:
        now = 0.0

        def __call__(self):
            return self.now

        def advance(self, seconds):
            self.now += seconds

    clock = ManualClock()
    calls = []

    def run_verification():
        calls.append("verification")
        clock.advance(100)
        return auth_email_delivery.AuthEmailDispatchOutcome.COMPLETED

    def run_reset():
        calls.append("reset")
        clock.advance(140)
        return auth_email_delivery.AuthEmailDispatchOutcome.COMPLETED

    assert auth_email_job.run(
        reset_dispatch=run_reset,
        verification_dispatch=run_verification,
        monotonic_clock=clock,
    ) == 0

    assert 0 < auth_email_job.AUTH_EMAIL_JOB_DEADLINE_SECONDS < 300
    assert calls == ["verification", "reset"]


def test_auth_email_job_continues_reset_after_verification_exception(capsys):
    import auth_email_delivery
    import auth_email_job

    calls = []

    def fail_verification():
        calls.append("verification")
        raise RuntimeError("private-verification-provider-and-recipient")

    reset_outcomes = iter(
        (
            auth_email_delivery.AuthEmailDispatchOutcome.COMPLETED,
            auth_email_delivery.AuthEmailDispatchOutcome.EMPTY_QUEUE,
        )
    )

    def run_reset():
        calls.append("reset")
        return next(reset_outcomes)

    result = auth_email_job.run(
        reset_dispatch=run_reset,
        verification_dispatch=fail_verification,
    )

    captured = capsys.readouterr()
    assert result == 1
    assert calls == ["verification", "reset", "reset"]
    assert captured.out == ""
    assert captured.err.strip() == "auth-email-job: failed"
    assert "private-verification" not in captured.err


def test_auth_email_job_aggregates_failed_and_invalid_outcomes_once(capsys):
    import auth_email_delivery
    import auth_email_job

    calls = []
    result = auth_email_job.run(
        reset_dispatch=lambda: calls.append("reset")
        or auth_email_delivery.AuthEmailDispatchOutcome.FAILED,
        verification_dispatch=lambda: calls.append("verification") or object(),
    )

    captured = capsys.readouterr()
    assert result == 1
    assert calls == ["verification", "reset"]
    assert captured.out == ""
    assert captured.err.splitlines() == ["auth-email-job: failed"]


def test_auth_email_job_accepts_only_empty_or_completed_outcomes(capsys):
    import auth_email_delivery
    import auth_email_job

    assert auth_email_job.run(
        reset_dispatch=lambda: auth_email_delivery.AuthEmailDispatchOutcome.EMPTY_QUEUE,
        verification_dispatch=lambda: auth_email_delivery.AuthEmailDispatchOutcome.EMPTY_QUEUE,
    ) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_auth_email_job_is_independent_of_web_oauth_and_upload_runtime():
    app_directory = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment.pop("UPLOAD_ROOT", None)
    probe = """
import sys

import auth_email_delivery
import auth_email_job

assert auth_email_job.run(
    reset_dispatch=lambda: auth_email_delivery.AuthEmailDispatchOutcome.EMPTY_QUEUE,
    verification_dispatch=lambda: auth_email_delivery.AuthEmailDispatchOutcome.COMPLETED,
) == 0
for forbidden_module in (
    "main",
    "database",
    "fastapi",
    "oauth_security",
    "upload_assets",
    "upload_scanner",
):
    assert forbidden_module not in sys.modules, forbidden_module
"""

    completed = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=app_directory,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_password_reset_job_runs_one_bounded_dispatch_batch():
    import password_reset_delivery
    import password_reset_job

    calls = []

    result = password_reset_job.run(
        lambda: calls.append("dispatched")
        or password_reset_delivery.PasswordResetDispatchOutcome.COMPLETED
    )

    assert result == 0
    assert calls == ["dispatched"]


def test_password_reset_job_is_independent_of_web_and_upload_runtime():
    app_directory = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment.pop("UPLOAD_ROOT", None)
    probe = """
import sys

import config

def reject_web_settings():
    raise AssertionError("full web settings were loaded")

config.get_settings = reject_web_settings
import password_reset_delivery

password_reset_delivery.dispatch_password_reset_emails_once = (
    lambda: password_reset_delivery.PasswordResetDispatchOutcome.EMPTY_QUEUE
)
import password_reset_job

assert password_reset_job.run() == 0
assert "upload_root" not in password_reset_delivery.PasswordResetWorkerSettings.model_fields
for forbidden_module in (
    "main",
    "database",
    "fastapi",
    "upload_assets",
    "upload_scanner",
):
    assert forbidden_module not in sys.modules, forbidden_module
"""

    completed = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=app_directory,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_password_reset_job_returns_failure_without_reflecting_exception(capsys):
    import password_reset_job

    def fail() -> None:
        raise RuntimeError("smtp-password-private-reset-token")

    result = password_reset_job.run(fail)

    captured = capsys.readouterr()
    assert result == 1
    assert captured.out == ""
    assert captured.err.strip() == "password-reset-job: failed"
    assert "private-reset-token" not in captured.err


def test_password_reset_job_maps_typed_delivery_outcomes_to_exit_status(capsys):
    import password_reset_delivery
    import password_reset_job

    assert password_reset_job.run(
        lambda: password_reset_delivery.PasswordResetDispatchOutcome.EMPTY_QUEUE
    ) == 0
    assert password_reset_job.run(
        lambda: password_reset_delivery.PasswordResetDispatchOutcome.COMPLETED
    ) == 0
    assert password_reset_job.run(
        lambda: password_reset_delivery.PasswordResetDispatchOutcome.FAILED
    ) == 1
    assert password_reset_job.run(lambda: None) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.splitlines() == [
        "password-reset-job: failed",
        "password-reset-job: failed",
    ]


def test_upload_reconciliation_job_propagates_one_shot_outcome(capsys):
    import upload_reconciliation_job

    assert upload_reconciliation_job.run(lambda: True) == 0
    assert upload_reconciliation_job.run(lambda: False) == 1
    assert capsys.readouterr().err.strip() == "upload-reconciliation-job: failed"


def test_upload_reconciliation_job_loads_the_existing_main_one_shot(monkeypatch):
    import main
    import upload_reconciliation_job

    calls = []

    def reconcile() -> bool:
        calls.append("main-one-shot")
        return True

    monkeypatch.setattr(main, "_reconcile_upload_assets_once", reconcile)

    assert upload_reconciliation_job.run() == 0
    assert calls == ["main-one-shot"]


def test_upload_reconciliation_job_returns_failure_without_reflecting_exception(capsys):
    import upload_reconciliation_job

    def fail() -> bool:
        raise RuntimeError("student-upload-private-filename")

    result = upload_reconciliation_job.run(fail)

    captured = capsys.readouterr()
    assert result == 1
    assert captured.out == ""
    assert captured.err.strip() == "upload-reconciliation-job: failed"
    assert "private-filename" not in captured.err


def test_job_main_functions_return_the_run_status(monkeypatch):
    import auth_email_job
    import password_reset_job
    import upload_reconciliation_job

    monkeypatch.setattr(auth_email_job, "run", lambda: 2)
    monkeypatch.setattr(password_reset_job, "run", lambda: 3)
    monkeypatch.setattr(upload_reconciliation_job, "run", lambda: 4)

    assert auth_email_job.main() == 2
    assert password_reset_job.main() == 3
    assert upload_reconciliation_job.main() == 4
