"""Standalone, bounded password-reset delivery runtime."""

from __future__ import annotations

import hashlib
import secrets
import smtplib
import ssl
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import UTC, datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from enum import StrEnum
from pathlib import Path

from pydantic import EmailStr, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import and_, create_engine, or_, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

import models
from config import (
    _PLACEHOLDER_FRAGMENTS,
    _canonical_https_origin,
    _is_network_host,
    _is_verified_postgresql_url,
)
from identity_controls import invalidate_password_reset_requests
from runtime_database_identity import verify_runtime_database_identity

APP_DIRECTORY = Path(__file__).resolve().parent
EXPECTED_ALEMBIC_HEAD = "f1ad78b2035f"
MAX_PASSWORD_RESET_BATCH_SIZE = 100

PASSWORD_RESET_PENDING = "PENDING"
PASSWORD_RESET_PROCESSING = "PROCESSING"
PASSWORD_RESET_DELIVERED = "DELIVERED"
PASSWORD_RESET_FAILED = "FAILED"
PASSWORD_RESET_LIFETIME = timedelta(hours=1)


class PasswordResetOperationalError(RuntimeError):
    """A sanitized reset-delivery infrastructure failure."""


class PasswordResetCompletionOutcome(StrEnum):
    COMPLETED = "COMPLETED"
    ACCOUNT_DISABLED = "ACCOUNT_DISABLED"
    CLAIM_LOST = "CLAIM_LOST"


class PasswordResetDispatchOutcome(StrEnum):
    EMPTY_QUEUE = "EMPTY_QUEUE"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class PasswordResetWorkerSettings(BaseSettings):
    """Only the settings required by the external reset-delivery process."""

    model_config = SettingsConfigDict(
        case_sensitive=False,
        enable_decoding=False,
        extra="ignore",
        frozen=True,
        hide_input_in_errors=True,
    )

    database_url: str = Field(repr=False)
    db_pool_size: int = Field(default=1, ge=1, le=20)
    db_max_overflow: int = Field(default=0, ge=0, le=20)
    db_pool_timeout_seconds: int = Field(default=10, ge=1, le=30)
    db_pool_recycle_seconds: int = Field(default=900, ge=60, le=3_600)
    db_connect_timeout_seconds: int = Field(default=5, ge=1, le=10)
    db_statement_timeout_ms: int = Field(default=15_000, ge=1_000, le=60_000)
    db_lock_timeout_ms: int = Field(default=5_000, ge=500, le=30_000)

    frontend_url: str
    email_host: str
    email_port: int = Field(default=587, ge=1, le=65_535)
    email_smtp_timeout_seconds: float = Field(default=5.0, ge=0.5, le=10.0)
    email_username: str
    email_password: SecretStr = Field(repr=False)
    email_from: EmailStr
    password_reset_claim_timeout_seconds: int = Field(default=120, ge=60, le=600)

    @field_validator(
        "database_url",
        "frontend_url",
        "email_host",
        "email_username",
        mode="before",
    )
    @classmethod
    def strip_required_text(cls, value):
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("worker setting must be nonempty")
        return normalized

    @field_validator("frontend_url")
    @classmethod
    def canonicalize_frontend_origin(cls, value: str) -> str:
        canonical = _canonical_https_origin(value)
        if canonical is None:
            raise ValueError("FRONTEND_URL must be a root HTTPS origin")
        return canonical

    @model_validator(mode="after")
    def validate_delivery_boundary(self):
        if not _is_verified_postgresql_url(self.database_url):
            raise ValueError("DATABASE_URL must be a verified PostgreSQL URL")
        database_user = make_url(self.database_url).username
        if database_user != "litblogs_runtime":
            raise ValueError("DATABASE_URL must use the litblogs_runtime role")
        if not _is_network_host(self.email_host):
            raise ValueError("EMAIL_HOST must be an exact network host")
        email_from_domain = str(self.email_from).rsplit("@", 1)[-1]
        if not _is_network_host(email_from_domain):
            raise ValueError("EMAIL_FROM must use a non-reserved DNS domain")
        smtp_password = self.email_password.get_secret_value()
        if len(smtp_password.encode("utf-8")) < 16 or any(
            fragment in smtp_password.lower() for fragment in _PLACEHOLDER_FRAGMENTS
        ):
            raise ValueError("EMAIL_PASSWORD must be a non-placeholder secret")
        return self


@dataclass(frozen=True)
class PasswordResetEmailSettings:
    frontend_url: str
    email_host: str | None
    email_port: int
    email_smtp_timeout_seconds: float
    email_username: str | None
    email_password: str | None = dataclass_field(repr=False)
    email_from: str | None


def load_password_reset_worker_settings() -> PasswordResetWorkerSettings:
    """Load the worker environment without loading the web Settings object."""

    return PasswordResetWorkerSettings(_env_file=None)


def worker_engine_options(settings: PasswordResetWorkerSettings) -> dict:
    return {
        "pool_pre_ping": True,
        "pool_size": settings.db_pool_size,
        "max_overflow": settings.db_max_overflow,
        "pool_timeout": settings.db_pool_timeout_seconds,
        "pool_recycle": settings.db_pool_recycle_seconds,
        "connect_args": {
            "connect_timeout": settings.db_connect_timeout_seconds,
            "application_name": "litblogs-password-reset",
            "options": (
                f"-c statement_timeout={settings.db_statement_timeout_ms} "
                f"-c lock_timeout={settings.db_lock_timeout_ms}"
            ),
        },
    }


def create_password_reset_engine(settings: PasswordResetWorkerSettings) -> Engine:
    return create_engine(settings.database_url, **worker_engine_options(settings))


def check_password_reset_database_readiness(engine: Engine) -> None:
    if engine.dialect.name != "postgresql":
        raise RuntimeError("Password-reset delivery requires PostgreSQL")
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
        current_revision = connection.execute(
            text("SELECT version_num FROM public.alembic_version")
        ).scalar_one()
        if current_revision != EXPECTED_ALEMBIC_HEAD:
            raise RuntimeError("Database migration revision is not current")
        verify_runtime_database_identity(connection)


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
            if user.disabled_at is not None:
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
        if user.disabled_at is not None:
            invalidate_password_reset_requests(db, user_id=user.id)
            db.commit()
            return PasswordResetCompletionOutcome.ACCOUNT_DISABLED

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

    try:
        with smtplib.SMTP(
            settings.email_host,
            settings.email_port,
            timeout=settings.email_smtp_timeout_seconds,
        ) as server:
            server.starttls(context=ssl.create_default_context())
            server.login(settings.email_username, settings.email_password)
            server.sendmail(settings.email_from, email, message.as_string())
        return True
    except Exception:
        return False


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
    completed_deliveries = 0
    for _ in range(batch_size):
        try:
            claimed = claim()
        except Exception:
            raise PasswordResetOperationalError(
                "Password-reset claim operation failed"
            ) from None
        if claimed is None:
            if completed_deliveries:
                return PasswordResetDispatchOutcome.COMPLETED
            return PasswordResetDispatchOutcome.EMPTY_QUEUE
        reset_id, email, claim_nonce = claimed
        raw_token = secrets.token_urlsafe(32)
        try:
            delivered = send(email, raw_token) is True
        except Exception:
            delivered = False
        try:
            completion = complete(
                reset_id,
                claim_nonce,
                raw_token,
                delivered,
            )
        except Exception:
            raise PasswordResetOperationalError(
                "Password-reset completion operation failed"
            ) from None

        if completion is True:
            completion = PasswordResetCompletionOutcome.COMPLETED
        elif completion is False:
            completion = PasswordResetCompletionOutcome.CLAIM_LOST
        if not isinstance(completion, PasswordResetCompletionOutcome):
            raise PasswordResetOperationalError(
                "Password-reset completion operation failed"
            )
        if not delivered or completion is not PasswordResetCompletionOutcome.COMPLETED:
            return PasswordResetDispatchOutcome.FAILED
        completed_deliveries += 1
    return PasswordResetDispatchOutcome.COMPLETED


def dispatch_password_reset_emails_once(
    batch_size: int = 100,
) -> PasswordResetDispatchOutcome:
    settings = load_password_reset_worker_settings()
    engine = create_password_reset_engine(settings)
    try:
        check_password_reset_database_readiness(engine)
        session_factory = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=engine,
        )
        email_settings = PasswordResetEmailSettings(
            frontend_url=settings.frontend_url,
            email_host=settings.email_host,
            email_port=settings.email_port,
            email_smtp_timeout_seconds=settings.email_smtp_timeout_seconds,
            email_username=settings.email_username,
            email_password=settings.email_password.get_secret_value(),
            email_from=str(settings.email_from),
        )
        return dispatch_password_reset_batch(
            batch_size=batch_size,
            claim=lambda: claim_password_reset_delivery(
                session_factory,
                claim_timeout_seconds=settings.password_reset_claim_timeout_seconds,
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
    finally:
        engine.dispose()
