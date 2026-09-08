from __future__ import annotations

import io
import json
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pytest

from e2e.support import capture_verification


class _IdentityResult:
    def __init__(self, identity):
        self.identity = identity

    def one(self):
        return self.identity


class _IdentityConnection:
    def __init__(self, identity):
        self.identity = identity
        self.statements = []

    def exec_driver_sql(self, statement):
        self.statements.append(statement)
        return _IdentityResult(self.identity)


def _runtime_metadata(tmp_path, runtime_url: str) -> dict[str, str]:
    run_directory = tmp_path / "litblogs-e2e-run"
    run_directory.mkdir(parents=True)
    (run_directory / "database.json").write_text(
        json.dumps({"runtime_url": runtime_url}),
        encoding="utf-8",
    )
    return {"E2E_RUN_DIR": str(run_directory)}


def test_request_uses_stdin_and_requires_an_http_loopback_frontend():
    payload = capture_verification._load_request(
        io.StringIO(
            json.dumps(
                {
                    "email": "student.journey@example.com",
                    "frontend_origin": "http://127.0.0.1:4173",
                }
            )
        )
    )

    assert payload == (
        "student.journey@example.com",
        "http://127.0.0.1:4173",
    )

    for rejected in (
        "not-json",
        json.dumps({"email": "student.journey@example.com"}),
        json.dumps(
            {
                "email": "student.journey@example.com",
                "frontend_origin": "https://litblogs.school.org",
            }
        ),
        json.dumps(
            {
                "email": "student.journey@example.com",
                "frontend_origin": "http://127.0.0.1:4173/path",
            }
        ),
    ):
        with pytest.raises(RuntimeError, match="verification capture request is invalid"):
            capture_verification._load_request(io.StringIO(rejected))


def test_runtime_url_is_loaded_from_run_metadata_and_requires_exact_e2e_identity(
    tmp_path,
):
    runtime_url = (
        "postgresql+psycopg2://litblogs_runtime:private-password@127.0.0.1:5432/"
        "litblog_test_e2e_0123456789abcdef"
    )
    environment = _runtime_metadata(tmp_path, runtime_url)

    with pytest.raises(RuntimeError, match="runtime database is invalid"):
        capture_verification._load_validated_runtime_url(environment)
    with pytest.raises(RuntimeError, match="runtime database is invalid"):
        capture_verification._load_validated_runtime_url(
            {
                **environment,
                "E2E_DISPOSABLE_DATABASE_CONFIRMED": "wrong-confirmation",
            }
        )
    environment["E2E_DISPOSABLE_DATABASE_CONFIRMED"] = "litblogs-e2e-only"
    assert capture_verification._load_validated_runtime_url(environment) == runtime_url

    rejected_urls = (
        runtime_url.replace("litblogs_runtime", "litblogs_migrator", 1),
        runtime_url.replace("127.0.0.1", "db.school.example"),
        runtime_url.replace(
            "litblog_test_e2e_0123456789abcdef",
            "litblogs_production",
        ),
        f"{runtime_url}?host=db.school.example",
    )
    for index, rejected_url in enumerate(rejected_urls):
        rejected_environment = _runtime_metadata(
            tmp_path / f"rejected-{index}",
            rejected_url,
        )
        rejected_environment["E2E_DISPOSABLE_DATABASE_CONFIRMED"] = (
            "litblogs-e2e-only"
        )
        with pytest.raises(RuntimeError, match="runtime database is invalid"):
            capture_verification._load_validated_runtime_url(rejected_environment)


def test_runtime_identity_probe_requires_session_and_current_runtime_roles():
    connection = _IdentityConnection(("litblogs_runtime", "litblogs_runtime"))

    capture_verification._require_runtime_identity(connection)

    assert connection.statements == ["SELECT session_user, current_user"]
    for rejected in (
        ("litblogs_migrator", "litblogs_migrator"),
        ("litblogs_runtime", "litblogs_migrator"),
    ):
        with pytest.raises(RuntimeError, match="runtime database is invalid"):
            capture_verification._require_runtime_identity(
                _IdentityConnection(rejected)
            )


def test_template_capture_requires_exact_recipient_fragment_link_and_subject():
    token = "private-token-material_0123456789"
    recipient = "student.journey@example.com"
    origin = "http://127.0.0.1:4173"
    message = MIMEMultipart("alternative")
    message["Subject"] = "Verify Your LitBlog Email"
    message["To"] = recipient
    message.attach(
        MIMEText(
            f'<a href="{origin}/verify-email#token={token}">Verify Email</a>',
            "html",
        )
    )

    assert capture_verification._extract_token_from_message(
        message,
        expected_email=recipient,
        expected_origin=origin,
    ) == token

    message.replace_header("To", "someone-else@example.com")
    with pytest.raises(RuntimeError, match="verification email capture failed"):
        capture_verification._extract_token_from_message(
            message,
            expected_email=recipient,
            expected_origin=origin,
        )


def test_main_prints_only_token_on_success(monkeypatch, capsys):
    token = "private-success-token_0123456789"
    monkeypatch.setattr(
        capture_verification,
        "_capture_token",
        lambda _stdin, _environment: token,
    )

    assert capture_verification.main(
        stdin=io.StringIO("{}"),
        environment={},
    ) == 0

    captured = capsys.readouterr()
    assert captured.out == f"{token}\n"
    assert captured.err == ""


def test_main_sanitizes_every_failure_without_a_traceback(monkeypatch, capsys):
    private_detail = "private-db-password recipient@example.com raw-token"
    monkeypatch.setattr(
        capture_verification,
        "_capture_token",
        lambda _stdin, _environment: (_ for _ in ()).throw(
            RuntimeError(private_detail)
        ),
    )

    assert capture_verification.main(
        stdin=io.StringIO("{}"),
        environment={},
    ) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Verification email capture failed\n"
    assert private_detail not in captured.err
    assert "Traceback" not in captured.err


def test_main_preserves_only_an_allowlisted_stage_exit_code(monkeypatch, capsys):
    stage_failure_type = getattr(
        capture_verification,
        "VerificationCaptureStageFailure",
        RuntimeError,
    )
    monkeypatch.setattr(
        capture_verification,
        "_capture_token",
        lambda _stdin, _environment: (_ for _ in ()).throw(
            stage_failure_type(4)
        ),
    )

    assert capture_verification.main(
        stdin=io.StringIO("{}"),
        environment={},
    ) == 4

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Verification email capture failed\n"
