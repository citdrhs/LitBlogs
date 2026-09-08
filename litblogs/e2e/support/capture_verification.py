"""Capture one real E2E verification delivery without contacting SMTP."""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Mapping
from email.message import Message
from pathlib import Path
from typing import TextIO
from urllib.parse import urlsplit

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

import auth_email_delivery
import email_verification_delivery
import models

DATABASE_NAME_PATTERN = re.compile(r"^litblog_test_e2e_[a-z0-9]{16,40}$")
EMAIL_PATTERN = re.compile(
    r"^[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$"
)
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1"})
DATABASE_OVERRIDE_KEYS = frozenset(
    {"database", "dbname", "host", "hostaddr", "port", "service", "user"}
)
FIXED_FAILURE = "Verification email capture failed"


class VerificationCaptureStageFailure(RuntimeError):
    """Carry only a fixed, non-secret process exit code across the CLI boundary."""

    def __init__(self, exit_code: int):
        if exit_code not in {2, 3, 4, 5, 6}:
            raise ValueError("verification capture stage code is invalid")
        self.exit_code = exit_code
        super().__init__(FIXED_FAILURE)


def _load_request(stdin: TextIO) -> tuple[str, str]:
    try:
        payload = json.load(stdin)
        if not isinstance(payload, dict) or set(payload) != {
            "email",
            "frontend_origin",
        }:
            raise ValueError
        email = payload["email"]
        frontend_origin = payload["frontend_origin"]
        if (
            not isinstance(email, str)
            or email != email.strip().lower()
            or len(email) > 254
            or EMAIL_PATTERN.fullmatch(email) is None
            or not isinstance(frontend_origin, str)
        ):
            raise ValueError
        parsed_origin = urlsplit(frontend_origin)
        if (
            parsed_origin.scheme != "http"
            or parsed_origin.hostname not in LOOPBACK_HOSTS
            or parsed_origin.port is None
            or parsed_origin.username is not None
            or parsed_origin.password is not None
            or parsed_origin.path not in {"", "/"}
            or parsed_origin.query
            or parsed_origin.fragment
            or frontend_origin.endswith("/")
        ):
            raise ValueError
    except (AttributeError, json.JSONDecodeError, TypeError, ValueError):
        raise RuntimeError("verification capture request is invalid") from None
    return email, frontend_origin


def _load_validated_runtime_url(environment: Mapping[str, str]) -> str:
    try:
        if (
            environment.get("E2E_DISPOSABLE_DATABASE_CONFIRMED")
            != "litblogs-e2e-only"
        ):
            raise ValueError
        run_directory = Path(environment["E2E_RUN_DIR"]).resolve(strict=True)
        metadata_path = (run_directory / "database.json").resolve(strict=True)
        if metadata_path.parent != run_directory:
            raise ValueError
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if not isinstance(metadata, dict) or not isinstance(
            metadata.get("runtime_url"), str
        ):
            raise ValueError
        raw_url = metadata["runtime_url"]
        url = make_url(raw_url)
        if (
            not url.drivername.startswith("postgresql")
            or url.host not in LOOPBACK_HOSTS
            or url.username != "litblogs_runtime"
            or not url.password
            or not DATABASE_NAME_PATTERN.fullmatch(url.database or "")
            or set(url.query) & DATABASE_OVERRIDE_KEYS
        ):
            raise ValueError
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        raise RuntimeError("verification capture runtime database is invalid") from None
    return raw_url


def _require_runtime_identity(connection) -> None:
    try:
        identity = connection.exec_driver_sql(
            "SELECT session_user, current_user"
        ).one()
        if tuple(identity) != ("litblogs_runtime", "litblogs_runtime"):
            raise ValueError
    except Exception:
        raise RuntimeError("verification capture runtime database is invalid") from None


def _html_parts(message: Message) -> list[str]:
    parts: list[str] = []
    for part in message.walk():
        if part.get_content_type() != "text/html":
            continue
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes):
            continue
        parts.append(payload.decode(part.get_content_charset() or "utf-8"))
    return parts


def _extract_token_from_message(
    message: Message,
    *,
    expected_email: str,
    expected_origin: str,
) -> str:
    try:
        if (
            message.get("Subject") != "Verify Your LitBlog Email"
            or message.get("To") != expected_email
        ):
            raise ValueError
        html = "\n".join(_html_parts(message))
        prefix = f"{expected_origin}/verify-email#token="
        candidates = re.findall(
            rf"{re.escape(prefix)}([A-Za-z0-9_-]{{32,128}})",
            html,
        )
        if len(set(candidates)) != 1 or "/verify-email?token=" in html:
            raise ValueError
        token = candidates[0]
        if TOKEN_PATTERN.fullmatch(token) is None:
            raise ValueError
    except (AttributeError, UnicodeError, ValueError):
        raise RuntimeError("verification email capture failed") from None
    return token


def _target_verification(session_factory, email: str):
    with session_factory() as db:
        return (
            db.query(models.EmailVerification)
            .join(models.User, models.User.id == models.EmailVerification.user_id)
            .filter(models.User.email == email)
            .one_or_none()
        )


def _capture_token(stdin: TextIO, environment: Mapping[str, str]) -> str:
    try:
        email, frontend_origin = _load_request(stdin)
    except Exception:
        raise VerificationCaptureStageFailure(2) from None
    try:
        runtime_url = _load_validated_runtime_url(environment)
    except Exception:
        raise VerificationCaptureStageFailure(3) from None
    try:
        engine = create_engine(
            runtime_url,
            pool_pre_ping=True,
            connect_args={"connect_timeout": 5},
        )
        session_factory = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=engine,
            expire_on_commit=False,
        )
    except Exception:
        raise VerificationCaptureStageFailure(3) from None
    captured: dict[str, object] = {}

    def capture_smtp(settings, recipient, message):
        if captured:
            return False
        captured.update(
            settings=settings,
            recipient=recipient,
            message=message,
        )
        return True

    original_smtp = auth_email_delivery.send_smtp_message
    try:
        try:
            with engine.connect() as connection:
                _require_runtime_identity(connection)
            before = _target_verification(session_factory, email)
            if (
                before is None
                or before.delivery_status
                != email_verification_delivery.EMAIL_VERIFICATION_PENDING
                or before.token_digest is not None
            ):
                raise RuntimeError
            verification_id = before.id
        except VerificationCaptureStageFailure:
            raise
        except Exception:
            raise VerificationCaptureStageFailure(4) from None
        try:
            settings = email_verification_delivery.EmailVerificationEmailSettings(
                frontend_url=frontend_origin,
                email_host="e2e-smtp.invalid",
                email_port=587,
                email_smtp_timeout_seconds=5,
                email_username="e2e-verification",
                email_password="e2e-verification-password",
                email_from="no-reply@example.com",
            )
            auth_email_delivery.send_smtp_message = capture_smtp
            outcome = email_verification_delivery.dispatch_email_verification_batch_once(
                session_factory=session_factory,
                email_settings=settings,
                claim_timeout_seconds=120,
                batch_size=1,
            )
            message = captured.get("message")
            if (
                outcome
                is not email_verification_delivery.EmailVerificationDispatchOutcome.COMPLETED
                or captured.get("recipient") != email
                or not isinstance(message, Message)
            ):
                raise RuntimeError
            token = _extract_token_from_message(
                message,
                expected_email=email,
                expected_origin=frontend_origin,
            )
        except Exception:
            raise VerificationCaptureStageFailure(5) from None
        try:
            after = _target_verification(session_factory, email)
            if (
                after is None
                or after.id != verification_id
                or after.delivery_status
                != email_verification_delivery.EMAIL_VERIFICATION_DELIVERED
                or after.delivery_claim_digest is not None
                or after.token_digest
                != email_verification_delivery.email_verification_token_digest(token)
            ):
                raise RuntimeError
        except VerificationCaptureStageFailure:
            raise
        except Exception:
            raise VerificationCaptureStageFailure(6) from None
        return token
    finally:
        auth_email_delivery.send_smtp_message = original_smtp
        try:
            engine.dispose()
        except Exception:
            pass


def main(
    *,
    stdin: TextIO = sys.stdin,
    environment: Mapping[str, str] = os.environ,
) -> int:
    try:
        token = _capture_token(stdin, environment)
    except VerificationCaptureStageFailure as error:
        print(FIXED_FAILURE, file=sys.stderr)
        return error.exit_code
    except Exception:
        print(FIXED_FAILURE, file=sys.stderr)
        return 1
    print(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
