import asyncio
import inspect
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

import main
import models
import schemas
from auth_security import hash_password
from database import SessionLocal

MAX_DRAFT_REVISION = 2_147_483_646
MAX_ASSIGNMENT_CONTENT_LENGTH = 1_000_000
NO_STORE_HEADERS = {
    "cache-control": "private, no-store",
    "pragma": "no-cache",
    "expires": "0",
}


@pytest.fixture
def assignment_student(client):
    with SessionLocal() as db:
        student = models.User(
            username="draft-revision-student",
            email="draft-revision-student@example.test",
            password=hash_password("synthetic-draft-password"),
            first_name="Draft",
            last_name="Student",
            role=models.UserRole.STUDENT,
            is_admin=False,
        )
        db.add(student)
        db.flush()

        class_ = models.Class(
            name="Revision Literature",
            description="Synthetic revision test class",
            access_code="REV001",
            status="active",
        )
        db.add(class_)
        db.flush()
        db.add(models.ClassEnrollment(student_id=student.id, class_id=class_.id))

        assignment = models.Assignment(
            class_id=class_.id,
            title="Revision response",
            description="Write a response",
            due_date=datetime.now(timezone.utc) + timedelta(days=7),
            created_by=student.id,
            allow_late=True,
            visibility="class",
        )
        db.add(assignment)
        db.commit()
        db.refresh(student)
        db.refresh(class_)
        db.refresh(assignment)
        student_id = student.id
        class_id = class_.id
        assignment_id = assignment.id

    def current_student():
        with SessionLocal() as db:
            user = db.get(models.User, student_id)
            db.expunge(user)
            return user

    main.app.dependency_overrides[main.get_current_user] = current_student
    try:
        yield {
            "client": client,
            "student_id": student_id,
            "class_id": class_id,
            "assignment_id": assignment_id,
        }
    finally:
        main.app.dependency_overrides.pop(main.get_current_user, None)


def _assert_private_no_store(response):
    for header, expected in NO_STORE_HEADERS.items():
        assert response.headers[header] == expected


def _get_draft_row(assignment_id, student_id):
    with SessionLocal() as db:
        draft = db.query(models.AssignmentDraft).filter(
            models.AssignmentDraft.assignment_id == assignment_id,
            models.AssignmentDraft.student_id == student_id,
        ).one_or_none()
        if draft is None:
            return None
        return {
            "content": draft.content,
            "revision": draft.revision,
        }


def test_draft_revision_is_required_and_bounded():
    with pytest.raises(ValidationError):
        schemas.AssignmentDraftUpdate(content="draft")
    with pytest.raises(ValidationError):
        schemas.AssignmentSubmissionCreate(content="submission")

    for invalid_revision in (-1, MAX_DRAFT_REVISION + 1):
        with pytest.raises(ValidationError):
            schemas.AssignmentDraftUpdate(
                content="draft",
                expected_revision=invalid_revision,
            )
        with pytest.raises(ValidationError):
            schemas.AssignmentSubmissionCreate(
                content="submission",
                expected_draft_revision=invalid_revision,
            )

    assert schemas.AssignmentDraftUpdate(
        content="draft",
        expected_revision=MAX_DRAFT_REVISION,
    ).expected_revision == MAX_DRAFT_REVISION


def test_assignment_draft_and_submission_content_have_an_explicit_boundary():
    boundary_content = "x" * MAX_ASSIGNMENT_CONTENT_LENGTH
    assert schemas.AssignmentDraftUpdate(
        content=boundary_content,
        expected_revision=0,
    ).content == boundary_content
    assert schemas.AssignmentSubmissionCreate(
        content=boundary_content,
        expected_draft_revision=0,
    ).content == boundary_content

    oversized_content = boundary_content + "x"
    with pytest.raises(ValidationError):
        schemas.AssignmentDraftUpdate(
            content=oversized_content,
            expected_revision=0,
        )
    with pytest.raises(ValidationError):
        schemas.AssignmentSubmissionCreate(
            content=oversized_content,
            expected_draft_revision=0,
        )


def test_assignment_content_boundary_is_accepted_by_the_authenticated_route(
    assignment_student,
):
    response = assignment_student["client"].put(
        f"/api/assignments/{assignment_student['assignment_id']}/draft",
        json={
            "content": "x" * MAX_ASSIGNMENT_CONTENT_LENGTH,
            "expected_revision": 0,
        },
    )

    assert response.status_code == 200
    assert response.json()["revision"] == 1
    _assert_private_no_store(response)


@pytest.mark.parametrize(
    ("method", "suffix", "revision_field"),
    [
        ("PUT", "draft", "expected_revision"),
        ("POST", "submit", "expected_draft_revision"),
    ],
)
def test_oversized_assignment_content_is_generic_redacted_and_no_store(
    assignment_student,
    method,
    suffix,
    revision_field,
):
    canary = "PRIVATE-OVERSIZED-ASSIGNMENT-CANARY-DO-NOT-ECHO"
    oversized_content = canary + (
        "x" * (MAX_ASSIGNMENT_CONTENT_LENGTH + 1 - len(canary))
    )
    response = assignment_student["client"].request(
        method,
        f"/api/assignments/{assignment_student['assignment_id']}/{suffix}",
        json={"content": oversized_content, revision_field: 0},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid assignment request"}
    assert len(response.content) <= 128
    assert canary not in response.text
    _assert_private_no_store(response)


def test_ten_megabyte_assignment_body_is_rejected_before_downstream_parsing():
    canary = b"PRIVATE-TEN-MEGABYTE-ASSIGNMENT-CANARY-DO-NOT-ECHO"
    request_body = canary + (b"x" * (10 * 1024 * 1024 - len(canary)))
    sent_messages = []
    downstream_called = False

    async def receive():
        return {"type": "http.request", "body": request_body, "more_body": False}

    async def send(message):
        sent_messages.append(message)

    async def downstream(scope, _receive, downstream_send):
        nonlocal downstream_called
        downstream_called = True
        await downstream_send({
            "type": "http.response.start",
            "status": 204,
            "headers": [],
        })
        await downstream_send({"type": "http.response.body", "body": b""})

    middleware = main.UploadRequestBodyLimitMiddleware(downstream)
    scope = {
        "type": "http",
        "method": "PUT",
        "path": "/api/assignments/17/draft",
        "headers": [(b"content-length", str(len(request_body)).encode("ascii"))],
    }

    asyncio.run(middleware(scope, receive, send))

    response_start = next(
        message for message in sent_messages if message["type"] == "http.response.start"
    )
    response_body = b"".join(
        message.get("body", b"")
        for message in sent_messages
        if message["type"] == "http.response.body"
    )
    headers = {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in response_start["headers"]
    }
    assert response_start["status"] == 413
    assert downstream_called is False
    assert canary not in response_body
    assert len(response_body) <= 128
    assert headers["cache-control"] == "private, no-store"
    assert headers["pragma"] == "no-cache"
    assert headers["expires"] == "0"


@pytest.mark.parametrize(
    ("method", "suffix", "revision_field", "revision_value"),
    [
        ("PUT", "draft", None, None),
        ("PUT", "draft", "expected_revision", "not-an-integer"),
        ("POST", "submit", None, None),
        ("POST", "submit", "expected_draft_revision", "not-an-integer"),
    ],
)
def test_private_assignment_validation_never_echoes_content_and_is_no_store(
    assignment_student,
    method,
    suffix,
    revision_field,
    revision_value,
):
    client = assignment_student["client"]
    assignment_id = assignment_student["assignment_id"]
    canary = "PRIVATE-ASSIGNMENT-DRAFT-CANARY-DO-NOT-ECHO"
    payload = {"content": canary}
    if revision_field is not None:
        payload[revision_field] = revision_value

    response = client.request(
        method,
        f"/api/assignments/{assignment_id}/{suffix}",
        json=payload,
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid assignment request"}
    assert len(response.content) <= 128
    assert canary not in response.text
    _assert_private_no_store(response)


def test_non_assignment_validation_keeps_the_default_error_shape(assignment_student):
    response = assignment_student["client"].get(
        "/api/classes/not-a-class/assignments"
    )

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


def test_absent_draft_and_assignment_list_expose_revision_zero_with_no_store(
    assignment_student,
):
    client = assignment_student["client"]
    assignment_id = assignment_student["assignment_id"]
    class_id = assignment_student["class_id"]

    draft_response = client.get(f"/api/assignments/{assignment_id}/draft")
    assert draft_response.status_code == 200
    assert draft_response.json() == {
        "content": "",
        "saved_at": None,
        "has_draft": False,
        "revision": 0,
    }
    _assert_private_no_store(draft_response)

    list_response = client.get(f"/api/classes/{class_id}/assignments")
    assert list_response.status_code == 200
    payload = list_response.json()
    assert payload[0]["my_draft"] is None
    assert payload[0]["my_draft_revision"] == 0
    _assert_private_no_store(list_response)


def test_two_revision_zero_tabs_cannot_overwrite_each_other(assignment_student):
    client = assignment_student["client"]
    assignment_id = assignment_student["assignment_id"]

    first = client.put(
        f"/api/assignments/{assignment_id}/draft",
        json={"content": "first tab", "expected_revision": 0},
    )
    assert first.status_code == 200
    assert first.json()["revision"] == 1
    _assert_private_no_store(first)

    second = client.put(
        f"/api/assignments/{assignment_id}/draft",
        json={"content": "second tab", "expected_revision": 0},
    )
    assert second.status_code == 409
    assert second.json()["detail"] == "Assignment draft changed in another session"
    _assert_private_no_store(second)

    current = client.get(f"/api/assignments/{assignment_id}/draft")
    assert current.json()["content"] == "first tab"
    assert current.json()["revision"] == 1


def test_empty_save_creates_persistent_revision_tombstone(assignment_student):
    client = assignment_student["client"]
    assignment_id = assignment_student["assignment_id"]
    student_id = assignment_student["student_id"]

    cleared = client.put(
        f"/api/assignments/{assignment_id}/draft",
        json={"content": "", "expected_revision": 0},
    )
    assert cleared.status_code == 200
    assert cleared.json() == {
        "content": "",
        "saved_at": None,
        "has_draft": False,
        "revision": 1,
    }
    assert _get_draft_row(assignment_id, student_id) == {
        "content": None,
        "revision": 1,
    }


def test_submit_rejects_delayed_save_revision_and_advances_tombstone(
    assignment_student,
):
    client = assignment_student["client"]
    assignment_id = assignment_student["assignment_id"]
    student_id = assignment_student["student_id"]

    accepted_save = client.put(
        f"/api/assignments/{assignment_id}/draft",
        json={"content": "accepted while response delayed", "expected_revision": 0},
    )
    assert accepted_save.status_code == 200
    assert accepted_save.json()["revision"] == 1

    stale_submit = client.post(
        f"/api/assignments/{assignment_id}/submit",
        json={"content": "submitted answer", "expected_draft_revision": 0},
    )
    assert stale_submit.status_code == 409
    assert stale_submit.json()["detail"] == "Assignment draft changed in another session"

    submitted = client.post(
        f"/api/assignments/{assignment_id}/submit",
        json={"content": "submitted answer", "expected_draft_revision": 1},
    )
    assert submitted.status_code == 200
    assert submitted.json()["draft_revision"] == 2
    _assert_private_no_store(submitted)
    assert _get_draft_row(assignment_id, student_id) == {
        "content": None,
        "revision": 2,
    }

    late_save = client.put(
        f"/api/assignments/{assignment_id}/draft",
        json={"content": "late response from old tab", "expected_revision": 1},
    )
    assert late_save.status_code == 409
    assert _get_draft_row(assignment_id, student_id) == {
        "content": None,
        "revision": 2,
    }


def test_resubmission_can_create_a_new_draft_after_tombstone(assignment_student):
    client = assignment_student["client"]
    assignment_id = assignment_student["assignment_id"]
    student_id = assignment_student["student_id"]

    first_draft = client.put(
        f"/api/assignments/{assignment_id}/draft",
        json={"content": "first draft", "expected_revision": 0},
    )
    assert first_draft.json()["revision"] == 1
    first_submit = client.post(
        f"/api/assignments/{assignment_id}/submit",
        json={"content": "first answer", "expected_draft_revision": 1},
    )
    assert first_submit.status_code == 200
    assert first_submit.json()["draft_revision"] == 2

    resubmission_draft = client.put(
        f"/api/assignments/{assignment_id}/draft",
        json={"content": "revised draft", "expected_revision": 2},
    )
    assert resubmission_draft.status_code == 200
    assert resubmission_draft.json()["revision"] == 3

    resubmission = client.post(
        f"/api/assignments/{assignment_id}/submit",
        json={"content": "revised answer", "expected_draft_revision": 3},
    )
    assert resubmission.status_code == 200
    assert resubmission.json()["draft_revision"] == 4
    assert _get_draft_row(assignment_id, student_id) == {
        "content": None,
        "revision": 4,
    }


def test_write_endpoints_lock_stable_user_before_draft_lookup():
    save_source = inspect.getsource(main.save_assignment_draft)
    submit_source = inspect.getsource(main.submit_assignment)

    for source in (save_source, submit_source):
        lock_position = source.index("with_for_update")
        draft_position = source.index("models.AssignmentDraft")
        assert "models.User" in source[:draft_position]
        assert lock_position < draft_position


def test_revision_migration_and_orm_schema_are_semantically_aligned():
    migration = (
        Path(main.__file__).resolve().parent
        / "migrations"
        / "0004_assignment_draft_revisions.sql"
    ).read_text(encoding="utf-8")
    normalized = " ".join(migration.lower().split())

    assert "alter table assignment_drafts" in normalized
    assert "add column" in normalized and "revision integer" in normalized
    assert "alter column content drop not null" in normalized
    assert "alter column revision set default 0" in normalized
    assert "alter column revision set not null" in normalized

    revision = models.AssignmentDraft.__table__.c.revision
    content = models.AssignmentDraft.__table__.c.content
    assert revision.nullable is False
    assert revision.default.arg == 0
    assert str(revision.server_default.arg) == "0"
    assert content.nullable is True
    checks = {
        str(constraint.sqltext)
        for constraint in models.AssignmentDraft.__table__.constraints
        if constraint.__class__.__name__ == "CheckConstraint"
    }
    assert "revision >= 0 AND revision <= 2147483647" in checks
