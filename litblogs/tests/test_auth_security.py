import json
import logging
import os
import secrets
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
from pydantic import ValidationError

import auth_security
from auth_security import (
    MAX_PASSWORD_BYTES,
    decode_access_token,
    hash_password,
    issue_access_token,
    provisioning_code_matches,
    verify_and_update_password,
    verify_password,
)
from config import Settings, get_settings, load_settings, reset_settings_cache

SAFE_SECRET = "test-only-secret-key-0123456789-ABCDEFGHIJKLMNOPQRSTUVWXYZ"
SYNTHETIC_UNREACHABLE_DATABASE_URL = "postgresql://litblog.invalid/production"
TOO_SHORT_PRODUCTION_SECRET = "too-short"
LEGACY_PASSWORD = "synthetic-legacy-password"
LEGACY_BCRYPT_HASH = "$2b$12$E/Tz4k0i2e8Hc7klKQTGnefurjjyh5VixxLURcqdkVTT9FkDet6e2"
LONG_LEGACY_PASSWORD = ("L" * 72) + "-synthetic-full-password-tail"
LONG_LEGACY_BCRYPT_HASH = "$2b$12$JXEBjl/XUo36y7LLMQ2mBuEmaxvDRCgLdk091R3.J1nAxJuXGlw4m"


def test_settings_values_are_immutable():
    settings = _test_settings()

    with pytest.raises(ValidationError, match="frozen"):
        settings.jwt_issuer = "changed"


def test_settings_normalize_environment_origins_tenants_and_domains():
    settings = Settings(
        **_test_settings_data(
            app_env=" TeSt ",
            cors_allowed_origins="http://testserver/, http://localhost:5173",
            microsoft_allowed_tenant_ids=" Tenant-A,tenant-b ",
            allowed_email_domains=" School.EXAMPLE,students.school.example ",
        )
    )

    assert settings.app_env == "test"
    assert settings.cors_allowed_origins == (
        "http://testserver",
        "http://localhost:5173",
    )
    assert settings.microsoft_allowed_tenant_ids == ("tenant-a", "tenant-b")
    assert settings.allowed_email_domains == (
        "school.example",
        "students.school.example",
    )


def test_process_environment_overrides_environment_specific_and_base_files(
    monkeypatch, tmp_path
):
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "APP_ENV=test",
                f"SECRET_KEY={SAFE_SECRET}-base",
                "JWT_ISSUER=base-issuer",
                "JWT_AUDIENCE=base-audience",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / ".env.test").write_text(
        "\n".join(
            [
                f"SECRET_KEY={SAFE_SECRET}-environment-specific",
                "JWT_ISSUER=environment-specific-issuer",
                "JWT_AUDIENCE=environment-specific-audience",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("APP_ENV", "TEST")
    monkeypatch.setenv("SECRET_KEY", f"{SAFE_SECRET}-process")
    monkeypatch.setenv("JWT_AUDIENCE", "process-audience")
    monkeypatch.delenv("JWT_ISSUER", raising=False)

    settings = load_settings(base_dir=tmp_path)

    assert settings.secret_key.get_secret_value() == f"{SAFE_SECRET}-process"
    assert settings.jwt_issuer == "environment-specific-issuer"
    assert settings.jwt_audience == "process-audience"


def test_environment_specific_file_cannot_downgrade_selected_production(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text(
        "APP_ENV=production\nSECRET_KEY=too-short\n",
        encoding="utf-8",
    )
    (tmp_path / ".env.production").write_text(
        "APP_ENV=development\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)

    with pytest.raises(ValidationError, match="SECRET_KEY"):
        load_settings(base_dir=tmp_path)


def test_settings_cache_can_be_reset_for_tests(monkeypatch):
    reset_settings_cache()
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("SECRET_KEY", f"{SAFE_SECRET}-first")
    first = get_settings()
    monkeypatch.setenv("SECRET_KEY", f"{SAFE_SECRET}-second")

    assert get_settings() is first

    reset_settings_cache()
    second = get_settings()
    assert second is not first
    assert second.secret_key.get_secret_value() == f"{SAFE_SECRET}-second"
    reset_settings_cache()


@pytest.mark.parametrize(
    "secret",
    [
        None,
        "",
        "too-short",
        "change-me-in-production-please-000000000000",
        "test-only-secret-key-0123456789-ABCDEFGHIJKLMNOPQRSTUVWXYZ",
        "x" * 64,
    ],
)
def test_production_rejects_missing_short_and_placeholder_secrets(secret):
    data = _production_settings_data()
    data["secret_key"] = secret

    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings(**data)


def test_settings_validation_errors_do_not_echo_secret_values():
    secret = "sensitive-synthetic-config-value-1234567890"

    with pytest.raises(ValidationError) as exc_info:
        Settings(app_env="production", secret_key=secret)

    error_text = str(exc_info.value)
    assert secret not in error_text
    assert "input_value" not in error_text


@pytest.mark.parametrize(
    "field",
    [
        "database_url",
        "jwt_issuer",
        "jwt_audience",
        "frontend_url",
        "cors_allowed_origins",
        "google_client_id",
        "microsoft_client_id",
        "microsoft_tenant_id",
        "session_cookie_name",
        "csrf_cookie_name",
        "teacher_invite_hmac_key",
        "admin_access_code",
        "email_host",
        "email_username",
        "email_password",
        "email_from",
    ],
)
def test_production_requires_provider_and_session_settings(field):
    data = _production_settings_data()
    data[field] = () if field == "cors_allowed_origins" else None

    with pytest.raises(ValidationError, match=field.upper()):
        Settings(**data)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("google_client_id", "test-google-client-id"),
        ("microsoft_client_id", "placeholder-client-id"),
        ("microsoft_tenant_id", "test-tenant-id"),
        ("session_cookie_name", "test-session-cookie"),
        ("csrf_cookie_name", "placeholder-csrf-cookie"),
        ("teacher_invite_hmac_key", ""),
        ("admin_access_code", "test-only-admin-access-code"),
    ],
)
def test_production_rejects_placeholder_or_blank_security_settings(field, value):
    data = _production_settings_data()
    data[field] = value

    with pytest.raises(ValidationError, match=f"(?i){field}"):
        Settings(**data)


@pytest.mark.parametrize(
    ("field", "sentinel"),
    [
        ("secret_key", "replace-with-at-least-32-random-characters"),
        ("google_client_id", "replace-with-google-client-id"),
        ("microsoft_client_id", "replace-with-microsoft-client-id"),
        (
            "teacher_invite_hmac_key",
            "replace-with-a-distinct-random-key-of-at-least-32-bytes",
        ),
        ("admin_access_code", "replace-with-admin-access-code"),
        ("admin_code", "replace-with-admin-code"),
    ],
)
def test_production_rejects_every_shipped_security_sentinel(field, sentinel):
    data = _production_settings_data()
    data[field] = sentinel

    with pytest.raises(ValidationError, match=f"(?i){field}"):
        Settings(**data)


@pytest.mark.parametrize(
    "field",
    [
        "google_client_id",
        "microsoft_client_id",
        "microsoft_tenant_id",
        "teacher_invite_hmac_key",
        "admin_access_code",
        "admin_code",
    ],
)
def test_production_rejects_trivially_short_provider_and_provisioning_values(field):
    data = _production_settings_data()
    data[field] = "x"

    with pytest.raises(ValidationError, match=f"(?i){field}"):
        Settings(**data)


def test_production_rejects_insecure_session_and_origin_configuration():
    for field, value in (
        ("session_cookie_secure", False),
        ("session_cookie_name", "litblog-session-cookie"),
        ("csrf_cookie_name", "litblog-csrf-cookie"),
        ("frontend_url", "http://litblogs.example"),
        ("cors_allowed_origins", ("*",)),
        ("access_token_expire_minutes", 121),
    ):
        data = _production_settings_data()
        data[field] = value
        with pytest.raises(ValidationError, match=f"(?i){field}"):
            Settings(**data)


def test_production_requires_distinct_session_and_csrf_cookie_names():
    data = _production_settings_data()
    data["csrf_cookie_name"] = data["session_cookie_name"]

    with pytest.raises(ValidationError, match="(?i)cookie.*differ"):
        Settings(**data)


def test_production_requires_password_reset_delivery_worker():
    data = _production_settings_data()
    data["password_reset_worker_enabled"] = False

    with pytest.raises(ValidationError, match="PASSWORD_RESET_WORKER_ENABLED"):
        Settings(**data)


def test_test_and_development_accept_explicit_nonproduction_placeholders():
    for app_env in ("test", "development"):
        settings = Settings(**_test_settings_data(app_env=app_env))
        assert settings.app_env == app_env
        assert settings.secret_key.get_secret_value() == SAFE_SECRET


def test_production_import_validates_settings_before_engine_creation():
    backend_dir = Path(__file__).resolve().parents[1]
    process_environment = os.environ.copy()
    process_environment.update(
        {
            "APP_ENV": "production",
            "DATABASE_URL": SYNTHETIC_UNREACHABLE_DATABASE_URL,
            "SECRET_KEY": TOO_SHORT_PRODUCTION_SECRET,
        }
    )
    probe = """
import json
import sqlalchemy

engine_called = False

def reject_engine_creation(*args, **kwargs):
    global engine_called
    engine_called = True
    raise AssertionError("database engine creation attempted")

sqlalchemy.create_engine = reject_engine_creation
try:
    import database
except Exception as exc:
    print(json.dumps({"engine_called": engine_called, "error": str(exc)}))
else:
    print(json.dumps({"engine_called": engine_called, "error": None}))
"""

    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=backend_dir,
        env=process_environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    outcome = json.loads(result.stdout)
    assert outcome["engine_called"] is False
    assert "SECRET_KEY" in outcome["error"]


def test_issued_access_tokens_have_fixed_algorithm_complete_claims_and_unique_ids():
    settings = _test_settings()
    now = datetime.now(timezone.utc).replace(microsecond=0)

    first = issue_access_token("42", settings=settings, now=now)
    second = issue_access_token("42", settings=settings, now=now)
    payload = jwt.decode(first, options={"verify_signature": False})

    assert jwt.get_unverified_header(first)["alg"] == "HS256"
    assert payload["sub"] == "42"
    assert payload["iss"] == settings.jwt_issuer
    assert payload["aud"] == settings.jwt_audience
    assert payload["iat"] == int(now.timestamp())
    assert payload["nbf"] == int(now.timestamp())
    assert payload["exp"] == int(
        (now + timedelta(minutes=settings.access_token_expire_minutes)).timestamp()
    )
    assert payload["jti"]
    assert jwt.decode(second, options={"verify_signature": False})["jti"] != payload["jti"]
    assert decode_access_token(first, settings=settings)["sub"] == "42"


@pytest.mark.parametrize("subject", [None, "", "   "])
def test_issuing_access_tokens_rejects_empty_subjects(subject):
    with pytest.raises((TypeError, ValueError), match="subject"):
        issue_access_token(subject, settings=_test_settings())


@pytest.mark.parametrize("missing_claim", ["sub", "iss", "aud", "iat", "nbf", "exp", "jti"])
def test_decode_rejects_every_missing_required_claim(missing_claim):
    settings = _test_settings()
    payload = _valid_payload(settings)
    payload.pop(missing_claim)
    token = _encode(payload, settings)

    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token, settings=settings)


def test_decode_rejects_empty_subject_and_jti():
    settings = _test_settings()
    for claim in ("sub", "jti"):
        payload = _valid_payload(settings)
        payload[claim] = "   "
        with pytest.raises(jwt.InvalidTokenError):
            decode_access_token(_encode(payload, settings), settings=settings)


def test_decode_rejects_expired_and_not_yet_valid_tokens():
    settings = _test_settings()
    now = datetime.now(timezone.utc)
    expired = _valid_payload(settings, now=now)
    expired["exp"] = int((now - timedelta(seconds=10)).timestamp())
    future = _valid_payload(settings, now=now)
    future["nbf"] = int((now + timedelta(minutes=5)).timestamp())

    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(_encode(expired, settings), settings=settings)
    with pytest.raises(jwt.ImmatureSignatureError):
        decode_access_token(_encode(future, settings), settings=settings)


@pytest.mark.parametrize(
    ("claim", "value", "error_type"),
    [
        ("iss", "wrong-issuer", jwt.InvalidIssuerError),
        ("aud", "wrong-audience", jwt.InvalidAudienceError),
    ],
)
def test_decode_rejects_wrong_issuer_and_audience(claim, value, error_type):
    settings = _test_settings()
    payload = _valid_payload(settings)
    payload[claim] = value

    with pytest.raises(error_type):
        decode_access_token(_encode(payload, settings), settings=settings)


def test_decode_rejects_none_and_algorithm_confusion_tokens():
    settings = _test_settings()
    payload = _valid_payload(settings)
    unsigned = jwt.encode(payload, key="", algorithm="none")
    wrong_algorithm = jwt.encode(
        payload,
        key=settings.secret_key.get_secret_value(),
        algorithm="HS384",
    )

    for token in (unsigned, wrong_algorithm):
        with pytest.raises(jwt.InvalidAlgorithmError):
            decode_access_token(token, settings=settings)


def test_token_values_are_never_logged(caplog):
    settings = _test_settings()
    token = issue_access_token("42", settings=settings)

    with caplog.at_level(logging.DEBUG):
        decode_access_token(token, settings=settings)
        with pytest.raises(jwt.InvalidTokenError):
            decode_access_token(f"{token}corrupted", settings=settings)

    assert token not in caplog.text


def test_provisioning_code_comparison_uses_constant_time_bytes(monkeypatch):
    calls = []
    real_compare_digest = auth_security.hmac.compare_digest

    def recording_compare_digest(left, right):
        calls.append((left, right))
        return real_compare_digest(left, right)

    monkeypatch.setattr(auth_security.hmac, "compare_digest", recording_compare_digest)

    assert provisioning_code_matches("café-🔐", "café-🔐")
    assert not provisioning_code_matches("wrong", "café-🔐")
    assert calls == [
        ("café-🔐".encode(), "café-🔐".encode()),
        (b"wrong", "café-🔐".encode()),
    ]


@pytest.mark.parametrize("supplied,configured", [(None, "code"), ("", "code"), ("code", None), (1, "1")])
def test_provisioning_code_comparison_rejects_invalid_inputs(supplied, configured):
    assert not provisioning_code_matches(supplied, configured)


def test_new_password_hashes_use_argon2id_and_verify():
    password_hash = hash_password("synthetic-new-password")

    assert password_hash.startswith("$argon2id$")
    assert verify_password("synthetic-new-password", password_hash)
    assert not verify_password("wrong-password", password_hash)


def test_known_synthetic_bcrypt_fixture_verifies_and_rehashes_to_argon2id():
    valid, upgraded_hash = verify_and_update_password(
        LEGACY_PASSWORD,
        LEGACY_BCRYPT_HASH,
    )

    assert valid
    assert upgraded_hash is not None
    assert upgraded_hash.startswith("$argon2id$")
    assert verify_password(LEGACY_PASSWORD, upgraded_hash)


def test_wrong_legacy_password_does_not_generate_upgrade_hash():
    assert verify_and_update_password("wrong-password", LEGACY_BCRYPT_HASH) == (False, None)


def test_long_legacy_bcrypt_password_verifies_then_upgrades_using_full_password():
    valid, upgraded_hash = verify_and_update_password(
        LONG_LEGACY_PASSWORD,
        LONG_LEGACY_BCRYPT_HASH,
    )

    assert valid
    assert upgraded_hash is not None
    assert upgraded_hash.startswith("$argon2id$")
    assert verify_password(LONG_LEGACY_PASSWORD, upgraded_hash)
    assert not verify_password("L" * 72, upgraded_hash)


def test_password_primitives_reject_oversized_passwords_before_hashing():
    oversized = "x" * (MAX_PASSWORD_BYTES + 1)

    with pytest.raises(ValueError, match="maximum"):
        hash_password(oversized)
    with pytest.raises(ValueError, match="maximum"):
        verify_and_update_password(oversized, LEGACY_BCRYPT_HASH)


def test_login_atomically_upgrades_legacy_bcrypt_hash(client):
    import models
    from database import SessionLocal

    with SessionLocal() as db:
        user = models.User(
            username="legacy-user",
            email="legacy@example.test",
            password=LEGACY_BCRYPT_HASH,
            first_name="Legacy",
            last_name="User",
            role=models.UserRole.STUDENT,
            is_admin=False,
        )
        db.add(user)
        db.commit()
        user_id = user.id

    response = client.post(
        "/api/auth/login",
        json={"email": "legacy@example.test", "password": LEGACY_PASSWORD},
    )

    assert response.status_code == 200
    with SessionLocal() as db:
        upgraded_hash = db.get(models.User, user_id).password
    assert upgraded_hash.startswith("$argon2id$")
    assert verify_password(LEGACY_PASSWORD, upgraded_hash)


def test_password_upgrade_compare_and_swap_preserves_concurrent_reset(client):
    import main
    import models
    from database import SessionLocal

    reset_hash = hash_password("synthetic-reset-password")
    upgraded_hash = hash_password(LEGACY_PASSWORD)
    with SessionLocal() as db:
        user = models.User(
            username="concurrent-reset-user",
            email="concurrent-reset@example.test",
            password=LEGACY_BCRYPT_HASH,
            first_name="Concurrent",
            last_name="Reset",
            role=models.UserRole.STUDENT,
            is_admin=False,
        )
        db.add(user)
        db.commit()
        user_id = user.id

    stale_login_session = SessionLocal()
    try:
        stale_user = stale_login_session.get(models.User, user_id)
        assert stale_user.password == LEGACY_BCRYPT_HASH

        with SessionLocal() as reset_session:
            reset_user = reset_session.get(models.User, user_id)
            reset_user.password = reset_hash
            reset_session.commit()

        persisted = main._persist_password_upgrade_if_current(
            stale_login_session,
            user_id=user_id,
            verified_hash=LEGACY_BCRYPT_HASH,
            upgraded_hash=upgraded_hash,
        )
    finally:
        stale_login_session.close()

    assert persisted is False
    with SessionLocal() as db:
        assert db.get(models.User, user_id).password == reset_hash


def test_malformed_bearer_token_remains_unauthorized(client):
    response = client.get(
        "/api/user/id/1",
        headers={"Authorization": "Bearer not-a-jwt"},
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_main_create_access_token_preserves_mapping_call_semantics():
    import main

    token = main.create_access_token(data={"sub": "42"})

    assert decode_access_token(token)["sub"] == "42"


def _test_settings(**overrides):
    return Settings(**_test_settings_data(**overrides))


def _test_settings_data(**overrides):
    data = {
        "app_env": "test",
        "database_url": "sqlite:///synthetic-test.db",
        "secret_key": SAFE_SECRET,
        "jwt_issuer": "litblog-test",
        "jwt_audience": "litblog-test-clients",
        "access_token_expire_minutes": 30,
        "frontend_url": "http://testserver",
        "cors_allowed_origins": ("http://testserver",),
        "google_client_id": "test-google-client-id",
        "microsoft_client_id": "test-microsoft-client-id",
        "microsoft_tenant_id": "test-tenant-id",
        "session_cookie_name": "test-litblog-session",
        "csrf_cookie_name": "test-litblog-csrf",
        "session_cookie_secure": False,
        "teacher_invite_hmac_key": "test-only-invitation-hmac-key-0123456789",
        "admin_access_code": "test-only-admin-access-code",
    }
    data.update(overrides)
    return data


def _production_settings_data():
    return {
        "app_env": "production",
        "database_url": "postgresql://litblog_app@database.internal/litblog",
        "secret_key": secrets.token_urlsafe(48),
        "jwt_issuer": "https://api.litblogs.school.example",
        "jwt_audience": "litblogs.school.example",
        "access_token_expire_minutes": 30,
        "frontend_url": "https://litblogs.school.example",
        "cors_allowed_origins": ("https://litblogs.school.example",),
        "google_client_id": "987654321.apps.googleusercontent.com",
        "microsoft_client_id": "2f1c67a1-91e2-46a3-941f-b88e31763e51",
        "microsoft_tenant_id": "871bd3e0-2dc0-4a40-9b07-9d03068c2364",
        "microsoft_allowed_tenant_ids": ("871bd3e0-2dc0-4a40-9b07-9d03068c2364",),
        "allowed_email_domains": ("school.example",),
        "session_cookie_name": "__Host-litblog-session",
        "csrf_cookie_name": "__Host-litblog-csrf",
        "session_cookie_secure": True,
        "teacher_invite_hmac_key": secrets.token_urlsafe(48),
        "admin_access_code": secrets.token_urlsafe(24),
        "admin_code": secrets.token_urlsafe(24),
        "email_host": "smtp.school.example",
        "email_username": "litblog-reset",
        "email_password": secrets.token_urlsafe(24),
        "email_from": "no-reply@school.example",
        "password_reset_worker_enabled": True,
    }


def _valid_payload(settings, *, now=None):
    now = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    return {
        "sub": "42",
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "jti": "synthetic-jti",
    }


def _encode(payload, settings):
    return jwt.encode(
        payload,
        settings.secret_key.get_secret_value(),
        algorithm="HS256",
    )
