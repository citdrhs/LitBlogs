from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace


def test_auth_email_job_uses_one_shared_runtime_and_runs_both_batches_once(
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
    monkeypatch.setattr(
        password_reset_delivery,
        "dispatch_password_reset_batch_once",
        lambda **kwargs: calls.append(("reset", kwargs))
        or auth_email_delivery.AuthEmailDispatchOutcome.COMPLETED,
    )
    monkeypatch.setattr(
        email_verification_delivery,
        "dispatch_email_verification_batch_once",
        lambda **kwargs: calls.append(("verification", kwargs))
        or auth_email_delivery.AuthEmailDispatchOutcome.EMPTY_QUEUE,
    )

    assert auth_email_job.run() == 0

    assert [call[0] if isinstance(call, tuple) else call for call in calls] == [
        "load",
        "engine",
        "ready",
        "sessions",
        "smtp",
        "reset",
        "verification",
        "dispose",
    ]
    reset_kwargs = next(
        call[1]
        for call in calls
        if isinstance(call, tuple) and call[0] == "reset"
    )
    verification_kwargs = next(
        call[1]
        for call in calls
        if isinstance(call, tuple) and call[0] == "verification"
    )
    for kwargs in (reset_kwargs, verification_kwargs):
        assert kwargs == {
            "session_factory": session_factory,
            "email_settings": email_settings,
            "claim_timeout_seconds": 120,
            "batch_size": 100,
        }


def test_auth_email_job_attempts_verification_after_reset_exception(capsys):
    import auth_email_delivery
    import auth_email_job

    calls = []

    def fail_reset():
        calls.append("reset")
        raise RuntimeError("private-reset-provider-and-recipient")

    def run_verification():
        calls.append("verification")
        return auth_email_delivery.AuthEmailDispatchOutcome.COMPLETED

    result = auth_email_job.run(
        reset_dispatch=fail_reset,
        verification_dispatch=run_verification,
    )

    captured = capsys.readouterr()
    assert result == 1
    assert calls == ["reset", "verification"]
    assert captured.out == ""
    assert captured.err.strip() == "auth-email-job: failed"
    assert "private-reset" not in captured.err


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
    assert calls == ["reset", "verification"]
    assert captured.out == ""
    assert captured.err.splitlines() == ["auth-email-job: failed"]


def test_auth_email_job_accepts_only_empty_or_completed_outcomes(capsys):
    import auth_email_delivery
    import auth_email_job

    assert auth_email_job.run(
        reset_dispatch=lambda: auth_email_delivery.AuthEmailDispatchOutcome.EMPTY_QUEUE,
        verification_dispatch=lambda: (
            auth_email_delivery.AuthEmailDispatchOutcome.COMPLETED
        ),
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
