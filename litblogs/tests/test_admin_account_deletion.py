from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier, Event

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

import main
import models
from database import SessionLocal, engine
from identity_controls import invitation_email_digest, issue_browser_session, operator_audit_resource_digest


@pytest.fixture
def deletion_db(client, tmp_path):
    del client
    if engine.dialect.name == "postgresql":
        yield SessionLocal
        return
    isolated = create_engine(f"sqlite:///{(tmp_path / 'delete.db').as_posix()}")

    @event.listens_for(isolated, "connect")
    def enable_constraints(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    models.Base.metadata.create_all(isolated)
    try:
        yield sessionmaker(bind=isolated, autoflush=False)
    finally:
        isolated.dispose()


def _user(db, name, role=models.UserRole.STUDENT):
    user = models.User(username=name, email=f"{name}@example.com", password="unused-synthetic-hash",
                       role=role, email_verified_at=datetime.now(UTC))
    db.add(user)
    db.flush()
    return user


@pytest.fixture
def accounts(deletion_db):
    with deletion_db() as db:
        actor = _user(db, "deleting-admin", models.UserRole.ADMIN)
        target = _user(db, "delete-target")
        session = models.BrowserSession(user_id=actor.id, jti_digest="a" * 64,
                                        expires_at=datetime.now(UTC) + timedelta(hours=1))
        db.add(session)
        db.flush()
        ids = {"actor_id": actor.id, "session_id": session.id, "target_user_id": target.id}
        db.commit()
    return ids


def _delete(db, accounts, **changes):
    from admin_account_deletion import delete_admin_account

    arguments = {**accounts, "confirmation_email": "delete-target@example.com", "settings": main.settings}
    arguments.update(changes)
    return delete_admin_account(db, **arguments)


@pytest.mark.parametrize("role", list(models.UserRole))
def test_empty_account_is_deleted_and_audited_for_every_role(deletion_db, accounts, role):
    with deletion_db() as db:
        target = db.get(models.User, accounts["target_user_id"])
        target.role = role
        target.email_verified_at = None
        db.commit()
        assert _delete(db, accounts) is None
    with deletion_db() as db:
        assert db.get(models.User, accounts["target_user_id"]) is None
        assert db.get(models.User, accounts["actor_id"]) is not None
        audit = db.query(models.OperatorAuditEvent).one()
        assert (audit.actor_identifier, audit.action, audit.outcome) == (
            f"admin-user:{accounts['actor_id']}", "ACCOUNT_DELETED", "SUCCEEDED",
        )
        assert audit.resource_digest == operator_audit_resource_digest("delete-target@example.com", settings=main.settings)


def test_authentication_rows_cascade_and_recipient_unused_invitation_is_revoked(deletion_db, accounts):
    target_id = accounts["target_user_id"]
    now = datetime.now(UTC)
    with deletion_db() as db:
        db.add_all([
            models.BrowserSession(user_id=target_id, jti_digest="b" * 64, expires_at=now + timedelta(hours=1)),
            models.PasswordReset(user_id=target_id, delivery_status="PENDING"),
            models.EmailVerification(user_id=target_id, delivery_status="PENDING"),
            models.FederatedIdentity(user_id=target_id, provider="google", issuer="https://accounts.google.com", subject="synthetic-subject"),
            models.UserSettings(user_id=target_id),
            models.PushSubscription(user_id=target_id, endpoint="https://push.example.com/test", p256dh="test-key", auth="test-auth"),
            models.Teacher(user_id=target_id, email="delete-target@example.com", name="Empty teacher profile"),
        ])
        digest = invitation_email_digest("delete-target@example.com", settings=main.settings)
        db.add_all([
            models.TeacherInvitation(token_digest="1" * 64, email_digest=digest, created_by="operator", expires_at=now + timedelta(hours=1)),
            models.TeacherInvitation(token_digest="2" * 64, email_digest=digest, created_by="operator", expires_at=now + timedelta(hours=1), consumed_at=now),
            models.TeacherInvitation(token_digest="3" * 64, email_digest=invitation_email_digest("other@example.com", settings=main.settings), created_by=f"admin-user:{target_id}", expires_at=now + timedelta(hours=1)),
        ])
        db.commit()
        _delete(db, accounts)
    with deletion_db() as db:
        for model in (models.BrowserSession, models.PasswordReset, models.EmailVerification, models.FederatedIdentity,
                      models.UserSettings, models.PushSubscription, models.Teacher):
            assert db.query(model).filter(model.user_id == target_id).count() == 0
        invitations = db.query(models.TeacherInvitation).order_by(models.TeacherInvitation.token_digest).all()
        assert invitations[0].revoked_at is not None
        assert invitations[1].consumed_at is not None and invitations[1].revoked_at is None
        assert invitations[2].revoked_at is None


@pytest.mark.parametrize("mutation,status", [
    ("student", 403), ("disabled", 401), ("unverified", 401), ("revoked", 401), ("expired", 401),
])
def test_stale_actor_and_session_are_rechecked(deletion_db, accounts, mutation, status):
    with deletion_db() as db:
        actor = db.get(models.User, accounts["actor_id"])
        session = db.get(models.BrowserSession, accounts["session_id"])
        if mutation == "student":
            actor.role = models.UserRole.STUDENT
            actor.is_admin = True
        elif mutation == "disabled":
            actor.disabled_at = datetime.now(UTC)
        elif mutation == "unverified":
            actor.email_verified_at = None
        elif mutation == "revoked":
            session.revoked_at = datetime.now(UTC)
        else:
            session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
        with pytest.raises(HTTPException) as error:
            _delete(db, accounts)
        assert error.value.status_code == status
        assert db.get(models.User, accounts["target_user_id"]) is not None


@pytest.mark.parametrize("confirmation", ["DELETE", "different@example.com", "DELETE-TARGET@example.com", " delete-target@example.com"])
def test_confirmation_must_match_exact_normalized_email(deletion_db, accounts, confirmation):
    with deletion_db() as db, pytest.raises(HTTPException) as error:
        _delete(db, accounts, confirmation_email=confirmation)
    assert error.value.status_code == 400


def test_last_admin_cannot_delete_self(deletion_db, accounts):
    with deletion_db() as db, pytest.raises(HTTPException) as error:
        _delete(db, accounts, target_user_id=accounts["actor_id"], confirmation_email="deleting-admin@example.com")
    assert error.value.status_code == 409


def test_missing_target_is_not_found(deletion_db, accounts):
    with deletion_db() as db, pytest.raises(HTTPException) as error:
        _delete(db, accounts, target_user_id=999999)
    assert error.value.status_code == 404


def _schoolwork(db, target_id, kind):
    other = _user(db, "other-teacher", models.UserRole.TEACHER)
    teacher = models.Teacher(user_id=other.id, email=other.email, name="Other teacher")
    db.add(teacher)
    db.flush()
    classroom = models.Class(name="Preserved class", access_code="SAFE01", teacher_id=teacher.id)
    db.add(classroom)
    db.flush()
    assignment = models.Assignment(class_id=classroom.id, title="Preserved assignment", created_by=other.id,
                                   due_date=datetime.now(UTC) + timedelta(days=1))
    blog = models.Blog(class_id=classroom.id, owner_id=other.id, title="Preserved post", content="Other work")
    db.add_all([assignment, blog])
    db.flush()
    if kind == "classes":
        teacher.user_id = target_id
    elif kind == "assignments":
        assignment.created_by = target_id
    elif kind == "posts":
        blog.owner_id = target_id
    elif kind == "submissions":
        db.add(models.AssignmentSubmission(assignment_id=assignment.id, student_id=target_id, content="Work"))
    elif kind == "drafts":
        db.add(models.AssignmentDraft(assignment_id=assignment.id, student_id=target_id, content="Draft"))
    elif kind == "enrollments":
        db.add(models.ClassEnrollment(class_id=classroom.id, student_id=target_id))
    elif kind in {"comments", "comment_likes"}:
        comment = models.Comment(user_id=target_id if kind == "comments" else other.id, blog_id=blog.id, content="Keep thread")
        db.add(comment)
        db.flush()
        db.add(models.Comment(user_id=other.id, blog_id=blog.id, parent_id=comment.id, content="Another person's reply"))
        if kind == "comment_likes":
            db.add(models.CommentLike(user_id=target_id, comment_id=comment.id))
    elif kind == "submission_replies":
        submission = models.AssignmentSubmission(assignment_id=assignment.id, student_id=other.id, content="Other work")
        db.add(submission)
        db.flush()
        db.add(models.AssignmentSubmissionReply(submission_id=submission.id, user_id=target_id, content="Feedback"))
    elif kind == "uploads":
        now = datetime.now(UTC)
        db.add(models.UploadAsset(owner_user_id=target_id, storage_key="objects/aa/" + "a" * 32 + ".png",
                                  purpose="POST", state="PENDING", media_type="image/png", size_bytes=10,
                                  sha256_digest="a" * 64, expires_at=now + timedelta(hours=1), scan_completed_at=now))
    elif kind == "post_likes":
        db.add(models.PostLike(user_id=target_id, post_id=blog.id))
    elif kind == "saved_posts":
        db.add(models.SavedPost(user_id=target_id, post_id=blog.id))
    elif kind == "reminders":
        db.add(models.AssignmentReminderNotification(user_id=target_id, assignment_id=assignment.id))
    db.flush()


@pytest.mark.parametrize("kind", ["classes", "assignments", "posts", "submissions", "drafts", "enrollments",
                                 "comments", "submission_replies", "uploads"])
def test_any_schoolwork_dependency_blocks_without_changing_other_data(deletion_db, accounts, kind):
    with deletion_db() as db:
        _schoolwork(db, accounts["target_user_id"], kind)
        db.commit()
        before = {table.name: db.execute(select(table)).all() for table in models.Base.metadata.sorted_tables}
        with pytest.raises(HTTPException) as error:
            _delete(db, accounts)
        assert error.value.status_code == 409
        after = {table.name: db.execute(select(table)).all() for table in models.Base.metadata.sorted_tables}
        assert after == before


@pytest.mark.parametrize("kind", ["post_likes", "comment_likes", "saved_posts", "reminders"])
def test_account_metadata_cascades_without_removing_schoolwork(deletion_db, accounts, kind):
    with deletion_db() as db:
        _schoolwork(db, accounts["target_user_id"], kind)
        db.commit()
        retained = (models.Class, models.Assignment, models.Blog, models.Comment)
        before = {model.__tablename__: db.execute(select(model.__table__)).all() for model in retained}
        _delete(db, accounts)
        assert db.get(models.User, accounts["target_user_id"]) is None
        assert {model.__tablename__: db.execute(select(model.__table__)).all() for model in retained} == before


def test_audit_failure_rolls_back_deletion_and_invitation_revocation(deletion_db, accounts, monkeypatch):
    import admin_account_deletion

    def fail(*_args, **_kwargs):
        raise SQLAlchemyError("synthetic private database failure")

    with deletion_db() as db:
        db.add(models.TeacherInvitation(token_digest="f" * 64,
            email_digest=invitation_email_digest("delete-target@example.com", settings=main.settings), created_by="operator",
            expires_at=datetime.now(UTC) + timedelta(hours=1)))
        db.commit()
        monkeypatch.setattr(admin_account_deletion, "record_operator_audit_event", fail)
        with pytest.raises(HTTPException) as error:
            _delete(db, accounts)
        assert error.value.status_code == 503
        assert db.get(models.User, accounts["target_user_id"]) is not None
        assert db.query(models.TeacherInvitation).one().revoked_at is None


@pytest.fixture
def deletion_client(client):
    with SessionLocal() as db:
        actor = _user(db, "route-admin", models.UserRole.ADMIN)
        target = _user(db, "delete-target", models.UserRole.TEACHER)
        target.email_verified_at = None
        target.disabled_at = datetime.now(UTC)
        issued = issue_browser_session(db, user_id=actor.id, settings=main.settings)
        actor_id, target_id = actor.id, target.id
        db.commit()
    client.cookies.set(main.settings.session_cookie_name, issued.token)
    client.cookies.set(main.settings.csrf_cookie_name, "deletion-csrf")
    client.headers[main.CSRF_HEADER_NAME] = "deletion-csrf"
    return client, actor_id, target_id


def _route_delete(client, user_id, email="delete-target@example.com"):
    return client.delete(f"/api/admin/users/{user_id}", params={"confirm": email})


def test_route_deletes_empty_disabled_unverified_account_with_confirmation(deletion_client):
    client, _actor_id, target_id = deletion_client
    response = _route_delete(client, target_id)
    assert response.status_code == 204 and response.content == b""
    with SessionLocal() as db:
        assert db.get(models.User, target_id) is None
        assert db.query(models.OperatorAuditEvent).one().action == "ACCOUNT_DELETED"


def test_route_rejects_missing_csrf_and_anonymous_requests(deletion_client):
    client, _actor_id, target_id = deletion_client
    del client.headers[main.CSRF_HEADER_NAME]
    assert _route_delete(client, target_id).status_code == 403
    client.cookies.clear()
    assert _route_delete(client, target_id).status_code == 401
    with SessionLocal() as db:
        assert db.get(models.User, target_id) is not None
        assert db.query(models.OperatorAuditEvent).count() == 0


def test_route_non_admin_cannot_delete_even_with_legacy_admin_flag(deletion_client):
    client, actor_id, target_id = deletion_client
    with SessionLocal() as db:
        actor = db.get(models.User, actor_id)
        actor.role = models.UserRole.STUDENT
        actor.is_admin = True
        db.commit()
    assert _route_delete(client, target_id).status_code == 403


def test_route_rejects_changed_identity_and_populated_target(deletion_client):
    client, _actor_id, target_id = deletion_client
    assert _route_delete(client, target_id, "stale-email@example.com").status_code == 400
    with SessionLocal() as db:
        _schoolwork(db, target_id, "posts")
        db.commit()
    assert _route_delete(client, target_id).status_code == 409
    with SessionLocal() as db:
        assert db.get(models.User, target_id) is not None
        assert db.query(models.Blog).one().content == "Other work"
        assert db.query(models.OperatorAuditEvent).count() == 0


@pytest.mark.skipif(engine.dialect.name != "postgresql", reason="PostgreSQL row-lock integration")
def test_in_flight_schoolwork_is_seen_after_user_lock(deletion_db, accounts):
    started = Event()
    dependency_check = Event()

    def observe(_connection, _cursor, statement, _parameters, _context, _many):
        if "FROM teachers" in statement:
            dependency_check.set()

    def attempt():
        with deletion_db() as db:
            started.set()
            try:
                _delete(db, accounts)
            except HTTPException as error:
                return error.status_code
        return 204

    with deletion_db() as pending:
        pending.execute(select(models.User.id).where(models.User.id == accounts["target_user_id"]).with_for_update())
        _schoolwork(pending, accounts["target_user_id"], "posts")
        event.listen(engine, "before_cursor_execute", observe)
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(attempt)
                try:
                    assert started.wait(timeout=2)
                    assert not dependency_check.wait(timeout=0.25)
                    pending.commit()
                finally:
                    pending.rollback()
                assert future.result(timeout=10) == 409
        finally:
            event.remove(engine, "before_cursor_execute", observe)
    with deletion_db() as db:
        assert db.get(models.User, accounts["target_user_id"]) is not None
        assert db.query(models.Blog).count() == 1
        assert db.query(models.OperatorAuditEvent).count() == 0


@pytest.mark.skipif(engine.dialect.name != "postgresql", reason="PostgreSQL row-lock integration")
def test_concurrent_admin_deletions_leave_one_active_admin(deletion_db, accounts):
    with deletion_db() as db:
        target = db.get(models.User, accounts["target_user_id"])
        target.role = models.UserRole.ADMIN
        session = models.BrowserSession(user_id=target.id, jti_digest="c" * 64,
                                        expires_at=datetime.now(UTC) + timedelta(hours=1))
        db.add(session)
        db.flush()
        reverse = {"actor_id": target.id, "session_id": session.id, "target_user_id": accounts["actor_id"]}
        db.commit()
    barrier = Barrier(2, timeout=10)

    def rendezvous(_connection, _cursor, statement, _parameters, _context, _many):
        if "FROM users" in statement and "FOR UPDATE" in statement:
            barrier.wait()

    def attempt(ids, confirmation):
        with deletion_db() as db:
            try:
                _delete(db, ids, confirmation_email=confirmation)
            except HTTPException as error:
                return error.status_code
        return 204

    event.listen(engine, "before_cursor_execute", rendezvous)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(attempt, accounts, "delete-target@example.com"),
                       executor.submit(attempt, reverse, "deleting-admin@example.com")]
            assert sorted(future.result(timeout=20) for future in futures) == [204, 401]
    finally:
        event.remove(engine, "before_cursor_execute", rendezvous)
    with deletion_db() as db:
        remaining = db.query(models.User).one()
        assert remaining.role == models.UserRole.ADMIN
        assert remaining.disabled_at is None and remaining.email_verified_at is not None
        assert db.query(models.OperatorAuditEvent).count() == 1
