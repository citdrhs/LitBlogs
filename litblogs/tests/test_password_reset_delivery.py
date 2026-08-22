from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from pydantic import ValidationError

DATABASE_URL = (
    "postgresql+psycopg2://litblogs_runtime:R4nd0m-worker-db-passphrase!"
    "@database.school.org:5432/litblogs?sslmode=verify-full&"
    "sslrootcert=%2Fetc%2Flitblogs%2Fpostgres-root-ca.pem"
)


def _worker_settings(**overrides):
    import password_reset_delivery

    values = {
        "database_url": DATABASE_URL,
        "frontend_url": "https://litblogs.school.org/",
        "email_host": "smtp.school.org",
        "email_port": 587,
        "email_smtp_timeout_seconds": 5,
        "email_username": "litblogs-reset",
        "email_password": "R4nd0m-smtp-passphrase!",
        "email_from": "no-reply@school.org",
        "password_reset_claim_timeout_seconds": 120,
    }
    values.update(overrides)
    return password_reset_delivery.PasswordResetWorkerSettings(**values)


def test_worker_settings_are_minimal_and_normalize_the_frontend_origin():
    import password_reset_delivery

    settings = _worker_settings()

    assert settings.frontend_url == "https://litblogs.school.org"
    model_fields = password_reset_delivery.PasswordResetWorkerSettings.model_fields
    assert "upload_root" not in model_fields
    assert "secret_key" not in model_fields
    assert "upload_scanner_host" not in model_fields


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("database_url", "sqlite:///litblogs.db"),
        (
            "database_url",
            DATABASE_URL.replace("litblogs_runtime", "overprivileged_role"),
        ),
        (
            "database_url",
            DATABASE_URL.replace("postgresql+psycopg2", "postgresql+psycopg"),
        ),
        ("frontend_url", "http://litblogs.school.org"),
        ("email_host", "localhost"),
        ("email_password", "short"),
    ],
)
def test_worker_settings_fail_closed_for_unsafe_delivery_inputs(field, value):
    with pytest.raises(ValidationError):
        _worker_settings(**{field: value})


@pytest.mark.parametrize("driver", ["postgresql+psycopg", "postgresql+asyncpg"])
def test_shared_production_database_validator_rejects_unshipped_drivers(driver):
    from config import _is_verified_postgresql_url

    candidate = DATABASE_URL.replace("postgresql+psycopg2", driver)

    assert _is_verified_postgresql_url(candidate) is False


def test_worker_engine_options_preserve_all_bounded_database_controls():
    import password_reset_delivery

    settings = _worker_settings(
        db_pool_size=2,
        db_max_overflow=1,
        db_pool_timeout_seconds=7,
        db_pool_recycle_seconds=600,
        db_connect_timeout_seconds=4,
        db_statement_timeout_ms=12_000,
        db_lock_timeout_ms=3_000,
    )

    options = password_reset_delivery.worker_engine_options(settings)

    assert options == {
        "pool_pre_ping": True,
        "pool_size": 2,
        "max_overflow": 1,
        "pool_timeout": 7,
        "pool_recycle": 600,
        "connect_args": {
            "connect_timeout": 4,
            "application_name": "litblogs-password-reset",
            "options": "-c statement_timeout=12000 -c lock_timeout=3000",
        },
    }


def test_email_delivery_settings_repr_never_reflects_the_smtp_password():
    import password_reset_delivery

    private_password = "smtp-private-password-material"
    settings = password_reset_delivery.PasswordResetEmailSettings(
        frontend_url="https://litblogs.school.org",
        email_host="smtp.school.org",
        email_port=587,
        email_smtp_timeout_seconds=5,
        email_username="litblogs-reset",
        email_password=private_password,
        email_from="no-reply@school.org",
    )

    assert private_password not in repr(settings)


class _Result:
    def __init__(self, scalar=None):
        self._scalar = scalar

    def scalar_one(self):
        return self._scalar


class _Connection:
    def __init__(self, revision):
        self.revision = revision
        self.statements = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.closed = True

    def execute(self, statement):
        rendered = " ".join(str(statement).split())
        self.statements.append(rendered)
        if "version_num" in rendered:
            return _Result(self.revision)
        return _Result()


class _Engine:
    def __init__(self, revision):
        self.connection = _Connection(revision)
        self.dialect = SimpleNamespace(name="postgresql")

    def connect(self):
        return self.connection


def test_worker_readiness_requires_current_revision_and_exact_runtime_identity(
    monkeypatch,
):
    import password_reset_delivery

    engine = _Engine(password_reset_delivery.EXPECTED_ALEMBIC_HEAD)
    verified = []
    monkeypatch.setattr(
        password_reset_delivery,
        "verify_runtime_database_identity",
        verified.append,
    )

    password_reset_delivery.check_password_reset_database_readiness(engine)

    assert verified == [engine.connection]
    assert engine.connection.closed is True
    assert any(
        "FROM public.alembic_version" in statement
        for statement in engine.connection.statements
    )


def test_worker_readiness_rejects_a_stale_revision_before_delivery(monkeypatch):
    import password_reset_delivery

    engine = _Engine("stale")
    verified = []
    monkeypatch.setattr(
        password_reset_delivery,
        "verify_runtime_database_identity",
        verified.append,
    )

    with pytest.raises(RuntimeError, match="migration revision"):
        password_reset_delivery.check_password_reset_database_readiness(engine)

    assert verified == []


def test_worker_expected_revision_tracks_the_repository_head():
    import password_reset_delivery

    config = Config(str(password_reset_delivery.APP_DIRECTORY / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)

    assert password_reset_delivery.EXPECTED_ALEMBIC_HEAD == scripts.get_current_head()


def test_dispatch_batch_is_bounded_and_uses_claim_capability_tokens():
    import password_reset_delivery

    claims = iter(
        [
            (11, "first@school.org", "first-claim"),
            (12, "second@school.org", "second-claim"),
            (13, "must-not-run@school.org", "third-claim"),
        ]
    )
    sent = []
    completed = []

    outcome = password_reset_delivery.dispatch_password_reset_batch(
        batch_size=2,
        claim=lambda: next(claims),
        send=lambda email, token: sent.append((email, token)) or True,
        complete=lambda *args: completed.append(args) or True,
    )

    assert outcome is password_reset_delivery.PasswordResetDispatchOutcome.COMPLETED
    assert [email for email, _token in sent] == [
        "first@school.org",
        "second@school.org",
    ]
    assert [item[:2] for item in completed] == [
        (11, "first-claim"),
        (12, "second-claim"),
    ]
    assert all(raw_token for _email, raw_token in sent)
    assert [item[2] for item in completed] == [token for _email, token in sent]


class _FailingSession:
    def __init__(self, private_detail: str):
        self.private_detail = private_detail
        self.rollbacks = 0
        self.closed = False

    def query(self, *_args):
        raise RuntimeError(self.private_detail)

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


class _CompletionQuery:
    def __init__(self, result):
        self.result = result

    def join(self, *_args, **_kwargs):
        return self

    def filter(self, *_args, **_kwargs):
        return self

    def with_for_update(self, *_args, **_kwargs):
        return self

    def first(self):
        return self.result


class _CompletionSession:
    def __init__(self, result):
        self.result = result
        self.rollbacks = 0
        self.commits = 0
        self.closed = False

    def query(self, *_args):
        return _CompletionQuery(self.result)

    def rollback(self):
        self.rollbacks += 1

    def commit(self):
        self.commits += 1

    def close(self):
        self.closed = True


def test_claim_database_error_raises_sanitized_operational_failure():
    import password_reset_delivery

    private_detail = "private-db-password-and-reset-recipient"
    session = _FailingSession(private_detail)

    with pytest.raises(
        password_reset_delivery.PasswordResetOperationalError
    ) as captured:
        password_reset_delivery.claim_password_reset_delivery(
            lambda: session,
            claim_timeout_seconds=120,
        )

    assert private_detail not in str(captured.value)
    assert session.rollbacks == 1
    assert session.closed is True


def test_completion_database_error_raises_sanitized_operational_failure():
    import password_reset_delivery

    private_detail = "private-db-password-and-claim-nonce"
    session = _FailingSession(private_detail)

    with pytest.raises(
        password_reset_delivery.PasswordResetOperationalError
    ) as captured:
        password_reset_delivery.complete_password_reset_delivery_outcome(
            lambda: session,
            reset_id=17,
            claim_nonce="private-claim",
            raw_token="private-token",
            delivered=True,
        )

    assert private_detail not in str(captured.value)
    assert session.rollbacks == 1
    assert session.closed is True


def test_completion_reports_claim_lost_without_committing():
    import password_reset_delivery

    session = _CompletionSession(None)

    outcome = password_reset_delivery.complete_password_reset_delivery_outcome(
        lambda: session,
        reset_id=18,
        claim_nonce="lost-claim",
        raw_token="unused-token",
        delivered=True,
    )

    assert outcome is password_reset_delivery.PasswordResetCompletionOutcome.CLAIM_LOST
    assert session.rollbacks == 1
    assert session.commits == 0
    assert session.closed is True


def test_completion_reports_disabled_account_race_after_invalidation(monkeypatch):
    import password_reset_delivery

    user = SimpleNamespace(id=23, disabled_at=datetime.now(UTC))
    session = _CompletionSession((SimpleNamespace(id=19), user))
    invalidated = []
    monkeypatch.setattr(
        password_reset_delivery,
        "invalidate_password_reset_requests",
        lambda db, *, user_id: invalidated.append((db, user_id)),
    )

    outcome = password_reset_delivery.complete_password_reset_delivery_outcome(
        lambda: session,
        reset_id=19,
        claim_nonce="disabled-claim",
        raw_token="unused-token",
        delivered=True,
    )

    assert outcome is (
        password_reset_delivery.PasswordResetCompletionOutcome.ACCOUNT_DISABLED
    )
    assert invalidated == [(session, 23)]
    assert session.commits == 1
    assert session.closed is True


def test_dispatch_empty_queue_is_an_explicit_success_without_work():
    import password_reset_delivery

    outcome = password_reset_delivery.dispatch_password_reset_batch(
        batch_size=1,
        claim=lambda: None,
        send=lambda *_args: pytest.fail("empty queue must not send"),
        complete=lambda *_args: pytest.fail("empty queue must not complete"),
    )

    assert outcome is password_reset_delivery.PasswordResetDispatchOutcome.EMPTY_QUEUE


def test_dispatch_smtp_failure_persists_failed_then_reports_failure():
    import password_reset_delivery

    completions = []

    outcome = password_reset_delivery.dispatch_password_reset_batch(
        batch_size=1,
        claim=lambda: (20, "student@school.org", "smtp-failure-claim"),
        send=lambda _email, _token: False,
        complete=lambda *args: completions.append(args)
        or password_reset_delivery.PasswordResetCompletionOutcome.COMPLETED,
    )

    assert outcome is password_reset_delivery.PasswordResetDispatchOutcome.FAILED
    assert len(completions) == 1
    assert completions[0][3] is False


@pytest.mark.parametrize(
    "completion_outcome",
    ["CLAIM_LOST", "ACCOUNT_DISABLED"],
)
def test_dispatch_never_reports_success_after_sent_completion_race(
    completion_outcome,
):
    import password_reset_delivery

    typed_completion = getattr(
        password_reset_delivery.PasswordResetCompletionOutcome,
        completion_outcome,
    )

    outcome = password_reset_delivery.dispatch_password_reset_batch(
        batch_size=1,
        claim=lambda: (21, "student@school.org", "completion-race-claim"),
        send=lambda _email, _token: True,
        complete=lambda *_args: typed_completion,
    )

    assert outcome is password_reset_delivery.PasswordResetDispatchOutcome.FAILED
