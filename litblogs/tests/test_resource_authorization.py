import hashlib
import inspect
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from email import message_from_string

import pytest

import main
import models
from auth_security import hash_password, issue_access_token
from database import SessionLocal

PASSWORD_HASH = hash_password("correct horse battery staple")


def _headers(user_id: int) -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_access_token(str(user_id))}"}


@pytest.fixture
def authorization_scenario(client):
    db = SessionLocal()
    try:
        password_hash = PASSWORD_HASH
        teacher_a_user = models.User(
            username="teacher-a",
            email="teacher-a@example.com",
            password=password_hash,
            first_name="Teacher",
            last_name="Alpha",
            role=models.UserRole.TEACHER,
        )
        teacher_b_user = models.User(
            username="teacher-b",
            email="teacher-b@example.com",
            password=password_hash,
            first_name="Teacher",
            last_name="Beta",
            role=models.UserRole.TEACHER,
        )
        student_a = models.User(
            username="student-a",
            email="student-a@example.com",
            password=password_hash,
            first_name="Student",
            last_name="Alpha",
            role=models.UserRole.STUDENT,
        )
        student_b = models.User(
            username="student-b",
            email="student-b@example.com",
            password=password_hash,
            first_name="Student",
            last_name="Beta",
            role=models.UserRole.STUDENT,
        )
        admin = models.User(
            username="administrator",
            email="administrator@example.com",
            password=password_hash,
            first_name="School",
            last_name="Admin",
            role=models.UserRole.ADMIN,
            is_admin=True,
        )
        db.add_all([teacher_a_user, teacher_b_user, student_a, student_b, admin])
        db.flush()

        db.add(models.Teacher(name="Legacy Teacher", email="legacy-teacher@example.com"))
        db.flush()

        teacher_a = models.Teacher(
            name="Teacher Alpha",
            email=teacher_a_user.email,
            user_id=teacher_a_user.id,
        )
        teacher_b = models.Teacher(
            name="Teacher Beta",
            email=teacher_b_user.email,
            user_id=teacher_b_user.id,
        )
        db.add_all([teacher_a, teacher_b])
        db.flush()

        class_a = models.Class(
            name="Alpha Literature",
            description="Teacher Alpha's class",
            access_code="ALPHA1",
            teacher_id=teacher_a.id,
            status="active",
        )
        class_b = models.Class(
            name="Beta Literature",
            description="Teacher Beta's class",
            access_code="BETA22",
            teacher_id=teacher_b.id,
            status="active",
        )
        db.add_all([class_a, class_b])
        db.flush()

        db.add_all(
            [
                models.ClassEnrollment(student_id=student_a.id, class_id=class_a.id),
                models.ClassEnrollment(student_id=student_b.id, class_id=class_a.id),
                models.ClassEnrollment(student_id=student_b.id, class_id=class_b.id),
            ]
        )

        post_a = models.Blog(
            title="Alpha post",
            content="Alpha content",
            owner_id=student_a.id,
            class_id=class_a.id,
            ai_percentage=17,
            ai_highlighted_html="private-alpha-analysis",
            ai_sentence_analysis="private-alpha-sentences",
        )
        post_b = models.Blog(
            title="Beta post",
            content="Beta content",
            owner_id=student_b.id,
            class_id=class_b.id,
            ai_percentage=81,
            ai_highlighted_html="private-beta-analysis",
            ai_sentence_analysis="private-beta-sentences",
        )
        db.add_all([post_a, post_b])
        db.flush()

        now = datetime.now(UTC)
        comment_a = models.Comment(
            content="Alpha comment",
            created_at=now,
            updated_at=now,
            user_id=student_b.id,
            blog_id=post_a.id,
        )
        comment_b = models.Comment(
            content="Beta comment",
            created_at=now,
            updated_at=now,
            user_id=student_b.id,
            blog_id=post_b.id,
        )
        db.add_all([comment_a, comment_b])

        assignment_a = models.Assignment(
            class_id=class_a.id,
            title="Alpha assignment",
            description="Write an essay",
            due_date=datetime.now(UTC) + timedelta(days=2),
            created_by=teacher_a_user.id,
            allow_late=True,
            visibility="class",
        )
        assignment_b = models.Assignment(
            class_id=class_b.id,
            title="Beta assignment",
            description="Write a response",
            due_date=datetime.now(UTC) + timedelta(days=3),
            created_by=teacher_b_user.id,
            allow_late=True,
            visibility="class",
        )
        db.add_all([assignment_a, assignment_b])
        db.flush()

        submission_a = models.AssignmentSubmission(
            assignment_id=assignment_a.id,
            student_id=student_a.id,
            content="Student Alpha private submission",
            ai_percentage=22,
            ai_highlighted_html="student-alpha-private-ai",
            ai_sentence_analysis="student-alpha-private-sentences",
        )
        submission_b = models.AssignmentSubmission(
            assignment_id=assignment_a.id,
            student_id=student_b.id,
            content="Student Beta private submission",
            ai_percentage=44,
            ai_highlighted_html="student-beta-private-ai",
            ai_sentence_analysis="student-beta-private-sentences",
        )
        db.add_all([submission_a, submission_b])
        db.flush()
        db.add(
            models.AssignmentSubmissionReply(
                submission_id=submission_b.id,
                user_id=teacher_a_user.id,
                content="Private teacher feedback",
            )
        )
        db.add(
            models.SavedPost(
                post_id=post_b.id,
                user_id=student_a.id,
                created_at=now,
            )
        )
        db.commit()

        ids = {
            "teacher_a": teacher_a_user.id,
            "teacher_b": teacher_b_user.id,
            "student_a": student_a.id,
            "student_b": student_b.id,
            "admin": admin.id,
            "class_a": class_a.id,
            "class_b": class_b.id,
            "post_a": post_a.id,
            "post_b": post_b.id,
            "comment_a": comment_a.id,
            "comment_b": comment_b.id,
            "assignment_a": assignment_a.id,
            "assignment_b": assignment_b.id,
            "submission_a": submission_a.id,
            "submission_b": submission_b.id,
        }
    finally:
        db.close()

    return {
        **ids,
        "teacher_a_headers": _headers(ids["teacher_a"]),
        "teacher_b_headers": _headers(ids["teacher_b"]),
        "student_a_headers": _headers(ids["student_a"]),
        "student_b_headers": _headers(ids["student_b"]),
        "admin_headers": _headers(ids["admin"]),
    }


def _assert_denied(response):
    assert response.status_code in {403, 404}, response.text


@pytest.mark.parametrize(
    ("method", "path_template"),
    [
        ("get", "/api/classes/{class_a}/details"),
        ("get", "/api/classes/{class_a}/posts"),
        ("get", "/api/classes/{class_a}/posts/{post_a}"),
        ("get", "/api/classes/{class_a}/students"),
        ("get", "/api/classes/{class_a}/students/{student_a}"),
        ("get", "/api/classes/{class_a}/students/{student_a}/posts"),
        ("get", "/api/classes/{class_a}/analytics"),
        ("put", "/api/classes/{class_a}/archive"),
        ("put", "/api/classes/{class_a}/restore"),
        ("delete", "/api/classes/{class_a}"),
    ],
)
def test_other_teacher_cannot_access_or_manage_class_a(
    client,
    authorization_scenario,
    method,
    path_template,
):
    scenario = authorization_scenario
    path = path_template.format(**scenario)
    response = getattr(client, method)(path, headers=scenario["teacher_b_headers"])
    _assert_denied(response)


def test_other_teacher_cannot_create_post_or_write_notes_in_class_a(client, authorization_scenario):
    scenario = authorization_scenario

    post_response = client.post(
        f"/api/classes/{scenario['class_a']}/posts",
        headers=scenario["teacher_b_headers"],
        json={"title": "Forged teacher post", "content": "not allowed"},
    )
    notes_response = client.put(
        f"/api/classes/{scenario['class_a']}/students/{scenario['student_a']}/notes",
        headers=scenario["teacher_b_headers"],
        json={"notes": "not allowed"},
    )

    _assert_denied(post_response)
    _assert_denied(notes_response)


def test_admin_class_override_uses_central_owner_policy(client, authorization_scenario):
    scenario = authorization_scenario
    archive_response = client.put(
        f"/api/classes/{scenario['class_a']}/archive",
        headers=scenario["admin_headers"],
    )
    restore_response = client.put(
        f"/api/classes/{scenario['class_a']}/restore",
        headers=scenario["admin_headers"],
    )
    details_response = client.get(
        f"/api/classes/{scenario['class_a']}/students/{scenario['student_a']}",
        headers=scenario["admin_headers"],
    )
    posts_response = client.get(
        f"/api/classes/{scenario['class_a']}/students/{scenario['student_a']}/posts",
        headers=scenario["admin_headers"],
    )

    assert archive_response.status_code == 200
    assert restore_response.status_code == 200
    assert details_response.status_code == 200
    assert posts_response.status_code == 200


def test_teacher_cannot_query_non_enrolled_user_as_class_student(client, authorization_scenario):
    scenario = authorization_scenario
    response = client.get(
        f"/api/classes/{scenario['class_b']}/students/{scenario['student_a']}/posts",
        headers=scenario["teacher_b_headers"],
    )

    assert response.status_code == 404


@pytest.mark.parametrize(
    ("method", "path_template", "json_body"),
    [
        ("get", "/api/classes/{class_b}/posts/{post_b}", None),
        ("post", "/api/classes/{class_b}/posts/{post_b}/like", None),
        ("get", "/api/classes/{class_b}/posts/{post_b}/likes", None),
        ("get", "/api/classes/{class_b}/posts/{post_b}/comments", None),
        (
            "post",
            "/api/classes/{class_b}/posts/{post_b}/comments",
            {"content": "cross-class comment"},
        ),
        ("get", "/api/comments/{comment_b}/replies", None),
        ("post", "/api/comments/{comment_b}/like", None),
        ("post", "/api/classes/{class_b}/posts/{post_b}/save", None),
    ],
)
def test_student_cannot_interact_with_cross_class_content(
    client,
    authorization_scenario,
    method,
    path_template,
    json_body,
):
    scenario = authorization_scenario
    path = path_template.format(**scenario)
    kwargs = {"headers": scenario["student_a_headers"]}
    if json_body is not None:
        kwargs["json"] = json_body

    response = getattr(client, method)(path, **kwargs)

    _assert_denied(response)


def test_student_roster_is_minimal_and_teacher_roster_includes_email(client, authorization_scenario):
    scenario = authorization_scenario
    student_response = client.get(
        f"/api/classes/{scenario['class_a']}/students",
        headers=scenario["student_a_headers"],
    )
    teacher_response = client.get(
        f"/api/classes/{scenario['class_a']}/students",
        headers=scenario["teacher_a_headers"],
    )

    assert student_response.status_code == 200
    assert teacher_response.status_code == 200
    assert all("email" not in entry and "created_at" not in entry for entry in student_response.json())
    assert all("email" in entry for entry in teacher_response.json())


def test_student_class_details_do_not_disclose_access_code(client, authorization_scenario):
    scenario = authorization_scenario
    student_response = client.get(
        f"/api/classes/{scenario['class_a']}/details",
        headers=scenario["student_a_headers"],
    )
    teacher_response = client.get(
        f"/api/classes/{scenario['class_a']}/details",
        headers=scenario["teacher_a_headers"],
    )

    assert student_response.status_code == 200
    assert "access_code" not in student_response.json()
    assert teacher_response.status_code == 200
    assert teacher_response.json()["access_code"] == "ALPHA1"


def test_class_listing_rejects_unrecognized_status_filter(client, authorization_scenario):
    response = client.get(
        "/api/classes?status=deleted",
        headers=authorization_scenario["teacher_a_headers"],
    )

    assert response.status_code == 422


def test_class_access_codes_use_cryptographic_randomness(
    authorization_scenario,
    monkeypatch,
):
    del authorization_scenario
    generated = iter("SAFE12")
    monkeypatch.setattr(main.secrets, "choice", lambda _alphabet: next(generated))

    db = SessionLocal()
    try:
        assert main.generate_unique_code(db) == "SAFE12"
    finally:
        db.close()


def test_admin_user_listing_uses_safe_fields_only(client, authorization_scenario):
    scenario = authorization_scenario
    response = client.get("/api/users", headers=scenario["admin_headers"])

    assert response.status_code == 200
    assert response.json()
    forbidden_fields = {"password", "hashed_password", "federated_identities"}
    assert all(forbidden_fields.isdisjoint(user) for user in response.json())


def test_legacy_admin_flag_never_grants_role_privileges(client, authorization_scenario):
    scenario = authorization_scenario
    db = SessionLocal()
    try:
        student = db.query(models.User).filter(models.User.id == scenario["student_a"]).one()
        student.is_admin = True
        db.commit()
    finally:
        db.close()

    classes_response = client.get("/api/classes", headers=scenario["student_a_headers"])
    profile_response = client.get(
        f"/api/user/profile/{scenario['student_b']}",
        headers=scenario["student_a_headers"],
    )
    posts_response = client.get(
        f"/api/user/{scenario['student_b']}/posts",
        headers=scenario["student_a_headers"],
    )

    assert classes_response.status_code == 403
    assert profile_response.status_code == 200
    assert profile_response.json()["email"] is None
    assert all(post["class_id"] != scenario["class_b"] for post in posts_response.json())


def test_shared_profile_does_not_disclose_unshared_class_ids_or_email(client, authorization_scenario):
    scenario = authorization_scenario
    response = client.get(
        f"/api/user/profile/{scenario['student_b']}",
        headers=scenario["student_a_headers"],
    )

    assert response.status_code == 200
    assert response.json()["email"] is None
    assert response.json()["class_ids"] == [scenario["class_a"]]


def test_unrelated_user_lookup_is_denied(client, authorization_scenario):
    scenario = authorization_scenario
    response = client.get(
        f"/api/user/id/{scenario['teacher_b']}",
        headers=scenario["student_a_headers"],
    )

    _assert_denied(response)


def test_saved_posts_omit_classes_the_user_cannot_access(client, authorization_scenario):
    scenario = authorization_scenario
    response = client.get("/api/user/saved-posts", headers=scenario["student_a_headers"])

    assert response.status_code == 200
    assert response.json() == []


def test_student_submission_listing_contains_only_their_own_work(client, authorization_scenario):
    scenario = authorization_scenario
    response = client.get(
        (
            f"/api/classes/{scenario['class_a']}/assignments/"
            f"{scenario['assignment_a']}/submissions"
        ),
        headers=scenario["student_a_headers"],
    )

    assert response.status_code == 200
    assert [submission["id"] for submission in response.json()] == [scenario["submission_a"]]
    serialized = response.text
    assert "Student Alpha private submission" in serialized
    assert "student-alpha-private-ai" in serialized
    assert "Student Beta private submission" not in serialized
    assert "student-beta-private-ai" not in serialized
    assert "student-b@example.com" not in serialized


def test_student_cannot_read_or_reply_to_peer_submission(client, authorization_scenario):
    scenario = authorization_scenario
    replies_url = (
        f"/api/classes/{scenario['class_a']}/assignments/{scenario['assignment_a']}"
        f"/submissions/{scenario['submission_b']}/replies"
    )

    list_response = client.get(replies_url, headers=scenario["student_a_headers"])
    create_response = client.post(
        replies_url,
        headers=scenario["student_a_headers"],
        json={"content": "I should not see or join this thread"},
    )

    _assert_denied(list_response)
    _assert_denied(create_response)


def test_student_can_read_and_reply_to_own_submission(client, authorization_scenario):
    scenario = authorization_scenario
    replies_url = (
        f"/api/classes/{scenario['class_a']}/assignments/{scenario['assignment_a']}"
        f"/submissions/{scenario['submission_a']}/replies"
    )

    list_response = client.get(replies_url, headers=scenario["student_a_headers"])
    create_response = client.post(
        replies_url,
        headers=scenario["student_a_headers"],
        json={"content": "Question about my own work"},
    )

    assert list_response.status_code == 200
    assert create_response.status_code == 200
    assert create_response.json()["content"] == "Question about my own work"


@pytest.mark.parametrize(
    ("method", "path_template", "json_body"),
    [
        (
            "post",
            "/api/classes/{class_a}/assignments",
            {
                "title": "Forged assignment",
                "description": "not allowed",
                "due_date": "2030-01-01T00:00:00Z",
            },
        ),
        (
            "put",
            "/api/classes/{class_a}/assignments/{assignment_a}",
            {
                "title": "Forged update",
                "description": "not allowed",
                "due_date": "2030-01-01T00:00:00Z",
            },
        ),
        (
            "get",
            "/api/classes/{class_a}/assignments/{assignment_a}/submissions",
            None,
        ),
        (
            "get",
            (
                "/api/classes/{class_a}/assignments/{assignment_a}/submissions/"
                "{submission_a}/replies"
            ),
            None,
        ),
        (
            "post",
            (
                "/api/classes/{class_a}/assignments/{assignment_a}/submissions/"
                "{submission_a}/replies"
            ),
            {"content": "not allowed"},
        ),
    ],
)
def test_other_teacher_cannot_access_assignment_or_submission_resources(
    client,
    authorization_scenario,
    method,
    path_template,
    json_body,
):
    scenario = authorization_scenario
    kwargs = {"headers": scenario["teacher_b_headers"]}
    if json_body is not None:
        kwargs["json"] = json_body
    response = getattr(client, method)(path_template.format(**scenario), **kwargs)

    _assert_denied(response)


def test_owning_teacher_can_review_all_class_submissions_with_private_analysis(
    client,
    authorization_scenario,
):
    scenario = authorization_scenario
    response = client.get(
        (
            f"/api/classes/{scenario['class_a']}/assignments/"
            f"{scenario['assignment_a']}/submissions"
        ),
        headers=scenario["teacher_a_headers"],
    )

    assert response.status_code == 200
    assert {submission["id"] for submission in response.json()} == {
        scenario["submission_a"],
        scenario["submission_b"],
    }
    assert "student-alpha-private-ai" in response.text
    assert "student-beta-private-ai" in response.text


def test_owning_teacher_notes_persist_and_are_returned_only_in_owned_student_details(
    client,
    authorization_scenario,
):
    scenario = authorization_scenario
    notes_url = (
        f"/api/classes/{scenario['class_a']}/students/{scenario['student_a']}/notes"
    )
    details_url = (
        f"/api/classes/{scenario['class_a']}/students/{scenario['student_a']}"
    )

    update_response = client.put(
        notes_url,
        headers=scenario["teacher_a_headers"],
        json={"notes": "Private support plan"},
    )
    details_response = client.get(details_url, headers=scenario["teacher_a_headers"])

    assert update_response.status_code == 200
    assert details_response.status_code == 200
    assert details_response.json()["teacher_notes"] == "Private support plan"


def test_owning_teacher_can_delete_a_populated_class_transactionally(client, authorization_scenario):
    scenario = authorization_scenario
    try:
        response = client.delete(
            f"/api/classes/{scenario['class_a']}",
            headers=scenario["teacher_a_headers"],
        )
    except Exception as exc:  # pragma: no cover - converted into a useful RED assertion
        pytest.fail(f"populated class deletion raised {type(exc).__name__}: {exc}")

    assert response.status_code == 200
    db = SessionLocal()
    try:
        assert db.get(models.Class, scenario["class_a"]) is None
        assert (
            db.query(models.Blog).filter(models.Blog.class_id == scenario["class_a"]).count()
            == 0
        )
        assert (
            db.query(models.Assignment)
            .filter(models.Assignment.class_id == scenario["class_a"])
            .count()
            == 0
        )
        assert (
            db.query(models.ClassEnrollment)
            .filter(models.ClassEnrollment.class_id == scenario["class_a"])
            .count()
            == 0
        )
    finally:
        db.close()


def test_student_cannot_join_an_archived_class(client, authorization_scenario):
    scenario = authorization_scenario
    archive_response = client.put(
        f"/api/classes/{scenario['class_b']}/archive",
        headers=scenario["teacher_b_headers"],
    )
    assert archive_response.status_code == 200

    response = client.post(
        "/api/student/join-class",
        headers=scenario["student_a_headers"],
        json={"access_code": "BETA22"},
    )

    assert response.status_code in {404, 409}


def test_archived_class_rejects_content_mutations(client, authorization_scenario):
    scenario = authorization_scenario
    deletable_post = client.post(
        f"/api/classes/{scenario['class_a']}/posts",
        headers=scenario["student_a_headers"],
        json={"title": "Archive fixture", "content": "must remain after archive"},
    )
    assert deletable_post.status_code == 200

    archive_response = client.put(
        f"/api/classes/{scenario['class_a']}/archive",
        headers=scenario["teacher_a_headers"],
    )
    assert archive_response.status_code == 200

    responses = [
        client.put(
            f"/api/classes/{scenario['class_a']}/posts/{scenario['post_a']}",
            headers=scenario["student_a_headers"],
            json={"title": "Changed while archived", "content": "must not persist"},
        ),
        client.delete(
            f"/api/classes/{scenario['class_a']}/posts/{deletable_post.json()['id']}",
            headers=scenario["student_a_headers"],
        ),
        client.post(
            f"/api/classes/{scenario['class_a']}/assignments",
            headers=scenario["teacher_a_headers"],
            json={
                "title": "Archived assignment",
                "description": "must not persist",
                "due_date": "2030-01-01T00:00:00Z",
            },
        ),
        client.put(
            f"/api/classes/{scenario['class_a']}/assignments/{scenario['assignment_a']}",
            headers=scenario["teacher_a_headers"],
            json={
                "title": "Changed while archived",
                "description": "must not persist",
                "due_date": "2030-01-01T00:00:00Z",
            },
        ),
        client.put(
            f"/api/assignments/{scenario['assignment_a']}/draft",
            headers=scenario["student_a_headers"],
            json={"content": "must not persist"},
        ),
        client.post(
            f"/api/assignments/{scenario['assignment_a']}/submit",
            headers=scenario["student_a_headers"],
            json={"content": "must not persist"},
        ),
        client.post(
            (
                f"/api/classes/{scenario['class_a']}/assignments/"
                f"{scenario['assignment_a']}/submissions/{scenario['submission_a']}/replies"
            ),
            headers=scenario["teacher_a_headers"],
            json={"content": "must not persist"},
        ),
    ]

    assert [response.status_code for response in responses] == [409] * len(responses)


@pytest.mark.parametrize(
    ("path_template", "payload"),
    [
        (
            "/api/classes/{class_a}/posts",
            {"title": "x" * 201, "content": "bounded content"},
        ),
        (
            "/api/classes/{class_a}/posts",
            {"title": "Bounded title", "content": "x" * 100_001},
        ),
        (
            "/api/classes/{class_a}/posts",
            {
                "title": "Bounded title",
                "content": "content",
                "media": [{"type": "image", "url": "/api/uploads/a.png"}] * 21,
            },
        ),
        (
            "/api/classes/{class_a}/posts",
            {
                "title": "Malformed nested payload",
                "content": "content",
                "code_snippets": [{"language": "python"}],
            },
        ),
    ],
)
def test_oversized_or_malformed_post_bodies_are_rejected_before_persistence(
    client,
    authorization_scenario,
    path_template,
    payload,
):
    scenario = authorization_scenario
    db = SessionLocal()
    try:
        before = db.query(models.Blog).count()
    finally:
        db.close()

    response = client.post(
        path_template.format(**scenario),
        headers=scenario["student_a_headers"],
        json=payload,
    )

    assert response.status_code == 422
    db = SessionLocal()
    try:
        assert db.query(models.Blog).count() == before
    finally:
        db.close()


@pytest.mark.parametrize(
    ("method", "path_template", "payload"),
    [
        (
            "post",
            "/api/classes/{class_a}/assignments",
            {
                "title": "x" * 201,
                "description": "bounded",
                "due_date": "2030-01-01T00:00:00Z",
            },
        ),
        (
            "post",
            "/api/classes/{class_a}/assignments",
            {
                "title": "Bounded assignment",
                "description": "x" * 50_001,
                "due_date": "2030-01-01T00:00:00Z",
            },
        ),
        (
            "put",
            "/api/assignments/{assignment_a}/draft",
            {"content": "x" * 100_001},
        ),
        (
            "post",
            "/api/assignments/{assignment_a}/submit",
            {"content": "x" * 100_001},
        ),
        (
            "post",
            (
                "/api/classes/{class_a}/assignments/{assignment_a}/submissions/"
                "{submission_a}/replies"
            ),
            {"content": "x" * 10_001},
        ),
    ],
)
def test_oversized_assignment_bodies_are_rejected(
    client,
    authorization_scenario,
    method,
    path_template,
    payload,
):
    scenario = authorization_scenario
    headers = (
        scenario["teacher_a_headers"]
        if "/classes/" in path_template and path_template.endswith("assignments")
        else scenario["student_a_headers"]
    )
    response = getattr(client, method)(
        path_template.format(**scenario),
        headers=headers,
        json=payload,
    )

    assert response.status_code == 422


@pytest.mark.parametrize("content", ["", "   ", "x" * 10_001])
def test_empty_or_oversized_comment_bodies_are_rejected(client, authorization_scenario, content):
    scenario = authorization_scenario
    response = client.post(
        f"/api/classes/{scenario['class_a']}/posts/{scenario['post_a']}/comments",
        headers=scenario["student_a_headers"],
        json={"content": content},
    )

    assert response.status_code == 422


def test_oversized_profile_body_and_privilege_fields_are_rejected(client, authorization_scenario):
    scenario = authorization_scenario
    oversized = client.post(
        "/api/user/update-profile",
        headers=scenario["student_a_headers"],
        json={"bio": "x" * 501},
    )
    privilege_field = client.post(
        "/api/user/update-profile",
        headers=scenario["student_a_headers"],
        json={"role": "ADMIN"},
    )

    assert oversized.status_code == 422
    assert privilege_field.status_code == 422


def test_internal_profile_errors_do_not_disclose_database_details(
    client,
    authorization_scenario,
    monkeypatch,
):
    def fail_commit(_session):
        raise RuntimeError("postgresql://private-user:private-password@database")

    monkeypatch.setattr("sqlalchemy.orm.Session.commit", fail_commit)
    response = client.post(
        "/api/user/update-profile",
        headers=authorization_scenario["student_a_headers"],
        json={"bio": "Updated bio"},
    )

    assert response.status_code == 500
    assert "private-password" not in response.text
    assert response.json() == {"detail": "Failed to update profile"}


@pytest.mark.parametrize(
    "subscription",
    [
        {"endpoint": f"https://push.example/{'x' * 1_025}", "keys": {"p256dh": "a", "auth": "b"}},
        {"endpoint": "http://push.example/sub", "keys": {"p256dh": "a", "auth": "b"}},
        {"endpoint": "https://127.0.0.1/sub", "keys": {"p256dh": "a", "auth": "b"}},
        {"endpoint": "https://10.0.0.8/sub", "keys": {"p256dh": "a", "auth": "b"}},
        {"endpoint": "https://[::1]/sub", "keys": {"p256dh": "a", "auth": "b"}},
        {"endpoint": "https://attacker.example/sub", "keys": {"p256dh": "a", "auth": "b"}},
        {"endpoint": "https://push.example/sub", "keys": {"p256dh": "a" * 256, "auth": "b"}},
        {"endpoint": "https://push.example/sub", "keys": {"p256dh": "a", "auth": "b" * 256}},
        {
            "endpoint": "https://push.example/sub",
            "keys": {"p256dh": "a", "auth": "b"},
            "user_id": 999,
        },
    ],
)
def test_push_subscription_payloads_are_bounded_and_forbid_forged_fields(
    client,
    authorization_scenario,
    subscription,
):
    response = client.post(
        "/api/push/subscribe",
        headers=authorization_scenario["student_a_headers"],
        json={"subscription": subscription},
    )

    assert response.status_code == 422


def test_web_push_delivery_uses_a_bounded_network_timeout(monkeypatch):
    captured = {}

    def fake_webpush(**kwargs):
        captured.update(kwargs)
        return True

    monkeypatch.setattr(main, "WEB_PUSH_ENABLED", True)
    monkeypatch.setattr(main, "webpush", fake_webpush)
    subscription = models.PushSubscription(
        endpoint="https://fcm.googleapis.com/fcm/send/test",
        p256dh="test-key",
        auth="test-auth",
    )

    assert main._send_web_push(subscription, {"title": "Bounded"}) is True
    assert 0 < captured["timeout"] <= 10


def test_push_subscription_endpoint_cannot_be_taken_over_by_another_user(
    client,
    authorization_scenario,
    monkeypatch,
):
    scenario = authorization_scenario
    endpoint = "https://fcm.googleapis.com/fcm/send/private-device-endpoint"
    db = SessionLocal()
    try:
        db.add(
            models.PushSubscription(
                user_id=scenario["student_b"],
                endpoint=endpoint,
                p256dh="student-b-key",
                auth="student-b-auth",
            )
        )
        db.commit()
    finally:
        db.close()

    monkeypatch.setattr(main, "WEB_PUSH_ENABLED", True)
    response = client.post(
        "/api/push/subscribe",
        headers=scenario["student_a_headers"],
        json={
            "subscription": {
                "endpoint": endpoint,
                "keys": {"p256dh": "forged-key", "auth": "forged-auth"},
            }
        },
    )

    assert response.status_code in {403, 409}
    db = SessionLocal()
    try:
        subscription = db.query(models.PushSubscription).filter_by(endpoint=endpoint).one()
        assert subscription.user_id == scenario["student_b"]
        assert subscription.p256dh == "student-b-key"
    finally:
        db.close()


def test_password_reset_is_enumeration_safe_and_rate_limited_per_account(
    client,
    authorization_scenario,
    monkeypatch,
):
    scenario = authorization_scenario
    sent_to = []
    monkeypatch.setattr(
        main,
        "send_password_reset_email",
        lambda email, _token: sent_to.append(email) or True,
    )

    unknown = client.post(
        "/api/auth/forgot-password",
        json={"email": "unknown-student@example.com"},
    )
    first = client.post(
        "/api/auth/forgot-password",
        json={"email": "student-a@example.com"},
    )
    repeated = client.post(
        "/api/auth/forgot-password",
        json={"email": "student-a@example.com"},
    )

    assert unknown.status_code == first.status_code == repeated.status_code == 202
    assert unknown.json() == first.json() == repeated.json()
    # Delivery is decoupled from the public request so SMTP latency cannot reveal
    # whether an account exists.
    assert sent_to == []
    assert inspect.iscoroutinefunction(main.forgot_password) is False

    db = SessionLocal()
    try:
        requests = (
            db.query(models.PasswordReset)
            .filter(models.PasswordReset.user_id == scenario["student_a"])
            .all()
        )
        assert len(requests) == 1
        assert requests[0].delivery_status == "PENDING"
        assert requests[0].token is None
        assert requests[0].expires_at is None
    finally:
        db.close()


def test_password_reset_queue_is_concurrency_safe_and_delivers_one_usable_token(
    client,
    authorization_scenario,
    monkeypatch,
):
    delivered = []
    monkeypatch.setattr(
        main,
        "send_password_reset_email",
        lambda email, token: delivered.append((email, token)) or True,
    )

    def request_reset(_index):
        return client.post(
            "/api/auth/forgot-password",
            json={"email": "student-a@example.com"},
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        responses = list(executor.map(request_reset, range(16)))

    assert {response.status_code for response in responses} == {202}
    db = SessionLocal()
    try:
        queued = (
            db.query(models.PasswordReset)
            .filter(models.PasswordReset.user_id == authorization_scenario["student_a"])
            .all()
        )
        assert len(queued) == 1
        assert queued[0].delivery_status == "PENDING"
    finally:
        db.close()

    main._dispatch_password_reset_emails_once()

    assert len(delivered) == 1
    recipient, raw_token = delivered[0]
    assert recipient == "student-a@example.com"
    db = SessionLocal()
    try:
        queued = (
            db.query(models.PasswordReset)
            .filter(models.PasswordReset.user_id == authorization_scenario["student_a"])
            .one()
        )
        assert queued.delivery_status == "DELIVERED"
        assert queued.token == hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        assert queued.token != raw_token
        assert queued.expires_at is not None
    finally:
        db.close()

    reset = client.post(
        "/api/auth/reset-password",
        json={
            "token": raw_token,
            "new_password": "a newly rotated password",
        },
    )
    assert reset.status_code == 200


def test_password_reset_token_can_only_be_consumed_once_concurrently(
    client,
    authorization_scenario,
    monkeypatch,
):
    del authorization_scenario
    delivered = []
    monkeypatch.setattr(
        main,
        "send_password_reset_email",
        lambda _email, token: delivered.append(token) or True,
    )
    queued = client.post(
        "/api/auth/forgot-password",
        json={"email": "student-a@example.com"},
    )
    assert queued.status_code == 202
    main._dispatch_password_reset_emails_once()
    assert len(delivered) == 1

    passwords = ["first concurrent password", "second concurrent password"]
    password_hash_barrier = threading.Barrier(2)
    real_hash_password = main.hash_password

    def synchronized_hash(password):
        password_hash_barrier.wait(timeout=10)
        return real_hash_password(password)

    monkeypatch.setattr(main, "hash_password", synchronized_hash)

    def consume(password):
        response = client.post(
            "/api/auth/reset-password",
            json={"token": delivered[0], "new_password": password},
        )
        return response.status_code, password

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(consume, passwords))

    assert sorted(status_code for status_code, _password in results) == [200, 400]
    winning_password = next(password for status_code, password in results if status_code == 200)
    login = client.post(
        "/api/auth/login",
        json={"email": "student-a@example.com", "password": winning_password},
    )
    assert login.status_code == 200


def test_password_reset_email_requires_tls_timeout_and_context_cleanup(monkeypatch):
    events = []
    delivered_message = []

    class FakeSMTP:
        def __init__(self, host, port, *, timeout):
            events.append(("connect", host, port, timeout))

        def __enter__(self):
            events.append(("enter",))
            return self

        def __exit__(self, exc_type, exc, traceback):
            events.append(("exit", exc_type))

        def starttls(self, *, context):
            events.append(("starttls", context is not None))

        def login(self, username, password):
            events.append(("login", bool(username), bool(password)))

        def sendmail(self, sender, recipient, message):
            events.append(("sendmail", sender, recipient, bool(message)))
            delivered_message.append(message)

    monkeypatch.setattr(main.smtplib, "SMTP", FakeSMTP)

    assert main.send_password_reset_email("student@example.com", "private-token") is True
    assert events[0][0] == "connect"
    assert 0 < events[0][3] <= 10
    assert [event[0] for event in events] == [
        "connect",
        "enter",
        "starttls",
        "login",
        "sendmail",
        "exit",
    ]
    parsed_message = message_from_string(delivered_message[0])
    html = next(part for part in parsed_message.walk() if part.get_content_type() == "text/html")
    decoded_html = html.get_payload(decode=True).decode(html.get_content_charset() or "utf-8")
    assert "/reset-password#token=private-token" in decoded_html
    assert "/reset-password?token=" not in decoded_html


def test_password_reset_smtp_failures_do_not_log_secrets(monkeypatch, capsys):
    class FailingSMTP:
        def __init__(self, _host, _port, *, timeout):
            del timeout

        def __enter__(self):
            raise RuntimeError("smtp-password-and-reset-token")

        def __exit__(self, exc_type, exc, traceback):
            return False

    monkeypatch.setattr(main.smtplib, "SMTP", FailingSMTP)

    assert main.send_password_reset_email("student@example.com", "private-token") is False
    captured = capsys.readouterr()
    assert "smtp-password" not in captured.out
    assert "smtp-password" not in captured.err
    assert "private-token" not in captured.out
    assert "private-token" not in captured.err


def test_password_reset_delivery_worker_removes_token_on_failure(
    client,
    authorization_scenario,
    monkeypatch,
):
    monkeypatch.setattr(main, "send_password_reset_email", lambda *_args: False)

    response = client.post(
        "/api/auth/forgot-password",
        json={"email": "student-a@example.com"},
    )

    assert response.status_code == 202
    main._dispatch_password_reset_emails_once()
    db = SessionLocal()
    try:
        failed = (
            db.query(models.PasswordReset)
            .filter(models.PasswordReset.user_id == authorization_scenario["student_a"])
            .one()
        )
        assert failed.delivery_status == "FAILED"
        assert failed.token is None
        assert failed.expires_at is None
    finally:
        db.close()


def test_student_and_teacher_class_social_journey(client, authorization_scenario):
    scenario = authorization_scenario
    create_class_response = client.post(
        "/api/classes",
        headers=scenario["teacher_a_headers"],
        json={"name": "Journey Literature", "description": "End-to-end role journey"},
    )
    assert create_class_response.status_code == 200, create_class_response.text
    created_class = create_class_response.json()
    class_id = created_class["id"]

    join_response = client.post(
        "/api/student/join-class",
        headers=scenario["student_a_headers"],
        json={"access_code": created_class["access_code"]},
    )
    settings_response = client.put(
        "/api/user/settings",
        headers=scenario["student_a_headers"],
        json={"editorFontSize": "large"},
    )
    assert join_response.status_code == 200
    assert settings_response.status_code == 200
    assert settings_response.json()["editorFontSize"] == "large"

    post_response = client.post(
        f"/api/classes/{class_id}/posts",
        headers=scenario["student_a_headers"],
        json={
            "title": "Journey post",
            "content": "<p>Journey content</p>",
            "code_snippets": [{"language": "python", "code": "print('safe')"}],
            "polls": [{"options": ["Option A", "Option B"]}],
        },
    )
    assert post_response.status_code == 200, post_response.text
    post_id = post_response.json()["id"]

    feed_response = client.get(
        f"/api/classes/{class_id}/posts",
        headers=scenario["student_a_headers"],
    )
    assert feed_response.status_code == 200
    assert feed_response.json()[0]["id"] == post_id

    like_response = client.post(
        f"/api/classes/{class_id}/posts/{post_id}/like",
        headers=scenario["student_a_headers"],
    )
    comment_response = client.post(
        f"/api/classes/{class_id}/posts/{post_id}/comments",
        headers=scenario["student_a_headers"],
        json={"content": "Journey comment"},
    )
    assert like_response.status_code == 200
    assert like_response.json()["action"] == "liked"
    assert comment_response.status_code == 200

    teacher_details = client.get(
        f"/api/classes/{class_id}/details",
        headers=scenario["teacher_a_headers"],
    )
    teacher_roster = client.get(
        f"/api/classes/{class_id}/students",
        headers=scenario["teacher_a_headers"],
    )
    teacher_student_details = client.get(
        f"/api/classes/{class_id}/students/{scenario['student_a']}",
        headers=scenario["teacher_a_headers"],
    )
    teacher_student_posts = client.get(
        f"/api/classes/{class_id}/students/{scenario['student_a']}/posts",
        headers=scenario["teacher_a_headers"],
    )
    assert teacher_details.status_code == 200
    assert teacher_details.json()["access_code"] == created_class["access_code"]
    assert teacher_roster.status_code == 200
    assert teacher_roster.json()[0]["email"] == "student-a@example.com"
    assert teacher_student_details.status_code == 200
    assert teacher_student_posts.status_code == 200
    assert teacher_student_posts.json()[0]["title"] == "Journey post"

    archive_response = client.put(
        f"/api/classes/{class_id}/archive",
        headers=scenario["teacher_a_headers"],
    )
    archived_post_response = client.post(
        f"/api/classes/{class_id}/posts",
        headers=scenario["student_a_headers"],
        json={"title": "Blocked while archived", "content": "blocked"},
    )
    restore_response = client.put(
        f"/api/classes/{class_id}/restore",
        headers=scenario["teacher_a_headers"],
    )
    delete_response = client.delete(
        f"/api/classes/{class_id}",
        headers=scenario["teacher_a_headers"],
    )
    assert archive_response.status_code == 200
    assert archived_post_response.status_code == 409
    assert restore_response.status_code == 200
    assert delete_response.status_code == 200


def test_student_and_teacher_assignment_journey(client, authorization_scenario):
    scenario = authorization_scenario
    assignment_response = client.post(
        f"/api/classes/{scenario['class_a']}/assignments",
        headers=scenario["teacher_a_headers"],
        json={
            "title": "Journey assignment",
            "description": "Write a private response",
            "due_date": "2030-01-01T00:00:00Z",
            "allow_late": True,
            "visibility": "class",
        },
    )
    assert assignment_response.status_code == 200
    assignment_id = assignment_response.json()["id"]

    save_draft_response = client.put(
        f"/api/assignments/{assignment_id}/draft",
        headers=scenario["student_a_headers"],
        json={"content": "Private journey draft"},
    )
    get_draft_response = client.get(
        f"/api/assignments/{assignment_id}/draft",
        headers=scenario["student_a_headers"],
    )
    assert save_draft_response.status_code == 200
    assert get_draft_response.status_code == 200
    assert get_draft_response.json()["content"] == "Private journey draft"

    submit_response = client.post(
        f"/api/assignments/{assignment_id}/submit",
        headers=scenario["student_a_headers"],
        json={"content": "Private journey submission"},
    )
    assert submit_response.status_code == 200
    submission_id = submit_response.json()["id"]

    teacher_submissions = client.get(
        f"/api/classes/{scenario['class_a']}/assignments/{assignment_id}/submissions",
        headers=scenario["teacher_a_headers"],
    )
    reply_url = (
        f"/api/classes/{scenario['class_a']}/assignments/{assignment_id}"
        f"/submissions/{submission_id}/replies"
    )
    teacher_reply = client.post(
        reply_url,
        headers=scenario["teacher_a_headers"],
        json={"content": "Private teacher response"},
    )
    student_replies = client.get(reply_url, headers=scenario["student_a_headers"])

    assert teacher_submissions.status_code == 200
    assert teacher_submissions.json()[0]["content"] == "Private journey submission"
    assert teacher_reply.status_code == 200
    assert student_replies.status_code == 200
    assert student_replies.json()[0]["content"] == "Private teacher response"
