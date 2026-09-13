import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import Depends, Request
from sqlalchemy import update

import main
import models
from database import SessionLocal
from identity_controls import consume_teacher_invitation, invitation_email_digest, issue_browser_session

URL = "/api/admin/teacher-invitations"
RECIPIENT = "teacher@henrico.k12.va.us"


@pytest.fixture
def admin_client(client, monkeypatch):
    monkeypatch.setattr(main, "settings", main.settings.model_copy(update={
        "allowed_email_domains": ("henricostudents.org", "henrico.k12.va.us"),
    }))
    with SessionLocal() as db:
        actor = models.User(
            username="inviting-admin", email="admin@henricostudents.org", password="unused-test-hash",
            role=models.UserRole.ADMIN, is_admin=False, email_verified_at=datetime.now(UTC),
        )
        db.add(actor)
        db.flush()
        actor_id = actor.id
        issued = issue_browser_session(db, user_id=actor_id, settings=main.settings)
        db.commit()
    client.cookies.set(main.settings.session_cookie_name, issued.token)
    client.cookies.set(main.settings.csrf_cookie_name, "invitation-csrf")
    client.headers[main.CSRF_HEADER_NAME] = "invitation-csrf"
    return client, actor_id


def _post(client, email=RECIPIENT):
    return client.post(URL, json={"email": email})


def _aware(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def test_student_domain_admin_gets_one_email_bound_48_hour_code_without_mail(admin_client, caplog):
    client, actor_id = admin_client
    before = datetime.now(UTC)
    response = _post(client, "Teacher@HENRICO.K12.VA.US")
    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"email", "invitation_token", "expires_at"}
    assert body["email"] == RECIPIENT
    token = body["invitation_token"]
    assert len(token) >= 40
    expiry = datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00"))
    assert before + timedelta(hours=48) <= expiry <= datetime.now(UTC) + timedelta(hours=48)
    assert "no-store" in response.headers["cache-control"]
    with SessionLocal() as db:
        invitation = db.query(models.TeacherInvitation).one()
        assert invitation.token_digest == hashlib.sha256(token.encode()).hexdigest()
        assert invitation.email_digest == invitation_email_digest(RECIPIENT, settings=main.settings)
        assert invitation.created_by == f"admin-user:{actor_id}"
        assert _aware(invitation.expires_at) == expiry
        audit = db.query(models.OperatorAuditEvent).one()
        assert (audit.actor_identifier, audit.action, audit.outcome) == (
            f"admin-user:{actor_id}", "TEACHER_INVITATION_CREATED", "SUCCEEDED",
        )
        assert audit.resource_digest != invitation.email_digest
        assert db.query(models.EmailVerification).count() == 0
        assert db.query(models.PasswordReset).count() == 0
        assert not consume_teacher_invitation(db, token=token, email="different@henrico.k12.va.us", settings=main.settings)
        assert consume_teacher_invitation(db, token=token, email=RECIPIENT, settings=main.settings)
        assert not consume_teacher_invitation(db, token=token, email=RECIPIENT, settings=main.settings)
        db.commit()
    assert token not in caplog.text
    assert RECIPIENT not in caplog.text


def test_anonymous_and_missing_csrf_cannot_issue(admin_client):
    client, _ = admin_client
    del client.headers[main.CSRF_HEADER_NAME]
    assert _post(client).status_code == 403
    client.cookies.clear()
    assert _post(client).status_code == 401
    with SessionLocal() as db:
        assert db.query(models.TeacherInvitation).count() == 0


@pytest.mark.parametrize("role", [models.UserRole.STUDENT, models.UserRole.TEACHER])
def test_non_admin_cannot_issue_even_with_legacy_admin_flag(admin_client, role):
    client, actor_id = admin_client
    with SessionLocal() as db:
        db.execute(update(models.User).where(models.User.id == actor_id).values(role=role, is_admin=True))
        db.commit()
    assert _post(client).status_code == 403


@pytest.mark.parametrize("mutation,expected", [("disabled", 401), ("unverified", 401), ("revoked", 401), ("expired", 401), ("demoted", 403)])
def test_actor_and_session_are_rechecked_after_authentication(admin_client, mutation, expected):
    client, actor_id = admin_client

    async def stale_actor(request: Request, db=Depends(main.get_db)):
        actor = await main.get_current_user(request, None, db)
        with SessionLocal() as other:
            if mutation in {"revoked", "expired"}:
                values = {"revoked_at": datetime.now(UTC)} if mutation == "revoked" else {"expires_at": datetime.now(UTC) - timedelta(seconds=1)}
                other.execute(update(models.BrowserSession).where(models.BrowserSession.user_id == actor_id).values(**values))
            else:
                values = {"disabled_at": datetime.now(UTC)} if mutation == "disabled" else {"email_verified_at": None} if mutation == "unverified" else {"role": models.UserRole.STUDENT}
                other.execute(update(models.User).where(models.User.id == actor_id).values(**values))
            other.commit()
        return actor

    main.app.dependency_overrides[main.get_current_user] = stale_actor
    try:
        assert _post(client).status_code == expected
    finally:
        main.app.dependency_overrides.pop(main.get_current_user, None)
    with SessionLocal() as db:
        assert db.query(models.TeacherInvitation).count() == 0


def test_replacement_revokes_unused_codes_but_retains_consumed_history(admin_client):
    client, _ = admin_client
    first = _post(client).json()["invitation_token"]
    second = _post(client).json()["invitation_token"]
    with SessionLocal() as db:
        assert not consume_teacher_invitation(db, token=first, email=RECIPIENT, settings=main.settings)
        assert consume_teacher_invitation(db, token=second, email=RECIPIENT, settings=main.settings)
        db.commit()
    third = _post(client).json()["invitation_token"]
    with SessionLocal() as db:
        rows = db.query(models.TeacherInvitation).order_by(models.TeacherInvitation.id).all()
        assert rows[0].revoked_at is not None
        assert rows[1].consumed_at is not None and rows[1].revoked_at is None
        assert consume_teacher_invitation(db, token=third, email=RECIPIENT, settings=main.settings)
        db.rollback()
        assert not consume_teacher_invitation(db, token=third, email=RECIPIENT, settings=main.settings, now=datetime.now(UTC) + timedelta(hours=49))


def test_existing_account_conflicts_before_domain_policy(admin_client):
    client, actor_id = admin_client
    with SessionLocal() as db:
        db.execute(update(models.User).where(models.User.id == actor_id).values(email="admin@unlisted.com"))
        db.commit()
    assert _post(client, "ADMIN@unlisted.com").status_code == 409
    with SessionLocal() as db:
        assert db.query(models.TeacherInvitation).count() == 0


@pytest.mark.parametrize("payload,expected", [({"email": "teacher@outside.com"}, 400), ({"email": "invalid"}, 422), ({"email": RECIPIENT, "expires_hours": 720}, 422)])
def test_invalid_input_or_domain_is_rejected(admin_client, payload, expected):
    client, _ = admin_client
    assert client.post(URL, json=payload).status_code == expected


def test_digest_collision_rolls_back_replacement(admin_client, monkeypatch):
    import admin_teacher_invitations

    client, _ = admin_client
    token = _post(client).json()["invitation_token"]
    monkeypatch.setattr(admin_teacher_invitations.secrets, "token_urlsafe", lambda _size: token)
    response = _post(client)
    assert response.status_code == 409
    assert "invitation_token" not in response.json()
    with SessionLocal() as db:
        assert db.query(models.TeacherInvitation).count() == 1
        assert consume_teacher_invitation(db, token=token, email=RECIPIENT, settings=main.settings)


def test_audit_failure_rolls_back_replacement_and_returns_no_code(admin_client, monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError

    import admin_teacher_invitations

    client, _ = admin_client
    first = _post(client).json()["invitation_token"]

    def fail_audit(*_args, **_kwargs):
        raise SQLAlchemyError("synthetic failure")

    monkeypatch.setattr(admin_teacher_invitations, "record_operator_audit_event", fail_audit)
    response = _post(client)
    assert response.status_code == 503
    assert "invitation_token" not in response.json()
    with SessionLocal() as db:
        assert db.query(models.TeacherInvitation).count() == 1
        assert db.query(models.OperatorAuditEvent).count() == 1
        assert consume_teacher_invitation(db, token=first, email=RECIPIENT, settings=main.settings)
