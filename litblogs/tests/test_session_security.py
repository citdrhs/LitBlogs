import logging
import secrets
import time

import pytest
from pydantic import BaseModel

import auth_security
import main
import models
from auth_security import hash_password, issue_access_token
from config import Settings
from database import SessionLocal


def _student_payload(suffix: str = "one") -> dict:
    return {
        "username": f"session-student-{suffix}",
        "email": f"session-student-{suffix}@example.com",
        "password": "synthetic-session-password",
        "first_name": "Session",
        "last_name": "Student",
        "role": "STUDENT",
    }


def _register(client, suffix: str = "one"):
    response = client.post("/api/auth/register", json=_student_payload(suffix))
    assert response.status_code == 200
    return response


def _create_student(suffix: str) -> models.User:
    with SessionLocal() as db:
        user = models.User(
            username=f"session-direct-{suffix}",
            email=f"session-direct-{suffix}@example.test",
            password=hash_password("synthetic-session-password"),
            first_name="Direct",
            last_name="Student",
            role=models.UserRole.STUDENT,
            is_admin=False,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        db.expunge(user)
        return user


def _set_cookie_auth(client, user_id: int, csrf_token: str = "synthetic-csrf-token") -> str:
    session_cookie_name = main.settings.session_cookie_name
    csrf_cookie_name = main.settings.csrf_cookie_name
    client.cookies.set(session_cookie_name, issue_access_token(str(user_id)))
    client.cookies.set(csrf_cookie_name, csrf_token)
    return csrf_token


def _cookie_header(response, cookie_name: str) -> str:
    matches = [
        value
        for value in response.headers.get_list("set-cookie")
        if value.startswith(f"{cookie_name}=")
    ]
    assert len(matches) == 1
    return matches[0]


def _assert_cookie_attributes(
    header: str,
    *,
    http_only: bool,
    secure: bool,
    max_age: int,
) -> None:
    lowered = header.lower()
    assert "path=/" in lowered
    assert "samesite=strict" in lowered
    assert f"max-age={max_age}" in lowered
    assert ("httponly" in lowered) is http_only
    assert ("secure" in lowered) is secure
    assert "domain=" not in lowered


def _assert_no_jwt_fields(payload: dict) -> None:
    assert "token" not in payload
    assert "access_token" not in payload
    assert "token_type" not in payload


def _production_settings() -> Settings:
    return Settings(
        app_env="production",
        database_url=(
            f"postgresql://litblog_app:{secrets.token_urlsafe(24)}@database.internal/litblog"
            "?sslmode=verify-full&sslrootcert=/etc/litblogs/postgres-root-ca.pem"
        ),
        secret_key=secrets.token_urlsafe(48),
        jwt_issuer="https://api.litblogs.school.edu",
        jwt_audience="litblogs.school.edu",
        access_token_expire_minutes=30,
        frontend_url="https://litblogs.school.edu",
        cors_allowed_origins=("https://litblogs.school.edu",),
        allowed_hosts=("litblogs.school.edu",),
        allowed_email_domains=("school.edu",),
        google_client_id="987654321.apps.googleusercontent.com",
        microsoft_client_id="2f1c67a1-91e2-46a3-941f-b88e31763e51",
        microsoft_tenant_id="871bd3e0-2dc0-4a40-9b07-9d03068c2364",
        microsoft_allowed_tenant_ids=("871bd3e0-2dc0-4a40-9b07-9d03068c2364",),
        session_cookie_name="__Host-litblog-session",
        csrf_cookie_name="__Host-litblog-csrf",
        session_cookie_secure=True,
        teacher_access_code=secrets.token_urlsafe(24),
        email_host="smtp.school.edu",
        email_username="litblogs-mailer",
        email_password=secrets.token_urlsafe(24),
        email_from="no-reply@school.edu",
    )


def test_csrf_comparison_uses_constant_time_bytes(monkeypatch):
    calls = []

    def fake_compare_digest(left, right):
        calls.append((left, right))
        return True

    monkeypatch.setattr(auth_security.hmac, "compare_digest", fake_compare_digest)
    matcher = getattr(auth_security, "csrf_token_matches", None)

    assert callable(matcher)
    if not callable(matcher):
        return
    assert matcher("supplied-csrf", "configured-csrf") is True
    assert calls == [(b"supplied-csrf", b"configured-csrf")]


def test_registration_sets_protected_session_and_readable_csrf_cookies(client):
    response = _register(client)
    max_age = main.settings.access_token_expire_minutes * 60

    session_header = _cookie_header(response, main.settings.session_cookie_name)
    csrf_header = _cookie_header(response, main.settings.csrf_cookie_name)
    _assert_cookie_attributes(session_header, http_only=True, secure=False, max_age=max_age)
    _assert_cookie_attributes(csrf_header, http_only=False, secure=False, max_age=max_age)
    _assert_no_jwt_fields(response.json())


def test_login_rotates_csrf_and_never_returns_the_jwt(client):
    _register(client)
    first_csrf = client.cookies.get(main.settings.csrf_cookie_name)

    response = client.post(
        "/api/auth/login",
        json={
            "email": _student_payload()["email"],
            "password": _student_payload()["password"],
        },
    )

    assert response.status_code == 200
    second_csrf = client.cookies.get(main.settings.csrf_cookie_name)
    assert isinstance(first_csrf, str) and len(first_csrf) >= 32
    assert isinstance(second_csrf, str) and len(second_csrf) >= 32
    assert second_csrf != first_csrf
    _assert_no_jwt_fields(response.json())


def test_production_login_marks_both_cookies_secure(monkeypatch, client):
    user = _create_student("production")
    monkeypatch.setattr(main, "settings", _production_settings())

    response = client.post(
        "/api/auth/login",
        json={"email": user.email, "password": "synthetic-session-password"},
    )

    assert response.status_code == 200
    max_age = main.settings.access_token_expire_minutes * 60
    _assert_cookie_attributes(
        _cookie_header(response, main.settings.session_cookie_name),
        http_only=True,
        secure=True,
        max_age=max_age,
    )
    _assert_cookie_attributes(
        _cookie_header(response, main.settings.csrf_cookie_name),
        http_only=False,
        secure=True,
        max_age=max_age,
    )


def test_safe_session_endpoint_returns_typed_nonsecret_metadata(client):
    _register(client)

    response = client.get("/api/auth/session")

    assert response.status_code == 200
    assert response.json() == {
        "user_id": 1,
        "username": "session-student-one",
        "first_name": "Session",
        "last_name": "Student",
        "role": "STUDENT",
        "is_admin": False,
    }
    _assert_no_jwt_fields(response.json())
    route = next(route for route in main.app.routes if route.path == "/api/auth/session")
    assert isinstance(route.response_model, type)
    assert issubclass(route.response_model, BaseModel)


def test_every_browser_auth_success_route_uses_the_nonsecret_session_schema():
    browser_auth_paths = {
        "/api/auth/register",
        "/api/auth/login",
        "/api/auth/google-signup",
        "/api/auth/google-login",
        "/api/auth/microsoft-login",
        "/api/auth/microsoft-signup",
    }
    routes = {route.path: route for route in main.app.routes if route.path in browser_auth_paths}

    assert set(routes) == browser_auth_paths
    assert {
        path: route.response_model
        for path, route in routes.items()
        if route.response_model is not main.SessionMetadataResponse
    } == {}
    assert set(main.SessionMetadataResponse.model_fields).isdisjoint(
        {"token", "access_token", "token_type", "password"}
    )


def test_cookie_authenticated_mutation_requires_matching_csrf_before_mutation(client):
    _register(client)
    csrf_token = client.cookies.get(main.settings.csrf_cookie_name)

    missing = client.put("/api/user/settings", json={"darkMode": True})
    mismatch = client.put(
        "/api/user/settings",
        json={"darkMode": True},
        headers={"X-CSRF-Token": "wrong-csrf-token"},
    )

    assert missing.status_code == 403
    assert mismatch.status_code == 403
    assert missing.json() == {"detail": "CSRF validation failed"}
    assert mismatch.json() == {"detail": "CSRF validation failed"}
    with SessionLocal() as db:
        assert db.query(models.UserSettings).count() == 0

    accepted = client.put(
        "/api/user/settings",
        json={"darkMode": True},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert accepted.status_code == 200
    assert accepted.json()["darkMode"] is True


def test_safe_cookie_authenticated_requests_do_not_require_csrf(client):
    _register(client)

    response = client.get("/api/auth/session")

    assert response.status_code == 200


def test_bearer_authenticated_mutation_remains_supported_without_csrf(client):
    user = _create_student("bearer")
    token = issue_access_token(str(user.id))

    response = client.put(
        "/api/user/settings",
        json={"darkMode": True},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["darkMode"] is True


@pytest.mark.parametrize("bearer_subject", ["same", "different"])
def test_cookie_and_bearer_credentials_are_rejected_as_ambiguous(client, bearer_subject):
    cookie_user = _create_student("cookie")
    bearer_user = cookie_user if bearer_subject == "same" else _create_student("bearer-conflict")
    csrf_token = _set_cookie_auth(client, cookie_user.id)
    bearer_token = issue_access_token(str(bearer_user.id))

    response = client.put(
        "/api/user/settings",
        json={"darkMode": True},
        headers={
            "Authorization": f"Bearer {bearer_token}",
            "X-CSRF-Token": csrf_token,
        },
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}
    with SessionLocal() as db:
        assert db.query(models.UserSettings).count() == 0


def test_logout_requires_cookie_csrf_and_clears_both_cookies(client):
    _register(client)
    session_cookie_name = main.settings.session_cookie_name
    csrf_cookie_name = main.settings.csrf_cookie_name
    csrf_token = client.cookies.get(csrf_cookie_name)

    denied = client.post("/api/auth/logout")
    assert denied.status_code == 403
    assert client.cookies.get(session_cookie_name)
    assert client.cookies.get(csrf_cookie_name)

    response = client.post(
        "/api/auth/logout",
        headers={"X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 204
    assert response.content == b""
    for cookie_name, http_only in (
        (session_cookie_name, True),
        (csrf_cookie_name, False),
    ):
        header = _cookie_header(response, cookie_name)
        assert "max-age=0" in header.lower()
        assert "path=/" in header.lower()
        assert ("httponly" in header.lower()) is http_only
        assert "domain=" not in header.lower()
    assert client.cookies.get(session_cookie_name) is None
    assert client.cookies.get(csrf_cookie_name) is None


def test_invalid_cookie_errors_are_generic_and_do_not_log_credentials(client, caplog):
    raw_cookie = "synthetic-invalid-cookie-value"
    raw_csrf = "synthetic-invalid-csrf-value"
    client.cookies.set(main.settings.session_cookie_name, raw_cookie)
    client.cookies.set(main.settings.csrf_cookie_name, raw_csrf)

    with caplog.at_level(logging.DEBUG):
        response = client.get("/api/auth/session")

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}
    assert raw_cookie not in caplog.text
    assert raw_csrf not in caplog.text


def test_provider_failures_are_generic_and_do_not_log_credentials(
    client,
    monkeypatch,
    caplog,
    capsys,
):
    raw_provider_token = "synthetic-sensitive-provider-token"

    def reject_provider_token(*_args, **_kwargs):
        raise ValueError(f"provider rejected {raw_provider_token}")

    monkeypatch.setattr(main.id_token, "verify_oauth2_token", reject_provider_token)

    with caplog.at_level(logging.DEBUG):
        response = client.post(
            "/api/auth/google-login",
            json={"idToken": raw_provider_token},
        )
    captured = capsys.readouterr()

    assert response.status_code == 401
    assert response.json() == {"detail": "External authentication failed"}
    assert raw_provider_token not in response.text
    assert raw_provider_token not in caplog.text
    assert raw_provider_token not in captured.out
    assert raw_provider_token not in captured.err


def test_expected_provider_auth_errors_preserve_their_safe_status(client, monkeypatch):
    now = int(time.time())

    def verified_missing_user(*_args, **_kwargs):
        return {
            "iss": "https://accounts.google.com",
            "aud": main.settings.google_client_id,
            "sub": "synthetic-missing-user-subject",
            "email": "missing-provider-user@example.test",
            "email_verified": True,
            "hd": "example.test",
            "iat": now - 5,
            "nbf": now - 5,
            "exp": now + 300,
        }

    monkeypatch.setattr(main.id_token, "verify_oauth2_token", verified_missing_user)
    response = client.post(
        "/api/auth/google-login",
        json={"idToken": "synthetic-provider-id-token"},
    )

    assert response.status_code == 404
    assert response.json() == {
        "detail": "User not found. Please sign up and choose a role first."
    }


def test_cors_allows_only_the_exact_configured_origin_with_credentials(client):
    allowed = client.options(
        "/api/auth/session",
        headers={
            "Origin": "http://testserver",
            "Access-Control-Request-Method": "GET",
        },
    )
    denied = client.options(
        "/api/auth/session",
        headers={
            "Origin": "http://unconfigured.example.test",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://testserver"
    assert allowed.headers["access-control-allow-credentials"] == "true"
    assert allowed.headers["access-control-allow-origin"] != "*"
    assert "access-control-allow-origin" not in denied.headers
