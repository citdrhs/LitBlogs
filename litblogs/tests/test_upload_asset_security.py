import asyncio
import hashlib
import inspect
import io
import os
import stat
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile
from pydantic import ValidationError
from sqlalchemy import String, func
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable
from test_auth_security import _production_settings_data
from test_content_security import PDF_BYTES, PNG_BYTES

import config
import main
import models
import schemas
import upload_assets
from config import Settings
from database import SessionLocal

GIB = 1024 * 1024 * 1024


def test_registered_object_path_rejects_noncanonical_keys(tmp_path):
    with pytest.raises(ValueError, match="storage key"):
        upload_assets.registered_object_path(tmp_path, "../outside.png")


def test_registered_object_path_rejects_linked_object_even_inside_root(tmp_path):
    target_key = f"objects/b1/{'b1' + ('1' * 30)}.png"
    linked_key = f"objects/b2/{'b2' + ('2' * 30)}.png"
    target = tmp_path / target_key
    linked = tmp_path / linked_key
    target.parent.mkdir(parents=True)
    linked.parent.mkdir(parents=True)
    target.write_bytes(PNG_BYTES)
    try:
        linked.symlink_to(target)
    except OSError:
        pytest.skip("file symlinks are unavailable on this platform")

    with pytest.raises(ValueError, match="storage key"):
        upload_assets.registered_object_path(tmp_path, linked_key)


def test_registered_object_path_checks_each_component_for_links(monkeypatch, tmp_path):
    key = f"objects/b3/{'b3' + ('3' * 30)}.png"
    candidate = tmp_path / key
    candidate.parent.mkdir(parents=True)
    candidate.write_bytes(PNG_BYTES)
    original_is_symlink = Path.is_symlink
    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda path: path == candidate or original_is_symlink(path),
    )

    with pytest.raises(ValueError, match="storage key"):
        upload_assets.registered_object_path(tmp_path, key)


@pytest.mark.parametrize(
    "stored_payload",
    [PNG_BYTES + b"extra", PNG_BYTES[:-1] + b"X"],
    ids=["size-mismatch", "digest-mismatch"],
)
def test_serving_registered_object_requires_exact_size_and_digest(
    client,
    monkeypatch,
    tmp_path,
    stored_payload,
):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    storage_key = f"objects/b4/{'b4' + ('4' * 30)}.png"
    stored_path = tmp_path / storage_key
    stored_path.parent.mkdir(parents=True)
    stored_path.write_bytes(stored_payload)

    with SessionLocal() as db:
        owner = _user(db, 104)
        asset = _asset(db, owner_id=owner.id, storage_key=storage_key)
        asset.size_bytes = len(PNG_BYTES)
        asset.sha256_digest = hashlib.sha256(PNG_BYTES).hexdigest()
        db.commit()

    _override_user(_actor(104))
    try:
        response = client.get(f"/api/uploads/{storage_key}")
    finally:
        _clear_user_override()

    assert response.status_code == 404
    assert response.json() == {"detail": "File not found"}


def test_serving_registered_object_uses_registry_safe_path_resolution(
    client,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    storage_key = f"objects/b5/{'b5' + ('5' * 30)}.png"
    stored_path = tmp_path / storage_key
    stored_path.parent.mkdir(parents=True)
    stored_path.write_bytes(PNG_BYTES)

    with SessionLocal() as db:
        owner = _user(db, 105)
        asset = _asset(db, owner_id=owner.id, storage_key=storage_key)
        asset.sha256_digest = hashlib.sha256(PNG_BYTES).hexdigest()
        db.commit()

    resolved_keys = []

    def reject_registered_path(upload_root, candidate_key):
        resolved_keys.append((upload_root, candidate_key))
        raise ValueError("synthetic linked component")

    monkeypatch.setattr(upload_assets, "registered_object_path", reject_registered_path)
    _override_user(_actor(105))
    try:
        response = client.get(f"/api/uploads/{storage_key}")
    finally:
        _clear_user_override()

    assert response.status_code == 404
    assert resolved_keys == [(tmp_path, storage_key)]


def test_finalize_new_upload_fsyncs_objects_root_before_publishing_file(
    monkeypatch,
    tmp_path,
):
    objects_root = tmp_path / "objects"
    objects_root.mkdir()
    object_id = "b6" + ("6" * 30)
    destination_path = objects_root / "b6" / f"{object_id}.png"
    staging_path = tmp_path / ".incoming" / f"{object_id}.part"
    staging_path.parent.mkdir()
    staging_path.write_bytes(PNG_BYTES)
    prepared = main.PreparedUpload(
        staging_path=staging_path,
        destination_path=destination_path,
        url=f"/api/uploads/objects/b6/{object_id}.png",
        filename=f"{object_id}.png",
        original_filename="upload.png",
        size=len(PNG_BYTES),
        spec=main.UPLOAD_TYPE_SPECS[".png"],
        storage_key=f"objects/b6/{object_id}.png",
        sha256_digest=hashlib.sha256(PNG_BYTES).hexdigest(),
    )
    events = []
    original_replace = Path.replace

    def record_replace(source, destination):
        events.append(("replace", Path(destination)))
        return original_replace(source, destination)

    monkeypatch.setattr(Path, "replace", record_replace)
    monkeypatch.setattr(
        main,
        "_fsync_upload_directory",
        lambda path: events.append(("fsync", Path(path))),
    )

    main._finalize_prepared_upload(prepared)

    assert events == [
        ("fsync", objects_root),
        ("replace", destination_path),
        ("fsync", destination_path.parent),
    ]


def test_promoting_registered_staging_fsyncs_objects_root_before_publish(
    monkeypatch,
    tmp_path,
):
    objects_root = tmp_path / "objects"
    objects_root.mkdir()
    object_id = "b7" + ("7" * 30)
    storage_key = f"objects/b7/{object_id}.png"
    staging_path = tmp_path / ".incoming" / f"{object_id}.part"
    staging_path.parent.mkdir()
    staging_path.write_bytes(PNG_BYTES)
    asset = SimpleNamespace(
        storage_key=storage_key,
        size_bytes=len(PNG_BYTES),
        sha256_digest=hashlib.sha256(PNG_BYTES).hexdigest(),
    )
    destination_path = tmp_path / storage_key
    events = []
    original_replace = Path.replace

    def record_replace(source, destination):
        events.append(("replace", Path(destination)))
        return original_replace(source, destination)

    monkeypatch.setattr(Path, "replace", record_replace)
    monkeypatch.setattr(
        upload_assets,
        "_fsync_directory",
        lambda path: events.append(("fsync", Path(path))),
    )

    upload_assets._promote_registered_staging(tmp_path, asset)

    assert events == [
        ("fsync", objects_root),
        ("replace", destination_path),
        ("fsync", destination_path.parent),
    ]


def test_post_asset_extraction_uses_only_final_persisted_semantics():
    image_key = f"objects/a1/{'a1' + ('1' * 30)}.png"
    file_key = f"objects/a2/{'a2' + ('2' * 30)}.pdf"
    image_url = f"/api/uploads/{image_key}"
    file_url = f"/api/uploads/{file_key}"
    content = (
        f'<p>Body</p><img src="{image_url}">'
        f'<a class="file-attachment" href="{file_url}">reading.pdf</a>'
    )

    assert upload_assets.post_asset_keys("<p>Body only</p>") == []
    assert upload_assets.post_asset_keys(content) == [image_key, file_key]


def _user(db, user_id: int, role=models.UserRole.STUDENT):
    user = models.User(
        id=user_id,
        username=f"student{user_id}",
        email=f"student{user_id}@example.com",
        password="not-a-real-password-hash",
        first_name="Test",
        last_name=str(user_id),
        role=role,
    )
    db.add(user)
    db.flush()
    return user


def _class(db, *, class_id: int, teacher_user: models.User, code: str):
    teacher = models.Teacher(
        name=f"Teacher {teacher_user.id}",
        email=teacher_user.email,
        hashed_password="unused",
        user_id=teacher_user.id,
    )
    db.add(teacher)
    db.flush()
    classroom = models.Class(
        id=class_id,
        name=f"Class {class_id}",
        access_code=code,
        teacher_id=teacher.id,
        status="active",
    )
    db.add(classroom)
    db.flush()
    return classroom


def _asset(
    db,
    *,
    owner_id: int | None,
    storage_key: str,
    state: str = "PENDING",
    purpose: str = "POST",
    blog_id: int | None = None,
    size_bytes: int = len(PNG_BYTES),
    created_at: datetime | None = None,
):
    now = created_at or main._utc_now_naive()
    asset = models.UploadAsset(
        storage_key=storage_key,
        owner_user_id=owner_id,
        blog_id=blog_id,
        purpose=purpose,
        state=state,
        original_filename=None if state == "DELETED" else "upload.png",
        media_type="image/png",
        size_bytes=size_bytes,
        sha256_digest="a" * 64,
        created_at=now,
        expires_at=now + timedelta(hours=24) if state == "PENDING" else None,
        bound_at=now if state == "ACTIVE" else None,
        delete_after=now if state == "DELETE_PENDING" else None,
        deleted_at=now if state == "DELETED" else None,
        scan_completed_at=now,
    )
    db.add(asset)
    db.flush()
    return asset


def _override_user(user):
    main.app.dependency_overrides[main.get_current_user] = lambda: user


def _clear_user_override():
    main.app.dependency_overrides.pop(main.get_current_user, None)


def _actor(user_id: int, role=models.UserRole.STUDENT):
    return SimpleNamespace(
        id=user_id,
        role=role,
        disabled_at=None,
        first_name="Test",
        last_name=str(user_id),
        profile_image=None,
    )


def test_upload_asset_registry_has_exact_contract_and_indexes(client):
    table = models.UploadAsset.__table__
    columns = {column.name: column for column in table.columns}
    assert set(columns) == {
        "id",
        "storage_key",
        "owner_user_id",
        "blog_id",
        "purpose",
        "state",
        "original_filename",
        "media_type",
        "size_bytes",
        "sha256_digest",
        "created_at",
        "expires_at",
        "bound_at",
        "delete_after",
        "deleted_at",
        "scan_completed_at",
    }
    assert columns["storage_key"].type.length == 255
    assert columns["original_filename"].type.length == 255
    assert columns["media_type"].type.length == 127
    assert columns["sha256_digest"].type.length == 64
    assert columns["storage_key"].unique is True
    owner_fk = next(iter(columns["owner_user_id"].foreign_keys))
    blog_fk = next(iter(columns["blog_id"].foreign_keys))
    assert owner_fk.ondelete == "SET NULL"
    assert blog_fk.ondelete == "SET NULL"
    assert owner_fk.constraint.name == "fk_upload_assets_owner_user"
    assert blog_fk.constraint.name == "fk_upload_assets_blog"

    indexes = {index.name: index for index in table.indexes}
    assert {
        "ix_upload_assets_owner_state_created",
        "ix_upload_assets_blog_id",
        "ix_upload_assets_expires_at",
        "ix_upload_assets_state_delete_after",
        "uq_upload_assets_active_profile_purpose",
    } <= set(indexes)
    assert indexes["uq_upload_assets_active_profile_purpose"].unique is True

    constraint_sql = " ".join(
        str(constraint.sqltext)
        for constraint in table.constraints
        if hasattr(constraint, "sqltext")
    )
    for expected in (
        "PENDING",
        "ACTIVE",
        "DELETE_PENDING",
        "DELETED",
        "PROFILE_IMAGE",
        "COVER_IMAGE",
        "size_bytes > 0",
        "length(sha256_digest) = 64",
        "substr(storage_key, 9, 2) = substr(storage_key, 12, 2)",
        "scan_completed_at IS NOT NULL",
    ):
        assert expected in constraint_sql

    postgres_ddl = str(
        CreateTable(table).compile(dialect=postgresql.dialect())
    )
    assert "id BIGSERIAL" in postgres_ddl
    assert "sha256_digest CHAR(64)" in postgres_ddl
    assert "state = 'DELETE_PENDING'" in constraint_sql
    assert "blog_id IS NULL" in constraint_sql
    assert "delete_after IS NULL" in constraint_sql
    assert "original_filename IS NULL" in constraint_sql


def test_pending_upload_is_owner_only_and_unmapped_object_is_never_served(
    client,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    with SessionLocal() as db:
        _user(db, 101)
        _user(db, 102)
        _user(db, 103, models.UserRole.ADMIN)
        db.commit()

    _override_user(_actor(101))
    try:
        response = client.post(
            "/api/upload/image",
            files={"file": ("private-name.png", PNG_BYTES, "image/png")},
        )
        assert response.status_code == 200
        url = response.json()["url"]
        key = url.removeprefix("/api/uploads/")
        assert key.startswith("objects/")
        assert "private-name" not in key

        owner_read = client.get(url)
        assert owner_read.status_code == 200

        _override_user(_actor(102))
        assert client.get(url).status_code == 404

        _override_user(_actor(103, models.UserRole.ADMIN))
        delete_url = url.replace("/api/uploads/", "/api/upload/")
        assert client.delete(delete_url).status_code == 404

        rogue_key = "objects/aa/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png"
        rogue_path = tmp_path / rogue_key
        rogue_path.parent.mkdir(parents=True)
        rogue_path.write_bytes(PNG_BYTES)
        assert client.get(f"/api/uploads/{rogue_key}").status_code == 404
    finally:
        _clear_user_override()


def test_post_creation_atomically_binds_pending_asset_and_derives_class_acl(
    client,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    with SessionLocal() as db:
        teacher_user = _user(db, 111, models.UserRole.TEACHER)
        author = _user(db, 112)
        classmate = _user(db, 113)
        _user(db, 114)
        classroom = _class(db, class_id=31, teacher_user=teacher_user, code="AA0031")
        db.add_all(
            [
                models.ClassEnrollment(student_id=author.id, class_id=classroom.id),
                models.ClassEnrollment(student_id=classmate.id, class_id=classroom.id),
            ]
        )
        db.commit()

    _override_user(_actor(112))
    try:
        uploaded = client.post(
            "/api/upload/image",
            files={"file": ("post.png", PNG_BYTES, "image/png")},
        )
        assert uploaded.status_code == 200
        url = uploaded.json()["url"]

        created = client.post(
            "/api/classes/31/posts",
            json={
                "title": "Bound upload",
                "content": "<p>Safe</p>",
                "media": [{"type": "image", "url": url}],
            },
        )
        assert created.status_code == 200
        blog_id = created.json()["id"]

        with SessionLocal() as db:
            asset = db.query(models.UploadAsset).one()
            assert asset.state == "ACTIVE"
            assert asset.blog_id == blog_id
            assert asset.expires_at is None
            assert asset.bound_at is not None

        _override_user(_actor(113))
        assert client.get(url).status_code == 200
        _override_user(_actor(111, models.UserRole.TEACHER))
        assert client.get(url).status_code == 200
        _override_user(_actor(114))
        assert client.get(url).status_code == 404
    finally:
        _clear_user_override()


def test_post_binding_rejects_foreign_or_unmapped_references_without_partial_blog(
    client,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    with SessionLocal() as db:
        teacher_user = _user(db, 121, models.UserRole.TEACHER)
        author = _user(db, 122)
        other = _user(db, 123)
        classroom = _class(db, class_id=32, teacher_user=teacher_user, code="AA0032")
        db.add(models.ClassEnrollment(student_id=author.id, class_id=classroom.id))
        foreign = _asset(
            db,
            owner_id=other.id,
            storage_key="objects/bb/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.png",
        )
        owned = _asset(
            db,
            owner_id=author.id,
            storage_key=f"objects/bc/{'bc' + ('c' * 30)}.png",
        )
        db.commit()
        foreign_url = f"/api/uploads/{foreign.storage_key}"
        bare_owned_key = owned.storage_key

    _override_user(_actor(122))
    try:
        for url in (
            foreign_url,
            "/api/uploads/objects/cc/cccccccccccccccccccccccccccccccc.png",
        ):
            response = client.post(
                "/api/classes/32/posts",
                json={
                    "title": "Must fail",
                    "content": "<p>Safe</p>",
                    "media": [{"type": "image", "url": url}],
                },
            )
            assert response.status_code in {400, 409}

        bare_reference = client.post(
            "/api/classes/32/posts",
            json={
                "title": "Bare key must fail",
                "content": "<p>Safe</p>",
                "media": [{"type": "image", "url": bare_owned_key}],
            },
        )
        assert bare_reference.status_code == 400
        with SessionLocal() as db:
            assert db.query(models.Blog).count() == 0
    finally:
        _clear_user_override()


def test_post_edit_and_delete_queue_active_assets_and_block_direct_delete(
    client,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    with SessionLocal() as db:
        teacher_user = _user(db, 125, models.UserRole.TEACHER)
        author = _user(db, 126)
        classroom = _class(db, class_id=33, teacher_user=teacher_user, code="AA0033")
        db.add(models.ClassEnrollment(student_id=author.id, class_id=classroom.id))
        blog = models.Blog(title="With file", content="safe", owner_id=author.id, class_id=33)
        db.add(blog)
        db.flush()
        asset = _asset(
            db,
            owner_id=author.id,
            storage_key="objects/ad/addddddddddddddddddddddddddddddd.png",
            state="ACTIVE",
            blog_id=blog.id,
        )
        blog_id = blog.id
        db.commit()
        url = f"/api/uploads/{asset.storage_key}"

    _override_user(_actor(126))
    try:
        assert client.delete(url.replace("/api/uploads/", "/api/upload/")).status_code == 409

        edited = client.put(
            f"/api/classes/33/posts/{blog_id}",
            json={"title": "No file", "content": "<p>updated</p>"},
        )
        assert edited.status_code == 200
        with SessionLocal() as db:
            assert db.query(models.UploadAsset).one().state == "DELETE_PENDING"
            assert db.query(models.UploadAsset).one().blog_id is None
    finally:
        _clear_user_override()


def test_teacher_moderation_locks_post_owner_and_cannot_bind_teacher_asset(
    client,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    with SessionLocal() as db:
        teacher_user = _user(db, 161, models.UserRole.TEACHER)
        student = _user(db, 162)
        classroom = _class(db, class_id=36, teacher_user=teacher_user, code="AA0036")
        db.add(models.ClassEnrollment(student_id=student.id, class_id=classroom.id))
        blog = models.Blog(
            title="Student work",
            content="<p>original</p>",
            owner_id=student.id,
            class_id=classroom.id,
        )
        db.add(blog)
        db.flush()
        teacher_asset = _asset(
            db,
            owner_id=teacher_user.id,
            storage_key=f"objects/d1/{'d1' + ('1' * 30)}.png",
        )
        student_asset = _asset(
            db,
            owner_id=student.id,
            storage_key=f"objects/d0/{'d0' + ('0' * 30)}.png",
        )
        for asset in (teacher_asset, student_asset):
            asset_path = tmp_path / asset.storage_key
            asset_path.parent.mkdir(parents=True)
            asset_path.write_bytes(PNG_BYTES)
        blog_id = blog.id
        teacher_url = f"/api/uploads/{teacher_asset.storage_key}"
        student_url = f"/api/uploads/{student_asset.storage_key}"
        db.commit()

    locked_owner_ids = []
    original_lock_owner = main._lock_upload_owner

    def recording_lock_owner(db, owner_user_id):
        locked_owner_ids.append(owner_user_id)
        return original_lock_owner(db, owner_user_id)

    monkeypatch.setattr(main, "_lock_upload_owner", recording_lock_owner)
    _override_user(_actor(161, models.UserRole.TEACHER))
    try:
        response = client.put(
            f"/api/classes/36/posts/{blog_id}",
            json={
                "title": "Teacher edit",
                "content": "<p>moderated</p>",
                "media": [{"type": "image", "url": teacher_url}],
            },
        )
        assert response.status_code == 409

        student_pending_response = client.put(
            f"/api/classes/36/posts/{blog_id}",
            json={
                "title": "Teacher edit",
                "content": f'<p>moderated</p><img src="{student_url}">',
            },
        )
        assert student_pending_response.status_code == 409
        assert locked_owner_ids == [162, 162]
        with SessionLocal() as db:
            assert db.get(models.Blog, blog_id).content == "<p>original</p>"
            assert {asset.state for asset in db.query(models.UploadAsset)} == {"PENDING"}
    finally:
        _clear_user_override()


def test_post_binding_handles_postgresql_aware_expiry_with_utc_lifecycle_time(
    tmp_path,
    client,
):
    naive_now = main._utc_now_naive()
    storage_key = f"objects/d7/{'d7' + ('7' * 30)}.png"
    path = tmp_path / storage_key
    path.parent.mkdir(parents=True)
    path.write_bytes(PNG_BYTES)
    with SessionLocal() as db:
        teacher_user = _user(db, 165, models.UserRole.TEACHER)
        owner = _user(db, 166)
        classroom = _class(db, class_id=38, teacher_user=teacher_user, code="AA0038")
        blog = models.Blog(
            title="Aware timestamps",
            content="<p>body</p>",
            owner_id=owner.id,
            class_id=classroom.id,
        )
        db.add(blog)
        db.flush()
        asset = _asset(db, owner_id=owner.id, storage_key=storage_key)
        asset.expires_at = naive_now.replace(tzinfo=UTC) + timedelta(hours=1)

        upload_assets.bind_post_assets(
            db,
            blog=blog,
            actor_user_id=owner.id,
            storage_keys=[storage_key],
            upload_root=tmp_path,
            now=naive_now,
        )

        assert asset.state == "ACTIVE"
        assert asset.bound_at.tzinfo is UTC


def test_post_binding_uses_only_final_sanitized_semantic_media_references(
    client,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    with SessionLocal() as db:
        teacher_user = _user(db, 163, models.UserRole.TEACHER)
        author = _user(db, 164)
        classroom = _class(db, class_id=37, teacher_user=teacher_user, code="AA0037")
        db.add(models.ClassEnrollment(student_id=author.id, class_id=classroom.id))
        storage_keys = {}
        for prefix, label, extension, payload in (
            ("d2", "code", "png", PNG_BYTES),
            ("d3", "stripped", "png", PNG_BYTES),
            ("d4", "image", "png", PNG_BYTES),
            ("d5", "video", "mp4", b"\x00\x00\x00\x18ftypisom"),
            ("d6", "file", "pdf", PDF_BYTES),
        ):
            storage_key = f"objects/{prefix}/{prefix + (prefix[-1] * 30)}.{extension}"
            storage_keys[label] = storage_key
            _asset(
                db,
                owner_id=author.id,
                storage_key=storage_key,
            )
            path = tmp_path / storage_key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        db.commit()

    urls = {
        label: f"/api/uploads/{storage_key}"
        for label, storage_key in storage_keys.items()
    }
    _override_user(_actor(164))
    try:
        response = client.post(
            "/api/classes/37/posts",
            json={
                "title": "Semantic references",
                "content": (
                    f"<pre><code>&lt;img src=&quot;{urls['code']}&quot;&gt;</code></pre>"
                    f"<p>Example only: {urls['code']}</p>"
                    f"<iframe src=\"{urls['stripped']}\"></iframe>"
                    f"<img src=\"{urls['image']}\" alt=\"kept\">"
                    f"<video controls><source src=\"{urls['video']}\" type=\"video/mp4\"></video>"
                    f"<div class=\"file-attachment\" data-file-url=\"{urls['file']}\"></div>"
                ),
            },
        )
        assert response.status_code == 200
        assert "iframe" not in response.json()["content"]
        with SessionLocal() as db:
            states = {
                asset.storage_key: asset.state
                for asset in db.query(models.UploadAsset).all()
            }
            assert states[storage_keys["code"]] == "PENDING"
            assert states[storage_keys["stripped"]] == "PENDING"
            for label in ("image", "video", "file"):
                assert states[storage_keys[label]] == "ACTIVE"
    finally:
        _clear_user_override()


def test_structured_video_reference_is_persisted_before_activation(
    client,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    with SessionLocal() as db:
        teacher_user = _user(db, 165, models.UserRole.TEACHER)
        author = _user(db, 166)
        classroom = _class(db, class_id=38, teacher_user=teacher_user, code="AA0038")
        db.add(models.ClassEnrollment(student_id=author.id, class_id=classroom.id))
        asset = _asset(
            db,
            owner_id=author.id,
            storage_key=f"objects/d7/{'d7' + ('7' * 30)}.mp4",
        )
        path = tmp_path / asset.storage_key
        path.parent.mkdir(parents=True)
        path.write_bytes(b"\x00\x00\x00\x18ftypisom")
        video_url = f"/api/uploads/{asset.storage_key}"
        db.commit()

    _override_user(_actor(166))
    try:
        response = client.post(
            "/api/classes/38/posts",
            json={
                "title": "Structured video",
                "content": "<p>Video reflection</p>",
                "media": [{"type": "video", "url": video_url}],
            },
        )
        assert response.status_code == 200
        assert video_url in response.json()["content"]
        with SessionLocal() as db:
            assert db.query(models.UploadAsset).one().state == "ACTIVE"
    finally:
        _clear_user_override()


def test_post_delete_with_comments_queues_assets_and_deletes_dependencies(
    client,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    with SessionLocal() as db:
        teacher_user = _user(db, 167, models.UserRole.TEACHER)
        author = _user(db, 168)
        classroom = _class(db, class_id=39, teacher_user=teacher_user, code="AA0039")
        db.add(models.ClassEnrollment(student_id=author.id, class_id=classroom.id))
        blog = models.Blog(
            title="Commented post",
            content="<p>Body</p>",
            owner_id=author.id,
            class_id=classroom.id,
        )
        db.add(blog)
        db.flush()
        db.add(models.Comment(content="A comment", user_id=author.id, blog_id=blog.id))
        _asset(
            db,
            owner_id=author.id,
            storage_key=f"objects/d8/{'d8' + ('8' * 30)}.png",
            state="ACTIVE",
            blog_id=blog.id,
        )
        blog_id = blog.id
        db.commit()

    _override_user(_actor(168))
    try:
        response = client.delete(f"/api/classes/39/posts/{blog_id}")
        assert response.status_code == 200
        with SessionLocal() as db:
            assert db.get(models.Blog, blog_id) is None
            assert db.query(models.Comment).count() == 0
            asset = db.query(models.UploadAsset).one()
            assert asset.state == "DELETE_PENDING"
            assert asset.blog_id is None
    finally:
        _clear_user_override()


def test_class_and_account_deletion_queue_owned_assets(client, monkeypatch, tmp_path):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    with SessionLocal() as db:
        teacher_user = _user(db, 127, models.UserRole.TEACHER)
        student = _user(db, 128)
        classroom = _class(db, class_id=34, teacher_user=teacher_user, code="AA0034")
        db.add(models.ClassEnrollment(student_id=student.id, class_id=classroom.id))
        blog = models.Blog(title="Class asset", content="safe", owner_id=student.id, class_id=34)
        db.add(blog)
        db.flush()
        _asset(
            db,
            owner_id=student.id,
            storage_key="objects/ae/aeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee.png",
            state="ACTIVE",
            blog_id=blog.id,
        )
        _asset(
            db,
            owner_id=student.id,
            storage_key="objects/af/afffffffffffffffffffffffffffffff.png",
        )
        db.commit()

    _override_user(_actor(127, models.UserRole.TEACHER))
    try:
        deleted_class = client.delete("/api/classes/34")
        assert deleted_class.status_code == 200
        with SessionLocal() as db:
            class_asset = (
                db.query(models.UploadAsset)
                .filter(models.UploadAsset.storage_key.like("objects/ae/%"))
                .one()
            )
            assert class_asset.state == "DELETE_PENDING"
            assert class_asset.blog_id is None
    finally:
        _clear_user_override()

    _override_user(_actor(128))
    try:
        deleted_account = client.delete("/api/user/account?confirm=DELETE")
        assert deleted_account.status_code == 200
        with SessionLocal() as db:
            assets = db.query(models.UploadAsset).all()
            assert {asset.state for asset in assets} == {"DELETE_PENDING"}
            assert all(asset.owner_user_id is None for asset in assets)
    finally:
        _clear_user_override()


def test_quota_and_success_rate_count_registry_states(client, monkeypatch, tmp_path):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    with SessionLocal() as db:
        _user(db, 131)
        _asset(
            db,
            owner_id=131,
            storage_key="objects/dd/dddddddddddddddddddddddddddddddd.pdf",
            size_bytes=GIB - len(PDF_BYTES) + 1,
        )
        db.commit()

    _override_user(_actor(131))
    try:
        over_quota = client.post(
            "/api/upload/file",
            files={"file": ("reading.pdf", PDF_BYTES, "application/pdf")},
        )
        assert over_quota.status_code == 413
        assert over_quota.json() == {"detail": "Upload quota exceeded"}

        with SessionLocal() as db:
            db.query(models.UploadAsset).delete()
            for index in range(20):
                _asset(
                    db,
                    owner_id=131,
                    storage_key=f"objects/00/{index:032x}.png",
                    state="DELETED",
                    created_at=main._utc_now_naive() - timedelta(minutes=1),
                )
            db.commit()

        rate_limited = client.post(
            "/api/upload/image",
            files={"file": ("next.png", PNG_BYTES, "image/png")},
        )
        assert rate_limited.status_code == 429
        assert rate_limited.json() == {"detail": "Upload rate limit exceeded"}
    finally:
        _clear_user_override()


def test_profile_urls_cannot_be_mutated_and_presets_are_bounded():
    fields = schemas.ProfileUpdate.model_fields
    assert "profile_image" not in fields
    assert "cover_image" not in fields
    assert fields["avatar_id"].annotation is not str
    assert fields["avatar_color"].annotation is not str


def test_profile_replacement_is_atomic_and_old_object_is_queued(client, monkeypatch, tmp_path):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    old_key = "objects/ab/abbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.png"
    with SessionLocal() as db:
        owner = _user(db, 135)
        old = _asset(
            db,
            owner_id=owner.id,
            storage_key=old_key,
            state="ACTIVE",
            purpose="PROFILE_IMAGE",
        )
        owner.profile_image = f"/api/uploads/{old.storage_key}"
        db.commit()
    old_path = tmp_path / old_key
    old_path.parent.mkdir(parents=True)
    old_path.write_bytes(PNG_BYTES)

    _override_user(_actor(135))
    try:
        response = client.post(
            "/api/user/upload-profile-image",
            files={"file": ("new.png", PNG_BYTES, "image/png")},
        )
        assert response.status_code == 200
        new_url = response.json()["image_url"]
        with SessionLocal() as db:
            assets = db.query(models.UploadAsset).order_by(models.UploadAsset.id).all()
            assert [asset.state for asset in assets] == ["DELETE_PENDING", "ACTIVE"]
            assert assets[1].purpose == "PROFILE_IMAGE"
            assert db.get(models.User, 135).profile_image == new_url
        assert old_path.is_file()
    finally:
        _clear_user_override()


def test_profile_commit_acknowledgement_loss_verifies_pointer_and_file(
    client,
    monkeypatch,
    tmp_path,
):
    from upload_scanner import DeterministicUploadScanner

    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(main, "upload_scanner", DeterministicUploadScanner())
    with SessionLocal() as seed:
        owner = _user(seed, 137)
        old_key = f"objects/a7/{'a7' + ('7' * 30)}.png"
        old = _asset(
            seed,
            owner_id=owner.id,
            storage_key=old_key,
            state="ACTIVE",
            purpose="PROFILE_IMAGE",
        )
        owner.profile_image = f"/api/uploads/{old.storage_key}"
        seed.commit()
    old_path = tmp_path / old_key
    old_path.parent.mkdir(parents=True, exist_ok=True)
    old_path.write_bytes(PNG_BYTES)

    db = SessionLocal()
    real_commit = db.commit

    def commit_then_raise():
        real_commit()
        raise RuntimeError("synthetic lost profile commit acknowledgement")

    monkeypatch.setattr(db, "commit", commit_then_raise)
    upload = UploadFile(
        filename="replacement.png",
        file=io.BytesIO(PNG_BYTES),
        headers={"content-type": "image/png"},
    )
    try:
        image_url = asyncio.run(
            main._replace_profile_upload(
                upload,
                purpose="PROFILE_IMAGE",
                profile_field="profile_image",
                db=db,
                current_user=_actor(137),
            )
        )
    finally:
        db.close()

    with SessionLocal() as verify:
        active = verify.query(models.UploadAsset).filter_by(state="ACTIVE").one()
        queued = verify.query(models.UploadAsset).filter_by(state="DELETE_PENDING").one()
        assert active.storage_key in image_url
        assert verify.get(models.User, 137).profile_image == image_url
        assert queued.storage_key == old_key
        assert (tmp_path / active.storage_key).read_bytes() == PNG_BYTES


def test_profile_preset_replaces_registered_cover_without_accepting_raw_url(
    client,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    with SessionLocal() as db:
        owner = _user(db, 136)
        cover = _asset(
            db,
            owner_id=owner.id,
            storage_key="objects/ac/accccccccccccccccccccccccccccccc.png",
            state="ACTIVE",
            purpose="COVER_IMAGE",
        )
        owner.cover_image = f"/api/uploads/{cover.storage_key}"
        db.commit()

    _override_user(_actor(136))
    try:
        rejected = client.post(
            "/api/user/update-profile",
            json={"cover_image": "https://tracker.example/pixel.png"},
        )
        assert rejected.status_code == 422

        accepted = client.post(
            "/api/user/update-profile",
            json={"cover_preset": "classroom-2"},
        )
        assert accepted.status_code == 200
        assert accepted.json()["profile"]["cover_image"] == "/Classroom2.jpeg"
        with SessionLocal() as db:
            assert db.query(models.UploadAsset).one().state == "DELETE_PENDING"
    finally:
        _clear_user_override()


def test_download_compatibility_route_is_removed():
    route_pairs = {
        (method, route.path)
        for route in main.app.routes
        for method in getattr(route, "methods", set())
    }
    assert ("GET", "/api/download") not in route_pairs


def test_cleanup_expires_pending_and_reconciles_delete_pending(monkeypatch, tmp_path, client):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    now = main._utc_now_naive()
    with SessionLocal() as db:
        owner = _user(db, 141)
        expired = _asset(
            db,
            owner_id=owner.id,
            storage_key="objects/fa/faaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png",
            created_at=now - timedelta(hours=25),
        )
        expired.expires_at = now - timedelta(hours=1)
        queued = _asset(
            db,
            owner_id=owner.id,
            storage_key="objects/fb/fbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.png",
            state="DELETE_PENDING",
            created_at=now,
        )
        db.commit()
        for asset in (expired, queued):
            path = tmp_path / asset.storage_key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(PNG_BYTES)

    with SessionLocal() as db:
        result = main.reconcile_upload_assets(db, now=now)
        db.commit()
        assert result == {"queued": 2, "deleted": 2, "failed": 0}
        states = {asset.storage_key: asset.state for asset in db.query(models.UploadAsset)}
        assert set(states.values()) == {"DELETED"}
        assert all(asset.deleted_at is not None for asset in db.query(models.UploadAsset))
        assert all(asset.original_filename is None for asset in db.query(models.UploadAsset))
        assert all(asset.delete_after is None for asset in db.query(models.UploadAsset))
    assert not any(path.is_file() for path in tmp_path.rglob("*"))


def test_delete_pending_cleanup_removes_registered_staging_before_tombstoning(
    monkeypatch,
    tmp_path,
    client,
):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    now = main._utc_now_aware()
    object_id = "fc" + ("c" * 30)
    storage_key = f"objects/fc/{object_id}.png"
    with SessionLocal() as db:
        owner = _user(db, 142)
        asset = _asset(
            db,
            owner_id=owner.id,
            storage_key=storage_key,
            state="DELETE_PENDING",
            created_at=now,
        )
        asset.sha256_digest = __import__("hashlib").sha256(PNG_BYTES).hexdigest()
        db.commit()

    incoming = tmp_path / ".incoming" / f"{object_id}.part"
    incoming.parent.mkdir(parents=True)
    incoming.write_bytes(PNG_BYTES)
    (tmp_path / "objects").mkdir()

    with SessionLocal() as db:
        result = main.reconcile_upload_assets(db, now=now)
        db.commit()
        assert db.query(models.UploadAsset).one().state == "DELETED"

    assert result["deleted"] == 1
    assert not incoming.exists()


def test_reconcile_repairs_registered_staging_and_sweeps_only_old_orphans(
    monkeypatch,
    tmp_path,
    client,
):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    now = main._utc_now_naive()
    object_id = "e1" + ("1" * 30)
    key = f"objects/e1/{object_id}.png"
    with SessionLocal() as db:
        owner = _user(db, 143)
        asset = _asset(db, owner_id=owner.id, storage_key=key)
        asset.sha256_digest = __import__("hashlib").sha256(PNG_BYTES).hexdigest()
        asset.size_bytes = len(PNG_BYTES)
        db.commit()

    incoming = tmp_path / ".incoming" / f"{object_id}.part"
    incoming.parent.mkdir(parents=True, exist_ok=True)
    incoming.write_bytes(PNG_BYTES)
    old_key = f"objects/e2/{'e2' + ('2' * 30)}.png"
    young_key = f"objects/e3/{'e3' + ('3' * 30)}.png"
    old_orphan = tmp_path / old_key
    young_orphan = tmp_path / young_key
    for candidate in (old_orphan, young_orphan):
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_bytes(PNG_BYTES)
    old_timestamp = (now.replace(tzinfo=UTC) - timedelta(hours=25)).timestamp()
    os.utime(old_orphan, (old_timestamp, old_timestamp))

    with SessionLocal() as db:
        main.reconcile_upload_assets(db, now=now)
        db.commit()

    assert (tmp_path / key).read_bytes() == PNG_BYTES
    assert not incoming.exists()
    assert not old_orphan.exists()
    assert young_orphan.exists()


def test_reconcile_replaces_a_corrupt_final_object_with_matching_registered_staging(
    monkeypatch,
    tmp_path,
    client,
):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    now = main._utc_now_naive()
    object_id = "e4" + ("4" * 30)
    key = f"objects/e4/{object_id}.png"
    with SessionLocal() as db:
        owner = _user(db, 144)
        asset = _asset(db, owner_id=owner.id, storage_key=key)
        asset.sha256_digest = __import__("hashlib").sha256(PNG_BYTES).hexdigest()
        asset.size_bytes = len(PNG_BYTES)
        db.commit()

    final_path = tmp_path / key
    final_path.parent.mkdir(parents=True, exist_ok=True)
    final_path.write_bytes(b"corrupt")
    incoming = tmp_path / ".incoming" / f"{object_id}.part"
    incoming.parent.mkdir(parents=True, exist_ok=True)
    incoming.write_bytes(PNG_BYTES)
    assert upload_assets._registered_staging_object_ids(tmp_path) == [object_id]

    with SessionLocal() as db:
        assert (
            db.query(models.UploadAsset)
            .filter(func.substr(models.UploadAsset.storage_key, 12, 32) == object_id)
            .count()
            == 1
        )
        main.reconcile_upload_assets(db, now=now)
        db.commit()

    assert final_path.read_bytes() == PNG_BYTES
    assert not incoming.exists()


def test_reconcile_does_not_starve_registered_staging_after_the_first_batch(
    monkeypatch,
    tmp_path,
    client,
):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    now = main._utc_now_naive()
    oldest_key = None
    with SessionLocal() as db:
        owner = _user(db, 146)
        for index in range(upload_assets.RECONCILE_BATCH_SIZE + 1):
            object_id = f"{index + 1:032x}"
            key = f"objects/{object_id[:2]}/{object_id}.png"
            asset = _asset(
                db,
                owner_id=owner.id,
                storage_key=key,
                created_at=now - timedelta(seconds=upload_assets.RECONCILE_BATCH_SIZE + 1 - index),
            )
            if index == 0:
                oldest_key = key
                asset.sha256_digest = __import__("hashlib").sha256(PNG_BYTES).hexdigest()
                asset.size_bytes = len(PNG_BYTES)
        db.commit()

    object_id = oldest_key.split("/")[-1].split(".")[0]
    (tmp_path / "objects").mkdir()
    incoming = tmp_path / ".incoming" / f"{object_id}.part"
    incoming.parent.mkdir(parents=True, exist_ok=True)
    incoming.write_bytes(PNG_BYTES)

    with SessionLocal() as db:
        assert upload_assets._registered_staging_object_ids(tmp_path) == [object_id]
        matches = (
            db.query(models.UploadAsset)
            .filter(func.substr(models.UploadAsset.storage_key, 12, 32) == object_id)
            .all()
        )
        assert len(matches) == 1
        main.reconcile_upload_assets(db, now=now)
        db.commit()

    assert (tmp_path / oldest_key).read_bytes() == PNG_BYTES
    assert not incoming.exists()


def test_commit_acknowledgement_loss_returns_success_without_unlinking_final_object(
    monkeypatch,
    tmp_path,
    client,
):
    from upload_scanner import DeterministicUploadScanner

    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(main, "upload_scanner", DeterministicUploadScanner())
    with SessionLocal() as seed:
        _user(seed, 145)
        seed.commit()

    db = SessionLocal()
    real_commit = db.commit

    def commit_then_raise():
        real_commit()
        raise RuntimeError("synthetic lost commit acknowledgement")

    monkeypatch.setattr(db, "commit", commit_then_raise)
    upload = UploadFile(
        filename="ambiguous.png",
        file=io.BytesIO(PNG_BYTES),
        headers={"content-type": "image/png"},
    )
    try:
        stored = asyncio.run(
            main._register_pending_upload(
                upload,
                allowed_kinds={"image"},
                db=db,
                current_user=_actor(145),
            )
        )
    finally:
        db.close()

    assert stored.path.read_bytes() == PNG_BYTES
    with SessionLocal() as verify:
        asset = verify.query(models.UploadAsset).one()
        assert asset.storage_key == stored.storage_key
        assert asset.state == "PENDING"


def test_definite_registry_failure_retains_final_for_reconciliation_and_returns_503(
    monkeypatch,
    tmp_path,
    client,
):
    from upload_scanner import DeterministicUploadScanner

    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(main, "upload_scanner", DeterministicUploadScanner())
    with SessionLocal() as seed:
        _user(seed, 147)
        seed.commit()

    db = SessionLocal()
    monkeypatch.setattr(
        db,
        "commit",
        lambda: (_ for _ in ()).throw(RuntimeError("synthetic pre-commit failure")),
    )
    upload = UploadFile(
        filename="retry.png",
        file=io.BytesIO(PNG_BYTES),
        headers={"content-type": "image/png"},
    )
    try:
        with pytest.raises(HTTPException) as failure:
            asyncio.run(
                main._register_pending_upload(
                    upload,
                    allowed_kinds={"image"},
                    db=db,
                    current_user=_actor(147),
                )
            )
    finally:
        db.close()

    assert failure.value.status_code == 503
    orphaned_finals = list((tmp_path / "objects").glob("*/*"))
    assert len(orphaned_finals) == 1
    assert orphaned_finals[0].read_bytes() == PNG_BYTES
    with SessionLocal() as verify:
        assert verify.query(models.UploadAsset).count() == 0


def test_production_upload_preflight_requires_external_root_and_available_scanner(tmp_path):
    settings_source = inspect.getsource(main.settings.__class__.validate_production_safety)
    assert "UPLOAD_ROOT" in settings_source
    assert "UPLOAD_SCANNER" in settings_source
    assert callable(main.upload_scanner.preflight)


def test_scanner_required_rejects_missing_or_unapproved_endpoint():
    with pytest.raises(ValidationError, match="UPLOAD_SCANNER_HOST"):
        Settings(app_env="test", upload_scanner_required=True)

    missing = _production_settings_data()
    missing["upload_scanner_host"] = None
    with pytest.raises(ValidationError, match="UPLOAD_SCANNER_HOST"):
        Settings(**missing)

    public_endpoint = _production_settings_data()
    public_endpoint.update(
        upload_scanner_host="scanner.attacker.example",
        upload_scanner_allowed_hosts=("scanner.attacker.example",),
    )
    with pytest.raises(ValidationError, match="local or private"):
        Settings(**public_endpoint)

    unapproved = _production_settings_data()
    unapproved["upload_scanner_allowed_hosts"] = ("different-clamd",)
    with pytest.raises(ValidationError, match="UPLOAD_SCANNER_ALLOWED_HOSTS"):
        Settings(**unapproved)


def test_production_upload_root_requires_existing_real_service_custody(
    monkeypatch,
    tmp_path,
):
    missing_root = _production_settings_data()
    missing_root["upload_root"] = tmp_path / "missing"
    with pytest.raises(ValidationError, match="UPLOAD_ROOT custody"):
        Settings(**missing_root)

    file_root = tmp_path / "not-a-directory"
    file_root.write_text("no", encoding="utf-8")
    not_a_directory = _production_settings_data()
    not_a_directory["upload_root"] = file_root
    with pytest.raises(ValidationError, match="UPLOAD_ROOT custody"):
        Settings(**not_a_directory)

    real_root = tmp_path / "real-root"
    real_root.mkdir()
    symlink_root = tmp_path / "linked-root"
    try:
        symlink_root.symlink_to(real_root, target_is_directory=True)
    except OSError:
        symlink_root = None
    if symlink_root is not None:
        linked = _production_settings_data()
        linked["upload_root"] = symlink_root
        with pytest.raises(ValidationError, match="UPLOAD_ROOT custody"):
            Settings(**linked)

    inaccessible = _production_settings_data()
    inaccessible["upload_root"] = real_root
    monkeypatch.setattr(os, "access", lambda *_args, **_kwargs: False)
    with pytest.raises(ValidationError, match="UPLOAD_ROOT custody"):
        Settings(**inaccessible)


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits only")
def test_production_upload_root_rejects_group_or_world_writable(tmp_path):
    upload_root = tmp_path / "insecure-root"
    upload_root.mkdir(mode=0o770)
    upload_root.chmod(0o770)
    data = _production_settings_data()
    data["upload_root"] = upload_root
    with pytest.raises(ValidationError, match="UPLOAD_ROOT custody"):
        Settings(**data)


def test_production_upload_root_rejects_mutable_ancestor(monkeypatch, tmp_path):
    mutable_ancestor = tmp_path / "mutable-ancestor"
    mutable_ancestor.mkdir(mode=0o770)
    mutable_ancestor.chmod(0o770)
    upload_root = mutable_ancestor / "upload-root"
    upload_root.mkdir(mode=0o700)
    upload_root.chmod(0o700)
    data = _production_settings_data()
    data["upload_root"] = upload_root
    if os.name != "posix":
        monkeypatch.setattr(config, "_POSIX_UPLOAD_CUSTODY", True, raising=False)
        monkeypatch.setattr(
            config.os,
            "geteuid",
            lambda: upload_root.stat().st_uid,
            raising=False,
        )
    with pytest.raises(ValidationError, match="UPLOAD_ROOT custody"):
        Settings(**data)


def test_production_upload_layout_never_creates_root_and_rejects_linked_children(
    tmp_path,
):
    missing_root = tmp_path / "missing-root"
    with pytest.raises(RuntimeError, match="Upload storage is unavailable"):
        main._initialize_upload_layout(missing_root, production=True)
    assert not missing_root.exists()

    upload_root = tmp_path / "upload-root"
    linked_target = tmp_path / "linked-target"
    upload_root.mkdir()
    linked_target.mkdir()
    try:
        (upload_root / "objects").symlink_to(linked_target, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable on this platform")

    with pytest.raises(RuntimeError, match="Upload storage is unavailable"):
        main._initialize_upload_layout(upload_root, production=True)


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits only")
def test_upload_layout_and_staging_are_service_private(monkeypatch, tmp_path, client):
    from upload_scanner import DeterministicUploadScanner

    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(main, "upload_scanner", DeterministicUploadScanner())
    with SessionLocal() as db:
        _user(db, 149)
        db.commit()
    _override_user(_actor(149))
    try:
        response = client.post(
            "/api/upload/image",
            files={"file": ("private.png", PNG_BYTES, "image/png")},
        )
        assert response.status_code == 200
    finally:
        _clear_user_override()

    assert stat.S_IMODE((tmp_path / "objects").stat().st_mode) == 0o700
    assert stat.S_IMODE((tmp_path / ".incoming").stat().st_mode) == 0o700
    final = next((tmp_path / "objects").glob("*/*"))
    assert stat.S_IMODE(final.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(final.stat().st_mode) == 0o600


def test_scanner_failure_is_fail_closed_before_registry_success(client, monkeypatch, tmp_path):
    from upload_scanner import DeterministicUploadScanner

    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(
        main,
        "upload_scanner",
        DeterministicUploadScanner(verdict="unavailable"),
    )
    with SessionLocal() as db:
        _user(db, 151)
        db.commit()

    _override_user(_actor(151))
    try:
        response = client.post(
            "/api/upload/image",
            files={"file": ("scan-me.png", PNG_BYTES, "image/png")},
        )
        assert response.status_code == 503
        assert response.json() == {"detail": "Upload scanning unavailable"}
        with SessionLocal() as db:
            assert db.query(models.UploadAsset).count() == 0
        assert not any(path.is_file() for path in tmp_path.rglob("*"))
    finally:
        _clear_user_override()


def test_rejected_upload_attempts_are_limited_before_repeated_scans(
    client,
    monkeypatch,
    tmp_path,
):
    from upload_scanner import DeterministicUploadScanner

    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    scanner = DeterministicUploadScanner(verdict="infected")
    monkeypatch.setattr(main, "upload_scanner", scanner)
    with SessionLocal() as db:
        _user(db, 150)
        db.commit()

    _override_user(_actor(150))
    try:
        responses = [
            client.post(
                "/api/upload/image",
                files={"file": (f"rejected-{index}.png", PNG_BYTES, "image/png")},
            )
            for index in range(21)
        ]
    finally:
        _clear_user_override()

    assert [response.status_code for response in responses[:20]] == [400] * 20
    assert responses[20].status_code == 429
    assert responses[20].json() == {"detail": "Upload attempt rate limit exceeded"}


def test_attempt_limit_rejects_before_framework_reads_multipart_body(monkeypatch):
    admission = main.UploadAdmissionController()
    identity = "ip:198.51.100.10"
    for _ in range(20):
        admission.acquire(identity)
        admission.release()
    monkeypatch.setattr(main, "upload_admission", admission)

    body_was_read = False
    sent = []

    async def downstream(_scope, receive, _send):
        await receive()

    async def receive():
        nonlocal body_was_read
        body_was_read = True
        return {"type": "http.request", "body": PNG_BYTES, "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/upload/image",
        "client": ("198.51.100.10", 12345),
        "headers": [(b"content-length", str(len(PNG_BYTES)).encode("ascii"))],
    }
    asyncio.run(
        main.UploadRequestBodyLimitMiddleware(downstream)(scope, receive, send)
    )

    assert body_was_read is False
    response_start = next(message for message in sent if message["type"] == "http.response.start")
    assert response_start["status"] == 429


def test_upload_transaction_deadlines_are_set_before_registry_locking():
    calls = []
    fake_db = SimpleNamespace(
        bind=SimpleNamespace(dialect=SimpleNamespace(name="postgresql")),
        execute=lambda statement: calls.append(str(statement)),
    )
    upload_assets.configure_upload_transaction(fake_db)
    assert calls == [
        "SET LOCAL lock_timeout = '10s'",
        "SET LOCAL statement_timeout = '30s'",
        "SET LOCAL idle_in_transaction_session_timeout = '30s'",
    ]


def test_upload_scans_in_nonservable_staging_before_user_lock_and_off_event_loop(
    client,
    monkeypatch,
    tmp_path,
):
    events = []

    class RecordingScanner:
        def preflight(self):
            return None

        def scan(self, path):
            events.append(("scan", threading.get_ident()))
            assert path.parent.name == ".incoming"
            assert not any(event == "lock" for event, _thread_id in events)

    original_lock_owner = main._lock_upload_owner

    def recording_lock_owner(*args, **kwargs):
        events.append(("lock", threading.get_ident()))
        return original_lock_owner(*args, **kwargs)

    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(main, "upload_scanner", RecordingScanner())
    monkeypatch.setattr(main, "_lock_upload_owner", recording_lock_owner)
    with SessionLocal() as db:
        _user(db, 152)
        db.commit()

    _override_user(_actor(152))
    try:
        response = client.post(
            "/api/upload/image",
            files={"file": ("off-loop.png", PNG_BYTES, "image/png")},
        )
        assert response.status_code == 200
        assert [event for event, _thread_id in events] == ["scan", "lock"]
        assert events[0][1] != events[1][1]

        register_source = inspect.getsource(main._register_pending_upload)
        profile_source = inspect.getsource(main._replace_profile_upload)
        assert "run_in_threadpool(_finalize_prepared_upload" in register_source
        assert "run_in_threadpool(_finalize_prepared_upload" in profile_source
    finally:
        _clear_user_override()


def test_legacy_inventory_is_fail_closed_on_unmapped_ambiguous_or_invalid_content(tmp_path):
    from upload_legacy_inventory import LegacyInventoryError, inventory_legacy_uploads

    legacy = tmp_path / "images" / "42" / "shared.png"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(PNG_BYTES)
    with pytest.raises(LegacyInventoryError):
        inventory_legacy_uploads(tmp_path, bindings=[])

    with pytest.raises(LegacyInventoryError):
        inventory_legacy_uploads(
            tmp_path,
            bindings=[
                {"path": "images/42/shared.png", "owner_user_id": 42, "blog_id": 1},
                {"path": "images/42/shared.png", "owner_user_id": 42, "blog_id": 2},
            ],
        )

    legacy.write_bytes(b"<script>not really a png</script>")
    with pytest.raises(LegacyInventoryError):
        inventory_legacy_uploads(
            tmp_path,
            bindings=[
                {"path": "images/42/shared.png", "owner_user_id": 42, "blog_id": 1},
            ],
        )


def test_legacy_inventory_does_not_hide_nested_objects_and_rejects_links(tmp_path):
    from upload_legacy_inventory import LegacyInventoryError, inventory_legacy_uploads

    hidden = tmp_path / "images" / "42" / "objects" / "hidden.png"
    hidden.parent.mkdir(parents=True)
    hidden.write_bytes(PNG_BYTES)
    with pytest.raises(LegacyInventoryError, match="exactly one binding"):
        inventory_legacy_uploads(tmp_path, bindings=[])

    outside = tmp_path.parent / f"{tmp_path.name}-outside.png"
    outside.write_bytes(PNG_BYTES)
    linked = tmp_path / "images" / "42" / "linked.png"
    try:
        linked.symlink_to(outside)
    except OSError:
        pytest.skip("file symlinks are unavailable on this platform")
    with pytest.raises(LegacyInventoryError, match="link"):
        inventory_legacy_uploads(tmp_path, bindings=[])


def test_legacy_inventory_reads_one_stable_file_and_excludes_only_registry_namespace(
    tmp_path,
):
    from upload_legacy_inventory import inventory_legacy_uploads

    legacy = tmp_path / "images" / "42" / "reading.png"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(PNG_BYTES)
    registered = tmp_path / "objects" / "aa" / f"{'a' * 32}.png"
    registered.parent.mkdir(parents=True)
    registered.write_bytes(PNG_BYTES)

    records = inventory_legacy_uploads(
        tmp_path,
        bindings=[
            {"path": "images/42/reading.png", "owner_user_id": 42, "blog_id": 7},
        ],
    )
    assert len(records) == 1
    assert records[0]["path"] == "images/42/reading.png"
    assert records[0]["size_bytes"] == len(PNG_BYTES)
    assert records[0]["sha256_digest"] == __import__("hashlib").sha256(PNG_BYTES).hexdigest()


def test_production_database_startup_never_uses_metadata_create_all(monkeypatch):
    import database

    calls = []
    monkeypatch.setattr(
        database.Base.metadata,
        "create_all",
        lambda **kwargs: calls.append(kwargs),
    )
    monkeypatch.setattr(database, "verify_database_schema", lambda: calls.append("verified"))
    database.initialize_database(allow_schema_create=False)
    assert calls == ["verified"]
    assert "allow_schema_create=settings.app_env != \"production\"" in inspect.getsource(
        main.lifespan
    )

    destructive = _production_settings_data()
    destructive["reset_database_on_startup"] = True
    with pytest.raises(ValidationError, match="RESET_DATABASE_ON_STARTUP"):
        Settings(**destructive)


def test_production_requires_postgresql_for_atomic_upload_accounting():
    unsafe = _production_settings_data()
    unsafe["database_url"] = "sqlite:///production.db"
    with pytest.raises(ValidationError, match="DATABASE_URL.*PostgreSQL"):
        Settings(**unsafe)


class _UploadSchemaInspector:
    def __init__(self):
        table = models.UploadAsset.__table__
        dialect = postgresql.dialect()
        self.columns = [
            {
                "name": column.name,
                "type": column.type.dialect_impl(dialect),
                "nullable": column.nullable,
                "default": (
                    "nextval('upload_assets_id_seq'::regclass)"
                    if column.name == "id"
                    else "CURRENT_TIMESTAMP"
                    if column.name == "created_at"
                    else None
                ),
            }
            for column in table.columns
        ]
        self.checks = [
            {"name": constraint.name, "sqltext": str(constraint.sqltext)}
            for constraint in table.constraints
            if constraint.__class__.__name__ == "CheckConstraint"
        ]
        self.indexes = []
        for index in table.indexes:
            where = index.dialect_options["postgresql"].get("where")
            if index.name == "uq_upload_assets_active_profile_purpose":
                where = (
                    "state = 'ACTIVE' "
                    "AND purpose IN ('PROFILE_IMAGE', 'COVER_IMAGE')"
                )
            self.indexes.append(
                {
                    "name": index.name,
                    "column_names": [column.name for column in index.columns],
                    "unique": index.unique,
                    "dialect_options": {
                        "postgresql_where": "" if where is None else str(where),
                    },
                }
            )
        self.uniques = [
            {"name": "uq_upload_assets_storage_key", "column_names": ["storage_key"]},
        ]
        self.foreign_keys = [
            {
                "name": "fk_upload_assets_owner_user",
                "constrained_columns": ["owner_user_id"],
                "referred_schema": None,
                "referred_table": "users",
                "referred_columns": ["id"],
                "options": {"ondelete": "SET NULL"},
            },
            {
                "name": "fk_upload_assets_blog",
                "constrained_columns": ["blog_id"],
                "referred_schema": None,
                "referred_table": "blogs",
                "referred_columns": ["id"],
                "options": {"ondelete": "SET NULL"},
            },
        ]

    def has_table(self, table_name):
        return table_name == "upload_assets"

    def get_columns(self, _table_name):
        return self.columns

    def get_check_constraints(self, _table_name):
        return self.checks

    def get_indexes(self, _table_name):
        return self.indexes

    def get_unique_constraints(self, _table_name):
        return self.uniques

    def get_foreign_keys(self, _table_name):
        return self.foreign_keys

    def get_pk_constraint(self, _table_name):
        return {"name": "upload_assets_pkey", "constrained_columns": ["id"]}


@pytest.mark.parametrize(
    "defect",
    (
        "wrong_type",
        "wrong_nullability",
        "vacuous_check",
        "negated_membership_check",
        "negated_regex_check",
        "tautological_size_check",
        "weakened_state_shape",
        "reparenthesized_state_shape",
        "wrong_index_columns",
        "wrong_profile_predicate",
        "wrong_foreign_target",
        "wrong_primary_key",
        "wrong_id_default",
        "wrong_created_default",
    ),
)
def test_production_schema_guard_rejects_named_but_semantically_wrong_ddl(
    monkeypatch,
    defect,
):
    import database

    schema = _UploadSchemaInspector()
    if defect == "wrong_type":
        next(column for column in schema.columns if column["name"] == "size_bytes")[
            "type"
        ] = String(40)
    elif defect == "wrong_nullability":
        next(column for column in schema.columns if column["name"] == "purpose")[
            "nullable"
        ] = True
    elif defect == "vacuous_check":
        next(
            check for check in schema.checks if check["name"] == "ck_upload_assets_purpose"
        )["sqltext"] = "TRUE"
    elif defect == "negated_membership_check":
        next(
            check for check in schema.checks if check["name"] == "ck_upload_assets_purpose"
        )["sqltext"] = "purpose NOT IN ('POST', 'PROFILE_IMAGE', 'COVER_IMAGE')"
    elif defect == "negated_regex_check":
        next(
            check
            for check in schema.checks
            if check["name"] == "ck_upload_assets_sha256_lower_hex"
        )["sqltext"] = "sha256_digest !~ '^[0-9a-f]{64}$'"
    elif defect == "tautological_size_check":
        next(
            check
            for check in schema.checks
            if check["name"] == "ck_upload_assets_positive_size"
        )["sqltext"] = "size_bytes > 0 OR size_bytes < 0"
    elif defect == "weakened_state_shape":
        shape = next(
            check
            for check in schema.checks
            if check["name"] == "ck_upload_assets_state_shape"
        )
        shape["sqltext"] = f"({shape['sqltext']}) OR size_bytes > 0"
    elif defect == "reparenthesized_state_shape":
        shape = next(
            check
            for check in schema.checks
            if check["name"] == "ck_upload_assets_state_shape"
        )
        approved_group = (
            "((purpose = 'POST' AND blog_id IS NOT NULL) OR "
            "(purpose IN ('PROFILE_IMAGE', 'COVER_IMAGE') AND blog_id IS NULL))"
        )
        weakened_group = (
            "(purpose = 'POST' AND (blog_id IS NOT NULL OR "
            "purpose IN ('PROFILE_IMAGE', 'COVER_IMAGE')) AND blog_id IS NULL)"
        )
        assert approved_group in shape["sqltext"]
        shape["sqltext"] = shape["sqltext"].replace(approved_group, weakened_group)
    elif defect == "wrong_index_columns":
        next(
            index
            for index in schema.indexes
            if index["name"] == "ix_upload_assets_owner_state_created"
        )["column_names"] = ["state", "owner_user_id", "created_at"]
    elif defect == "wrong_profile_predicate":
        next(
            index
            for index in schema.indexes
            if index["name"] == "uq_upload_assets_active_profile_purpose"
        )["dialect_options"]["postgresql_where"] = (
            "state = 'ACTIVE' OR purpose IN ('PROFILE_IMAGE', 'COVER_IMAGE')"
        )
    elif defect == "wrong_foreign_target":
        schema.foreign_keys[0]["referred_table"] = "admins"
    elif defect == "wrong_primary_key":
        schema.get_pk_constraint = lambda _table_name: {
            "name": "upload_assets_pkey",
            "constrained_columns": ["storage_key"],
        }
    elif defect == "wrong_id_default":
        next(column for column in schema.columns if column["name"] == "id")[
            "default"
        ] = None
    elif defect == "wrong_created_default":
        next(column for column in schema.columns if column["name"] == "created_at")[
            "default"
        ] = None

    monkeypatch.setattr(database, "inspect", lambda _engine: schema)
    monkeypatch.setattr(
        database,
        "engine",
        SimpleNamespace(dialect=postgresql.dialect()),
    )
    with pytest.raises(RuntimeError, match="Database schema is not ready"):
        database.verify_database_schema()


def test_production_schema_guard_accepts_the_exact_upload_registry_shape(monkeypatch):
    import database

    schema = _UploadSchemaInspector()
    monkeypatch.setattr(database, "inspect", lambda _engine: schema)
    monkeypatch.setattr(
        database,
        "engine",
        SimpleNamespace(dialect=postgresql.dialect()),
    )
    database.verify_database_schema()


@pytest.mark.parametrize(
    ("setting_name", "error_marker"),
    (
        ("upload_registry_schema_ready", "UPLOAD_REGISTRY_SCHEMA_READY"),
        ("upload_legacy_import_complete", "UPLOAD_LEGACY_IMPORT_COMPLETE"),
        ("upload_backup_restore_verified", "UPLOAD_BACKUP_RESTORE_VERIFIED"),
    ),
)
def test_production_requires_explicit_upload_deployment_gates(
    setting_name,
    error_marker,
):
    data = _production_settings_data()
    data.update(
        upload_registry_schema_ready=True,
        upload_legacy_import_complete=True,
        upload_backup_restore_verified=True,
    )
    data[setting_name] = False
    with pytest.raises(ValidationError, match=error_marker):
        Settings(**data)


def test_upload_asset_semantic_migration_reference_is_explicitly_not_alembic_ready():
    migration = Path("migrations/0005_upload_asset_registry.sql").read_text(encoding="utf-8")
    readme = Path("migrations/README-upload-asset-registry.md").read_text(encoding="utf-8")
    for marker in (
        "CREATE TABLE upload_assets",
        "ON DELETE SET NULL",
        "fk_upload_assets_owner_user",
        "fk_upload_assets_blog",
        "ck_upload_assets_storage_key",
        "ck_upload_assets_state_shape",
        "scan_completed_at IS NOT NULL",
        "uq_upload_assets_active_profile_purpose",
        "ix_upload_assets_owner_state_created",
        "ix_upload_assets_state_delete_after",
    ):
        assert marker in migration
    assert "semantic reference" in readme.lower()
    assert "not an alembic migration" in readme.lower()
    assert "abort" in readme.lower()
    assert "unmapped" in readme.lower()
    for marker in (
        "hard deployment blocker",
        "upload-store snapshot",
        "immutable manifest",
        "restore rehearsal",
        "every active",
        "size_bytes",
        "sha256_digest",
    ):
        assert marker in readme.lower()
