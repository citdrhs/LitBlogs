"""Administrator recovery uses the existing one-use reset flow, never SMTP inline."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import Depends, Request
from sqlalchemy import update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

import main
import models
from database import SessionLocal, engine
from identity_controls import issue_browser_session

RECIPIENT = "recovery-teacher@henrico.k12.va.us"
NEW_PASSWORD = "Synthetic-recovered-password-2!"


@pytest.fixture
def recovery_client(client, monkeypatch):
    monkeypatch.setattr(main, "settings", main.settings.model_copy(update={
        "frontend_url": "https://drhscit.org/dren", "app_base_path": "/dren",
    }))
    with SessionLocal() as db:
        actor = models.User(
            username="recovery-admin", email="recovery-admin@example.com", password="unused-admin-hash",
            role=models.UserRole.ADMIN, is_admin=False, email_verified_at=datetime.now(UTC),
        )
        target = models.User(
            username="recovery-teacher", email=RECIPIENT, password=main.hash_password("Synthetic-old-password-1!"),
            role=models.UserRole.TEACHER, email_verified_at=datetime.now(UTC),
        )
        db.add_all([actor, target])
        db.flush()
        actor_id, target_id = actor.id, target.id
        issued = issue_browser_session(db, user_id=actor_id, settings=main.settings)
        issue_browser_session(db, user_id=target_id, settings=main.settings)
        db.commit()
    client.cookies.set(main.settings.session_cookie_name, issued.token)
    client.cookies.set(main.settings.csrf_cookie_name, "recovery-csrf")
    client.headers[main.CSRF_HEADER_NAME] = "recovery-csrf"
    return client, actor_id, target_id


def request_recovery(client, target_id, delivery="manual"):
    return client.post(f"/api/admin/users/{target_id}/recovery", json={"delivery": delivery})


def token_from(body):
    return parse_qs(urlsplit(body["reset_url"]).fragment)["token"][0]


def test_manual_link_is_private_audited_single_use_and_revokes_target_sessions(recovery_client, monkeypatch, caplog):
    client, actor_id, target_id = recovery_client
    monkeypatch.setattr(main, "send_password_reset_email", lambda *_args: pytest.fail("manual recovery must not send mail"))
    before = datetime.now(UTC)
    response = request_recovery(client, target_id)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"email", "reset_url", "expires_at"}
    assert body["email"] == RECIPIENT
    assert body["reset_url"].startswith("https://drhscit.org/dren/reset-password#token=")
    assert "no-store" in response.headers["cache-control"]
    token = token_from(body)
    assert len(token) >= 40
    expiry = datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00"))
    assert before + timedelta(hours=1) <= expiry <= datetime.now(UTC) + timedelta(hours=1)
    with SessionLocal() as db:
        row = db.query(models.PasswordReset).one()
        assert row.user_id == target_id
        assert row.token == hashlib.sha256(token.encode()).hexdigest()
        assert row.delivery_status == "DELIVERED" and row.used is False
        assert row.delivery_claim_digest is None and row.delivery_attempted_at is None
        audit = db.query(models.OperatorAuditEvent).one()
        assert (audit.actor_identifier, audit.action, audit.outcome) == (
            f"admin-user:{actor_id}", "ACCOUNT_RECOVERY_LINK_CREATED", "SUCCEEDED",
        )
        assert audit.resource_digest != RECIPIENT
        assert db.query(models.BrowserSession).filter_by(user_id=target_id, revoked_at=None).count() == 1
    reset = client.post("/api/auth/reset-password", json={"token": token, "new_password": NEW_PASSWORD})
    assert reset.status_code == 200
    assert client.post("/api/auth/reset-password", json={"token": token, "new_password": NEW_PASSWORD}).status_code == 400
    with SessionLocal() as db:
        assert main.verify_password(NEW_PASSWORD, db.get(models.User, target_id).password)
        assert db.query(models.BrowserSession).filter_by(user_id=target_id, revoked_at=None).count() == 0
        assert db.query(models.BrowserSession).filter_by(user_id=actor_id, revoked_at=None).count() == 1
    assert token not in caplog.text and RECIPIENT not in caplog.text


def test_email_mode_replaces_manual_token_with_committed_pending_queue(recovery_client, monkeypatch):
    client, _actor_id, target_id = recovery_client
    first = request_recovery(client, target_id)
    assert first.status_code == 200
    old_token = token_from(first.json())
    with SessionLocal() as db:
        db.query(models.PasswordReset).one().created_at = datetime.now(UTC) - timedelta(minutes=6)
        db.commit()
    monkeypatch.setattr(main, "send_password_reset_email", lambda *_args: pytest.fail("queueing must not send inline"))
    response = request_recovery(client, target_id, "email")
    assert response.status_code == 200
    assert response.json() == {"email": RECIPIENT, "queued": True}
    assert "no-store" in response.headers["cache-control"]
    with SessionLocal() as db:
        row = db.query(models.PasswordReset).one()
        assert row.delivery_status == "PENDING" and row.used is False
        assert row.token is None and row.expires_at is None and row.delivery_claim_digest is None
        assert db.query(models.OperatorAuditEvent).filter_by(action="ACCOUNT_RECOVERY_EMAIL_QUEUED").count() == 1
    assert client.post("/api/auth/reset-password", json={"token": old_token, "new_password": NEW_PASSWORD}).status_code == 400


def test_reissue_invalidates_previous_link_and_existing_worker_claim(recovery_client):
    client, _actor_id, target_id = recovery_client
    first = request_recovery(client, target_id)
    assert first.status_code == 200
    old_token = token_from(first.json())
    with SessionLocal() as db:
        row = db.query(models.PasswordReset).one()
        row.delivery_status = "PROCESSING"
        row.delivery_claim_digest = main._password_reset_claim_digest("previous-worker-claim")
        row.delivery_attempted_at = datetime.now(UTC)
        reset_id = row.id
        db.commit()
    second = request_recovery(client, target_id)
    assert second.status_code == 200
    assert token_from(second.json()) != old_token
    assert main._complete_password_reset_delivery(reset_id, "previous-worker-claim", "obsolete-worker-token", True) is False
    assert client.post("/api/auth/reset-password", json={"token": old_token, "new_password": NEW_PASSWORD}).status_code == 400


def test_anonymous_and_missing_csrf_are_rejected(recovery_client):
    client, _actor_id, target_id = recovery_client
    del client.headers[main.CSRF_HEADER_NAME]
    assert request_recovery(client, target_id).status_code == 403
    client.cookies.clear()
    assert request_recovery(client, target_id).status_code == 401
    with SessionLocal() as db:
        assert db.query(models.PasswordReset).count() == db.query(models.OperatorAuditEvent).count() == 0


@pytest.mark.parametrize("role", [models.UserRole.STUDENT, models.UserRole.TEACHER])
def test_legacy_admin_flag_does_not_authorize_recovery(recovery_client, role):
    client, actor_id, target_id = recovery_client
    with SessionLocal() as db:
        db.execute(update(models.User).where(models.User.id == actor_id).values(role=role, is_admin=True))
        db.commit()
    assert request_recovery(client, target_id).status_code == 403


@pytest.mark.parametrize("mutation,expected", [("revoked", 401), ("expired", 401), ("disabled", 401), ("unverified", 401), ("demoted", 403)])
def test_stale_administrator_authentication_is_rechecked_under_lock(recovery_client, mutation, expected):
    client, actor_id, target_id = recovery_client

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
        assert request_recovery(client, target_id).status_code == expected
    finally:
        main.app.dependency_overrides.pop(main.get_current_user, None)
    with SessionLocal() as db:
        assert db.query(models.PasswordReset).count() == 0


@pytest.mark.parametrize("state", ["disabled", "unverified"])
def test_ineligible_target_returns_clear_conflict_without_issuing(recovery_client, state):
    client, _actor_id, target_id = recovery_client
    with SessionLocal() as db:
        db.execute(update(models.User).where(models.User.id == target_id).values(
            **({"disabled_at": datetime.now(UTC)} if state == "disabled" else {"email_verified_at": None}),
        ))
        db.commit()
    response = request_recovery(client, target_id)
    assert response.status_code == 409
    assert ("disabled" if state == "disabled" else "verif") in response.json()["detail"].lower()
    with SessionLocal() as db:
        assert db.query(models.PasswordReset).count() == 0


def test_unknown_target_and_strict_request_validation(recovery_client):
    client, _actor_id, target_id = recovery_client
    assert request_recovery(client, target_id + 10000).status_code == 404
    for payload in ({}, {"delivery": "sms"}, {"delivery": True}, {"delivery": "manual", "password": "administrator-chosen"}):
        assert client.post(f"/api/admin/users/{target_id}/recovery", json=payload).status_code == 422


@pytest.mark.parametrize("delivery", ["manual", "email"])
def test_audit_failure_rolls_back_replacement_and_never_reports_success(recovery_client, monkeypatch, delivery):
    import admin_account_recovery

    client, _actor_id, target_id = recovery_client
    first = request_recovery(client, target_id)
    assert first.status_code == 200
    original = hashlib.sha256(token_from(first.json()).encode()).hexdigest()
    with SessionLocal() as db:
        db.query(models.PasswordReset).one().created_at = datetime.now(UTC) - timedelta(minutes=6)
        db.commit()

    def fail_audit(*_args, **_kwargs):
        raise SQLAlchemyError("private database diagnostic")

    monkeypatch.setattr(admin_account_recovery, "record_operator_audit_event", fail_audit)
    response = request_recovery(client, target_id, delivery)
    assert response.status_code == 503
    assert "private database diagnostic" not in response.text
    with SessionLocal() as db:
        row = db.query(models.PasswordReset).one()
        assert row.token == original and row.delivery_status == "DELIVERED"
        assert db.query(models.OperatorAuditEvent).count() == 1


def test_administrator_can_recover_self_without_revoking_session_at_issuance(recovery_client):
    client, actor_id, _target_id = recovery_client
    response = request_recovery(client, actor_id)
    assert response.status_code == 200
    with SessionLocal() as db:
        assert db.query(models.BrowserSession).filter_by(user_id=actor_id, revoked_at=None).count() == 1


@pytest.mark.parametrize("delivery", ["manual", "email"])
def test_commit_failure_cannot_return_a_link_or_queued_success(recovery_client, monkeypatch, delivery):
    client, _actor_id, target_id = recovery_client

    def fail_commit(_db):
        raise SQLAlchemyError("synthetic private commit failure")

    with monkeypatch.context() as change:
        change.setattr(Session, "commit", fail_commit)
        response = request_recovery(client, target_id, delivery)
    assert response.status_code == 503
    assert not {"queued", "reset_url"}.intersection(response.json())
    assert "private commit failure" not in response.text
    assert "no-store" in response.headers["cache-control"]
    with SessionLocal() as db:
        assert db.query(models.PasswordReset).count() == db.query(models.OperatorAuditEvent).count() == 0


@pytest.mark.skipif(engine.dialect.name != "postgresql", reason="PostgreSQL row locks required")
def test_postgres_concurrent_admin_reissues_leave_exactly_one_current_digest(recovery_client):
    client, _actor_id, target_id = recovery_client
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _index: request_recovery(client, target_id), range(2)))
    assert [response.status_code for response in responses] == [200, 200]
    digests = {hashlib.sha256(token_from(response.json()).encode()).hexdigest() for response in responses}
    assert len(digests) == 2
    with SessionLocal() as db:
        row = db.query(models.PasswordReset).one()
        assert row.token in digests and row.delivery_status == "DELIVERED"
        assert db.query(models.OperatorAuditEvent).filter_by(action="ACCOUNT_RECOVERY_LINK_CREATED").count() == 2


@pytest.mark.parametrize("initial_delivery", ["manual", "email"])
def test_email_cooldown_preserves_recent_token_or_queue(recovery_client, initial_delivery):
    client, _actor_id, target_id = recovery_client
    first = request_recovery(client, target_id, initial_delivery)
    assert first.status_code == 200
    with SessionLocal() as db:
        row = db.query(models.PasswordReset).one()
        original = (row.token, row.created_at, row.delivery_status)
    denied = request_recovery(client, target_id, "email")
    assert denied.status_code == 429
    assert 1 <= int(denied.headers["retry-after"]) <= 300
    with SessionLocal() as db:
        row = db.query(models.PasswordReset).one()
        assert (row.token, row.created_at, row.delivery_status) == original
        assert db.query(models.OperatorAuditEvent).count() == 1
        row.created_at = datetime.now(UTC) - timedelta(minutes=5, seconds=1)
        db.commit()
    assert request_recovery(client, target_id, "email").status_code == 200
    assert request_recovery(client, target_id, "manual").status_code == 200


@pytest.mark.skipif(engine.dialect.name != "postgresql", reason="PostgreSQL row locks required")
def test_postgres_concurrent_email_recovery_queues_once(recovery_client):
    client, _actor_id, target_id = recovery_client
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _index: request_recovery(client, target_id, "email"), range(2)))
    assert sorted(response.status_code for response in responses) == [200, 429]
    with SessionLocal() as db:
        assert db.query(models.PasswordReset).one().delivery_status == "PENDING"
        assert db.query(models.OperatorAuditEvent).filter_by(action="ACCOUNT_RECOVERY_EMAIL_QUEUED").count() == 1
