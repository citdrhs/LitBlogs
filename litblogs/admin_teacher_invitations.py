"""Browser administrator invitations using only the application database role."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import DateTime, bindparam, select, text, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

import models
from config import Settings
from identity_controls import invitation_email_digest, normalize_email, record_operator_audit_event
from schemas import TeacherInvitationResponse

INVITATION_LIFETIME = timedelta(hours=48)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _lock_active_admin_session(db: Session, *, actor_id: int, session_id: int | None) -> None:
    # Match account-disable lock ordering. Select columns to bypass the ORM's
    # cached authentication object, and retain both locks until invitation commit.
    actor = db.execute(
        select(models.User.role, models.User.disabled_at, models.User.email_verified_at)
        .where(models.User.id == actor_id)
        .with_for_update()
    ).one_or_none()
    if actor is None or actor.disabled_at is not None or actor.email_verified_at is None:
        raise HTTPException(status_code=401, detail="Could not validate credentials")
    if actor.role != models.UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Administrator access required")
    session = db.execute(
        select(models.BrowserSession.expires_at, models.BrowserSession.revoked_at)
        .where(models.BrowserSession.id == session_id, models.BrowserSession.user_id == actor_id)
        .with_for_update()
    ).one_or_none()
    if session is None or session.revoked_at is not None or _aware(session.expires_at) <= datetime.now(UTC):
        raise HTTPException(status_code=401, detail="Could not validate credentials")


def issue_admin_teacher_invitation(
    db: Session, *, actor_id: int, session_id: int | None, email: str, settings: Settings,
) -> TeacherInvitationResponse:
    """Commit an email-bound replacement and audit record, returning its code once."""
    try:
        _lock_active_admin_session(db, actor_id=actor_id, session_id=session_id)
        try:
            normalized_email = normalize_email(email)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="A valid school email address is required") from None
        existing = db.execute(select(models.User.id).where(models.User.email == normalized_email)).first()
        if existing is not None:
            raise HTTPException(status_code=409, detail="An account already exists for this email address")
        if settings.allowed_email_domains and normalized_email.rsplit("@", 1)[-1] not in settings.allowed_email_domains:
            raise HTTPException(status_code=400, detail="Use an allowed school email address")

        now = datetime.now(UTC)
        expiry = now + INVITATION_LIFETIME
        digest = invitation_email_digest(normalized_email, settings=settings)
        actor = f"admin-user:{actor_id}"
        db.execute(
            update(models.TeacherInvitation)
            .where(
                models.TeacherInvitation.email_digest == digest,
                models.TeacherInvitation.consumed_at.is_(None),
                models.TeacherInvitation.revoked_at.is_(None),
            )
            .values(revoked_at=now)
            .execution_options(synchronize_session=False)
        )
        # A signup may have consumed the old code while this UPDATE waited.
        # Under READ COMMITTED, recheck its newly committed account now.
        existing = db.execute(select(models.User.id).where(models.User.email == normalized_email)).first()
        if existing is not None:
            raise HTTPException(status_code=409, detail="An account already exists for this email address")
        token = secrets.token_urlsafe(32)
        # Explicit columns avoid ORM Python defaults exceeding the narrow grant.
        if db.get_bind().dialect.name == "postgresql":
            statement = (
                "INSERT INTO public.teacher_invitations (token_digest, email_digest, expires_at, created_by) "
                "VALUES (:token_digest, :email_digest, :expires_at, :created_by)"
            )
        else:
            statement = (
                "INSERT INTO teacher_invitations (token_digest, email_digest, expires_at, created_by) "
                "VALUES (:token_digest, :email_digest, :expires_at, :created_by)"
            )
        db.execute(
            text(statement).bindparams(bindparam("expires_at", type_=DateTime(timezone=True))),
            {"token_digest": hashlib.sha256(token.encode("utf-8")).hexdigest(),
             "email_digest": digest, "expires_at": expiry, "created_by": actor},
        )
        record_operator_audit_event(
            db, actor_identifier=actor, action="TEACHER_INVITATION_CREATED", outcome="SUCCEEDED",
            resource_email=normalized_email, settings=settings,
        )
        db.commit()
        return TeacherInvitationResponse(email=normalized_email, invitation_token=token, expires_at=expiry)
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError:
        # Concurrent administrators may race the partial unique email index.
        # Roll back revocation too, retaining the other transaction's valid code.
        db.rollback()
        raise HTTPException(status_code=409, detail="An invitation changed concurrently; try again") from None
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=503, detail="Invitation could not be created; try again") from None
