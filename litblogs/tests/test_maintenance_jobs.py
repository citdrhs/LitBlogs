from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


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
    import password_reset_job
    import upload_reconciliation_job

    monkeypatch.setattr(password_reset_job, "run", lambda: 3)
    monkeypatch.setattr(upload_reconciliation_job, "run", lambda: 4)

    assert password_reset_job.main() == 3
    assert upload_reconciliation_job.main() == 4
