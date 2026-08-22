import ast
import asyncio
import inspect
import textwrap
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.datastructures import Headers
from starlette.routing import Mount

import main

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"safe-image-payload"
PDF_BYTES = b"%PDF-1.7\n" + b"safe-pdf-payload"
MP4_BYTES = b"\x00\x00\x00\x18ftypisom" + b"safe-video-payload"


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
            <source src="/uploads/videos/42/book-talk.mp4" type="video/mp4">
          </video>
        </figure>
        <video controls src="/api/uploads/videos/42/direct.mp4"></video>
        <video controls src="https://tracker.example/direct.mp4"></video>
        <video controls src="data:video/mp4;base64,AAAA"></video>
        <img src="/api/uploads/images/42/cover.png" alt="Book cover">
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
    assert '<source src="/uploads/videos/42/book-talk.mp4" type="video/mp4">' in sanitized
    assert 'src="/api/uploads/videos/42/direct.mp4"' in sanitized
    assert "https://tracker.example/direct.mp4" not in sanitized
    assert "data:video/mp4" not in sanitized
    assert '<img src="/api/uploads/images/42/cover.png" alt="Book cover">' in sanitized


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
        files=[{"name": "</div><img src=x onerror=alert(1)>", "url": "/uploads/files/42/x.pdf"}],
    )

    built = main._build_post_content(post)

    assert "<script" not in built.lower()
    assert "<img src=x" not in built.lower()
    assert "&lt;img" in built


@pytest.mark.parametrize(
    ("reference", "expected"),
    [
        ("/uploads/files/42/reading.pdf", "files/42/reading.pdf"),
        ("/api/uploads/files/42/reading.pdf", "files/42/reading.pdf"),
        ("/dren/api/uploads/files/42/reading.pdf", "files/42/reading.pdf"),
        ("files/42/reading.pdf", "files/42/reading.pdf"),
    ],
)
def test_upload_reference_parser_accepts_canonical_local_forms(reference, expected):
    assert main._canonical_upload_relative_path(reference) == expected


@pytest.mark.parametrize(
    "reference",
    [
        "https://tracker.example/uploads/files/42/reading.pdf",
        "//tracker.example/uploads/files/42/reading.pdf",
        "/uploads.evil/files/42/reading.pdf",
        "/api/uploads/../secrets.env",
        "/api/uploads/%2e%2e/secrets.env",
        "/api/uploads/files%2f..%2fsecrets.env",
        "/api/uploads/files\\..\\secrets.env",
        "/api/uploads/files/42/reading.pdf?token=secret",
        "/api/uploads/files/42/reading.pdf#fragment",
        "/api/uploads/files/42/read\x00ing.pdf",
        "/api/uploads/files/42/reading.pdf::$DATA",
        "/api/uploads/files/42/read%3Asecret.pdf",
        "/api/uploads/files/42/read%ZZing.pdf",
        "",
    ],
)
def test_upload_reference_parser_rejects_malformed_or_escaping_paths(reference):
    with pytest.raises(ValueError, match="upload"):
        main._canonical_upload_relative_path(reference)


def test_upload_reference_parser_rejects_very_long_input_without_a_regex():
    oversized = "/uploads/" + ("uploads/a/" * 50_000) + "reading.pdf"

    with pytest.raises(ValueError, match="upload"):
        main._canonical_upload_relative_path(oversized)

    parser_source = textwrap.dedent(
        inspect.getsource(main._canonical_upload_relative_path)
    )
    tree = ast.parse(parser_source)
    regex_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"match", "fullmatch", "search"}
    ]
    assert regex_calls == []


def test_upload_path_cannot_escape_upload_root(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)

    assert main._upload_path("files", "42", "reading.pdf") == (
        tmp_path / "files" / "42" / "reading.pdf"
    ).resolve()

    with pytest.raises(ValueError, match="upload"):
        main._upload_path("..", "secrets.env")


def test_missing_upload_does_not_fall_back_to_another_users_same_filename(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    other_users_file = tmp_path / "files" / "99" / "private.pdf"
    other_users_file.parent.mkdir(parents=True)
    other_users_file.write_bytes(b"private")

    with pytest.raises(HTTPException) as error:
        asyncio.run(main.get_uploaded_file("files/42/private.pdf"))

    assert error.value.status_code == 404


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
    monkeypatch,
    tmp_path,
    filename,
    content_type,
    content,
):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            main.upload_image(
                make_upload(filename, content_type, content),
                current_user=SimpleNamespace(id=42),
            )
        )

    assert error.value.status_code == 400
    assert [path for path in tmp_path.rglob("*") if path.is_file()] == []


def test_validated_upload_is_bounded_opaque_and_cleans_partial_files(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(main, "MAX_IMAGE_UPLOAD_BYTES", len(PNG_BYTES) - 1)

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            main.upload_image(
                make_upload("student-private-name.png", "image/png", PNG_BYTES),
                current_user=SimpleNamespace(id=42),
            )
        )

    assert error.value.status_code == 413
    assert [path for path in tmp_path.rglob("*") if path.is_file()] == []

    monkeypatch.setattr(main, "MAX_IMAGE_UPLOAD_BYTES", len(PNG_BYTES))
    result = asyncio.run(
        main.upload_image(
            make_upload("student-private-name.png", "image/png", PNG_BYTES),
            current_user=SimpleNamespace(id=42),
        )
    )
    stored_name = Path(result["url"]).name
    assert stored_name.endswith(".png")
    assert "student-private-name" not in stored_name
    assert (tmp_path / "images" / "42" / stored_name).read_bytes() == PNG_BYTES


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
    main.app.dependency_overrides[main.get_current_user] = lambda: SimpleNamespace(id=42)
    try:
        upload_response = client.post(
            "/api/upload/image",
            files={"file": ("cover.png", PNG_BYTES, "image/png")},
        )
        assert upload_response.status_code == 200

        upload_url = upload_response.json()["url"]
        assert upload_url.startswith("/api/uploads/images/42/")

        served_response = client.get(upload_url)
        assert served_response.status_code == 200
        assert served_response.content == PNG_BYTES
        assert served_response.headers["content-type"] == "image/png"

        upload_path = upload_url.removeprefix("/api/uploads/")
        delete_response = client.delete(f"/api/upload/{upload_path}")
        assert delete_response.status_code == 200
        assert not any(path.is_file() for path in tmp_path.rglob("*"))
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
        main.upload_profile_image,
        main.upload_cover_image,
    ):
        assert "_save_validated_upload" in inspect.getsource(endpoint)


def test_uploads_are_not_exposed_through_the_public_static_mount():
    assert not any(
        isinstance(route, Mount) and route.path == "/uploads"
        for route in main.app.routes
    )


def test_upload_route_requires_authentication_before_revealing_file(client, monkeypatch, tmp_path):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    image_path = tmp_path / "images" / "42" / "safe.png"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(PNG_BYTES)

    unauthenticated = client.get("/api/uploads/images/42/safe.png")
    assert unauthenticated.status_code == 401

    main.app.dependency_overrides[main.get_current_user] = lambda: SimpleNamespace(id=42)
    try:
        authenticated = client.get("/api/uploads/images/42/safe.png")
    finally:
        main.app.dependency_overrides.pop(main.get_current_user, None)

    assert authenticated.status_code == 200
    assert authenticated.content == PNG_BYTES


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


def test_safe_upload_response_has_fixed_type_and_defensive_headers(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    image_path = tmp_path / "images" / "42" / "safe.png"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(PNG_BYTES)

    response = asyncio.run(main.get_uploaded_file("images/42/safe.png"))

    assert response.media_type == "image/png"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cross-origin-resource-policy"] == "same-origin"
    assert response.headers["cache-control"] == "private, no-store"
    assert "sandbox" in response.headers["content-security-policy"]
    assert response.headers["content-disposition"].startswith("inline;")


def test_pdf_uploads_are_always_served_as_attachments(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    document_path = tmp_path / "files" / "42" / "safe.pdf"
    document_path.parent.mkdir(parents=True)
    document_path.write_bytes(PDF_BYTES)

    response = asyncio.run(main.get_uploaded_file("files/42/safe.pdf"))

    assert response.media_type == "application/pdf"
    assert response.headers["content-disposition"].startswith("attachment;")


def test_download_uses_stored_type_and_sanitizes_requested_filename(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    document_path = tmp_path / "files" / "42" / "safe.pdf"
    document_path.parent.mkdir(parents=True)
    document_path.write_bytes(PDF_BYTES)

    response = asyncio.run(
        main.download_file(
            "/api/uploads/files/42/safe.pdf",
            'report.html"\r\nX-Injected: true',
            current_user=SimpleNamespace(id=42),
        )
    )

    disposition = response.headers["content-disposition"]
    assert response.media_type == "application/pdf"
    assert disposition.startswith("attachment;")
    assert ".html" not in disposition
    assert disposition.endswith('report.pdf"')
    assert "\r" not in disposition and "\n" not in disposition
    assert response.headers["x-content-type-options"] == "nosniff"


def test_upload_and_download_errors_do_not_disclose_server_paths(
    monkeypatch,
    tmp_path,
    capsys,
):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)

    with pytest.raises(HTTPException) as upload_error:
        asyncio.run(main.get_uploaded_file("files/42/private-name.pdf"))
    assert upload_error.value.status_code == 404
    assert upload_error.value.detail == "File not found"

    document_path = tmp_path / "files" / "42" / "safe.pdf"
    document_path.parent.mkdir(parents=True)
    document_path.write_bytes(PDF_BYTES)
    monkeypatch.setattr(
        main,
        "_safe_upload_file_response",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError(str(tmp_path / "private" / "student-record.pdf"))
        ),
    )

    with pytest.raises(HTTPException) as download_error:
        asyncio.run(
            main.download_file(
                "/api/uploads/files/42/safe.pdf",
                "reading.pdf",
                current_user=SimpleNamespace(id=42),
            )
        )
    assert download_error.value.status_code == 500
    assert download_error.value.detail == "Failed to download file"
    assert capsys.readouterr().out == ""


def test_existing_active_or_forged_uploads_are_not_served(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    active_svg = tmp_path / "images" / "42" / "active.svg"
    forged_png = tmp_path / "images" / "42" / "forged.png"
    active_svg.parent.mkdir(parents=True)
    active_svg.write_bytes(b"<svg onload='alert(1)'></svg>")
    forged_png.write_bytes(b"<script>alert(1)</script>")

    for reference in ("images/42/active.svg", "images/42/forged.png"):
        with pytest.raises(HTTPException) as error:
            asyncio.run(main.get_uploaded_file(reference))
        assert error.value.status_code == 404


def test_delete_upload_maps_malformed_paths_to_bad_request():
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            main.delete_file(
                file_path="../secrets.env",
                current_user=SimpleNamespace(id=42),
            )
        )

    assert error.value.status_code == 400
    assert error.value.detail == "Invalid upload path"


def test_delete_upload_does_not_accept_another_user_id_with_the_same_prefix():
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            main.delete_file(
                file_path="files/420/reading.pdf",
                current_user=SimpleNamespace(id=42),
            )
        )

    assert error.value.status_code == 403


def test_delete_upload_rejects_directories_without_disclosing_paths(
    monkeypatch,
    tmp_path,
    capsys,
):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    (tmp_path / "images" / "42").mkdir(parents=True)

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            main.delete_file(
                file_path="images/42",
                current_user=SimpleNamespace(id=42),
            )
        )

    assert error.value.status_code == 404
    assert error.value.detail == "File not found"
    assert capsys.readouterr().out == ""


def test_delete_upload_io_failures_are_generic_and_not_printed(
    monkeypatch,
    tmp_path,
    capsys,
):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    stored_file = tmp_path / "images" / "42" / "safe.png"
    stored_file.parent.mkdir(parents=True)
    stored_file.write_bytes(PNG_BYTES)

    def fail_unlink(_path):
        raise OSError(str(tmp_path / "private" / "student-record.png"))

    monkeypatch.setattr(Path, "unlink", fail_unlink)

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            main.delete_file(
                file_path="images/42/safe.png",
                current_user=SimpleNamespace(id=42),
            )
        )

    assert error.value.status_code == 500
    assert error.value.detail == "Failed to delete file"
    assert capsys.readouterr().out == ""
