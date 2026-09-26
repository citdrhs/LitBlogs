"""Delete an empty account without cascading into another person's schoolwork."""

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

import models
from config import Settings
from identity_controls import invitation_email_digest, normalize_email, record_operator_audit_event


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def delete_admin_account(
    db: Session, *, actor_id: int, session_id: int | None, target_user_id: int,
    confirmation_email: str, settings: Settings,
) -> None:
    """Atomically remove authentication data and an otherwise empty account."""
    try:
        # Every account lifecycle operation locks User before its children.
        # Stable ordering also serializes two administrators targeting each other.
        users = db.execute(
            select(models.User.id, models.User.email, models.User.role,
                   models.User.disabled_at, models.User.email_verified_at)
            .where(models.User.id.in_(sorted({actor_id, target_user_id})))
            .order_by(models.User.id)
            .with_for_update()
        ).all()
        by_id = {user.id: user for user in users}
        actor = by_id.get(actor_id)
        if actor is None or actor.disabled_at is not None or actor.email_verified_at is None:
            raise HTTPException(status_code=401, detail="Could not validate credentials")
        if actor.role != models.UserRole.ADMIN:
            raise HTTPException(status_code=403, detail="Administrator access required")
        session = db.execute(
            select(models.BrowserSession.revoked_at, models.BrowserSession.expires_at)
            .where(models.BrowserSession.id == session_id, models.BrowserSession.user_id == actor_id)
            .with_for_update()
        ).one_or_none()
        if session is None or session.revoked_at is not None or _aware(session.expires_at) <= datetime.now(UTC):
            raise HTTPException(status_code=401, detail="Could not validate credentials")
        target = by_id.get(target_user_id)
        if target is None:
            raise HTTPException(status_code=404, detail="User not found")
        if target_user_id == actor_id:
            raise HTTPException(status_code=409, detail="Administrators cannot delete their current account")
        if target.role == models.UserRole.ADMIN:
            active_admins = db.scalar(select(func.count(models.User.id)).where(
                models.User.role == models.UserRole.ADMIN, models.User.disabled_at.is_(None),
                models.User.email_verified_at.is_not(None),
            ))
            if active_admins <= 1 and target.disabled_at is None and target.email_verified_at is not None:
                raise HTTPException(status_code=409, detail="The last active administrator cannot be deleted")
        try:
            valid_confirmation = normalize_email(confirmation_email) == confirmation_email == target.email
        except (TypeError, ValueError):
            valid_confirmation = False
        if not valid_confirmation:
            raise HTTPException(status_code=400, detail="Confirmation must exactly match the account email")

        # Do not infer teacher associations from the current account role.
        # Locking this parent prevents a concurrent class from acquiring its FK.
        teacher_ids = list(db.scalars(
            select(models.Teacher.id).where(models.Teacher.user_id == target_user_id)
            .order_by(models.Teacher.id).with_for_update()
        ))
        dependencies = (
            (models.Class, models.Class.teacher_id.in_(teacher_ids)),
            (models.Assignment, models.Assignment.created_by == target_user_id),
            (models.Blog, models.Blog.owner_id == target_user_id),
            (models.AssignmentSubmission, models.AssignmentSubmission.student_id == target_user_id),
            (models.AssignmentDraft, models.AssignmentDraft.student_id == target_user_id),
            (models.ClassEnrollment, models.ClassEnrollment.student_id == target_user_id),
            (models.Comment, models.Comment.user_id == target_user_id),
            (models.AssignmentSubmissionReply, models.AssignmentSubmissionReply.user_id == target_user_id),
            (models.UploadAsset, models.UploadAsset.owner_user_id == target_user_id),
        )
        if any(db.scalar(select(model.id).where(condition).limit(1)) is not None
               for model, condition in dependencies):
            raise HTTPException(status_code=409, detail="This account has schoolwork or uploads; preserve or transfer them before deleting it")

        now = datetime.now(UTC)
        db.execute(
            update(models.TeacherInvitation).where(
                models.TeacherInvitation.email_digest == invitation_email_digest(target.email, settings=settings),
                models.TeacherInvitation.consumed_at.is_(None),
                models.TeacherInvitation.revoked_at.is_(None),
            ).values(revoked_at=now).execution_options(synchronize_session=False)
        )
        db.execute(delete(models.Teacher).where(models.Teacher.user_id == target_user_id))
        # Use database cascades only. ORM deletion would traverse content trees.
        db.execute(delete(models.User).where(models.User.id == target_user_id).execution_options(synchronize_session=False))
        record_operator_audit_event(
            db, actor_identifier=f"admin-user:{actor_id}", action="ACCOUNT_DELETED", outcome="SUCCEEDED",
            resource_email=target.email, settings=settings,
        )
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Account dependencies changed; review the account before trying again") from None
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=503, detail="Account could not be deleted; try again") from None
