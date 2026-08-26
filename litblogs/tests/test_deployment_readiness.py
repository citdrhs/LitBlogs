import ast
import base64
import importlib.util
import json
import logging
import os
import re
import secrets
import stat
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import yaml
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.util.exc import CommandError
from dotenv import dotenv_values
from pydantic import ValidationError
from settings_test_support import production_upload_settings
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

import config
from config import Settings

BACKEND_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = BACKEND_DIR.parent


def test_postgres_ca_metadata_contract_is_exact_root_root_0644():
    import deployment_check

    valid = SimpleNamespace(st_mode=stat.S_IFREG | 0o644, st_uid=0, st_gid=0)
    assert deployment_check._postgres_ca_metadata_matches_contract(valid)

    for invalid in (
        SimpleNamespace(st_mode=stat.S_IFREG | 0o640, st_uid=0, st_gid=0),
        SimpleNamespace(st_mode=stat.S_IFREG | 0o664, st_uid=0, st_gid=0),
        SimpleNamespace(st_mode=stat.S_IFREG | 0o644, st_uid=1, st_gid=0),
        SimpleNamespace(st_mode=stat.S_IFREG | 0o644, st_uid=0, st_gid=1),
        SimpleNamespace(st_mode=stat.S_IFDIR | 0o644, st_uid=0, st_gid=0),
    ):
        assert not deployment_check._postgres_ca_metadata_matches_contract(invalid)


def test_production_upload_custody_metadata_is_exact_for_leaf_and_ancestors():
    leaf = SimpleNamespace(st_mode=stat.S_IFDIR | 0o750, st_uid=4242, st_gid=4343)
    assert config._upload_root_metadata_matches_contract(
        leaf,
        required_owner_uid=4242,
        required_group_gid=4343,
    )
    for invalid in (
        SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_uid=4242, st_gid=4343),
        SimpleNamespace(st_mode=stat.S_IFDIR | 0o750, st_uid=4243, st_gid=4343),
        SimpleNamespace(st_mode=stat.S_IFDIR | 0o750, st_uid=4242, st_gid=4344),
        SimpleNamespace(st_mode=stat.S_IFREG | 0o750, st_uid=4242, st_gid=4343),
    ):
        assert not config._upload_root_metadata_matches_contract(
            invalid,
            required_owner_uid=4242,
            required_group_gid=4343,
        )

    ancestor = SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_uid=0, st_gid=0)
    assert config._upload_ancestor_metadata_matches_contract(ancestor)
    for invalid in (
        SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_uid=4242, st_gid=4343),
        SimpleNamespace(st_mode=stat.S_IFDIR | 0o775, st_uid=0, st_gid=0),
        SimpleNamespace(st_mode=stat.S_IFREG | 0o755, st_uid=0, st_gid=0),
    ):
        assert not config._upload_ancestor_metadata_matches_contract(invalid)


@pytest.mark.skipif(
    os.name != "posix" or not hasattr(os, "geteuid") or os.geteuid() == 0,
    reason="requires a non-root POSIX service identity",
)
def test_production_upload_custody_rejects_a_service_owned_ancestor(tmp_path):
    service_parent = tmp_path / "service-owned-parent"
    upload_root = service_parent / "uploads"
    upload_root.mkdir(parents=True, mode=0o750)
    upload_root.chmod(0o750)

    assert not config._has_valid_upload_root_custody(
        upload_root,
        required_owner_uid=os.geteuid(),
        required_group_gid=os.getegid(),
    )


def _production_settings(**overrides):
    values = {
        "app_env": "production",
        "database_url": (
            f"postgresql://litblog_app:{secrets.token_urlsafe(24)}@database.internal/litblog"
            "?sslmode=verify-full&sslrootcert=/etc/litblogs/postgres-root-ca.pem"
        ),
        "secret_key": "A9!production-only-random-secret-0123456789-uvwxyz-XYZ",
        "jwt_issuer": "https://api.litblogs.school.edu",
        "jwt_audience": "litblogs.school.edu",
        "frontend_url": "https://litblogs.school.edu",
        "cors_allowed_origins": ("https://litblogs.school.edu",),
        "allowed_hosts": ("litblogs.school.edu",),
        "allowed_email_domains": ("school.edu",),
        "google_client_id": "987654321.apps.googleusercontent.com",
        "microsoft_client_id": "2f1c67a1-91e2-46a3-941f-b88e31763e51",
        "microsoft_tenant_id": "871bd3e0-2dc0-4a40-9b07-9d03068c2364",
        "microsoft_allowed_tenant_ids": ("871bd3e0-2dc0-4a40-9b07-9d03068c2364",),
        "session_cookie_name": "__Host-litblog-session",
        "csrf_cookie_name": "__Host-litblog-csrf",
        "session_cookie_secure": True,
        "teacher_invite_hmac_key": secrets.token_urlsafe(48),
        "admin_access_code": secrets.token_urlsafe(24),
        "admin_code": secrets.token_urlsafe(24),
        "local_password_registration_enabled": False,
        "email_host": "smtp.school.edu",
        "email_username": "litblogs-mailer",
        "email_password": "smtp-password-4R!v9nK2sQ7x",
        "email_from": "no-reply@school.edu",
        "password_reset_worker_enabled": True,
        **production_upload_settings(),
    }
    values.update(overrides)
    return Settings(**values)


def test_production_upload_root_is_the_exact_deployment_path(monkeypatch):
    expected_root = Path("/var/lib/litblogs/uploads")
    monkeypatch.setattr(config, "PRODUCTION_UPLOAD_ROOT", expected_root)
    monkeypatch.setattr(config, "_has_valid_upload_root_custody", lambda _root: True)

    settings = _production_settings(upload_root=expected_root)
    assert settings.upload_root == expected_root

    with pytest.raises(ValidationError, match="must be /var/lib/litblogs/uploads"):
        _production_settings(upload_root=Path("/srv/litblogs/uploads"))


@pytest.mark.parametrize(
    "database_url",
    [
        "sqlite:///production.db",
        "postgresql://litblog_app@database.internal/litblog",
        "postgresql://litblog_app@database.internal/litblog?sslmode=disable",
        "postgresql://litblog_app@database.internal/litblog?sslmode=allow",
        "postgresql://litblog_app@database.internal/litblog?service=production",
        "postgresql://litblog_app@database.internal/litblog?host=elsewhere.internal&sslmode=require",
        "postgresql://litblog_app@database.internal/litblog?sslmode=verify-full",
        (
            "postgresql://database.internal/litblog"
            "?sslmode=verify-full&sslrootcert=/etc/litblogs/ca.pem"
        ),
        (
            "postgresql://litblog_app@database.internal/litblog"
            "?sslmode=verify-full&sslrootcert=/etc/litblogs/ca.pem"
        ),
        (
            "postgresql://litblog_app:short@database.internal/litblog"
            "?sslmode=verify-full&sslrootcert=/etc/litblogs/ca.pem"
        ),
        (
            "postgresql://litblog_app:replace-with-password@database.internal/litblog"
            "?sslmode=verify-full&sslrootcert=/etc/litblogs/ca.pem"
        ),
        (
            "postgresql://litblog_app@database.internal/litblog"
            "?sslmode=verify-full&sslrootcert=relative/ca.pem"
        ),
        (
            "postgresql://litblog_app@database.internal/litblog"
            "?sslmode=verify-full&sslrootcert=/tmp/unreviewed-ca.pem"
        ),
        (
            "postgresql://litblog_app@database.internal/litblog"
            "?sslmode=verify-full&sslrootcert=/etc/litblogs/../private/ca.pem"
        ),
        (
            "postgresql://litblog_app@database.internal/litblog"
            "?sslmode=verify-full&sslrootcert=/etc/litblogs/%2e%2e/private/ca.pem"
        ),
        (
            "postgresql://litblog_app@database.internal/litblog"
            "?sslmode=verify-full&sslrootcert=/etc/litblogs/ca.pem&options=-c%20search_path%3Dother"
        ),
        (
            "postgresql://litblog_app@database.internal/litblog"
            "?sslmode=verify-full&sslrootcert=/etc/litblogs/ca.pem&connect_timeout=99"
        ),
        (
            "postgresql://litblog_app@database.internal,alternate.internal/litblog"
            "?sslmode=verify-full&sslrootcert=/etc/litblogs/ca.pem"
        ),
        (
            "postgresql://litblog_app@database.internal%2Calternate.internal/litblog"
            "?sslmode=verify-full&sslrootcert=/etc/litblogs/ca.pem"
        ),
    ],
)
def test_production_rejects_non_postgres_or_unverified_database_targets(database_url):
    with pytest.raises(ValidationError, match="(?i)database_url"):
        _production_settings(database_url=database_url)


def test_production_database_url_requires_the_canonical_postgres_ca_path():
    alternate_ca = (
        f"postgresql://litblog_app:{secrets.token_urlsafe(24)}@database.internal/litblog"
        "?sslmode=verify-full&sslrootcert=/etc/litblogs/alternate-root-ca.pem"
    )

    with pytest.raises(ValidationError, match="(?i)database_url"):
        _production_settings(database_url=alternate_ca)


def test_settings_repr_does_not_disclose_database_credentials():
    database_password = "db-private-credential-4R9nK2sQ7x"
    settings = _production_settings(
        database_url=(
            f"postgresql://litblog_app:{database_password}@database.internal/litblog"
            "?sslmode=verify-full&sslrootcert=/etc/litblogs/postgres-root-ca.pem"
        )
    )

    assert database_password not in repr(settings)


def test_production_rejects_startup_schema_reset():
    with pytest.raises(ValidationError, match="(?i)reset_database_on_startup"):
        _production_settings(reset_database_on_startup=True)


@pytest.mark.parametrize("allowed_hosts", [(), ("*",), ("https://litblogs.school.example",)])
def test_production_requires_exact_trusted_hosts(allowed_hosts):
    with pytest.raises(ValidationError, match="(?i)allowed_hosts"):
        _production_settings(allowed_hosts=allowed_hosts)


def test_production_frontend_origin_matches_cors_and_trusted_host():
    with pytest.raises(ValidationError, match="(?i)cors_allowed_origins"):
        _production_settings(cors_allowed_origins=("https://other.school.edu",))

    with pytest.raises(ValidationError, match="(?i)allowed_hosts"):
        _production_settings(allowed_hosts=("other.school.edu",))


def test_production_frontend_url_is_the_root_https_origin():
    with pytest.raises(
        ValidationError,
        match="FRONTEND_URL must use the root HTTPS origin",
    ):
        _production_settings(frontend_url="https://litblogs.school.edu/school-app")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("cors_allowed_origins", ("https://user@litblogs.school.example",)),
        ("cors_allowed_origins", ("https://litblogs.school.example?source=other",)),
        ("cors_allowed_origins", ("https://litblogs.school.example#other",)),
        ("frontend_url", "https://user@litblogs.school.example"),
        ("frontend_url", "https://litblogs.school.example#other"),
        ("frontend_url", "https://litblogs.school.edu/school-app"),
    ],
)
def test_production_rejects_ambiguous_browser_origins(field, value):
    with pytest.raises(ValidationError, match=f"(?i){field}"):
        _production_settings(**{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("session_cookie_name", "litblog-session"),
        ("session_cookie_name", "__Secure-litblog-session"),
        ("session_cookie_name", "__Host-invalid cookie"),
        ("csrf_cookie_name", "litblog-csrf"),
        ("csrf_cookie_name", "__Host-"),
    ],
)
def test_production_requires_host_prefixed_cookie_names(field, value):
    with pytest.raises(ValidationError, match=f"(?i){field}"):
        _production_settings(**{field: value})


def test_production_requires_distinct_session_and_csrf_cookie_names():
    with pytest.raises(ValidationError, match="(?i)cookie"):
        _production_settings(
            session_cookie_name="__Host-litblog-session",
            csrf_cookie_name="__Host-litblog-session",
        )


@pytest.mark.parametrize(
    "jwt_issuer",
    (
        "http://api.litblogs.school.example",
        "https://user@api.litblogs.school.example",
        "https://api.litblogs.school.example?tenant=other",
        "https://api.litblogs.school.example#other",
    ),
)
def test_production_requires_unambiguous_https_jwt_issuer(jwt_issuer):
    with pytest.raises(ValidationError, match="(?i)jwt_issuer"):
        _production_settings(jwt_issuer=jwt_issuer)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("jwt_issuer", "https://api.litblogs.school.example"),
        ("jwt_audience", "litblogs.school.example"),
        ("frontend_url", "https://litblogs.school.test"),
        ("cors_allowed_origins", ("https://litblogs.school.invalid",)),
        ("allowed_hosts", ("litblogs.school.example",)),
        ("allowed_email_domains", ("school.example",)),
        ("email_host", "smtp.school.example"),
        ("email_from", "no-reply@school.example"),
    ],
)
def test_production_rejects_reserved_example_network_identifiers(field, value):
    with pytest.raises(ValidationError, match=f"(?i){field}"):
        _production_settings(**{field: value})


@pytest.mark.parametrize(
    "field",
    ("email_host", "email_username", "email_password", "email_from"),
)
def test_production_requires_password_recovery_delivery_settings(field):
    with pytest.raises(ValidationError, match=f"(?i){field}"):
        _production_settings(**{field: None})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("email_host", "http://smtp.school.example"),
        ("email_host", "localhost"),
        ("email_from", "not-an-email"),
        ("email_password", "replace-with-email-password"),
    ],
)
def test_production_rejects_unsafe_password_recovery_delivery_settings(field, value):
    with pytest.raises(ValidationError, match=f"(?i){field}"):
        _production_settings(**{field: value})


def _base64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def test_push_delivery_stays_disabled_until_endpoint_ssrf_controls_exist():
    assert _production_settings().push_notifications_enabled is False

    with pytest.raises(ValidationError, match="(?i)push_notifications_enabled"):
        _production_settings(
            push_notifications_enabled=True,
            vapid_public_key=_base64url(b"\x04" + (b"\x01" * 64)),
            vapid_private_key=_base64url(b"\x02" * 32),
            vapid_subject="mailto:admin@school.edu",
        )


def test_cors_and_host_middleware_use_explicit_browser_boundaries():
    import main

    middleware_options = {
        middleware.cls.__name__: middleware.kwargs for middleware in main.app.user_middleware
    }
    cors = middleware_options["CORSMiddleware"]
    trusted_hosts = middleware_options["TrustedHostMiddleware"]["allowed_hosts"]

    assert cors["allow_methods"] == ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
    assert cors["allow_headers"] == [
        "Accept",
        "Authorization",
        "Content-Type",
        "X-CSRF-Token",
    ]
    assert "*" not in trusted_hosts
    assert "testserver" in trusted_hosts


def test_database_engine_uses_bounded_resilient_production_options():
    import database

    options = database.engine_options(_production_settings())

    assert options["pool_pre_ping"] is True
    assert options["pool_size"] == 5
    assert options["max_overflow"] == 5
    assert options["pool_timeout"] == 10
    assert options["pool_recycle"] == 900
    assert options["connect_args"]["connect_timeout"] == 5
    assert options["connect_args"]["application_name"] == "litblogs-web"
    assert "statement_timeout=15000" in options["connect_args"]["options"]
    assert "lock_timeout=5000" in options["connect_args"]["options"]


def test_runtime_source_contains_no_schema_creation_or_reset_calls():
    forbidden = {"create_all", "drop_all", "initialize_database", "reset_database"}
    violations = []
    for relative_path in ("database.py", "main.py"):
        path = BACKEND_DIR / relative_path
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            name = None
            if isinstance(node, ast.Name):
                name = node.id
            elif isinstance(node, ast.Attribute):
                name = node.attr
            if name in forbidden:
                violations.append(f"{relative_path}:{node.lineno}:{name}")
    assert violations == []


def test_web_lifespan_does_not_start_an_in_process_scheduler():
    source = (BACKEND_DIR / "main.py").read_text(encoding="utf-8")

    assert "_start_push_scheduler()" not in source
    assert "threading.Thread(" not in source


def test_reminder_job_skips_when_another_database_worker_holds_the_lock(monkeypatch):
    import main

    db = MagicMock()
    monkeypatch.setattr(main, "WEB_PUSH_ENABLED", True)
    monkeypatch.setattr(main, "SessionLocal", lambda: db)
    monkeypatch.setattr(main, "_try_acquire_reminder_dispatch_lock", lambda _db: False)

    assert main._dispatch_assignment_push_reminders_once() is True
    db.query.assert_not_called()
    db.close.assert_called_once_with()


def test_reminder_job_rolls_back_and_never_logs_database_error_details(monkeypatch, caplog):
    import main

    db = MagicMock()
    db.query.side_effect = RuntimeError(
        "postgresql://private-user:private-password@db.internal/private"
    )
    monkeypatch.setattr(main, "WEB_PUSH_ENABLED", True)
    monkeypatch.setattr(main, "SessionLocal", lambda: db)
    monkeypatch.setattr(main, "_try_acquire_reminder_dispatch_lock", lambda _db: True)

    with caplog.at_level(logging.ERROR):
        assert main._dispatch_assignment_push_reminders_once() is False

    db.rollback.assert_called_once_with()
    assert "push_reminder_dispatch_failed" in caplog.text
    assert "private-password" not in caplog.text


def test_liveness_and_readiness_are_distinct_and_generic(
    client, monkeypatch, caplog
):
    import main

    live = client.get("/api/health/live")
    assert live.status_code == 200
    assert live.json() == {"status": "ok"}

    monkeypatch.setattr(main, "check_database_readiness", lambda: None)
    ready = client.get("/api/health/ready")
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready"}

    def fail_readiness():
        raise RuntimeError("postgresql://private-user:private-password@db.internal/private")

    monkeypatch.setattr(main, "check_database_readiness", fail_readiness)
    with caplog.at_level(logging.ERROR, logger="litblogs.readiness"):
        unavailable = client.get("/api/health/ready")
    assert unavailable.status_code == 503
    assert unavailable.json() == {"detail": "Service not ready"}
    assert "private" not in unavailable.text
    events = [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "litblogs.readiness"
    ]
    assert events == [
        {
            "event": "readiness_failed",
            "reason": "migration_mismatch",
            "request_id": unavailable.headers["x-request-id"],
        }
    ]
    assert "private-password" not in caplog.text


def test_readiness_logs_database_unreachable_without_reflecting_the_cause(
    client, monkeypatch, caplog
):
    import main

    def fail_readiness():
        raise ConnectionError("host=db.internal password=private-password")

    monkeypatch.setattr(main, "check_database_readiness", fail_readiness)
    with caplog.at_level(logging.ERROR, logger="litblogs.readiness"):
        unavailable = client.get("/api/health/ready")

    event = next(
        json.loads(record.message)
        for record in caplog.records
        if record.name == "litblogs.readiness"
    )
    assert event == {
        "event": "readiness_failed",
        "reason": "database_unreachable",
        "request_id": unavailable.headers["x-request-id"],
    }
    assert unavailable.status_code == 503
    assert unavailable.json() == {"detail": "Service not ready"}
    assert "private-password" not in caplog.text


def test_request_observability_uses_unique_ids_and_structured_non_sensitive_logs(client, caplog):
    with caplog.at_level(logging.INFO, logger="litblogs.requests"):
        first = client.get("/api/health/live?token=must-not-be-logged")
        second = client.get("/api/health/live")

    first_id = first.headers["x-request-id"]
    second_id = second.headers["x-request-id"]
    assert first.headers["cache-control"] == "no-store"
    assert first.headers["pragma"] == "no-cache"
    assert first.headers["x-content-type-options"] == "nosniff"
    assert first.headers["referrer-policy"] == "no-referrer"
    assert len(first_id) == 32
    assert all(character in "0123456789abcdef" for character in first_id)
    assert second_id != first_id

    events = [json.loads(record.message) for record in caplog.records]
    completed = [event for event in events if event.get("event") == "request_complete"]
    assert len(completed) == 2
    assert {event["request_id"] for event in completed} == {first_id, second_id}
    assert all(event["route"] == "/api/health/live" for event in completed)
    assert all(event["method"] == "GET" and event["status"] == 200 for event in completed)
    assert "must-not-be-logged" not in caplog.text


def test_request_observability_reuses_only_well_formed_proxy_request_ids(client, caplog):
    trusted_proxy_id = "a" * 32
    with caplog.at_level(logging.INFO, logger="litblogs.requests"):
        correlated = client.get(
            "/api/health/live", headers={"X-Request-ID": trusted_proxy_id}
        )
        rejected = client.get(
            "/api/health/live", headers={"X-Request-ID": "attacker-controlled-value"}
        )

    assert correlated.headers["x-request-id"] == trusted_proxy_id
    assert rejected.headers["x-request-id"] != "attacker-controlled-value"
    assert len(rejected.headers["x-request-id"]) == 32
    events = [json.loads(record.message) for record in caplog.records]
    assert any(event.get("request_id") == trusted_proxy_id for event in events)


def test_unhandled_errors_are_generic_correlated_and_do_not_log_exception_details(caplog):
    from observability import RequestObservabilityMiddleware

    async def fail(_request):
        raise RuntimeError("postgresql://private:password@db.internal/private")

    error_app = Starlette(routes=[Route("/boom", fail)])
    error_app.add_middleware(RequestObservabilityMiddleware)
    with caplog.at_level(logging.INFO, logger="litblogs.requests"):
        response = TestClient(error_app, raise_server_exceptions=False).get("/boom")

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert len(response.headers["x-request-id"]) == 32
    assert "password" not in caplog.text
    failed = [json.loads(record.message) for record in caplog.records]
    assert failed[-1]["event"] == "request_failed"


def test_production_api_docs_default_to_disabled():
    settings = _production_settings()

    assert settings.api_docs_enabled is False


def test_public_runtime_config_is_backend_derived_and_contains_no_secrets(client):
    response = client.get("/api/runtime-config")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "csrf_cookie_name": "test-litblog-csrf",
        "google_client_id": "test-google-client-id",
        "microsoft_client_id": "test-microsoft-client-id",
        "microsoft_tenant_id": "871bd3e0-2dc0-4a40-9b07-9d03068c2364",
        "local_password_registration_enabled": True,
    }
    serialized = response.text.lower()
    for forbidden in (
        "test-only-secret-key",
        "test-only-admin",
        "sqlite://",
        "vapid_private",
        "teacher_invite_hmac",
    ):
        assert forbidden not in serialized


def test_admin_provisioning_secrets_are_server_only_runtime_configuration():
    import main

    example = (BACKEND_DIR / ".env.example").read_text(encoding="utf-8")
    response_fields = set(main.PublicRuntimeConfigResponse.model_fields)

    assert "admin_access_code" in Settings.model_fields
    assert "admin_code" in Settings.model_fields
    assert {"admin_access_code", "admin_code"}.isdisjoint(response_fields)
    assert "VITE_ADMIN_ACCESS_CODE" not in example
    assert "VITE_ADMIN_CODE" not in example
    assert "ALGORITHM=" not in example


def test_release_admission_requires_every_shipped_runtime_module():
    import deployment_check

    required = set(deployment_check.REQUIRED_RELEASE_FILES)
    assert {
        "litblogs/access_control.py",
        "litblogs/auth_security.py",
        "litblogs/base.py",
        "litblogs/identity_controls.py",
        "litblogs/manage_accounts.py",
        "litblogs/manage_teacher_invitations.py",
        "litblogs/migrations/sqlite_contract.py",
        "litblogs/models.py",
        "litblogs/oauth_security.py",
        "litblogs/operator_runtime.py",
        "litblogs/password_reset_delivery.py",
        "litblogs/THIRD_PARTY_EDITOR_NOTICES.md",
        "litblogs/rich_text_contract.json",
        "litblogs/rich_text_contract.py",
        "litblogs/rich_text_security.py",
        "litblogs/reminder_job.py",
        "litblogs/runtime_database_identity.py",
        "litblogs/schemas.py",
        "litblogs/security_utils.py",
        "litblogs/upload_assets.py",
        "litblogs/upload_legacy_inventory.py",
        "litblogs/upload_scanner.py",
        "deploy/scripts/upload_snapshot_common.py",
    }.issubset(required)


def test_nginx_csp_preserves_the_self_hosted_privacy_contract():
    nginx = (ROOT_DIR / "deploy" / "nginx" / "litblogs.conf").read_text(
        encoding="utf-8"
    )
    forbidden_origins = (
        "cdn.tiny.cloud",
        "tiny.cloud",
        "sp.tinymce.com",
        "fonts.googleapis.com",
        "fonts.gstatic.com",
        "images.unsplash.com",
    )
    assert all(origin not in nginx for origin in forbidden_origins)

    expected_csp = (
        "default-src 'self'; base-uri 'self'; object-src 'none'; "
        "frame-ancestors 'none'; form-action 'self'; script-src 'self' "
        "https://accounts.google.com https://apis.google.com; style-src 'self' "
        "'unsafe-inline' https://accounts.google.com; font-src 'self' data:; "
        "img-src 'self' data: blob: https://*.googleusercontent.com; media-src "
        "'self' data: blob:; connect-src 'self' https://accounts.google.com "
        "https://login.microsoftonline.com https://graph.microsoft.com; frame-src "
        "'self' https://accounts.google.com https://login.microsoftonline.com; "
        "worker-src 'self' blob:; manifest-src 'self'; upgrade-insecure-requests"
    )
    csp_values = re.findall(
        r'add_header Content-Security-Policy "([^"]+)" always;', nginx
    )
    assert len(csp_values) == 5
    assert set(csp_values) == {expected_csp}


def _nginx_hashed_asset_locations(nginx):
    return [
        (re.compile(match.group("pattern"), re.IGNORECASE), match.group("body"))
        for match in re.finditer(
            r'location ~\* "(?P<pattern>\^/assets/[^\"]+)" \{(?P<body>.*?)\n    \}',
            nginx,
            re.DOTALL,
        )
    ]


def test_nginx_immutably_caches_standard_hashed_tutorial_assets():
    nginx = (ROOT_DIR / "deploy" / "nginx" / "litblogs.conf").read_text(
        encoding="utf-8"
    )
    standard_locations = [
        (pattern, body)
        for pattern, body in _nginx_hashed_asset_locations(nginx)
        if all(
            pattern.fullmatch(f"/assets/litblogs-tutorial-AbCdEf12.{extension}")
            for extension in ("jpg", "mp4", "txt")
        )
    ]

    assert len(standard_locations) == 1
    asset_pattern, hashed_assets = standard_locations[0]
    assert not asset_pattern.fullmatch(
        "/assets/litblogs-tutorial-AbCdEf12.vtt"
    )

    assert not asset_pattern.fullmatch("/assets/tutorial.mp4")
    assert 'Cache-Control "public, max-age=31536000, immutable" always' in hashed_assets
    assert "try_files $uri =404;" in hashed_assets
    assert "proxy_pass" not in hashed_assets
    assert "max_ranges 0;" not in nginx


def test_nginx_hashed_webvtt_assets_have_an_explicit_caption_mime_type():
    nginx = (ROOT_DIR / "deploy" / "nginx" / "litblogs.conf").read_text(
        encoding="utf-8"
    )
    vtt_path = "/assets/litblogs-tutorial-AbCdEf12.vtt"
    vtt_locations = [
        (pattern, body)
        for pattern, body in _nginx_hashed_asset_locations(nginx)
        if pattern.fullmatch(vtt_path)
    ]

    assert len(vtt_locations) == 1
    vtt_pattern, vtt_assets = vtt_locations[0]
    assert not vtt_pattern.fullmatch("/assets/litblogs-tutorial-AbCdEf12.mp4")
    assert "default_type text/vtt;" in vtt_assets
    assert 'Cache-Control "public, max-age=31536000, immutable" always' in vtt_assets
    assert "try_files $uri =404;" in vtt_assets
    assert "proxy_pass" not in vtt_assets
    for header in (
        "Strict-Transport-Security",
        "Content-Security-Policy",
        "X-Frame-Options",
        "X-Content-Type-Options",
        "Referrer-Policy",
        "Permissions-Policy",
        "Cross-Origin-Opener-Policy",
        "Cross-Origin-Resource-Policy",
    ):
        assert f"add_header {header} " in vtt_assets


def test_nginx_content_server_uses_the_complete_distribution_mime_table():
    nginx = (ROOT_DIR / "deploy" / "nginx" / "litblogs.conf").read_text(
        encoding="utf-8"
    )
    content_server = nginx.split("server {\n    listen 443 ssl http2;", 1)[1]

    assert content_server.count("include /etc/nginx/mime.types;") == 1
    assert re.search(r"(?m)^\s*types\s*\{", nginx) is None


def _write_deployment_release(tmp_path):
    import deployment_check

    release_root = tmp_path / "release"
    required_files = (
        *deployment_check.REQUIRED_RELEASE_FILES,
        "litblogs/migrations/versions/reviewed_revision.py",
    )
    for relative_path in required_files:
        path = release_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if relative_path == "litblogs/rich_text_contract.json":
            path.write_text(
                (BACKEND_DIR / "rich_text_contract.json").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
        else:
            path.write_text("reviewed release file\n", encoding="utf-8")
    dist = release_root / "litblogs" / "dist"
    (dist / "assets").mkdir(parents=True, exist_ok=True)
    (dist / "index.html").write_text("<!doctype html>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text(
        'fetch("/api/runtime-config")', encoding="utf-8"
    )
    (release_root / "RELEASE-MANIFEST").write_text(
        "commit=0123456789abcdef0123456789abcdef01234567\n"
        "built_at_epoch=1787350000\n",
        encoding="utf-8",
    )
    return release_root


def test_pretraffic_deployment_check_requires_manifest_assets_and_database(
    tmp_path, capsys, monkeypatch
):
    import deployment_check

    release_root = _write_deployment_release(tmp_path)
    calls = []
    real_contract_validator = deployment_check.validate_rich_text_contract
    monkeypatch.setattr(
        deployment_check,
        "validate_rich_text_contract",
        lambda path: (
            calls.append(("contract", Path(path).relative_to(release_root).as_posix())),
            real_contract_validator(path),
        )[1],
    )

    result = deployment_check.run(
        app_settings=SimpleNamespace(
            app_env="production", database_url="postgresql://validated"
        ),
        release_root=release_root,
        database_check=lambda: calls.append("database"),
        migration_drift_check=lambda: calls.append("drift"),
        ca_custody_check=lambda _database_url: calls.append("ca"),
        interpreter_version=(3, 13),
    )

    assert result == 0
    assert calls == [
        "ca",
        ("contract", "litblogs/rich_text_contract.json"),
        "database",
        "drift",
    ]
    assert capsys.readouterr().out.strip() == "deployment-check: ready"


def test_deployment_check_rejects_an_invalid_rich_text_contract(tmp_path, capsys):
    import deployment_check

    release_root = _write_deployment_release(tmp_path)
    (release_root / "litblogs" / "rich_text_contract.json").write_text(
        '{"schemaVersion":1,"schemaVersion":1}', encoding="utf-8"
    )

    result = deployment_check.run(
        app_settings=SimpleNamespace(
            app_env="production", database_url="postgresql://validated"
        ),
        release_root=release_root,
        database_check=lambda: None,
        migration_drift_check=lambda: None,
        ca_custody_check=lambda _database_url: None,
        interpreter_version=(3, 13),
    )

    assert result == 1
    assert capsys.readouterr().err.strip() == (
        "deployment-check: failed code=manifest_invalid"
    )


def test_artifact_preflight_does_not_require_database_at_migration_head(tmp_path, capsys):
    import deployment_check

    calls = []
    result = deployment_check.run(
        app_settings=SimpleNamespace(
            app_env="production", database_url="postgresql://validated"
        ),
        release_root=_write_deployment_release(tmp_path),
        database_check=lambda: calls.append("database"),
        migration_drift_check=lambda: calls.append("drift"),
        ca_custody_check=lambda _database_url: calls.append("ca"),
        interpreter_version=(3, 13),
        mode="preflight",
    )

    assert result == 0
    assert calls == ["ca"]
    assert capsys.readouterr().out.strip() == "deployment-check: ready"


@pytest.mark.skipif(os.name != "posix", reason="POSIX ownership and modes required")
def test_deployment_check_rejects_a_ca_beneath_a_mutable_trust_directory(
    tmp_path,
):
    import deployment_check

    trust_root = tmp_path / "managed-trust"
    certificate_directory = trust_root / "etc" / "litblogs"
    certificate_directory.mkdir(parents=True)
    certificate = certificate_directory / "postgres-root-ca.pem"
    certificate.write_text("synthetic test CA", encoding="utf-8")
    certificate.chmod(0o644)
    metadata = certificate.stat()
    database_url = (
        "postgresql://litblogs_runtime:managed-password-4R%21v9nK2sQ7x@db.school.edu/"
        f"litblogs?sslmode=verify-full&sslrootcert={certificate}"
    )

    deployment_check._validate_postgres_ca_custody(
        database_url,
        required_owner_uid=metadata.st_uid,
        required_group_gid=metadata.st_gid,
        trusted_ancestor=tmp_path,
    )

    trust_root.chmod(0o775)
    with pytest.raises(deployment_check._DeploymentFailure) as failure:
        deployment_check._validate_postgres_ca_custody(
            database_url,
            required_owner_uid=metadata.st_uid,
            required_group_gid=metadata.st_gid,
            trusted_ancestor=tmp_path,
        )
    assert failure.value.code == "config_invalid"


@pytest.mark.parametrize(
    ("overrides", "expected_code"),
    [
        ({"app_settings": SimpleNamespace(app_env="development")}, "config_invalid"),
        ({"interpreter_version": (3, 12)}, "interpreter_invalid"),
    ],
)
def test_deployment_check_reports_only_bounded_safe_preflight_codes(
    tmp_path, capsys, overrides, expected_code
):
    import deployment_check

    arguments = {
        "app_settings": SimpleNamespace(
            app_env="production", database_url="postgresql://validated"
        ),
        "release_root": _write_deployment_release(tmp_path),
        "database_check": lambda: None,
        "migration_drift_check": lambda: None,
        "ca_custody_check": lambda _database_url: None,
        "interpreter_version": (3, 13),
    }
    arguments.update(overrides)
    result = deployment_check.run(**arguments)

    captured = capsys.readouterr()
    assert result == 1
    assert captured.err.strip() == f"deployment-check: failed code={expected_code}"


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        (
            ConnectionError("postgresql://private:password@db.internal/private"),
            "database_unreachable",
        ),
        (
            RuntimeError("unexpected revision; token=private-secret"),
            "migration_mismatch",
        ),
    ],
)
def test_deployment_check_redacts_database_failures(tmp_path, capsys, failure, expected_code):
    import deployment_check

    result = deployment_check.run(
        app_settings=SimpleNamespace(
            app_env="production", database_url="postgresql://validated"
        ),
        release_root=_write_deployment_release(tmp_path),
        database_check=lambda: (_ for _ in ()).throw(failure),
        migration_drift_check=lambda: None,
        ca_custody_check=lambda _database_url: None,
        interpreter_version=(3, 13),
    )

    captured = capsys.readouterr()
    assert result == 1
    assert captured.err.strip() == f"deployment-check: failed code={expected_code}"
    assert "password" not in captured.err
    assert "private-secret" not in captured.err


def test_deployment_check_fails_closed_on_alembic_schema_drift(tmp_path, capsys):
    import deployment_check

    result = deployment_check.run(
        app_settings=SimpleNamespace(
            app_env="production", database_url="postgresql://validated"
        ),
        release_root=_write_deployment_release(tmp_path),
        database_check=lambda: None,
        migration_drift_check=lambda: (_ for _ in ()).throw(
            RuntimeError("private table drift and token=secret")
        ),
        ca_custody_check=lambda _database_url: None,
        interpreter_version=(3, 13),
    )

    captured = capsys.readouterr()
    assert result == 1
    assert captured.err.strip() == "deployment-check: failed code=migration_mismatch"
    assert "private table" not in captured.err
    assert "secret" not in captured.err


def test_deployment_check_distinguishes_manifest_and_frontend_contract_failures(
    tmp_path, capsys
):
    import deployment_check

    release_root = _write_deployment_release(tmp_path)
    (release_root / "RELEASE-MANIFEST").write_text(
        "commit=secret-bearing-malformed-value\n", encoding="utf-8"
    )
    assert (
        deployment_check.run(
            app_settings=SimpleNamespace(
                app_env="production", database_url="postgresql://validated"
            ),
            release_root=release_root,
            database_check=lambda: None,
            migration_drift_check=lambda: None,
            ca_custody_check=lambda _database_url: None,
            interpreter_version=(3, 13),
        )
        == 1
    )
    assert capsys.readouterr().err.strip() == (
        "deployment-check: failed code=manifest_invalid"
    )

    release_root = _write_deployment_release(tmp_path)
    (release_root / "litblogs" / "dist" / "assets" / "app.js").write_text(
        'const clientId = "VITE_GOOGLE_CLIENT_ID"', encoding="utf-8"
    )
    assert (
        deployment_check.run(
            app_settings=SimpleNamespace(
                app_env="production", database_url="postgresql://validated"
            ),
            release_root=release_root,
            database_check=lambda: None,
            migration_drift_check=lambda: None,
            ca_custody_check=lambda _database_url: None,
            interpreter_version=(3, 13),
        )
        == 1
    )
    assert capsys.readouterr().err.strip() == (
        "deployment-check: failed code=frontend_contract_invalid"
    )


def test_alembic_is_pinned_and_single_head_configuration_is_tracked():
    assert importlib.util.find_spec("alembic") is not None
    requirements = (BACKEND_DIR / "requirements.txt").read_text(encoding="utf-8")
    assert "alembic==" in requirements.lower()
    assert (BACKEND_DIR / "alembic.ini").is_file()
    assert (BACKEND_DIR / "migrations" / "env.py").is_file()
    versions = sorted((BACKEND_DIR / "migrations" / "versions").glob("*.py"))
    assert versions
    scripts = ScriptDirectory.from_config(_alembic_config())
    assert len(scripts.get_heads()) == 1


def test_alembic_autogeneration_compares_types_and_server_defaults_in_every_mode():
    environment = (BACKEND_DIR / "migrations" / "env.py").read_text(encoding="utf-8")
    assert environment.count("compare_type=True") == 3
    assert environment.count("compare_server_default=True") == 3
    assert "LITBLOGS_MIGRATION_DATABASE_URL" in environment
    assert "get_settings" not in environment
    assert "disable_existing_loggers=False" in environment


def test_supplied_connection_drift_check_needs_no_app_or_migration_secrets(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("LITBLOGS_MIGRATION_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    engine = create_engine(f"sqlite:///{(tmp_path / 'drift.db').as_posix()}")

    with engine.connect() as connection:
        with pytest.raises(CommandError):
            command.check(_alembic_config(connection))
    engine.dispose()


def test_env_example_initializes_local_sqlite_idempotently(tmp_path, monkeypatch):
    example = dotenv_values(BACKEND_DIR / ".env.example")
    assert example["APP_ENV"] == "development"
    assert example["DATABASE_URL"] == "sqlite:///./litblogs.db"
    assert example["LITBLOGS_MIGRATION_DATABASE_URL"] == example["DATABASE_URL"]

    database_name = f".pytest-{tmp_path.name}.db"
    database_path = BACKEND_DIR / database_name
    database_url = f"sqlite:///./{database_name}"
    monkeypatch.chdir(BACKEND_DIR)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("LITBLOGS_MIGRATION_DATABASE_URL", database_url)
    try:
        command.upgrade(_alembic_config(), "head")
        command.upgrade(_alembic_config(), "head")
        engine = create_engine(database_url)
        assert _current_revision(engine) == _head_revision()
        engine.dispose()
    finally:
        database_path.unlink(missing_ok=True)


def test_release_artifact_uses_a_runtime_allowlist_instead_of_shipping_the_repository():
    release = (ROOT_DIR / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )

    assert (
        "git archive --format=tar HEAD -- deploy docs/operations litblogs/*.py "
        "litblogs/rich_text_contract.json litblogs/THIRD_PARTY_EDITOR_NOTICES.md "
        "litblogs/alembic.ini litblogs/migrations/env.py "
        "litblogs/migrations/sqlite_contract.py "
        "litblogs/migrations/script.py.mako litblogs/migrations/versions "
        "litblogs/requirements.txt "
        "litblogs/requirements.in litblogs/requirements-lock.txt "
        "litblogs/requirements-lock.in" in release
    )
    assert "git archive --format=tar HEAD |" not in release
    assert 'test -f "$staging/tree/litblogs/rich_text_contract.json"' in release
    assert 'test -f "$staging/tree/litblogs/THIRD_PARTY_EDITOR_NOTICES.md"' in release
    assert 'test -f "$staging/tree/litblogs/rich_text_contract.py"' in release
    assert 'test -f "$staging/tree/litblogs/rich_text_security.py"' in release
    assert "litblogs/migrations/0001_create_federated_identities.sql" not in release
    assert "litblogs/alembic.ini litblogs/migrations litblogs/requirements" not in release

    deploy_readme = (ROOT_DIR / "deploy" / "README.md").read_text(encoding="utf-8")
    assert "`litblogs/migrations/sqlite_contract.py`" in deploy_readme


def test_release_attestation_permissions_are_isolated_from_dependency_execution():
    workflow_path = ROOT_DIR / ".github" / "workflows" / "release.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    jobs = workflow["jobs"]
    assert set(jobs) == {"browser-journeys", "build-release", "attest-release"}

    browser = jobs["browser-journeys"]
    assert browser["permissions"] == {"contents": "read"}
    assert "environment" not in browser
    assert "id-token" not in browser["permissions"]
    assert "attestations" not in browser["permissions"]

    build = jobs["build-release"]
    assert build["needs"] == "browser-journeys"
    assert build["permissions"] == {"contents": "read"}
    assert "environment" not in build
    assert "id-token" not in build["permissions"]
    assert "attestations" not in build["permissions"]

    attestation = jobs["attest-release"]
    assert attestation["needs"] == "build-release"
    assert attestation["environment"] == "production-release"
    assert attestation["permissions"] == {
        "contents": "read",
        "id-token": "write",
        "attestations": "write",
        "artifact-metadata": "write",
    }
    attestation_uses = [step.get("uses", "") for step in attestation["steps"]]
    assert any(value.startswith("actions/download-artifact@") for value in attestation_uses)
    assert sum(value.startswith("actions/attest@") for value in attestation_uses) == 3
    assert all("run" not in step for step in attestation["steps"])


def test_release_postgres_name_satisfies_the_test_ddl_guard():
    workflow_path = ROOT_DIR / ".github" / "workflows" / "release.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    build = workflow["jobs"]["build-release"]
    service_database = build["services"]["postgres"]["env"]["POSTGRES_DB"]
    pytest_step = next(
        step for step in build["steps"] if "python -m pytest -q" in str(step.get("run", ""))
    )

    assert service_database.startswith("litblog_test_")
    assert pytest_step["env"]["TEST_POSTGRES_DATABASE"] == service_database
    assert pytest_step["env"]["TEST_DATABASE_URL"].endswith(f"/{service_database}")
    assert pytest_step["env"]["DATABASE_URL"] == pytest_step["env"]["TEST_DATABASE_URL"]


def test_release_migrations_use_the_minimal_migration_environment():
    workflow_path = ROOT_DIR / ".github" / "workflows" / "release.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    migration_step = next(
        step
        for step in workflow["jobs"]["build-release"]["steps"]
        if step.get("name") == "Verify migrations on disposable PostgreSQL"
    )

    assert migration_step["env"]["APP_ENV"] == "test"
    test_url = make_url(migration_step["env"]["TEST_DATABASE_URL"])
    migrator_url = make_url(
        migration_step["env"]["LITBLOGS_MIGRATION_DATABASE_URL"]
    )
    assert test_url == migrator_url
    assert test_url.database == migrator_url.database
    assert test_url.username == "litblogs_migrator"
    assert migrator_url.username == "litblogs_migrator"
    assert "DATABASE_URL" not in migration_step["env"]


def test_ci_and_release_run_real_pinned_postgres_backup_restore_smoke():
    ci = (ROOT_DIR / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    release = (ROOT_DIR / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )

    for workflow in (ci, release):
        assert "tests/test_postgres_operator_integration.py" in workflow
        assert "job.services.postgres.id" in workflow
        assert "POSTGRES_OPERATOR_CONTAINER_ID" in workflow
        assert "POSTGRES_OPERATOR_BACKUP_DATABASE_URL:" in workflow
        assert "POSTGRES_OPERATOR_RESTORE_DATABASE_URL:" in workflow
        assert "CREATE ROLE litblogs_backup LOGIN INHERIT" in workflow
        assert "GRANT pg_read_all_data TO litblogs_backup" in workflow
        assert "?sslmode=verify-full" in workflow


def test_release_checksum_manifest_uses_downloaded_bundle_basenames():
    release = (ROOT_DIR / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )

    assert '(cd "$RUNNER_TEMP/litblogs-release-output" && sha256sum' in release
    assert "sha256sum \"$artifact\" release/" not in release


def test_release_output_directory_is_fresh_and_outside_the_checkout():
    workflow_path = ROOT_DIR / ".github" / "workflows" / "release.yml"
    release = workflow_path.read_text(encoding="utf-8")
    workflow = yaml.safe_load(release)
    upload_step = next(
        step
        for step in workflow["jobs"]["build-release"]["steps"]
        if str(step.get("uses", "")).startswith("actions/upload-artifact@")
    )
    assert 'test ! -e "$RUNNER_TEMP/litblogs-release-output"' in release
    assert 'mkdir -m 0700 "$RUNNER_TEMP/litblogs-release-output"' in release
    assert "${{ runner.temp }}/litblogs-release-output/" in release
    assert "mkdir -p release" not in release
    assert upload_step["with"]["path"] == "${{ runner.temp }}/litblogs-release-output/"


def test_python_dependencies_use_reviewable_inputs_and_hash_locked_installs():
    runtime_input = BACKEND_DIR / "requirements.in"
    development_input = BACKEND_DIR / "requirements-dev.in"
    lock_tool_input = BACKEND_DIR / "requirements-lock.in"
    runtime_lock = (BACKEND_DIR / "requirements.txt").read_text(encoding="utf-8")
    development_lock = (BACKEND_DIR / "requirements-dev.txt").read_text(
        encoding="utf-8"
    )
    lock_tool_lock = (BACKEND_DIR / "requirements-lock.txt").read_text(
        encoding="utf-8"
    )
    ci = (ROOT_DIR / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    release = (ROOT_DIR / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )
    compiler = ROOT_DIR / "scripts" / "compile-python-locks.py"

    assert runtime_input.is_file()
    assert development_input.is_file()
    assert "pip==26.2.1" in lock_tool_input.read_text(encoding="utf-8")
    assert "pip-tools==7.6.1" in lock_tool_input.read_text(encoding="utf-8")
    for lock in (runtime_lock, development_lock, lock_tool_lock):
        assert "autogenerated by pip-compile" in lock
        assert "--generate-hashes" in lock
        assert "--hash=sha256:" in lock
    assert compiler.is_file()
    compiler_text = compiler.read_text(encoding="utf-8")
    assert '"pip": "26.2.1"' in compiler_text
    assert '"pip-tools": "7.6.1"' in compiler_text
    for workflow in (ci, release):
        assert (
            "pip install --require-hashes --only-binary=:all: "
            "-r requirements-lock.txt" in workflow
        )
        assert "python ../scripts/compile-python-locks.py" in workflow
        assert (
            "git diff --exit-code -- requirements.txt requirements-dev.txt "
            "requirements-lock.txt" in workflow
        )
    assert (
        "pip install --require-hashes --only-binary=:all: -r requirements-dev.txt"
        in ci
    )
    assert (
        "pip install --require-hashes --only-binary=:all: "
        "-r litblogs/requirements-dev.txt" in release
    )


def test_disabled_push_transport_is_not_shipped_in_the_runtime_dependency_graph():
    dependency_files = (
        BACKEND_DIR / "requirements.in",
        BACKEND_DIR / "requirements.txt",
        BACKEND_DIR / "requirements-dev.txt",
    )
    for dependency_file in dependency_files:
        contents = dependency_file.read_text(encoding="utf-8").lower()
        assert "pywebpush" not in contents
        assert "http-ece" not in contents


def test_release_audits_every_installed_build_and_runtime_dependency():
    release = (ROOT_DIR / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )
    assert "python -m pip_audit -r litblogs/requirements-dev.txt" in release
    assert "npm --prefix litblogs audit --audit-level=high" in release
    assert "npm --prefix litblogs audit --omit=dev --audit-level=high" in release


def test_empty_database_upgrades_to_the_complete_model_schema(tmp_path):
    from base import Base

    engine = create_engine(f"sqlite:///{(tmp_path / 'fresh.db').as_posix()}")
    _upgrade(engine, "head")

    migrated_tables = set(inspect(engine).get_table_names())
    assert migrated_tables == set(Base.metadata.tables) | {"alembic_version"}
    assert _current_revision(engine) == _head_revision()
    with engine.connect() as connection:
        command.check(_alembic_config(connection))
    engine.dispose()


def test_baseline_migration_can_round_trip_without_leaving_postgresql_enum_types(
    tmp_path,
):
    engine = create_engine(f"sqlite:///{(tmp_path / 'roundtrip.db').as_posix()}")
    _upgrade(engine, "head")
    _downgrade(engine, "base")
    assert set(inspect(engine).get_table_names()) == {"alembic_version"}
    _upgrade(engine, "head")
    assert _current_revision(engine) == _head_revision()
    engine.dispose()

    baseline = (
        BACKEND_DIR / "migrations" / "versions" / "985a04df032a_baseline_schema.py"
    ).read_text(encoding="utf-8")
    assert "userrole_enum.drop" in baseline

    for workflow_path in (
        ROOT_DIR / ".github" / "workflows" / "ci.yml",
        ROOT_DIR / ".github" / "workflows" / "release.yml",
    ):
        workflow = workflow_path.read_text(encoding="utf-8")
        assert "python -m alembic downgrade base" in workflow
        assert "python -m alembic check" in workflow


def test_existing_schema_can_be_stamped_then_receive_security_migrations(tmp_path):
    from base import Base

    engine = create_engine(f"sqlite:///{(tmp_path / 'adoption.db').as_posix()}")
    baseline_tables = [
        table for name, table in Base.metadata.tables.items() if name != "federated_identities"
    ]
    Base.metadata.create_all(bind=engine, tables=baseline_tables)

    _upgrade(engine, "985a04df032a", stamp=True)
    _upgrade(engine, "head")

    assert "federated_identities" in inspect(engine).get_table_names()
    assert _current_revision(engine) == _head_revision()
    engine.dispose()


def test_readiness_requires_database_at_migration_head(tmp_path):
    import database

    engine = create_engine(f"sqlite:///{(tmp_path / 'readiness.db').as_posix()}")
    with pytest.raises(RuntimeError, match="revision"):
        database.check_database_readiness(engine)

    _upgrade(engine, "head")
    database.check_database_readiness(engine)

    _downgrade(engine, "985a04df032a")
    with pytest.raises(RuntimeError, match="revision"):
        database.check_database_readiness(engine)
    engine.dispose()


def test_private_server_examples_enforce_tls_body_limits_and_no_direct_upload_alias():
    nginx = (ROOT_DIR / "deploy" / "nginx" / "litblogs.conf").read_text(encoding="utf-8")
    unit = (ROOT_DIR / "deploy" / "systemd" / "litblogs-web.service").read_text(
        encoding="utf-8"
    )

    assert "listen 443 ssl http2" in nginx
    assert "client_max_body_size 2m" in nginx
    assert "client_max_body_size 12m" in nginx
    assert "client_max_body_size 27m" in nginx
    assert "client_max_body_size 102m" in nginx
    assert "proxy_pass http://127.0.0.1:" in nginx
    assert "Content-Security-Policy" in nginx
    assert "frame-ancestors 'none'" in nginx
    assert "object-src 'none'" in nginx
    assert "media-src 'self' data: blob:" in nginx
    assert "X-Frame-Options \"DENY\"" in nginx
    assert 'Cross-Origin-Opener-Policy "same-origin-allow-popups"' in nginx
    assert 'Cross-Origin-Opener-Policy "same-origin"' not in nginx
    assert "log_format litblogs_privacy" in nginx
    privacy_log_format = nginx.split("log_format litblogs_privacy", 1)[1].split(";", 1)[0]
    assert '"$request_method $server_protocol"' in privacy_log_format
    assert "$uri" not in privacy_log_format
    assert "$request_uri" not in privacy_log_format
    assert "$args" not in privacy_log_format
    assert "access_log /var/log/nginx/litblogs-access.log litblogs_privacy" in nginx
    assert "location = /index.html {" in nginx
    index_location = nginx.split("location = /index.html {", 1)[1].split("\n    }", 1)[0]
    assert 'Cache-Control "no-cache, no-store, must-revalidate" always' in index_location
    assert "try_files /index.html =404;" in index_location
    assert 'location ~* "^/assets/' in nginx
    hashed_assets = nginx.split('location ~* "^/assets/', 1)[1].split("\n    }", 1)[0]
    assert 'Cache-Control "public, max-age=31536000, immutable" always' in hashed_assets
    fallback = nginx.split("location / {", 1)[1].split("\n    }", 1)[0]
    assert 'Cache-Control "no-cache, no-store, must-revalidate" always' in fallback
    assert "try_files $uri $uri/ /index.html;" in fallback
    assert nginx.count("immutable") == 2
    inherited_security_headers = (
        "Strict-Transport-Security",
        "Content-Security-Policy",
        "X-Frame-Options",
        "X-Content-Type-Options",
        "Referrer-Policy",
        "Permissions-Policy",
        "Cross-Origin-Opener-Policy",
        "Cross-Origin-Resource-Policy",
    )
    for cache_location in (index_location, hashed_assets, fallback):
        for header in inherited_security_headers:
            assert f"add_header {header} " in cache_location
    assert nginx.count("proxy_set_header X-Request-ID $request_id;") == 5
    assert "alias" not in nginx.lower()
    assert "location /uploads" not in nginx.lower()
    assert "NoNewPrivileges=true" in unit
    assert "ProtectSystem=strict" in unit
    assert "PrivateTmp=true" in unit
    assert "CapabilityBoundingSet=" in unit
    assert "AmbientCapabilities=" in unit
    assert "RestrictNamespaces=true" in unit
    assert "ProtectHostname=true" in unit
    assert "RemoveIPC=true" in unit
    assert "EnvironmentFile=" in unit
    assert "ExecStartPre=/opt/litblogs/current/.venv/bin/python -m deployment_check" in unit
    assert "ExecStart=/opt/litblogs/current/.venv/bin/uvicorn" in unit
    assert "/opt/litblogs/venv/" not in unit
    assert "Type=simple" in unit
    assert "Type=notify" not in unit
    assert "--reload" not in unit

    job_unit = (ROOT_DIR / "deploy" / "systemd" / "litblogs-reminders.service").read_text(
        encoding="utf-8"
    )
    timer = (ROOT_DIR / "deploy" / "systemd" / "litblogs-reminders.timer").read_text(
        encoding="utf-8"
    )
    assert "Type=oneshot" in job_unit
    assert "CapabilityBoundingSet=" in job_unit
    assert "AmbientCapabilities=" in job_unit
    assert "RestrictNamespaces=true" in job_unit
    assert "ProtectHostname=true" in job_unit
    assert "ProtectClock=true" in job_unit
    assert "RemoveIPC=true" in job_unit
    assert "RestrictRealtime=true" in job_unit
    assert "SystemCallArchitectures=native" in job_unit
    assert "/opt/litblogs/current/.venv/bin/python -m reminder_job" in job_unit
    assert "/opt/litblogs/venv/" not in job_unit
    assert "Persistent=true" in timer
    assert "RandomizedDelaySec=" in timer


def test_root_readme_routes_operators_to_reviewed_release_runbook():
    readme = (ROOT_DIR / "README.md").read_text(encoding="utf-8")

    assert "deploy/README.md" in readme
    assert "docs/operations/production-runbook.md" in readme
    for unsafe_legacy_instruction in (
        "npm install --force",
        "CREATE USER postgres WITH PASSWORD 'postgres'",
        "PUSH_REMINDER_INTERVAL_SECONDS",
        "systemctl start blog",
        "location ^~ /uploads/",
    ):
        assert unsafe_legacy_instruction not in readme


def _alembic_config(connection=None):
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    if connection is not None:
        config.attributes["connection"] = connection
    return config


def _upgrade(engine, revision, *, stamp=False):
    with engine.begin() as connection:
        config = _alembic_config(connection)
        if stamp:
            command.stamp(config, revision)
        else:
            command.upgrade(config, revision)


def _current_revision(engine):
    with engine.connect() as connection:
        return connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()


def _downgrade(engine, revision):
    with engine.begin() as connection:
        command.downgrade(_alembic_config(connection), revision)


def _head_revision():
    return ScriptDirectory.from_config(_alembic_config()).get_current_head()
