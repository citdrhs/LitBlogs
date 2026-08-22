import inspect
import logging
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from dotenv import dotenv_values
from fastapi import HTTPException
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm
from pydantic import ValidationError
from settings_test_support import production_upload_settings
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession

import main
import models
import oauth_security
from auth_security import decode_access_token, hash_password
from config import Settings
from database import SessionLocal
from identity_controls import create_teacher_invitation

MICROSOFT_TENANT_ID = "871bd3e0-2dc0-4a40-9b07-9d03068c2364"
SYNTHETIC_MICROSOFT_AUDIENCE = "2f1c67a1-91e2-46a3-941f-b88e31763e51"
SYNTHETIC_GOOGLE_AUDIENCE = "987654321.apps.googleusercontent.com"
ALLOWED_DOMAIN = "school.example"
KEY_ID = "synthetic-microsoft-key"
GOOGLE_ISSUER = "https://accounts.google.com"
MICROSOFT_ISSUER = f"https://login.microsoftonline.com/{MICROSOFT_TENANT_ID}/v2.0"


@pytest.fixture
def oauth_settings(monkeypatch):
    reset_google_cache = getattr(oauth_security, "reset_google_request_cache", None)
    if callable(reset_google_cache):
        reset_google_cache()
    reset_jwks_cache = getattr(oauth_security, "reset_microsoft_jwk_client_cache", None)
    if callable(reset_jwks_cache):
        reset_jwks_cache()
    data = main.settings.model_dump()
    data.update(
        {
            "google_client_id": SYNTHETIC_GOOGLE_AUDIENCE,
            "microsoft_client_id": SYNTHETIC_MICROSOFT_AUDIENCE,
            "microsoft_tenant_id": MICROSOFT_TENANT_ID,
            "microsoft_allowed_tenant_ids": (MICROSOFT_TENANT_ID,),
            "allowed_email_domains": (ALLOWED_DOMAIN,),
            "oauth_http_timeout_seconds": 2.0,
            "oauth_jwks_cache_seconds": 300,
        }
    )
    selected = Settings(**data)
    monkeypatch.setattr(main, "settings", selected)
    return selected


@pytest.fixture(scope="module")
def microsoft_keys():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    jwk.update({"kid": KEY_ID, "use": "sig", "alg": "RS256"})
    return private_key, other_private_key, {"keys": [jwk]}


def _create_user(email: str, *, role: models.UserRole = models.UserRole.STUDENT) -> int:
    with SessionLocal() as db:
        user = models.User(
            username=f"oauth-{secrets.token_hex(6)}",
            email=email,
            password=hash_password("synthetic-oauth-password"),
            first_name="Existing",
            last_name="User",
            role=role,
            is_admin=role == models.UserRole.ADMIN,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user.id


def _bind_identity(
    user_id: int,
    *,
    provider: str,
    issuer: str,
    subject: str,
) -> None:
    with SessionLocal() as db:
        db.add(
            models.FederatedIdentity(
                provider=provider,
                issuer=issuer,
                subject=subject,
                user_id=user_id,
            )
        )
        db.commit()


def _create_teacher_invitation(email: str, settings: Settings) -> str:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    with SessionLocal() as db:
        token = create_teacher_invitation(
            db,
            email=email,
            created_by="oauth-security-test-operator",
            expires_at=now + timedelta(hours=1),
            settings=settings,
            now=now,
        )
        db.commit()
        return token


def _google_claims(**overrides) -> dict:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    claims = {
        "iss": "https://accounts.google.com",
        "aud": SYNTHETIC_GOOGLE_AUDIENCE,
        "sub": "google-subject-123",
        "email": f"learner@{ALLOWED_DOMAIN}",
        "email_verified": True,
        "hd": ALLOWED_DOMAIN,
        "given_name": "Google",
        "family_name": "Learner",
        "iat": int((now - timedelta(seconds=5)).timestamp()),
        "nbf": int((now - timedelta(seconds=5)).timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
    }
    claims.update(overrides)
    return claims


def _install_google_claims(monkeypatch, claims: dict) -> None:
    def verify(token, request, audience, **kwargs):
        assert token == "synthetic-google-id-token"
        assert request is not None
        assert audience == SYNTHETIC_GOOGLE_AUDIENCE
        return claims.copy()

    monkeypatch.setattr(main.id_token, "verify_oauth2_token", verify)


def _microsoft_claims(**overrides) -> dict:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    claims = {
        "iss": f"https://login.microsoftonline.com/{MICROSOFT_TENANT_ID}/v2.0",
        "aud": SYNTHETIC_MICROSOFT_AUDIENCE,
        "tid": MICROSOFT_TENANT_ID,
        "sub": "microsoft-subject-123",
        "email": f"learner@{ALLOWED_DOMAIN}",
        "given_name": "Microsoft",
        "family_name": "Learner",
        "iat": int((now - timedelta(seconds=5)).timestamp()),
        "nbf": int((now - timedelta(seconds=5)).timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
    }
    claims.update(overrides)
    return claims


def _microsoft_token(private_key, claims: dict | None = None, *, algorithm: str = "RS256") -> str:
    selected_claims = claims or _microsoft_claims()
    if algorithm == "none":
        return jwt.encode(selected_claims, key="", algorithm="none", headers={"kid": KEY_ID})
    if algorithm == "HS256":
        return jwt.encode(
            selected_claims,
            key="synthetic-wrong-algorithm-secret",
            algorithm="HS256",
            headers={"kid": KEY_ID},
        )
    return jwt.encode(
        selected_claims,
        key=private_key,
        algorithm="RS256",
        headers={"kid": KEY_ID},
    )


def _install_microsoft_jwks(monkeypatch, jwks: dict, requested_urls: list[str] | None = None):
    def fetch_data(client):
        if requested_urls is not None:
            requested_urls.append(client.uri)
        return jwks

    monkeypatch.setattr(jwt.PyJWKClient, "fetch_data", fetch_data)


def _assert_safe_session(response, *, expected_role: str) -> None:
    assert response.status_code == 200
    payload = response.json()
    assert payload["role"] == expected_role
    assert set(payload).isdisjoint({"token", "access_token", "idToken", "password"})
    assert main.settings.session_cookie_name in response.cookies
    session_header = next(
        value
        for value in response.headers.get_list("set-cookie")
        if value.startswith(f"{main.settings.session_cookie_name}=")
    )
    assert "httponly" in session_header.lower()


def _production_settings_data(**overrides) -> dict:
    data = {
        "app_env": "production",
        "database_url": (
            f"postgresql://litblog_app:{secrets.token_urlsafe(24)}@database.internal/litblog"
            "?sslmode=verify-full&sslrootcert=/etc/litblogs/postgres-root-ca.pem"
        ),
        "secret_key": secrets.token_urlsafe(48),
        "jwt_issuer": "https://api.litblogs.school.edu",
        "jwt_audience": "litblogs.school.edu",
        "frontend_url": "https://litblogs.school.edu",
        "cors_allowed_origins": ("https://litblogs.school.edu",),
        "allowed_hosts": ("litblogs.school.edu",),
        "allowed_email_domains": ("school.edu",),
        "google_client_id": SYNTHETIC_GOOGLE_AUDIENCE,
        "microsoft_client_id": SYNTHETIC_MICROSOFT_AUDIENCE,
        "microsoft_tenant_id": MICROSOFT_TENANT_ID,
        "microsoft_allowed_tenant_ids": (MICROSOFT_TENANT_ID,),
        "session_cookie_name": "__Host-litblog-session",
        "csrf_cookie_name": "__Host-litblog-csrf",
        "session_cookie_secure": True,
        "teacher_invite_hmac_key": secrets.token_urlsafe(48),
        "admin_access_code": secrets.token_urlsafe(24),
        "admin_code": secrets.token_urlsafe(24),
        "email_host": "smtp.school.edu",
        "email_username": "litblog-reset",
        "email_password": secrets.token_urlsafe(24),
        "email_from": "no-reply@school.edu",
        "password_reset_worker_enabled": True,
        "local_password_registration_enabled": False,
        **production_upload_settings(),
    }
    data.update(overrides)
    return data


def test_backend_configuration_has_no_microsoft_confidential_secret_and_accepts_public_client_config():
    assert "microsoft_client_secret" not in Settings.model_fields
    settings = Settings(**_production_settings_data())
    assert settings.microsoft_client_id == SYNTHETIC_MICROSOFT_AUDIENCE


@pytest.mark.parametrize("tenant", ["common", "organizations", "consumers", "not-a-guid"])
def test_production_rejects_untrusted_microsoft_tenant_aliases(tenant):
    with pytest.raises(ValidationError, match="MICROSOFT_TENANT_ID"):
        Settings(**_production_settings_data(microsoft_tenant_id=tenant))


def test_production_requires_an_oauth_email_domain_allowlist():
    with pytest.raises(ValidationError, match="ALLOWED_EMAIL_DOMAINS"):
        Settings(**_production_settings_data(allowed_email_domains=()))


def test_shipped_oauth_placeholders_are_explicit_and_fail_production_closed():
    values = dotenv_values(Path(__file__).resolve().parents[1] / ".env.example")
    shipped = {
        "allowed_email_domains": values.get("ALLOWED_EMAIL_DOMAINS"),
        "google_client_id": values.get("GOOGLE_CLIENT_ID"),
        "microsoft_client_id": values.get("MICROSOFT_CLIENT_ID"),
        "microsoft_tenant_id": values.get("MICROSOFT_TENANT_ID"),
        "microsoft_allowed_tenant_ids": values.get("MICROSOFT_ALLOWED_TENANT_IDS"),
    }

    assert shipped == {
        "allowed_email_domains": "replace-with-approved-domain",
        "google_client_id": "replace-with-google-client-id",
        "microsoft_client_id": "replace-with-microsoft-client-id",
        "microsoft_tenant_id": "replace-with-microsoft-tenant-id",
        "microsoft_allowed_tenant_ids": "replace-with-approved-microsoft-tenant-id",
    }
    with pytest.raises(ValidationError):
        Settings(**_production_settings_data(**shipped))


def test_removed_microsoft_confidential_exchange_route_is_absent():
    assert "/api/auth/microsoft-token" not in {route.path for route in main.app.routes}


def test_public_admin_code_verification_route_is_absent():
    assert "/api/verify-admin-code" not in {route.path for route in main.app.routes}


def test_public_role_update_escalation_route_is_absent():
    assert "/api/update-role" not in {route.path for route in main.app.routes}


def test_public_password_registration_rejects_admin_even_with_valid_code(
    client, oauth_settings
):
    response = client.post(
        "/api/auth/register",
        json={
            "username": "public-admin-attempt",
            "email": f"public-admin@{ALLOWED_DOMAIN}",
            "password": "Synthetic-password-123!",
            "first_name": "Public",
            "last_name": "Admin",
            "role": "ADMIN",
        },
    )

    assert response.status_code == 202
    assert response.json() == {
        "message": "If registration can be completed, sign in with the submitted credentials."
    }
    assert response.headers.get_list("set-cookie") == []
    with SessionLocal() as db:
        assert db.query(models.User).count() == 0


def test_forged_microsoft_profile_json_is_rejected_before_identity_lookup(client, oauth_settings):
    forged_email = f"attacker@{ALLOWED_DOMAIN}"
    response = client.post(
        "/api/auth/microsoft-login",
        json={
            "msUserData": {
                "email": forged_email,
                "firstName": "Forged",
                "lastName": "Profile",
                "microsoftId": "forged-id",
            }
        },
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "External authentication failed"}
    assert forged_email not in response.text


def test_google_timing_failure_cannot_fall_back_to_unsigned_claims(
    client, oauth_settings, monkeypatch
):
    unsigned = jwt.encode(_google_claims(), key="", algorithm="none")

    def reject(*_args, **_kwargs):
        raise ValueError("Token used too early")

    monkeypatch.setattr(main.id_token, "verify_oauth2_token", reject)
    response = client.post("/api/auth/google-signup", json={"idToken": unsigned})

    assert response.status_code == 401
    assert response.json() == {"detail": "External authentication failed"}
    with SessionLocal() as db:
        assert db.query(models.User).count() == 0


@pytest.mark.parametrize(
    "claim_overrides",
    [
        {"aud": "wrong-google-client"},
        {"iss": "https://evil.example"},
        {"sub": ""},
        {"email": ""},
        {"email_verified": False},
        {"hd": "other.example", "email": "learner@other.example"},
        {"exp": 1},
        {"iat": int((datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp())},
        {"nbf": int((datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp())},
    ],
    ids=[
        "wrong-audience",
        "wrong-issuer",
        "missing-subject",
        "missing-email",
        "unverified-email",
        "wrong-domain",
        "expired",
        "future-issued-at",
        "not-yet-valid",
    ],
)
def test_google_rejects_invalid_verified_claim_sets(
    client, oauth_settings, monkeypatch, claim_overrides
):
    _install_google_claims(monkeypatch, _google_claims(**claim_overrides))

    response = client.post(
        "/api/auth/google-signup",
        json={"idToken": "synthetic-google-id-token"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "External authentication failed"}


def test_google_provider_http_exception_status_is_not_swallowed(
    client, oauth_settings, monkeypatch
):
    def reject(*_args, **_kwargs):
        raise HTTPException(status_code=429, detail="External authentication unavailable")

    monkeypatch.setattr(main.id_token, "verify_oauth2_token", reject)
    response = client.post(
        "/api/auth/google-login",
        json={"idToken": "synthetic-google-id-token"},
    )

    assert response.status_code == 429
    assert response.json() == {"detail": "External authentication unavailable"}


def test_google_reuses_a_bounded_thread_safe_certificate_cache(
    oauth_settings,
    monkeypatch,
):
    reset_google_cache = getattr(oauth_security, "reset_google_request_cache", None)
    assert callable(reset_google_cache)
    if not callable(reset_google_cache):
        return

    calls = []
    calls_lock = threading.Lock()
    start_together = threading.Barrier(2)

    class SyntheticResponse:
        status = 200
        data = b"{}"
        headers = {"cache-control": "public, max-age=3600"}

    class RecordingTransport:
        def __call__(self, url, *, method="GET", timeout=None, **_kwargs):
            with calls_lock:
                calls.append({"url": url, "method": method, "timeout": timeout})
            time.sleep(0.05)
            return SyntheticResponse()

    monkeypatch.setattr(
        oauth_security.google_requests,
        "Request",
        lambda: RecordingTransport(),
    )
    reset_google_cache()
    seen_requests = []

    def verify(_token, request, _audience, **_kwargs):
        seen_requests.append(request)
        start_together.wait(timeout=2)
        response = request(oauth_security.GOOGLE_OAUTH2_CERTS_URL)
        assert response.status == 200
        return _google_claims()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                oauth_security.verify_google_id_token,
                "synthetic-google-id-token",
                settings=oauth_settings,
                verifier=verify,
            )
            for _ in range(2)
        ]
        claims = [future.result(timeout=3) for future in futures]

    assert [claim["sub"] for claim in claims] == [
        "google-subject-123",
        "google-subject-123",
    ]
    assert seen_requests[0] is seen_requests[1]
    assert calls == [
        {
            "url": oauth_security.GOOGLE_OAUTH2_CERTS_URL,
            "method": "GET",
            "timeout": oauth_settings.oauth_http_timeout_seconds,
        }
    ]


def test_google_concurrent_provider_failure_uses_short_backoff_and_stays_generic(
    client,
    oauth_settings,
    monkeypatch,
    caplog,
):
    reset_google_cache = oauth_security.reset_google_request_cache
    calls = []
    calls_lock = threading.Lock()
    start_together = threading.Barrier(2)
    sensitive_token = "sensitive-google-outage-token"
    sensitive_error = "synthetic-provider-outage-detail"

    class FailingTransport:
        def __call__(self, url, *, method="GET", timeout=None, **_kwargs):
            with calls_lock:
                calls.append({"url": url, "method": method, "timeout": timeout})
            time.sleep(0.05)
            raise RuntimeError(sensitive_error)

    def verify(token, request, audience, **_kwargs):
        assert token == sensitive_token
        assert audience == SYNTHETIC_GOOGLE_AUDIENCE
        start_together.wait(timeout=2)
        request(oauth_security.GOOGLE_OAUTH2_CERTS_URL)
        raise AssertionError("unreachable")

    monkeypatch.setattr(
        oauth_security.google_requests,
        "Request",
        lambda: FailingTransport(),
    )
    monkeypatch.setattr(main.id_token, "verify_oauth2_token", verify)
    reset_google_cache()
    first_client = TestClient(main.app)
    second_client = TestClient(main.app)
    caplog.set_level(logging.DEBUG)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    selected_client.post,
                    "/api/auth/google-login",
                    json={"idToken": sensitive_token},
                )
                for selected_client in (first_client, second_client)
            ]
            responses = [future.result(timeout=5) for future in futures]
    finally:
        first_client.close()
        second_client.close()

    for response in responses:
        assert response.status_code == 401
        assert response.json() == {"detail": "External authentication failed"}
        assert sensitive_token not in response.text
        assert sensitive_error not in response.text
    assert calls == [
        {
            "url": oauth_security.GOOGLE_OAUTH2_CERTS_URL,
            "method": "GET",
            "timeout": oauth_settings.oauth_http_timeout_seconds,
        }
    ]
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert sensitive_token not in logged
    assert sensitive_error not in logged


def test_google_provider_failure_backoff_is_short_and_expires():
    now = [100.0]
    attempts = []

    def fail(_url, **_kwargs):
        attempts.append(now[0])
        raise RuntimeError("synthetic provider detail")

    request = oauth_security._BoundedGoogleCertRequest(
        cache_seconds=300,
        timeout_seconds=2.0,
        transport=fail,
        monotonic=lambda: now[0],
    )

    for _ in range(2):
        with pytest.raises(
            oauth_security.OAuthVerificationError,
            match="^Google certificate service unavailable$",
        ):
            request(oauth_security.GOOGLE_OAUTH2_CERTS_URL)
    assert attempts == [100.0]
    assert 0 < oauth_security.GOOGLE_CERT_FAILURE_BACKOFF_SECONDS <= 5

    now[0] += oauth_security.GOOGLE_CERT_FAILURE_BACKOFF_SECONDS + 0.001
    with pytest.raises(oauth_security.OAuthVerificationError):
        request(oauth_security.GOOGLE_OAUTH2_CERTS_URL)
    assert attempts == [100.0, now[0]]


def test_oauth_routes_run_blocking_provider_verification_off_the_event_loop():
    routes = {
        route.path: route.endpoint
        for route in main.app.routes
        if hasattr(route, "endpoint")
    }

    for path in (
        "/api/auth/google-login",
        "/api/auth/google-signup",
        "/api/auth/microsoft-login",
        "/api/auth/microsoft-signup",
    ):
        assert not inspect.iscoroutinefunction(routes[path]), path


def test_google_signup_defaults_to_student_and_issues_only_protected_session_metadata(
    client, oauth_settings, monkeypatch
):
    _install_google_claims(monkeypatch, _google_claims())

    response = client.post(
        "/api/auth/google-signup",
        json={"idToken": "synthetic-google-id-token"},
    )

    _assert_safe_session(response, expected_role="STUDENT")
    with SessionLocal() as db:
        user = db.query(models.User).one()
        assert user.role == models.UserRole.STUDENT
        assert user.is_admin is False
        identity = db.query(models.FederatedIdentity).one()
        assert identity.provider == "google"
        assert identity.issuer == GOOGLE_ISSUER
        assert identity.subject == "google-subject-123"
        assert identity.user_id == user.id


def test_google_accepts_canonical_claims_without_optional_nbf(
    client, oauth_settings, monkeypatch
):
    claims = _google_claims()
    claims.pop("nbf")
    _install_google_claims(monkeypatch, claims)

    response = client.post(
        "/api/auth/google-signup",
        json={"idToken": "synthetic-google-id-token"},
    )

    _assert_safe_session(response, expected_role="STUDENT")


def test_google_signup_allows_teacher_only_with_email_bound_invitation(
    client, oauth_settings, monkeypatch
):
    claims = _google_claims()
    _install_google_claims(monkeypatch, claims)
    invitation_token = _create_teacher_invitation(claims["email"], oauth_settings)

    denied = client.post(
        "/api/auth/google-signup",
        json={
            "idToken": "synthetic-google-id-token",
            "role": "TEACHER",
            "teacherInvitationToken": "wrong-invitation-token",
        },
    )
    accepted = client.post(
        "/api/auth/google-signup",
        json={
            "idToken": "synthetic-google-id-token",
            "role": "TEACHER",
            "teacherInvitationToken": invitation_token,
        },
    )

    assert denied.status_code == 401
    assert denied.json() == {"detail": "External authentication failed"}
    _assert_safe_session(accepted, expected_role="TEACHER")
    with SessionLocal() as db:
        invitation = db.query(models.TeacherInvitation).one()
        assert invitation.consumed_at is not None


def test_google_teacher_invitation_cannot_be_used_for_another_verified_email(
    client,
    oauth_settings,
    monkeypatch,
):
    invitation_token = _create_teacher_invitation(
        f"intended-teacher@{ALLOWED_DOMAIN}",
        oauth_settings,
    )
    _install_google_claims(
        monkeypatch,
        _google_claims(email=f"different-teacher@{ALLOWED_DOMAIN}"),
    )

    response = client.post(
        "/api/auth/google-signup",
        json={
            "idToken": "synthetic-google-id-token",
            "role": "TEACHER",
            "teacherInvitationToken": invitation_token,
        },
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "External authentication failed"}
    assert main.settings.session_cookie_name not in response.cookies
    with SessionLocal() as db:
        assert db.query(models.User).count() == 0
        invitation = db.query(models.TeacherInvitation).one()
        assert invitation.consumed_at is None


def test_oauth_signup_rejects_legacy_shared_access_code_field(
    client,
    oauth_settings,
    monkeypatch,
):
    _install_google_claims(monkeypatch, _google_claims())

    response = client.post(
        "/api/auth/google-signup",
        json={
            "idToken": "synthetic-google-id-token",
            "role": "TEACHER",
            "accessCode": "legacy-shared-code",
        },
    )

    assert "accessCode" not in main.OAuthSignupRequest.model_fields
    assert response.status_code == 401
    assert response.json() == {"detail": "External authentication failed"}
    with SessionLocal() as db:
        assert db.query(models.User).count() == 0


def test_google_teacher_creation_rolls_back_invite_identity_and_user_when_session_fails(
    client,
    oauth_settings,
    monkeypatch,
):
    email = f"rollback-teacher@{ALLOWED_DOMAIN}"
    invitation_token = _create_teacher_invitation(email, oauth_settings)
    _install_google_claims(monkeypatch, _google_claims(email=email))
    session_attempts = []

    def fail_session_issue(*args, **kwargs):
        session_attempts.append((args, kwargs))
        raise RuntimeError("synthetic session persistence failure")

    monkeypatch.setattr(main, "issue_browser_session", fail_session_issue)
    response = client.post(
        "/api/auth/google-signup",
        json={
            "idToken": "synthetic-google-id-token",
            "role": "TEACHER",
            "teacherInvitationToken": invitation_token,
        },
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "External authentication failed"}
    assert len(session_attempts) == 1
    with SessionLocal() as db:
        assert db.query(models.User).count() == 0
        assert db.query(models.FederatedIdentity).count() == 0
        invitation = db.query(models.TeacherInvitation).one()
        assert invitation.consumed_at is None


def test_disabled_federated_identity_cannot_create_a_new_session(
    client,
    oauth_settings,
    monkeypatch,
):
    email = f"disabled-oauth@{ALLOWED_DOMAIN}"
    user_id = _create_user(email, role=models.UserRole.TEACHER)
    _bind_identity(
        user_id,
        provider="google",
        issuer=GOOGLE_ISSUER,
        subject="disabled-google-subject",
    )
    with SessionLocal() as db:
        user = db.get(models.User, user_id)
        user.disabled_at = datetime.now(timezone.utc)
        db.commit()
    _install_google_claims(
        monkeypatch,
        _google_claims(sub="disabled-google-subject", email=email),
    )

    response = client.post(
        "/api/auth/google-login",
        json={"idToken": "synthetic-google-id-token"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "External authentication failed"}
    assert main.settings.session_cookie_name not in response.cookies
    with SessionLocal() as db:
        assert db.query(models.BrowserSession).count() == 0


def test_google_invalid_assertions_cannot_be_used_as_a_teacher_code_oracle(
    client,
    oauth_settings,
    monkeypatch,
):
    def reject(*_args, **_kwargs):
        raise ValueError("synthetic provider rejection")

    monkeypatch.setattr(main.id_token, "verify_oauth2_token", reject)
    invitation_token = _create_teacher_invitation(
        f"learner@{ALLOWED_DOMAIN}",
        oauth_settings,
    )
    guesses = ["wrong-invitation-token", invitation_token]

    responses = [
        client.post(
            "/api/auth/google-signup",
            json={
                "idToken": "synthetic-google-id-token",
                "role": "TEACHER",
                "teacherInvitationToken": guess,
            },
        )
        for guess in guesses
    ]

    assert [response.status_code for response in responses] == [401, 401]
    assert [response.json() for response in responses] == [
        {"detail": "External authentication failed"},
        {"detail": "External authentication failed"},
    ]


def test_google_signup_never_allows_public_admin_creation(
    client, oauth_settings, monkeypatch
):
    _install_google_claims(monkeypatch, _google_claims())

    response = client.post(
        "/api/auth/google-signup",
        json={
            "idToken": "synthetic-google-id-token",
            "role": "ADMIN",
        },
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid role"}
    with SessionLocal() as db:
        assert db.query(models.User).count() == 0


def test_existing_google_signup_never_changes_the_existing_role(
    client, oauth_settings, monkeypatch
):
    email = f"learner@{ALLOWED_DOMAIN}"
    user_id = _create_user(email, role=models.UserRole.TEACHER)
    _bind_identity(
        user_id,
        provider="google",
        issuer=GOOGLE_ISSUER,
        subject="google-subject-123",
    )
    _install_google_claims(monkeypatch, _google_claims(email=email))

    response = client.post(
        "/api/auth/google-signup",
        json={"idToken": "synthetic-google-id-token", "role": "STUDENT"},
    )

    _assert_safe_session(response, expected_role="TEACHER")
    with SessionLocal() as db:
        assert db.get(models.User, user_id).role == models.UserRole.TEACHER


def test_google_authenticates_by_stable_subject_when_verified_email_changes(
    client, oauth_settings, monkeypatch
):
    original_email = f"original@{ALLOWED_DOMAIN}"
    user_id = _create_user(original_email, role=models.UserRole.TEACHER)
    _bind_identity(
        user_id,
        provider="google",
        issuer=GOOGLE_ISSUER,
        subject="stable-google-subject",
    )
    _install_google_claims(
        monkeypatch,
        _google_claims(
            sub="stable-google-subject",
            email=f"renamed@{ALLOWED_DOMAIN}",
        ),
    )

    response = client.post(
        "/api/auth/google-login",
        json={"idToken": "synthetic-google-id-token"},
    )

    _assert_safe_session(response, expected_role="TEACHER")
    session_claims = decode_access_token(
        response.cookies[main.settings.session_cookie_name],
        settings=main.settings,
    )
    assert session_claims["sub"] == str(user_id)
    with SessionLocal() as db:
        assert db.get(models.User, user_id).email == original_email


def test_google_different_subject_cannot_take_over_reused_email(
    client, oauth_settings, monkeypatch
):
    email = f"reused@{ALLOWED_DOMAIN}"
    invitation_token = _create_teacher_invitation(email, oauth_settings)
    _install_google_claims(
        monkeypatch,
        _google_claims(sub="original-google-subject", email=email),
    )
    created = client.post(
        "/api/auth/google-signup",
        json={
            "idToken": "synthetic-google-id-token",
            "role": "TEACHER",
            "teacherInvitationToken": invitation_token,
        },
    )
    _assert_safe_session(created, expected_role="TEACHER")
    with SessionLocal() as db:
        original_user_id = db.query(models.User).one().id
    client.cookies.clear()

    _install_google_claims(
        monkeypatch,
        _google_claims(sub="replacement-google-subject", email=email),
    )
    takeover = client.post(
        "/api/auth/google-signup",
        json={"idToken": "synthetic-google-id-token"},
    )

    assert takeover.status_code == 401
    assert takeover.json() == {"detail": "External authentication failed"}
    assert main.settings.session_cookie_name not in takeover.cookies
    with SessionLocal() as db:
        assert db.query(models.User).count() == 1
        assert db.get(models.User, original_user_id).role == models.UserRole.TEACHER
        assert db.query(models.FederatedIdentity).count() == 1


def test_oauth_signup_does_not_implicitly_link_an_existing_email(
    client, oauth_settings, monkeypatch
):
    email = f"local-account@{ALLOWED_DOMAIN}"
    existing_user_id = _create_user(email, role=models.UserRole.TEACHER)
    _install_google_claims(
        monkeypatch,
        _google_claims(sub="unlinked-google-subject", email=email),
    )

    response = client.post(
        "/api/auth/google-signup",
        json={"idToken": "synthetic-google-id-token"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "External authentication failed"}
    assert main.settings.session_cookie_name not in response.cookies
    with SessionLocal() as db:
        assert db.get(models.User, existing_user_id).role == models.UserRole.TEACHER
        assert db.query(models.FederatedIdentity).count() == 0


@pytest.mark.parametrize(
    ("token_kind", "claim_overrides"),
    [
        ("unsigned", {}),
        ("wrong-algorithm", {}),
        ("wrong-signature", {}),
        ("valid", {"aud": "wrong-audience"}),
        ("valid", {"iss": "https://login.microsoftonline.com/other/v2.0"}),
        ("valid", {"tid": "00000000-0000-0000-0000-000000000000"}),
        ("valid", {"exp": 1}),
        (
            "valid",
            {"iat": int((datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp())},
        ),
        (
            "valid",
            {"nbf": int((datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp())},
        ),
        ("valid", {"sub": ""}),
        ("valid", {"email": ""}),
        ("valid", {"email": "learner@other.example"}),
    ],
    ids=[
        "unsigned",
        "wrong-algorithm",
        "wrong-signature",
        "wrong-audience",
        "wrong-issuer",
        "wrong-tenant",
        "expired",
        "future-issued-at",
        "not-yet-valid",
        "missing-subject",
        "missing-email",
        "wrong-domain",
    ],
)
def test_microsoft_rejects_untrusted_tokens(
    client,
    oauth_settings,
    monkeypatch,
    microsoft_keys,
    token_kind,
    claim_overrides,
):
    private_key, other_private_key, jwks = microsoft_keys
    _install_microsoft_jwks(monkeypatch, jwks)
    claims = _microsoft_claims(**claim_overrides)
    if token_kind == "unsigned":
        token = _microsoft_token(private_key, claims, algorithm="none")
    elif token_kind == "wrong-algorithm":
        token = _microsoft_token(private_key, claims, algorithm="HS256")
    elif token_kind == "wrong-signature":
        token = _microsoft_token(other_private_key, claims)
    else:
        token = _microsoft_token(private_key, claims)

    response = client.post("/api/auth/microsoft-login", json={"idToken": token})

    assert response.status_code == 401
    assert response.json() == {"detail": "External authentication failed"}


@pytest.mark.parametrize("missing_claim", ["iat", "nbf", "exp", "sub", "email", "tid"])
def test_microsoft_rejects_missing_required_claims(
    client,
    oauth_settings,
    monkeypatch,
    microsoft_keys,
    missing_claim,
):
    private_key, _, jwks = microsoft_keys
    _install_microsoft_jwks(monkeypatch, jwks)
    claims = _microsoft_claims()
    claims.pop(missing_claim)

    response = client.post(
        "/api/auth/microsoft-login",
        json={"idToken": _microsoft_token(private_key, claims)},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "External authentication failed"}


@pytest.mark.parametrize("malformed", ["", "not-a-jwt", "one.two.three", 123])
def test_microsoft_rejects_malformed_id_tokens(client, oauth_settings, malformed):
    response = client.post(
        "/api/auth/microsoft-login",
        json={"idToken": malformed},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "External authentication failed"}
    if str(malformed):
        assert str(malformed) not in response.text


@pytest.mark.parametrize(
    ("path", "payload", "sensitive_value"),
    [
        (
            "/api/auth/google-login",
            {"token": "legacy-sensitive-google-token"},
            "legacy-sensitive-google-token",
        ),
        (
            "/api/auth/google-signup",
            {"idToken": {"raw": "wrong-shape-sensitive-google-token"}},
            "wrong-shape-sensitive-google-token",
        ),
        (
            "/api/auth/microsoft-login",
            {
                "msUserData": {
                    "email": "sensitive-forged-profile@attacker.example",
                }
            },
            "sensitive-forged-profile@attacker.example",
        ),
        (
            "/api/auth/microsoft-signup",
            {"idToken": "oversized-sensitive-token-" + ("x" * 20_000)},
            "oversized-sensitive-token-",
        ),
    ],
)
def test_invalid_oauth_request_bodies_are_generic_and_never_echo_or_log_input(
    client,
    oauth_settings,
    caplog,
    capsys,
    path,
    payload,
    sensitive_value,
):
    with caplog.at_level(logging.DEBUG):
        response = client.post(path, json=payload)
    captured = capsys.readouterr()

    assert response.status_code == 401
    assert response.json() == {"detail": "External authentication failed"}
    combined_output = response.text + caplog.text + captured.out + captured.err
    assert sensitive_value not in combined_output


def test_non_oauth_credential_validation_is_also_generic(client):
    response = client.post("/api/auth/register", json={})

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid authentication request"}


def test_microsoft_uses_only_the_configured_tenant_jwks_and_issues_safe_cookie_session(
    client, oauth_settings, monkeypatch, microsoft_keys
):
    private_key, _, jwks = microsoft_keys
    requested_urls = []
    _install_microsoft_jwks(monkeypatch, jwks, requested_urls)
    user_id = _create_user(f"learner@{ALLOWED_DOMAIN}")
    _bind_identity(
        user_id,
        provider="microsoft",
        issuer=MICROSOFT_ISSUER,
        subject="microsoft-subject-123",
    )

    response = client.post(
        "/api/auth/microsoft-login",
        json={"idToken": _microsoft_token(private_key)},
    )

    _assert_safe_session(response, expected_role="STUDENT")
    assert requested_urls == [
        f"https://login.microsoftonline.com/{MICROSOFT_TENANT_ID}/discovery/v2.0/keys"
    ]


def test_microsoft_jwks_client_has_bounded_network_and_ttl_cache_without_unbounded_key_cache(
    oauth_settings,
    microsoft_keys,
):
    private_key, _, _ = microsoft_keys
    captured = {}

    class SyntheticSigningKey:
        key = private_key.public_key()

    class RecordingJwkClient:
        def __init__(self, url, **kwargs):
            captured.update({"url": url, **kwargs})

        def get_signing_key_from_jwt(self, _token):
            return SyntheticSigningKey()

    claims = oauth_security.verify_microsoft_id_token(
        _microsoft_token(private_key),
        settings=oauth_settings,
        jwk_client_factory=RecordingJwkClient,
    )

    assert claims["sub"] == "microsoft-subject-123"
    assert captured == {
        "url": f"https://login.microsoftonline.com/{MICROSOFT_TENANT_ID}/discovery/v2.0/keys",
        "cache_keys": False,
        "cache_jwk_set": True,
        "lifespan": oauth_settings.oauth_jwks_cache_seconds,
        "timeout": oauth_settings.oauth_http_timeout_seconds,
    }


def test_microsoft_reuses_the_bounded_jwks_set_cache_across_verifications(
    oauth_settings,
    monkeypatch,
    microsoft_keys,
):
    reset_jwks_cache = getattr(oauth_security, "reset_microsoft_jwk_client_cache", None)
    assert callable(reset_jwks_cache)
    if not callable(reset_jwks_cache):
        return

    private_key, _, jwks = microsoft_keys
    fetch_count = 0

    def fetch_data(client):
        nonlocal fetch_count
        fetch_count += 1
        client.jwk_set_cache.put(jwks)
        return jwks

    monkeypatch.setattr(jwt.PyJWKClient, "fetch_data", fetch_data)
    reset_jwks_cache()
    token = _microsoft_token(private_key)

    oauth_security.verify_microsoft_id_token(token, settings=oauth_settings)
    oauth_security.verify_microsoft_id_token(token, settings=oauth_settings)

    assert fetch_count == 1


def test_microsoft_provider_failure_is_generic_and_never_logs_token_or_provider_error(
    client,
    oauth_settings,
    monkeypatch,
    microsoft_keys,
    caplog,
    capsys,
):
    private_key, _, _ = microsoft_keys
    raw_token = _microsoft_token(private_key)
    sensitive_provider_error = "synthetic-sensitive-jwks-provider-error"

    def fail_fetch(_client):
        raise TimeoutError(sensitive_provider_error)

    monkeypatch.setattr(jwt.PyJWKClient, "fetch_data", fail_fetch)
    with caplog.at_level(logging.DEBUG):
        response = client.post(
            "/api/auth/microsoft-login",
            json={"idToken": raw_token},
        )
    captured = capsys.readouterr()

    assert response.status_code == 401
    assert response.json() == {"detail": "External authentication failed"}
    combined_output = caplog.text + captured.out + captured.err + response.text
    assert raw_token not in combined_output
    assert sensitive_provider_error not in combined_output


def test_microsoft_signup_defaults_to_student_and_creates_subject_binding(
    client, oauth_settings, monkeypatch, microsoft_keys
):
    private_key, _, jwks = microsoft_keys
    _install_microsoft_jwks(monkeypatch, jwks)

    response = client.post(
        "/api/auth/microsoft-signup",
        json={"idToken": _microsoft_token(private_key)},
    )

    _assert_safe_session(response, expected_role="STUDENT")
    with SessionLocal() as db:
        user = db.query(models.User).one()
        identity = db.query(models.FederatedIdentity).one()
        assert identity.provider == "microsoft"
        assert identity.issuer == MICROSOFT_ISSUER
        assert identity.subject == "microsoft-subject-123"
        assert identity.user_id == user.id


def test_microsoft_existing_bound_account_role_is_immutable(
    client, oauth_settings, monkeypatch, microsoft_keys
):
    private_key, _, jwks = microsoft_keys
    _install_microsoft_jwks(monkeypatch, jwks)
    email = f"learner@{ALLOWED_DOMAIN}"
    user_id = _create_user(email, role=models.UserRole.TEACHER)
    _bind_identity(
        user_id,
        provider="microsoft",
        issuer=MICROSOFT_ISSUER,
        subject="microsoft-subject-123",
    )

    response = client.post(
        "/api/auth/microsoft-signup",
        json={"idToken": _microsoft_token(private_key)},
    )

    _assert_safe_session(response, expected_role="TEACHER")
    with SessionLocal() as db:
        assert db.get(models.User, user_id).role == models.UserRole.TEACHER


def test_microsoft_signup_never_allows_public_admin_creation(
    client, oauth_settings, monkeypatch, microsoft_keys
):
    private_key, _, jwks = microsoft_keys
    _install_microsoft_jwks(monkeypatch, jwks)

    response = client.post(
        "/api/auth/microsoft-signup",
        json={
            "idToken": _microsoft_token(private_key),
            "role": "ADMIN",
        },
    )

    assert response.status_code == 400
    with SessionLocal() as db:
        assert db.query(models.User).count() == 0


def test_microsoft_different_subject_cannot_take_over_reused_email(
    client, oauth_settings, monkeypatch, microsoft_keys
):
    private_key, _, jwks = microsoft_keys
    _install_microsoft_jwks(monkeypatch, jwks)
    email = f"reused@{ALLOWED_DOMAIN}"
    invitation_token = _create_teacher_invitation(email, oauth_settings)
    created = client.post(
        "/api/auth/microsoft-signup",
        json={
            "idToken": _microsoft_token(
                private_key,
                _microsoft_claims(sub="original-microsoft-subject", email=email),
            ),
            "role": "TEACHER",
            "teacherInvitationToken": invitation_token,
        },
    )
    _assert_safe_session(created, expected_role="TEACHER")
    with SessionLocal() as db:
        original_user_id = db.query(models.User).one().id
    client.cookies.clear()

    takeover = client.post(
        "/api/auth/microsoft-signup",
        json={
            "idToken": _microsoft_token(
                private_key,
                _microsoft_claims(sub="replacement-microsoft-subject", email=email),
            ),
        },
    )

    assert takeover.status_code == 401
    assert takeover.json() == {"detail": "External authentication failed"}
    assert main.settings.session_cookie_name not in takeover.cookies
    with SessionLocal() as db:
        assert db.query(models.User).count() == 1
        assert db.get(models.User, original_user_id).role == models.UserRole.TEACHER
        assert db.query(models.FederatedIdentity).count() == 1


def test_cross_provider_email_collision_never_links_accounts(
    client, oauth_settings, monkeypatch, microsoft_keys
):
    email = f"cross-provider@{ALLOWED_DOMAIN}"
    _install_google_claims(
        monkeypatch,
        _google_claims(sub="google-owner-subject", email=email),
    )
    created = client.post(
        "/api/auth/google-signup",
        json={"idToken": "synthetic-google-id-token"},
    )
    _assert_safe_session(created, expected_role="STUDENT")
    client.cookies.clear()

    private_key, _, jwks = microsoft_keys
    _install_microsoft_jwks(monkeypatch, jwks)
    collision = client.post(
        "/api/auth/microsoft-signup",
        json={
            "idToken": _microsoft_token(
                private_key,
                _microsoft_claims(sub="microsoft-other-subject", email=email),
            ),
        },
    )

    assert collision.status_code == 401
    assert collision.json() == {"detail": "External authentication failed"}
    assert main.settings.session_cookie_name not in collision.cookies
    with SessionLocal() as db:
        assert db.query(models.User).count() == 1
        assert db.query(models.FederatedIdentity).count() == 1


def test_federated_identity_subject_binding_is_database_unique(client):
    first_user_id = _create_user(f"first@{ALLOWED_DOMAIN}")
    second_user_id = _create_user(f"second@{ALLOWED_DOMAIN}")
    _bind_identity(
        first_user_id,
        provider="google",
        issuer=GOOGLE_ISSUER,
        subject="database-unique-subject",
    )

    with SessionLocal() as db:
        db.add(
            models.FederatedIdentity(
                provider="google",
                issuer=GOOGLE_ISSUER,
                subject="database-unique-subject",
                user_id=second_user_id,
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

    with SessionLocal() as db:
        identities = db.query(models.FederatedIdentity).all()
        assert len(identities) == 1
        assert identities[0].user_id == first_user_id


def test_deleting_user_removes_identity_and_allows_safe_subject_resignup(
    client,
    oauth_settings,
    monkeypatch,
):
    claims = _google_claims(
        sub="deleted-user-google-subject",
        email=f"deleted-user@{ALLOWED_DOMAIN}",
    )
    _install_google_claims(monkeypatch, claims)
    created = client.post(
        "/api/auth/google-signup",
        json={"idToken": "synthetic-google-id-token"},
    )
    _assert_safe_session(created, expected_role="STUDENT")
    client.cookies.clear()

    with SessionLocal() as db:
        user_id = db.query(models.User.id).scalar()
    with SessionLocal() as db:
        user = db.get(models.User, user_id)
        assert "federated_identities" not in user.__dict__
        db.delete(user)
        db.commit()
    with SessionLocal() as db:
        assert db.query(models.User).count() == 0
        assert db.query(models.FederatedIdentity).count() == 0

    recreated = client.post(
        "/api/auth/google-signup",
        json={"idToken": "synthetic-google-id-token"},
    )
    _assert_safe_session(recreated, expected_role="STUDENT")
    with SessionLocal() as db:
        assert db.query(models.User).count() == 1
        assert db.query(models.FederatedIdentity).count() == 1


def test_concurrent_email_collision_is_atomic_and_never_issues_loser_cookie(
    client,
    oauth_settings,
    monkeypatch,
):
    email = f"race@{ALLOWED_DOMAIN}"
    flush_barrier = threading.Barrier(2)

    def verify(token, request, audience, **_kwargs):
        assert request is not None
        assert audience == SYNTHETIC_GOOGLE_AUDIENCE
        return _google_claims(sub=token, email=email)

    def synchronize_identity_inserts(session, _flush_context, _instances):
        if any(isinstance(item, models.FederatedIdentity) for item in session.new):
            flush_barrier.wait(timeout=5)

    monkeypatch.setattr(main.id_token, "verify_oauth2_token", verify)
    event.listen(OrmSession, "before_flush", synchronize_identity_inserts)
    first_client = TestClient(main.app)
    second_client = TestClient(main.app)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    selected_client.post,
                    "/api/auth/google-signup",
                    json={"idToken": subject},
                )
                for selected_client, subject in (
                    (first_client, "race-subject-a"),
                    (second_client, "race-subject-b"),
                )
            ]
            responses = [future.result(timeout=10) for future in futures]
    finally:
        event.remove(OrmSession, "before_flush", synchronize_identity_inserts)
        first_client.close()
        second_client.close()

    assert sorted(response.status_code for response in responses) == [200, 401]
    loser = next(response for response in responses if response.status_code == 401)
    assert loser.json() == {"detail": "External authentication failed"}
    assert main.settings.session_cookie_name not in loser.cookies
    with SessionLocal() as db:
        assert db.query(models.User).count() == 1
        assert db.query(models.FederatedIdentity).count() == 1


def test_concurrent_same_subject_signup_resolves_to_one_bound_account(
    client,
    oauth_settings,
    monkeypatch,
):
    email = f"same-subject-race@{ALLOWED_DOMAIN}"
    subject = "same-provider-subject-race"
    flush_barrier = threading.Barrier(2)

    def verify(token, request, audience, **_kwargs):
        assert token == "same-subject-token"
        assert request is not None
        assert audience == SYNTHETIC_GOOGLE_AUDIENCE
        return _google_claims(sub=subject, email=email)

    def synchronize_identity_inserts(session, _flush_context, _instances):
        if any(isinstance(item, models.FederatedIdentity) for item in session.new):
            flush_barrier.wait(timeout=5)

    monkeypatch.setattr(main.id_token, "verify_oauth2_token", verify)
    event.listen(OrmSession, "before_flush", synchronize_identity_inserts)
    first_client = TestClient(main.app)
    second_client = TestClient(main.app)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    selected_client.post,
                    "/api/auth/google-signup",
                    json={"idToken": "same-subject-token"},
                )
                for selected_client in (first_client, second_client)
            ]
            responses = [future.result(timeout=10) for future in futures]
    finally:
        event.remove(OrmSession, "before_flush", synchronize_identity_inserts)
        first_client.close()
        second_client.close()

    for response in responses:
        _assert_safe_session(response, expected_role="STUDENT")
    session_subjects = {
        decode_access_token(
            response.cookies[main.settings.session_cookie_name],
            settings=oauth_settings,
        )["sub"]
        for response in responses
    }
    with SessionLocal() as db:
        user = db.query(models.User).one()
        identity = db.query(models.FederatedIdentity).one()
        assert session_subjects == {str(user.id)}
        assert identity.user_id == user.id
        assert identity.subject == subject


def test_federated_identity_table_has_an_explicit_production_migration():
    migration = (
        Path(main.__file__).resolve().parent
        / "migrations"
        / "0001_create_federated_identities.sql"
    )

    sql = migration.read_text(encoding="utf-8").lower()
    assert "create table federated_identities" in sql
    assert "unique (provider, issuer, subject)" in sql
    assert "unique (provider, user_id)" in sql
    assert "foreign key (user_id) references users (id) on delete cascade" in sql
    assert "check (provider in ('google', 'microsoft'))" in sql
    assert "create index ix_federated_identities_user_id" in sql
    assert "no automatic email" in sql


def test_federated_identity_migration_runbook_blocks_unsafe_email_backfill():
    runbook = (
        Path(main.__file__).resolve().parent
        / "migrations"
        / "README-federated-identities.md"
    )

    text = runbook.read_text(encoding="utf-8").lower()
    assert "deployment blocker" in text
    assert "preflight" in text
    assert "never" in text and "email" in text and "backfill" in text
    assert "authenticated account-link" in text
    assert "school-it" in text and "provider subject" in text
    assert "rollback" in text and "abort" in text
    assert text.index("`0001_create_federated_identities.sql`") < text.index(
        "left join federated_identities"
    )
    assert "keep the application disabled" in text
