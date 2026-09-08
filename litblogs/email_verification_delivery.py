"""Separate claim, token, template, and completion semantics for verification."""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from enum import StrEnum

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

import auth_email_delivery
import models

EXPECTED_ALEMBIC_HEAD = auth_email_delivery.EXPECTED_ALEMBIC_HEAD
MAX_EMAIL_VERIFICATION_BATCH_SIZE = 100
EMAIL_VERIFICATION_CLAIM_CANDIDATE_LIMIT = 25

EMAIL_VERIFICATION_PENDING = "PENDING"
EMAIL_VERIFICATION_PROCESSING = "PROCESSING"
EMAIL_VERIFICATION_DELIVERED = "DELIVERED"
EMAIL_VERIFICATION_FAILED = "FAILED"
EMAIL_VERIFICATION_LIFETIME = timedelta(hours=24)
EMAIL_VERIFICATION_RESEND_COOLDOWN = timedelta(minutes=5)

EmailVerificationOperationalError = auth_email_delivery.AuthEmailOperationalError
EmailVerificationDispatchOutcome = auth_email_delivery.AuthEmailDispatchOutcome
EmailVerificationEmailSettings = auth_email_delivery.AuthEmailSettings


class EmailVerificationCompletionOutcome(StrEnum):
    COMPLETED = "COMPLETED"
    ACCOUNT_INELIGIBLE = "ACCOUNT_INELIGIBLE"
    CLAIM_LOST = "CLAIM_LOST"


def _utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def email_verification_token_digest(raw_token: str) -> str:
    return hashlib.sha256(
        f"litblogs-email-verification-v1:{raw_token}".encode("utf-8")
    ).hexdigest()


def email_verification_claim_digest(claim_nonce: str) -> str:
    return hashlib.sha256(
        f"litblogs-email-verification-claim-v1:{claim_nonce}".encode("utf-8")
    ).hexdigest()


def _open_delivery_session(
    session_factory: Callable[[], Session],
) -> Session:
    try:
        return session_factory()
    except Exception:
        raise EmailVerificationOperationalError(
            "Email-verification database operation failed"
        ) from None


def _rollback_quietly(db: Session) -> None:
    try:
        db.rollback()
    except Exception:
        return


def _close_delivery_session(db: Session) -> None:
    try:
        db.close()
    except Exception:
        raise EmailVerificationOperationalError(
            "Email-verification database operation failed"
        ) from None


def _invalidation_values(now: datetime) -> dict:
    return {
        models.EmailVerification.token_digest: None,
        models.EmailVerification.expires_at: None,
        models.EmailVerification.delivery_status: EMAIL_VERIFICATION_FAILED,
        models.EmailVerification.delivery_attempted_at: now,
        models.EmailVerification.delivery_claim_digest: None,
    }


def claim_email_verification_delivery(
    session_factory: Callable[[], Session],
    *,
    claim_timeout_seconds: int,
) -> tuple[int, str, str] | None:
    db = _open_delivery_session(session_factory)
    try:
        now = _utc_now_naive()
        stale_before = now - timedelta(seconds=claim_timeout_seconds)
        claimable = or_(
            models.EmailVerification.delivery_status
            == EMAIL_VERIFICATION_PENDING,
            and_(
                models.EmailVerification.delivery_status
                == EMAIL_VERIFICATION_PROCESSING,
                or_(
                    models.EmailVerification.delivery_attempted_at.is_(None),
                    models.EmailVerification.delivery_attempted_at
                    <= stale_before,
                ),
            ),
        )
        candidate_ids = [
            verification_id
            for (verification_id,) in (
                db.query(models.EmailVerification.id)
                .filter(claimable)
                .order_by(
                    models.EmailVerification.created_at,
                    models.EmailVerification.id,
                )
                .limit(EMAIL_VERIFICATION_CLAIM_CANDIDATE_LIMIT)
                .all()
            )
        ]

        for verification_id in candidate_ids:
            locked_verification = (
                db.query(models.EmailVerification, models.User)
                .join(
                    models.User,
                    models.User.id == models.EmailVerification.user_id,
                )
                .filter(
                    models.EmailVerification.id == verification_id,
                    claimable,
                )
                .with_for_update(of=models.User)
                .first()
            )
            if locked_verification is None:
                db.rollback()
                continue
            verification, user = locked_verification
            if user.disabled_at is not None or user.email_verified_at is not None:
                invalidated = (
                    db.query(models.EmailVerification)
                    .filter(
                        models.EmailVerification.id == verification_id,
                        claimable,
                    )
                    .update(
                        _invalidation_values(now),
                        synchronize_session=False,
                    )
                )
                if invalidated == 1:
                    db.commit()
                else:
                    db.rollback()
                continue

            claim_nonce = secrets.token_hex(32)
            claim_digest = email_verification_claim_digest(claim_nonce)
            claimed = (
                db.query(models.EmailVerification)
                .filter(
                    models.EmailVerification.id == verification_id,
                    claimable,
                )
                .update(
                    {
                        models.EmailVerification.delivery_status: (
                            EMAIL_VERIFICATION_PROCESSING
                        ),
                        models.EmailVerification.delivery_attempted_at: now,
                        models.EmailVerification.delivery_claim_digest: claim_digest,
                    },
                    synchronize_session=False,
                )
            )
            if claimed != 1:
                db.rollback()
                continue

            claimed_verification_id = verification.id
            claimed_email = user.email
            db.commit()
            return claimed_verification_id, claimed_email, claim_nonce
        return None
    except Exception:
        _rollback_quietly(db)
        raise EmailVerificationOperationalError(
            "Email-verification database operation failed"
        ) from None
    finally:
        _close_delivery_session(db)


def complete_email_verification_delivery_outcome(
    session_factory: Callable[[], Session],
    verification_id: int,
    claim_nonce: str,
    raw_token: str,
    delivered: bool,
) -> EmailVerificationCompletionOutcome:
    db = _open_delivery_session(session_factory)
    try:
        claim_digest = email_verification_claim_digest(claim_nonce)
        locked_verification = (
            db.query(models.EmailVerification, models.User)
            .join(
                models.User,
                models.User.id == models.EmailVerification.user_id,
            )
            .filter(
                models.EmailVerification.id == verification_id,
                models.EmailVerification.delivery_status
                == EMAIL_VERIFICATION_PROCESSING,
                models.EmailVerification.delivery_claim_digest == claim_digest,
            )
            .with_for_update(of=models.User)
            .first()
        )
        if locked_verification is None:
            db.rollback()
            return EmailVerificationCompletionOutcome.CLAIM_LOST

        _verification, user = locked_verification
        now = _utc_now_naive()
        if user.disabled_at is not None or user.email_verified_at is not None:
            completion_values = _invalidation_values(now)
            completion_outcome = (
                EmailVerificationCompletionOutcome.ACCOUNT_INELIGIBLE
            )
        elif delivered:
            completion_values = {
                models.EmailVerification.token_digest: (
                    email_verification_token_digest(raw_token)
                ),
                models.EmailVerification.expires_at: (
                    now + EMAIL_VERIFICATION_LIFETIME
                ),
                models.EmailVerification.delivery_status: (
                    EMAIL_VERIFICATION_DELIVERED
                ),
                models.EmailVerification.delivery_claim_digest: None,
            }
            completion_outcome = EmailVerificationCompletionOutcome.COMPLETED
        else:
            completion_values = {
                models.EmailVerification.token_digest: None,
                models.EmailVerification.expires_at: None,
                models.EmailVerification.delivery_status: EMAIL_VERIFICATION_FAILED,
                models.EmailVerification.delivery_claim_digest: None,
            }
            completion_outcome = EmailVerificationCompletionOutcome.COMPLETED

        completed = (
            db.query(models.EmailVerification)
            .filter(
                models.EmailVerification.id == verification_id,
                models.EmailVerification.delivery_status
                == EMAIL_VERIFICATION_PROCESSING,
                models.EmailVerification.delivery_claim_digest == claim_digest,
            )
            .update(completion_values, synchronize_session=False)
        )
        if completed != 1:
            db.rollback()
            return EmailVerificationCompletionOutcome.CLAIM_LOST
        db.commit()
        return completion_outcome
    except Exception:
        _rollback_quietly(db)
        raise EmailVerificationOperationalError(
            "Email-verification database operation failed"
        ) from None
    finally:
        _close_delivery_session(db)


def complete_email_verification_delivery(
    session_factory: Callable[[], Session],
    verification_id: int,
    claim_nonce: str,
    raw_token: str,
    delivered: bool,
) -> bool:
    return (
        complete_email_verification_delivery_outcome(
            session_factory,
            verification_id,
            claim_nonce,
            raw_token,
            delivered,
        )
        is EmailVerificationCompletionOutcome.COMPLETED
    )


def send_email_verification_email(
    settings: EmailVerificationEmailSettings,
    email: str,
    raw_token: str,
) -> bool:
    verification_url = (
        f"{settings.frontend_url}/verify-email#token={raw_token}"
    )
    if not all(
        (
            settings.email_host,
            settings.email_username,
            settings.email_password,
            settings.email_from,
        )
    ):
        return False

    message = MIMEMultipart("alternative")
    message["Subject"] = "Verify Your LitBlog Email"
    message["From"] = settings.email_from
    message["To"] = email
    html = f"""
        <html>
            <body style="margin:0; padding:0; background-color:#f3f4f6;">
                <div style="max-width:640px; margin:0 auto; padding:32px 16px;">
                    <div style="background-color:#ffffff; border-radius:16px; padding:32px; font-family:Arial,sans-serif; color:#111827;">
                        <h1 style="font-size:24px;">Verify your LitBlog email</h1>
                        <p style="font-size:16px; line-height:1.6;">
                            Confirm your school email to finish setting up your account.
                            This link expires in <strong>24 hours</strong>.
                        </p>
                        <p style="text-align:center; margin:24px 0;">
                            <a href="{verification_url}" style="display:inline-block; background-color:#4F46E5; color:#ffffff; text-decoration:none; padding:12px 24px; border-radius:999px; font-weight:600;">Verify Email</a>
                        </p>
                        <p style="font-size:14px; color:#6b7280;">
                            If you did not create a LitBlog account, ignore this email.
                        </p>
                        <div style="word-break:break-all; font-size:12px; color:#6b7280;">
                            {verification_url}
                        </div>
                    </div>
                </div>
            </body>
        </html>
    """
    message.attach(MIMEText(html, "html"))
    return auth_email_delivery.send_smtp_message(settings, email, message)


def dispatch_email_verification_batch(
    *,
    batch_size: int,
    claim: Callable[[], tuple[int, str, str] | None],
    send: Callable[[str, str], bool],
    complete: Callable[
        [int, str, str, bool], EmailVerificationCompletionOutcome | bool
    ],
) -> EmailVerificationDispatchOutcome:
    if (
        not isinstance(batch_size, int)
        or isinstance(batch_size, bool)
        or not 1 <= batch_size <= MAX_EMAIL_VERIFICATION_BATCH_SIZE
    ):
        raise ValueError("email-verification batch size is outside the safe bound")

    def completion_succeeded(
        completion: EmailVerificationCompletionOutcome | bool,
    ) -> bool:
        if completion is True:
            return True
        if completion is False:
            return False
        if not isinstance(completion, EmailVerificationCompletionOutcome):
            raise EmailVerificationOperationalError(
                "Email-verification completion operation failed"
            )
        return completion is EmailVerificationCompletionOutcome.COMPLETED

    return auth_email_delivery.dispatch_auth_email_batch(
        batch_size=batch_size,
        claim=claim,
        send=send,
        complete=complete,
        completion_succeeded=completion_succeeded,
    )


def dispatch_email_verification_batch_once(
    *,
    session_factory: Callable[[], Session],
    email_settings: EmailVerificationEmailSettings,
    claim_timeout_seconds: int,
    batch_size: int = 100,
) -> EmailVerificationDispatchOutcome:
    return dispatch_email_verification_batch(
        batch_size=batch_size,
        claim=lambda: claim_email_verification_delivery(
            session_factory,
            claim_timeout_seconds=claim_timeout_seconds,
        ),
        send=lambda email, token: send_email_verification_email(
            email_settings,
            email,
            token,
        ),
        complete=lambda verification_id, claim_nonce, raw_token, delivered: (
            complete_email_verification_delivery_outcome(
                session_factory,
                verification_id,
                claim_nonce,
                raw_token,
                delivered,
            )
        ),
    )


def dispatch_email_verification_emails_once(
    batch_size: int = 100,
) -> EmailVerificationDispatchOutcome:
    settings = auth_email_delivery.load_auth_email_worker_settings()
    engine = auth_email_delivery.create_auth_email_engine(settings)
    try:
        auth_email_delivery.check_auth_email_database_readiness(engine)
        return dispatch_email_verification_batch_once(
            session_factory=(
                auth_email_delivery.create_auth_email_session_factory(engine)
            ),
            email_settings=(
                auth_email_delivery.auth_email_settings_from_worker(settings)
            ),
            claim_timeout_seconds=settings.password_reset_claim_timeout_seconds,
            batch_size=batch_size,
        )
    finally:
        engine.dispose()
