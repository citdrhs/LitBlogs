"""Standalone, bounded password-reset delivery runtime."""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from enum import StrEnum

from sqlalchemy import and_, or_
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

import auth_email_delivery
import models
from identity_controls import invalidate_password_reset_requests

# Preserve the legacy module patch point used by the web compatibility wrapper.
smtplib = auth_email_delivery.smtplib

APP_DIRECTORY = auth_email_delivery.APP_DIRECTORY
EXPECTED_ALEMBIC_HEAD = auth_email_delivery.EXPECTED_ALEMBIC_HEAD
MAX_PASSWORD_RESET_BATCH_SIZE = 100

PASSWORD_RESET_PENDING = "PENDING"
PASSWORD_RESET_PROCESSING = "PROCESSING"
PASSWORD_RESET_DELIVERED = "DELIVERED"
PASSWORD_RESET_FAILED = "FAILED"
PASSWORD_RESET_LIFETIME = timedelta(hours=1)


PasswordResetOperationalError = auth_email_delivery.AuthEmailOperationalError
PasswordResetDispatchOutcome = auth_email_delivery.AuthEmailDispatchOutcome
PasswordResetWorkerSettings = auth_email_delivery.AuthEmailWorkerSettings
PasswordResetEmailSettings = auth_email_delivery.AuthEmailSettings


class PasswordResetCompletionOutcome(StrEnum):
    COMPLETED = "COMPLETED"
    ACCOUNT_DISABLED = "ACCOUNT_DISABLED"
    ACCOUNT_INELIGIBLE = "ACCOUNT_INELIGIBLE"
    CLAIM_LOST = "CLAIM_LOST"


def load_password_reset_worker_settings() -> PasswordResetWorkerSettings:
    """Compatibility wrapper for the shared authentication-email settings."""

    return auth_email_delivery.load_auth_email_worker_settings()


def worker_engine_options(settings: PasswordResetWorkerSettings) -> dict:
    return auth_email_delivery.auth_email_engine_options(settings)


def create_password_reset_engine(settings: PasswordResetWorkerSettings) -> Engine:
    return auth_email_delivery.create_auth_email_engine(settings)


def check_password_reset_database_readiness(engine: Engine) -> None:
    auth_email_delivery.check_auth_email_database_readiness(engine)


def _utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def password_reset_token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def password_reset_claim_digest(claim_nonce: str) -> str:
    return hashlib.sha256(
        b"litblog:password-reset-delivery-claim:v1\0"
        + claim_nonce.encode("utf-8")
    ).hexdigest()


def _open_delivery_session(
    session_factory: Callable[[], Session],
) -> Session:
    try:
        return session_factory()
    except Exception:
        raise PasswordResetOperationalError(
            "Password-reset database operation failed"
        ) from None


def _rollback_quietly(db: Session) -> None:
    try:
        db.rollback()
    except Exception:
        # Never replace the fixed operational error with driver details.
        return


def _close_delivery_session(db: Session) -> None:
    try:
        db.close()
    except Exception:
        raise PasswordResetOperationalError(
            "Password-reset database operation failed"
        ) from None


def claim_password_reset_delivery(
    session_factory: Callable[[], Session],
    *,
    claim_timeout_seconds: int,
) -> tuple[int, str, str] | None:
    db = _open_delivery_session(session_factory)
    try:
        now = _utc_now_naive()
        stale_before = now - timedelta(seconds=claim_timeout_seconds)
        claimable = or_(
            models.PasswordReset.delivery_status == PASSWORD_RESET_PENDING,
            and_(
                models.PasswordReset.delivery_status == PASSWORD_RESET_PROCESSING,
                or_(
                    models.PasswordReset.delivery_attempted_at.is_(None),
                    models.PasswordReset.delivery_attempted_at <= stale_before,
                ),
            ),
        )
        candidate_ids = [
            reset_id
            for (reset_id,) in (
                db.query(models.PasswordReset.id)
                .filter(claimable)
                .order_by(models.PasswordReset.created_at, models.PasswordReset.id)
                .limit(25)
                .all()
            )
        ]

        for reset_id in candidate_ids:
            locked_reset = (
                db.query(models.PasswordReset, models.User)
                .join(models.User, models.User.id == models.PasswordReset.user_id)
                .filter(models.PasswordReset.id == reset_id, claimable)
                .with_for_update(of=models.User)
                .first()
            )
            if locked_reset is None:
                db.rollback()
                continue
            reset_request, user = locked_reset
            if user.disabled_at is not None or user.email_verified_at is None:
                invalidate_password_reset_requests(db, user_id=user.id)
                db.commit()
                continue

            claim_nonce = secrets.token_urlsafe(32)
            claim_digest = password_reset_claim_digest(claim_nonce)
            claimed = (
                db.query(models.PasswordReset)
                .filter(models.PasswordReset.id == reset_id, claimable)
                .update(
                    {
                        models.PasswordReset.delivery_status: PASSWORD_RESET_PROCESSING,
                        models.PasswordReset.delivery_attempted_at: now,
                        models.PasswordReset.delivery_claim_digest: claim_digest,
                    },
                    synchronize_session=False,
                )
            )
            if not claimed:
                db.rollback()
                continue

            claimed_reset_id = reset_request.id
            claimed_email = user.email
            db.commit()
            return claimed_reset_id, claimed_email, claim_nonce
        return None
    except Exception:
        _rollback_quietly(db)
        raise PasswordResetOperationalError(
            "Password-reset database operation failed"
        ) from None
    finally:
        _close_delivery_session(db)


def complete_password_reset_delivery_outcome(
    session_factory: Callable[[], Session],
    reset_id: int,
    claim_nonce: str,
    raw_token: str,
    delivered: bool,
) -> PasswordResetCompletionOutcome:
    db = _open_delivery_session(session_factory)
    try:
        claim_digest = password_reset_claim_digest(claim_nonce)
        locked_reset = (
            db.query(models.PasswordReset, models.User)
            .join(models.User, models.User.id == models.PasswordReset.user_id)
            .filter(
                models.PasswordReset.id == reset_id,
                models.PasswordReset.delivery_status == PASSWORD_RESET_PROCESSING,
                models.PasswordReset.delivery_claim_digest == claim_digest,
            )
            .with_for_update(of=models.User)
            .first()
        )
        if locked_reset is None:
            db.rollback()
            return PasswordResetCompletionOutcome.CLAIM_LOST
        _reset_request, user = locked_reset
        if user.disabled_at is not None or user.email_verified_at is None:
            invalidate_password_reset_requests(db, user_id=user.id)
            db.commit()
            return (
                PasswordResetCompletionOutcome.ACCOUNT_DISABLED
                if user.disabled_at is not None
                else PasswordResetCompletionOutcome.ACCOUNT_INELIGIBLE
            )

        if delivered:
            completion_values = {
                models.PasswordReset.token: password_reset_token_digest(raw_token),
                models.PasswordReset.expires_at: _utc_now_naive()
                + PASSWORD_RESET_LIFETIME,
                models.PasswordReset.delivery_status: PASSWORD_RESET_DELIVERED,
                models.PasswordReset.delivery_claim_digest: None,
            }
        else:
            completion_values = {
                models.PasswordReset.token: None,
                models.PasswordReset.expires_at: None,
                models.PasswordReset.delivery_status: PASSWORD_RESET_FAILED,
                models.PasswordReset.delivery_claim_digest: None,
            }
        completed = (
            db.query(models.PasswordReset)
            .filter(
                models.PasswordReset.id == reset_id,
                models.PasswordReset.delivery_status == PASSWORD_RESET_PROCESSING,
                models.PasswordReset.delivery_claim_digest == claim_digest,
            )
            .update(completion_values, synchronize_session=False)
        )
        if completed != 1:
            db.rollback()
            return PasswordResetCompletionOutcome.CLAIM_LOST
        db.commit()
        return PasswordResetCompletionOutcome.COMPLETED
    except Exception:
        _rollback_quietly(db)
        raise PasswordResetOperationalError(
            "Password-reset database operation failed"
        ) from None
    finally:
        _close_delivery_session(db)


def complete_password_reset_delivery(
    session_factory: Callable[[], Session],
    reset_id: int,
    claim_nonce: str,
    raw_token: str,
    delivered: bool,
) -> bool:
    """Compatibility boundary for the web module's existing bool wrapper."""

    return (
        complete_password_reset_delivery_outcome(
            session_factory,
            reset_id,
            claim_nonce,
            raw_token,
            delivered,
        )
        is PasswordResetCompletionOutcome.COMPLETED
    )


def send_password_reset_email(
    settings: PasswordResetEmailSettings,
    email: str,
    token: str,
) -> bool:
    reset_url = f"{settings.frontend_url}/reset-password#token={token}"
    if not all(
        [
            settings.email_host,
            settings.email_username,
            settings.email_password,
            settings.email_from,
        ]
    ):
        return False

    message = MIMEMultipart("alternative")
    message["Subject"] = "Reset Your LitBlog Password"
    message["From"] = settings.email_from
    message["To"] = email
    html = f"""
        <html>
            <head></head>
            <body style="margin:0; padding:0; background-color:#f3f4f6;">
                <div style="max-width:640px; margin:0 auto; padding:32px 16px;">
                    <div style="background-color:#ffffff; border-radius:16px; padding:32px; font-family: Arial, sans-serif; color:#111827; box-shadow:0 10px 30px rgba(0,0,0,0.08);">
                        <div style="text-align:center; margin-bottom:24px;">
                            <h1 style="margin:0; font-size:24px; font-weight:700;">Reset your LitBlog password</h1>
                            <p style="margin:8px 0 0; color:#6b7280; font-size:14px;">We received a request to reset your password.</p>
                        </div>
                        <p style="font-size:16px; line-height:1.6; margin:0 0 24px;">
                            Click the button below to set a new password. This link will expire in <strong>1 hour</strong>.
                        </p>
                        <div style="text-align:center; margin:24px 0;">
                            <a href="{reset_url}" style="display:inline-block; background-color:#4F46E5; color:#ffffff; text-decoration:none; padding:12px 24px; border-radius:999px; font-weight:600;">Reset Password</a>
                        </div>
                        <p style="font-size:14px; color:#6b7280; line-height:1.6; margin:0 0 16px;">
                            If you didn't request a password reset, you can safely ignore this email.
                        </p>
                        <div style="background-color:#f9fafb; border-radius:12px; padding:16px; font-size:12px; color:#6b7280;">
                            Having trouble with the button? Copy and paste this link into your browser:<br />
                            <span style="word-break:break-all; color:#4F46E5;">{reset_url}</span>
                        </div>
                    </div>
                    <p style="text-align:center; color:#9ca3af; font-size:12px; margin-top:16px;">&copy; {datetime.now(UTC).year} LitBlog</p>
                </div>
            </body>
        </html>
        """
    message.attach(MIMEText(html, "html"))
    return auth_email_delivery.send_smtp_message(settings, email, message)


def dispatch_password_reset_batch(
    *,
    batch_size: int,
    claim: Callable[[], tuple[int, str, str] | None],
    send: Callable[[str, str], bool],
    complete: Callable[
        [int, str, str, bool], PasswordResetCompletionOutcome | bool
    ],
) -> PasswordResetDispatchOutcome:
    if (
        not isinstance(batch_size, int)
        or isinstance(batch_size, bool)
        or not 1 <= batch_size <= MAX_PASSWORD_RESET_BATCH_SIZE
    ):
        raise ValueError("password-reset batch size is outside the safe bound")
    def completion_succeeded(
        completion: PasswordResetCompletionOutcome | bool,
    ) -> bool:
        if completion is True:
            return True
        if completion is False:
            return False
        if not isinstance(completion, PasswordResetCompletionOutcome):
            raise PasswordResetOperationalError(
                "Password-reset completion operation failed"
            )
        return completion is PasswordResetCompletionOutcome.COMPLETED

    return auth_email_delivery.dispatch_auth_email_batch(
        batch_size=batch_size,
        claim=claim,
        send=send,
        complete=complete,
        completion_succeeded=completion_succeeded,
    )


def dispatch_password_reset_batch_once(
    *,
    session_factory: Callable[[], Session],
    email_settings: PasswordResetEmailSettings,
    claim_timeout_seconds: int,
    batch_size: int = 100,
) -> PasswordResetDispatchOutcome:
    return dispatch_password_reset_batch(
        batch_size=batch_size,
        claim=lambda: claim_password_reset_delivery(
            session_factory,
            claim_timeout_seconds=claim_timeout_seconds,
        ),
        send=lambda email, token: send_password_reset_email(
            email_settings,
            email,
            token,
        ),
        complete=lambda reset_id, claim_nonce, raw_token, delivered: (
            complete_password_reset_delivery_outcome(
                session_factory,
                reset_id,
                claim_nonce,
                raw_token,
                delivered,
            )
        ),
    )


def dispatch_password_reset_emails_once(
    batch_size: int = 100,
) -> PasswordResetDispatchOutcome:
    settings = load_password_reset_worker_settings()
    engine = create_password_reset_engine(settings)
    try:
        check_password_reset_database_readiness(engine)
        session_factory = auth_email_delivery.create_auth_email_session_factory(engine)
        email_settings = auth_email_delivery.auth_email_settings_from_worker(settings)
        return dispatch_password_reset_batch_once(
            session_factory=session_factory,
            email_settings=email_settings,
            claim_timeout_seconds=settings.password_reset_claim_timeout_seconds,
            batch_size=batch_size,
        )
    finally:
        engine.dispose()
