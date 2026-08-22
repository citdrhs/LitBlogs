import asyncio
import hashlib
import inspect
import re
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.datastructures import Headers
from starlette.routing import Mount

import main
import models
from database import SessionLocal

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"safe-image-payload"
PDF_BYTES = b"%PDF-1.7\n" + b"safe-pdf-payload"
MP4_BYTES = b"\x00\x00\x00\x18ftypisom" + b"safe-video-payload"
PNG_SIZE = len(PNG_BYTES)


def _security_actor(user_id=42, role=models.UserRole.STUDENT):
    return SimpleNamespace(id=user_id, role=role, disabled_at=None)


def _security_user(db, user_id=42, role=models.UserRole.STUDENT):
    user = models.User(
        id=user_id,
        username=f"content-security-{user_id}",
        email=f"content-security-{user_id}@example.com",
        password="not-a-real-password-hash",
        first_name="Content",
        last_name="Security",
        role=role,
    )
    db.add(user)
    db.flush()
    return user


def _registered_asset(
    db,
    *,
    storage_key,
    owner_id=42,
    original_filename="safe.png",
    media_type="image/png",
    size_bytes=PNG_SIZE,
    sha256_digest=None,
    state="PENDING",
    purpose="POST",
):
    now = main._utc_now_naive()
    asset = models.UploadAsset(
        storage_key=storage_key,
        owner_user_id=owner_id,
        purpose=purpose,
        state=state,
        original_filename=original_filename,
        media_type=media_type,
        size_bytes=size_bytes,
        sha256_digest=sha256_digest
        or hashlib.sha256(
            PDF_BYTES if media_type == "application/pdf" else PNG_BYTES
        ).hexdigest(),
        created_at=now,
        expires_at=now + timedelta(hours=24) if state == "PENDING" else None,
        bound_at=now if state == "ACTIVE" else None,
        scan_completed_at=now,
    )
    db.add(asset)
    db.flush()
    return asset


def make_upload(filename, content_type, content):
    return main.UploadFile(
        file=BytesIO(content),
        filename=filename,
        headers=Headers({"content-type": content_type}),
    )


def test_server_sanitizer_removes_active_content_and_unsafe_urls():
    sanitized = main.sanitize_html(
        """
        <style>body { display: none }</style>
        <script>alert(document.domain)</script>
        <a href="javascript:alert(1)" onclick="alert(1)">Open</a>
        <img src="data:text/html,<script>alert(1)</script>" onerror="alert(1)">
        <img src="https://tracker.example/pixel.png">
        <img src="files/42/not-an-upload-route.png">
        <img src="/api/uploads/images/42/private.png?cache=bypass">
        <figure class="video-container">
          <video controls onplay="alert(1)">
            <source src="https://tracker.example/video.mp4" type="video/mp4">
          </video>
        </figure>
        """
    )

    lowered = sanitized.lower()
    assert "<script" not in lowered
    assert "<style" not in lowered
    assert "onclick" not in lowered
    assert "onerror" not in lowered
    assert "onplay" not in lowered
    assert "javascript:" not in lowered
    assert "data:text/html" not in lowered
    assert "https://tracker.example/video.mp4" not in sanitized
    assert "https://tracker.example/pixel.png" not in sanitized
    assert "not-an-upload-route.png" not in sanitized
    assert "cache=bypass" not in sanitized


def test_server_sanitizer_preserves_supported_rich_text_and_uploaded_media():
    sanitized = main.sanitize_html(
        """
        <h2>Reading response</h2>
        <p style="font-family: Georgia, serif; color: #123456; background-color: #fafafa; font-size: 18px; text-align: center; position: fixed">
          <strong>Close reading</strong>
        </p>
        <figure class="video-container" contenteditable="false">
          <video controls preload="metadata" width="100%">
            <source src="/api/uploads/objects/aa/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.mp4" type="video/mp4">
          </video>
        </figure>
        <video controls src="/api/uploads/objects/bb/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.mp4"></video>
        <video controls src="https://tracker.example/direct.mp4"></video>
        <video controls src="data:video/mp4;base64,AAAA"></video>
        <img src="/api/uploads/objects/cc/cccccccccccccccccccccccccccccccc.png" alt="Book cover">
        """
    )

    assert "<h2>Reading response</h2>" in sanitized
    assert "font-family: Georgia, serif" in sanitized
    assert "color: #123456" in sanitized
    assert "background-color: #fafafa" in sanitized
    assert "font-size: 18px" in sanitized
    assert "text-align: center" in sanitized
    assert "position" not in sanitized
    assert '<figure class="video-container" contenteditable="false">' in sanitized
    assert "<video controls" in sanitized
    assert '<source src="/api/uploads/objects/aa/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.mp4" type="video/mp4">' in sanitized
    assert 'src="/api/uploads/objects/bb/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.mp4"' in sanitized
    assert "https://tracker.example/direct.mp4" not in sanitized
    assert "data:video/mp4" not in sanitized
    assert '<img src="/api/uploads/objects/cc/cccccccccccccccccccccccccccccccc.png" alt="Book cover">' in sanitized


def test_server_sanitizer_drops_pathological_layout_values():
    sanitized = main.sanitize_html(
        """
        <p style="font-size: 999999999px; width: 999999999px; height: 999999999px; margin: 999999999px; max-width: 999999999px">Oversized</p>
        <p style="font-size: 18px; width: 100%; max-width: 600px; margin: 12px 0">Bounded</p>
        <img src="/api/uploads/images/42/unsafe.png" width="999999999px" height="999999999px">
        <img src="/api/uploads/images/42/safe.png" width="100%" height="4096px">
        """
    )

    assert "999999999" not in sanitized
    assert "font-size: 18px" in sanitized
    assert "width: 100%" in sanitized
    assert "max-width: 600px" in sanitized
    assert "margin: 12px 0" in sanitized
    assert 'width="100%"' in sanitized
    assert 'height="4096px"' in sanitized


def test_server_sanitizer_rejects_malformed_urls_without_raising():
    sanitized = main.sanitize_html(
        '<a href="https://[">Broken link</a><img src="//[">'
    )

    assert "href=" not in sanitized
    assert "src=" not in sanitized


def test_server_sanitizer_rejects_oversized_content_before_parsing(monkeypatch):
    monkeypatch.setattr(main, "MAX_RICH_TEXT_INPUT_LENGTH", 16)

    with pytest.raises(HTTPException) as error:
        main.sanitize_html("x" * 17)

    assert error.value.status_code == 413
    assert error.value.detail == "Rich text exceeds the allowed size"


def test_post_builder_does_not_append_active_markup_after_sanitization():
    post = main.schemas.BlogCreate(
        title="Security regression",
        content="<p>Visible response</p>",
        code_snippets=[
            {"language": "html", "code": '<img src=x onerror="window.__xss=true">'},
        ],
        media=[{"type": "image", "url": '"><script>window.__xss=true</script>'}],
        polls=[{"options": ["safe", "</div><script>alert(1)</script>"]}],
        files=[{"name": "</div><img src=x onerror=alert(1)>", "url": "/api/uploads/objects/dd/dddddddddddddddddddddddddddddddd.pdf"}],
    )

    built = main._build_post_content(post)

    assert "<script" not in built.lower()
    assert "<img src=x" not in built.lower()
    assert "&lt;img" in built


def test_compatibility_upload_reference_parser_is_removed():
    assert not hasattr(main, "_canonical_upload_relative_path")


def test_upload_path_cannot_escape_upload_root(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)

    assert main._upload_path("objects", "aa", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.pdf") == (
        tmp_path / "objects" / "aa" / "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.pdf"
    ).resolve()

    with pytest.raises(ValueError, match="upload"):
        main._upload_path("..", "secrets.env")


def test_legacy_and_unmapped_uploads_are_never_served(client, monkeypatch, tmp_path):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    other_users_file = tmp_path / "files" / "99" / "private.pdf"
    other_users_file.parent.mkdir(parents=True)
    other_users_file.write_bytes(b"private")

    with pytest.raises(HTTPException) as legacy_error:
        asyncio.run(main.get_uploaded_file("files/42/private.pdf"))
    assert legacy_error.value.status_code == 400
    assert legacy_error.value.detail == "Invalid upload path"

    rogue_key = "objects/aa/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.pdf"
    rogue_path = tmp_path / rogue_key
    rogue_path.parent.mkdir(parents=True)
    rogue_path.write_bytes(PDF_BYTES)
    with SessionLocal() as db:
        _security_user(db)
        db.commit()
        with pytest.raises(HTTPException) as unmapped_error:
            asyncio.run(
                main.get_uploaded_file(
                    rogue_key,
                    db=db,
                    current_user=_security_actor(),
                )
            )
    assert unmapped_error.value.status_code == 404
    assert unmapped_error.value.detail == "File not found"


@pytest.mark.parametrize(
    ("filename", "content_type", "content"),
    [
        ("active.svg", "image/svg+xml", b"<svg onload='alert(1)'></svg>"),
        ("active.html", "text/html", b"<script>alert(1)</script>"),
        ("forged.png", "image/png", b"<script>alert(1)</script>"),
        ("mismatch.jpg", "image/png", PNG_BYTES),
    ],
)
def test_image_upload_rejects_active_or_mismatched_content(
    client,
    monkeypatch,
    tmp_path,
    filename,
    content_type,
    content,
):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    with SessionLocal() as db:
        _security_user(db)
        db.commit()
        with pytest.raises(HTTPException) as error:
            asyncio.run(
                main.upload_image(
                    make_upload(filename, content_type, content),
                    db=db,
                    current_user=_security_actor(),
                )
            )

    assert error.value.status_code == 400
    assert [path for path in tmp_path.rglob("*") if path.is_file()] == []


def test_validated_upload_is_bounded_opaque_and_cleans_partial_files(client, monkeypatch, tmp_path):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(main, "MAX_IMAGE_UPLOAD_BYTES", len(PNG_BYTES) - 1)

    with SessionLocal() as db:
        _security_user(db)
        db.commit()
        with pytest.raises(HTTPException) as error:
            asyncio.run(
                main.upload_image(
                    make_upload("student-private-name.png", "image/png", PNG_BYTES),
                    db=db,
                    current_user=_security_actor(),
                )
            )
        assert error.value.status_code == 413
        assert [path for path in tmp_path.rglob("*") if path.is_file()] == []

        monkeypatch.setattr(main, "MAX_IMAGE_UPLOAD_BYTES", len(PNG_BYTES))
        result = asyncio.run(
            main.upload_image(
                make_upload("student-private-name.png", "image/png", PNG_BYTES),
                db=db,
                current_user=_security_actor(),
            )
        )
        storage_key = result["url"].removeprefix("/api/uploads/")
        assert re.fullmatch(r"objects/[0-9a-f]{2}/[0-9a-f]{32}\.png", storage_key)
        assert storage_key.split("/")[1] == Path(storage_key).stem[:2]
        assert "student-private-name" not in storage_key
        assert (tmp_path / storage_key).read_bytes() == PNG_BYTES
        assert db.query(models.UploadAsset).one().state == "PENDING"


@pytest.mark.parametrize(
    "endpoint",
    [main.upload_profile_image, main.upload_cover_image],
)
def test_profile_upload_database_failures_clean_files_without_disclosing_paths(
    endpoint,
    monkeypatch,
    tmp_path,
):
    class FailingDatabase:
        def query(self, *_args, **_kwargs):
            raise RuntimeError(str(tmp_path / "private" / "database.sqlite"))

        def rollback(self):
            return None

    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            endpoint(
                make_upload("portrait.png", "image/png", PNG_BYTES),
                db=FailingDatabase(),
                current_user=SimpleNamespace(id=42),
            )
        )

    assert error.value.status_code == 500
    assert error.value.detail == "Failed to upload image"
    assert not any(path.is_file() for path in tmp_path.rglob("*"))


def test_upload_round_trip_uses_the_canonical_authenticated_api_route(
    client,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    with SessionLocal() as db:
        _security_user(db)
        db.commit()
    main.app.dependency_overrides[main.get_current_user] = lambda: _security_actor()
    try:
        upload_response = client.post(
            "/api/upload/image",
            files={"file": ("cover.png", PNG_BYTES, "image/png")},
        )
        assert upload_response.status_code == 200

        upload_url = upload_response.json()["url"]
        assert re.fullmatch(
            r"/api/uploads/objects/[0-9a-f]{2}/[0-9a-f]{32}\.png",
            upload_url,
        )

        served_response = client.get(upload_url)
        assert served_response.status_code == 200
        assert served_response.content == PNG_BYTES
        assert served_response.headers["content-type"] == "image/png"

        upload_path = upload_url.removeprefix("/api/uploads/")
        delete_response = client.delete(f"/api/upload/{upload_path}")
        assert delete_response.status_code == 200
        assert delete_response.json() == {"message": "File deletion queued"}
        assert (tmp_path / upload_path).is_file()
        with SessionLocal() as db:
            assert db.query(models.UploadAsset).one().state == "DELETE_PENDING"
    finally:
        main.app.dependency_overrides.pop(main.get_current_user, None)


@pytest.mark.parametrize(
    ("filename", "content_type", "content", "kind"),
    [
        ("reading.pdf", "application/pdf", PDF_BYTES, "pdf"),
        ("book-talk.mp4", "video/mp4", MP4_BYTES, "video"),
        ("cover.png", "image/png", PNG_BYTES, "image"),
    ],
)
def test_upload_type_classifier_requires_extension_mime_and_signature_agreement(
    filename,
    content_type,
    content,
    kind,
):
    upload = make_upload(filename, content_type, content)
    spec = main._validated_upload_spec(upload, {kind}, content[:32])

    assert spec.kind == kind


def test_all_upload_endpoints_use_the_bounded_validation_writer():
    for endpoint in (
        main.upload_image,
        main.upload_video,
        main.upload_file,
        main.upload_generic_file,
    ):
        assert "_register_pending_upload" in inspect.getsource(endpoint)
    assert "_save_validated_upload" in inspect.getsource(main._register_pending_upload)
    for endpoint in (main.upload_profile_image, main.upload_cover_image):
        assert "_replace_profile_upload" in inspect.getsource(endpoint)
    assert "_save_validated_upload" in inspect.getsource(main._replace_profile_upload)


def test_uploads_are_not_exposed_through_the_public_static_mount():
    assert not any(
        isinstance(route, Mount) and route.path == "/uploads"
        for route in main.app.routes
    )


def test_upload_route_requires_authentication_before_revealing_file(client, monkeypatch, tmp_path):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    storage_key = "objects/aa/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png"
    image_path = tmp_path / storage_key
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(PNG_BYTES)
    with SessionLocal() as db:
        _security_user(db)
        _registered_asset(db, storage_key=storage_key)
        db.commit()

    upload_url = f"/api/uploads/{storage_key}"
    unauthenticated = client.get(upload_url)
    assert unauthenticated.status_code == 401

    main.app.dependency_overrides[main.get_current_user] = lambda: _security_actor()
    try:
        authenticated = client.get(upload_url)
        main.app.dependency_overrides[main.get_current_user] = lambda: _security_actor(
            99,
            models.UserRole.ADMIN,
        )
        admin_read = client.get(upload_url)
    finally:
        main.app.dependency_overrides.pop(main.get_current_user, None)

    assert authenticated.status_code == 200
    assert authenticated.content == PNG_BYTES
    assert admin_read.status_code == 200
    assert admin_read.content == PNG_BYTES


def test_upload_request_body_cap_runs_before_auth_and_multipart_parsing(client, monkeypatch):
    monkeypatch.setattr(main, "MAX_IMAGE_UPLOAD_BYTES", 16)

    response = client.post(
        "/api/upload/image",
        files={"file": ("oversized.png", b"x" * (2 * 1024 * 1024), "image/png")},
    )

    assert response.status_code == 413
    assert response.json() == {"detail": "Upload request exceeds the allowed size"}


def test_upload_request_body_cap_counts_chunked_bodies_without_content_length(monkeypatch):
    monkeypatch.setattr(main, "MAX_IMAGE_UPLOAD_BYTES", 5)
    monkeypatch.setattr(main, "UPLOAD_REQUEST_OVERHEAD_BYTES", 0)
    request_messages = iter(
        [
            {"type": "http.request", "body": b"123", "more_body": True},
            {"type": "http.request", "body": b"456", "more_body": False},
        ]
    )
    sent_messages = []
    downstream_completed = False

    async def receive():
        return next(request_messages)

    async def send(message):
        sent_messages.append(message)

    async def downstream(_scope, limited_receive, _send):
        nonlocal downstream_completed
        await limited_receive()
        await limited_receive()
        downstream_completed = True

    middleware = main.UploadRequestBodyLimitMiddleware(downstream)
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/upload/image",
        "headers": [],
    }

    asyncio.run(middleware(scope, receive, send))

    response_start = next(
        message for message in sent_messages if message["type"] == "http.response.start"
    )
    assert response_start["status"] == 413
    assert downstream_completed is False


def test_safe_upload_response_has_fixed_type_and_defensive_headers(client, monkeypatch, tmp_path):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    storage_key = "objects/aa/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png"
    image_path = tmp_path / storage_key
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(PNG_BYTES)

    with SessionLocal() as db:
        _security_user(db)
        _registered_asset(db, storage_key=storage_key)
        db.commit()
        response = asyncio.run(
            main.get_uploaded_file(
                storage_key,
                db=db,
                current_user=_security_actor(),
            )
        )

    assert response.media_type == "image/png"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cross-origin-resource-policy"] == "same-origin"
    assert response.headers["cache-control"] == "private, no-store"
    assert "sandbox" in response.headers["content-security-policy"]
    assert response.headers["content-disposition"].startswith("inline;")


def test_pdf_uploads_are_always_served_as_attachments(client, monkeypatch, tmp_path):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    storage_key = "objects/bb/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.pdf"
    document_path = tmp_path / storage_key
    document_path.parent.mkdir(parents=True)
    document_path.write_bytes(PDF_BYTES)

    with SessionLocal() as db:
        _security_user(db)
        _registered_asset(
            db,
            storage_key=storage_key,
            original_filename="safe.pdf",
            media_type="application/pdf",
            size_bytes=len(PDF_BYTES),
        )
        db.commit()
        response = asyncio.run(
            main.get_uploaded_file(
                storage_key,
                db=db,
                current_user=_security_actor(),
            )
        )

    assert response.media_type == "application/pdf"
    assert response.headers["content-disposition"].startswith("attachment;")


def test_registry_response_uses_stored_name_and_sanitizes_it(client, monkeypatch, tmp_path):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    storage_key = "objects/bb/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.pdf"
    document_path = tmp_path / storage_key
    document_path.parent.mkdir(parents=True)
    document_path.write_bytes(PDF_BYTES)

    with SessionLocal() as db:
        _security_user(db)
        _registered_asset(
            db,
            storage_key=storage_key,
            original_filename='report.html"\r\nX-Injected: true',
            media_type="application/pdf",
            size_bytes=len(PDF_BYTES),
        )
        db.commit()
        response = asyncio.run(
            main.get_uploaded_file(
                storage_key,
                db=db,
                current_user=_security_actor(),
            )
        )

    disposition = response.headers["content-disposition"]
    assert response.media_type == "application/pdf"
    assert disposition.startswith("attachment;")
    assert ".html" not in disposition
    assert disposition.endswith('report.pdf"')
    assert "\r" not in disposition and "\n" not in disposition
    assert response.headers["x-content-type-options"] == "nosniff"


def test_upload_and_delete_errors_do_not_disclose_server_paths(
    client,
    monkeypatch,
    tmp_path,
    capsys,
):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    missing_key = "objects/bb/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.pdf"
    with SessionLocal() as db:
        _security_user(db)
        db.commit()
        with pytest.raises(HTTPException) as upload_error:
            asyncio.run(
                main.get_uploaded_file(
                    missing_key,
                    db=db,
                    current_user=_security_actor(),
                )
            )
    assert upload_error.value.status_code == 404
    assert upload_error.value.detail == "File not found"

    class FailingDatabase:
        def query(self, *_args, **_kwargs):
            raise RuntimeError(str(tmp_path / "private" / "student-record.pdf"))

        def rollback(self):
            return None

    with pytest.raises(HTTPException) as delete_error:
        asyncio.run(
            main.delete_file(
                missing_key,
                db=FailingDatabase(),
                current_user=_security_actor(),
            )
        )
    assert delete_error.value.status_code == 500
    assert delete_error.value.detail == "Failed to delete file"
    assert capsys.readouterr().out == ""


def test_unmapped_or_forged_uploads_are_not_served(client, monkeypatch, tmp_path):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    unmapped_key = "objects/aa/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png"
    forged_key = "objects/bb/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.png"
    unmapped_png = tmp_path / unmapped_key
    forged_png = tmp_path / forged_key
    unmapped_png.parent.mkdir(parents=True)
    unmapped_png.write_bytes(PNG_BYTES)
    forged_png.parent.mkdir(parents=True)
    forged_payload = b"<script>alert(1)</script>"
    forged_png.write_bytes(forged_payload)

    with SessionLocal() as db:
        _security_user(db)
        _registered_asset(
            db,
            storage_key=forged_key,
            size_bytes=len(forged_payload),
            sha256_digest=hashlib.sha256(forged_payload).hexdigest(),
        )
        db.commit()
        for reference in (unmapped_key, forged_key):
            with pytest.raises(HTTPException) as error:
                asyncio.run(
                    main.get_uploaded_file(
                        reference,
                        db=db,
                        current_user=_security_actor(),
                    )
                )
            assert error.value.status_code == 404
            assert error.value.detail == "File not found"


def test_delete_upload_maps_malformed_paths_to_bad_request(client):
    with SessionLocal() as db:
        _security_user(db)
        db.commit()
        with pytest.raises(HTTPException) as error:
            asyncio.run(
                main.delete_file(
                    file_path="../secrets.env",
                    db=db,
                    current_user=_security_actor(),
                )
            )

    assert error.value.status_code == 400
    assert error.value.detail == "Invalid upload path"


def test_delete_upload_hides_another_owners_registered_object(client):
    storage_key = "objects/aa/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.pdf"
    with SessionLocal() as db:
        _security_user(db, 42)
        _security_user(db, 420)
        _registered_asset(
            db,
            storage_key=storage_key,
            owner_id=420,
            original_filename="reading.pdf",
            media_type="application/pdf",
            size_bytes=len(PDF_BYTES),
        )
        db.commit()
        with pytest.raises(HTTPException) as error:
            asyncio.run(
                main.delete_file(
                    file_path=storage_key,
                    db=db,
                    current_user=_security_actor(42),
                )
            )

    assert error.value.status_code == 404
    assert error.value.detail == "File not found"


def test_delete_upload_rejects_direct_active_asset(client):
    storage_key = "objects/aa/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png"
    with SessionLocal() as db:
        _security_user(db)
        _registered_asset(
            db,
            storage_key=storage_key,
            state="ACTIVE",
            purpose="PROFILE_IMAGE",
        )
        db.commit()
        with pytest.raises(HTTPException) as error:
            asyncio.run(
                main.delete_file(
                    file_path=storage_key,
                    db=db,
                    current_user=_security_actor(),
                )
            )

    assert error.value.status_code == 409
    assert error.value.detail == "Active uploads must be removed from their resource"


def test_delete_upload_rejects_directories_without_disclosing_paths(
    client,
    monkeypatch,
    tmp_path,
    capsys,
):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    (tmp_path / "objects" / "aa").mkdir(parents=True)

    with SessionLocal() as db:
        _security_user(db)
        db.commit()
        with pytest.raises(HTTPException) as error:
            asyncio.run(
                main.delete_file(
                    file_path="objects/aa",
                    db=db,
                    current_user=_security_actor(),
                )
            )

    assert error.value.status_code == 400
    assert error.value.detail == "Invalid upload path"
    assert capsys.readouterr().out == ""


def test_pending_delete_queues_without_synchronously_unlinking(
    client,
    monkeypatch,
    tmp_path,
    capsys,
):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    storage_key = "objects/aa/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png"
    stored_file = tmp_path / storage_key
    stored_file.parent.mkdir(parents=True)
    stored_file.write_bytes(PNG_BYTES)
    with SessionLocal() as db:
        _security_user(db)
        _registered_asset(db, storage_key=storage_key)
        db.commit()

    def fail_unlink(_path):
        raise OSError(str(tmp_path / "private" / "student-record.png"))

    monkeypatch.setattr(Path, "unlink", fail_unlink)

    with SessionLocal() as db:
        result = asyncio.run(
            main.delete_file(
                file_path=storage_key,
                db=db,
                current_user=_security_actor(),
            )
        )

    assert result == {"message": "File deletion queued"}
    assert stored_file.is_file()
    with SessionLocal() as db:
        asset = db.query(models.UploadAsset).one()
        assert asset.state == "DELETE_PENDING"
        assert asset.delete_after is not None
    assert capsys.readouterr().out == ""
