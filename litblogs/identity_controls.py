import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, select, text, update
from sqlalchemy.orm import Session

import models
from auth_security import decode_access_token, issue_access_token
from config import Settings, get_settings

__all__ = [
    "IssuedBrowserSession",
    "MAX_BROWSER_SESSIONS_PER_USER",
    "SessionIssuanceDenied",
    "consume_teacher_invitation",
    "create_teacher_invitation",
    "delete_expired_sessions",
    "find_active_browser_session",
    "get_settings",
    "invalidate_password_reset_requests",
    "invitation_email_digest",
    "issue_browser_session",
    "normalize_email",
    "operator_audit_resource_digest",
    "record_operator_audit_event",
    "revoke_all_sessions",
    "revoke_session",
    "revoke_teacher_invitation",
    "utc_now",
    "validate_operator_identifier",
]

INVITATION_EMAIL_DOMAIN = b"litblog:teacher-invite-email:v1\0"
OPERATOR_AUDIT_EMAIL_DOMAIN = b"litblog:operator-audit-email:v1\0"
MAX_INVITATION_TOKEN_LENGTH = 512
MAX_EMAIL_LENGTH = 100
MAX_OPERATOR_IDENTIFIER_LENGTH = 100
MAX_SESSION_CLEANUP_BATCH = 1_000
MAX_BROWSER_SESSIONS_PER_USER = 10
OPERATOR_AUDIT_ACTIONS = frozenset(
    {
        "TEACHER_INVITATION_CREATED",
        "TEACHER_INVITATION_REVOKED",
        "ACCOUNT_DISABLED",
        "ACCOUNT_ENABLED",
    }
)
OPERATOR_AUDIT_OUTCOMES = frozenset({"SUCCEEDED", "NOT_FOUND", "CONFLICT"})
_OPERATOR_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@/-]{0,99}")


@dataclass(frozen=True)
class IssuedBrowserSession:
    token: str
    expires_at: datetime


class SessionIssuanceDenied(RuntimeError):
    """The account changed after the authentication check began."""


def utc_now() -> datetime:
    return datetime.now(UTC)


def issue_browser_session(
    db: Session,
    *,
    user_id: int,
    settings: Settings,
    expected_password_hash: str | None = None,
) -> IssuedBrowserSession:
    now = utc_now()
    account_filters = [
        models.User.id == user_id,
        models.User.disabled_at.is_(None),
    ]
    if expected_password_hash is not None:
        account_filters.append(models.User.password == expected_password_hash)
    locked_user_id = db.scalar(
        select(models.User.id).where(*account_filters).with_for_update()
    )
    if locked_user_id is None:
        raise SessionIssuanceDenied("account state changed")
    delete_expired_sessions(db, now=now)
    _prune_user_sessions_for_new_issue(db, user_id=user_id)
    token = issue_access_token(user_id, settings=settings, now=now)
    payload = decode_access_token(token, settings=settings)
    expires_at = datetime.fromtimestamp(payload["exp"], UTC)
    db.add(
        models.BrowserSession(
            jti_digest=_sha256_text(payload["jti"]),
            user_id=user_id,
            expires_at=expires_at,
        )
    )
    db.flush()
    return IssuedBrowserSession(token=token, expires_at=expires_at)


def _prune_user_sessions_for_new_issue(db: Session, *, user_id: int) -> int:
    oldest_ids = list(
        db.scalars(
            select(models.BrowserSession.id)
            .where(models.BrowserSession.user_id == user_id)
            .order_by(
                models.BrowserSession.created_at.desc(),
                models.BrowserSession.id.desc(),
            )
            .offset(MAX_BROWSER_SESSIONS_PER_USER - 1)
        )
    )
    if not oldest_ids:
        return 0
    result = db.execute(
        delete(models.BrowserSession)
        .where(models.BrowserSession.id.in_(oldest_ids))
        .execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0)


def find_active_browser_session(
    db: Session,
    *,
    user_id: int,
    jti: str,
    now: datetime | None = None,
) -> models.BrowserSession | None:
    if not isinstance(jti, str) or not jti:
        return None
    current_time = _aware_utc(now or utc_now())
    return (
        db.query(models.BrowserSession)
        .filter(
            models.BrowserSession.jti_digest == _sha256_text(jti),
            models.BrowserSession.user_id == user_id,
            models.BrowserSession.revoked_at.is_(None),
            models.BrowserSession.expires_at > current_time,
        )
        .first()
    )


def revoke_session(
    db: Session,
    *,
    session_id: int,
    now: datetime | None = None,
) -> bool:
    current_time = _aware_utc(now or utc_now())
    result = db.execute(
        update(models.BrowserSession)
        .where(
            models.BrowserSession.id == session_id,
            models.BrowserSession.revoked_at.is_(None),
            models.BrowserSession.expires_at > current_time,
        )
        .values(revoked_at=current_time)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


def revoke_all_sessions(
    db: Session,
    *,
    user_id: int,
    now: datetime | None = None,
) -> int:
    current_time = _aware_utc(now or utc_now())
    result = db.execute(
        update(models.BrowserSession)
        .where(
            models.BrowserSession.user_id == user_id,
            models.BrowserSession.revoked_at.is_(None),
            models.BrowserSession.expires_at > current_time,
        )
        .values(revoked_at=current_time)
        .execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0)


def invalidate_password_reset_requests(
    db: Session,
    *,
    user_id: int,
    now: datetime | None = None,
) -> int:
    """Make every reset/outbox row for an account permanently unusable."""
    current_time = _aware_utc(now or utc_now())
    result = db.execute(
        update(models.PasswordReset)
        .where(models.PasswordReset.user_id == user_id)
        .values(
            token=None,
            expires_at=None,
            used=True,
            delivery_status="FAILED",
            delivery_attempted_at=current_time,
            delivery_claim_digest=None,
        )
        .execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0)


def delete_expired_sessions(
    db: Session,
    *,
    now: datetime | None = None,
    limit: int = 500,
) -> int:
    if not isinstance(limit, int) or isinstance(limit, bool):
        raise TypeError("session cleanup limit must be an integer")
    if limit < 1 or limit > MAX_SESSION_CLEANUP_BATCH:
        raise ValueError(
            f"session cleanup limit must be between 1 and {MAX_SESSION_CLEANUP_BATCH}"
        )
    current_time = _aware_utc(now or utc_now())
    expired_ids = list(
        db.scalars(
            select(models.BrowserSession.id)
            .where(models.BrowserSession.expires_at <= current_time)
            .order_by(
                models.BrowserSession.expires_at,
                models.BrowserSession.id,
            )
            .limit(limit)
        )
    )
    if not expired_ids:
        return 0
    result = db.execute(
        delete(models.BrowserSession)
        .where(models.BrowserSession.id.in_(expired_ids))
        .execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0)


def normalize_email(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("email must be a string")
    # U+0020 is the only legacy padding character we normalize. Every ASCII
    # control byte (C0 plus DEL) and remaining space is rejected so this
    # exactly matches the PostgreSQL btrim/lower/control checks.
    normalized = value.strip(" ")
    if not normalized or len(normalized) > MAX_EMAIL_LENGTH:
        raise ValueError("email is invalid")
    if not normalized.isascii():
        raise ValueError("email must use ASCII characters")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in normalized):
        raise ValueError("email must not contain control characters")
    if " " in normalized:
        raise ValueError("email must not contain whitespace")
    return normalized.lower()


def invitation_email_digest(email: str, *, settings: Settings) -> str:
    return _keyed_email_digest(
        email,
        settings=settings,
        domain=INVITATION_EMAIL_DOMAIN,
    )


def operator_audit_resource_digest(email: str, *, settings: Settings) -> str:
    return _keyed_email_digest(
        email,
        settings=settings,
        domain=OPERATOR_AUDIT_EMAIL_DOMAIN,
    )


def _keyed_email_digest(
    email: str,
    *,
    settings: Settings,
    domain: bytes,
) -> str:
    invitation_key = settings.teacher_invite_hmac_key
    if invitation_key is None:
        raise RuntimeError("TEACHER_INVITE_HMAC_KEY is required")
    return hmac.new(
        invitation_key.get_secret_value().encode("utf-8"),
        domain + normalize_email(email).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def record_operator_audit_event(
    db: Session,
    *,
    actor_identifier: str,
    action: str,
    outcome: str,
    resource_email: str,
    settings: Settings,
) -> None:
    actor = validate_operator_identifier(actor_identifier)
    if action not in OPERATOR_AUDIT_ACTIONS:
        raise ValueError("operator audit action is invalid")
    if outcome not in OPERATOR_AUDIT_OUTCOMES:
        raise ValueError("operator audit outcome is invalid")
    dialect_name = db.get_bind().dialect.name
    if dialect_name == "postgresql":
        audit_insert = text(
            "INSERT INTO public.operator_audit_events "
            "(actor_identifier, action, outcome, resource_digest) "
            "VALUES (:actor_identifier, :action, :outcome, :resource_digest)"
        )
    elif dialect_name == "sqlite":
        audit_insert = text(
            "INSERT INTO operator_audit_events "
            "(actor_identifier, action, outcome, resource_digest) "
            "VALUES (:actor_identifier, :action, :outcome, :resource_digest)"
        )
    else:
        raise RuntimeError("unsupported database dialect for operator auditing")
    db.execute(
        audit_insert,
        {
            "actor_identifier": actor,
            "action": action,
            "outcome": outcome,
            "resource_digest": operator_audit_resource_digest(
                resource_email,
                settings=settings,
            ),
        },
    )


def create_teacher_invitation(
    db: Session,
    *,
    email: str,
    created_by: str,
    expires_at: datetime,
    settings: Settings,
    now: datetime | None = None,
) -> str:
    current_time = _aware_utc(now or utc_now())
    normalized_expires_at = _aware_utc(expires_at)
    if normalized_expires_at <= current_time:
        raise ValueError("invitation expiry must be in the future")
    operator = validate_operator_identifier(created_by)
    email_digest = invitation_email_digest(email, settings=settings)

    db.execute(
        update(models.TeacherInvitation)
        .where(
            models.TeacherInvitation.email_digest == email_digest,
            models.TeacherInvitation.consumed_at.is_(None),
            models.TeacherInvitation.revoked_at.is_(None),
            models.TeacherInvitation.expires_at <= current_time,
        )
        .values(revoked_at=current_time)
        .execution_options(synchronize_session=False)
    )

    token = secrets.token_urlsafe(32)
    db.add(
        models.TeacherInvitation(
            token_digest=_sha256_text(token),
            email_digest=email_digest,
            expires_at=normalized_expires_at,
            created_by=operator,
        )
    )
    db.flush()
    return token


def consume_teacher_invitation(
    db: Session,
    *,
    token: str,
    email: str,
    settings: Settings,
    now: datetime | None = None,
) -> bool:
    if (
        not isinstance(token, str)
        or not token
        or len(token) > MAX_INVITATION_TOKEN_LENGTH
    ):
        return False
    try:
        email_digest = invitation_email_digest(email, settings=settings)
    except (TypeError, ValueError):
        return False
    current_time = _aware_utc(now or utc_now())
    invitation_id = db.execute(
        update(models.TeacherInvitation)
        .where(
            models.TeacherInvitation.token_digest == _sha256_text(token),
            models.TeacherInvitation.email_digest == email_digest,
            models.TeacherInvitation.expires_at > current_time,
            models.TeacherInvitation.consumed_at.is_(None),
            models.TeacherInvitation.revoked_at.is_(None),
        )
        .values(consumed_at=current_time)
        .returning(models.TeacherInvitation.id)
        .execution_options(synchronize_session=False)
    ).scalar_one_or_none()
    return invitation_id is not None


def revoke_teacher_invitation(
    db: Session,
    *,
    email: str,
    settings: Settings,
    now: datetime | None = None,
) -> bool:
    try:
        email_digest = invitation_email_digest(email, settings=settings)
    except (TypeError, ValueError):
        return False
    current_time = _aware_utc(now or utc_now())
    invitation_id = db.execute(
        update(models.TeacherInvitation)
        .where(
            models.TeacherInvitation.email_digest == email_digest,
            models.TeacherInvitation.consumed_at.is_(None),
            models.TeacherInvitation.revoked_at.is_(None),
        )
        .values(revoked_at=current_time)
        .returning(models.TeacherInvitation.id)
        .execution_options(synchronize_session=False)
    ).scalar_one_or_none()
    return invitation_id is not None


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def validate_operator_identifier(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("operator identifier must be a string")
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > MAX_OPERATOR_IDENTIFIER_LENGTH
        or _OPERATOR_IDENTIFIER_PATTERN.fullmatch(normalized) is None
    ):
        raise ValueError("operator identifier is invalid")
    return normalized


def _aware_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)
