"""Private rich assignment media from upload through draft and submission."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Query
from test_content_security import MP4_BYTES, PDF_BYTES, PNG_BYTES

import main
import models
from database import SessionLocal


@pytest.fixture
def assignment_images(client, monkeypatch, tmp_path):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    with SessionLocal() as db:
        users = {}
        for name, role in (
            ("student", models.UserRole.STUDENT),
            ("classmate", models.UserRole.STUDENT),
            ("teacher", models.UserRole.TEACHER),
            ("other_teacher", models.UserRole.TEACHER),
            ("admin", models.UserRole.ADMIN),
        ):
            user = models.User(
                username=f"assignment-image-{name}",
                email=f"assignment-image-{name}@example.test",
                password="synthetic-hash",
                first_name="Image",
                last_name=name,
                role=role,
                is_admin=role == models.UserRole.ADMIN,
                email_verified_at=datetime.now(UTC),
            )
            db.add(user)
            db.flush()
            users[name] = user.id
        teacher = models.Teacher(
            name="Image Teacher",
            email="assignment-image-teacher@example.test",
            hashed_password="synthetic-hash",
            user_id=users["teacher"],
        )
        other_teacher = models.Teacher(
            name="Other Teacher",
            email="assignment-image-other_teacher@example.test",
            hashed_password="synthetic-hash",
            user_id=users["other_teacher"],
        )
        db.add_all([teacher, other_teacher])
        db.flush()
        classroom = models.Class(
            name="Image class",
            access_code="IMG001",
            teacher_id=teacher.id,
            status="active",
        )
        db.add(classroom)
        db.flush()
        db.add_all([
            models.ClassEnrollment(student_id=users["student"], class_id=classroom.id),
            models.ClassEnrollment(student_id=users["classmate"], class_id=classroom.id),
        ])
        assignment = models.Assignment(
            class_id=classroom.id,
            title="Draw your response",
            due_date=datetime.now(UTC) + timedelta(days=7),
            created_by=users["teacher"],
            allow_late=True,
            visibility="class",
        )
        db.add(assignment)
        db.commit()
        assignment_id = assignment.id
        class_id = classroom.id

    def act_as(name):
        actor = SimpleNamespace(
            id=users[name],
            role=next(role for candidate, role in (
                ("student", models.UserRole.STUDENT),
                ("classmate", models.UserRole.STUDENT),
                ("teacher", models.UserRole.TEACHER),
                ("other_teacher", models.UserRole.TEACHER),
                ("admin", models.UserRole.ADMIN),
            ) if candidate == name),
            disabled_at=None,
        )
        main.app.dependency_overrides[main.get_current_user] = lambda: actor

    try:
        yield {"client": client, "users": users, "assignment_id": assignment_id,
               "class_id": class_id, "act_as": act_as}
    finally:
        main.app.dependency_overrides.pop(main.get_current_user, None)


def _upload(context, kind="image"):
    filename, payload, media_type = {
        "image": ("response.png", PNG_BYTES, "image/png"),
        "video": ("response.mp4", MP4_BYTES, "video/mp4"),
        "file": ("response.pdf", PDF_BYTES, "application/pdf"),
    }[kind]
    response = context["client"].post(
        f"/api/assignments/{context['assignment_id']}/upload/{kind}",
        files={"file": (filename, payload, media_type)},
    )
    assert response.status_code == 200, response.text
    return response.json()["url"]


def _rich_image(url):
    return f'<p>See my response</p><img src="{url}" alt="response">'


def test_assignment_image_stays_private_until_submission(assignment_images):
    context = assignment_images
    client = context["client"]
    context["act_as"]("student")
    url = _upload(context)
    assert url.startswith("/api/uploads/objects/")
    assert client.get(url).status_code == 200

    for other in ("classmate", "teacher", "admin", "other_teacher"):
        context["act_as"](other)
        assert client.get(url).status_code == 404

    context["act_as"]("student")
    saved = client.put(
        f"/api/assignments/{context['assignment_id']}/draft",
        json={"content": _rich_image(url), "content_format": "rich", "expected_revision": 0},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["has_draft"] is True
    assert url in saved.json()["content"]
    assert saved.json()["content_format"] == "rich"
    assert url in client.get(f"/api/assignments/{context['assignment_id']}/draft").json()["content"]
    listed = client.get(f"/api/classes/{context['class_id']}/assignments").json()
    assert url in listed[0]["my_draft"]["content"]

    for other in ("classmate", "teacher", "admin"):
        context["act_as"](other)
        assert client.get(url).status_code == 404

    context["act_as"]("student")
    submitted = client.post(
        f"/api/assignments/{context['assignment_id']}/submit",
        json={"content": _rich_image(url), "content_format": "rich", "expected_draft_revision": 1},
    )
    assert submitted.status_code == 200, submitted.text
    assert url in submitted.json()["content"]
    assert client.get(url).status_code == 200

    for allowed in ("teacher", "admin"):
        context["act_as"](allowed)
        assert client.get(url).status_code == 200
    context["act_as"]("teacher")
    submissions = client.get(
        f"/api/classes/{context['class_id']}/assignments/{context['assignment_id']}/submissions"
    )
    assert submissions.status_code == 200
    assert submissions.headers["cache-control"] == "private, no-store"
    assert url in submissions.json()[0]["content"]
    for denied in ("classmate", "other_teacher"):
        context["act_as"](denied)
        assert client.get(url).status_code == 404

    with SessionLocal() as db:
        assignment = db.get(models.Assignment, context["assignment_id"])
        assignment.archived_at = datetime.now(UTC)
        db.commit()
    context["act_as"]("teacher")
    assert client.get(url).status_code == 200


def test_replacing_a_submitted_image_keeps_old_visible_until_resubmitted(assignment_images):
    context = assignment_images
    client = context["client"]
    context["act_as"]("student")
    old_url = _upload(context)
    first = client.post(
        f"/api/assignments/{context['assignment_id']}/submit",
        json={"content": _rich_image(old_url), "content_format": "rich", "expected_draft_revision": 0},
    )
    assert first.status_code == 200, first.text
    new_url = _upload(context)
    draft = client.put(
        f"/api/assignments/{context['assignment_id']}/draft",
        json={"content": _rich_image(new_url), "content_format": "rich",
              "expected_revision": first.json()["draft_revision"]},
    )
    assert draft.status_code == 200, draft.text

    context["act_as"]("teacher")
    assert client.get(old_url).status_code == 200
    assert client.get(new_url).status_code == 404
    context["act_as"]("student")
    second = client.post(
        f"/api/assignments/{context['assignment_id']}/submit",
        json={"content": _rich_image(new_url), "content_format": "rich",
              "expected_draft_revision": draft.json()["revision"]},
    )
    assert second.status_code == 200, second.text
    context["act_as"]("teacher")
    assert client.get(old_url).status_code == 404
    assert client.get(new_url).status_code == 200
    with SessionLocal() as db:
        old = db.query(models.UploadAsset).filter(
            models.UploadAsset.storage_key == old_url.removeprefix("/api/uploads/")
        ).one()
        assert old.state == "DELETE_PENDING"
        assert old.assignment_id is None


def test_rich_response_binds_multiple_media_and_keeps_draft_private(assignment_images):
    context = assignment_images
    client = context["client"]
    context["act_as"]("student")
    image_url = _upload(context, "image")
    video_url = _upload(context, "video")
    pdf_url = _upload(context, "file")
    content = (
        f'<p><strong>My response</strong></p><img src="{image_url}" alt="work">'
        f'<video controls src="{video_url}"></video>'
        f'<a class="file-attachment" href="{pdf_url}">Reading</a>'
    )
    draft = client.put(
        f"/api/assignments/{context['assignment_id']}/draft",
        json={"content": content, "content_format": "rich", "expected_revision": 0},
    )
    assert draft.status_code == 200, draft.text
    assert draft.json()["content_format"] == "rich"
    for url in (image_url, video_url, pdf_url):
        assert url in draft.json()["content"]

    context["act_as"]("teacher")
    for url in (image_url, video_url, pdf_url):
        assert client.get(url).status_code == 404

    context["act_as"]("student")
    submitted = client.post(
        f"/api/assignments/{context['assignment_id']}/submit",
        json={"content": content, "content_format": "rich", "expected_draft_revision": 1},
    )
    assert submitted.status_code == 200, submitted.text
    context["act_as"]("teacher")
    for url in (image_url, video_url, pdf_url):
        assert client.get(url).status_code == 200
    context["act_as"]("classmate")
    for url in (image_url, video_url, pdf_url):
        assert client.get(url).status_code == 404


def test_media_only_submission_and_legacy_plain_content(assignment_images):
    context = assignment_images
    client = context["client"]
    context["act_as"]("student")
    image_url = _upload(context)
    image_only = f'<img src="{image_url}" alt="drawing">'
    submitted = client.post(
        f"/api/assignments/{context['assignment_id']}/submit",
        json={"content": image_only, "content_format": "rich", "expected_draft_revision": 0},
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["content_format"] == "rich"
    context["act_as"]("teacher")
    assert client.get(image_url).status_code == 200

    context["act_as"]("student")
    plain = '<img src="/api/uploads/objects/bad" onerror="alert(1)">'
    draft = client.put(
        f"/api/assignments/{context['assignment_id']}/draft",
        json={"content": plain, "expected_revision": submitted.json()["draft_revision"]},
    )
    assert draft.status_code == 200, draft.text
    assert draft.json()["content"] == plain
    assert draft.json()["content_format"] == "plain"
    context["act_as"]("teacher")
    assert client.get(image_url).status_code == 200


def test_rich_assignment_save_uses_blog_sanitizer(assignment_images):
    context = assignment_images
    context["act_as"]("student")
    draft = context["client"].put(
        f"/api/assignments/{context['assignment_id']}/draft",
        json={
            "content": '<script>alert(1)</script><p onclick="alert(2)">'
                       '<strong>Safe</strong></p><a href="javascript:alert(3)">link</a>',
            "content_format": "rich",
            "expected_revision": 0,
        },
    )
    assert draft.status_code == 200, draft.text
    assert "<strong>Safe</strong>" in draft.json()["content"]
    assert "script" not in draft.json()["content"]
    assert "onclick" not in draft.json()["content"]
    assert "javascript:" not in draft.json()["content"]


def test_assignment_upload_locks_assignment_before_owner(assignment_images, monkeypatch):
    context = assignment_images
    context["act_as"]("student")
    lock_order = []
    original = Query.with_for_update

    def trace_lock(query, *args, **kwargs):
        entity = query.column_descriptions[0].get("entity")
        if entity in (models.Assignment, models.User):
            lock_order.append(entity)
        return original(query, *args, **kwargs)

    monkeypatch.setattr(Query, "with_for_update", trace_lock)
    _upload(context)
    assert lock_order[:2] == [models.Assignment, models.User]


def test_assignment_rejects_blog_and_foreign_image_references(assignment_images):
    context = assignment_images
    client = context["client"]
    context["act_as"]("classmate")
    foreign_url = _upload(context)
    context["act_as"]("student")
    blog = client.post(
        "/api/upload/image",
        files={"file": ("blog.png", PNG_BYTES, "image/png")},
    )
    assert blog.status_code == 200, blog.text
    for url in (foreign_url, blog.json()["url"]):
        rejected = client.put(
            f"/api/assignments/{context['assignment_id']}/draft",
            json={"content": _rich_image(url), "content_format": "rich", "expected_revision": 0},
        )
        assert rejected.status_code == 400, (url, rejected.text)
    assert client.get(f"/api/assignments/{context['assignment_id']}/draft").json()["revision"] == 0

    sanitized = client.put(
        f"/api/assignments/{context['assignment_id']}/draft",
        json={"content": _rich_image("/api/uploads/objects/bad"),
              "content_format": "rich", "expected_revision": 0},
    )
    assert sanitized.status_code == 200, sanitized.text
    assert "/api/uploads/objects/bad" not in sanitized.json()["content"]


def test_deleting_an_assignment_queues_pending_and_active_images(assignment_images):
    context = assignment_images
    client = context["client"]
    context["act_as"]("student")
    active_url = _upload(context)
    saved = client.put(
        f"/api/assignments/{context['assignment_id']}/draft",
        json={"content": _rich_image(active_url), "content_format": "rich", "expected_revision": 0},
    )
    assert saved.status_code == 200, saved.text
    pending_url = _upload(context)

    with SessionLocal() as db:
        main._delete_assignments_with_dependencies(db, [context["assignment_id"]])
        db.commit()
        for url in (active_url, pending_url):
            asset = db.query(models.UploadAsset).filter(
                models.UploadAsset.storage_key == url.removeprefix("/api/uploads/")
            ).one()
            assert asset.state == "DELETE_PENDING"
            assert asset.assignment_id is None
    assert client.get(active_url).status_code == 404
    assert client.get(pending_url).status_code == 404


def test_student_can_cancel_pending_assignment_image_without_a_server_error(assignment_images):
    context = assignment_images
    client = context["client"]
    context["act_as"]("student")
    url = _upload(context)
    delete_url = url.replace("/api/uploads/", "/api/upload/", 1)

    removed = client.delete(delete_url)
    assert removed.status_code == 200, removed.text
    assert client.get(url).status_code == 404
    with SessionLocal() as db:
        asset = db.query(models.UploadAsset).filter(
            models.UploadAsset.storage_key == url.removeprefix("/api/uploads/")
        ).one()
        assert asset.state == "DELETE_PENDING"
        assert asset.assignment_id is None
