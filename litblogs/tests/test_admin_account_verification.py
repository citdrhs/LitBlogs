"""Manual administrator verification uses the normal one-use redemption flow."""

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import Depends, Request
from sqlalchemy import update
from sqlalchemy.exc import SQLAlchemyError
from test_admin_account_recovery import recovery_client as recovery_client

import email_verification_delivery as delivery
import main
import models
from database import SessionLocal


@pytest.fixture
def verification_client(recovery_client):
    client, actor_id, target_id = recovery_client
    with SessionLocal() as db:
        db.execute(update(models.User).where(models.User.id == target_id).values(email_verified_at=None))
        db.commit()
    return client, actor_id, target_id


def issue(client, target_id, **kwargs):
    return client.post(f"/api/admin/users/{target_id}/verification", **kwargs)


def token_from(response):
    return parse_qs(urlsplit(response.json()["verification_url"]).fragment)["token"][0]


def test_manual_verification_is_private_audited_and_redeemed_once(verification_client, monkeypatch, caplog):
    client, actor_id, target_id = verification_client
    monkeypatch.setattr(delivery, "send_email_verification_email", lambda *_args: pytest.fail("must not send mail"))
    before = datetime.now(UTC)
    response = issue(client, target_id)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"email", "verification_url", "expires_at"}
    assert body["verification_url"].startswith("https://drhscit.org/dren/verify-email#token=")
    assert "no-store" in response.headers["cache-control"]
    token = token_from(response)
    assert len(token) >= 40
    expiry = datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00"))
    assert before + timedelta(hours=24) <= expiry <= datetime.now(UTC) + timedelta(hours=24)
    with SessionLocal() as db:
        assert db.get(models.User, target_id).email_verified_at is None
        row = db.query(models.EmailVerification).one()
        assert row.token_digest == delivery.email_verification_token_digest(token)
        assert row.delivery_status == "DELIVERED"
        assert row.delivery_claim_digest is None and row.delivery_attempted_at is None
        audit = db.query(models.OperatorAuditEvent).one()
        assert (audit.actor_identifier, audit.action, audit.outcome) == (
            f"admin-user:{actor_id}", "ACCOUNT_VERIFICATION_LINK_CREATED", "SUCCEEDED",
        )
        assert audit.resource_digest != body["email"]
    assert client.post("/api/auth/verify-email", json={"token": token}).status_code == 200
    assert client.post("/api/auth/verify-email", json={"token": token}).status_code == 400
    with SessionLocal() as db:
        assert db.get(models.User, target_id).email_verified_at is not None
        assert db.query(models.EmailVerification).one().token_digest is None
    assert token not in caplog.text and body["email"] not in caplog.text


def test_reissue_invalidates_old_token_and_inflight_worker(verification_client):
    client, _actor_id, target_id = verification_client
    first = issue(client, target_id)
    assert first.status_code == 200
    old_token = token_from(first)
    with SessionLocal() as db:
        row = db.query(models.EmailVerification).one()
        row.delivery_status = "PROCESSING"
        row.delivery_claim_digest = delivery.email_verification_claim_digest("old-claim")
        row.delivery_attempted_at = datetime.now(UTC)
        verification_id = row.id
        db.commit()
    second = issue(client, target_id, json={})
    assert second.status_code == 200 and token_from(second) != old_token
    assert delivery.complete_email_verification_delivery_outcome(
        SessionLocal, verification_id, "old-claim", "old-worker-token", True,
    ) == delivery.EmailVerificationCompletionOutcome.CLAIM_LOST
    assert client.post("/api/auth/verify-email", json={"token": old_token}).status_code == 400
    assert client.post("/api/auth/verify-email", json={"token": token_from(second)}).status_code == 200


@pytest.mark.parametrize("state", ["disabled", "verified", "federated"])
def test_ineligible_targets_rejected_without_token(verification_client, state):
    client, _actor_id, target_id = verification_client
    with SessionLocal() as db:
        if state == "federated":
            db.add(models.FederatedIdentity(user_id=target_id, provider="google", issuer="https://accounts.google.com", subject="synthetic-subject"))
        else:
            values = {"disabled_at": datetime.now(UTC)} if state == "disabled" else {"email_verified_at": datetime.now(UTC)}
            db.execute(update(models.User).where(models.User.id == target_id).values(**values))
        db.commit()
    assert issue(client, target_id).status_code == 409
    with SessionLocal() as db:
        assert db.query(models.EmailVerification).count() == db.query(models.OperatorAuditEvent).count() == 0


def test_authentication_csrf_and_strict_empty_body(verification_client):
    client, actor_id, target_id = verification_client
    assert issue(client, target_id, json={"email_verified_at": "now"}).status_code == 422
    assert issue(client, target_id + 10000).status_code == 404
    del client.headers[main.CSRF_HEADER_NAME]
    assert issue(client, target_id).status_code == 403
    client.headers[main.CSRF_HEADER_NAME] = "recovery-csrf"
    with SessionLocal() as db:
        db.execute(update(models.User).where(models.User.id == actor_id).values(role=models.UserRole.TEACHER, is_admin=True))
        db.commit()
    assert issue(client, target_id).status_code == 403
    client.cookies.clear()
    assert issue(client, target_id).status_code == 401


@pytest.mark.parametrize("mutation,expected", [("revoked", 401), ("expired", 401), ("disabled", 401), ("unverified", 401), ("demoted", 403)])
def test_stale_admin_rechecked_under_lock(verification_client, mutation, expected):
    client, actor_id, target_id = verification_client

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
        assert issue(client, target_id).status_code == expected
    finally:
        main.app.dependency_overrides.pop(main.get_current_user, None)
    with SessionLocal() as db:
        assert db.query(models.EmailVerification).count() == 0


def test_audit_failure_preserves_previous_link(verification_client, monkeypatch):
    import admin_account_recovery

    client, _actor_id, target_id = verification_client
    first = issue(client, target_id)
    assert first.status_code == 200

    def fail(*_args, **_kwargs):
        raise SQLAlchemyError("synthetic private database error")

    monkeypatch.setattr(admin_account_recovery, "record_operator_audit_event", fail)
    failed = issue(client, target_id)
    assert failed.status_code == 503 and "private database" not in failed.text
    assert "no-store" in failed.headers["cache-control"]
    assert client.post("/api/auth/verify-email", json={"token": token_from(first)}).status_code == 200
