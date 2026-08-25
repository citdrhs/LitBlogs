import hashlib
import io
import json
import logging
import os
import secrets
import stat
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from importlib import import_module
from pathlib import Path
from threading import Barrier, Event
from types import SimpleNamespace

import pytest
from psycopg2 import DatabaseError as PsycopgDatabaseError
from pydantic import ValidationError
from settings_test_support import production_upload_settings
from sqlalchemy import create_engine, event, select, update
from sqlalchemy.exc import SQLAlchemyError

import main
import models
from auth_security import (
    decode_access_token,
    hash_password,
    issue_access_token,
    verify_password,
)
from config import Settings
from database import SessionLocal, engine

identity_controls = import_module("identity_controls")

REGISTRATION_ACCEPTED = {
    "message": "If registration can be completed, sign in with the submitted credentials."
}


def _production_settings_data() -> dict:
    return {
        "app_env": "production",
        "database_url": (
            f"postgresql://litblog_app:{secrets.token_urlsafe(24)}@database.internal/litblog"
            "?sslmode=verify-full&sslrootcert=/etc/litblogs/postgres-root-ca.pem"
        ),
        "secret_key": secrets.token_urlsafe(48),
        "teacher_invite_hmac_key": secrets.token_urlsafe(48),
        "jwt_issuer": "https://api.litblogs.school.edu",
        "jwt_audience": "litblogs.school.edu",
        "access_token_expire_minutes": 30,
        "frontend_url": "https://litblogs.school.edu",
        "cors_allowed_origins": ("https://litblogs.school.edu",),
        "allowed_hosts": ("litblogs.school.edu",),
        "allowed_email_domains": ("school.edu",),
        "google_client_id": "987654321.apps.googleusercontent.com",
        "microsoft_client_id": "2f1c67a1-91e2-46a3-941f-b88e31763e51",
        "microsoft_tenant_id": "871bd3e0-2dc0-4a40-9b07-9d03068c2364",
        "microsoft_allowed_tenant_ids": (
            "871bd3e0-2dc0-4a40-9b07-9d03068c2364",
        ),
        "session_cookie_name": "__Host-litblog-session",
        "csrf_cookie_name": "__Host-litblog-csrf",
        "session_cookie_secure": True,
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


def test_identity_models_store_only_bounded_digests():
    assert set(models.BrowserSession.__table__.columns.keys()) == {
        "id",
        "jti_digest",
        "user_id",
        "created_at",
        "expires_at",
        "revoked_at",
    }
    assert set(models.TeacherInvitation.__table__.columns.keys()) == {
        "id",
        "token_digest",
        "email_digest",
        "created_at",
        "expires_at",
        "consumed_at",
        "revoked_at",
        "created_by",
    }
    assert models.BrowserSession.__table__.c.jti_digest.type.length == 64
    assert models.TeacherInvitation.__table__.c.token_digest.type.length == 64
    assert models.TeacherInvitation.__table__.c.email_digest.type.length == 64
    identity_check_sql = " ".join(
        str(constraint.sqltext)
        for table in (
            models.BrowserSession.__table__,
            models.TeacherInvitation.__table__,
            models.OperatorAuditEvent.__table__,
            models.PasswordReset.__table__,
        )
        for constraint in table.constraints
        if hasattr(constraint, "sqltext")
    )
    for lowercase_hex_column in (
        "jti_digest",
        "token_digest",
        "email_digest",
        "resource_digest",
        "delivery_claim_digest",
        "token",
    ):
        assert f"{lowercase_hex_column} ~ '^[0-9a-f]{{64}}$'" in identity_check_sql
    assert "actor_identifier ~" in identity_check_sql
    assert "created_by ~" in identity_check_sql
    assert set(models.OperatorAuditEvent.__table__.columns.keys()) == {
        "id",
        "actor_identifier",
        "action",
        "outcome",
        "resource_digest",
        "created_at",
    }
    assert models.OperatorAuditEvent.__table__.c.actor_identifier.type.length == 100
    assert models.OperatorAuditEvent.__table__.c.action.type.length == 64
    assert models.OperatorAuditEvent.__table__.c.outcome.type.length == 16
    assert models.OperatorAuditEvent.__table__.c.resource_digest.type.length == 64
    constraint_names = {
        constraint.name
        for constraint in models.OperatorAuditEvent.__table__.constraints
        if constraint.name is not None
    }
    assert "ck_operator_audit_actor_identifier" in constraint_names
    invitation_constraint_names = {
        constraint.name
        for constraint in models.TeacherInvitation.__table__.constraints
        if constraint.name is not None
    }
    assert "ck_teacher_invitation_created_by" in invitation_constraint_names
    assert "uq_teacher_invitation_token_digest" in invitation_constraint_names
    browser_session_constraint_names = {
        constraint.name
        for constraint in models.BrowserSession.__table__.constraints
        if constraint.name is not None
    }
    assert "uq_browser_session_jti_digest" in browser_session_constraint_names

    forbidden_columns = {
        "token",
        "jti",
        "email",
        "raw_token",
        "session_token",
        "invitation_token",
    }
    assert forbidden_columns.isdisjoint(
        models.BrowserSession.__table__.columns.keys()
    )
    assert forbidden_columns.isdisjoint(
        models.TeacherInvitation.__table__.columns.keys()
    )
    assert forbidden_columns.isdisjoint(
        models.OperatorAuditEvent.__table__.columns.keys()
    )


def test_user_model_has_disabled_timestamp_and_session_cascade():
    assert "disabled_at" in models.User.__table__.columns
    user_constraint_names = {
        constraint.name
        for constraint in models.User.__table__.constraints
        if constraint.name is not None
    }
    assert "ck_users_email_ascii" in user_constraint_names
    assert "ck_users_email_canonical" in user_constraint_names
    assert "ck_users_email_no_whitespace" in user_constraint_names
    assert "ck_users_email_no_controls" in user_constraint_names
    user_canonical_constraint = next(
        constraint
        for constraint in models.User.__table__.constraints
        if constraint.name == "ck_users_email_canonical"
    )
    assert "translate(" in str(user_canonical_constraint.sqltext)
    assert 'COLLATE "C"' in str(user_canonical_constraint.sqltext)
    foreign_key = next(iter(models.BrowserSession.__table__.c.user_id.foreign_keys))
    assert foreign_key.target_fullname == "users.id"
    assert foreign_key.ondelete == "CASCADE"
    assert foreign_key.constraint.name == "fk_browser_session_user"
    assert "ix_browser_sessions_user_recency" in {
        index.name for index in models.BrowserSession.__table__.indexes
    }
    email_index = next(
        index
        for index in models.User.__table__.indexes
        if index.name == "uq_users_email_normalized"
    )
    assert email_index.unique is True
    assert tuple(expression.key for expression in email_index.expressions) == ("email",)
    assert email_index.dialect_options["postgresql"]["ops"] == {
        "email": "varchar_pattern_ops"
    }
    teacher_constraint_names = {
        constraint.name
        for constraint in models.Teacher.__table__.constraints
        if constraint.name is not None
    }
    assert models.Teacher.__table__.c.user_id.nullable is False
    assert "uq_teachers_user_id" in teacher_constraint_names
    assert "ck_teachers_email_ascii" in teacher_constraint_names
    assert "ck_teachers_email_canonical" in teacher_constraint_names
    assert "ck_teachers_email_no_whitespace" in teacher_constraint_names
    assert "ck_teachers_email_no_controls" in teacher_constraint_names
    assert models.Teacher.__table__.c.email.type.length == 100
    password_reset_constraint_names = {
        constraint.name
        for constraint in models.PasswordReset.__table__.constraints
        if constraint.name is not None
    }
    assert models.PasswordReset.__table__.c.delivery_claim_digest.type.length == 64
    assert "ck_password_reset_delivery_claim_digest" in (
        password_reset_constraint_names
    )


def test_production_requires_dedicated_invitation_hmac_key():
    settings_data = _production_settings_data()
    settings_data.pop("teacher_invite_hmac_key")

    with pytest.raises(ValidationError, match="TEACHER_INVITE_HMAC_KEY"):
        Settings(**settings_data)


@pytest.mark.parametrize(
    "unsafe_key",
    [
        "too-short",
        "replace-with-teacher-invite-key-000000000000",
        "x" * 64,
    ],
)
def test_production_rejects_weak_invitation_hmac_keys(unsafe_key):
    settings_data = _production_settings_data()
    settings_data["teacher_invite_hmac_key"] = unsafe_key

    with pytest.raises(ValidationError, match="TEACHER_INVITE_HMAC_KEY"):
        Settings(**settings_data)


def test_invitation_hmac_key_must_differ_from_jwt_signing_key():
    settings_data = _production_settings_data()
    settings_data["teacher_invite_hmac_key"] = settings_data["secret_key"]

    with pytest.raises(ValidationError, match="TEACHER_INVITE_HMAC_KEY must differ"):
        Settings(**settings_data)


def test_shared_teacher_access_code_is_not_a_setting():
    assert "teacher_access_code" not in Settings.model_fields


def test_operator_runtime_loads_only_minimal_secrets_from_protected_fd():
    operator_runtime = import_module("operator_runtime")
    assert set(operator_runtime.OperatorSettings.model_fields) == {
        "purpose",
        "database_url",
        "teacher_invite_hmac_key",
        "allowed_email_domains",
    }
    config = {
        "purpose": "invitation",
        "database_url": (
            "postgresql+psycopg2://litblog_invitation_operator:"
            "synthetic-private-password-xxxxxxxxxxxxxxxxxxxxxxxx@"
            "127.0.0.1:5432/litblogs?sslmode=verify-full&"
            "sslrootcert=%2Fetc%2Flitblogs%2Fpostgres-root-ca.pem"
        ),
        "teacher_invite_hmac_key": "synthetic-invite-hmac-key-" + ("x" * 48),
        "allowed_email_domains": ["example.com"],
    }
    read_fd, write_fd = os.pipe()
    try:
        os.write(write_fd, json.dumps(config).encode("utf-8"))
    finally:
        os.close(write_fd)

    try:
        settings = operator_runtime.load_operator_settings(
            expected_purpose="invitation",
            config_fd=read_fd,
        )
    finally:
        os.close(read_fd)

    assert settings.purpose == "invitation"
    assert operator_runtime.expected_database_role("invitation") == (
        "litblog_invitation_operator"
    )
    assert settings.allowed_email_domains == ("example.com",)
    rendered = repr(settings)
    assert "synthetic-private-password" not in rendered
    assert "synthetic-invite-hmac-key" not in rendered
    for forbidden_app_secret in (
        "secret_key",
        "google_client_id",
        "microsoft_client_id",
        "email_password",
        "vapid_private_key",
    ):
        assert forbidden_app_secret not in operator_runtime.OperatorSettings.model_fields


@pytest.mark.parametrize(
    "descriptor_stat",
    [
        SimpleNamespace(st_mode=stat.S_IFIFO | 0o066, st_uid=0),
        SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_uid=99_999),
        SimpleNamespace(st_mode=stat.S_IFSOCK | 0o600, st_uid=0),
    ],
)
def test_operator_runtime_rejects_untrusted_config_descriptor_custody(
    monkeypatch,
    descriptor_stat,
):
    operator_runtime = import_module("operator_runtime")
    read_fd, write_fd = os.pipe()
    os.close(write_fd)
    monkeypatch.setattr(operator_runtime.os, "fstat", lambda descriptor: descriptor_stat)
    monkeypatch.setattr(operator_runtime.os, "geteuid", lambda: 1_000, raising=False)
    try:
        with pytest.raises(RuntimeError, match="descriptor"):
            operator_runtime.load_operator_settings(
                expected_purpose="account",
                config_fd=read_fd,
            )
    finally:
        os.close(read_fd)


def test_operator_runtime_checks_root_owned_ca_ancestor_chain(monkeypatch):
    operator_runtime = import_module("operator_runtime")
    ca_path = operator_runtime.OPERATOR_ROOT_CERTIFICATE_PATH
    secure_stats = {
        ca_path: SimpleNamespace(st_mode=stat.S_IFREG | 0o644, st_uid=0),
        "/etc/litblogs": SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_uid=0),
        "/etc": SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_uid=0),
        "/": SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_uid=0),
    }
    inspected_paths = []
    monkeypatch.setattr(operator_runtime, "OPERATOR_RUNTIME_PLATFORM", "posix")
    monkeypatch.setattr(operator_runtime.os.path, "realpath", lambda path: path)

    def secure_lstat(path):
        inspected_paths.append(path)
        return secure_stats[path]

    monkeypatch.setattr(operator_runtime.os, "lstat", secure_lstat)
    operator_runtime._validate_root_certificate_custody()
    assert inspected_paths == [ca_path, "/etc/litblogs", "/etc", "/"]

    secure_stats["/etc/litblogs"] = SimpleNamespace(
        st_mode=stat.S_IFDIR | 0o775,
        st_uid=0,
    )
    with pytest.raises(RuntimeError, match="custody"):
        operator_runtime._validate_root_certificate_custody()


@pytest.mark.parametrize(
    "database_url",
    [
        (
            "postgresql://litblog_invitation_operator:"
            "synthetic-private-password-xxxxxxxxxxxxxxxxxxxxxxxx@"
            "127.0.0.1:5432/litblogs"
        ),
        (
            "postgresql+psycopg2://litblog_invitation_operator:weak@"
            "127.0.0.1:5432/litblogs?sslmode=verify-full&"
            "sslrootcert=%2Fetc%2Flitblogs%2Fpostgres-root-ca.pem"
        ),
        (
            "postgresql+psycopg2://litblog_invitation_operator:"
            "synthetic-private-password-xxxxxxxxxxxxxxxxxxxxxxxx@"
            "127.0.0.1:5432/litblogs?sslmode=require&"
            "sslrootcert=%2Fetc%2Flitblogs%2Fpostgres-root-ca.pem"
        ),
        (
            "postgresql+psycopg2://litblog_invitation_operator:"
            "synthetic-private-password-xxxxxxxxxxxxxxxxxxxxxxxx@"
            "127.0.0.1:5432/litblogs?sslmode=verify-full&"
            "sslrootcert=relative-ca.pem"
        ),
        (
            "postgresql+psycopg2://litblog_invitation_operator:"
            "synthetic-private-password-xxxxxxxxxxxxxxxxxxxxxxxx@"
            "127.0.0.1:5432/litblogs?sslmode=verify-full&"
            "sslrootcert=%2Fetc%2Flitblogs%2Fpostgres-root-ca.pem&"
            "hostaddr=127.0.0.1"
        ),
        (
            "postgresql+psycopg2://postgres:"
            "synthetic-private-password-xxxxxxxxxxxxxxxxxxxxxxxx@"
            "127.0.0.1:5432/litblogs?sslmode=verify-full&"
            "sslrootcert=%2Fetc%2Flitblogs%2Fpostgres-root-ca.pem"
        ),
        (
            "postgresql+psycopg2://litblog_invitation_operator:"
            "synthetic-private-password-xxxxxxxxxxxxxxxxxxxxxxxx@"
            "127.0.0.1:5432/litblogs?sslmode=verify-full&"
            "sslrootcert=%2Ftmp%2Foperator-supplied-ca.pem"
        ),
        (
            "postgresql+psycopg2://litblog_invitation_operator:"
            "synthetic-private-password-xxxxxxxxxxxxxxxxxxxxxxxx@"
            "database.internal:5432/litblogs?sslmode=verify-full&"
            "sslrootcert=%2Fetc%2Flitblogs%2Fpostgres-root-ca.pem"
        ),
        (
            "postgresql+psycopg2://litblog_invitation_operator:"
            "synthetic-private-password-xxxxxxxxxxxxxxxxxxxxxxxx@"
            "localhost:5432/litblogs?sslmode=verify-full&"
            "sslrootcert=%2Fetc%2Flitblogs%2Fpostgres-root-ca.pem"
        ),
        (
            "postgresql+psycopg2://litblog_invitation_operator:"
            "synthetic-private-password-xxxxxxxxxxxxxxxxxxxxxxxx@"
            "127.0.0.1:5432/litblogs?sslmode=verify-full&"
            "sslrootcert=%2Fetc%2Flitblogs%2F..%2Ftmp%2Fca.pem"
        ),
        (
            "postgresql+psycopg2://litblog_invitation_operator:"
            "synthetic-private-password-xxxxxxxxxxxxxxxxxxxxxxxx@"
            "127.0.0.1:5433/litblogs?sslmode=verify-full&"
            "sslrootcert=%2Fetc%2Flitblogs%2Fpostgres-root-ca.pem"
        ),
        (
            "postgresql+psycopg2://litblog_invitation_operator:"
            "synthetic-private-password-xxxxxxxxxxxxxxxxxxxxxxxx@"
            "127.0.0.1:5432/another_database?sslmode=verify-full&"
            "sslrootcert=%2Fetc%2Flitblogs%2Fpostgres-root-ca.pem"
        ),
    ],
)
def test_operator_runtime_rejects_unverified_or_ambiguous_postgres_urls(
    database_url,
):
    operator_runtime = import_module("operator_runtime")
    with pytest.raises(ValidationError):
        operator_runtime.OperatorSettings(
            purpose="invitation",
            database_url=database_url,
            teacher_invite_hmac_key=(
                "synthetic-invite-hmac-key-" + ("x" * 48)
            ),
            allowed_email_domains=("example.com",),
        )


def test_operator_runtime_checks_database_current_user_before_returning_session():
    operator_runtime = import_module("operator_runtime")

    class FakeRoleResult:
        def __init__(self, record):
            self.record = record

        def one(self):
            return self.record

    class FakeSession:
        def __init__(self, record, privilege_record=None):
            self.record = record
            self.privilege_record = privilege_record
            self.closed = False

        def execute(self, statement):
            rendered = " ".join(str(statement).split()).casefold()
            if "select session_user, current_user" in rendered:
                assert "pg_catalog.pg_auth_members" in rendered
                return FakeRoleResult(self.record)
            assert "has_table_privilege" in rendered
            assert "has_any_column_privilege" in rendered
            assert "has_function_privilege" in rendered
            assert (
                "has_schema_privilege( 'litblog_identity_owner', 'public', 'create'"
                in rendered
            )
            assert "operator_function_acl_is_exact" in rendered
            return FakeRoleResult(self.privilege_record)

        def close(self):
            self.closed = True

    matching = FakeSession(
        (
            "litblog_account_operator",
            "litblog_account_operator",
            False,
            False,
            False,
            False,
            True,
            False,
            False,
            False,
        ),
        (
            True,
            False,
            False,
            False,
            True,
            False,
            False,
            3,
            1,
            False,
            False,
            True,
            True,
            False,
            True,
        ),
    )
    assert operator_runtime.require_expected_database_role(
        matching,
        expected_purpose="account",
    ) is matching

    mismatched = FakeSession(
        (
            "postgres",
            "postgres",
            True,
            True,
            True,
            True,
            True,
            True,
            True,
            True,
        )
    )
    with pytest.raises(RuntimeError, match="privilege boundary"):
        operator_runtime.require_expected_database_role(
            mismatched,
            expected_purpose="account",
        )
    assert mismatched.closed is True


@pytest.mark.parametrize(
    "unsafe_privilege_record",
    [
        (True, True, False, False, True, False, False, 3, 1, False, False, True, True, False, True),
        (True, False, True, False, True, False, False, 3, 1, False, False, True, True, False, True),
        (True, False, False, True, True, False, False, 3, 1, False, False, True, True, False, True),
        (True, False, False, False, False, False, False, 3, 0, False, False, True, True, False, True),
        (True, False, False, False, True, True, False, 3, 2, False, False, True, True, False, True),
        (True, False, False, False, True, False, False, 2, 1, False, False, True, True, False, True),
        (True, False, False, False, True, False, False, 3, 1, True, False, True, True, False, True),
        (False, False, False, False, True, False, False, 3, 1, False, False, True, True, False, True),
        (True, False, False, False, True, False, False, 3, 1, False, True, True, True, False, True),
        (True, False, False, False, True, False, False, 3, 1, False, False, False, True, False, True),
        (True, False, False, False, True, False, False, 3, 1, False, False, True, False, False, True),
        (True, False, False, False, True, False, False, 3, 2, False, False, True, True, False, True),
        (True, False, False, False, True, False, False, 3, 1, False, False, True, True, True, True),
        (True, False, False, False, True, False, False, 3, 1, False, False, True, True, False, False),
    ],
)
def test_operator_runtime_rejects_direct_grants_or_wrong_function_boundary(
    unsafe_privilege_record,
):
    operator_runtime = import_module("operator_runtime")

    class FakeResult:
        def __init__(self, record):
            self.record = record

        def one(self):
            return self.record

    class FakeSession:
        closed = False

        def execute(self, statement):
            rendered = " ".join(str(statement).split()).casefold()
            if "select session_user, current_user" in rendered:
                return FakeResult(
                    (
                        "litblog_account_operator",
                        "litblog_account_operator",
                        False,
                        False,
                        False,
                        False,
                        True,
                        False,
                        False,
                        False,
                    )
                )
            return FakeResult(unsafe_privilege_record)

        def close(self):
            self.closed = True

    session = FakeSession()
    with pytest.raises(RuntimeError, match="privilege boundary"):
        operator_runtime.require_expected_database_role(
            session,
            expected_purpose="account",
        )
    assert session.closed is True


def test_operator_runtime_rejects_set_role_from_broader_authenticated_session():
    operator_runtime = import_module("operator_runtime")

    class FakeResult:
        def one(self):
            return (
                "litblog_web",
                "litblog_account_operator",
                False,
                False,
                False,
                False,
                True,
                False,
                False,
                False,
            )

    class FakeSession:
        closed = False

        def execute(self, statement):
            del statement
            return FakeResult()

        def close(self):
            self.closed = True

    session = FakeSession()
    with pytest.raises(RuntimeError, match="privilege boundary"):
        operator_runtime.require_expected_database_role(
            session,
            expected_purpose="account",
        )
    assert session.closed is True


@pytest.mark.parametrize(
    ("security_flag_index", "security_flag_value"),
    [
        (2, True),  # rolsuper
        (3, True),  # rolinherit
        (4, True),  # rolcreaterole
        (5, True),  # rolcreatedb
        (6, False),  # rolcanlogin
        (7, True),  # rolreplication
        (8, True),  # rolbypassrls
        (9, True),  # membership in another role
    ],
)
def test_operator_runtime_rejects_privileged_or_inherited_database_roles(
    security_flag_index,
    security_flag_value,
):
    operator_runtime = import_module("operator_runtime")

    class FakeResult:
        def one(self):
            record = [
                "litblog_invitation_operator",
                "litblog_invitation_operator",
                False,
                False,
                False,
                False,
                True,
                False,
                False,
                False,
            ]
            record[security_flag_index] = security_flag_value
            return tuple(record)

    class FakeSession:
        closed = False

        def execute(self, statement):
            del statement
            return FakeResult()

        def close(self):
            self.closed = True

    session = FakeSession()
    with pytest.raises(RuntimeError, match="privilege boundary"):
        operator_runtime.require_expected_database_role(
            session,
            expected_purpose="invitation",
        )
    assert session.closed is True


def _create_user(*, suffix: str, role: models.UserRole) -> int:
    with SessionLocal() as db:
        user = models.User(
            username=f"identity-{role.value.casefold()}-{suffix}",
            email=f"identity-{role.value.casefold()}-{suffix}@example.com",
            password=hash_password("synthetic-identity-password"),
            first_name="Identity",
            last_name=role.value.title(),
            role=role,
            is_admin=role == models.UserRole.ADMIN,
        )
        db.add(user)
        db.commit()
        return user.id


def _create_student(*, suffix: str) -> int:
    return _create_user(suffix=suffix, role=models.UserRole.STUDENT)


def _create_password_reset(
    *,
    user_id: int,
    raw_token: str,
    delivery_status: str = "DELIVERED",
    delivery_attempted_at: datetime | None = None,
    delivery_claim_nonce: str | None = None,
) -> int:
    now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
    with SessionLocal() as db:
        reset = models.PasswordReset(
            user_id=user_id,
            token=(
                hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
                if delivery_status == "DELIVERED"
                else None
            ),
            created_at=now,
            expires_at=(
                now + timedelta(hours=1)
                if delivery_status == "DELIVERED"
                else None
            ),
            used=False,
            delivery_status=delivery_status,
            delivery_attempted_at=delivery_attempted_at,
            delivery_claim_digest=(
                main._password_reset_claim_digest(delivery_claim_nonce)
                if delivery_claim_nonce is not None
                else None
            ),
        )
        db.add(reset)
        db.commit()
        return reset.id


def _registration_payload(
    suffix: str,
    *,
    role: str = "STUDENT",
    email: str | None = None,
    username: str | None = None,
    teacher_invitation_token: str | None = None,
) -> dict:
    payload = {
        "username": username or f"registration-{suffix}",
        "email": email or f"registration-{suffix}@example.com",
        "password": "synthetic-registration-password",
        "first_name": "Registration",
        "last_name": "User",
        "role": role,
    }
    if teacher_invitation_token is not None:
        payload["teacher_invitation_token"] = teacher_invitation_token
    return payload


def _private_email_input(email: str) -> io.StringIO:
    return io.StringIO(f"{email}\n")


@pytest.mark.parametrize(
    ("dialect_name", "qualified_table"),
    [
        ("postgresql", "public.operator_audit_events"),
        ("sqlite", "operator_audit_events"),
    ],
)
def test_operator_audit_insert_uses_only_append_only_runtime_columns(
    dialect_name,
    qualified_table,
):
    class RecordingSession:
        def __init__(self):
            self.statement = None
            self.parameters = None

        def get_bind(self):
            return SimpleNamespace(dialect=SimpleNamespace(name=dialect_name))

        def execute(self, statement, parameters):
            self.statement = statement
            self.parameters = parameters

        def add(self, _record):
            pytest.fail("operator audit writes must not use ORM implicit RETURNING")

        def flush(self):
            pytest.fail("operator audit writes must execute directly without a flush")

    db = RecordingSession()
    identity_controls.record_operator_audit_event(
        db,
        actor_identifier="admin-user:7",
        action="ACCOUNT_DISABLED",
        outcome="SUCCEEDED",
        resource_email="audit-target@example.com",
        settings=identity_controls.get_settings(),
    )

    normalized = " ".join(str(db.statement).casefold().split())
    assert normalized == (
        f"insert into {qualified_table} "
        "(actor_identifier, action, outcome, resource_digest) "
        "values (:actor_identifier, :action, :outcome, :resource_digest)"
    )
    assert " returning " not in f" {normalized} "
    assert "created_at" not in normalized
    assert set(db.parameters) == {
        "actor_identifier",
        "action",
        "outcome",
        "resource_digest",
    }


def test_operator_audit_insert_rejects_an_unsupported_database_dialect():
    class UnsupportedSession:
        def get_bind(self):
            return SimpleNamespace(dialect=SimpleNamespace(name="mysql"))

        def execute(self, _statement, _parameters):
            pytest.fail("unsupported database dialect must fail before audit insertion")

    with pytest.raises(RuntimeError, match="unsupported database dialect"):
        identity_controls.record_operator_audit_event(
            UnsupportedSession(),
            actor_identifier="admin-user:7",
            action="ACCOUNT_DISABLED",
            outcome="SUCCEEDED",
            resource_email="audit-target@example.com",
            settings=identity_controls.get_settings(),
        )


def _sqlite_account_status_executor(
    db,
    *,
    email: str,
    disabled: bool,
    actor_identifier: str,
    resource_digest: str,
    settings,
) -> str:
    """Exercise CLI transaction behavior without weakening the PostgreSQL role."""

    del resource_digest
    users = db.execute(
        select(
            models.User.id,
            models.User.email,
            models.User.disabled_at,
        )
        .where(models.User.email == email)
        .with_for_update(of=models.User)
        .limit(2)
    ).all()
    action = "ACCOUNT_DISABLED" if disabled else "ACCOUNT_ENABLED"
    if len(users) != 1:
        identity_controls.record_operator_audit_event(
            db,
            actor_identifier=actor_identifier,
            action=action,
            outcome="NOT_FOUND",
            resource_email=email,
            settings=settings,
        )
        return "NOT_FOUND"

    user = users[0]
    if disabled:
        disabled_at = datetime.now(UTC)
        identity_controls.revoke_all_sessions(db, user_id=user.id)
        identity_controls.invalidate_password_reset_requests(db, user_id=user.id)
    else:
        disabled_at = None
    result = db.execute(
        update(models.User)
        .where(models.User.id == user.id)
        .values(disabled_at=disabled_at)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise SQLAlchemyError("synthetic account status conflict")
    identity_controls.record_operator_audit_event(
        db,
        actor_identifier=actor_identifier,
        action=action,
        outcome="SUCCEEDED",
        resource_email=user.email,
        settings=settings,
    )
    return "SUCCEEDED"


def _sqlite_invitation_command_executor(
    db,
    *,
    command: str,
    token_digest: str | None,
    email_digest: str,
    expires_at,
    actor_identifier: str,
    resource_digest: str,
    email: str,
    settings,
) -> str:
    """Exercise invitation CLI behavior without granting its role table DML."""

    del resource_digest
    if command == "create":
        now = identity_controls.utc_now()
        db.execute(
            update(models.TeacherInvitation)
            .where(
                models.TeacherInvitation.email_digest == email_digest,
                models.TeacherInvitation.consumed_at.is_(None),
                models.TeacherInvitation.revoked_at.is_(None),
                models.TeacherInvitation.expires_at <= now,
            )
            .values(revoked_at=now)
            .execution_options(synchronize_session=False)
        )
        active_invitation = db.execute(
            select(models.TeacherInvitation.id).where(
                models.TeacherInvitation.email_digest == email_digest,
                models.TeacherInvitation.consumed_at.is_(None),
                models.TeacherInvitation.revoked_at.is_(None),
            )
        ).first()
        if active_invitation is not None:
            identity_controls.record_operator_audit_event(
                db,
                actor_identifier=actor_identifier,
                action="TEACHER_INVITATION_CREATED",
                outcome="CONFLICT",
                resource_email=email,
                settings=settings,
            )
            return "CONFLICT"
        db.add(
            models.TeacherInvitation(
                token_digest=token_digest,
                email_digest=email_digest,
                expires_at=expires_at,
                created_by=actor_identifier,
            )
        )
        db.flush()
        identity_controls.record_operator_audit_event(
            db,
            actor_identifier=actor_identifier,
            action="TEACHER_INVITATION_CREATED",
            outcome="SUCCEEDED",
            resource_email=email,
            settings=settings,
        )
        return "SUCCEEDED"
    if command == "revoke":
        revoked = identity_controls.revoke_teacher_invitation(
            db,
            email=email,
            settings=settings,
        )
        identity_controls.record_operator_audit_event(
            db,
            actor_identifier=actor_identifier,
            action="TEACHER_INVITATION_REVOKED",
            outcome="SUCCEEDED" if revoked else "NOT_FOUND",
            resource_email=email,
            settings=settings,
        )
        return "SUCCEEDED" if revoked else "NOT_FOUND"
    raise ValueError("synthetic invitation command is invalid")


def test_account_operator_invokes_only_mediated_database_command():
    account_cli = import_module("manage_accounts")

    class FakeResult:
        def scalar_one(self):
            return "SUCCEEDED"

    class FakeSession:
        def __init__(self):
            self.statement = None
            self.parameters = None

        def execute(self, statement, parameters):
            self.statement = " ".join(str(statement).split()).casefold()
            self.parameters = parameters
            return FakeResult()

    db = FakeSession()
    outcome = account_cli.execute_account_status_command(
        db,
        email="student@example.com",
        disabled=True,
        actor_identifier="reviewed-security-operator",
        resource_digest="a" * 64,
        settings=None,
    )

    assert outcome == "SUCCEEDED"
    assert "public.operator_set_account_status" in db.statement
    assert db.parameters == {
        "email": "student@example.com",
        "disabled": True,
        "actor_identifier": "reviewed-security-operator",
        "resource_digest": "a" * 64,
    }


@pytest.mark.parametrize(
    ("command", "expected_function"),
    [
        ("create", "public.operator_create_teacher_invitation"),
        ("revoke", "public.operator_revoke_teacher_invitation"),
    ],
)
def test_invitation_operator_invokes_only_mediated_database_commands(
    command,
    expected_function,
):
    invitation_cli = import_module("manage_teacher_invitations")

    class FakeResult:
        def scalar_one(self):
            return "SUCCEEDED"

    class FakeSession:
        def __init__(self):
            self.statement = None

        def execute(self, statement, parameters):
            self.statement = " ".join(str(statement).split()).casefold()
            assert parameters["email_digest"] == "b" * 64
            assert parameters["actor_identifier"] == "reviewed-security-operator"
            assert parameters["resource_digest"] == "c" * 64
            return FakeResult()

    db = FakeSession()
    outcome = invitation_cli.execute_invitation_command(
        db,
        command=command,
        token_digest="a" * 64 if command == "create" else None,
        email_digest="b" * 64,
        expires_at=(
            datetime.now(UTC) + timedelta(hours=1)
            if command == "create"
            else None
        ),
        actor_identifier="reviewed-security-operator",
        resource_digest="c" * 64,
        email="teacher@example.com",
        settings=None,
    )

    assert outcome == "SUCCEEDED"
    assert expected_function in db.statement
    assert "cast(:email_digest as varchar(64))" in db.statement
    assert "cast(:actor_identifier as varchar(100))" in db.statement
    assert "cast(:resource_digest as varchar(64))" in db.statement
    if command == "create":
        assert "cast(:token_digest as varchar(64))" in db.statement
        assert "cast(:expires_at as timestamptz)" in db.statement


def _set_cookie_session(
    client,
    token: str,
    *,
    csrf_token: str = "synthetic-identity-csrf-token",
) -> str:
    client.cookies.set(main._session_cookie_name(), token)
    client.cookies.set(main._csrf_cookie_name(), csrf_token)
    return csrf_token


def _login(client, *, role: models.UserRole, suffix: str) -> tuple[str, str]:
    response = client.post(
        "/api/auth/login",
        json={
            "email": f"identity-{role.value.casefold()}-{suffix}@example.com",
            "password": "synthetic-identity-password",
        },
    )
    assert response.status_code == 200
    token = client.cookies.get(main._session_cookie_name())
    csrf = client.cookies.get(main._csrf_cookie_name())
    assert isinstance(token, str)
    assert isinstance(csrf, str)
    return token, csrf


def test_issued_browser_session_persists_only_jti_digest(client):
    del client
    user_id = _create_student(suffix="issued")

    with SessionLocal() as db:
        issued = identity_controls.issue_browser_session(
            db,
            user_id=user_id,
            settings=identity_controls.get_settings(),
        )
        db.commit()

        payload = decode_access_token(
            issued.token,
            settings=identity_controls.get_settings(),
        )
        row = db.query(models.BrowserSession).one()
        expected_digest = hashlib.sha256(payload["jti"].encode("utf-8")).hexdigest()

        assert row.jti_digest == expected_digest
        assert row.user_id == user_id
        assert row.revoked_at is None
        assert issued.expires_at == row.expires_at.replace(tzinfo=UTC)
        persisted_text = " ".join(str(value) for value in row.__dict__.values())
        assert issued.token not in persisted_text
        assert payload["jti"] not in persisted_text


def test_session_issuance_rechecks_disabled_state_after_authentication(client):
    del client
    user_id = _create_student(suffix="disabled-before-issue")
    with SessionLocal() as db:
        user = db.get(models.User, user_id)
        user.disabled_at = datetime.now(UTC)
        db.commit()

    with SessionLocal() as db, pytest.raises(
        identity_controls.SessionIssuanceDenied
    ):
        identity_controls.issue_browser_session(
            db,
            user_id=user_id,
            settings=identity_controls.get_settings(),
        )

    with SessionLocal() as db:
        assert db.query(models.BrowserSession).count() == 0


def test_password_session_issuance_rechecks_current_password_hash(client):
    del client
    user_id = _create_student(suffix="password-changed-before-issue")
    with SessionLocal() as db:
        stale_password_hash = db.get(models.User, user_id).password
        db.query(models.User).filter(models.User.id == user_id).update(
            {"password": hash_password("synthetic-replaced-password")},
            synchronize_session=False,
        )
        db.commit()

    with SessionLocal() as db, pytest.raises(
        identity_controls.SessionIssuanceDenied
    ):
        identity_controls.issue_browser_session(
            db,
            user_id=user_id,
            settings=identity_controls.get_settings(),
            expected_password_hash=stale_password_hash,
        )

    with SessionLocal() as db:
        assert db.query(models.BrowserSession).count() == 0


def test_active_session_lookup_is_user_expiry_and_revocation_scoped(client):
    del client
    first_user_id = _create_student(suffix="scope-one")
    second_user_id = _create_student(suffix="scope-two")
    now = datetime.now(UTC).replace(microsecond=0)

    with SessionLocal() as db:
        issued = identity_controls.issue_browser_session(
            db,
            user_id=first_user_id,
            settings=identity_controls.get_settings(),
        )
        db.commit()
        jti = decode_access_token(
            issued.token,
            settings=identity_controls.get_settings(),
        )["jti"]

        active = identity_controls.find_active_browser_session(
            db,
            user_id=first_user_id,
            jti=jti,
            now=now,
        )
        wrong_user = identity_controls.find_active_browser_session(
            db,
            user_id=second_user_id,
            jti=jti,
            now=now,
        )

        assert active is not None
        assert wrong_user is None
        assert identity_controls.revoke_session(
            db,
            session_id=active.id,
            now=now,
        ) is True
        assert identity_controls.revoke_session(
            db,
            session_id=active.id,
            now=now,
        ) is False
        db.commit()

        assert identity_controls.find_active_browser_session(
            db,
            user_id=first_user_id,
            jti=jti,
            now=now,
        ) is None


def test_expired_session_cleanup_is_bounded_and_preserves_other_rows(client):
    del client
    user_id = _create_student(suffix="cleanup")
    now = datetime.now(UTC).replace(microsecond=0)

    def session_row(label: str, expires_at: datetime, revoked_at=None):
        return models.BrowserSession(
            jti_digest=hashlib.sha256(label.encode("utf-8")).hexdigest(),
            user_id=user_id,
            expires_at=expires_at,
            revoked_at=revoked_at,
        )

    with SessionLocal() as db:
        db.add_all(
            (
                session_row("expired-one", now - timedelta(minutes=3)),
                session_row("expired-two", now - timedelta(minutes=2)),
                session_row(
                    "revoked-future",
                    now + timedelta(minutes=5),
                    revoked_at=now,
                ),
                session_row("active-future", now + timedelta(minutes=5)),
            )
        )
        db.commit()

        assert identity_controls.delete_expired_sessions(
            db,
            now=now,
            limit=1,
        ) == 1
        db.commit()
        assert db.query(models.BrowserSession).count() == 3

        assert identity_controls.delete_expired_sessions(
            db,
            now=now,
            limit=500,
        ) == 1
        db.commit()
        remaining = {
            row.jti_digest for row in db.query(models.BrowserSession).all()
        }
        assert remaining == {
            hashlib.sha256(b"revoked-future").hexdigest(),
            hashlib.sha256(b"active-future").hexdigest(),
        }


def test_revoke_all_sessions_is_idempotent(client):
    del client
    user_id = _create_student(suffix="revoke-all")
    with SessionLocal() as db:
        identity_controls.issue_browser_session(
            db,
            user_id=user_id,
            settings=identity_controls.get_settings(),
        )
        identity_controls.issue_browser_session(
            db,
            user_id=user_id,
            settings=identity_controls.get_settings(),
        )
        db.commit()

        assert identity_controls.revoke_all_sessions(db, user_id=user_id) == 2
        assert identity_controls.revoke_all_sessions(db, user_id=user_id) == 0
        db.commit()
        assert all(
            row.revoked_at is not None
            for row in db.query(models.BrowserSession).all()
        )


def test_session_issuance_caps_per_user_rows_and_invalidates_oldest(client):
    del client
    user_id = _create_student(suffix="session-cap")
    issued_tokens = []
    with SessionLocal() as db:
        for _ in range(identity_controls.MAX_BROWSER_SESSIONS_PER_USER + 3):
            issued_tokens.append(
                identity_controls.issue_browser_session(
                    db,
                    user_id=user_id,
                    settings=identity_controls.get_settings(),
                ).token
            )
            db.commit()

        rows = (
            db.query(models.BrowserSession)
            .filter(models.BrowserSession.user_id == user_id)
            .order_by(models.BrowserSession.id)
            .all()
        )
        assert len(rows) == identity_controls.MAX_BROWSER_SESSIONS_PER_USER
        retained_digests = {row.jti_digest for row in rows}

    token_digests = [
        hashlib.sha256(
            decode_access_token(token, settings=identity_controls.get_settings())[
                "jti"
            ].encode("utf-8")
        ).hexdigest()
        for token in issued_tokens
    ]
    assert retained_digests == set(
        token_digests[-identity_controls.MAX_BROWSER_SESSIONS_PER_USER :]
    )
    assert retained_digests.isdisjoint(token_digests[:3])


def test_teacher_invitation_is_email_bound_digest_only_and_one_time(client, caplog):
    del client
    email = " Invited.Teacher@Example.Test "
    now = datetime.now(UTC).replace(microsecond=0)

    with caplog.at_level(logging.DEBUG), SessionLocal() as db:
        token = identity_controls.create_teacher_invitation(
            db,
            email=email,
            created_by="security-operator",
            expires_at=now + timedelta(hours=2),
            settings=identity_controls.get_settings(),
            now=now,
        )
        db.commit()
        row = db.query(models.TeacherInvitation).one()
        persisted_text = " ".join(str(value) for value in row.__dict__.values())

        assert row.token_digest == hashlib.sha256(token.encode("utf-8")).hexdigest()
        assert len(row.email_digest) == 64
        assert token not in persisted_text
        assert email.strip().casefold() not in persisted_text.casefold()
        assert token not in caplog.text
        assert email.strip().casefold() not in caplog.text.casefold()

        assert identity_controls.consume_teacher_invitation(
            db,
            token=token,
            email="invited.teacher@EXAMPLE.TEST",
            settings=identity_controls.get_settings(),
            now=now + timedelta(minutes=1),
        ) is True
        db.commit()
        assert identity_controls.consume_teacher_invitation(
            db,
            token=token,
            email="invited.teacher@example.test",
            settings=identity_controls.get_settings(),
            now=now + timedelta(minutes=1),
        ) is False


def test_teacher_invitation_rejects_mismatch_expiry_and_revocation(client):
    del client
    now = datetime.now(UTC).replace(microsecond=0)
    settings = identity_controls.get_settings()

    with SessionLocal() as db:
        token = identity_controls.create_teacher_invitation(
            db,
            email="teacher-one@example.test",
            created_by="security-operator",
            expires_at=now + timedelta(minutes=5),
            settings=settings,
            now=now,
        )
        db.commit()

        assert identity_controls.consume_teacher_invitation(
            db,
            token=token,
            email="other-teacher@example.test",
            settings=settings,
            now=now,
        ) is False
        assert identity_controls.consume_teacher_invitation(
            db,
            token=token,
            email="teacher-one@example.test",
            settings=settings,
            now=now + timedelta(minutes=6),
        ) is False
        assert identity_controls.revoke_teacher_invitation(
            db,
            email="teacher-one@example.test",
            settings=settings,
            now=now,
        ) is True
        assert identity_controls.revoke_teacher_invitation(
            db,
            email="teacher-one@example.test",
            settings=settings,
            now=now,
        ) is False
        db.commit()

        assert identity_controls.consume_teacher_invitation(
            db,
            token=token,
            email="teacher-one@example.test",
            settings=settings,
            now=now,
        ) is False


def test_expired_invitation_is_retired_before_reissue(client):
    del client
    now = datetime.now(UTC).replace(microsecond=0)
    settings = identity_controls.get_settings()

    with SessionLocal() as db:
        first_token = identity_controls.create_teacher_invitation(
            db,
            email="reissue@example.test",
            created_by="security-operator",
            expires_at=now + timedelta(minutes=1),
            settings=settings,
            now=now,
        )
        db.commit()
        second_token = identity_controls.create_teacher_invitation(
            db,
            email="REISSUE@example.test",
            created_by="security-operator",
            expires_at=now + timedelta(hours=2),
            settings=settings,
            now=now + timedelta(minutes=2),
        )
        db.commit()

        assert first_token != second_token
        invitations = db.query(models.TeacherInvitation).order_by(
            models.TeacherInvitation.id
        ).all()
        assert len(invitations) == 2
        assert invitations[0].revoked_at is not None
        assert invitations[1].revoked_at is None


def test_teacher_invitation_atomic_consume_allows_one_race_winner(client):
    del client
    now = datetime.now(UTC).replace(microsecond=0)
    settings = identity_controls.get_settings()
    with SessionLocal() as db:
        token = identity_controls.create_teacher_invitation(
            db,
            email="race-teacher@example.test",
            created_by="security-operator",
            expires_at=now + timedelta(hours=1),
            settings=settings,
            now=now,
        )
        db.commit()

    barrier = Barrier(2)

    def consume_once() -> bool:
        with SessionLocal() as worker_db:
            barrier.wait(timeout=5)
            consumed = identity_controls.consume_teacher_invitation(
                worker_db,
                token=token,
                email="race-teacher@example.test",
                settings=settings,
                now=now + timedelta(minutes=1),
            )
            worker_db.commit()
            return consumed

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: consume_once(), range(2)))

    assert sorted(results) == [False, True]


def test_password_registration_success_and_duplicates_share_generic_202(client):
    first_payload = _registration_payload("generic")
    successful = client.post("/api/auth/register", json=first_payload)
    duplicate_email = client.post(
        "/api/auth/register",
        json=_registration_payload(
            "duplicate-email",
            email=first_payload["email"],
        ),
    )
    duplicate_username = client.post(
        "/api/auth/register",
        json=_registration_payload(
            "duplicate-username",
            username=first_payload["username"],
        ),
    )
    admin_request = client.post(
        "/api/auth/register",
        json=_registration_payload("admin", role="ADMIN"),
    )

    for response in (
        successful,
        duplicate_email,
        duplicate_username,
        admin_request,
    ):
        assert response.status_code == 202
        assert response.json() == REGISTRATION_ACCEPTED
        assert response.headers.get_list("set-cookie") == []

    with SessionLocal() as db:
        users = db.query(models.User).all()
        assert [(user.username, user.email, user.role) for user in users] == [
            (
                first_payload["username"],
                first_payload["email"],
                models.UserRole.STUDENT,
            )
        ]

    client.cookies.clear()
    assert client.get("/api/auth/session").status_code == 401


def test_disabled_password_registration_is_generic_and_creates_no_account(
    client,
    monkeypatch,
):
    disabled_settings = main.settings.model_copy(
        update={"local_password_registration_enabled": False}
    )
    monkeypatch.setattr(main, "settings", disabled_settings)

    def password_hashing_must_not_run(_password):
        raise AssertionError("disabled registration must not hash submitted passwords")

    monkeypatch.setattr(main, "hash_password", password_hashing_must_not_run)
    response = client.post(
        "/api/auth/register",
        json=_registration_payload("disabled-in-production"),
    )

    assert response.status_code == 202
    assert response.json() == REGISTRATION_ACCEPTED
    assert response.headers.get_list("set-cookie") == []
    with SessionLocal() as db:
        assert db.query(models.User).count() == 0


def test_password_registration_and_login_use_one_normalized_email_identity(client):
    first = client.post(
        "/api/auth/register",
        json=_registration_payload(
            "email-case-first",
            email="Case.Sensitive@EXAMPLE.COM",
        ),
    )
    case_variant = client.post(
        "/api/auth/register",
        json=_registration_payload(
            "email-case-second",
            email="case.sensitive@example.com",
        ),
    )

    assert first.status_code == 202
    assert case_variant.status_code == 202
    assert first.json() == case_variant.json() == REGISTRATION_ACCEPTED
    with SessionLocal() as db:
        users = db.query(models.User).all()
        assert len(users) == 1
        assert users[0].email == "case.sensitive@example.com"

    login = client.post(
        "/api/auth/login",
        json={
            "email": "CASE.SENSITIVE@example.com",
            "password": "synthetic-registration-password",
        },
    )
    assert login.status_code == 200


@pytest.mark.parametrize(
    "email",
    (
        "Straße@example.com",
        "τελικοσς@example.com",
    ),
)
def test_non_ascii_email_registration_is_generic_and_creates_no_identity(
    client,
    email,
):
    response = client.post(
        "/api/auth/register",
        json=_registration_payload("unicode-email", email=email),
    )

    assert response.status_code == 202
    assert response.json() == REGISTRATION_ACCEPTED
    assert response.headers.get_list("set-cookie") == []
    with SessionLocal() as db:
        assert db.query(models.User).count() == 0


def test_email_normalization_is_ascii_lowercase_not_unicode_casefolding():
    assert identity_controls.normalize_email(" Teacher@EXAMPLE.COM ") == (
        "teacher@example.com"
    )
    with pytest.raises(ValueError, match="ASCII"):
        identity_controls.normalize_email("Straße@example.com")
    with pytest.raises(ValueError, match="ASCII"):
        identity_controls.normalize_email("τελικοσς@example.com")


def test_email_normalization_rejects_tab_control():
    with pytest.raises(ValueError, match="control"):
        identity_controls.normalize_email("teacher@example.com\t")


@pytest.mark.parametrize("control_character", ["\x00", "\x07", "\x1c", "\x7f"])
def test_email_normalization_rejects_every_ascii_control_character(
    control_character,
):
    with pytest.raises(ValueError, match="control"):
        identity_controls.normalize_email(
            f"teacher{control_character}@example.com"
        )


@pytest.mark.parametrize("control_character", ["\x00", "\x07", "\x1c", "\x7f"])
def test_control_character_login_is_generic_and_never_reaches_database(
    client,
    control_character,
):
    response = client.post(
        "/api/auth/login",
        json={
            "email": f"unknown{control_character}@example.com",
            "password": "synthetic-identity-password",
        },
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid email or password"}


def test_control_character_registration_validation_is_generic(client):
    response = client.post(
        "/api/auth/register",
        json=_registration_payload(
            "control-email",
            email="student\x00@example.com",
        ),
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid authentication request"}
    assert "student" not in response.text


def test_verified_provider_non_ascii_email_failure_is_generic(
    client,
    monkeypatch,
):
    monkeypatch.setattr(
        main,
        "verify_google_id_token",
        lambda *args, **kwargs: {
            "iss": "https://accounts.google.com",
            "sub": "unicode-provider-subject",
            "email": "Straße@example.com",
            "given_name": "Unicode",
            "family_name": "Teacher",
        },
    )

    response = client.post(
        "/api/auth/google-signup",
        json={"idToken": "synthetic-provider-token", "role": "STUDENT"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "External authentication failed"}
    with SessionLocal() as db:
        assert db.query(models.User).count() == 0


def test_legacy_teacher_record_is_reused_by_user_id(client):
    user_id = _create_user(
        suffix="legacy-teacher-canonical",
        role=models.UserRole.TEACHER,
    )
    with SessionLocal() as db:
        teacher = models.Teacher(
            name="Legacy Teacher",
            email="legacy-teacher-alias@example.com",
            hashed_password="unused-legacy-hash",
            user_id=user_id,
        )
        db.add(teacher)
        db.flush()
        existing_teacher_id = teacher.id
        db.add(
            models.Class(
                name="Existing legacy class",
                description="Existing ownership must remain stable",
                access_code="LGCY01",
                teacher_id=teacher.id,
            )
        )
        db.commit()

    _, csrf_token = _login(
        client,
        role=models.UserRole.TEACHER,
        suffix="legacy-teacher-canonical",
    )
    response = client.post(
        "/api/classes",
        json={"name": "New canonical class", "description": "Same teacher"},
        headers={"X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 200
    with SessionLocal() as db:
        assert db.query(models.Teacher).count() == 1
        classes = db.query(models.Class).order_by(models.Class.id).all()
        assert len(classes) == 2
        assert {class_.teacher_id for class_ in classes} == {existing_teacher_id}


@pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="PostgreSQL migration apply integration test",
)
def test_postgres_identity_migration_reconciles_legacy_teacher_identity(client):
    del client
    migration_sql = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "0003_add_identity_controls.sql"
    ).read_text(encoding="utf-8")
    database_name = f"litblog_identity_migration_{secrets.token_hex(8)}"
    quoted_database = f'"{database_name}"'
    role_suffix = secrets.token_hex(6)
    identity_owner = f"identity_owner_{role_suffix}"
    account_operator = f"account_operator_{role_suffix}"
    invitation_operator = f"invitation_operator_{role_suffix}"
    rogue_operator = f"rogue_operator_{role_suffix}"
    temporary_roles = (
        identity_owner,
        account_operator,
        invitation_operator,
        rogue_operator,
    )
    admin_engine = create_engine(engine.url, isolation_level="AUTOCOMMIT")
    migration_engine = None
    connection = None
    cursor = None
    try:
        with admin_engine.connect() as admin_connection:
            admin_connection.exec_driver_sql(
                f'CREATE ROLE "{identity_owner}" NOLOGIN NOINHERIT '
                "NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
            )
            admin_connection.exec_driver_sql(
                f'CREATE ROLE "{account_operator}" NOLOGIN NOINHERIT '
                "NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
            )
            admin_connection.exec_driver_sql(
                f'CREATE ROLE "{invitation_operator}" NOLOGIN NOINHERIT '
                "NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
            )
            admin_connection.exec_driver_sql(
                f'CREATE ROLE "{rogue_operator}" NOLOGIN NOINHERIT '
                "NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
            )
            admin_connection.exec_driver_sql(f"CREATE DATABASE {quoted_database}")
        migration_engine = create_engine(engine.url.set(database=database_name))
        connection = migration_engine.raw_connection()
        connection.autocommit = True
        cursor = connection.cursor()
        cursor.execute(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                email VARCHAR(100) NOT NULL UNIQUE,
                password VARCHAR(255) NOT NULL,
                role VARCHAR(20) NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE teachers (
                id INTEGER PRIMARY KEY,
                email VARCHAR(100) UNIQUE,
                user_id INTEGER REFERENCES users(id)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE password_resets (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL UNIQUE,
                token VARCHAR(64),
                expires_at TIMESTAMPTZ,
                used BOOLEAN NOT NULL DEFAULT FALSE,
                delivery_status VARCHAR(16) NOT NULL DEFAULT 'PENDING',
                delivery_attempted_at TIMESTAMPTZ
            )
            """
        )
        cursor.execute(
            """
            INSERT INTO users (id, email, password, role)
            VALUES (
                1,
                ' Legacy.Teacher@EXAMPLE.COM ',
                'unused-legacy-password-hash',
                'TEACHER'
            )
            """
        )
        cursor.execute(
            """
            INSERT INTO password_resets (
                id,
                user_id,
                token,
                expires_at,
                used,
                delivery_status
            ) VALUES (
                20,
                1,
                'legacy-raw-reset-token',
                CURRENT_TIMESTAMP + INTERVAL '1 hour',
                FALSE,
                'DELIVERED'
            )
            """
        )
        cursor.execute(
            """
            INSERT INTO teachers (id, email, user_id)
            VALUES (10, 'legacy.teacher@example.com', NULL)
            """
        )

        cursor.execute(migration_sql)

        cursor.execute("SELECT email FROM users WHERE id = 1")
        assert cursor.fetchone() == ("legacy.teacher@example.com",)
        cursor.execute("SELECT email, user_id FROM teachers WHERE id = 10")
        assert cursor.fetchone() == ("legacy.teacher@example.com", 1)
        cursor.execute(
            """
            SELECT conname
            FROM pg_constraint
            WHERE conrelid = 'teachers'::regclass
            """
        )
        teacher_constraints = {name for (name,) in cursor.fetchall()}
        assert {
            "uq_teachers_user_id",
            "ck_teachers_email_ascii",
            "ck_teachers_email_canonical",
            "ck_teachers_email_no_whitespace",
        }.issubset(teacher_constraints)
        cursor.execute(
            """
            SELECT token, expires_at, used, delivery_status, delivery_claim_digest
            FROM password_resets
            WHERE id = 20
            """
        )
        assert cursor.fetchone() == (None, None, True, "FAILED", None)
        cursor.execute(
            """
            INSERT INTO browser_sessions (
                jti_digest, user_id, expires_at
            ) VALUES (
                repeat('d', 64), 1, CURRENT_TIMESTAMP + INTERVAL '1 hour'
            )
            """
        )
        cursor.execute(
            """
            UPDATE password_resets
            SET token = repeat('e', 64),
                expires_at = CURRENT_TIMESTAMP + INTERVAL '1 hour',
                used = FALSE,
                delivery_status = 'DELIVERED'
            WHERE id = 20
            """
        )
        cursor.execute(
            """
            SELECT public.operator_set_account_status(
                CAST('legacy.teacher@example.com' AS VARCHAR(100)),
                CAST(TRUE AS BOOLEAN),
                CAST('migration-smoke' AS VARCHAR(100)),
                CAST(repeat('a', 64) AS VARCHAR(64))
            )
            """
        )
        assert cursor.fetchone() == ("SUCCEEDED",)
        cursor.execute("SELECT disabled_at IS NOT NULL FROM users WHERE id = 1")
        assert cursor.fetchone() == (True,)
        cursor.execute(
            "SELECT revoked_at IS NOT NULL FROM browser_sessions WHERE user_id = 1"
        )
        assert cursor.fetchone() == (True,)
        cursor.execute(
            """
            SELECT token, expires_at, used, delivery_status
            FROM password_resets WHERE id = 20
            """
        )
        assert cursor.fetchone() == (None, None, True, "FAILED")

        cursor.execute(
            """
            SELECT public.operator_create_teacher_invitation(
                CAST(repeat('b', 64) AS VARCHAR(64)),
                CAST(repeat('c', 64) AS VARCHAR(64)),
                CAST(CURRENT_TIMESTAMP + INTERVAL '1 hour' AS TIMESTAMPTZ),
                CAST('migration-smoke' AS VARCHAR(100)),
                CAST(repeat('f', 64) AS VARCHAR(64))
            )
            """
        )
        assert cursor.fetchone() == ("SUCCEEDED",)
        cursor.execute(
            """
            SELECT public.operator_create_teacher_invitation(
                CAST(repeat('0', 64) AS VARCHAR(64)),
                CAST(repeat('c', 64) AS VARCHAR(64)),
                CAST(CURRENT_TIMESTAMP + INTERVAL '1 hour' AS TIMESTAMPTZ),
                CAST('migration-smoke' AS VARCHAR(100)),
                CAST(repeat('f', 64) AS VARCHAR(64))
            )
            """
        )
        assert cursor.fetchone() == ("CONFLICT",)
        cursor.execute(
            """
            SELECT public.operator_revoke_teacher_invitation(
                CAST(repeat('c', 64) AS VARCHAR(64)),
                CAST('migration-smoke' AS VARCHAR(100)),
                CAST(repeat('f', 64) AS VARCHAR(64))
            )
            """
        )
        assert cursor.fetchone() == ("SUCCEEDED",)
        cursor.execute(
            """
            SELECT action, outcome
            FROM operator_audit_events
            ORDER BY id
            """
        )
        assert cursor.fetchall() == [
            ("ACCOUNT_DISABLED", "SUCCEEDED"),
            ("TEACHER_INVITATION_CREATED", "SUCCEEDED"),
            ("TEACHER_INVITATION_CREATED", "CONFLICT"),
            ("TEACHER_INVITATION_REVOKED", "SUCCEEDED"),
        ]
        cursor.execute(
            """
            SELECT count(*), bool_and(prosecdef),
                   bool_and(proconfig = ARRAY['search_path=pg_catalog, pg_temp']::TEXT[])
            FROM pg_catalog.pg_proc AS procedures
            JOIN pg_catalog.pg_namespace AS namespaces
              ON namespaces.oid = procedures.pronamespace
            WHERE namespaces.nspname = 'public'
              AND procedures.proname LIKE 'operator_%'
            """
        )
        assert cursor.fetchone() == (3, True, True)

        cursor.execute(
            f"""
            GRANT EXECUTE ON FUNCTION public.operator_set_account_status(
                VARCHAR, BOOLEAN, VARCHAR, VARCHAR
            ) TO "{rogue_operator}";
            REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public
                FROM "{identity_owner}", "{account_operator}", "{invitation_operator}";
            REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public
                FROM "{identity_owner}", "{account_operator}", "{invitation_operator}";
            REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public
                FROM "{account_operator}", "{invitation_operator}";
            GRANT USAGE ON SCHEMA public TO "{identity_owner}";
            GRANT SELECT (id, email), UPDATE (disabled_at)
                ON users TO "{identity_owner}";
            GRANT SELECT (user_id, revoked_at, expires_at), UPDATE (revoked_at)
                ON browser_sessions TO "{identity_owner}";
            GRANT SELECT (user_id), UPDATE (
                token, expires_at, used, delivery_status,
                delivery_attempted_at, delivery_claim_digest
            ) ON password_resets TO "{identity_owner}";
            GRANT SELECT (email_digest, consumed_at, revoked_at, expires_at),
                  INSERT (token_digest, email_digest, expires_at, created_by),
                  UPDATE (revoked_at)
                ON teacher_invitations TO "{identity_owner}";
            GRANT INSERT (actor_identifier, action, outcome, resource_digest)
                ON operator_audit_events TO "{identity_owner}";
            GRANT USAGE ON SEQUENCE teacher_invitations_id_seq,
                                    operator_audit_events_id_seq
                TO "{identity_owner}";
            BEGIN;
            GRANT CREATE ON SCHEMA public TO "{identity_owner}";
            ALTER FUNCTION public.operator_set_account_status(
                VARCHAR, BOOLEAN, VARCHAR, VARCHAR
            ) OWNER TO "{identity_owner}";
            ALTER FUNCTION public.operator_create_teacher_invitation(
                VARCHAR, VARCHAR, TIMESTAMPTZ, VARCHAR, VARCHAR
            ) OWNER TO "{identity_owner}";
            ALTER FUNCTION public.operator_revoke_teacher_invitation(
                VARCHAR, VARCHAR, VARCHAR
            ) OWNER TO "{identity_owner}";
            REVOKE CREATE ON SCHEMA public FROM "{identity_owner}";
            DO $operator_acl$
            DECLARE
                privilege_record RECORD;
            BEGIN
                FOR privilege_record IN
                    SELECT
                        pg_catalog.format(
                            '%I.%I(%s)',
                            namespaces.nspname,
                            procedures.proname,
                            pg_catalog.pg_get_function_identity_arguments(
                                procedures.oid
                            )
                        ) AS function_signature,
                        grantees.rolname AS unexpected_function_grantee
                    FROM pg_catalog.pg_proc AS procedures
                    JOIN pg_catalog.pg_namespace AS namespaces
                      ON namespaces.oid = procedures.pronamespace
                    CROSS JOIN LATERAL pg_catalog.aclexplode(
                        COALESCE(
                            procedures.proacl,
                            pg_catalog.acldefault('f', procedures.proowner)
                        )
                    ) AS privileges
                    JOIN pg_catalog.pg_roles AS grantees
                      ON grantees.oid = privileges.grantee
                    WHERE procedures.proname IN (
                        'operator_set_account_status',
                        'operator_create_teacher_invitation',
                        'operator_revoke_teacher_invitation'
                    )
                      AND privileges.privilege_type = 'EXECUTE'
                      AND privileges.grantee <> procedures.proowner
                      AND (
                          grantees.rolname <> CASE procedures.proname
                              WHEN 'operator_set_account_status'
                                  THEN '{account_operator}'
                              ELSE '{invitation_operator}'
                          END
                          OR privileges.is_grantable
                      )
                LOOP
                    EXECUTE pg_catalog.format(
                        'REVOKE ALL PRIVILEGES ON FUNCTION %s FROM %I',
                        privilege_record.function_signature,
                        privilege_record.unexpected_function_grantee
                    );
                END LOOP;
            END;
            $operator_acl$;
            GRANT USAGE ON SCHEMA public
                TO "{account_operator}", "{invitation_operator}";
            GRANT EXECUTE ON FUNCTION public.operator_set_account_status(
                VARCHAR, BOOLEAN, VARCHAR, VARCHAR
            ) TO "{account_operator}";
            GRANT EXECUTE ON FUNCTION public.operator_create_teacher_invitation(
                VARCHAR, VARCHAR, TIMESTAMPTZ, VARCHAR, VARCHAR
            ) TO "{invitation_operator}";
            GRANT EXECUTE ON FUNCTION public.operator_revoke_teacher_invitation(
                VARCHAR, VARCHAR, VARCHAR
            ) TO "{invitation_operator}";
            COMMIT;
            """
        )
        cursor.execute(
            """
            SELECT
                pg_catalog.has_function_privilege(
                    %s,
                    'public.operator_set_account_status(character varying,boolean,character varying,character varying)',
                    'EXECUTE'
                ),
                pg_catalog.has_schema_privilege(%s, 'public', 'CREATE')
            """,
            (rogue_operator, identity_owner),
        )
        assert cursor.fetchone() == (False, False)
        cursor.execute("BEGIN")
        cursor.execute(f'SET LOCAL ROLE "{account_operator}"')
        cursor.execute(
            """
            SELECT public.operator_set_account_status(
                CAST('missing-release-probe@example.invalid' AS VARCHAR(100)),
                CAST(TRUE AS BOOLEAN),
                CAST('migration-smoke' AS VARCHAR(100)),
                CAST(repeat('1', 64) AS VARCHAR(64))
            )
            """
        )
        assert cursor.fetchone() == ("NOT_FOUND",)
        cursor.execute("ROLLBACK")

        cursor.execute("BEGIN")
        cursor.execute(f'SET LOCAL ROLE "{invitation_operator}"')
        cursor.execute(
            """
            SELECT public.operator_create_teacher_invitation(
                CAST(repeat('1', 64) AS VARCHAR(64)),
                CAST(repeat('2', 64) AS VARCHAR(64)),
                CAST(CURRENT_TIMESTAMP + INTERVAL '1 hour' AS TIMESTAMPTZ),
                CAST('migration-smoke' AS VARCHAR(100)),
                CAST(repeat('3', 64) AS VARCHAR(64))
            )
            """
        )
        assert cursor.fetchone() == ("SUCCEEDED",)
        cursor.execute("ROLLBACK")

        for denied_role, denied_statement in (
            (account_operator, "SELECT password FROM public.users LIMIT 0"),
            (
                account_operator,
                "SELECT public.operator_create_teacher_invitation("
                "repeat('1', 64)::VARCHAR, repeat('2', 64)::VARCHAR, "
                "CURRENT_TIMESTAMP + INTERVAL '1 hour', "
                "'migration-smoke'::VARCHAR, repeat('3', 64)::VARCHAR)",
            ),
            (
                invitation_operator,
                "SELECT token_digest FROM public.teacher_invitations LIMIT 0",
            ),
            (
                invitation_operator,
                "SELECT public.operator_set_account_status("
                "'missing@example.invalid'::VARCHAR, TRUE, "
                "'migration-smoke'::VARCHAR, repeat('3', 64)::VARCHAR)",
            ),
            (
                rogue_operator,
                "SELECT public.operator_set_account_status("
                "'missing@example.invalid'::VARCHAR, TRUE, "
                "'migration-smoke'::VARCHAR, repeat('3', 64)::VARCHAR)",
            ),
        ):
            cursor.execute("BEGIN")
            cursor.execute(f'SET LOCAL ROLE "{denied_role}"')
            with pytest.raises(PsycopgDatabaseError) as denied:
                cursor.execute(denied_statement)
            assert denied.value.pgcode == "42501"
            cursor.execute("ROLLBACK")

        cursor.execute(
            """
            SELECT count(*), bool_and(owners.rolname = %s),
                   bool_and(procedures.prosecdef),
                   bool_and(procedures.proconfig = ARRAY[
                       'search_path=pg_catalog, pg_temp'
                   ]::TEXT[])
            FROM pg_catalog.pg_proc AS procedures
            JOIN pg_catalog.pg_namespace AS namespaces
              ON namespaces.oid = procedures.pronamespace
            JOIN pg_catalog.pg_roles AS owners
              ON owners.oid = procedures.proowner
            WHERE namespaces.nspname = 'public'
              AND procedures.proname LIKE 'operator_%%'
            """,
            (identity_owner,),
        )
        assert cursor.fetchone() == (3, True, True, True)
        cursor.execute(
            """
            SELECT procedures.proname,
                   pg_catalog.array_agg(grantees.rolname ORDER BY grantees.rolname)
            FROM pg_catalog.pg_proc AS procedures
            JOIN pg_catalog.pg_namespace AS namespaces
              ON namespaces.oid = procedures.pronamespace
            CROSS JOIN LATERAL pg_catalog.aclexplode(
                COALESCE(
                    procedures.proacl,
                    pg_catalog.acldefault('f', procedures.proowner)
                )
            ) AS privileges
            JOIN pg_catalog.pg_roles AS grantees
              ON grantees.oid = privileges.grantee
            WHERE namespaces.nspname = 'public'
              AND procedures.proname LIKE 'operator_%%'
              AND privileges.privilege_type = 'EXECUTE'
            GROUP BY procedures.proname
            """
        )
        function_grantees = {
            function_name: set(grantees)
            for function_name, grantees in cursor.fetchall()
        }
        assert function_grantees == {
            "operator_set_account_status": {identity_owner, account_operator},
            "operator_create_teacher_invitation": {
                identity_owner,
                invitation_operator,
            },
            "operator_revoke_teacher_invitation": {
                identity_owner,
                invitation_operator,
            },
        }
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()
        if migration_engine is not None:
            migration_engine.dispose()
        try:
            with admin_engine.connect() as admin_connection:
                admin_connection.exec_driver_sql(
                    f"DROP DATABASE IF EXISTS {quoted_database} WITH (FORCE)"
                )
                for temporary_role in reversed(temporary_roles):
                    admin_connection.exec_driver_sql(
                        f'DROP ROLE IF EXISTS "{temporary_role}"'
                    )
        finally:
            admin_engine.dispose()


def test_password_registration_disallowed_domain_is_generic_and_creates_no_user(client):
    response = client.post(
        "/api/auth/register",
        json=_registration_payload(
            "external-domain",
            email="student@outside-school.org",
        ),
    )

    assert response.status_code == 202
    assert response.json() == REGISTRATION_ACCEPTED
    assert response.headers.get_list("set-cookie") == []
    with SessionLocal() as db:
        assert db.query(models.User).count() == 0


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        (
            "/api/auth/register",
            {
                **_registration_payload("oversized-email"),
                "email": f"{'a' * 64}@{'b' * 30}.example",
            },
        ),
        (
            "/api/auth/login",
            {
                "email": f"{'a' * 64}@{'b' * 30}.example",
                "password": "synthetic-invalid-password",
            },
        ),
        (
            "/api/auth/forgot-password",
            {"email": f"{'a' * 64}@{'b' * 30}.example"},
        ),
    ],
)
def test_account_email_requests_are_bounded_to_database_contract(client, path, payload):
    response = client.post(path, json=payload)

    assert response.status_code == 422
    with SessionLocal() as db:
        assert db.query(models.User).count() == 0


@pytest.mark.parametrize(
    ("path", "payload", "secret_value"),
    [
        (
            "/api/auth/register",
            {
                **_registration_payload("oversized-invitation", role="TEACHER"),
                "teacher_invitation_token": "sensitive-invitation-" + ("x" * 512),
            },
            "sensitive-invitation-" + ("x" * 512),
        ),
        (
            "/api/auth/login",
            {
                "email": "validation-login@example.com",
                "password": "sensitive-password-" + ("x" * 1_024),
            },
            "sensitive-password-" + ("x" * 1_024),
        ),
        (
            "/api/auth/reset-password",
            {
                "token": "sensitive-reset-token-" + ("x" * 128),
                "new_password": "valid-synthetic-password-value",
            },
            "sensitive-reset-token-" + ("x" * 128),
        ),
        (
            "/api/auth/register",
            {
                **_registration_payload("multibyte-password"),
                "password": "🔐" * 300,
            },
            "🔐" * 300,
        ),
        (
            "/api/auth/login",
            {
                "email": "multibyte-password@example.com",
                "password": "🔐" * 300,
            },
            "🔐" * 300,
        ),
    ],
)
def test_sensitive_auth_validation_errors_never_echo_secret_inputs(
    client,
    caplog,
    capsys,
    path,
    payload,
    secret_value,
):
    with caplog.at_level(logging.DEBUG):
        response = client.post(path, json=payload)

    captured = capsys.readouterr()
    combined_output = response.text + caplog.text + captured.out + captured.err
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid authentication request"}
    assert secret_value not in combined_output


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (
            main.LoginRequest,
            {"email": "multibyte@example.com", "password": "🔐" * 300},
        ),
        (
            main.ResetPasswordRequest,
            {"token": "synthetic-token", "new_password": "🔐" * 300},
        ),
        (
            main.schemas.ChangePasswordRequest,
            {"current_password": "🔐" * 300, "new_password": "valid-password-value"},
        ),
        (
            main.schemas.ChangePasswordRequest,
            {"current_password": "valid-password-value", "new_password": "🔐" * 300},
        ),
    ],
)
def test_password_request_models_enforce_utf8_byte_bound(model, payload):
    with pytest.raises(ValidationError, match="UTF-8 bytes"):
        model(**payload)


def test_registration_hashes_password_before_private_account_lookup(client, monkeypatch):
    payload = _registration_payload("hash-order")
    assert client.post("/api/auth/register", json=payload).status_code in {200, 202}
    order = []
    original_hash_password = main.hash_password

    def recorded_hash_password(password):
        order.append("hash")
        return original_hash_password(password)

    def record_user_query(
        connection,
        cursor,
        statement,
        parameters,
        context,
        executemany,
    ):
        del connection, cursor, parameters, context, executemany
        normalized = " ".join(statement.casefold().split())
        if " from users " in f" {normalized} ":
            order.append("user-query")

    monkeypatch.setattr(main, "hash_password", recorded_hash_password)
    event.listen(engine, "before_cursor_execute", record_user_query)
    try:
        response = client.post("/api/auth/register", json=payload)
    finally:
        event.remove(engine, "before_cursor_execute", record_user_query)

    assert response.status_code == 202
    assert order.index("hash") < order.index("user-query")


def test_teacher_password_registration_consumes_email_bound_invitation(client):
    now = datetime.now(UTC).replace(microsecond=0)
    settings = identity_controls.get_settings()
    teacher_email = "invited-registration@example.com"
    with SessionLocal() as db:
        token = identity_controls.create_teacher_invitation(
            db,
            email=teacher_email,
            created_by="security-operator",
            expires_at=now + timedelta(hours=1),
            settings=settings,
            now=now,
        )
        db.commit()

    response = client.post(
        "/api/auth/register",
        json=_registration_payload(
            "invited-teacher",
            role="TEACHER",
            email=teacher_email,
            teacher_invitation_token=token,
        ),
    )

    assert response.status_code == 202
    assert response.json() == REGISTRATION_ACCEPTED
    assert response.headers.get_list("set-cookie") == []
    assert token not in response.text
    with SessionLocal() as db:
        teacher = db.query(models.User).filter(models.User.email == teacher_email).one()
        invitation = db.query(models.TeacherInvitation).one()
        assert teacher.role == models.UserRole.TEACHER
        assert invitation.consumed_at is not None


def test_invalid_mismatched_expired_and_replayed_invitations_are_generic(client):
    now = datetime.now(UTC).replace(microsecond=0)
    settings = identity_controls.get_settings()
    with SessionLocal() as db:
        mismatch_token = identity_controls.create_teacher_invitation(
            db,
            email="bound-teacher@example.com",
            created_by="security-operator",
            expires_at=now + timedelta(hours=1),
            settings=settings,
            now=now,
        )
        expired_token = identity_controls.create_teacher_invitation(
            db,
            email="expired-teacher@example.com",
            created_by="security-operator",
            expires_at=now + timedelta(minutes=1),
            settings=settings,
            now=now,
        )
        consumed_token = identity_controls.create_teacher_invitation(
            db,
            email="consumed-teacher@example.com",
            created_by="security-operator",
            expires_at=now + timedelta(hours=1),
            settings=settings,
            now=now,
        )
        assert identity_controls.consume_teacher_invitation(
            db,
            token=consumed_token,
            email="consumed-teacher@example.com",
            settings=settings,
            now=now,
        ) is True
        expired_row = db.query(models.TeacherInvitation).filter(
            models.TeacherInvitation.token_digest
            == hashlib.sha256(expired_token.encode("utf-8")).hexdigest()
        ).one()
        expired_row.expires_at = now - timedelta(minutes=1)
        db.commit()

    cases = (
        ("invalid", "invalid-teacher@example.com", "invalid-token"),
        ("mismatch", "other-teacher@example.com", mismatch_token),
        ("expired", "expired-teacher@example.com", expired_token),
        ("replayed", "consumed-teacher@example.com", consumed_token),
    )
    responses = [
        client.post(
            "/api/auth/register",
            json=_registration_payload(
                suffix,
                role="TEACHER",
                email=email,
                teacher_invitation_token=token,
            ),
        )
        for suffix, email, token in cases
    ]

    for response in responses:
        assert response.status_code == 202
        assert response.json() == REGISTRATION_ACCEPTED
        assert response.headers.get_list("set-cookie") == []

    with SessionLocal() as db:
        assert db.query(models.User).count() == 0


def test_legacy_teacher_access_code_registration_field_is_rejected(client):
    payload = _registration_payload("legacy-code", role="TEACHER")
    payload["access_code"] = "legacy-shared-code"

    response = client.post("/api/auth/register", json=payload)

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid authentication request"}
    with SessionLocal() as db:
        assert db.query(models.User).count() == 0


def test_cryptographically_valid_jwt_without_server_session_is_denied(client):
    user_id = _create_student(suffix="stateless-denied")
    stateless_token = issue_access_token(
        user_id,
        settings=identity_controls.get_settings(),
    )
    _set_cookie_session(client, stateless_token)

    denied = client.get("/api/auth/session")

    assert denied.status_code == 401
    with SessionLocal() as db:
        issued = identity_controls.issue_browser_session(
            db,
            user_id=user_id,
            settings=identity_controls.get_settings(),
        )
        db.commit()
    _set_cookie_session(client, issued.token)

    accepted = client.get("/api/auth/session")

    assert accepted.status_code == 200
    assert accepted.json()["user_id"] == user_id


def test_password_login_creates_digest_only_server_session(client):
    user_id = _create_student(suffix="login-persisted")

    response = client.post(
        "/api/auth/login",
        json={
            "email": "identity-student-login-persisted@example.com",
            "password": "synthetic-identity-password",
        },
    )

    assert response.status_code == 200
    token = client.cookies.get(main._session_cookie_name())
    assert isinstance(token, str)
    payload = decode_access_token(token, settings=identity_controls.get_settings())
    with SessionLocal() as db:
        session = db.query(models.BrowserSession).one()
        assert session.user_id == user_id
        assert session.jti_digest == hashlib.sha256(
            payload["jti"].encode("utf-8")
        ).hexdigest()
        persisted_text = " ".join(str(value) for value in session.__dict__.values())
        assert token not in persisted_text
        assert payload["jti"] not in persisted_text


def test_session_row_commit_precedes_all_browser_cookie_writes(client, monkeypatch):
    del client
    events = []
    issued = identity_controls.IssuedBrowserSession(
        token="synthetic-issued-session-token",
        expires_at=datetime.now(UTC) + timedelta(minutes=30),
    )

    class RecordingDatabase:
        def commit(self):
            events.append("commit")

        def rollback(self):
            events.append("rollback")

    class RecordingResponse:
        def set_cookie(self, *args, **kwargs):
            del args, kwargs
            events.append("cookie")

    monkeypatch.setattr(main, "issue_browser_session", lambda *args, **kwargs: issued)

    main._set_browser_session(
        RecordingResponse(),
        SimpleNamespace(id=321),
        RecordingDatabase(),
    )

    assert events == ["commit", "cookie", "cookie"]


def test_password_login_verification_runs_off_the_event_loop(client, monkeypatch):
    _create_student(suffix="login-threadpool")
    offloaded_functions = []

    async def recorded_threadpool(function, *args, **kwargs):
        offloaded_functions.append(function)
        return function(*args, **kwargs)

    monkeypatch.setattr(main, "run_in_threadpool", recorded_threadpool)
    response = client.post(
        "/api/auth/login",
        json={
            "email": "identity-student-login-threadpool@example.com",
            "password": "synthetic-identity-password",
        },
    )

    assert response.status_code == 200
    assert main.verify_and_update_password in offloaded_functions


def test_password_login_failures_are_generic_and_use_dummy_verification(
    client,
    monkeypatch,
):
    active_user_id = _create_student(suffix="login-enumeration-active")
    disabled_user_id = _create_student(suffix="login-enumeration-disabled")
    with SessionLocal() as db:
        disabled_user = db.get(models.User, disabled_user_id)
        disabled_user.disabled_at = datetime.now(UTC)
        active_hash = db.get(models.User, active_user_id).password
        db.commit()

    verified_hashes = []

    def rejected_password(password, encoded_hash):
        del password
        verified_hashes.append(encoded_hash)
        return False, None

    monkeypatch.setattr(main, "verify_and_update_password", rejected_password)
    responses = [
        client.post(
            "/api/auth/login",
            json={
                "email": "identity-student-login-enumeration-missing@example.com",
                "password": "synthetic-invalid-password",
            },
        ),
        client.post(
            "/api/auth/login",
            json={
                "email": "identity-student-login-enumeration-active@example.com",
                "password": "synthetic-invalid-password",
            },
        ),
        client.post(
            "/api/auth/login",
            json={
                "email": "identity-student-login-enumeration-disabled@example.com",
                "password": "synthetic-invalid-password",
            },
        ),
    ]

    assert [response.status_code for response in responses] == [401, 401, 401]
    assert [response.json() for response in responses] == [
        {"detail": "Invalid email or password"},
        {"detail": "Invalid email or password"},
        {"detail": "Invalid email or password"},
    ]
    assert verified_hashes == [
        main._DUMMY_PASSWORD_HASH,
        active_hash,
        main._DUMMY_PASSWORD_HASH,
    ]


@pytest.mark.parametrize("state", ["revoked", "expired"])
def test_revoked_or_expired_server_session_is_denied(client, state):
    user_id = _create_student(suffix=f"denied-{state}")
    with SessionLocal() as db:
        issued = identity_controls.issue_browser_session(
            db,
            user_id=user_id,
            settings=identity_controls.get_settings(),
        )
        session = db.query(models.BrowserSession).one()
        if state == "revoked":
            session.revoked_at = datetime.now(UTC)
        else:
            session.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        db.commit()

    _set_cookie_session(client, issued.token)

    response = client.get("/api/auth/session")

    assert response.status_code == 401


@pytest.mark.parametrize("state", ["revoked", "disabled"])
def test_bearer_fallback_checks_server_revocation_and_account_status(client, state):
    user_id = _create_student(suffix=f"bearer-{state}")
    with SessionLocal() as db:
        issued = identity_controls.issue_browser_session(
            db,
            user_id=user_id,
            settings=identity_controls.get_settings(),
        )
        if state == "revoked":
            db.query(models.BrowserSession).one().revoked_at = datetime.now(UTC)
        else:
            db.get(models.User, user_id).disabled_at = datetime.now(UTC)
        db.commit()

    response = client.get(
        "/api/auth/session",
        headers={"Authorization": f"Bearer {issued.token}"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}


def test_logout_revokes_only_current_session_and_is_retry_safe(client):
    user_id = _create_student(suffix="logout-current")
    login_payload = {
        "email": "identity-student-logout-current@example.com",
        "password": "synthetic-identity-password",
    }
    assert client.post("/api/auth/login", json=login_payload).status_code == 200
    first_token = client.cookies.get(main._session_cookie_name())
    first_csrf = client.cookies.get(main._csrf_cookie_name())
    assert client.post("/api/auth/login", json=login_payload).status_code == 200
    second_token = client.cookies.get(main._session_cookie_name())
    second_csrf = client.cookies.get(main._csrf_cookie_name())
    assert first_token != second_token

    with SessionLocal() as db:
        assert db.query(models.BrowserSession).count() == 2

    _set_cookie_session(client, first_token, csrf_token=first_csrf)
    logout = client.post(
        "/api/auth/logout",
        headers={"X-CSRF-Token": first_csrf},
    )

    assert logout.status_code == 204
    first_jti = decode_access_token(
        first_token,
        settings=identity_controls.get_settings(),
    )["jti"]
    second_jti = decode_access_token(
        second_token,
        settings=identity_controls.get_settings(),
    )["jti"]
    with SessionLocal() as db:
        sessions = {
            row.jti_digest: row for row in db.query(models.BrowserSession).all()
        }
        assert sessions[hashlib.sha256(first_jti.encode("utf-8")).hexdigest()].revoked_at is not None
        assert sessions[hashlib.sha256(second_jti.encode("utf-8")).hexdigest()].revoked_at is None

    _set_cookie_session(client, first_token, csrf_token=first_csrf)
    assert client.get("/api/auth/session").status_code == 401
    _set_cookie_session(client, second_token, csrf_token=second_csrf)
    assert client.get("/api/auth/session").status_code == 200
    assert client.get("/api/auth/session").json()["user_id"] == user_id


def test_change_password_revokes_all_sessions_and_requires_new_login(client):
    user_id = _create_student(suffix="change-password")
    raw_reset_token = "synthetic-pre-change-password-reset-token"
    reset_id = _create_password_reset(
        user_id=user_id,
        raw_token=raw_reset_token,
    )
    first_token, first_csrf = _login(
        client,
        role=models.UserRole.STUDENT,
        suffix="change-password",
    )
    second_token, second_csrf = _login(
        client,
        role=models.UserRole.STUDENT,
        suffix="change-password",
    )

    response = client.post(
        "/api/auth/change-password",
        json={
            "current_password": "synthetic-identity-password",
            "new_password": "synthetic-new-identity-password",
        },
        headers={"X-CSRF-Token": second_csrf},
    )

    assert response.status_code == 204
    assert client.cookies.get(main._session_cookie_name()) is None
    assert client.cookies.get(main._csrf_cookie_name()) is None
    with SessionLocal() as db:
        assert db.query(models.BrowserSession).count() == 2
        assert all(
            row.revoked_at is not None
            for row in db.query(models.BrowserSession).all()
        )
        password_reset = db.get(models.PasswordReset, reset_id)
        assert password_reset.token is None
        assert password_reset.used is True
        assert password_reset.delivery_status == "FAILED"

    _set_cookie_session(client, first_token, csrf_token=first_csrf)
    assert client.get("/api/auth/session").status_code == 401
    _set_cookie_session(client, second_token, csrf_token=second_csrf)
    assert client.get("/api/auth/session").status_code == 401
    client.cookies.clear()

    reset_replay = client.post(
        "/api/auth/reset-password",
        json={
            "token": raw_reset_token,
            "new_password": "synthetic-stolen-reset-password",
        },
    )

    old_password = client.post(
        "/api/auth/login",
        json={
            "email": "identity-student-change-password@example.com",
            "password": "synthetic-identity-password",
        },
    )
    new_password = client.post(
        "/api/auth/login",
        json={
            "email": "identity-student-change-password@example.com",
            "password": "synthetic-new-identity-password",
        },
    )
    assert reset_replay.status_code == 400
    assert old_password.status_code == 401
    assert new_password.status_code == 200


def test_password_reset_revokes_every_existing_session(client):
    user_id = _create_student(suffix="reset-revokes")
    first_token, first_csrf = _login(
        client,
        role=models.UserRole.STUDENT,
        suffix="reset-revokes",
    )
    second_token, second_csrf = _login(
        client,
        role=models.UserRole.STUDENT,
        suffix="reset-revokes",
    )
    raw_reset_token = "synthetic-delivered-reset-token"
    now_naive = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
    with SessionLocal() as db:
        db.add(
            models.PasswordReset(
                user_id=user_id,
                token=hashlib.sha256(raw_reset_token.encode("utf-8")).hexdigest(),
                created_at=now_naive,
                expires_at=now_naive + timedelta(hours=1),
                used=False,
                delivery_status="DELIVERED",
            )
        )
        db.commit()

    response = client.post(
        "/api/auth/reset-password",
        json={
            "token": raw_reset_token,
            "new_password": "synthetic-reset-identity-password",
        },
    )

    assert response.status_code == 200
    with SessionLocal() as db:
        sessions = db.query(models.BrowserSession).all()
        assert len(sessions) == 2
        assert all(session.revoked_at is not None for session in sessions)

    _set_cookie_session(client, first_token, csrf_token=first_csrf)
    assert client.get("/api/auth/session").status_code == 401
    _set_cookie_session(client, second_token, csrf_token=second_csrf)
    assert client.get("/api/auth/session").status_code == 401
    client.cookies.clear()
    assert client.post(
        "/api/auth/login",
        json={
            "email": "identity-student-reset-revokes@example.com",
            "password": "synthetic-reset-identity-password",
        },
    ).status_code == 200


def test_legacy_raw_password_reset_token_is_never_accepted(client):
    user_id = _create_student(suffix="legacy-raw-reset")
    raw_token = "a" * 64
    with SessionLocal() as db:
        original_password_hash = db.get(models.User, user_id).password
        db.add(
            models.PasswordReset(
                user_id=user_id,
                token=raw_token,
                expires_at=datetime.now(UTC) + timedelta(hours=1),
                used=False,
                delivery_status="DELIVERED",
            )
        )
        db.commit()

    response = client.post(
        "/api/auth/reset-password",
        json={
            "token": raw_token,
            "new_password": "synthetic-password-that-must-not-win",
        },
    )

    assert response.status_code == 400
    with SessionLocal() as db:
        assert db.get(models.User, user_id).password == original_password_hash
        assert db.query(models.PasswordReset).one().used is False


def test_user_status_route_is_admin_only_and_disable_revokes_all(client):
    target_user_id = _create_student(suffix="status-target")
    student_user_id = _create_student(suffix="status-actor")
    teacher_user_id = _create_user(
        suffix="status-actor",
        role=models.UserRole.TEACHER,
    )
    admin_user_id = _create_user(
        suffix="status-actor",
        role=models.UserRole.ADMIN,
    )
    del student_user_id, teacher_user_id

    with SessionLocal() as db:
        target_sessions = [
            identity_controls.issue_browser_session(
                db,
                user_id=target_user_id,
                settings=identity_controls.get_settings(),
            ).token
            for _ in range(2)
        ]
        db.commit()

    anonymous = client.put(
        f"/api/users/{target_user_id}/status",
        json={"disabled": True},
    )
    _, student_csrf = _login(
        client,
        role=models.UserRole.STUDENT,
        suffix="status-actor",
    )
    student = client.put(
        f"/api/users/{target_user_id}/status",
        json={"disabled": True},
        headers={"X-CSRF-Token": student_csrf},
    )
    _, teacher_csrf = _login(
        client,
        role=models.UserRole.TEACHER,
        suffix="status-actor",
    )
    teacher = client.put(
        f"/api/users/{target_user_id}/status",
        json={"disabled": True},
        headers={"X-CSRF-Token": teacher_csrf},
    )
    _, admin_csrf = _login(
        client,
        role=models.UserRole.ADMIN,
        suffix="status-actor",
    )
    administrator = client.put(
        f"/api/users/{target_user_id}/status",
        json={"disabled": True},
        headers={"X-CSRF-Token": admin_csrf},
    )

    assert anonymous.status_code == 401
    assert student.status_code == 403
    assert teacher.status_code == 403
    assert administrator.status_code == 200
    assert administrator.json() == {"disabled": True}
    with SessionLocal() as db:
        target = db.get(models.User, target_user_id)
        assert target.disabled_at is not None
        assert all(
            row.revoked_at is not None
            for row in db.query(models.BrowserSession)
            .filter(models.BrowserSession.user_id == target_user_id)
            .all()
        )
        disable_audit = db.query(models.OperatorAuditEvent).one()
        assert disable_audit.actor_identifier == f"admin-user:{admin_user_id}"
        assert disable_audit.action == "ACCOUNT_DISABLED"
        assert disable_audit.outcome == "SUCCEEDED"
        assert disable_audit.resource_digest == (
            identity_controls.operator_audit_resource_digest(
                "identity-student-status-target@example.com",
                settings=identity_controls.get_settings(),
            )
        )

    _set_cookie_session(client, target_sessions[0])
    assert client.get("/api/auth/session").status_code == 401
    client.cookies.clear()
    assert client.post(
        "/api/auth/login",
        json={
            "email": "identity-student-status-target@example.com",
            "password": "synthetic-identity-password",
        },
    ).status_code == 401

    _, fresh_admin_csrf = _login(
        client,
        role=models.UserRole.ADMIN,
        suffix="status-actor",
    )
    self_disable = client.put(
        f"/api/users/{admin_user_id}/status",
        json={"disabled": True},
        headers={"X-CSRF-Token": fresh_admin_csrf},
    )
    re_enabled = client.put(
        f"/api/users/{target_user_id}/status",
        json={"disabled": False},
        headers={"X-CSRF-Token": fresh_admin_csrf},
    )
    assert self_disable.status_code == 400
    assert re_enabled.status_code == 200
    assert re_enabled.json() == {"disabled": False}
    with SessionLocal() as db:
        audit_events = db.query(models.OperatorAuditEvent).order_by(
            models.OperatorAuditEvent.id
        ).all()
        assert [event.actor_identifier for event in audit_events] == [
            f"admin-user:{admin_user_id}",
            f"admin-user:{admin_user_id}",
        ]
        assert [event.action for event in audit_events] == [
            "ACCOUNT_DISABLED",
            "ACCOUNT_ENABLED",
        ]
        assert [event.outcome for event in audit_events] == [
            "SUCCEEDED",
            "SUCCEEDED",
        ]
        assert len({event.resource_digest for event in audit_events}) == 1
    client.cookies.clear()
    assert client.post(
        "/api/auth/login",
        json={
            "email": "identity-student-status-target@example.com",
            "password": "synthetic-identity-password",
        },
    ).status_code == 200


def test_user_status_audit_failure_rolls_back_status_and_session_revocation(
    client,
    monkeypatch,
):
    target_user_id = _create_student(suffix="status-audit-failure-target")
    admin_user_id = _create_user(
        suffix="status-audit-failure-actor",
        role=models.UserRole.ADMIN,
    )
    with SessionLocal() as db:
        session = identity_controls.issue_browser_session(
            db,
            user_id=target_user_id,
            settings=identity_controls.get_settings(),
        )
        target_session_digest = hashlib.sha256(
            decode_access_token(session.token)["jti"].encode("utf-8")
        ).hexdigest()
        db.commit()
    raw_reset_token = "synthetic-status-audit-failure-reset-token"
    reset_id = _create_password_reset(
        user_id=target_user_id,
        raw_token=raw_reset_token,
    )

    def unavailable_audit(*args, **kwargs):
        del args, kwargs
        raise SQLAlchemyError("synthetic audit storage failure")

    monkeypatch.setattr(main, "record_operator_audit_event", unavailable_audit)
    _, admin_csrf = _login(
        client,
        role=models.UserRole.ADMIN,
        suffix="status-audit-failure-actor",
    )
    response = client.put(
        f"/api/users/{target_user_id}/status",
        json={"disabled": True},
        headers={"X-CSRF-Token": admin_csrf},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Account status could not be updated"}
    with SessionLocal() as db:
        target = db.get(models.User, target_user_id)
        target_session = (
            db.query(models.BrowserSession)
            .filter(models.BrowserSession.jti_digest == target_session_digest)
            .one()
        )
        assert target.disabled_at is None
        assert target_session.revoked_at is None
        password_reset = db.get(models.PasswordReset, reset_id)
        assert password_reset.token == hashlib.sha256(
            raw_reset_token.encode("utf-8")
        ).hexdigest()
        assert password_reset.used is False
        assert password_reset.delivery_status == "DELIVERED"
        assert db.query(models.OperatorAuditEvent).count() == 0
        assert db.get(models.User, admin_user_id).disabled_at is None


def test_disabled_account_cannot_queue_or_consume_password_reset(client):
    user_id = _create_student(suffix="disabled-reset")
    original_password_hash = None
    raw_reset_token = "synthetic-disabled-reset-token"
    now_naive = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
    with SessionLocal() as db:
        user = db.get(models.User, user_id)
        user.disabled_at = now_naive
        original_password_hash = user.password
        db.add(
            models.PasswordReset(
                user_id=user_id,
                token=hashlib.sha256(raw_reset_token.encode("utf-8")).hexdigest(),
                created_at=now_naive,
                expires_at=now_naive + timedelta(hours=1),
                used=False,
                delivery_status="DELIVERED",
            )
        )
        db.commit()

    forgot = client.post(
        "/api/auth/forgot-password",
        json={"email": "identity-student-disabled-reset@example.com"},
    )
    reset = client.post(
        "/api/auth/reset-password",
        json={
            "token": raw_reset_token,
            "new_password": "synthetic-disabled-new-password",
        },
    )

    assert forgot.status_code == 202
    assert reset.status_code == 400
    with SessionLocal() as db:
        user = db.get(models.User, user_id)
        password_reset = db.query(models.PasswordReset).one()
        assert user.password == original_password_hash
        assert password_reset.used is False


def test_admin_disable_invalidates_reset_and_reenable_cannot_restore_it(client):
    target_user_id = _create_student(suffix="status-reset-invalidation")
    admin_user_id = _create_user(
        suffix="status-reset-invalidation",
        role=models.UserRole.ADMIN,
    )
    raw_reset_token = "synthetic-pre-disable-admin-reset-token"
    reset_id = _create_password_reset(
        user_id=target_user_id,
        raw_token=raw_reset_token,
    )
    with SessionLocal() as db:
        original_password_hash = db.get(models.User, target_user_id).password

    _, admin_csrf = _login(
        client,
        role=models.UserRole.ADMIN,
        suffix="status-reset-invalidation",
    )
    disabled = client.put(
        f"/api/users/{target_user_id}/status",
        json={"disabled": True},
        headers={"X-CSRF-Token": admin_csrf},
    )
    enabled = client.put(
        f"/api/users/{target_user_id}/status",
        json={"disabled": False},
        headers={"X-CSRF-Token": admin_csrf},
    )

    assert disabled.status_code == enabled.status_code == 200
    with SessionLocal() as db:
        invalidated = db.get(models.PasswordReset, reset_id)
        assert invalidated.token is None
        assert invalidated.expires_at is None
        assert invalidated.used is True
        assert invalidated.delivery_status == "FAILED"
        assert db.get(models.User, admin_user_id).disabled_at is None

    client.cookies.clear()
    replay = client.post(
        "/api/auth/reset-password",
        json={
            "token": raw_reset_token,
            "new_password": "synthetic-password-after-reenable",
        },
    )
    assert replay.status_code == 400
    with SessionLocal() as db:
        assert db.get(models.User, target_user_id).password == original_password_hash


def test_operator_disable_invalidates_reset_and_reenable_cannot_restore_it(client):
    account_cli = import_module("manage_accounts")
    user_id = _create_student(suffix="operator-reset-invalidation")
    email = "identity-student-operator-reset-invalidation@example.com"
    operator = "reviewed-security-operator"
    raw_reset_token = "synthetic-pre-disable-operator-reset-token"
    reset_id = _create_password_reset(user_id=user_id, raw_token=raw_reset_token)

    disable_status = account_cli.main(
        ["disable", "--operator", operator],
        session_factory=SessionLocal,
        settings=identity_controls.get_settings(),
        status_executor=_sqlite_account_status_executor,
        stdin=_private_email_input(email),
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )
    enable_status = account_cli.main(
        ["enable", "--operator", operator],
        session_factory=SessionLocal,
        settings=identity_controls.get_settings(),
        status_executor=_sqlite_account_status_executor,
        stdin=_private_email_input(email),
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    assert disable_status == enable_status == 0
    with SessionLocal() as db:
        invalidated = db.get(models.PasswordReset, reset_id)
        assert invalidated.token is None
        assert invalidated.expires_at is None
        assert invalidated.used is True
        assert invalidated.delivery_status == "FAILED"

    replay = client.post(
        "/api/auth/reset-password",
        json={
            "token": raw_reset_token,
            "new_password": "synthetic-operator-password-after-reenable",
        },
    )
    assert replay.status_code == 400


def test_disabled_account_pending_reset_is_not_claimed_or_sent(client, monkeypatch):
    user_id = _create_student(suffix="disabled-pending-reset")
    reset_id = _create_password_reset(
        user_id=user_id,
        raw_token="unused-pending-token",
        delivery_status="PENDING",
    )
    with SessionLocal() as db:
        db.get(models.User, user_id).disabled_at = datetime.now(UTC)
        db.commit()

    deliveries = []
    monkeypatch.setattr(
        main,
        "send_password_reset_email",
        lambda *args: deliveries.append(args) or True,
    )
    main._dispatch_password_reset_emails_once()

    assert deliveries == []
    with SessionLocal() as db:
        reset = db.get(models.PasswordReset, reset_id)
        assert reset.token is None
        assert reset.expires_at is None
        assert reset.used is True
        assert reset.delivery_status == "FAILED"


@pytest.mark.parametrize("stale_delivery_result", [False, True])
def test_stale_password_reset_claim_cannot_complete_after_reclaim(
    client,
    stale_delivery_result,
):
    result_suffix = str(stale_delivery_result).lower()
    user_id = _create_student(suffix=f"stale-reset-claim-{result_suffix}")
    reset_id = _create_password_reset(
        user_id=user_id,
        raw_token="unused-reset-token",
        delivery_status="PENDING",
    )

    first_reset_id, first_email, first_claim = main._claim_password_reset_delivery()
    assert first_reset_id == reset_id
    with SessionLocal() as db:
        reset = db.get(models.PasswordReset, reset_id)
        reset.delivery_attempted_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(
            seconds=main.PASSWORD_RESET_CLAIM_TIMEOUT_SECONDS + 1
        )
        db.commit()

    second_reset_id, second_email, second_claim = main._claim_password_reset_delivery()
    assert (second_reset_id, second_email) == (first_reset_id, first_email)
    assert second_claim != first_claim

    stale_completed = main._complete_password_reset_delivery(
        reset_id,
        first_claim,
        "stale-worker-token",
        stale_delivery_result,
    )
    current_completed = main._complete_password_reset_delivery(
        reset_id,
        second_claim,
        "current-worker-token",
        True,
    )

    assert stale_completed is False
    assert current_completed is True
    with SessionLocal() as db:
        reset = db.get(models.PasswordReset, reset_id)
        assert reset.delivery_status == "DELIVERED"
        assert reset.token == hashlib.sha256(
            b"current-worker-token"
        ).hexdigest()
        assert reset.delivery_claim_digest is None
        persisted = " ".join(str(value) for value in reset.__dict__.values())
        assert first_claim not in persisted
        assert second_claim not in persisted


def test_disabled_account_processing_reset_cannot_be_completed(client):
    user_id = _create_student(suffix="disabled-processing-reset")
    claim_nonce = "synthetic-disabled-processing-claim"
    reset_id = _create_password_reset(
        user_id=user_id,
        raw_token="unused-processing-token",
        delivery_status="PROCESSING",
        delivery_attempted_at=datetime.now(UTC).replace(tzinfo=None),
        delivery_claim_nonce=claim_nonce,
    )
    with SessionLocal() as db:
        db.get(models.User, user_id).disabled_at = datetime.now(UTC)
        db.commit()

    main._complete_password_reset_delivery(
        reset_id,
        claim_nonce,
        "raw-token-that-must-not-be-persisted",
        True,
    )

    with SessionLocal() as db:
        reset = db.get(models.PasswordReset, reset_id)
        assert reset.token is None
        assert reset.expires_at is None
        assert reset.used is True
        assert reset.delivery_status == "FAILED"


@pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="PostgreSQL row-lock integration test",
)
def test_postgres_reset_user_lock_serializes_operator_disable(client):
    del client
    account_cli = import_module("manage_accounts")
    user_id = _create_student(suffix="postgres-reset-disable-race")
    email = "identity-student-postgres-reset-disable-race@example.com"
    raw_reset_token = "synthetic-postgres-reset-disable-race-token"
    reset_id = _create_password_reset(user_id=user_id, raw_token=raw_reset_token)

    reset_db = SessionLocal()
    locked_user = main._lock_usable_password_reset_user(
        reset_db,
        password_reset_id=reset_id,
        raw_token=raw_reset_token,
    )
    assert locked_user is not None

    disable_started = Event()
    disable_finished = Event()

    def disable_account():
        disable_started.set()
        try:
            return account_cli.main(
                [
                    "disable",
                    "--operator",
                    "reviewed-security-operator",
                ],
                session_factory=SessionLocal,
                settings=identity_controls.get_settings(),
                status_executor=_sqlite_account_status_executor,
                stdin=_private_email_input(email),
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )
        finally:
            disable_finished.set()

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(disable_account)
            assert disable_started.wait(timeout=2)
            assert not disable_finished.wait(timeout=0.25)
            reset_db.rollback()
            assert future.result(timeout=5) == 0
    finally:
        reset_db.close()

    with SessionLocal() as db:
        assert db.get(models.User, user_id).disabled_at is not None
        reset = db.get(models.PasswordReset, reset_id)
        assert reset.token is None
        assert reset.used is True
        assert reset.delivery_status == "FAILED"


@pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="PostgreSQL row-lock integration test",
)
def test_postgres_password_change_and_reset_have_one_winner(client, monkeypatch):
    user_id = _create_student(suffix="postgres-change-reset-race")
    raw_reset_token = "synthetic-postgres-change-reset-race-token"
    reset_id = _create_password_reset(user_id=user_id, raw_token=raw_reset_token)
    _, csrf_token = _login(
        client,
        role=models.UserRole.STUDENT,
        suffix="postgres-change-reset-race",
    )

    reset_db = SessionLocal()
    locked_user = main._lock_usable_password_reset_user(
        reset_db,
        password_reset_id=reset_id,
        raw_token=raw_reset_token,
    )
    assert locked_user is not None

    change_hashed = Event()
    change_finished = Event()
    original_hash_password = main.hash_password

    def signaling_hash_password(password):
        result = original_hash_password(password)
        change_hashed.set()
        return result

    monkeypatch.setattr(main, "hash_password", signaling_hash_password)

    def change_password_request():
        try:
            return client.post(
                "/api/auth/change-password",
                json={
                    "current_password": "synthetic-identity-password",
                    "new_password": "synthetic-change-race-password",
                },
                headers={"X-CSRF-Token": csrf_token},
            )
        finally:
            change_finished.set()

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(change_password_request)
            assert change_hashed.wait(timeout=5)
            assert not change_finished.wait(timeout=0.25)

            locked_user.password = hash_password("synthetic-reset-race-password")
            consumed = (
                reset_db.query(models.PasswordReset)
                .filter(
                    models.PasswordReset.id == reset_id,
                    models.PasswordReset.used.is_(False),
                )
                .update({models.PasswordReset.used: True}, synchronize_session=False)
            )
            assert consumed == 1
            identity_controls.revoke_all_sessions(reset_db, user_id=user_id)
            reset_db.commit()

            response = future.result(timeout=5)
    finally:
        reset_db.close()

    assert response.status_code == 409
    with SessionLocal() as db:
        user = db.get(models.User, user_id)
        assert verify_password(
            "synthetic-reset-race-password",
            user.password,
        )
        assert not verify_password(
            "synthetic-change-race-password",
            user.password,
        )
        assert db.get(models.PasswordReset, reset_id).used is True


def test_account_deletion_revokes_sessions_and_clears_browser_cookies(
    client,
    monkeypatch,
):
    user_id = _create_student(suffix="delete-revokes")
    _login(client, role=models.UserRole.STUDENT, suffix="delete-revokes")
    _, csrf = _login(client, role=models.UserRole.STUDENT, suffix="delete-revokes")
    revocation_calls = []
    original_revoke_all = identity_controls.revoke_all_sessions

    def recorded_revoke_all(db, *, user_id, now=None):
        revocation_calls.append(user_id)
        return original_revoke_all(db, user_id=user_id, now=now)

    monkeypatch.setattr(main, "revoke_all_sessions", recorded_revoke_all)
    response = client.delete(
        "/api/user/account?confirm=DELETE",
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 200
    assert revocation_calls == [user_id]
    assert client.cookies.get(main._session_cookie_name()) is None
    assert client.cookies.get(main._csrf_cookie_name()) is None
    with SessionLocal() as db:
        assert db.get(models.User, user_id) is None
        assert db.query(models.BrowserSession).count() == 0


@pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="PostgreSQL row-lock integration test",
)
def test_postgres_account_delete_locks_user_before_session_and_reset_cleanup(
    client,
    monkeypatch,
):
    user_id = _create_student(suffix="postgres-delete-lifecycle")
    _, csrf = _login(
        client,
        role=models.UserRole.STUDENT,
        suffix="postgres-delete-lifecycle",
    )

    dependency_work_started = Event()
    delete_request_started = Event()
    delete_request_finished = Event()
    original_delete_dependencies = main._delete_user_dependencies

    def signaling_delete_dependencies(db, user):
        dependency_work_started.set()
        return original_delete_dependencies(db, user)

    monkeypatch.setattr(
        main,
        "_delete_user_dependencies",
        signaling_delete_dependencies,
    )

    locking_db = SessionLocal()
    locked_user = (
        locking_db.query(models.User)
        .filter(models.User.id == user_id)
        .with_for_update(of=models.User)
        .one()
    )

    def delete_account_request():
        delete_request_started.set()
        try:
            return client.delete(
                "/api/user/account?confirm=DELETE",
                headers={"X-CSRF-Token": csrf},
            )
        finally:
            delete_request_finished.set()

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(delete_account_request)
            assert delete_request_started.wait(timeout=2)
            assert not dependency_work_started.wait(timeout=0.25)
            assert not delete_request_finished.is_set()

            identity_controls.issue_browser_session(
                locking_db,
                user_id=user_id,
                settings=identity_controls.get_settings(),
                expected_password_hash=locked_user.password,
            )
            locking_db.add(
                models.PasswordReset(
                    user_id=user_id,
                    token=None,
                    expires_at=None,
                    used=False,
                    delivery_status="PENDING",
                )
            )
            locking_db.commit()

            response = future.result(timeout=5)
    finally:
        locking_db.close()

    assert response.status_code == 200
    assert dependency_work_started.is_set()
    with SessionLocal() as db:
        assert db.get(models.User, user_id) is None
        assert (
            db.query(models.BrowserSession)
            .filter(models.BrowserSession.user_id == user_id)
            .count()
            == 0
        )
        assert (
            db.query(models.PasswordReset)
            .filter(models.PasswordReset.user_id == user_id)
            .count()
            == 0
        )


def test_operator_cli_creates_and_revokes_digest_only_invitation(client):
    del client
    invitation_cli = import_module("manage_teacher_invitations")
    settings = identity_controls.get_settings()
    email = "operator-invited-teacher@example.com"
    operator = "reviewed-security-operator"
    create_stdout = io.StringIO()
    create_stderr = io.StringIO()

    create_status = invitation_cli.main(
        [
            "create",
            "--expires-hours",
            "12",
            "--operator",
            operator,
        ],
        session_factory=SessionLocal,
        settings=settings,
        command_executor=_sqlite_invitation_command_executor,
        stdin=_private_email_input(email),
        stdout=create_stdout,
        stderr=create_stderr,
    )

    raw_token = create_stdout.getvalue().strip()
    combined_create_output = create_stdout.getvalue() + create_stderr.getvalue()
    assert create_status == 0
    assert len(raw_token) >= 40
    assert create_stdout.getvalue().count(raw_token) == 1
    assert create_stderr.getvalue() == "Invitation created\n"
    assert combined_create_output.count(raw_token) == 1
    assert email not in combined_create_output
    assert operator not in combined_create_output
    with SessionLocal() as db:
        invitation = db.query(models.TeacherInvitation).one()
        persisted_text = " ".join(
            str(value) for value in invitation.__dict__.values()
        )
        assert raw_token not in persisted_text
        assert email not in persisted_text

    revoke_stdout = io.StringIO()
    revoke_stderr = io.StringIO()
    revoke_status = invitation_cli.main(
        ["revoke", "--operator", operator],
        session_factory=SessionLocal,
        settings=settings,
        command_executor=_sqlite_invitation_command_executor,
        stdin=_private_email_input(email),
        stdout=revoke_stdout,
        stderr=revoke_stderr,
    )

    assert revoke_status == 0
    assert revoke_stdout.getvalue() == ""
    assert revoke_stderr.getvalue() == "Invitation revoked\n"
    assert email not in revoke_stderr.getvalue()
    assert operator not in revoke_stderr.getvalue()
    with SessionLocal() as db:
        assert db.query(models.TeacherInvitation).one().revoked_at is not None
        audit_events = db.query(models.OperatorAuditEvent).order_by(
            models.OperatorAuditEvent.id
        ).all()
        assert [event.action for event in audit_events] == [
            "TEACHER_INVITATION_CREATED",
            "TEACHER_INVITATION_REVOKED",
        ]
        assert [event.outcome for event in audit_events] == [
            "SUCCEEDED",
            "SUCCEEDED",
        ]
        assert {event.actor_identifier for event in audit_events} == {operator}
        assert len({event.resource_digest for event in audit_events}) == 1
        assert audit_events[0].resource_digest != (
            db.query(models.TeacherInvitation).one().email_digest
        )
        persisted_audit = " ".join(
            str(value)
            for event in audit_events
            for value in event.__dict__.values()
        )
        assert email not in persisted_audit
        assert raw_token not in persisted_audit


@pytest.mark.parametrize(
    ("module_name", "argv"),
    [
        (
            "manage_teacher_invitations",
            [
                "create",
                "--email",
                "argv-private@example.com",
                "--expires-hours",
                "12",
                "--operator",
                "reviewed-security-operator",
            ],
        ),
        (
            "manage_accounts",
            [
                "disable",
                "--email",
                "argv-private@example.com",
                "--operator",
                "reviewed-security-operator",
            ],
        ),
    ],
)
def test_operator_clis_reject_target_email_in_argv(
    client,
    caplog,
    module_name,
    argv,
):
    del client
    cli = import_module(module_name)
    stdout = io.StringIO()
    stderr = io.StringIO()

    status_code = cli.main(
        argv,
        session_factory=SessionLocal,
        settings=identity_controls.get_settings(),
        stdin=_private_email_input("private-stdin@example.com"),
        stdout=stdout,
        stderr=stderr,
    )

    assert status_code == 2
    assert stdout.getvalue() == ""
    assert "argv-private@example.com" not in stderr.getvalue()
    assert "argv-private@example.com" not in caplog.text
    with SessionLocal() as db:
        assert db.query(models.TeacherInvitation).count() == 0
        assert db.query(models.OperatorAuditEvent).count() == 0


def test_operator_invitation_cli_failures_are_generic_and_secret_free(client):
    del client
    invitation_cli = import_module("manage_teacher_invitations")
    settings = identity_controls.get_settings()
    email = "duplicate-operator-invite@example.com"
    operator = "reviewed-security-operator"
    first_stdout = io.StringIO()
    assert invitation_cli.main(
        ["create", "--expires-hours", "12", "--operator", operator],
        session_factory=SessionLocal,
        settings=settings,
        command_executor=_sqlite_invitation_command_executor,
        stdin=_private_email_input(email),
        stdout=first_stdout,
        stderr=io.StringIO(),
    ) == 0
    first_token = first_stdout.getvalue().strip()

    duplicate_stdout = io.StringIO()
    duplicate_stderr = io.StringIO()
    duplicate_status = invitation_cli.main(
        ["create", "--expires-hours", "12", "--operator", operator],
        session_factory=SessionLocal,
        settings=settings,
        command_executor=_sqlite_invitation_command_executor,
        stdin=_private_email_input(email),
        stdout=duplicate_stdout,
        stderr=duplicate_stderr,
    )
    missing_stdout = io.StringIO()
    missing_stderr = io.StringIO()
    missing_status = invitation_cli.main(
        [
            "revoke",
            "--operator",
            operator,
        ],
        session_factory=SessionLocal,
        settings=settings,
        command_executor=_sqlite_invitation_command_executor,
        stdin=_private_email_input("missing-teacher@example.com"),
        stdout=missing_stdout,
        stderr=missing_stderr,
    )

    assert duplicate_status == 1
    assert duplicate_stdout.getvalue() == ""
    assert duplicate_stderr.getvalue() == "Invitation could not be created\n"
    assert missing_status == 1
    assert missing_stdout.getvalue() == ""
    assert missing_stderr.getvalue() == "Invitation not found\n"
    combined_output = (
        duplicate_stderr.getvalue()
        + missing_stderr.getvalue()
        + duplicate_stdout.getvalue()
        + missing_stdout.getvalue()
    )
    for secret_value in (first_token, email, operator, "missing-teacher@example.com"):
        assert secret_value not in combined_output


def test_operator_cli_rejects_control_character_audit_actor_before_database_work(
    client,
):
    del client
    invitation_cli = import_module("manage_teacher_invitations")
    account_cli = import_module("manage_accounts")
    forged_actor = "reviewed-operator\nSUCCEEDED forged-event"
    invitation_stderr = io.StringIO()
    account_stderr = io.StringIO()

    invitation_status = invitation_cli.main(
        [
            "create",
            "--expires-hours",
            "12",
            "--operator",
            forged_actor,
        ],
        session_factory=SessionLocal,
        settings=identity_controls.get_settings(),
        stdin=_private_email_input("audit-actor@example.com"),
        stdout=io.StringIO(),
        stderr=invitation_stderr,
    )
    account_status = account_cli.main(
        [
            "disable",
            "--operator",
            forged_actor,
        ],
        session_factory=SessionLocal,
        settings=identity_controls.get_settings(),
        stdin=_private_email_input("audit-actor@example.com"),
        stdout=io.StringIO(),
        stderr=account_stderr,
    )

    assert invitation_status == account_status == 2
    assert invitation_stderr.getvalue() == "Invitation command rejected\n"
    assert account_stderr.getvalue() == "Account command rejected\n"
    assert forged_actor not in invitation_stderr.getvalue() + account_stderr.getvalue()
    with SessionLocal() as db:
        assert db.query(models.TeacherInvitation).count() == 0
        assert db.query(models.OperatorAuditEvent).count() == 0


def test_operator_account_cli_disable_and_enable_is_transactional(client):
    del client
    account_cli = import_module("manage_accounts")
    user_id = _create_student(suffix="operator-status")
    with SessionLocal() as db:
        for _ in range(2):
            identity_controls.issue_browser_session(
                db,
                user_id=user_id,
                settings=identity_controls.get_settings(),
            )
        db.commit()
    email = "identity-student-operator-status@example.com"
    operator = "reviewed-security-operator"

    disable_stdout = io.StringIO()
    disable_stderr = io.StringIO()
    disable_status = account_cli.main(
        ["disable", "--operator", operator],
        session_factory=SessionLocal,
        settings=identity_controls.get_settings(),
        status_executor=_sqlite_account_status_executor,
        stdin=_private_email_input(email),
        stdout=disable_stdout,
        stderr=disable_stderr,
    )

    assert disable_status == 0
    assert disable_stdout.getvalue() == ""
    assert disable_stderr.getvalue() == "Account disabled\n"
    assert email not in disable_stderr.getvalue()
    assert operator not in disable_stderr.getvalue()
    with SessionLocal() as db:
        user = db.get(models.User, user_id)
        assert user.disabled_at is not None
        sessions = db.query(models.BrowserSession).all()
        assert len(sessions) == 2
        assert all(session.revoked_at is not None for session in sessions)

    enable_stdout = io.StringIO()
    enable_stderr = io.StringIO()
    enable_status = account_cli.main(
        ["enable", "--operator", operator],
        session_factory=SessionLocal,
        settings=identity_controls.get_settings(),
        status_executor=_sqlite_account_status_executor,
        stdin=_private_email_input(email),
        stdout=enable_stdout,
        stderr=enable_stderr,
    )

    assert enable_status == 0
    assert enable_stdout.getvalue() == ""
    assert enable_stderr.getvalue() == "Account enabled\n"
    with SessionLocal() as db:
        assert db.get(models.User, user_id).disabled_at is None
        assert db.query(models.BrowserSession).count() == 2
        audit_events = db.query(models.OperatorAuditEvent).order_by(
            models.OperatorAuditEvent.id
        ).all()
        assert [event.action for event in audit_events] == [
            "ACCOUNT_DISABLED",
            "ACCOUNT_ENABLED",
        ]
        assert [event.outcome for event in audit_events] == [
            "SUCCEEDED",
            "SUCCEEDED",
        ]
        assert {event.actor_identifier for event in audit_events} == {operator}
        assert len({event.resource_digest for event in audit_events}) == 1
        assert email not in " ".join(
            str(value)
            for event in audit_events
            for value in event.__dict__.values()
        )


def test_account_operator_reads_and_updates_only_required_user_columns(client):
    del client
    account_cli = import_module("manage_accounts")
    _create_student(suffix="operator-column-privileges")
    statements: list[str] = []

    def capture_statement(
        connection,
        cursor,
        statement,
        parameters,
        context,
        executemany,
    ):
        del connection, cursor, parameters, context, executemany
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture_statement)
    try:
        status = account_cli.main(
            ["disable", "--operator", "reviewed-security-operator"],
            session_factory=SessionLocal,
            settings=identity_controls.get_settings(),
            status_executor=_sqlite_account_status_executor,
            stdin=_private_email_input(
                "identity-student-operator-column-privileges@example.com"
            ),
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        )
    finally:
        event.remove(engine, "before_cursor_execute", capture_statement)

    assert status == 0
    user_selects = [
        " ".join(statement.casefold().split())
        for statement in statements
        if statement.lstrip().casefold().startswith("select")
        and " from users" in " ".join(statement.casefold().split())
    ]
    assert len(user_selects) == 1
    selected_columns = user_selects[0].split(" from users", maxsplit=1)[0]
    assert "users.id" in selected_columns
    assert "users.email" in selected_columns
    assert "users.disabled_at" in selected_columns
    for private_or_unneeded_column in (
        "users.password",
        "users.username",
        "users.user_type",
        "users.avatar",
        "users.bio",
        "users.grade",
        "users.school",
        "users.provider",
        "users.provider_subject",
    ):
        assert private_or_unneeded_column not in selected_columns

    user_updates = [
        " ".join(statement.casefold().split())
        for statement in statements
        if statement.lstrip().casefold().startswith("update users set")
    ]
    assert len(user_updates) == 1
    set_clause = user_updates[0].split(" set ", maxsplit=1)[1].split(
        " where ", maxsplit=1
    )[0]
    assert set_clause.startswith("disabled_at")
    assert "," not in set_clause


def test_operator_account_cli_missing_user_output_reveals_no_identifiers(client):
    del client
    account_cli = import_module("manage_accounts")
    email = "missing-operator-account@example.com"
    operator = "reviewed-security-operator"
    stdout = io.StringIO()
    stderr = io.StringIO()

    status_code = account_cli.main(
        ["disable", "--operator", operator],
        session_factory=SessionLocal,
        settings=identity_controls.get_settings(),
        status_executor=_sqlite_account_status_executor,
        stdin=_private_email_input(email),
        stdout=stdout,
        stderr=stderr,
    )

    assert status_code == 1
    assert stdout.getvalue() == ""
    assert stderr.getvalue() == "Account not found\n"
    assert email not in stderr.getvalue()
    assert operator not in stderr.getvalue()
    with SessionLocal() as db:
        audit_event = db.query(models.OperatorAuditEvent).one()
        assert audit_event.actor_identifier == operator
        assert audit_event.action == "ACCOUNT_DISABLED"
        assert audit_event.outcome == "NOT_FOUND"
        assert email not in " ".join(
            str(value) for value in audit_event.__dict__.values()
        )


def test_operator_audit_failure_rolls_back_privileged_state_change(
    client,
    monkeypatch,
):
    del client
    account_cli = import_module("manage_accounts")
    invitation_cli = import_module("manage_teacher_invitations")
    user_id = _create_student(suffix="audit-failure")
    raw_reset_token = "synthetic-operator-audit-failure-reset-token"
    reset_id = _create_password_reset(
        user_id=user_id,
        raw_token=raw_reset_token,
    )
    settings = identity_controls.get_settings()
    invitation_email = "audit-failure-invitation@example.com"
    with SessionLocal() as db:
        identity_controls.create_teacher_invitation(
            db,
            email=invitation_email,
            created_by="reviewed-security-operator",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            settings=settings,
        )
        db.commit()

    def unavailable_audit(*args, **kwargs):
        del args, kwargs
        raise SQLAlchemyError("synthetic audit storage failure")

    monkeypatch.setattr(
        identity_controls,
        "record_operator_audit_event",
        unavailable_audit,
    )
    account_status = account_cli.main(
        [
            "disable",
            "--operator",
            "reviewed-security-operator",
        ],
        session_factory=SessionLocal,
        settings=settings,
        status_executor=_sqlite_account_status_executor,
        stdin=_private_email_input(
            "identity-student-audit-failure@example.com"
        ),
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )
    invitation_status = invitation_cli.main(
        [
            "revoke",
            "--operator",
            "reviewed-security-operator",
        ],
        session_factory=SessionLocal,
        settings=settings,
        command_executor=_sqlite_invitation_command_executor,
        stdin=_private_email_input(invitation_email),
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    assert account_status == 1
    assert invitation_status == 1
    with SessionLocal() as db:
        assert db.get(models.User, user_id).disabled_at is None
        password_reset = db.get(models.PasswordReset, reset_id)
        assert password_reset.token == hashlib.sha256(
            raw_reset_token.encode("utf-8")
        ).hexdigest()
        assert password_reset.used is False
        assert password_reset.delivery_status == "DELIVERED"
        assert db.query(models.TeacherInvitation).one().revoked_at is None
        assert db.query(models.OperatorAuditEvent).count() == 0


def test_operator_cli_database_failures_are_generic_and_secret_free(client):
    del client
    invitation_cli = import_module("manage_teacher_invitations")
    account_cli = import_module("manage_accounts")
    private_error = "postgresql://private-user:private-password@database.internal"

    def unavailable_database():
        raise SQLAlchemyError(private_error)

    invitation_stdout = io.StringIO()
    invitation_stderr = io.StringIO()
    invitation_status = invitation_cli.main(
        [
            "create",
            "--expires-hours",
            "12",
            "--operator",
            "reviewed-security-operator",
        ],
        session_factory=unavailable_database,
        settings=identity_controls.get_settings(),
        stdin=_private_email_input("database-failure@example.com"),
        stdout=invitation_stdout,
        stderr=invitation_stderr,
    )
    account_stdout = io.StringIO()
    account_stderr = io.StringIO()
    account_status = account_cli.main(
        [
            "disable",
            "--operator",
            "reviewed-security-operator",
        ],
        session_factory=unavailable_database,
        settings=identity_controls.get_settings(),
        stdin=_private_email_input("database-failure@example.com"),
        stdout=account_stdout,
        stderr=account_stderr,
    )

    assert invitation_status == 1
    assert invitation_stdout.getvalue() == ""
    assert invitation_stderr.getvalue() == "Invitation could not be created\n"
    assert account_status == 1
    assert account_stdout.getvalue() == ""
    assert account_stderr.getvalue() == "Account could not be updated\n"
    assert private_error not in invitation_stderr.getvalue()
    assert private_error not in account_stderr.getvalue()


def test_no_public_invitation_or_operator_account_routes_exist():
    route_paths = {route.path.casefold() for route in main.app.routes}
    assert not any("invite" in path or "invitation" in path for path in route_paths)
    assert not any("operator" in path for path in route_paths)
