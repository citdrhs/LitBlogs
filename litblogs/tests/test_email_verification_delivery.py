from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import models

FIXED_NOW = datetime(2026, 8, 31, 12, 0, 0)


@pytest.fixture
def verification_sessions(tmp_path):
    database_path = tmp_path / "email-verification.db"
    engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    models.User.__table__.create(engine)
    models.EmailVerification.__table__.create(engine)
    factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
        expire_on_commit=False,
    )
    try:
        yield factory
    finally:
        engine.dispose()


def _create_verification(
    session_factory,
    suffix: str,
    *,
    status: str = "PENDING",
    created_at: datetime = FIXED_NOW,
    attempted_at: datetime | None = None,
    disabled_at: datetime | None = None,
    verified_at: datetime | None = None,
    token_digest: str | None = None,
    claim_digest: str | None = None,
) -> tuple[int, int]:
    db = session_factory()
    try:
        user = models.User(
            username=f"verification-{suffix}",
            email=f"verification-{suffix}@school.org",
            password="stored-password-hash",
            role=models.UserRole.STUDENT,
            disabled_at=disabled_at,
            email_verified_at=verified_at,
        )
        db.add(user)
        db.flush()
        verification = models.EmailVerification(
            user_id=user.id,
            token_digest=token_digest,
            created_at=created_at,
            expires_at=None,
            delivery_status=status,
            delivery_attempted_at=attempted_at,
            delivery_claim_digest=claim_digest,
        )
        db.add(verification)
        db.commit()
        return user.id, verification.id
    finally:
        db.close()


def _load_verification(session_factory, verification_id: int):
    db = session_factory()
    try:
        return db.get(models.EmailVerification, verification_id)
    finally:
        db.close()


def test_verification_token_and_claim_digests_are_domain_separated():
    import email_verification_delivery
    import password_reset_delivery

    raw_token = "same-private-token-material"

    assert email_verification_delivery.email_verification_token_digest(
        raw_token
    ) == hashlib.sha256(
        f"litblogs-email-verification-v1:{raw_token}".encode("utf-8")
    ).hexdigest()
    assert email_verification_delivery.email_verification_token_digest(
        raw_token
    ) != password_reset_delivery.password_reset_token_digest(raw_token)
    assert email_verification_delivery.email_verification_claim_digest(
        raw_token
    ) not in {
        email_verification_delivery.email_verification_token_digest(raw_token),
        password_reset_delivery.password_reset_claim_digest(raw_token),
    }


def test_verification_constants_keep_separate_lifetime_and_resend_policy():
    import email_verification_delivery

    assert email_verification_delivery.EMAIL_VERIFICATION_LIFETIME == timedelta(
        hours=24
    )
    assert email_verification_delivery.EMAIL_VERIFICATION_RESEND_COOLDOWN == timedelta(
        minutes=5
    )
    assert {
        email_verification_delivery.EMAIL_VERIFICATION_PENDING,
        email_verification_delivery.EMAIL_VERIFICATION_PROCESSING,
        email_verification_delivery.EMAIL_VERIFICATION_DELIVERED,
        email_verification_delivery.EMAIL_VERIFICATION_FAILED,
    } == {"PENDING", "PROCESSING", "DELIVERED", "FAILED"}


def test_verification_email_uses_fragment_link_and_separate_template(monkeypatch):
    import auth_email_delivery
    import email_verification_delivery

    captured = {}

    def capture_message(settings, recipient, message):
        captured.update(
            settings=settings,
            recipient=recipient,
            message=message.as_string(),
        )
        return True

    monkeypatch.setattr(
        auth_email_delivery,
        "send_smtp_message",
        capture_message,
    )
    settings = auth_email_delivery.AuthEmailSettings(
        frontend_url="https://litblogs.school.org",
        email_host="smtp.school.org",
        email_port=587,
        email_smtp_timeout_seconds=5,
        email_username="litblogs-reset",
        email_password="private-smtp-password",
        email_from="no-reply@school.org",
    )

    assert email_verification_delivery.send_email_verification_email(
        settings,
        "student@school.org",
        "raw-fragment-token",
    ) is True

    message = captured["message"]
    assert captured["recipient"] == "student@school.org"
    assert "Subject: Verify Your LitBlog Email" in message
    assert "/verify-email#token=raw-fragment-token" in message
    assert "/verify-email?token=" not in message
    assert "Reset Your LitBlog Password" not in message


def test_only_one_concurrent_worker_claims_a_verification(
    verification_sessions,
    monkeypatch,
):
    import email_verification_delivery

    _user_id, verification_id = _create_verification(
        verification_sessions,
        "concurrent",
    )
    monkeypatch.setattr(email_verification_delivery, "_utc_now_naive", lambda: FIXED_NOW)
    start = Barrier(2)

    def claim_once():
        start.wait()
        return email_verification_delivery.claim_email_verification_delivery(
            verification_sessions,
            claim_timeout_seconds=120,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: claim_once(), range(2)))

    claims = [result for result in results if result is not None]
    assert len(claims) == 1
    assert claims[0][0] == verification_id
    assert sum(result is None for result in results) == 1
    stored = _load_verification(verification_sessions, verification_id)
    assert stored.delivery_status == email_verification_delivery.EMAIL_VERIFICATION_PROCESSING
    assert stored.delivery_attempted_at == FIXED_NOW
    assert stored.delivery_claim_digest == (
        email_verification_delivery.email_verification_claim_digest(claims[0][2])
    )


def test_fresh_processing_claim_waits_but_stale_120_second_claim_is_recovered(
    verification_sessions,
    monkeypatch,
):
    import email_verification_delivery

    _user_id, verification_id = _create_verification(
        verification_sessions,
        "stale",
        status="PROCESSING",
        attempted_at=FIXED_NOW - timedelta(seconds=119),
        claim_digest="a" * 64,
    )
    monkeypatch.setattr(email_verification_delivery, "_utc_now_naive", lambda: FIXED_NOW)

    assert email_verification_delivery.claim_email_verification_delivery(
        verification_sessions,
        claim_timeout_seconds=120,
    ) is None

    db = verification_sessions()
    try:
        stored = db.get(models.EmailVerification, verification_id)
        stored.delivery_attempted_at = FIXED_NOW - timedelta(seconds=121)
        db.commit()
    finally:
        db.close()

    recovered = email_verification_delivery.claim_email_verification_delivery(
        verification_sessions,
        claim_timeout_seconds=120,
    )
    assert recovered is not None
    assert recovered[0] == verification_id
    assert recovered[2]


def test_claim_scan_is_ordered_and_bounded_to_25_candidates(
    verification_sessions,
    monkeypatch,
):
    import email_verification_delivery

    monkeypatch.setattr(email_verification_delivery, "_utc_now_naive", lambda: FIXED_NOW)
    for index in range(25):
        _create_verification(
            verification_sessions,
            f"ineligible-{index:02d}",
            created_at=FIXED_NOW + timedelta(seconds=index),
            verified_at=FIXED_NOW,
        )
    _user_id, eligible_id = _create_verification(
        verification_sessions,
        "eligible-26",
        created_at=FIXED_NOW + timedelta(seconds=25),
    )

    first_scan = email_verification_delivery.claim_email_verification_delivery(
        verification_sessions,
        claim_timeout_seconds=120,
    )
    second_scan = email_verification_delivery.claim_email_verification_delivery(
        verification_sessions,
        claim_timeout_seconds=120,
    )

    assert first_scan is None
    assert second_scan is not None
    assert second_scan[0] == eligible_id


def test_delivery_token_is_generated_only_after_a_successful_claim(monkeypatch):
    import auth_email_delivery
    import email_verification_delivery

    generated = []
    monkeypatch.setattr(
        auth_email_delivery.secrets,
        "token_urlsafe",
        lambda size: generated.append(size) or "generated-after-claim",
    )

    empty = email_verification_delivery.dispatch_email_verification_batch(
        batch_size=1,
        claim=lambda: None,
        send=lambda *_args: pytest.fail("empty queue must not send"),
        complete=lambda *_args: pytest.fail("empty queue must not complete"),
    )
    assert empty is email_verification_delivery.EmailVerificationDispatchOutcome.EMPTY_QUEUE
    assert generated == []

    completed = []
    delivered = email_verification_delivery.dispatch_email_verification_batch(
        batch_size=1,
        claim=lambda: (9, "student@school.org", "claim-capability"),
        send=lambda _email, token: token == "generated-after-claim",
        complete=lambda *args: completed.append(args)
        or email_verification_delivery.EmailVerificationCompletionOutcome.COMPLETED,
    )
    assert delivered is email_verification_delivery.EmailVerificationDispatchOutcome.COMPLETED
    assert generated == [32]
    assert completed == [
        (9, "claim-capability", "generated-after-claim", True)
    ]


def test_successful_completion_persists_only_digest_and_24_hour_expiry(
    verification_sessions,
    monkeypatch,
):
    import email_verification_delivery

    _user_id, verification_id = _create_verification(
        verification_sessions,
        "success",
    )
    monkeypatch.setattr(email_verification_delivery, "_utc_now_naive", lambda: FIXED_NOW)
    claim = email_verification_delivery.claim_email_verification_delivery(
        verification_sessions,
        claim_timeout_seconds=120,
    )
    assert claim is not None
    raw_token = "raw-token-must-never-be-stored"

    outcome = email_verification_delivery.complete_email_verification_delivery_outcome(
        verification_sessions,
        verification_id=verification_id,
        claim_nonce=claim[2],
        raw_token=raw_token,
        delivered=True,
    )

    assert outcome is email_verification_delivery.EmailVerificationCompletionOutcome.COMPLETED
    stored = _load_verification(verification_sessions, verification_id)
    assert stored.token_digest == (
        email_verification_delivery.email_verification_token_digest(raw_token)
    )
    assert stored.token_digest != raw_token
    assert stored.expires_at == FIXED_NOW + timedelta(hours=24)
    assert stored.delivery_status == email_verification_delivery.EMAIL_VERIFICATION_DELIVERED
    assert stored.delivery_claim_digest is None


def test_failed_delivery_clears_token_and_expiry(
    verification_sessions,
    monkeypatch,
):
    import email_verification_delivery

    _user_id, verification_id = _create_verification(
        verification_sessions,
        "failed",
        token_digest="b" * 64,
    )
    monkeypatch.setattr(email_verification_delivery, "_utc_now_naive", lambda: FIXED_NOW)
    claim = email_verification_delivery.claim_email_verification_delivery(
        verification_sessions,
        claim_timeout_seconds=120,
    )
    assert claim is not None

    outcome = email_verification_delivery.complete_email_verification_delivery_outcome(
        verification_sessions,
        verification_id=verification_id,
        claim_nonce=claim[2],
        raw_token="unused-raw-token",
        delivered=False,
    )

    assert outcome is email_verification_delivery.EmailVerificationCompletionOutcome.COMPLETED
    stored = _load_verification(verification_sessions, verification_id)
    assert stored.token_digest is None
    assert stored.expires_at is None
    assert stored.delivery_status == email_verification_delivery.EMAIL_VERIFICATION_FAILED
    assert stored.delivery_claim_digest is None


@pytest.mark.parametrize(
    ("disabled_at", "verified_at"),
    [
        (FIXED_NOW, None),
        (None, FIXED_NOW),
    ],
)
def test_disabled_or_already_verified_account_is_invalidated_without_send(
    verification_sessions,
    monkeypatch,
    disabled_at,
    verified_at,
):
    import email_verification_delivery

    _user_id, verification_id = _create_verification(
        verification_sessions,
        f"ineligible-{bool(disabled_at)}-{bool(verified_at)}",
        disabled_at=disabled_at,
        verified_at=verified_at,
        token_digest="c" * 64,
    )
    monkeypatch.setattr(email_verification_delivery, "_utc_now_naive", lambda: FIXED_NOW)
    sends = []

    outcome = email_verification_delivery.dispatch_email_verification_batch(
        batch_size=1,
        claim=lambda: email_verification_delivery.claim_email_verification_delivery(
            verification_sessions,
            claim_timeout_seconds=120,
        ),
        send=lambda *args: sends.append(args) or True,
        complete=lambda *_args: pytest.fail("ineligible account must not complete"),
    )

    assert outcome is email_verification_delivery.EmailVerificationDispatchOutcome.EMPTY_QUEUE
    assert sends == []
    stored = _load_verification(verification_sessions, verification_id)
    assert stored.token_digest is None
    assert stored.expires_at is None
    assert stored.delivery_status == email_verification_delivery.EMAIL_VERIFICATION_FAILED
    assert stored.delivery_attempted_at == FIXED_NOW
    assert stored.delivery_claim_digest is None


def test_lost_or_reclaimed_claim_cannot_overwrite_new_owner(
    verification_sessions,
    monkeypatch,
):
    import email_verification_delivery

    _user_id, verification_id = _create_verification(
        verification_sessions,
        "lost-claim",
    )
    monkeypatch.setattr(email_verification_delivery, "_utc_now_naive", lambda: FIXED_NOW)
    original_claim = email_verification_delivery.claim_email_verification_delivery(
        verification_sessions,
        claim_timeout_seconds=120,
    )
    assert original_claim is not None
    replacement_claim = "replacement-claim-capability"
    replacement_digest = email_verification_delivery.email_verification_claim_digest(
        replacement_claim
    )
    db = verification_sessions()
    try:
        stored = db.get(models.EmailVerification, verification_id)
        stored.delivery_claim_digest = replacement_digest
        stored.delivery_attempted_at = FIXED_NOW + timedelta(seconds=1)
        db.commit()
    finally:
        db.close()

    outcome = email_verification_delivery.complete_email_verification_delivery_outcome(
        verification_sessions,
        verification_id=verification_id,
        claim_nonce=original_claim[2],
        raw_token="old-owner-token",
        delivered=True,
    )

    assert outcome is email_verification_delivery.EmailVerificationCompletionOutcome.CLAIM_LOST
    stored = _load_verification(verification_sessions, verification_id)
    assert stored.delivery_claim_digest == replacement_digest
    assert stored.token_digest is None
    assert stored.delivery_status == email_verification_delivery.EMAIL_VERIFICATION_PROCESSING


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


def test_database_and_dispatch_failures_never_reflect_private_values(capsys):
    import email_verification_delivery

    private_detail = (
        "id=77 email=student@school.org token=raw-token "
        "link=https://litblogs.school.org/verify-email#token=raw-token "
        "nonce=claim-capability password=smtp-secret provider=relay-detail"
    )
    session = _FailingSession(private_detail)

    with pytest.raises(
        email_verification_delivery.EmailVerificationOperationalError
    ) as captured:
        email_verification_delivery.claim_email_verification_delivery(
            lambda: session,
            claim_timeout_seconds=120,
        )

    rendered = f"{captured.value!s} {captured.value!r}"
    assert private_detail not in rendered
    for private_value in (
        "77",
        "student@school.org",
        "raw-token",
        "claim-capability",
        "smtp-secret",
        "relay-detail",
    ):
        assert private_value not in rendered
    assert session.rollbacks == 1
    assert session.closed is True
    captured_output = capsys.readouterr()
    assert captured_output.out == ""
    assert captured_output.err == ""


def test_smtp_settings_and_provider_failure_do_not_expose_credentials(
    monkeypatch,
    capsys,
):
    from email.mime.text import MIMEText

    import auth_email_delivery

    smtp_password = "private-smtp-password-material"
    provider_error = "private-provider-response-with-recipient-and-token"
    settings = auth_email_delivery.AuthEmailSettings(
        frontend_url="https://litblogs.school.org",
        email_host="smtp.school.org",
        email_port=587,
        email_smtp_timeout_seconds=5,
        email_username="litblogs-reset",
        email_password=smtp_password,
        email_from="no-reply@school.org",
    )

    def fail_smtp(*_args, **_kwargs):
        raise RuntimeError(provider_error)

    monkeypatch.setattr(auth_email_delivery.smtplib, "SMTP", fail_smtp)

    assert smtp_password not in repr(settings)
    assert auth_email_delivery.send_smtp_message(
        settings,
        "student@school.org",
        MIMEText("private token and link", "plain"),
    ) is False
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert provider_error not in captured.out + captured.err


def test_engine_creation_failure_is_sanitized(monkeypatch):
    import auth_email_delivery

    private_detail = "private-database-host-password-and-driver-error"
    settings = SimpleNamespace(
        database_url="postgresql://private-runtime-url",
        db_pool_size=1,
        db_max_overflow=0,
        db_pool_timeout_seconds=10,
        db_pool_recycle_seconds=900,
        db_connect_timeout_seconds=5,
        db_statement_timeout_ms=15_000,
        db_lock_timeout_ms=5_000,
    )
    monkeypatch.setattr(
        auth_email_delivery,
        "create_engine",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError(private_detail)
        ),
    )

    with pytest.raises(auth_email_delivery.AuthEmailOperationalError) as captured:
        auth_email_delivery.create_auth_email_engine(settings)

    assert private_detail not in str(captured.value)
