"""Teacher-assisted verification without granting unverified users a session."""

import hashlib
import hmac
import re
import secrets
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import HTTPException
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

import models
from config import Settings
from identity_controls import invalidate_email_verification_requests, normalize_email, record_operator_audit_event

CODE_LIFETIME = timedelta(minutes=15)
MAX_CODE_ATTEMPTS = 5
CHALLENGE_PURPOSE = "student-email-verification"
INVALID_CODE_DETAIL = "Invalid or expired verification code. Ask your teacher for a new code."
INELIGIBLE_TARGET_DETAIL = "Some selected students are no longer eligible. Look them up again."


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _derived_key(settings: Settings, purpose: bytes) -> bytes:
    secret = settings.secret_key.get_secret_value() if settings.secret_key else ""
    if not secret:
        raise RuntimeError("Student verification requires SECRET_KEY")
    return hmac.digest(secret.encode("utf-8"), b"litblogs:student-verification:v1\0" + purpose, "sha256")


def _credential_digest(user, *, settings: Settings) -> str:
    value = f"{user.id}\0{user.email}\0{user.password}".encode("utf-8")
    return hmac.new(_derived_key(settings, b"credentials"), value, hashlib.sha256).hexdigest()


def _code_digest(student_id: int, email: str, code: str, *, settings: Settings) -> str:
    value = f"{student_id}\0{email}\0{code}".encode("ascii")
    return hmac.new(_derived_key(settings, b"code"), value, hashlib.sha256).hexdigest()


def _challenge_audience(settings: Settings) -> str:
    return f"{settings.jwt_audience}:student-email-verification"


def _allowed_email(email: str, settings: Settings) -> bool:
    return not settings.allowed_email_domains or email.rsplit("@", 1)[-1] in settings.allowed_email_domains


def _student_eligible(user, federated_ids: set[int], *, settings: Settings) -> bool:
    return (
        user.role == models.UserRole.STUDENT
        and user.disabled_at is None
        and user.email_verified_at is None
        and user.id not in federated_ids
        and _allowed_email(user.email, settings)
    )


def pending_login_detail(
    db: Session, *, user_id: int, expected_password_hash: str, settings: Settings,
) -> dict:
    """Return only a narrow proof of a successful password check, never a session."""
    user = db.execute(
        select(models.User.id, models.User.email, models.User.password, models.User.role,
               models.User.disabled_at, models.User.email_verified_at)
        .where(models.User.id == user_id, models.User.password == expected_password_hash,
               models.User.disabled_at.is_(None), models.User.email_verified_at.is_(None))
        .with_for_update()
    ).one_or_none()
    if user is None:
        db.rollback()
        raise HTTPException(status_code=401, detail="Invalid email or password")
    federated_ids = set(db.scalars(
        select(models.FederatedIdentity.user_id).where(models.FederatedIdentity.user_id == user_id)
    ))
    allowed = _student_eligible(user, federated_ids, settings=settings)
    challenge = None
    expires_at = None
    if allowed:
        now = datetime.now(UTC).replace(microsecond=0)
        expires_at = now + CODE_LIFETIME
        challenge = jwt.encode(
            {
                "sub": str(user.id), "iss": settings.jwt_issuer, "aud": _challenge_audience(settings),
                "iat": now, "nbf": now, "exp": expires_at, "jti": secrets.token_urlsafe(16),
                "purpose": CHALLENGE_PURPOSE, "credential_digest": _credential_digest(user, settings=settings),
            },
            _derived_key(settings, b"challenge-signing"), algorithm="HS256",
            headers={"typ": "student-verification+jwt"},
        )
    result = {
        "code": "email_verification_required", "email": user.email,
        "verification_challenge": challenge,
        "expires_at": expires_at.isoformat() if expires_at is not None else None,
        "teacher_code_allowed": allowed,
    }
    db.rollback()
    return result


def _lock_teacher_and_targets(
    db: Session, *, actor_id: int, session_id: int | None, emails: list[str], settings: Settings,
):
    # Every lifecycle path locks users before their children. Stable ordering
    # serializes a teacher's role/disable/revocation with multi-student issuance.
    users = db.execute(
        select(models.User.id, models.User.email, models.User.username, models.User.first_name,
               models.User.last_name, models.User.role, models.User.disabled_at, models.User.email_verified_at)
        .where(or_(models.User.id == actor_id, models.User.email.in_(emails)))
        .order_by(models.User.id).with_for_update()
    ).all()
    by_id = {user.id: user for user in users}
    actor = by_id.get(actor_id)
    if actor is None or actor.disabled_at is not None or actor.email_verified_at is None:
        raise HTTPException(status_code=401, detail="Could not validate credentials")
    if actor.role not in {models.UserRole.TEACHER, models.UserRole.ADMIN}:
        raise HTTPException(status_code=403, detail="Teacher or administrator access required")
    session = db.execute(
        select(models.BrowserSession.revoked_at, models.BrowserSession.expires_at)
        .where(models.BrowserSession.id == session_id, models.BrowserSession.user_id == actor_id)
        .with_for_update()
    ).one_or_none()
    if session is None or session.revoked_at is not None or _aware(session.expires_at) <= datetime.now(UTC):
        raise HTTPException(status_code=401, detail="Could not validate credentials")
    federated_ids = set(db.scalars(
        select(models.FederatedIdentity.user_id).where(models.FederatedIdentity.user_id.in_(by_id))
    ))
    eligible = {
        user.email: user for user in users
        if user.email in emails and _student_eligible(user, federated_ids, settings=settings)
    }
    return eligible


def _normalized_emails(emails: list[str]) -> list[str]:
    try:
        return list(dict.fromkeys(normalize_email(str(email)) for email in emails))
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="Use exact school email addresses") from None


def lookup_pending_students(
    db: Session, *, actor_id: int, session_id: int | None, emails: list[str], settings: Settings,
) -> dict:
    try:
        requested = _normalized_emails(emails)
        eligible = _lock_teacher_and_targets(
            db, actor_id=actor_id, session_id=session_id, emails=requested, settings=settings,
        )
        students = [
            {"id": user.id, "email": user.email, "first_name": user.first_name,
             "last_name": user.last_name, "username": user.username}
            for email in requested if (user := eligible.get(email)) is not None
        ]
        db.rollback()
        return {"students": students, "unmatched_count": len(requested) - len(students)}
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=503, detail="Student lookup is unavailable. Try again.") from None


def create_student_verification_codes(
    db: Session, *, actor_id: int, session_id: int | None, emails: list[str], settings: Settings,
) -> dict:
    """Issue selected students' one-use codes and their audits in one transaction."""
    try:
        requested = _normalized_emails(emails)
        eligible = _lock_teacher_and_targets(
            db, actor_id=actor_id, session_id=session_id, emails=requested, settings=settings,
        )
        if len(eligible) != len(requested):
            raise HTTPException(status_code=409, detail=INELIGIBLE_TARGET_DETAIL)
        now = datetime.now(UTC)
        expires_at = now + CODE_LIFETIME
        codes = []
        for email in requested:
            student = eligible[email]
            existing = db.execute(
                select(models.StudentVerificationCode.id, models.StudentVerificationCode.code_digest)
                .where(models.StudentVerificationCode.student_id == student.id).with_for_update()
            ).one_or_none()
            while True:
                code = f"{secrets.randbelow(1_000_000):06d}"
                digest = _code_digest(student.id, student.email, code, settings=settings)
                if existing is None or digest != existing.code_digest:
                    break
            values = {
                "issuer_id": actor_id, "code_digest": digest, "created_at": now,
                "expires_at": expires_at, "attempts": 0, "consumed_at": None,
            }
            if existing is None:
                db.add(models.StudentVerificationCode(student_id=student.id, **values))
            else:
                db.execute(update(models.StudentVerificationCode).where(models.StudentVerificationCode.id == existing.id)
                           .values(**values).execution_options(synchronize_session=False))
            record_operator_audit_event(
                db, actor_identifier=f"teacher-user:{actor_id}", action="STUDENT_VERIFICATION_CODE_CREATED",
                outcome="SUCCEEDED", resource_email=student.email, settings=settings,
            )
            codes.append({
                "student_id": student.id, "email": student.email, "first_name": student.first_name,
                "last_name": student.last_name, "code": code, "expires_at": expires_at,
            })
        db.commit()
        return {"codes": codes}
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=INELIGIBLE_TARGET_DETAIL) from None
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=503, detail="Verification codes could not be saved. Try again.") from None


def _invalid_code() -> HTTPException:
    return HTTPException(status_code=400, detail=INVALID_CODE_DETAIL)


def consume_student_verification_code(
    db: Session, *, verification_challenge: str, code: str, settings: Settings,
) -> None:
    try:
        try:
            claims = jwt.decode(
                verification_challenge, _derived_key(settings, b"challenge-signing"), algorithms=["HS256"],
                audience=_challenge_audience(settings), issuer=settings.jwt_issuer,
                options={"require": ["sub", "iss", "aud", "iat", "nbf", "exp", "jti", "purpose", "credential_digest"]},
            )
            if (
                claims["purpose"] != CHALLENGE_PURPOSE or not isinstance(claims["credential_digest"], str)
                or re.fullmatch(r"[0-9a-f]{64}", claims["credential_digest"]) is None
            ):
                raise _invalid_code()
            student_id = int(claims["sub"])
            if student_id <= 0 or str(student_id) != claims["sub"]:
                raise _invalid_code()
        except (jwt.InvalidTokenError, TypeError, ValueError, KeyError):
            raise _invalid_code() from None

        issuer_id = db.scalar(
            select(models.StudentVerificationCode.issuer_id)
            .where(models.StudentVerificationCode.student_id == student_id)
        )
        if issuer_id is None:
            raise _invalid_code()
        accounts = db.execute(
            select(models.User.id, models.User.email, models.User.password, models.User.role,
                   models.User.disabled_at, models.User.email_verified_at)
            .where(models.User.id.in_({student_id, issuer_id})).order_by(models.User.id).with_for_update()
        ).all()
        by_id = {user.id: user for user in accounts}
        student, issuer = by_id.get(student_id), by_id.get(issuer_id)
        federated_ids = set(db.scalars(
            select(models.FederatedIdentity.user_id).where(models.FederatedIdentity.user_id == student_id)
        ))
        if (
            student is None or not _student_eligible(student, federated_ids, settings=settings)
            or not hmac.compare_digest(claims["credential_digest"], _credential_digest(student, settings=settings))
            or issuer is None or issuer.disabled_at is not None or issuer.email_verified_at is None
            or issuer.role not in {models.UserRole.TEACHER, models.UserRole.ADMIN}
        ):
            raise _invalid_code()
        row = db.execute(
            select(models.StudentVerificationCode.id, models.StudentVerificationCode.issuer_id,
                   models.StudentVerificationCode.code_digest, models.StudentVerificationCode.expires_at,
                   models.StudentVerificationCode.attempts, models.StudentVerificationCode.consumed_at)
            .where(models.StudentVerificationCode.student_id == student_id).with_for_update()
        ).one_or_none()
        now = datetime.now(UTC)
        if (
            row is None or row.issuer_id != issuer_id or row.consumed_at is not None
            or row.code_digest is None or _aware(row.expires_at) <= now or row.attempts >= MAX_CODE_ATTEMPTS
        ):
            raise _invalid_code()
        matches = hmac.compare_digest(row.code_digest, _code_digest(student_id, student.email, code, settings=settings))
        consumed = db.execute(
            update(models.StudentVerificationCode)
            .where(models.StudentVerificationCode.id == row.id, models.StudentVerificationCode.attempts == row.attempts,
                   models.StudentVerificationCode.code_digest == row.code_digest,
                   models.StudentVerificationCode.consumed_at.is_(None))
            .values(attempts=row.attempts + 1, **({"code_digest": None, "consumed_at": now} if matches else {}))
            .execution_options(synchronize_session=False)
        )
        if consumed.rowcount != 1:
            raise _invalid_code()
        if not matches:
            # Persist failures before responding. A new login/challenge must not
            # reset the code's attempt budget, including across app replicas.
            db.commit()
            raise _invalid_code()
        activated = db.execute(
            update(models.User)
            .where(models.User.id == student_id, models.User.disabled_at.is_(None),
                   models.User.email_verified_at.is_(None), models.User.password == student.password,
                   models.User.role == models.UserRole.STUDENT)
            .values(email_verified_at=now).execution_options(synchronize_session=False)
        )
        if activated.rowcount != 1:
            raise _invalid_code()
        invalidate_email_verification_requests(db, user_id=student_id, now=now)
        record_operator_audit_event(
            db, actor_identifier=f"student-user:{student_id}", action="STUDENT_VERIFICATION_CODE_CONSUMED",
            outcome="SUCCEEDED", resource_email=student.email, settings=settings,
        )
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=503, detail="Account verification is unavailable. Try again.") from None
