"""Audited administrator recovery through the existing one-use password reset flow."""

import hashlib
import math
import secrets
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

import models
from config import Settings
from email_verification_delivery import EMAIL_VERIFICATION_LIFETIME, email_verification_token_digest
from identity_controls import record_operator_audit_event
from schemas import EmailAccountRecoveryResponse, ManualAccountRecoveryResponse, ManualAccountVerificationResponse

RECOVERY_LIFETIME = timedelta(hours=1)
RECOVERY_EMAIL_COOLDOWN = timedelta(minutes=5)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _lock_account_target(db: Session, *, actor_id: int, session_id: int | None, target_id: int):
    # Lock both users in a stable order before any browser-session lock. This
    # also serializes account disabling, target deletion and reset consumption.
    accounts = {row.id: row for row in db.execute(
        select(models.User.id, models.User.email, models.User.role,
               models.User.disabled_at, models.User.email_verified_at)
        .where(models.User.id.in_({actor_id, target_id}))
        .order_by(models.User.id)
        .with_for_update()
    ).all()}
    actor = accounts.get(actor_id)
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
    target = accounts.get(target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Account not found")
    if target.disabled_at is not None:
        raise HTTPException(status_code=409, detail="This account is disabled; account recovery is unavailable")
    return target


def create_admin_account_recovery(
    db: Session, *, actor_id: int, session_id: int | None, target_id: int,
    delivery: Literal["manual", "email"], settings: Settings,
) -> ManualAccountRecoveryResponse | EmailAccountRecoveryResponse:
    """Replace any old token/worker claim and commit recovery plus audit together."""
    try:
        if delivery not in {"manual", "email"}:
            raise HTTPException(status_code=422, detail="Choose manual or email recovery")
        target = _lock_account_target(db, actor_id=actor_id, session_id=session_id, target_id=target_id)
        if target.email_verified_at is None:
            raise HTTPException(status_code=409, detail="Verify this account's email before requesting password recovery")
        now = datetime.now(UTC)
        existing = db.execute(select(models.PasswordReset.id, models.PasswordReset.created_at)
                              .where(models.PasswordReset.user_id == target_id)).one_or_none()
        if delivery == "email" and existing is not None:
            remaining = (_aware(existing.created_at) + RECOVERY_EMAIL_COOLDOWN - now).total_seconds()
            if remaining > 0:
                raise HTTPException(
                    status_code=429, detail="Wait five minutes between recovery email requests",
                    headers={"Retry-After": str(math.ceil(remaining))},
                )
        token = secrets.token_urlsafe(32) if delivery == "manual" else None
        expiry = now + RECOVERY_LIFETIME if token is not None else None
        if token is not None:
            if not settings.frontend_url:
                raise HTTPException(status_code=503, detail="Account recovery is unavailable; try again")
            result = ManualAccountRecoveryResponse(
                email=target.email, reset_url=f"{settings.frontend_url.rstrip('/')}/reset-password#token={token}",
                expires_at=expiry,
            )
            action = "ACCOUNT_RECOVERY_LINK_CREATED"
        else:
            result = EmailAccountRecoveryResponse(email=target.email, queued=True)
            action = "ACCOUNT_RECOVERY_EMAIL_QUEUED"
        values = {
            "token": hashlib.sha256(token.encode("utf-8")).hexdigest() if token is not None else None,
            "created_at": now, "expires_at": expiry, "used": False,
            "delivery_status": "DELIVERED" if token is not None else "PENDING",
            "delivery_attempted_at": None, "delivery_claim_digest": None,
        }
        # Every issuing/claiming/reset path locks this user first. The unique
        # user_id row and cleared claim prevent an old worker overwriting this.
        if existing is None:
            db.add(models.PasswordReset(user_id=target_id, **values))
        else:
            db.execute(update(models.PasswordReset).where(models.PasswordReset.id == existing.id)
                       .values(**values).execution_options(synchronize_session=False))
        record_operator_audit_event(
            db, actor_identifier=f"admin-user:{actor_id}", action=action, outcome="SUCCEEDED",
            resource_email=target.email, settings=settings,
        )
        # Do not use the public request's queue helper: it intentionally swallows
        # failures for enumeration resistance and cannot attest successful queuing.
        db.commit()
        return result
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Account recovery changed concurrently; try again") from None
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=503, detail="Account recovery could not be saved; try again") from None


def create_admin_account_verification(
    db: Session, *, actor_id: int, session_id: int | None, target_id: int, settings: Settings,
) -> ManualAccountVerificationResponse:
    """Issue a capability; only the existing redemption flow verifies the account."""
    try:
        target = _lock_account_target(db, actor_id=actor_id, session_id=session_id, target_id=target_id)
        if target.email_verified_at is not None:
            raise HTTPException(status_code=409, detail="This account's email is already verified")
        federated_id = db.execute(select(models.FederatedIdentity.id)
                                 .where(models.FederatedIdentity.user_id == target_id).limit(1)).scalar_one_or_none()
        if federated_id is not None:
            raise HTTPException(status_code=409, detail="This account uses a federated sign-in provider")
        if not settings.frontend_url:
            raise HTTPException(status_code=503, detail="Account verification is unavailable; try again")
        now = datetime.now(UTC)
        token = secrets.token_urlsafe(32)
        expiry = now + EMAIL_VERIFICATION_LIFETIME
        result = ManualAccountVerificationResponse(
            email=target.email, verification_url=f"{settings.frontend_url.rstrip('/')}/verify-email#token={token}",
            expires_at=expiry,
        )
        values = {
            "token_digest": email_verification_token_digest(token), "created_at": now,
            "expires_at": expiry, "delivery_status": "DELIVERED",
            "delivery_attempted_at": None, "delivery_claim_digest": None,
        }
        verification_id = db.execute(select(models.EmailVerification.id)
                                     .where(models.EmailVerification.user_id == target_id)).scalar_one_or_none()
        if verification_id is None:
            db.add(models.EmailVerification(user_id=target_id, **values))
        else:
            db.execute(update(models.EmailVerification).where(models.EmailVerification.id == verification_id)
                       .values(**values).execution_options(synchronize_session=False))
        record_operator_audit_event(
            db, actor_identifier=f"admin-user:{actor_id}", action="ACCOUNT_VERIFICATION_LINK_CREATED",
            outcome="SUCCEEDED", resource_email=target.email, settings=settings,
        )
        db.commit()
        return result
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Account verification changed concurrently; try again") from None
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=503, detail="Account verification could not be saved; try again") from None
