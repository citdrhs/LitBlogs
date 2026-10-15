"""Teacher-assisted codes remain scoped, short-lived, audited capabilities."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select, text, update
from sqlalchemy.exc import SQLAlchemyError

import email_verification_delivery as delivery
import main
import models
import student_verification as verification
from database import SessionLocal, engine
from identity_controls import issue_browser_session

PASSWORD = "Synthetic-student-password-1!"
ALPHA = "alpha@example.com"
BETA = "beta@example.com"
LOOKUP = "/api/teacher/student-verifications/lookup"
ISSUE = "/api/teacher/student-verifications/codes"
REDEEM = "/api/auth/verify-student-code"


@pytest.fixture
def verification_client(client):
    with SessionLocal() as db:
        teacher = models.User(
            username="verification-teacher", email="teacher@example.com", password="unused-teacher-hash",
            role=models.UserRole.TEACHER, email_verified_at=datetime.now(UTC),
        )
        alpha = models.User(
            username="alpha", email=ALPHA, password=main.hash_password(PASSWORD),
            first_name="Alex", last_name="Reader", role=models.UserRole.STUDENT,
        )
        beta = models.User(
            username="beta", email=BETA, password=alpha.password,
            first_name="Blair", last_name="Writer", role=models.UserRole.STUDENT,
        )
        db.add_all([teacher, alpha, beta])
        db.flush()
        teacher_id, alpha_id, beta_id = teacher.id, alpha.id, beta.id
        issued = issue_browser_session(db, user_id=teacher_id, settings=main.settings)
        db.commit()
    client.cookies.set(main.settings.session_cookie_name, issued.token)
    client.cookies.set(main.settings.csrf_cookie_name, "verification-csrf")
    client.headers[main.CSRF_HEADER_NAME] = "verification-csrf"
    return client, teacher_id, alpha_id, beta_id


def issue(client, emails=None):
    return client.post(ISSUE, json={"emails": emails or [ALPHA]})


def login_pending(client, email=ALPHA):
    response = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 403
    assert not response.headers.get_list("set-cookie")
    return response.json()["detail"]["verification_challenge"]


def redeem(client, challenge, code):
    return client.post(REDEEM, json={"verification_challenge": challenge, "code": code})


def test_pending_login_has_narrow_challenge_and_never_a_browser_session(verification_client):
    client, _teacher_id, alpha_id, _beta_id = verification_client
    response = client.post("/api/auth/login", json={"email": ALPHA, "password": PASSWORD})
    assert response.status_code == 403
    detail = response.json()["detail"]
    assert set(detail) == {"code", "email", "verification_challenge", "expires_at", "teacher_code_allowed"}
    assert detail["code"] == "email_verification_required" and detail["email"] == ALPHA
    assert detail["teacher_code_allowed"] is True
    assert datetime.fromisoformat(detail["expires_at"]) <= datetime.now(UTC) + timedelta(minutes=15)
    assert "no-store" in response.headers["cache-control"]
    assert response.headers.get_list("set-cookie") == []
    with SessionLocal() as db:
        assert db.scalar(select(models.BrowserSession.id).where(models.BrowserSession.user_id == alpha_id)) is None
    client.cookies.clear()
    assert client.get("/api/auth/session", headers={"Authorization": f"Bearer {detail['verification_challenge']}"}).status_code == 401


@pytest.mark.parametrize("state", ["unknown", "wrong-password", "disabled"])
def test_invalid_credentials_remain_generic(verification_client, state):
    client, _teacher_id, alpha_id, _beta_id = verification_client
    if state == "disabled":
        with SessionLocal() as db:
            db.execute(update(models.User).where(models.User.id == alpha_id).values(disabled_at=datetime.now(UTC)))
            db.commit()
    response = client.post("/api/auth/login", json={
        "email": "unknown@example.com" if state == "unknown" else ALPHA,
        "password": "wrong-password" if state == "wrong-password" else PASSWORD,
    })
    assert response.status_code == 401 and response.json() == {"detail": "Invalid email or password"}
    assert response.headers.get_list("set-cookie") == []


@pytest.mark.parametrize("role", [models.UserRole.TEACHER, models.UserRole.ADMIN])
def test_pending_nonstudent_has_no_code_challenge(verification_client, role):
    client, _teacher_id, alpha_id, _beta_id = verification_client
    with SessionLocal() as db:
        db.execute(update(models.User).where(models.User.id == alpha_id).values(role=role))
        db.commit()
    response = client.post("/api/auth/login", json={"email": ALPHA, "password": PASSWORD})
    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["teacher_code_allowed"] is False
    assert detail["verification_challenge"] is detail["expires_at"] is None


def test_exact_email_lookup_normalizes_deduplicates_and_avoids_directory(verification_client):
    client, _teacher_id, alpha_id, _beta_id = verification_client
    response = client.post(LOOKUP, json={"emails": ["ALPHA@example.com", ALPHA, "missing@example.com"]})
    assert response.status_code == 200
    assert response.json() == {"students": [{
        "id": alpha_id, "email": ALPHA, "first_name": "Alex", "last_name": "Reader", "username": "alpha",
    }], "unmatched_count": 1}
    assert "no-store" in response.headers["cache-control"]
    for payload in ({}, {"emails": []}, {"emails": ["alpha"]}, {"emails": [ALPHA] * 26}, {"emails": [ALPHA], "all": True}):
        assert client.post(LOOKUP, json=payload).status_code == 422
    assert client.get(LOOKUP).status_code == 405


@pytest.mark.parametrize("state", ["verified", "disabled", "teacher", "admin", "federated", "outside-school"])
def test_lookup_and_issuance_exclude_ineligible_accounts(verification_client, state):
    client, _teacher_id, alpha_id, _beta_id = verification_client
    email = ALPHA
    with SessionLocal() as db:
        values = {}
        if state == "verified":
            values["email_verified_at"] = datetime.now(UTC)
        elif state == "disabled":
            values["disabled_at"] = datetime.now(UTC)
        elif state in {"teacher", "admin"}:
            values["role"] = models.UserRole[state.upper()]
        elif state == "outside-school":
            email = "alpha@outside.edu"
            values["email"] = email
        else:
            db.add(models.FederatedIdentity(user_id=alpha_id, provider="google", issuer="https://accounts.google.com", subject="synthetic"))
        if values:
            db.execute(update(models.User).where(models.User.id == alpha_id).values(**values))
        db.commit()
    assert client.post(LOOKUP, json={"emails": [email]}).json() == {"students": [], "unmatched_count": 1}
    assert issue(client, [email]).status_code == 409


def test_codes_are_private_account_bound_audited_and_do_not_send_email(verification_client, monkeypatch, caplog):
    client, teacher_id, alpha_id, beta_id = verification_client
    monkeypatch.setattr(delivery, "send_email_verification_email", lambda *_a: pytest.fail("Code flow must not send email"))
    monkeypatch.setattr(main, "send_password_reset_email", lambda *_a: pytest.fail("Code flow must not send email"))
    challenge = login_pending(client)
    before = datetime.now(UTC)
    response = issue(client, [ALPHA, BETA])
    assert response.status_code == 200
    codes = response.json()["codes"]
    assert [entry["student_id"] for entry in codes] == [alpha_id, beta_id]
    assert "no-store" in response.headers["cache-control"]
    code = codes[0]["code"]
    assert len(code) == 6 and code.isascii() and code.isdigit()
    expiry = datetime.fromisoformat(codes[0]["expires_at"].replace("Z", "+00:00"))
    assert before + timedelta(minutes=15) <= expiry <= datetime.now(UTC) + timedelta(minutes=15)
    with SessionLocal() as db:
        row = db.query(models.StudentVerificationCode).filter_by(student_id=alpha_id).one()
        assert row.code_digest == verification._code_digest(alpha_id, ALPHA, code, settings=main.settings)
        assert row.code_digest != hashlib.sha256(code.encode()).hexdigest() and code not in row.code_digest
        assert row.attempts == 0 and row.consumed_at is None and row.issuer_id == teacher_id
        assert db.query(models.EmailVerification).count() == 0
        assert db.query(models.OperatorAuditEvent).count() == 2
        assert db.get(models.User, alpha_id).email_verified_at is None
    result = redeem(client, challenge, code)
    assert result.status_code == 200 and result.json() == {"message": "Email verified successfully"}
    assert not result.headers.get_list("set-cookie")
    assert redeem(client, challenge, code).status_code == 400
    with SessionLocal() as db:
        assert db.get(models.User, alpha_id).email_verified_at is not None
        row = db.query(models.StudentVerificationCode).filter_by(student_id=alpha_id).one()
        assert row.code_digest is None and row.consumed_at is not None and row.attempts == 1
        assert db.scalar(select(models.BrowserSession.id).where(models.BrowserSession.user_id == alpha_id)) is None
        assert db.query(models.EmailVerification).count() == 0
        audit = db.query(models.OperatorAuditEvent).filter_by(action="STUDENT_VERIFICATION_CODE_CONSUMED").one()
        assert audit.actor_identifier == f"student-user:{alpha_id}" and audit.resource_digest != ALPHA
    assert challenge not in caplog.text and code not in caplog.text and ALPHA not in caplog.text
    assert client.post("/api/auth/login", json={"email": ALPHA, "password": PASSWORD}).status_code == 200


def test_bulk_issue_is_all_or_nothing(verification_client):
    client, _teacher_id, _alpha_id, beta_id = verification_client
    assert client.post(LOOKUP, json={"emails": [ALPHA, BETA]}).status_code == 200
    with SessionLocal() as db:
        db.execute(update(models.User).where(models.User.id == beta_id).values(email_verified_at=datetime.now(UTC)))
        db.commit()
    assert issue(client, [ALPHA, BETA]).status_code == 409
    with SessionLocal() as db:
        assert db.query(models.StudentVerificationCode).count() == db.query(models.OperatorAuditEvent).count() == 0


def test_reissue_replaces_old_code_and_attempts_survive_relogin(verification_client):
    client, _teacher_id, alpha_id, _beta_id = verification_client
    challenge = login_pending(client)
    old_code = issue(client).json()["codes"][0]["code"]
    new_code = issue(client).json()["codes"][0]["code"]
    assert new_code != old_code
    assert redeem(client, challenge, old_code).status_code == 400
    wrong_code = "000000" if new_code != "000000" else "111111"
    for _ in range(4):
        challenge = login_pending(client)
        assert redeem(client, challenge, wrong_code).status_code == 400
    assert redeem(client, login_pending(client), new_code).status_code == 400
    with SessionLocal() as db:
        assert db.query(models.StudentVerificationCode).one().attempts == 5
        assert db.get(models.User, alpha_id).email_verified_at is None
    replacement = issue(client).json()["codes"][0]["code"]
    assert redeem(client, login_pending(client), replacement).status_code == 200


def test_code_is_bound_to_selected_account(verification_client):
    client, _teacher_id, alpha_id, beta_id = verification_client
    code = issue(client).json()["codes"][0]["code"]
    assert redeem(client, login_pending(client, BETA), code).status_code == 400
    with SessionLocal() as db:
        assert db.get(models.User, beta_id).email_verified_at is None
        assert db.query(models.StudentVerificationCode).filter_by(student_id=alpha_id).one().attempts == 0


def test_changing_email_invalidates_previously_issued_code(verification_client):
    client, _teacher_id, alpha_id, _beta_id = verification_client
    code = issue(client).json()["codes"][0]["code"]
    with SessionLocal() as db:
        db.execute(update(models.User).where(models.User.id == alpha_id).values(email="renamed@example.com"))
        db.commit()
    challenge = login_pending(client, "renamed@example.com")
    assert redeem(client, challenge, code).status_code == 400


@pytest.mark.parametrize("mutation", ["expired-code", "expired-challenge", "changed-password", "disabled-student", "changed-role", "disabled-issuer", "demoted-issuer"])
def test_expiry_and_current_account_state_are_enforced(verification_client, mutation):
    client, teacher_id, alpha_id, _beta_id = verification_client
    challenge = login_pending(client)
    code = issue(client).json()["codes"][0]["code"]
    if mutation == "expired-challenge":
        claims = jwt.decode(challenge, options={"verify_signature": False})
        claims["iat"] = claims["nbf"] = int((datetime.now(UTC) - timedelta(hours=1)).timestamp())
        claims["exp"] = int((datetime.now(UTC) - timedelta(minutes=1)).timestamp())
        challenge = jwt.encode(claims, verification._derived_key(main.settings, b"challenge-signing"), algorithm="HS256")
    else:
        with SessionLocal() as db:
            if mutation == "expired-code":
                db.execute(update(models.StudentVerificationCode).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
            else:
                target = teacher_id if mutation.endswith("issuer") else alpha_id
                values = {"password": "replacement-password-hash"} if mutation == "changed-password" else (
                    {"role": models.UserRole.STUDENT if mutation == "demoted-issuer" else models.UserRole.TEACHER}
                    if "role" in mutation or mutation == "demoted-issuer" else {"disabled_at": datetime.now(UTC)}
                )
                db.execute(update(models.User).where(models.User.id == target).values(**values))
            db.commit()
    response = redeem(client, challenge, code)
    assert response.status_code == 400 and response.json() == {"detail": verification.INVALID_CODE_DETAIL}
    with SessionLocal() as db:
        assert db.get(models.User, alpha_id).email_verified_at is None


@pytest.mark.parametrize("payload", [
    {}, {"verification_challenge": "private-challenge", "code": "12345"},
    {"verification_challenge": "private-challenge", "code": "１２３４５６"},
    {"verification_challenge": "private-challenge", "code": "123456", "email": ALPHA},
])
def test_redemption_validation_never_echoes_secrets(verification_client, payload):
    client, *_rest = verification_client
    response = client.post(REDEEM, json=payload)
    assert response.status_code == 400 and response.json() == {"detail": verification.INVALID_CODE_DETAIL}
    assert "private-challenge" not in response.text


def test_normal_session_and_tampered_challenges_are_rejected(verification_client):
    client, *_rest = verification_client
    challenge = login_pending(client)
    code = issue(client).json()["codes"][0]["code"]
    assert redeem(client, main.create_access_token({"sub": "2"}), code).status_code == 400
    assert redeem(client, "x" + challenge[1:], code).status_code == 400


def test_email_link_and_teacher_code_are_mutually_exclusive(verification_client):
    client, _teacher_id, alpha_id, _beta_id = verification_client
    challenge = login_pending(client)
    code = issue(client).json()["codes"][0]["code"]
    with SessionLocal() as db:
        db.add(models.EmailVerification(
            user_id=alpha_id, token_digest=delivery.email_verification_token_digest("email-link"),
            delivery_status="DELIVERED", expires_at=datetime.now(UTC) + timedelta(hours=1),
        ))
        db.commit()
    assert client.post("/api/auth/verify-email", json={"token": "email-link"}).status_code == 200
    assert redeem(client, challenge, code).status_code == 400


@pytest.mark.skipif(engine.dialect.name != "postgresql", reason="PostgreSQL session timezone regression")
def test_email_link_verification_uses_the_same_instant_in_non_utc_database_timezone(verification_client):
    client, _teacher_id, alpha_id, _beta_id = verification_client
    with SessionLocal() as db:
        db.add(models.EmailVerification(
            user_id=alpha_id, token_digest=delivery.email_verification_token_digest("timezone-email-link"),
            delivery_status="DELIVERED", expires_at=datetime.now(UTC) + timedelta(minutes=2),
        ))
        db.commit()

    def shifted_database_timezone():
        with SessionLocal() as db:
            db.execute(text("SET LOCAL TIME ZONE 'Pacific/Honolulu'"))
            yield db

    main.app.dependency_overrides[main.get_db] = shifted_database_timezone
    try:
        response = client.post("/api/auth/verify-email", json={"token": "timezone-email-link"})
    finally:
        main.app.dependency_overrides.pop(main.get_db, None)
    assert response.status_code == 200
    assert client.post("/api/auth/verify-email", json={"token": "timezone-email-link"}).status_code == 400


def test_code_success_invalidates_email_token_and_worker_claim(verification_client):
    client, _teacher_id, alpha_id, _beta_id = verification_client
    challenge = login_pending(client)
    code = issue(client).json()["codes"][0]["code"]
    with SessionLocal() as db:
        row = models.EmailVerification(
            user_id=alpha_id, token_digest=delivery.email_verification_token_digest("email-link"),
            delivery_status="PROCESSING", expires_at=datetime.now(UTC) + timedelta(hours=1),
            delivery_claim_digest=delivery.email_verification_claim_digest("old-claim"), delivery_attempted_at=datetime.now(UTC),
        )
        db.add(row)
        db.flush()
        row_id = row.id
        db.commit()
    assert redeem(client, challenge, code).status_code == 200
    assert delivery.complete_email_verification_delivery_outcome(SessionLocal, row_id, "old-claim", "old-token", True) == delivery.EmailVerificationCompletionOutcome.CLAIM_LOST
    assert client.post("/api/auth/verify-email", json={"token": "email-link"}).status_code == 400


@pytest.mark.parametrize("endpoint", [LOOKUP, ISSUE])
def test_teacher_routes_enforce_authentication_roles_and_csrf(verification_client, endpoint):
    client, teacher_id, _alpha_id, _beta_id = verification_client
    del client.headers[main.CSRF_HEADER_NAME]
    assert client.post(endpoint, json={"emails": [ALPHA]}).status_code == 403
    client.headers[main.CSRF_HEADER_NAME] = "verification-csrf"
    with SessionLocal() as db:
        db.execute(update(models.User).where(models.User.id == teacher_id).values(role=models.UserRole.STUDENT, is_admin=True))
        db.commit()
    assert client.post(endpoint, json={"emails": [ALPHA]}).status_code == 403
    client.cookies.clear()
    assert client.post(endpoint, json={"emails": [ALPHA]}).status_code == 401


def test_admins_can_assist_students(verification_client):
    client, teacher_id, _alpha_id, _beta_id = verification_client
    with SessionLocal() as db:
        db.execute(update(models.User).where(models.User.id == teacher_id).values(role=models.UserRole.ADMIN))
        db.commit()
    assert issue(client).status_code == 200


@pytest.mark.parametrize("mutation,expected", [("revoked", 401), ("expired", 401), ("disabled", 401), ("unverified", 401), ("demoted", 403)])
def test_stale_teacher_is_rechecked_under_lock(verification_client, mutation, expected):
    client, teacher_id, _alpha_id, _beta_id = verification_client

    async def stale_actor(request: Request, db=Depends(main.get_db)):
        actor = await main.get_current_user(request, None, db)
        with SessionLocal() as other:
            if mutation in {"revoked", "expired"}:
                values = {"revoked_at": datetime.now(UTC)} if mutation == "revoked" else {"expires_at": datetime.now(UTC) - timedelta(seconds=1)}
                other.execute(update(models.BrowserSession).where(models.BrowserSession.user_id == teacher_id).values(**values))
            else:
                values = {"disabled_at": datetime.now(UTC)} if mutation == "disabled" else {"email_verified_at": None} if mutation == "unverified" else {"role": models.UserRole.STUDENT}
                other.execute(update(models.User).where(models.User.id == teacher_id).values(**values))
            other.commit()
        return actor

    main.app.dependency_overrides[main.get_current_user] = stale_actor
    try:
        assert issue(client).status_code == expected
    finally:
        main.app.dependency_overrides.pop(main.get_current_user, None)
    with SessionLocal() as db:
        assert db.query(models.StudentVerificationCode).count() == 0


@pytest.mark.parametrize("operation", ["issue", "consume"])
def test_audit_failure_rolls_back_code_and_account(verification_client, monkeypatch, operation):
    client, _teacher_id, alpha_id, _beta_id = verification_client
    challenge = login_pending(client)
    code = issue(client).json()["codes"][0]["code"]

    def fail(*_args, **_kwargs):
        raise SQLAlchemyError("synthetic private database failure")

    monkeypatch.setattr(verification, "record_operator_audit_event", fail)
    response = issue(client) if operation == "issue" else redeem(client, challenge, code)
    assert response.status_code == 503 and "private database" not in response.text
    with SessionLocal() as db:
        row = db.query(models.StudentVerificationCode).one()
        assert row.code_digest == verification._code_digest(alpha_id, ALPHA, code, settings=main.settings)
        assert row.attempts == 0 and row.consumed_at is None
        assert db.get(models.User, alpha_id).email_verified_at is None


def test_admin_disable_reenable_does_not_revive_issued_codes(verification_client):
    client, teacher_id, alpha_id, _beta_id = verification_client
    challenge = login_pending(client)
    code = issue(client).json()["codes"][0]["code"]
    with SessionLocal() as db:
        db.execute(update(models.User).where(models.User.id == teacher_id).values(role=models.UserRole.ADMIN))
        db.commit()
    assert client.put(f"/api/users/{alpha_id}/status", json={"disabled": True}).status_code == 200
    assert client.put(f"/api/users/{alpha_id}/status", json={"disabled": False}).status_code == 200
    assert redeem(client, challenge, code).status_code == 400


@pytest.mark.skipif(engine.dialect.name != "postgresql", reason="Concurrent row locking requires PostgreSQL")
def test_concurrent_code_redemption_has_one_winner(verification_client):
    client, _teacher_id, alpha_id, _beta_id = verification_client
    challenge = login_pending(client)
    code = issue(client).json()["codes"][0]["code"]

    def consume(_index):
        with SessionLocal() as db:
            try:
                verification.consume_student_verification_code(db, verification_challenge=challenge, code=code, settings=main.settings)
                return 200
            except HTTPException as exc:
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(consume, range(2))) == [200, 400]
    with SessionLocal() as db:
        assert db.get(models.User, alpha_id).email_verified_at is not None
        assert db.query(models.StudentVerificationCode).one().attempts == 1
