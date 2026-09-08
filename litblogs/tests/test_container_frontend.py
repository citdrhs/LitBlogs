import importlib
import importlib.util
import re
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.responses import Response
from fastapi.testclient import TestClient

INDEX_HTML = '<!doctype html><html><body><div id="root">LitBlogs</div></body></html>'
VIDEO_BYTES = b"\x00\x00\x00\x20ftypisom" + bytes(range(128))


@pytest.fixture
def frontend_dist(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (dist / "assets").mkdir()
    (dist / "assets" / "index-AbCd1234.js").write_text("console.log('app');", encoding="utf-8")
    (dist / "assets" / "lesson-AbCd1234.mp4").write_bytes(VIDEO_BYTES)
    (dist / "assets" / "lesson-AbCd1234.vtt").write_text("WEBVTT\n\n", encoding="utf-8")
    (dist / "assets" / "current.js").write_text("console.log('current');", encoding="utf-8")
    (dist / "push-sw.js").write_text("self.addEventListener('push', () => {});", encoding="utf-8")
    (dist / "logo.png").write_bytes(b"public-logo")
    (dist / "school photo (1).jpeg").write_bytes(b"public-school-photo")
    (dist / ".env").write_text("PRIVATE_SECRET=never-public", encoding="utf-8")
    (dist / "README.md").write_text("not a public build entrypoint", encoding="utf-8")
    (dist / "uploads").mkdir()
    (dist / "uploads" / "student.txt").write_text("private student work", encoding="utf-8")
    (dist / "assets" / ".private.js").write_text("private", encoding="utf-8")
    return dist


def test_frontend_serves_spa_deep_links_without_caching(frontend_dist):
    assert importlib.util.find_spec("container_frontend") is not None, "Container frontend is not implemented"
    frontend = importlib.import_module("container_frontend")
    app = frontend.mount_frontend(FastAPI(), frontend_dist)
    with TestClient(app) as client:
        for path in ("/", "/index.html", "/help", "/classes/12/posts/34", "/help/?topic=video"):
            response = client.get(path)
            assert response.status_code == 200
            assert response.text == INDEX_HTML
            assert response.headers["content-type"] == "text/html; charset=utf-8"
            assert "no-store" in response.headers["cache-control"]


@pytest.fixture
def frontend_client(frontend_dist):
    frontend = importlib.import_module("container_frontend")
    app = FastAPI()

    @app.get("/api/probe")
    def probe():
        return {"backend": True}

    @app.get("/api/private")
    def private_file():
        return Response(
            "private",
            headers={"Content-Security-Policy": "sandbox; default-src 'none'", "Cache-Control": "private, no-store"},
        )

    frontend.mount_frontend(app, frontend_dist)
    with TestClient(app) as client:
        yield client


def test_api_routes_keep_priority_and_existing_security_headers(frontend_client):
    response = frontend_client.get("/api/probe")
    assert response.status_code == 200
    assert response.json() == {"backend": True}
    private_response = frontend_client.get("/api/private")
    assert private_response.headers["content-security-policy"] == "sandbox; default-src 'none'"
    assert private_response.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize(
    "path",
    [
        "/api", "/api/missing", "/uploads", "/uploads/student.txt", "/uploads/missing",
        "/.env", "/assets/.private.js", "/assets/missing.js", "/assets/missing",
        "/missing.js", "/README.md", "/assets/%2e%2e/index.html", "/%2e%2e/help",
        "/assets/%252e%252e/index.html", "/assets/%5c..%5cindex.html", "/logo.png:secret",
    ],
)
def test_non_frontend_paths_never_fall_back_to_html(frontend_client, path):
    response = frontend_client.get(path)
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"detail": "Not Found"}
    assert "no-store" in response.headers["cache-control"]


@pytest.mark.parametrize(
    ("path", "expected"),
    [("/logo.png", b"public-logo"), ("/school%20photo%20(1).jpeg", b"public-school-photo")],
)
def test_known_build_root_public_files_are_served(frontend_client, path, expected):
    response = frontend_client.get(path)
    assert response.status_code == 200
    assert response.content == expected
    assert "no-store" in response.headers["cache-control"]


def test_only_hash_named_assets_are_immutable(frontend_client):
    response = frontend_client.get("/assets/index-AbCd1234.js")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    for path in ("/assets/current.js", "/push-sw.js"):
        response = frontend_client.get(path)
        assert response.status_code == 200
        assert "no-store" in response.headers["cache-control"]
        assert "immutable" not in response.headers["cache-control"]


def test_captions_have_explicit_webvtt_type(frontend_client):
    response = frontend_client.get("/assets/lesson-AbCd1234.vtt")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/vtt; charset=utf-8"
    assert response.text.startswith("WEBVTT")


@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_video_byte_ranges_allow_browser_seeking(frontend_client, method):
    response = frontend_client.request(method, "/assets/lesson-AbCd1234.mp4", headers={"Range": "bytes=4-15"})
    assert response.status_code == 206
    assert response.headers["content-type"] == "video/mp4"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-range"] == f"bytes 4-15/{len(VIDEO_BYTES)}"
    assert response.headers["content-length"] == "12"
    assert response.content == (VIDEO_BYTES[4:16] if method == "GET" else b"")


def test_invalid_video_range_returns_416(frontend_client):
    response = frontend_client.get("/assets/lesson-AbCd1234.mp4", headers={"Range": "bytes=99999-"})
    assert response.status_code == 416
    assert response.headers["content-range"] == f"bytes */{len(VIDEO_BYTES)}"
    assert "no-store" in response.headers["cache-control"]


@pytest.mark.parametrize("path", ["/help", "/assets/index-AbCd1234.js", "/api/probe", "/api/missing"])
def test_security_headers_match_reviewed_nginx_defaults(frontend_client, path):
    nginx_path = Path(__file__).resolve().parents[2] / "deploy" / "nginx" / "litblogs.conf"
    expected_headers = dict(re.findall(r'add_header ([\w-]+) "([^\"]+)" always;', nginx_path.read_text()))
    expected_headers.pop("Cache-Control")
    response = frontend_client.get(path)
    for header_name, value in expected_headers.items():
        assert response.headers[header_name] == value


def test_static_requests_do_not_accept_writes(frontend_client):
    response = frontend_client.post("/help")
    assert response.status_code == 405
    assert response.headers["allow"] == "GET, HEAD"


def test_missing_frontend_build_fails_at_startup(tmp_path):
    frontend = importlib.import_module("container_frontend")
    with pytest.raises(RuntimeError, match="index.html"):
        frontend.mount_frontend(FastAPI(), tmp_path)


def test_container_frontend_rejects_shared_subpath_configuration(frontend_dist):
    frontend = importlib.import_module("container_frontend")
    with pytest.raises(ValueError, match="root"):
        frontend.mount_frontend(FastAPI(root_path="/shared/litblogs"), frontend_dist)


def test_symlinked_asset_cannot_escape_build_directory(frontend_dist, tmp_path):
    frontend = importlib.import_module("container_frontend")
    private = tmp_path / "student-work.txt"
    private.write_text("private student work", encoding="utf-8")
    link = frontend_dist / "assets" / "private-AbCd1234.txt"
    try:
        link.symlink_to(private)
    except OSError:
        pytest.skip("Creating a symlink is not permitted on this host")
    with TestClient(frontend.mount_frontend(FastAPI(), frontend_dist)) as client:
        assert client.get("/assets/private-AbCd1234.txt").status_code == 404


def test_container_entrypoint_preserves_real_backend_auth_and_host_checks(frontend_dist, monkeypatch):
    frontend = importlib.import_module("container_frontend")
    main = importlib.import_module("main")
    monkeypatch.setattr(frontend, "DEFAULT_DIST_DIRECTORY", frontend_dist)
    monkeypatch.setattr(main.app.router, "routes", list(main.app.router.routes))
    monkeypatch.setattr(main.app, "user_middleware", list(main.app.user_middleware))
    monkeypatch.setattr(main.app, "middleware_stack", None)
    monkeypatch.delitem(sys.modules, "container_app", raising=False)
    try:
        container = importlib.import_module("container_app")
        assert container.app is main.app
        with TestClient(container.app) as client:
            assert client.get("/help").text == INDEX_HTML
            assert client.get("/api/").json() == {"message": "Welcome to LitBlogs Backend"}
            protected = client.get("/api/user/profile")
            assert protected.status_code == 401
            assert protected.headers["www-authenticate"] == "Bearer"
            assert protected.headers["cache-control"] == "no-store"
            assert protected.headers["x-request-id"]
            assert client.get("/api/uploads/student.txt").status_code == 401
            assert client.get("/uploads/student.txt").status_code == 404
            assert client.get("/api/missing").json() == {"detail": "Not Found"}
            assert client.get("/help", headers={"Host": "attacker.example"}).status_code == 400
    finally:
        sys.modules.pop("container_app", None)


def test_development_backend_does_not_serve_frontend(client):
    assert client.get("/help").status_code == 404
