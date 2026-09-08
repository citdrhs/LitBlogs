"""Container-only, root-origin delivery of the immutable frontend build.

This module deliberately does not import the backend or its database settings.
Only the dist directory is served; private upload storage is never mounted.
"""

import re
import stat
from pathlib import Path

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import MutableHeaders
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Message, Receive, Scope, Send

DEFAULT_DIST_DIRECTORY = Path(__file__).resolve().parent / "dist"
NO_STORE = "no-cache, no-store, must-revalidate"
IMMUTABLE = "public, max-age=31536000, immutable"
HASHED_ASSET = re.compile(r"^assets/[^/]+-[A-Za-z0-9_-]{8,}\.[A-Za-z0-9]+$")
ASSET_SUFFIXES = frozenset({".css", ".js", ".mjs", ".map", ".png", ".jpg", ".jpeg", ".gif", ".svg",
                            ".webp", ".avif", ".woff", ".woff2", ".mp4", ".txt", ".vtt"})
# Vite copies these reviewed public/ files directly into the build root.
PUBLIC_ROOT_FILES = frozenset({
    "push-sw.js", "logo.png", "litBlogSmallLight.png", "school photo (1).jpeg",
    "tambellini.jpg", "musk.jpg", "Classroom1.jpeg", "Classroom2.jpeg", "Classroom3.jpeg", "Classroom4.jpeg",
})
SECURITY_HEADERS = {
    "strict-transport-security": "max-age=31536000; includeSubDomains",
    "content-security-policy": (
        "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; form-action 'self'; "
        "script-src 'self' https://accounts.google.com https://apis.google.com; "
        "style-src 'self' 'unsafe-inline' https://accounts.google.com; font-src 'self' data:; "
        "img-src 'self' data: blob: https://*.googleusercontent.com; media-src 'self' data: blob:; "
        "connect-src 'self' https://accounts.google.com https://login.microsoftonline.com https://graph.microsoft.com; "
        "frame-src 'self' https://accounts.google.com https://login.microsoftonline.com; worker-src 'self' blob:; "
        "manifest-src 'self'; upgrade-insecure-requests"
    ),
    "x-frame-options": "DENY",
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "permissions-policy": "camera=(), microphone=(), geolocation=()",
    "cross-origin-opener-policy": "same-origin-allow-popups",
    "cross-origin-resource-policy": "same-origin",
}


class ContainerSecurityHeadersMiddleware:
    """Fill nginx-equivalent defaults without changing stricter backend headers."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                message = {**message, "headers": list(message.get("headers", []))}
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    headers.setdefault(name, value)
                headers.setdefault("cache-control", NO_STORE)
            await send(message)

        await self.app(scope, receive, send_with_headers)


class ContainerFrontend(StaticFiles):
    """Serve reviewed build files and extensionless SPA routes, never API paths."""

    def __init__(self, directory: Path):
        directory = directory.resolve()
        index = directory / "index.html"
        if not index.is_file() or not index.resolve().is_relative_to(directory):
            raise RuntimeError("Container frontend build must contain index.html inside its dist directory")
        super().__init__(directory=directory, html=False, follow_symlink=False)

    async def get_response(self, path: str, scope: Scope) -> Response:
        # Inspect the original decoded path BEFORE StaticFiles' normalized path.
        # Reject Windows separators/streams and doubly encoded path components too.
        request_path = scope["path"]
        parts = request_path.strip("/").split("/")
        if (
            any(part.startswith(".") for part in parts)
            or re.search(r"[\\%:\x00-\x1f\x7f]", request_path)
            or parts[0].lower() in {"api", "uploads"}
        ):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        if scope["method"] not in {"GET", "HEAD"}:
            return JSONResponse({"detail": "Method Not Allowed"}, status_code=405, headers={"Allow": "GET, HEAD"})

        relative_path = "/".join(parts)
        if parts[0] == "assets":
            if Path(relative_path).suffix.lower() not in ASSET_SUFFIXES:
                return JSONResponse({"detail": "Not Found"}, status_code=404)
        elif relative_path not in PUBLIC_ROOT_FILES and relative_path != "index.html":
            if any("." in part for part in parts):
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            relative_path = "index.html"

        full_path, file_stat = await run_in_threadpool(self.lookup_path, relative_path)
        if file_stat is None or not stat.S_ISREG(file_stat.st_mode):
            return JSONResponse({"detail": "Not Found"}, status_code=404)

        # Do not rely on the host's MIME database for tutorial captions/video.
        media_type = {".vtt": "text/vtt", ".mp4": "video/mp4"}.get(Path(relative_path).suffix.lower())
        return FileResponse(
            full_path,
            stat_result=file_stat,
            media_type=media_type,
            headers={"Cache-Control": IMMUTABLE if HASHED_ASSET.fullmatch(relative_path) else NO_STORE},
        )


def mount_frontend(app: FastAPI, dist_directory: str | Path | None = None) -> FastAPI:
    """Append frontend delivery after the backend routes before application startup."""
    if app.root_path:
        raise ValueError("The production container requires a dedicated hostname served at the root path")
    frontend = ContainerFrontend(Path(dist_directory) if dist_directory is not None else DEFAULT_DIST_DIRECTORY)
    app.add_middleware(ContainerSecurityHeadersMiddleware)
    app.mount("/", frontend, name="container-frontend")
    return app
