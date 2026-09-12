"""Neutral, bounded infrastructure for isolated authentication-email workers."""

from __future__ import annotations

import secrets
import smtplib
import ssl
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from email.message import Message
from enum import StrEnum
from pathlib import Path
from typing import TypeVar

from pydantic import EmailStr, Field, SecretStr, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from config import (
    _PLACEHOLDER_FRAGMENTS,
    _canonical_https_frontend_url,
    _is_network_host,
    _is_verified_postgresql_url,
    validate_app_base_path,
)
from runtime_database_identity import verify_runtime_database_identity

APP_DIRECTORY = Path(__file__).resolve().parent
EXPECTED_ALEMBIC_HEAD = "a82f8f2b1d7c"
MAX_AUTH_EMAIL_BATCH_SIZE = 100

Claim = tuple[int, str, str]
CompletionT = TypeVar("CompletionT")


class AuthEmailOperationalError(RuntimeError):
    """A sanitized authentication-email infrastructure failure."""


class AuthEmailDispatchOutcome(StrEnum):
    EMPTY_QUEUE = "EMPTY_QUEUE"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class AuthEmailWorkerSettings(BaseSettings):
    """Only settings shared by reset and verification delivery."""

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

    app_base_path: str = ""
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

    @field_validator("app_base_path", mode="before")
    @classmethod
    def validate_base_path(cls, value) -> str:
        return validate_app_base_path(value)

    @field_validator("frontend_url")
    @classmethod
    def canonicalize_frontend_url(cls, value: str, info: ValidationInfo) -> str:
        base_path = info.data.get("app_base_path", "")
        canonical = _canonical_https_frontend_url(value, base_path)
        if canonical is None:
            if base_path:
                raise ValueError("FRONTEND_URL must use HTTPS with its path equal to APP_BASE_PATH")
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
class AuthEmailSettings:
    frontend_url: str
    email_host: str | None
    email_port: int
    email_smtp_timeout_seconds: float
    email_username: str | None
    email_password: str | None = dataclass_field(repr=False)
    email_from: str | None


def load_auth_email_worker_settings() -> AuthEmailWorkerSettings:
    """Load the isolated worker environment without web settings."""

    return AuthEmailWorkerSettings(_env_file=None)


def auth_email_engine_options(settings: AuthEmailWorkerSettings) -> dict:
    return {
        "pool_pre_ping": True,
        "pool_size": settings.db_pool_size,
        "max_overflow": settings.db_max_overflow,
        "pool_timeout": settings.db_pool_timeout_seconds,
        "pool_recycle": settings.db_pool_recycle_seconds,
        "connect_args": {
            "connect_timeout": settings.db_connect_timeout_seconds,
            "application_name": "litblogs-auth-email",
            "options": (
                f"-c statement_timeout={settings.db_statement_timeout_ms} "
                f"-c lock_timeout={settings.db_lock_timeout_ms}"
            ),
        },
    }


def create_auth_email_engine(settings: AuthEmailWorkerSettings) -> Engine:
    try:
        return create_engine(
            settings.database_url,
            **auth_email_engine_options(settings),
        )
    except Exception:
        raise AuthEmailOperationalError(
            "Authentication-email engine creation failed"
        ) from None


def check_auth_email_database_readiness(engine: Engine) -> None:
    try:
        if engine.dialect.name != "postgresql":
            raise AuthEmailOperationalError(
                "Authentication-email delivery requires PostgreSQL"
            )
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            current_revision = connection.execute(
                text("SELECT version_num FROM public.alembic_version")
            ).scalar_one()
            if current_revision != EXPECTED_ALEMBIC_HEAD:
                raise AuthEmailOperationalError(
                    "Database migration revision is not current"
                )
            verify_runtime_database_identity(connection)
    except AuthEmailOperationalError:
        raise
    except Exception:
        raise AuthEmailOperationalError(
            "Authentication-email database readiness failed"
        ) from None


def create_auth_email_session_factory(engine: Engine) -> Callable[[], Session]:
    return sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )


def auth_email_settings_from_worker(
    settings: AuthEmailWorkerSettings,
) -> AuthEmailSettings:
    return AuthEmailSettings(
        frontend_url=settings.frontend_url,
        email_host=settings.email_host,
        email_port=settings.email_port,
        email_smtp_timeout_seconds=settings.email_smtp_timeout_seconds,
        email_username=settings.email_username,
        email_password=settings.email_password.get_secret_value(),
        email_from=str(settings.email_from),
    )


def send_smtp_message(
    settings: AuthEmailSettings,
    recipient: str,
    message: Message,
) -> bool:
    if not all(
        (
            settings.email_host,
            settings.email_username,
            settings.email_password,
            settings.email_from,
        )
    ):
        return False
    try:
        with smtplib.SMTP(
            settings.email_host,
            settings.email_port,
            timeout=settings.email_smtp_timeout_seconds,
        ) as server:
            server.starttls(context=ssl.create_default_context())
            server.login(settings.email_username, settings.email_password)
            server.sendmail(
                settings.email_from,
                recipient,
                message.as_string(),
            )
        return True
    except Exception:
        return False


def dispatch_auth_email_batch(
    *,
    batch_size: int,
    claim: Callable[[], Claim | None],
    send: Callable[[str, str], bool],
    complete: Callable[[int, str, str, bool], CompletionT],
    completion_succeeded: Callable[[CompletionT], bool],
) -> AuthEmailDispatchOutcome:
    """Dispatch one bounded batch without owning any domain state."""

    if (
        not isinstance(batch_size, int)
        or isinstance(batch_size, bool)
        or not 1 <= batch_size <= MAX_AUTH_EMAIL_BATCH_SIZE
    ):
        raise ValueError("authentication-email batch size is outside the safe bound")

    completed_deliveries = 0
    for _ in range(batch_size):
        try:
            claimed = claim()
        except Exception:
            raise AuthEmailOperationalError(
                "Authentication-email claim operation failed"
            ) from None
        if claimed is None:
            if completed_deliveries:
                return AuthEmailDispatchOutcome.COMPLETED
            return AuthEmailDispatchOutcome.EMPTY_QUEUE

        record_id, recipient, claim_nonce = claimed
        raw_token = secrets.token_urlsafe(32)
        try:
            delivered = send(recipient, raw_token) is True
        except Exception:
            delivered = False
        try:
            completion = complete(
                record_id,
                claim_nonce,
                raw_token,
                delivered,
            )
            completed = completion_succeeded(completion) is True
        except Exception:
            raise AuthEmailOperationalError(
                "Authentication-email completion operation failed"
            ) from None
        if not delivered or not completed:
            return AuthEmailDispatchOutcome.FAILED
        completed_deliveries += 1
    return AuthEmailDispatchOutcome.COMPLETED
