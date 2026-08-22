# main.py
# To run locally run:
# uvicorn main:app --reload --host 0.0.0.0 --port 8000 &
import hashlib
import json
import logging
import os
import re
import secrets
import stat
import string
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from html import escape
from http.cookies import CookieError, SimpleCookie
from ipaddress import ip_address
from pathlib import Path
from typing import List, Literal
from urllib.parse import urlsplit

import bleach
import tinycss2
import uvicorn
from bleach.css_sanitizer import CSSSanitizer
from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import OAuth2PasswordBearer
from google.oauth2 import id_token
from jwt.exceptions import InvalidTokenError
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from sqlalchemy import or_, text, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import MutableHeaders
from starlette.middleware.trustedhost import TrustedHostMiddleware

import models
import password_reset_delivery
import schemas
from access_control import (
    can_access_class as _can_access_class,
)
from access_control import (
    can_moderate_post as _can_moderate_post,
)
from access_control import (
    can_view_post_analysis as _can_view_post_analysis,
)
from access_control import (
    get_teacher_record as _get_teacher_record,
)
from access_control import (
    require_active_class as _ensure_class_is_active,
)
from access_control import (
    require_active_class_access as _ensure_active_class_access,
)
from access_control import (
    require_active_class_owner as _ensure_active_class_owner,
)
from access_control import (
    require_admin as _require_admin,
)
from access_control import (
    require_assignment_for_class as _ensure_assignment_for_class,
)
from access_control import (
    require_class_access as _ensure_class_access,
)
from access_control import (
    require_class_owner as _ensure_class_owner,
)
from access_control import (
    require_comment_access as _ensure_comment_access,
)
from access_control import (
    require_enrolled_student as _ensure_enrolled_student,
)
from access_control import (
    require_post_access as _ensure_post_access,
)
from access_control import (
    require_profile_access as _ensure_profile_access,
)
from access_control import (
    require_submission_access as _ensure_submission_access,
)
from access_control import (
    teacher_owns_class as _teacher_owns_class,
)
from access_control import (
    user_class_ids as _get_user_class_ids,
)
from auth_security import (
    csrf_token_matches,
    decode_access_token,
    hash_password,
    issue_access_token,
    verify_and_update_password,
    verify_password,
)
from config import get_settings
from database import SessionLocal, check_database_readiness, get_db
from identity_controls import (
    SessionIssuanceDenied,
    consume_teacher_invitation,
    find_active_browser_session,
    invalidate_password_reset_requests,
    issue_browser_session,
    normalize_email,
    record_operator_audit_event,
    revoke_all_sessions,
    revoke_session,
)
from oauth_security import verify_google_id_token, verify_microsoft_id_token
from observability import RequestObservabilityMiddleware
from upload_assets import (
    add_active_profile_asset,
    add_pending_asset,
    bind_post_assets,
    canonical_object_key,
    configure_upload_transaction,
    enforce_quota,
    enforce_rate_limit,
    object_matches_registration,
    open_verified_registered_object,
    post_asset_keys,
    queue_assets,
    queue_blog_assets,
    queue_owner_assets,
    validate_structured_upload_references,
)
from upload_assets import (
    lock_blog as _lock_upload_blog,
)
from upload_assets import (
    lock_owner as _lock_upload_owner,
)
from upload_assets import (
    reconcile as _reconcile_upload_assets,
)
from upload_scanner import (
    ClamdUploadScanner,
    NoopUploadScanner,
    UploadRejected,
    UploadScannerUnavailable,
)

settings = get_settings()
security_logger = logging.getLogger("litblogs.security")
readiness_logger = logging.getLogger("litblogs.readiness")
_DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(32))
# Preserve the existing test/integration patch point while sharing the standalone
# delivery module's SMTP client.
smtplib = password_reset_delivery.smtplib


def _utc_now_naive() -> datetime:
    """Return UTC as a naive datetime for the app's existing database columns."""
    return datetime.now(UTC).replace(tzinfo=None)


def _utc_now_aware() -> datetime:
    """Return aware UTC for TIMESTAMPTZ-backed upload lifecycle columns."""
    return datetime.now(UTC)

try:
    from pywebpush import WebPushException, webpush
except Exception:
    webpush = None
    WebPushException = Exception

def _secret_value(value) -> str | None:
    return value.get_secret_value() if value is not None else None

FRONTEND_URL = (settings.frontend_url or "https://drhscit.org/dren").rstrip("/")
CORS_ALLOWED_ORIGINS = list(settings.cors_allowed_origins)
VAPID_PUBLIC_KEY = settings.vapid_public_key
VAPID_PRIVATE_KEY = settings.vapid_private_key.get_secret_value() if settings.vapid_private_key else ""
VAPID_SUBJECT = settings.vapid_subject
WEB_PUSH_ENABLED = bool(
    settings.push_notifications_enabled
    and VAPID_PUBLIC_KEY
    and VAPID_PRIVATE_KEY
    and webpush
)
PUSH_REMINDER_INTERVAL_SECONDS = settings.push_reminder_interval_seconds
PUSH_ALLOWED_ENDPOINT_HOSTS = settings.push_allowed_endpoint_hosts
PUSH_DELIVERY_TIMEOUT_SECONDS = settings.push_delivery_timeout_seconds
PASSWORD_RESET_WORKER_ENABLED = settings.password_reset_worker_enabled
PASSWORD_RESET_WORKER_INTERVAL_SECONDS = settings.password_reset_worker_interval_seconds
PASSWORD_RESET_CLAIM_TIMEOUT_SECONDS = settings.password_reset_claim_timeout_seconds

if "*" in CORS_ALLOWED_ORIGINS:
    raise RuntimeError("CORS_ALLOWED_ORIGINS must not contain a wildcard when credentials are enabled")

@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.upload_scanner_required:
        await run_in_threadpool(upload_scanner.preflight)
    yield

app = FastAPI(
    lifespan=lifespan,
    docs_url="/api/docs" if settings.api_docs_enabled else None,
    redoc_url="/api/redoc" if settings.api_docs_enabled else None,
    openapi_url="/api/openapi.json" if settings.api_docs_enabled else None,
)

OAUTH_AUTH_PATHS = frozenset(
    {
        "/api/auth/google-login",
        "/api/auth/google-signup",
        "/api/auth/microsoft-login",
        "/api/auth/microsoft-signup",
    }
)
SENSITIVE_CREDENTIAL_AUTH_PATHS = frozenset(
    {
        "/api/auth/register",
        "/api/auth/login",
        "/api/auth/change-password",
        "/api/auth/forgot-password",
        "/api/auth/reset-password",
    }
)
GOOGLE_IDENTITY_ISSUER = "https://accounts.google.com"


@app.exception_handler(RequestValidationError)
async def safe_auth_request_validation_error(request: Request, exc: RequestValidationError):
    if _is_private_assignment_mutation(request):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"detail": "Invalid assignment request"},
            headers=ASSIGNMENT_PRIVATE_CACHE_HEADERS,
        )
    if request.url.path in OAUTH_AUTH_PATHS:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "External authentication failed"},
        )
    if request.url.path in SENSITIVE_CREDENTIAL_AUTH_PATHS:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"detail": "Invalid authentication request"},
        )
    return await request_validation_exception_handler(request, exc)

# Fix CORS middleware setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Accept", "Authorization", "Content-Type", "X-CSRF-Token"],
)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=list(settings.allowed_hosts)
    or ["testserver", "localhost", "127.0.0.1", "[::1]"],
)
app.add_middleware(RequestObservabilityMiddleware)

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = (
    settings.upload_root.resolve()
    if settings.upload_root is not None
    else BASE_DIR / "uploads"
)
if settings.app_env == "production" and UPLOAD_DIR.is_relative_to(BASE_DIR):
    raise RuntimeError("UPLOAD_ROOT must be outside the application source tree")


def _build_upload_scanner(configured_settings):
    if configured_settings.upload_scanner_required and not configured_settings.upload_scanner_host:
        raise RuntimeError("Required upload scanner is unavailable")
    if configured_settings.upload_scanner_host:
        return ClamdUploadScanner(
            configured_settings.upload_scanner_host,
            configured_settings.upload_scanner_port,
            configured_settings.upload_scanner_timeout_seconds,
        )
    return NoopUploadScanner()


upload_scanner = _build_upload_scanner(settings)
UPLOAD_CHUNK_SIZE = 1024 * 1024
UPLOAD_HEADER_BYTES = 512
MAX_IMAGE_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_VIDEO_UPLOAD_BYTES = 100 * 1024 * 1024
MAX_PDF_UPLOAD_BYTES = 25 * 1024 * 1024
UPLOAD_REQUEST_OVERHEAD_BYTES = 1024 * 1024
MAX_RICH_TEXT_INPUT_LENGTH = 1_000_000
MAX_ASSIGNMENT_REQUEST_BODY_BYTES = (
    6 * schemas.MAX_ASSIGNMENT_CONTENT_LENGTH
    + 64 * 1024
)
ASSIGNMENT_PRIVATE_CACHE_HEADERS = {
    "Cache-Control": "private, no-store",
    "Pragma": "no-cache",
    "Expires": "0",
}


class UploadAdmissionController:
    """Bound upload attempts and concurrent body/scanner work per process."""

    def __init__(self, *, attempt_limit: int = 20, window_seconds: int = 300, max_inflight: int = 4):
        self.attempt_limit = attempt_limit
        self.window_seconds = window_seconds
        self.max_inflight = max_inflight
        self._lock = threading.Lock()
        self._attempts = defaultdict(deque)
        self._inflight = 0

    def acquire(self, identity: str) -> None:
        now = time.monotonic()
        with self._lock:
            attempts = self._attempts[identity]
            cutoff = now - self.window_seconds
            while attempts and attempts[0] <= cutoff:
                attempts.popleft()
            if len(attempts) >= self.attempt_limit:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Upload attempt rate limit exceeded",
                )
            if self._inflight >= self.max_inflight:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Upload capacity is temporarily unavailable",
                )
            attempts.append(now)
            self._inflight += 1

    def release(self) -> None:
        with self._lock:
            self._inflight = max(0, self._inflight - 1)

    def reset(self) -> None:
        with self._lock:
            self._attempts.clear()
            self._inflight = 0


upload_admission = UploadAdmissionController()


def _scope_header(scope: dict, name: bytes) -> str | None:
    for header_name, header_value in scope.get("headers", []):
        if header_name.lower() == name:
            try:
                return header_value.decode("latin-1")
            except UnicodeDecodeError:
                return None
    return None


def _upload_admission_identity(scope: dict) -> str:
    authorization = _scope_header(scope, b"authorization")
    bearer_token = None
    if authorization and authorization.lower().startswith("bearer "):
        bearer_token = authorization[7:].strip()

    cookie_token = None
    raw_cookie = _scope_header(scope, b"cookie")
    if raw_cookie:
        try:
            cookies = SimpleCookie()
            cookies.load(raw_cookie)
            morsel = cookies.get(_session_cookie_name())
            cookie_token = morsel.value if morsel else None
        except CookieError:
            cookie_token = None

    tokens = [token for token in (bearer_token, cookie_token) if token]
    if len(tokens) == 1:
        try:
            payload = decode_access_token(tokens[0], settings=settings)
            return f"user:{int(payload['sub'])}"
        except (InvalidTokenError, KeyError, TypeError, ValueError):
            pass

    client = scope.get("client") or ("unknown", 0)
    return f"ip:{client[0]}"


class _UploadRequestTooLarge(Exception):
    pass


def _upload_request_body_limit(scope: dict) -> int | None:
    if scope.get("type") != "http" or scope.get("method", "").upper() != "POST":
        return None

    path = str(scope.get("path") or "").rstrip("/") or "/"
    upload_limits = {
        "/api/upload/image": MAX_IMAGE_UPLOAD_BYTES,
        "/api/upload/video": MAX_VIDEO_UPLOAD_BYTES,
        "/api/upload/file": MAX_PDF_UPLOAD_BYTES,
        "/api/upload": MAX_VIDEO_UPLOAD_BYTES,
        "/api/user/upload-profile-image": MAX_IMAGE_UPLOAD_BYTES,
        "/api/user/upload-cover-image": MAX_IMAGE_UPLOAD_BYTES,
    }
    file_limit = upload_limits.get(path)
    if file_limit is None:
        return None
    return file_limit + UPLOAD_REQUEST_OVERHEAD_BYTES


def _private_assignment_request_body_limit(scope: dict) -> int | None:
    if scope.get("type") != "http":
        return None

    method = str(scope.get("method") or "").upper()
    path = str(scope.get("path") or "").rstrip("/") or "/"
    path_match = re.fullmatch(
        r"/api/assignments/[^/]+/(?P<operation>draft|submit)",
        path,
    )
    if not path_match:
        return None

    operation = path_match.group("operation")
    if (
        (operation == "draft" and method == "PUT")
        or (operation == "submit" and method == "POST")
    ):
        return MAX_ASSIGNMENT_REQUEST_BODY_BYTES
    return None


class UploadRequestBodyLimitMiddleware:
    """Reject bounded private and upload bodies before Starlette parses them."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        upload_limit = _upload_request_body_limit(scope)
        assignment_limit = _private_assignment_request_body_limit(scope)
        request_limit = (
            assignment_limit
            if assignment_limit is not None
            else upload_limit
        )
        if request_limit is None:
            await self.app(scope, receive, send)
            return

        admitted = False
        if upload_limit is not None:
            try:
                upload_admission.acquire(_upload_admission_identity(scope))
                admitted = True
            except HTTPException as exc:
                response = JSONResponse(
                    status_code=exc.status_code,
                    content={"detail": exc.detail},
                    headers={"Cache-Control": "no-store"},
                )
                await response(scope, receive, send)
                return

        try:
            await self._call_with_limit(
                scope,
                receive,
                send,
                request_limit=request_limit,
                private_assignment=assignment_limit is not None,
            )
        finally:
            if admitted:
                upload_admission.release()

    async def _call_with_limit(
        self,
        scope,
        receive,
        send,
        *,
        request_limit: int,
        private_assignment: bool,
    ):

        for header_name, header_value in scope.get("headers", []):
            if header_name.lower() != b"content-length":
                continue
            try:
                content_length = int(header_value)
            except (TypeError, ValueError):
                break
            if content_length > request_limit:
                await self._send_too_large(
                    scope,
                    receive,
                    send,
                    private_assignment=private_assignment,
                )
                return
            break

        received_bytes = 0
        response_started = False

        async def limited_receive():
            nonlocal received_bytes
            message = await receive()
            if message.get("type") == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > request_limit:
                    raise _UploadRequestTooLarge
            return message

        async def tracked_send(message):
            nonlocal response_started
            if message.get("type") == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except _UploadRequestTooLarge:
            if response_started:
                raise
            await self._send_too_large(
                scope,
                receive,
                send,
                private_assignment=private_assignment,
            )

    @staticmethod
    async def _send_too_large(
        scope,
        receive,
        send,
        *,
        private_assignment: bool = False,
    ):
        response = JSONResponse(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            content={
                "detail": (
                    "Invalid assignment request"
                    if private_assignment
                    else "Upload request exceeds the allowed size"
                )
            },
            headers=(
                ASSIGNMENT_PRIVATE_CACHE_HEADERS
                if private_assignment
                else {"Cache-Control": "no-store"}
            ),
        )
        await response(scope, receive, send)


app.add_middleware(UploadRequestBodyLimitMiddleware)

def _sanitize_filename(filename: str | None, fallback: str = "upload") -> str:
    clean_name = Path(filename or fallback).name
    if not clean_name or clean_name in {".", ".."}:
        clean_name = fallback
    return re.sub(r"[^A-Za-z0-9._-]", "_", clean_name)

def _build_unique_filename(filename: str | None, prefix: str | None = None) -> str:
    safe_name = _sanitize_filename(filename)
    suffix = Path(safe_name).suffix.lower()
    safe_prefix = _sanitize_filename(prefix, "").strip("._-") if prefix else ""
    opaque_name = secrets.token_hex(16)
    return f"{safe_prefix}_{opaque_name}{suffix}" if safe_prefix else f"{opaque_name}{suffix}"

def _upload_path(*parts: str) -> Path:
    upload_root = UPLOAD_DIR.resolve()
    candidate = upload_root.joinpath(*(str(part) for part in parts)).resolve()
    try:
        candidate.relative_to(upload_root)
    except ValueError as exc:
        raise ValueError("Invalid upload path") from exc
    return candidate


def _upload_url(*parts: str) -> str:
    normalized_parts = [str(part).replace("\\", "/").strip("/") for part in parts if str(part).strip("/")]
    return f"/api/uploads/{'/'.join(normalized_parts)}"

@dataclass(frozen=True)
class UploadTypeSpec:
    kind: str
    bucket: str
    extension: str
    media_type: str
    signature: str
    declared_media_types: frozenset[str]


def _upload_type_spec(
    kind: str,
    bucket: str,
    extension: str,
    media_type: str,
    signature: str,
    *declared_media_types: str,
) -> UploadTypeSpec:
    return UploadTypeSpec(
        kind=kind,
        bucket=bucket,
        extension=extension,
        media_type=media_type,
        signature=signature,
        declared_media_types=frozenset(declared_media_types or (media_type,)),
    )


UPLOAD_TYPE_SPECS = {
    ".jpg": _upload_type_spec("image", "images", ".jpg", "image/jpeg", "jpeg"),
    ".jpeg": _upload_type_spec("image", "images", ".jpeg", "image/jpeg", "jpeg"),
    ".png": _upload_type_spec("image", "images", ".png", "image/png", "png"),
    ".gif": _upload_type_spec("image", "images", ".gif", "image/gif", "gif"),
    ".webp": _upload_type_spec("image", "images", ".webp", "image/webp", "webp"),
    ".bmp": _upload_type_spec("image", "images", ".bmp", "image/bmp", "bmp"),
    ".pdf": _upload_type_spec("pdf", "files", ".pdf", "application/pdf", "pdf"),
    ".mp4": _upload_type_spec("video", "videos", ".mp4", "video/mp4", "mp4"),
    ".m4v": _upload_type_spec(
        "video", "videos", ".m4v", "video/x-m4v", "mp4", "video/x-m4v", "video/mp4"
    ),
    ".webm": _upload_type_spec("video", "videos", ".webm", "video/webm", "ebml"),
    ".mkv": _upload_type_spec("video", "videos", ".mkv", "video/x-matroska", "ebml"),
    ".ogg": _upload_type_spec("video", "videos", ".ogg", "video/ogg", "ogg"),
    ".avi": _upload_type_spec("video", "videos", ".avi", "video/x-msvideo", "avi"),
}
def _matches_upload_signature(spec: UploadTypeSpec, header: bytes) -> bool:
    signatures = {
        "jpeg": header.startswith(b"\xff\xd8\xff"),
        "png": header.startswith(b"\x89PNG\r\n\x1a\n"),
        "gif": header.startswith((b"GIF87a", b"GIF89a")),
        "webp": len(header) >= 12 and header.startswith(b"RIFF") and header[8:12] == b"WEBP",
        "bmp": header.startswith(b"BM"),
        "pdf": header.startswith(b"%PDF-"),
        "mp4": len(header) >= 12 and header[4:8] == b"ftyp",
        "ebml": header.startswith(b"\x1aE\xdf\xa3"),
        "ogg": header.startswith(b"OggS"),
        "avi": len(header) >= 12 and header.startswith(b"RIFF") and header[8:12] == b"AVI ",
    }
    return signatures.get(spec.signature, False)


def _validated_upload_spec(
    file: UploadFile,
    allowed_kinds: set[str],
    header: bytes,
) -> UploadTypeSpec:
    extension = Path(file.filename or "").suffix.lower()
    declared_media_type = (file.content_type or "").split(";", 1)[0].strip().lower()
    spec = UPLOAD_TYPE_SPECS.get(extension)
    if (
        spec is None
        or spec.kind not in allowed_kinds
        or declared_media_type not in spec.declared_media_types
        or not _matches_upload_signature(spec, header)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported or invalid upload content",
        )
    return spec


@dataclass(frozen=True)
class StoredUpload:
    path: Path
    url: str
    filename: str
    original_filename: str
    size: int
    spec: UploadTypeSpec
    storage_key: str
    sha256_digest: str


@dataclass(frozen=True)
class PreparedUpload:
    staging_path: Path
    destination_path: Path
    url: str
    filename: str
    original_filename: str
    size: int
    spec: UploadTypeSpec
    storage_key: str
    sha256_digest: str


def _write_upload_chunk(buffer, chunk: bytes) -> None:
    buffer.write(chunk)


def _open_private_upload(path: Path):
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(path, flags, 0o600)
    try:
        if os.name == "posix":
            os.fchmod(descriptor, 0o600)
            opened = os.fstat(descriptor)
            if opened.st_uid != os.geteuid() or stat.S_IMODE(opened.st_mode) != 0o600:
                raise OSError("Upload staging custody is invalid")
        return os.fdopen(descriptor, "wb")
    except Exception:
        os.close(descriptor)
        path.unlink(missing_ok=True)
        raise


def _flush_upload(buffer) -> None:
    buffer.flush()
    os.fsync(buffer.fileno())


def _fsync_upload_directory(path: Path) -> None:
    if os.name != "posix":
        return
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _remove_upload_candidate(prepared: PreparedUpload | None) -> None:
    if prepared is None:
        return
    prepared.staging_path.unlink(missing_ok=True)


def _finalize_prepared_upload(prepared: PreparedUpload) -> StoredUpload:
    objects_root = prepared.destination_path.parents[1]
    if not objects_root.is_dir():
        raise OSError("Upload object storage is unavailable")
    shard = prepared.destination_path.parent
    if shard.is_symlink() or getattr(shard, "is_junction", lambda: False)():
        raise OSError("Upload object storage is unavailable")
    shard_created = False
    try:
        shard.mkdir(mode=0o700)
    except FileExistsError:
        pass
    else:
        shard_created = True
    if shard.resolve(strict=True).parent != objects_root.resolve(strict=True):
        raise OSError("Upload object storage is unavailable")
    if os.name == "posix":
        shard_stat = shard.stat()
        if settings.app_env != "production" and shard_stat.st_uid == os.geteuid():
            shard.chmod(0o700)
            shard_stat = shard.stat()
        if shard_stat.st_uid != os.geteuid() or stat.S_IMODE(shard_stat.st_mode) != 0o700:
            raise OSError("Upload object storage is unavailable")
    if shard_created:
        _fsync_upload_directory(objects_root)
    if prepared.destination_path.exists():
        raise OSError("Upload object storage is unavailable")
    prepared.staging_path.replace(prepared.destination_path)
    if os.name == "posix":
        prepared.destination_path.chmod(0o600)
    os.utime(prepared.destination_path, None)
    _fsync_upload_directory(shard)
    return StoredUpload(
        path=prepared.destination_path,
        url=prepared.url,
        filename=prepared.filename,
        original_filename=prepared.original_filename,
        size=prepared.size,
        spec=prepared.spec,
        storage_key=prepared.storage_key,
        sha256_digest=prepared.sha256_digest,
    )


async def _save_validated_upload(
    file: UploadFile,
    *,
    allowed_kinds: set[str],
) -> PreparedUpload:
    destination_path = None
    staging_path = None
    try:
        await run_in_threadpool(
            _initialize_upload_layout,
            UPLOAD_DIR,
            production=settings.app_env == "production",
        )
        header = await file.read(UPLOAD_HEADER_BYTES)
        spec = _validated_upload_spec(file, allowed_kinds, header)
        max_bytes = {
            "image": MAX_IMAGE_UPLOAD_BYTES,
            "video": MAX_VIDEO_UPLOAD_BYTES,
            "pdf": MAX_PDF_UPLOAD_BYTES,
        }[spec.kind]
        object_id = secrets.token_hex(16)
        storage_key = f"objects/{object_id[:2]}/{object_id}{spec.extension}"
        filename = f"{object_id}{spec.extension}"
        destination_path = _upload_path(storage_key)
        incoming_dir = _upload_path(".incoming")
        await run_in_threadpool(incoming_dir.mkdir, mode=0o700, exist_ok=True)
        staging_path = _upload_path(".incoming", f"{object_id}.part")
        size = 0
        digest = hashlib.sha256()
        buffer = await run_in_threadpool(_open_private_upload, staging_path)
        try:
            chunk = header
            while chunk:
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        detail="Upload exceeds the allowed size",
                    )
                await run_in_threadpool(_write_upload_chunk, buffer, chunk)
                digest.update(chunk)
                chunk = await file.read(UPLOAD_CHUNK_SIZE)
        finally:
            await run_in_threadpool(_flush_upload, buffer)
            await run_in_threadpool(buffer.close)

        try:
            await run_in_threadpool(upload_scanner.scan, staging_path)
        except UploadScannerUnavailable as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Upload scanning unavailable",
            ) from exc
        except UploadRejected as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Upload rejected by security scanner",
            ) from exc

        return PreparedUpload(
            staging_path=staging_path,
            destination_path=destination_path,
            url=_upload_url(storage_key),
            filename=filename,
            original_filename=_sanitize_filename(file.filename),
            size=size,
            spec=spec,
            storage_key=storage_key,
            sha256_digest=digest.hexdigest(),
        )
    except Exception:
        if staging_path is not None:
            await run_in_threadpool(staging_path.unlink, missing_ok=True)
        raise
    finally:
        await file.close()


def _safe_download_filename(requested_name: str | None, actual_extension: str) -> str:
    requested = _sanitize_filename(requested_name, "download")
    safe_stem = Path(requested).stem[:100].strip("._-") or "download"
    return f"{safe_stem}{actual_extension}"


class _OpenedUploadFileResponse(FileResponse):
    """FileResponse semantics backed by the descriptor verified for this request."""

    def __init__(self, opened_object, path: Path, **kwargs):
        self._opened_object = opened_object
        super().__init__(path=path, stat_result=opened_object.stat_result, **kwargs)

    async def __call__(self, scope, receive, send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            self._opened_object.close()

    async def _seek(self, offset: int) -> None:
        await run_in_threadpool(
            os.lseek,
            self._opened_object.descriptor,
            offset,
            os.SEEK_SET,
        )

    async def _read(self, size: int) -> bytes:
        return await run_in_threadpool(
            os.read,
            self._opened_object.descriptor,
            size,
        )

    async def _handle_simple(self, send, send_header_only: bool, send_pathsend: bool) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": self.status_code,
                "headers": self.raw_headers,
            }
        )
        if send_header_only:
            await send({"type": "http.response.body", "body": b"", "more_body": False})
            return
        await self._seek(0)
        more_body = True
        while more_body:
            chunk = await self._read(self.chunk_size)
            more_body = len(chunk) == self.chunk_size
            await send(
                {
                    "type": "http.response.body",
                    "body": chunk,
                    "more_body": more_body,
                }
            )

    async def _handle_single_range(
        self,
        send,
        start: int,
        end: int,
        file_size: int,
        send_header_only: bool,
    ) -> None:
        headers = MutableHeaders(raw=list(self.raw_headers))
        headers["content-range"] = f"bytes {start}-{end - 1}/{file_size}"
        headers["content-length"] = str(end - start)
        await send(
            {
                "type": "http.response.start",
                "status": 206,
                "headers": headers.raw,
            }
        )
        if send_header_only:
            await send({"type": "http.response.body", "body": b"", "more_body": False})
            return
        await self._seek(start)
        more_body = True
        while more_body:
            chunk = await self._read(min(self.chunk_size, end - start))
            start += len(chunk)
            more_body = len(chunk) == self.chunk_size and start < end
            await send(
                {
                    "type": "http.response.body",
                    "body": chunk,
                    "more_body": more_body,
                }
            )

    async def _handle_multiple_ranges(
        self,
        send,
        ranges,
        file_size: int,
        send_header_only: bool,
    ) -> None:
        boundary = secrets.token_hex(13)
        content_length, header_generator = self.generate_multipart(
            ranges,
            boundary,
            file_size,
            self.headers["content-type"],
        )
        headers = MutableHeaders(raw=list(self.raw_headers))
        headers["content-type"] = f"multipart/byteranges; boundary={boundary}"
        headers["content-length"] = str(content_length)
        await send(
            {
                "type": "http.response.start",
                "status": 206,
                "headers": headers.raw,
            }
        )
        if send_header_only:
            await send({"type": "http.response.body", "body": b"", "more_body": False})
            return
        for start, end in ranges:
            await send(
                {
                    "type": "http.response.body",
                    "body": header_generator(start, end),
                    "more_body": True,
                }
            )
            await self._seek(start)
            while start < end:
                chunk = await self._read(min(self.chunk_size, end - start))
                start += len(chunk)
                await send(
                    {
                        "type": "http.response.body",
                        "body": chunk,
                        "more_body": True,
                    }
                )
            await send(
                {
                    "type": "http.response.body",
                    "body": b"\r\n",
                    "more_body": True,
                }
            )
        await send(
            {
                "type": "http.response.body",
                "body": f"--{boundary}--".encode("latin-1"),
                "more_body": False,
            }
        )


def _safe_upload_file_response(
    opened_object,
    file_path: Path,
    *,
    requested_filename: str | None = None,
    disposition: str = "inline",
) -> FileResponse:
    spec = UPLOAD_TYPE_SPECS.get(file_path.suffix.lower())
    if spec is None:
        opened_object.close()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    try:
        os.lseek(opened_object.descriptor, 0, os.SEEK_SET)
        header = os.read(opened_object.descriptor, UPLOAD_HEADER_BYTES)
        os.lseek(opened_object.descriptor, 0, os.SEEK_SET)
    except OSError as exc:
        opened_object.close()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found") from exc
    if not _matches_upload_signature(spec, header):
        opened_object.close()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

    response_filename = _safe_download_filename(
        requested_filename or file_path.name,
        spec.extension,
    )
    safe_disposition = (
        "inline"
        if disposition == "inline" and spec.kind in {"image", "video"}
        else "attachment"
    )
    return _OpenedUploadFileResponse(
        opened_object,
        path=file_path,
        media_type=spec.media_type,
        filename=response_filename,
        content_disposition_type=safe_disposition,
        headers={
            "Cache-Control": "private, no-store",
            "Content-Security-Policy": "sandbox; default-src 'none'",
            "Cross-Origin-Resource-Policy": "same-origin",
            "X-Content-Type-Options": "nosniff",
        },
    )

def _is_admin_role(role) -> bool:
    if role is None:
        return False
    if isinstance(role, models.UserRole):
        return role == models.UserRole.ADMIN
    if hasattr(role, "value"):
        return str(role.value).upper() == "ADMIN"
    return str(role).upper() == "ADMIN"


def _push_endpoint_host_allowed(hostname: str) -> bool:
    normalized_host = hostname.lower().rstrip(".")
    try:
        ip_address(normalized_host)
    except ValueError:
        pass
    else:
        return False

    for rule in PUSH_ALLOWED_ENDPOINT_HOSTS:
        normalized_rule = rule.lower().rstrip(".")
        if normalized_rule.startswith("."):
            base_domain = normalized_rule[1:]
            if normalized_host == base_domain or normalized_host.endswith(normalized_rule):
                return True
        elif normalized_host == normalized_rule:
            return True
    return False

class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Login canonicalizes the address before the case-insensitive identity lookup.
    # The bound matches the persisted account column.
    email: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=1, max_length=1_024)

    @field_validator("password")
    @classmethod
    def validate_password_size(cls, value: str) -> str:
        return schemas.validate_password_request_bytes(value)


class SessionMetadataResponse(BaseModel):
    user_id: int
    username: str
    first_name: str | None = None
    last_name: str | None = None
    role: str
    is_admin: bool


class RegistrationAcceptedResponse(BaseModel):
    message: str


class UserStatusResponse(BaseModel):
    disabled: bool


class PublicRuntimeConfigResponse(BaseModel):
    csrf_cookie_name: str
    google_client_id: str
    microsoft_client_id: str
    microsoft_tenant_id: str
    local_password_registration_enabled: bool


class OAuthLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idToken: str = Field(min_length=1, max_length=16_384)


class OAuthSignupRequest(OAuthLoginRequest):
    role: str | None = Field(default=None, max_length=16)
    teacherInvitationToken: str | None = Field(default=None, max_length=512)


class UserSettingsUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    darkMode: bool | None = None
    reducedMotion: bool | None = None
    emailNotifications: bool | None = None
    assignmentReminders: bool | None = None
    autoPlayVideos: bool | None = None
    compactFeed: bool | None = None
    rememberDrafts: bool | None = None
    showProfileToClassmates: bool | None = None
    editorFontSize: Literal["small", "medium", "large"] | None = None

class PushSubscriptionKeysRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    p256dh: str = Field(min_length=1, max_length=255)
    auth: str = Field(min_length=1, max_length=255)

class PushSubscriptionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    endpoint: str = Field(min_length=12, max_length=1_024)
    keys: PushSubscriptionKeysRequest

    @field_validator("endpoint")
    @classmethod
    def validate_https_endpoint(cls, value: str) -> str:
        normalized = value.strip()
        parsed = urlsplit(normalized)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.port not in {None, 443}
            or not _push_endpoint_host_allowed(parsed.hostname)
        ):
            raise ValueError("push endpoint is not an approved HTTPS push service")
        return normalized

class PushSubscriptionEnvelopeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subscription: PushSubscriptionRequest

DEFAULT_USER_SETTINGS = {
    "darkMode": False,
    "reducedMotion": False,
    "emailNotifications": True,
    "assignmentReminders": True,
    "autoPlayVideos": False,
    "compactFeed": False,
    "rememberDrafts": True,
    "showProfileToClassmates": True,
    "editorFontSize": "medium",
}

DEFAULT_SESSION_COOKIE_NAME = "litblog-session"
DEFAULT_CSRF_COOKIE_NAME = "litblog-csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"
UNSAFE_HTTP_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)

def _normalize_editor_font_size(value: str | None) -> str:
    normalized = str(value or "").lower()
    return normalized if normalized in {"small", "medium", "large"} else "medium"

def _is_student_role(role) -> bool:
    if role is None:
        return False
    if isinstance(role, models.UserRole):
        return role == models.UserRole.STUDENT
    if hasattr(role, "value"):
        return str(role.value).upper() == "STUDENT"
    return str(role).upper() == "STUDENT"

def _normalize_user_settings_payload(raw_settings: dict, role) -> dict:
    normalized = {**DEFAULT_USER_SETTINGS, **(raw_settings or {})}
    normalized["darkMode"] = bool(normalized.get("darkMode"))
    normalized["reducedMotion"] = bool(normalized.get("reducedMotion"))
    normalized["emailNotifications"] = bool(normalized.get("emailNotifications"))
    normalized["assignmentReminders"] = bool(normalized.get("assignmentReminders"))
    normalized["autoPlayVideos"] = bool(normalized.get("autoPlayVideos"))
    normalized["compactFeed"] = bool(normalized.get("compactFeed"))
    normalized["rememberDrafts"] = bool(normalized.get("rememberDrafts"))
    normalized["showProfileToClassmates"] = bool(normalized.get("showProfileToClassmates"))
    normalized["editorFontSize"] = _normalize_editor_font_size(normalized.get("editorFontSize"))

    if not _is_student_role(role):
        normalized["showProfileToClassmates"] = False

    return normalized

def _serialize_user_settings(settings: models.UserSettings | None, role) -> dict:
    if settings is None:
        return _normalize_user_settings_payload({}, role)

    payload = {
        "darkMode": settings.dark_mode,
        "reducedMotion": settings.reduced_motion,
        "emailNotifications": settings.email_notifications,
        "assignmentReminders": settings.assignment_reminders,
        "autoPlayVideos": settings.auto_play_videos,
        "compactFeed": settings.compact_feed,
        "rememberDrafts": settings.remember_drafts,
        "showProfileToClassmates": settings.show_profile_to_classmates,
        "editorFontSize": settings.editor_font_size,
    }
    return _normalize_user_settings_payload(payload, role)

def _apply_user_settings_to_model(settings_model: models.UserSettings, payload: dict, role) -> None:
    normalized = _normalize_user_settings_payload(payload, role)
    settings_model.dark_mode = normalized["darkMode"]
    settings_model.reduced_motion = normalized["reducedMotion"]
    settings_model.email_notifications = normalized["emailNotifications"]
    settings_model.assignment_reminders = normalized["assignmentReminders"]
    settings_model.auto_play_videos = normalized["autoPlayVideos"]
    settings_model.compact_feed = normalized["compactFeed"]
    settings_model.remember_drafts = normalized["rememberDrafts"]
    settings_model.show_profile_to_classmates = normalized["showProfileToClassmates"]
    settings_model.editor_font_size = normalized["editorFontSize"]

def _get_or_create_user_settings(db: Session, user: models.User) -> models.UserSettings:
    settings = db.query(models.UserSettings).filter(models.UserSettings.user_id == user.id).first()
    if settings:
        return settings

    settings = models.UserSettings(user_id=user.id)
    _apply_user_settings_to_model(settings, DEFAULT_USER_SETTINGS, user.role)
    db.add(settings)
    db.commit()
    db.refresh(settings)
    return settings

def _assignment_due_soon(due_date: datetime, now_utc: datetime) -> bool:
    if not due_date:
        return False

    normalized_due = due_date
    if normalized_due.tzinfo is not None:
        normalized_due = normalized_due.astimezone(tz=None).replace(tzinfo=None)

    window_end = now_utc + timedelta(hours=24)
    return now_utc < normalized_due <= window_end

def _make_push_payload(assignment: models.Assignment) -> dict:
    return {
        "title": "Assignment Reminder",
        "body": f"{assignment.title} is due within 24 hours.",
        "url": f"/class-feed/{assignment.class_id}",
        "tag": f"assignment-reminder-{assignment.id}",
    }

def _send_web_push(subscription: models.PushSubscription, payload: dict) -> bool:
    if not WEB_PUSH_ENABLED:
        return False

    subscription_info = {
        "endpoint": subscription.endpoint,
        "keys": {
            "p256dh": subscription.p256dh,
            "auth": subscription.auth,
        },
    }

    try:
        webpush(
            subscription_info=subscription_info,
            data=json.dumps(payload),
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={"sub": VAPID_SUBJECT},
            timeout=PUSH_DELIVERY_TIMEOUT_SECONDS,
        )
        return True
    except WebPushException as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        if status_code in {404, 410}:
            return False
        return False
    except Exception:
        return False

REMINDER_DISPATCH_LOCK_ID = 4_979_842_103


def _try_acquire_reminder_dispatch_lock(db: Session) -> bool:
    bind = db.get_bind()
    if bind.dialect.name == "postgresql":
        return bool(
            db.execute(
                text("SELECT pg_try_advisory_xact_lock(:lock_id)"),
                {"lock_id": REMINDER_DISPATCH_LOCK_ID},
            ).scalar_one()
        )
    if settings.app_env == "test":
        return True
    raise RuntimeError("Reminder dispatch requires PostgreSQL outside tests")


def _dispatch_assignment_push_reminders_once() -> bool:
    if not WEB_PUSH_ENABLED:
        return True

    db = SessionLocal()
    try:
        if not _try_acquire_reminder_dispatch_lock(db):
            return True

        now_utc = _utc_now_naive()
        students = (
            db.query(models.User)
            .join(models.UserSettings, models.UserSettings.user_id == models.User.id)
            .filter(
                models.User.role == models.UserRole.STUDENT,
                models.UserSettings.email_notifications.is_(True),
                models.UserSettings.assignment_reminders.is_(True),
            )
            .all()
        )

        for student in students:
            subscriptions = (
                db.query(models.PushSubscription)
                .filter(models.PushSubscription.user_id == student.id)
                .all()
            )
            if not subscriptions:
                continue

            class_ids = [enrollment.class_id for enrollment in (student.enrolled_classes or [])]
            if not class_ids:
                continue

            due_soon_assignments = (
                db.query(models.Assignment)
                .filter(
                    models.Assignment.class_id.in_(class_ids),
                    models.Assignment.visibility == "class",
                )
                .all()
            )

            for assignment in due_soon_assignments:
                if not _assignment_due_soon(assignment.due_date, now_utc):
                    continue

                already_sent = (
                    db.query(models.AssignmentReminderNotification)
                    .filter(
                        models.AssignmentReminderNotification.user_id == student.id,
                        models.AssignmentReminderNotification.assignment_id == assignment.id,
                    )
                    .first()
                )
                if already_sent:
                    continue

                has_submitted = (
                    db.query(models.AssignmentSubmission.id)
                    .filter(
                        models.AssignmentSubmission.assignment_id == assignment.id,
                        models.AssignmentSubmission.student_id == student.id,
                    )
                    .first()
                    is not None
                )
                if has_submitted:
                    continue

                payload = _make_push_payload(assignment)
                delivered = False
                stale_subscription_ids: list[int] = []

                for subscription in subscriptions:
                    success = _send_web_push(subscription, payload)
                    if success:
                        delivered = True
                    else:
                        stale_subscription_ids.append(subscription.id)

                if stale_subscription_ids:
                    db.query(models.PushSubscription).filter(
                        models.PushSubscription.id.in_(stale_subscription_ids)
                    ).delete(synchronize_session=False)

                if delivered:
                    db.add(
                        models.AssignmentReminderNotification(
                            user_id=student.id,
                            assignment_id=assignment.id,
                        )
                    )

        db.commit()
        return True
    except Exception:
        db.rollback()
        security_logger.error("push_reminder_dispatch_failed")
        return False
    finally:
        db.close()

# ---------- Authentication Endpoints ----------


def _session_cookie_name() -> str:
    return settings.session_cookie_name or DEFAULT_SESSION_COOKIE_NAME


def _csrf_cookie_name() -> str:
    return settings.csrf_cookie_name or DEFAULT_CSRF_COOKIE_NAME


def _session_metadata(user: models.User) -> dict:
    return {
        "user_id": user.id,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "role": user.role.value,
        "is_admin": _is_admin_role(user.role),
    }


def _set_browser_session(
    response: Response,
    user: models.User,
    db: Session,
    *,
    expected_password_hash: str | None = None,
    authentication_error_detail: str = "External authentication failed",
) -> None:
    try:
        issued = issue_browser_session(
            db,
            user_id=user.id,
            settings=settings,
            expected_password_hash=expected_password_hash,
        )
    except SessionIssuanceDenied as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=authentication_error_detail,
        ) from exc
    db.commit()
    max_age = settings.access_token_expire_minutes * 60
    cookie_options = {
        "max_age": max_age,
        "path": "/",
        "secure": settings.session_cookie_secure,
        "samesite": "strict",
    }
    response.set_cookie(
        _session_cookie_name(),
        issued.token,
        httponly=True,
        **cookie_options,
    )
    response.set_cookie(
        _csrf_cookie_name(),
        secrets.token_urlsafe(32),
        httponly=False,
        **cookie_options,
    )


def _clear_browser_session(response: Response) -> None:
    common_options = {
        "path": "/",
        "secure": settings.session_cookie_secure,
        "samesite": "strict",
    }
    response.delete_cookie(_session_cookie_name(), httponly=True, **common_options)
    response.delete_cookie(_csrf_cookie_name(), httponly=False, **common_options)


def _federated_identity_key(provider: str, claims: dict) -> tuple[str, str, str]:
    issuer = GOOGLE_IDENTITY_ISSUER if provider == "google" else claims["iss"]
    return provider, issuer, claims["sub"]


def _find_federated_user(
    db: Session,
    *,
    provider: str,
    issuer: str,
    subject: str,
) -> models.User | None:
    identity = db.query(models.FederatedIdentity).filter(
        models.FederatedIdentity.provider == provider,
        models.FederatedIdentity.issuer == issuer,
        models.FederatedIdentity.subject == subject,
    ).first()
    return identity.user if identity is not None else None


def _create_federated_user(
    db: Session,
    *,
    provider: str,
    issuer: str,
    subject: str,
    email: str,
    first_name: str,
    last_name: str,
    role: models.UserRole,
) -> models.User:
    normalized_email = normalize_email(email)
    if (
        db.query(models.User)
        .filter(models.User.email == normalized_email)
        .first()
        is not None
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="External authentication failed",
        )

    user = models.User(
        username=f"oauth-{secrets.token_hex(12)}",
        email=normalized_email,
        password=hash_password(secrets.token_urlsafe(32)),
        first_name=first_name[:50],
        last_name=last_name[:50],
        role=role,
        is_admin=False,
    )
    identity = models.FederatedIdentity(
        provider=provider,
        issuer=issuer,
        subject=subject,
        user=user,
    )
    db.add_all((user, identity))
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        winner = _find_federated_user(
            db,
            provider=provider,
            issuer=issuer,
            subject=subject,
        )
        if winner is not None:
            return winner
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="External authentication failed",
        ) from exc
    return user


def _require_active_federated_user(user: models.User) -> models.User:
    if user.disabled_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="External authentication failed",
        )
    return user


REGISTRATION_ACCEPTED_RESPONSE = {
    "message": "If registration can be completed, sign in with the submitted credentials."
}


def _registration_email_domain_allowed(normalized_email: str) -> bool:
    allowed_domains = settings.allowed_email_domains
    if not allowed_domains:
        return True
    return normalized_email.rsplit("@", 1)[-1] in allowed_domains


@app.post(
    "/api/auth/register",
    response_model=RegistrationAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def register(
    user_data: schemas.UserCreate,
    db: Session = Depends(get_db),
):
    """Accept an account request without disclosing account or invite state."""
    if not settings.local_password_registration_enabled:
        return REGISTRATION_ACCEPTED_RESPONSE

    hashed_password = await run_in_threadpool(hash_password, user_data.password)
    try:
        normalized_email = normalize_email(str(user_data.email))
    except (TypeError, ValueError):
        return REGISTRATION_ACCEPTED_RESPONSE
    role = models.UserRole.__members__.get(user_data.role)
    existing_user = (
        db.query(models.User.id)
        .filter(
            or_(
                models.User.email == normalized_email,
                models.User.username == user_data.username,
            )
        )
        .first()
    )
    eligible = (
        existing_user is None
        and _registration_email_domain_allowed(normalized_email)
        and role in {
            models.UserRole.STUDENT,
            models.UserRole.TEACHER,
        }
    )

    if eligible and role == models.UserRole.TEACHER:
        eligible = consume_teacher_invitation(
            db,
            token=user_data.teacher_invitation_token or "",
            email=normalized_email,
            settings=settings,
        )

    if not eligible:
        db.rollback()
        return REGISTRATION_ACCEPTED_RESPONSE

    db.add(
        models.User(
            username=user_data.username,
            email=normalized_email,
            password=hashed_password,
            first_name=user_data.first_name,
            last_name=user_data.last_name,
            role=role,
            is_admin=False,
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()

    return REGISTRATION_ACCEPTED_RESPONSE

def create_access_token(data: dict):
    return issue_access_token(data.get("sub"), settings=settings)


def _persist_password_upgrade_if_current(
    db: Session,
    *,
    user_id: int,
    verified_hash: str,
    upgraded_hash: str,
) -> bool:
    try:
        result = db.execute(
            update(models.User)
            .where(
                models.User.id == user_id,
                models.User.password == verified_hash,
            )
            .values(password=upgraded_hash)
        )
        if result.rowcount != 1:
            db.rollback()
            return False
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise

async def get_current_user(
    request: Request,
    bearer_token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    cookie_token = request.cookies.get(_session_cookie_name())
    authorization_header = request.headers.get("Authorization")
    if cookie_token and authorization_header:
        raise credentials_exception
    if authorization_header and not bearer_token:
        raise credentials_exception

    token = bearer_token or cookie_token
    if not token:
        raise credentials_exception
    try:
        payload = decode_access_token(token, settings=settings)
        user_id = int(payload["sub"])
    except (InvalidTokenError, TypeError, ValueError) as exc:
        raise credentials_exception from exc

    browser_session = find_active_browser_session(
        db,
        user_id=user_id,
        jti=payload["jti"],
    )
    if browser_session is None:
        raise credentials_exception

    user = (
        db.query(models.User)
        .filter(
            models.User.id == user_id,
            models.User.disabled_at.is_(None),
        )
        .first()
    )
    if user is None:
        raise credentials_exception
    request.state.browser_session_id = browser_session.id

    if cookie_token and request.method.upper() in UNSAFE_HTTP_METHODS:
        if not csrf_token_matches(
            request.headers.get(CSRF_HEADER_NAME),
            request.cookies.get(_csrf_cookie_name()),
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="CSRF validation failed",
            )
    return user

@app.get("/api/auth/session", response_model=SessionMetadataResponse)
async def get_browser_session(current_user: models.User = Depends(get_current_user)):
    return _session_metadata(current_user)


@app.post("/api/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    del current_user
    revoke_session(
        db,
        session_id=request.state.browser_session_id,
    )
    db.commit()
    _clear_browser_session(response)


@app.post("/api/auth/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    payload: schemas.ChangePasswordRequest,
    response: Response,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    verified_hash = current_user.password
    password_valid = await run_in_threadpool(
        verify_password,
        payload.current_password,
        verified_hash,
    )
    if not password_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )
    new_password_hash = await run_in_threadpool(hash_password, payload.new_password)
    result = db.execute(
        update(models.User)
        .where(
            models.User.id == current_user.id,
            models.User.password == verified_hash,
            models.User.disabled_at.is_(None),
        )
        .values(password=new_password_hash)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Password changed concurrently; sign in again",
        )
    revoke_all_sessions(db, user_id=current_user.id)
    invalidate_password_reset_requests(db, user_id=current_user.id)
    db.commit()
    _clear_browser_session(response)


@app.put(
    "/api/users/{user_id}/status",
    response_model=UserStatusResponse,
)
async def update_user_status(
    user_id: int,
    payload: schemas.UserStatusUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _require_admin(current_user)
    if payload.disabled and user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Administrators cannot disable their current account",
        )
    target_user = (
        db.query(models.User)
        .filter(models.User.id == user_id)
        .with_for_update()
        .first()
    )
    if target_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    try:
        if payload.disabled:
            target_user.disabled_at = _utc_now_naive()
            revoke_all_sessions(db, user_id=target_user.id)
            invalidate_password_reset_requests(db, user_id=target_user.id)
            audit_action = "ACCOUNT_DISABLED"
        else:
            target_user.disabled_at = None
            audit_action = "ACCOUNT_ENABLED"
        record_operator_audit_event(
            db,
            actor_identifier=f"admin-user:{current_user.id}",
            action=audit_action,
            outcome="SUCCEEDED",
            resource_email=target_user.email,
            settings=settings,
        )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Account status could not be updated",
        ) from None
    return {"disabled": payload.disabled}


@app.post("/api/auth/login", response_model=SessionMetadataResponse)
async def login(
    login_data: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    try:
        normalized_email = normalize_email(str(login_data.email))
    except (TypeError, ValueError):
        normalized_email = ""
    user = (
        db.query(models.User)
        .filter(
            models.User.email == normalized_email,
            models.User.disabled_at.is_(None),
        )
        .first()
    )
    
    verified_password_hash = user.password if user is not None else _DUMMY_PASSWORD_HASH
    password_valid, upgraded_password_hash = await run_in_threadpool(
        verify_and_update_password,
        login_data.password,
        verified_password_hash,
    )
    if user is None or not password_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    if upgraded_password_hash is not None:
        if not _persist_password_upgrade_if_current(
            db,
            user_id=user.id,
            verified_hash=verified_password_hash,
            upgraded_hash=upgraded_password_hash,
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )
        verified_password_hash = upgraded_password_hash
    
    _set_browser_session(
        response,
        user,
        db,
        expected_password_hash=verified_password_hash,
        authentication_error_detail="Invalid email or password",
    )
    return _session_metadata(user)

@app.post("/api/auth/google-signup", response_model=SessionMetadataResponse)
def google_signup(
    token_data: OAuthSignupRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    """Handle Google Sign Up"""
    try:
        credential = token_data.idToken
        idinfo = verify_google_id_token(
            credential,
            settings=settings,
            verifier=id_token.verify_oauth2_token,
        )
        provider, issuer, subject = _federated_identity_key("google", idinfo)
        user = _find_federated_user(
            db,
            provider=provider,
            issuer=issuer,
            subject=subject,
        )
        if user is not None:
            _require_active_federated_user(user)
            _set_browser_session(response, user, db)
            return _session_metadata(user)

        selected_role = (token_data.role or "STUDENT").upper()

        if selected_role not in {"STUDENT", "TEACHER"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid role",
            )
        if selected_role == "TEACHER" and not consume_teacher_invitation(
            db,
            token=token_data.teacherInvitationToken or "",
            email=idinfo["email"],
            settings=settings,
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="External authentication failed",
            )

        user = _create_federated_user(
            db,
            provider=provider,
            issuer=issuer,
            subject=subject,
            email=idinfo["email"],
            first_name=str(idinfo.get("given_name") or ""),
            last_name=str(idinfo.get("family_name") or ""),
            role=models.UserRole[selected_role],
        )

        _set_browser_session(response, user, db)
        return _session_metadata(user)

    except HTTPException:
        db.rollback()
        raise
    except ValueError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="External authentication failed",
        ) from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="External authentication failed",
        ) from exc

@app.post("/api/auth/google-login", response_model=SessionMetadataResponse)
def google_login(
    token_data: OAuthLoginRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    """Process Google login - now with existence check"""
    try:
        idinfo = verify_google_id_token(
            token_data.idToken,
            settings=settings,
            verifier=id_token.verify_oauth2_token,
        )
        provider, issuer, subject = _federated_identity_key("google", idinfo)
        user = _find_federated_user(
            db,
            provider=provider,
            issuer=issuer,
            subject=subject,
        )
        
        # If user doesn't exist, require signup
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found. Please sign up and choose a role first."
            )

        _require_active_federated_user(user)
        _set_browser_session(response, user, db)
        return _session_metadata(user)
        
    except HTTPException:
        db.rollback()
        raise
    except ValueError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="External authentication failed",
        ) from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="External authentication failed",
        ) from exc

@app.post("/api/auth/microsoft-login", response_model=SessionMetadataResponse)
def microsoft_login(
    microsoft_data: OAuthLoginRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    """Process Microsoft login"""
    try:
        user_data = verify_microsoft_id_token(
            microsoft_data.idToken,
            settings=settings,
        )
        provider, issuer, subject = _federated_identity_key("microsoft", user_data)
        user = _find_federated_user(
            db,
            provider=provider,
            issuer=issuer,
            subject=subject,
        )
        
        # If user doesn't exist, require signup
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found. Please sign up and choose a role first."
            )

        _require_active_federated_user(user)
        _set_browser_session(response, user, db)
        return _session_metadata(user)
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="External authentication failed",
        ) from exc

@app.post("/api/auth/microsoft-signup", response_model=SessionMetadataResponse)
def microsoft_signup(
    microsoft_data: OAuthSignupRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    """Process Microsoft signup"""
    try:
        user_data = verify_microsoft_id_token(
            microsoft_data.idToken,
            settings=settings,
        )
        user_email = user_data["email"]
        first_name = str(user_data.get("given_name") or "")[:50]
        last_name = str(user_data.get("family_name") or "")[:50]
        provider, issuer, subject = _federated_identity_key("microsoft", user_data)
        existing_user = _find_federated_user(
            db,
            provider=provider,
            issuer=issuer,
            subject=subject,
        )
        if existing_user is not None:
            _require_active_federated_user(existing_user)
            _set_browser_session(response, existing_user, db)
            return _session_metadata(existing_user)

        role = (microsoft_data.role or "STUDENT").upper()

        if role not in {"STUDENT", "TEACHER"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid role",
            )
        if role == "TEACHER" and not consume_teacher_invitation(
            db,
            token=microsoft_data.teacherInvitationToken or "",
            email=user_email,
            settings=settings,
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="External authentication failed",
            )

        user = _create_federated_user(
            db,
            provider=provider,
            issuer=issuer,
            subject=subject,
            email=user_email,
            first_name=first_name,
            last_name=last_name,
            role=models.UserRole[role],
        )

        _set_browser_session(response, user, db)
        return _session_metadata(user)
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="External authentication failed",
        ) from exc

@app.get("/api/user/id/{user_id}")
async def get_user_info(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    _ensure_profile_access(db, current_user, user)
    
    return {
        "role": user.role.value,
        "id": user.id,
        "username": user.username,
        "first_name": user.first_name
    }

# ---------- Home Endpoint ----------
@app.get("/api/")
def home():
    return {"message": "Welcome to LitBlogs Backend"}

@app.get("/api/health/live", include_in_schema=False)
def liveness():
    return {"status": "ok"}


@app.get(
    "/api/runtime-config",
    response_model=PublicRuntimeConfigResponse,
    include_in_schema=False,
)
def public_runtime_config(response: Response):
    response.headers["Cache-Control"] = "no-store"
    return PublicRuntimeConfigResponse(
        csrf_cookie_name=settings.csrf_cookie_name or "",
        google_client_id=settings.google_client_id or "",
        microsoft_client_id=settings.microsoft_client_id or "",
        microsoft_tenant_id=settings.microsoft_tenant_id or "",
        local_password_registration_enabled=(
            settings.local_password_registration_enabled
            and settings.app_env != "production"
        ),
    )


@app.get("/api/health/ready", include_in_schema=False)
def readiness(request: Request):
    try:
        check_database_readiness()
    except Exception as exc:
        reason = (
            "database_unreachable"
            if isinstance(exc, (ConnectionError, OSError, TimeoutError, SQLAlchemyError))
            else "migration_mismatch"
        )
        readiness_logger.error(
            json.dumps(
                {
                    "event": "readiness_failed",
                    "reason": reason,
                    "request_id": getattr(request.state, "request_id", "unavailable"),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service not ready",
        ) from None
    return {"status": "ready"}

@app.get("/api/classes/{class_id}/details")
async def get_class_details(
    class_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Get detailed information about a class"""
    db_class = _ensure_class_access(db, current_user, class_id)
    
    # Get enrollment count
    enrollment_count = db.query(models.ClassEnrollment).filter(
        models.ClassEnrollment.class_id == class_id
    ).count()
    
    # Get post count
    post_count = db.query(models.Blog).filter(
        models.Blog.class_id == class_id
    ).count()
    
    result = {
        "id": db_class.id,
        "name": db_class.name,
        "description": db_class.description,
        "created_at": db_class.created_at,
        "teacher_id": db_class.teacher_id,
        "enrollment_count": enrollment_count,
        "post_count": post_count,
        "status": db_class.status
    }
    if _is_admin_role(current_user.role) or _teacher_owns_class(db, current_user, db_class):
        result["access_code"] = db_class.access_code
    return result


# Add these new models to handle rich content
class PostContent(BaseModel):
    text: str
    code_snippets: List[dict] = []
    media: List[dict] = []
    polls: List[dict] = []
    expandable_lists: List[dict] = []

RICH_TEXT_ALLOWED_TAGS = {
    "a", "b", "blockquote", "br", "button", "code", "del", "div", "em",
    "figure", "font", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "i",
    "img", "li", "mark", "ol", "p", "pre", "s", "source", "span", "strike",
    "strong", "table", "tbody", "td", "th", "thead", "tr", "u", "ul", "video",
}
RICH_TEXT_GLOBAL_ATTRIBUTES = {"class", "style"}
RICH_TEXT_TAG_ATTRIBUTES = {
    "a": {"href", "rel", "target", "title"},
    "button": {"class", "data-file-url", "data-video-url", "type"},
    "div": {
        "align", "contenteditable", "data-file-name", "data-file-size",
        "data-file-type", "data-file-url", "data-video-type", "data-video-url",
    },
    "figure": {"contenteditable"},
    "font": {"color", "face", "size"},
    "img": {"alt", "height", "src", "title", "width"},
    "source": {"src", "type"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan", "scope"},
    "video": {"controls", "height", "preload", "src", "width"},
}
RICH_TEXT_ALLOWED_CLASSES = {
    "aligncenter", "alignleft", "alignright", "custom-font", "d-block",
    "editor-only", "editor-only-control", "file-actions", "file-attachment",
    "file-icon", "file-info", "file-name", "file-size", "float-left", "float-right",
    "mceNonEditable", "mx-auto", "post-image", "preserved-heading", "remove-btn",
    "video-container", "video-data", "video-delete-btn", "video-delete-overlay",
    "video-wrapper",
}
RICH_TEXT_ALLOWED_STYLES = {
    "background-color", "border-radius", "color", "display", "float", "font-family",
    "font-size", "font-style", "font-weight", "height", "margin", "margin-bottom",
    "margin-left", "margin-right", "margin-top", "max-height", "max-width", "overflow-wrap",
    "text-align", "text-decoration", "width", "word-break",
}
RICH_TEXT_CSS_KEYWORDS = {
    "display": {"block", "inline", "inline-block", "list-item", "table", "table-cell", "table-row"},
    "float": {"left", "none", "right"},
    "font-style": {"italic", "normal", "oblique"},
    "font-weight": {
        "100", "200", "300", "400", "500", "600", "700", "800", "900",
        "bold", "bolder", "lighter", "normal",
    },
    "overflow-wrap": {"anywhere", "break-word", "normal"},
    "text-align": {"center", "end", "justify", "left", "right", "start"},
    "text-decoration": {"line-through", "none", "overline", "underline"},
    "word-break": {"break-all", "break-word", "keep-all", "normal"},
}


def _is_bounded_css_length(value: str, limits: dict[str, tuple[float, float]], keywords: set[str] | None = None) -> bool:
    normalized_value = value.strip().lower()
    if keywords and normalized_value in keywords:
        return True

    unit = ""
    for candidate_unit in ("rem", "em", "px", "%"):
        if normalized_value.endswith(candidate_unit):
            unit = candidate_unit
            normalized_value = normalized_value[:-len(candidate_unit)]
            break
    try:
        amount = float(normalized_value)
    except ValueError:
        return False
    if not unit:
        return amount == 0
    minimum, maximum = limits.get(unit, (1, 0))
    return minimum <= amount <= maximum


def _is_bounded_rich_text_css_value(property_name: str, value: str) -> bool:
    if not value or len(value) > 128 or "\\" in value:
        return False
    lowered_value = value.lower()
    if any(character.isspace() and ord(character) < 0x20 for character in value):
        return False
    if any(fragment in lowered_value for fragment in ("expression(", "url(", "@import")):
        return False
    if property_name in {"background-color", "color"}:
        return len(value) <= 64
    if property_name == "font-family":
        return True
    if property_name in RICH_TEXT_CSS_KEYWORDS:
        return lowered_value in RICH_TEXT_CSS_KEYWORDS[property_name]
    if property_name == "font-size":
        return _is_bounded_css_length(
            value,
            {"px": (8, 96), "%": (50, 400), "em": (0.5, 6), "rem": (0.5, 6)},
            {"large", "larger", "medium", "small", "smaller", "x-large", "x-small", "xx-large", "xx-small"},
        )
    if property_name in {"height", "max-height", "max-width", "width"}:
        return _is_bounded_css_length(
            value,
            {"px": (0, 4096), "%": (0, 100), "em": (0, 256), "rem": (0, 256)},
            {"auto", "none"},
        )
    if property_name == "border-radius":
        return all(
            _is_bounded_css_length(
                token,
                {"px": (0, 512), "%": (0, 100), "em": (0, 64), "rem": (0, 64)},
            )
            for token in value.split()
        )
    if property_name == "margin" or property_name.startswith("margin-"):
        tokens = value.split()
        return len(tokens) <= 4 and all(
            _is_bounded_css_length(
                token,
                {"px": (-512, 512), "%": (-100, 100), "em": (-64, 64), "rem": (-64, 64)},
                {"auto"},
            )
            for token in tokens
        )
    return False


def _is_bounded_dimension_attribute(value: str) -> bool:
    normalized_value = value.strip().lower()
    if not normalized_value or len(normalized_value) > 32 or normalized_value.startswith("-"):
        return False
    if re.fullmatch(r"\d+(?:\.\d+)?", normalized_value):
        normalized_value = f"{normalized_value}px"
    return _is_bounded_css_length(
        normalized_value,
        {"px": (0, 4096), "%": (0, 100), "em": (0, 256), "rem": (0, 256)},
        {"auto"},
    )


class BoundedRichTextCSSSanitizer(CSSSanitizer):
    def sanitize_css(self, style: str) -> str:
        declarations = []
        for token in tinycss2.parse_declaration_list(style):
            if token.type != "declaration" or token.lower_name not in self.allowed_css_properties:
                continue
            value = tinycss2.serialize(token.value).strip()
            if not _is_bounded_rich_text_css_value(token.lower_name, value):
                continue
            important = " !important" if token.important else ""
            declarations.append(f"{token.lower_name}: {value}{important}")
        return "; ".join(declarations) + (";" if declarations else "")


def _is_safe_rich_text_url(value: str, *, media_kind: str) -> bool:
    if not value or value != value.strip() or len(value) > 2048 or "\\" in value:
        return False
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        return False

    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    if parsed.scheme:
        return media_kind == "link" and parsed.scheme == "https" and bool(parsed.netloc)
    if parsed.netloc or value.startswith("//"):
        return False

    if media_kind == "link":
        return True

    try:
        canonical_object_key(value)
    except ValueError:
        return False
    return True


def _rich_text_attribute_allowed(tag: str, name: str, value: str) -> bool:
    if name.startswith("on"):
        return False
    allowed_attributes = RICH_TEXT_GLOBAL_ATTRIBUTES | RICH_TEXT_TAG_ATTRIBUTES.get(tag, set())
    if name not in allowed_attributes:
        return False
    if name == "class":
        class_names = value.split()
        return bool(class_names) and all(
            class_name in RICH_TEXT_ALLOWED_CLASSES or class_name.startswith("language-")
            for class_name in class_names
        )
    if name == "contenteditable":
        return value.lower() == "false"
    if name == "target":
        return value in {"_blank", "_self"}
    if name == "href":
        return _is_safe_rich_text_url(value, media_kind="link")
    if name == "src":
        media_kind = "image" if tag == "img" else "video"
        return _is_safe_rich_text_url(value, media_kind=media_kind)
    if name in {"data-file-url", "data-video-url"}:
        return _is_safe_rich_text_url(value, media_kind="attachment")
    if name in {"height", "width"}:
        return _is_bounded_dimension_attribute(value)
    return True


def sanitize_html(content: str) -> str:
    raw_content = content or ""
    if len(raw_content) > MAX_RICH_TEXT_INPUT_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Rich text exceeds the allowed size",
        )
    css_sanitizer = BoundedRichTextCSSSanitizer(
        allowed_css_properties=RICH_TEXT_ALLOWED_STYLES,
    )
    cleaner = bleach.Cleaner(
        tags=RICH_TEXT_ALLOWED_TAGS,
        attributes=_rich_text_attribute_allowed,
        protocols={"https"},
        css_sanitizer=css_sanitizer,
        strip=True,
        strip_comments=True,
    )
    return cleaner.clean(raw_content)

def _build_post_content(post: schemas.BlogCreate) -> str:
    content = sanitize_html(post.content)

    if post.code_snippets:
        for snippet in post.code_snippets:
            language = escape(str(snippet.language), quote=True)
            code = escape(str(snippet.code), quote=True)
            content += f"\n[CODE:{language}]{code}\n"

    if post.media:
        for media in post.media:
            media_url = escape(str(media.url), quote=True)
            media_alt = escape(str(media.alt or "Uploaded image"), quote=True)
            if media.type in {'gif', 'image'}:
                content += f'\n<img src="{media_url}" alt="{media_alt}">\n'
            elif media.type == 'video':
                content += f'\n<video controls src="{media_url}"></video>\n'

    if post.polls:
        for poll in post.polls:
            options = ",".join(
                escape(str(option), quote=True)
                for option in poll.options
            )
            content += f"\n[POLL:{options}]\n"

    if post.files:
        for file in post.files:
            file_name = escape(str(file.name), quote=True)
            file_url = escape(str(file.url), quote=True)
            content += (
                f'\n<a class="file-attachment" href="{file_url}">'
                f'{file_name}</a>\n'
            )

    return sanitize_html(content)


def _post_analysis_payload(
    db: Session,
    current_user: models.User,
    db_class: models.Class,
    post: models.Blog,
) -> dict:
    if not _can_view_post_analysis(db, current_user, db_class, post):
        return {}
    return {
        "ai_percentage": post.ai_percentage,
        "ai_highlighted_html": post.ai_highlighted_html,
        "ai_sentence_analysis": post.ai_sentence_analysis,
    }

@app.post("/api/classes/{class_id}/posts", response_model=schemas.BlogResponse)
async def create_class_post(
    class_id: int,
    post: schemas.BlogCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        _lock_upload_owner(db, current_user.id)
        db_class = _ensure_active_class_access(db, current_user, class_id)
        validate_structured_upload_references(post)
        content = _build_post_content(post)
        asset_keys = post_asset_keys(content)

        new_post = models.Blog(
            title=post.title,
            content=content,
            owner_id=current_user.id,
            class_id=class_id,
        )
        db.add(new_post)
        db.flush()
        bind_post_assets(
            db,
            blog=new_post,
            actor_user_id=current_user.id,
            storage_keys=asset_keys,
            upload_root=UPLOAD_DIR,
            now=_utc_now_aware(),
        )
        db.commit()
        db.refresh(new_post)
    except Exception:
        db.rollback()
        raise
    
    result = {
        "id": new_post.id,
        "title": new_post.title,
        "content": new_post.content,
        "created_at": new_post.created_at,
        "owner_id": new_post.owner_id,
        "class_id": new_post.class_id,
        "author": f"{current_user.first_name} {current_user.last_name}",
        "author_profile_image": current_user.profile_image,
        "likes": len(new_post.likes) if hasattr(new_post, 'likes') else 0,
        "comments": len(new_post.comments) if hasattr(new_post, 'comments') else 0,
    }
    result.update(_post_analysis_payload(db, current_user, db_class, new_post))
    return result

@app.get("/api/classes/{class_id}/posts")
async def get_class_posts(
    class_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    db_class = _ensure_class_access(db, current_user, class_id)
    
    # Get posts with author information
    posts = db.query(models.Blog).filter(
        models.Blog.class_id == class_id
    ).order_by(models.Blog.created_at.desc()).all()
    
    saved_ids = set()
    if posts:
        saved_post_ids = [post.id for post in posts]
        saved_ids = {
            entry.post_id
            for entry in db.query(models.SavedPost).filter(
                models.SavedPost.user_id == current_user.id,
                models.SavedPost.post_id.in_(saved_post_ids),
            ).all()
        }

    # Format posts with author information
    formatted_posts = []
    for post in posts:
        author = db.query(models.User).filter(models.User.id == post.owner_id).first()
        formatted_post = {
            "id": post.id,
            "title": post.title,
            "content": post.content,  # Whitespace will be preserved
            "created_at": post.created_at,
            "owner_id": post.owner_id,
            "author": f"{author.first_name} {author.last_name}" if author else "Unknown Author",
            "author_profile_image": author.profile_image if author else None,
            "likes": len(post.likes) if hasattr(post, 'likes') else 0,
            "comments": len(post.comments) if hasattr(post, 'comments') else 0,
            "is_saved": post.id in saved_ids,
        }
        formatted_post.update(_post_analysis_payload(db, current_user, db_class, post))
        formatted_posts.append(formatted_post)
    
    return formatted_posts

@app.get("/api/users", response_model=list[schemas.AdminUserSummary])
async def get_users(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    _require_admin(current_user)
    users = db.query(models.User).all()
    return [
        {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "role": user.role.value,
            "is_admin": _is_admin_role(user.role),
            "created_at": user.created_at,
            "disabled": user.disabled_at is not None,
        }
        for user in users
    ]

@app.get("/api/classes")
async def get_classes(
    status: Literal["active", "archived"] = "active",
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    # Allow both admin and teacher access
    if not (_is_admin_role(current_user.role) or current_user.role == models.UserRole.TEACHER):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # For teachers, only return their classes
    if current_user.role == models.UserRole.TEACHER:
        teacher = _get_teacher_record(db, current_user)
        if not teacher:
            classes = []
        else:
            classes = db.query(models.Class).filter(
                models.Class.teacher_id == teacher.id,
                models.Class.status == status
            ).all()
    else:  # For admins, return all classes
        classes = db.query(models.Class).filter(
            models.Class.status == status
        ).all()
    
    # Add student count to each class
    result = []
    for class_ in classes:
        enrollment_count = db.query(models.ClassEnrollment).filter(
            models.ClassEnrollment.class_id == class_.id
        ).count()
        
        # Create a dict with class data and student count
        class_data = {
            "id": class_.id,
            "name": class_.name,
            "description": class_.description,
            "access_code": class_.access_code,
            "teacher_id": class_.teacher_id,
            "created_at": class_.created_at,
            "status": class_.status,
            "enrollment_count": enrollment_count
        }
        result.append(class_data)
    
    return result

def _initialize_upload_layout(upload_root: Path, *, production: bool) -> None:
    """Create only private child directories beneath a trusted upload root."""

    is_root_junction = getattr(upload_root, "is_junction", lambda: False)
    if upload_root.is_symlink() or is_root_junction():
        raise RuntimeError("Upload storage is unavailable")
    try:
        if production:
            if not upload_root.is_dir():
                raise RuntimeError("Upload storage is unavailable")
        else:
            upload_root.mkdir(mode=0o700, parents=True, exist_ok=True)

        resolved_root = upload_root.resolve(strict=True)
        for child_name in ("objects", ".incoming"):
            child = upload_root / child_name
            is_child_junction = getattr(child, "is_junction", lambda: False)
            if child.is_symlink() or is_child_junction():
                raise RuntimeError("Upload storage is unavailable")
            child.mkdir(mode=0o700, exist_ok=True)
            if (
                not child.is_dir()
                or child.is_symlink()
                or getattr(child, "is_junction", lambda: False)()
                or child.resolve(strict=True).parent != resolved_root
            ):
                raise RuntimeError("Upload storage is unavailable")
            if os.name == "posix":
                child_stat = child.stat()
                if not production and child_stat.st_uid == os.geteuid():
                    child.chmod(0o700)
                    child_stat = child.stat()
                if (
                    child_stat.st_uid != os.geteuid()
                    or stat.S_IMODE(child_stat.st_mode) != 0o700
                ):
                    raise RuntimeError("Upload storage is unavailable")
            if not os.access(child, os.W_OK | os.X_OK):
                raise RuntimeError("Upload storage is unavailable")
    except OSError as exc:
        raise RuntimeError("Upload storage is unavailable") from exc


# Production root custody is validated before import. The application creates
# private children, but never the configured production root or its ancestors.
_initialize_upload_layout(
    UPLOAD_DIR,
    production=settings.app_env == "production",
)


def reconcile_upload_assets(
    db: Session,
    *,
    now: datetime | None = None,
) -> dict[str, int]:
    return _reconcile_upload_assets(
        db,
        upload_root=UPLOAD_DIR,
        now=now or _utc_now_aware(),
    )


def _reconcile_upload_assets_once() -> bool:
    db = SessionLocal()
    try:
        reconcile_upload_assets(db)
        db.commit()
        return True
    except Exception:
        db.rollback()
        security_logger.error('{"event":"upload_reconciliation_failed"}')
        return False
    finally:
        db.close()


def _rollback_upload_session(db: Session) -> None:
    try:
        db.rollback()
    except Exception:
        # Resolve an ambiguous COMMIT only through a new independent session.
        pass


def _pending_upload_commit_is_visible(stored: StoredUpload, owner_user_id: int) -> bool:
    try:
        with SessionLocal() as verification_db:
            asset = (
                verification_db.query(models.UploadAsset)
                .filter(models.UploadAsset.storage_key == stored.storage_key)
                .one_or_none()
            )
            return bool(
                asset is not None
                and asset.owner_user_id == owner_user_id
                and asset.purpose == "POST"
                and asset.state in {"PENDING", "ACTIVE"}
                and asset.media_type == stored.spec.media_type
                and asset.size_bytes == stored.size
                and asset.sha256_digest == stored.sha256_digest
                and object_matches_registration(
                    UPLOAD_DIR,
                    storage_key=stored.storage_key,
                    size_bytes=stored.size,
                    sha256_digest=stored.sha256_digest,
                )
            )
    except Exception:
        return False


def _profile_upload_commit_is_visible(
    stored: StoredUpload,
    *,
    owner_user_id: int,
    purpose: str,
    profile_field: str,
) -> bool:
    try:
        with SessionLocal() as verification_db:
            active = (
                verification_db.query(models.UploadAsset)
                .filter(
                    models.UploadAsset.owner_user_id == owner_user_id,
                    models.UploadAsset.purpose == purpose,
                    models.UploadAsset.state == "ACTIVE",
                )
                .all()
            )
            user = verification_db.get(models.User, owner_user_id)
            return bool(
                len(active) == 1
                and active[0].storage_key == stored.storage_key
                and active[0].media_type == stored.spec.media_type
                and active[0].size_bytes == stored.size
                and active[0].sha256_digest == stored.sha256_digest
                and user is not None
                and getattr(user, profile_field) == stored.url
                and object_matches_registration(
                    UPLOAD_DIR,
                    storage_key=stored.storage_key,
                    size_bytes=stored.size,
                    sha256_digest=stored.sha256_digest,
                )
            )
    except Exception:
        return False


def _upload_reconciliation_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Upload finalization is being reconciled; refresh before retrying",
    )


async def _register_pending_upload(
    file: UploadFile,
    *,
    allowed_kinds: set[str],
    db: Session,
    current_user: models.User,
) -> StoredUpload:
    prepared = None
    stored = None
    try:
        prepared = await _save_validated_upload(file, allowed_kinds=allowed_kinds)
        now = _utc_now_aware()
        configure_upload_transaction(db)
        _lock_upload_owner(db, current_user.id)
        enforce_rate_limit(db, current_user.id, now=now)
        enforce_quota(db, current_user.id, prepared.size)
        stored = await run_in_threadpool(_finalize_prepared_upload, prepared)
        add_pending_asset(
            db,
            owner_user_id=current_user.id,
            stored=stored,
            now=now,
        )
        db.commit()
        return stored
    except Exception as exc:
        _rollback_upload_session(db)
        await run_in_threadpool(_remove_upload_candidate, prepared)
        if stored is not None and await run_in_threadpool(
            _pending_upload_commit_is_visible,
            stored,
            current_user.id,
        ):
            return stored
        if stored is not None or (
            prepared is not None and prepared.destination_path.is_file()
        ):
            raise _upload_reconciliation_error() from exc
        raise

# Add these new endpoints
@app.post("/api/upload/image")
async def upload_image(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    stored = await _register_pending_upload(
        file,
        allowed_kinds={"image"},
        db=db,
        current_user=current_user,
    )
    return {"url": stored.url}

@app.post("/api/upload/video")
async def upload_video(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    stored = await _register_pending_upload(
        file,
        allowed_kinds={"video"},
        db=db,
        current_user=current_user,
    )
    return {"url": stored.url}

@app.post("/api/upload/file")
async def upload_file(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    stored = await _register_pending_upload(
        file,
        allowed_kinds={"pdf"},
        db=db,
        current_user=current_user,
    )
    return {"url": stored.url}

@app.post("/api/upload")
async def upload_generic_file(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Upload a file and return its URL"""
    stored = await _register_pending_upload(
        file,
        allowed_kinds={"image", "pdf", "video"},
        db=db,
        current_user=current_user,
    )
    return {
        "url": stored.url,
        "filename": stored.original_filename,
        "size": stored.size,
    }

@app.get("/api/teacher/dashboard")
async def get_teacher_dashboard(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Get teacher dashboard data"""
    if current_user.role != models.UserRole.TEACHER:
        raise HTTPException(status_code=403, detail="Not a teacher")
    
    try:
        # Get classes taught by this teacher
        teacher = _get_teacher_record(db, current_user)
        if not teacher:
            classes = []
        else:
            classes = db.query(models.Class).filter(
                models.Class.teacher_id == teacher.id
            ).all()
        
        classes_data = []
        for class_ in classes:
            # Count enrollments for this class
            enrollment_count = db.query(models.ClassEnrollment).filter(
                models.ClassEnrollment.class_id == class_.id
            ).count()
            
            # Count posts in this class
            post_count = db.query(models.Blog).filter(
                models.Blog.class_id == class_.id
            ).count()
            
            # Get recent activity for this class
            recent_posts = db.query(models.Blog).filter(
                models.Blog.class_id == class_.id
            ).order_by(models.Blog.created_at.desc()).limit(5).all()
            
            recent_activity = []
            for post in recent_posts:
                student = db.query(models.User).filter(models.User.id == post.owner_id).first()
                if student:
                    recent_activity.append({
                        "id": post.id,
                        "title": post.title,
                        "student_name": f"{student.first_name} {student.last_name}",
                        "created_at": post.created_at
                    })
            
            classes_data.append({
                "id": class_.id,
                "name": class_.name,
                "description": class_.description,
                "access_code": class_.access_code,
                "enrollment_count": enrollment_count,
                "post_count": post_count,
                "recent_activity": recent_activity
            })
        
        return {
            "name": f"{current_user.first_name} {current_user.last_name}",
            "email": current_user.email,
            "classes": classes_data,
            "total_students": sum(c["enrollment_count"] for c in classes_data),
            "total_posts": sum(c["post_count"] for c in classes_data)
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load dashboard"
        ) from e

@app.post("/api/classes")
async def create_class(
    class_data: schemas.ClassCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Create a new class (for teachers)"""
    if current_user.role != models.UserRole.TEACHER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only teachers can create classes"
        )
    
    try:
        # Serialize creation on the canonical User -> Teacher association. This
        # prevents concurrent requests from creating duplicate teacher rows and
        # keeps ownership attached to user_id rather than a denormalized email.
        locked_user = (
            db.query(models.User)
            .filter(
                models.User.id == current_user.id,
                models.User.disabled_at.is_(None),
                models.User.role == models.UserRole.TEACHER,
            )
            .with_for_update(of=models.User)
            .first()
        )
        if locked_user is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only active teachers can create classes",
            )

        teacher = _get_teacher_record(db, locked_user)
        
        if not teacher:
            teacher = models.Teacher(
                name=f"{locked_user.first_name} {locked_user.last_name}",
                email=locked_user.email,
                user_id=locked_user.id,
            )
            db.add(teacher)
            db.flush()
        elif teacher.email != locked_user.email:
            # The migration performs the same reconciliation for legacy rows.
            teacher.email = locked_user.email
        
        # Generate a unique access code
        access_code = generate_unique_code(db)
        
        # Create new class with teacher_id from the Teacher table
        new_class = models.Class(
            name=class_data.name,
            description=class_data.description or "",
            access_code=access_code,
            teacher_id=teacher.id  # Use teacher.id, not current_user.id
        )
        
        db.add(new_class)
        db.commit()
        db.refresh(new_class)
        
        return {
            "id": new_class.id,
            "name": new_class.name,
            "description": new_class.description,
            "access_code": new_class.access_code,
            "created_at": new_class.created_at,
            "teacher_id": new_class.teacher_id
        }
    
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create class"
        ) from e

@app.post("/api/classes/{class_id}/assignments")
async def create_assignment(
    class_id: int,
    assignment: schemas.AssignmentCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    _ensure_active_class_owner(db, current_user, class_id)

    visibility = assignment.visibility or "class"
    if visibility not in ["class", "private"]:
        raise HTTPException(status_code=400, detail="Invalid assignment visibility")

    new_assignment = models.Assignment(
        class_id=class_id,
        title=assignment.title,
        description=assignment.description,
        due_date=assignment.due_date,
        created_by=current_user.id,
        allow_late=assignment.allow_late if assignment.allow_late is not None else True,
        visibility=visibility
    )
    db.add(new_assignment)
    db.commit()
    db.refresh(new_assignment)

    return {
        "id": new_assignment.id,
        "class_id": new_assignment.class_id,
        "title": new_assignment.title,
        "description": new_assignment.description,
        "due_date": new_assignment.due_date,
        "created_at": new_assignment.created_at,
        "created_by": new_assignment.created_by,
        "allow_late": new_assignment.allow_late,
        "visibility": new_assignment.visibility
    }

@app.put("/api/classes/{class_id}/assignments/{assignment_id}")
async def update_assignment(
    class_id: int,
    assignment_id: int,
    assignment: schemas.AssignmentUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    _ensure_active_class_owner(db, current_user, class_id)

    db_assignment = db.query(models.Assignment).filter(
        models.Assignment.id == assignment_id,
        models.Assignment.class_id == class_id
    ).first()
    if not db_assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    visibility = assignment.visibility or db_assignment.visibility or "class"
    if visibility not in ["class", "private"]:
        raise HTTPException(status_code=400, detail="Invalid assignment visibility")

    db_assignment.title = assignment.title
    db_assignment.description = assignment.description
    db_assignment.due_date = assignment.due_date
    db_assignment.allow_late = assignment.allow_late if assignment.allow_late is not None else True
    db_assignment.visibility = visibility

    db.commit()
    db.refresh(db_assignment)

    return {
        "id": db_assignment.id,
        "class_id": db_assignment.class_id,
        "title": db_assignment.title,
        "description": db_assignment.description,
        "due_date": db_assignment.due_date,
        "created_at": db_assignment.created_at,
        "created_by": db_assignment.created_by,
        "allow_late": db_assignment.allow_late,
        "visibility": db_assignment.visibility
    }

_PRIVATE_ASSIGNMENT_MUTATION_PATH = re.compile(
    r"^/api/assignments/[^/]+/(?P<operation>draft|submit)/?$"
)


def _is_private_assignment_mutation(request: Request) -> bool:
    """Keep rejected private assignment bodies out of validation responses."""
    path_match = _PRIVATE_ASSIGNMENT_MUTATION_PATH.fullmatch(request.url.path)
    return bool(path_match) and (
        (path_match.group("operation") == "draft" and request.method == "PUT")
        or (path_match.group("operation") == "submit" and request.method == "POST")
    )


def _set_private_no_store(response: Response) -> None:
    response.headers.update(ASSIGNMENT_PRIVATE_CACHE_HEADERS)


def _draft_revision_conflict() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Assignment draft changed in another session",
        headers=ASSIGNMENT_PRIVATE_CACHE_HEADERS,
    )


def _advance_assignment_draft_tombstone(
    db: Session,
    *,
    draft: models.AssignmentDraft | None,
    assignment_id: int,
    student_id: int,
) -> models.AssignmentDraft:
    if draft is None:
        draft = models.AssignmentDraft(
            assignment_id=assignment_id,
            student_id=student_id,
            content=None,
            revision=1,
        )
        db.add(draft)
    else:
        draft.content = None
        draft.revision += 1
    draft.updated_at = _utc_now_naive()
    return draft


@app.get("/api/classes/{class_id}/assignments")
async def list_assignments(
    class_id: int,
    response: Response,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    _set_private_no_store(response)
    _ensure_class_access(db, current_user, class_id)
    assignments_query = db.query(models.Assignment).filter(
        models.Assignment.class_id == class_id
    )
    if current_user.role == models.UserRole.STUDENT:
        assignments_query = assignments_query.filter(
            models.Assignment.visibility == "class"
        )
    assignments = assignments_query.order_by(models.Assignment.due_date.asc()).all()

    total_students = _get_class_student_count(db, class_id)
    assignment_items = []

    for assignment in assignments:
        stats = _get_assignment_stats(db, assignment, total_students)
        submission = None
        draft = None
        if current_user.role == models.UserRole.STUDENT:
            submission = db.query(models.AssignmentSubmission).filter(
                models.AssignmentSubmission.assignment_id == assignment.id,
                models.AssignmentSubmission.student_id == current_user.id
            ).first()
            draft = db.query(models.AssignmentDraft).filter(
                models.AssignmentDraft.assignment_id == assignment.id,
                models.AssignmentDraft.student_id == current_user.id
            ).first()

        assignment_items.append({
            "id": assignment.id,
            "class_id": assignment.class_id,
            "title": assignment.title,
            "description": assignment.description,
            "due_date": assignment.due_date,
            "created_at": assignment.created_at,
            "created_by": assignment.created_by,
            "allow_late": assignment.allow_late,
            "visibility": assignment.visibility,
            "stats": stats,
            "my_submission": {
                "id": submission.id,
                "submitted_at": submission.submitted_at,
                "is_late": submission.is_late,
                "content": submission.content,
                "ai_percentage": submission.ai_percentage,
                "ai_highlighted_html": submission.ai_highlighted_html,
                "ai_sentence_analysis": submission.ai_sentence_analysis
            } if submission else None,
            "my_draft": {
                "content": draft.content,
                "updated_at": draft.updated_at,
                "revision": draft.revision
            } if draft and draft.content else None,
            "my_draft_revision": draft.revision if draft else 0
        })

    return assignment_items


def _ensure_assignment_visible_to_student(
    current_user: models.User,
    assignment: models.Assignment,
) -> None:
    if (
        current_user.role == models.UserRole.STUDENT
        and assignment.visibility != "class"
    ):
        raise HTTPException(status_code=404, detail="Assignment not found")

@app.get("/api/assignments/{assignment_id}/draft")
async def get_assignment_draft(
    assignment_id: int,
    response: Response,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    _set_private_no_store(response)
    if current_user.role != models.UserRole.STUDENT:
        raise HTTPException(status_code=403, detail="Only students can access assignment drafts")

    assignment = db.query(models.Assignment).filter(models.Assignment.id == assignment_id).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    _ensure_assignment_visible_to_student(current_user, assignment)
    _ensure_class_access(db, current_user, assignment.class_id)

    draft = db.query(models.AssignmentDraft).filter(
        models.AssignmentDraft.assignment_id == assignment_id,
        models.AssignmentDraft.student_id == current_user.id
    ).first()

    return {
        "content": draft.content if draft and draft.content else "",
        "saved_at": draft.updated_at if draft and draft.content else None,
        "has_draft": bool(draft and draft.content),
        "revision": draft.revision if draft else 0
    }

@app.put("/api/assignments/{assignment_id}/draft")
async def save_assignment_draft(
    assignment_id: int,
    payload: schemas.AssignmentDraftUpdate,
    response: Response,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    _set_private_no_store(response)
    if current_user.role != models.UserRole.STUDENT:
        raise HTTPException(status_code=403, detail="Only students can save assignment drafts")

    assignment = db.query(models.Assignment).filter(models.Assignment.id == assignment_id).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    _ensure_assignment_visible_to_student(current_user, assignment)
    _ensure_active_class_access(db, current_user, assignment.class_id)

    # The user row is stable even when no draft row exists yet. Locking it
    # serializes revision-zero creates as well as updates and submissions.
    db.query(models.User).filter(
        models.User.id == current_user.id
    ).with_for_update().one()

    draft = db.query(models.AssignmentDraft).filter(
        models.AssignmentDraft.assignment_id == assignment_id,
        models.AssignmentDraft.student_id == current_user.id
    ).first()

    current_revision = draft.revision if draft else 0
    if payload.expected_revision != current_revision:
        raise _draft_revision_conflict()

    content = payload.content if payload.content else None

    if not draft:
        draft = models.AssignmentDraft(
            assignment_id=assignment_id,
            student_id=current_user.id,
            content=content,
            revision=1,
        )
        db.add(draft)
    else:
        draft.content = content
        draft.revision += 1

    draft.updated_at = _utc_now_naive()
    db.commit()
    db.refresh(draft)

    return {
        "content": draft.content or "",
        "saved_at": draft.updated_at if draft.content else None,
        "has_draft": bool(draft.content),
        "revision": draft.revision,
    }

@app.post("/api/assignments/{assignment_id}/submit")
async def submit_assignment(
    assignment_id: int,
    submission: schemas.AssignmentSubmissionCreate,
    response: Response,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    _set_private_no_store(response)
    if current_user.role != models.UserRole.STUDENT:
        raise HTTPException(status_code=403, detail="Only students can submit assignments")

    assignment = db.query(models.Assignment).filter(models.Assignment.id == assignment_id).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    _ensure_assignment_visible_to_student(current_user, assignment)
    _ensure_active_class_access(db, current_user, assignment.class_id)

    # Serialize with autosave even before the first draft row is created.
    db.query(models.User).filter(
        models.User.id == current_user.id
    ).with_for_update().one()

    draft = db.query(models.AssignmentDraft).filter(
        models.AssignmentDraft.assignment_id == assignment_id,
        models.AssignmentDraft.student_id == current_user.id
    ).first()

    current_draft_revision = draft.revision if draft else 0
    if submission.expected_draft_revision != current_draft_revision:
        raise _draft_revision_conflict()

    submitted_at = _utc_now_naive()
    due_date = assignment.due_date

    if due_date is not None:
        if due_date.tzinfo is not None and submitted_at.tzinfo is None:
            submitted_at = submitted_at.replace(tzinfo=due_date.tzinfo)
        elif due_date.tzinfo is None and submitted_at.tzinfo is not None:
            due_date = due_date.replace(tzinfo=submitted_at.tzinfo)

    is_late = due_date is not None and submitted_at > due_date
    if is_late and not assignment.allow_late:
        raise HTTPException(status_code=400, detail="Late submissions are not allowed")

    existing = db.query(models.AssignmentSubmission).filter(
        models.AssignmentSubmission.assignment_id == assignment_id,
        models.AssignmentSubmission.student_id == current_user.id
    ).first()

    if existing:
        existing.content = submission.content
        existing.submitted_at = submitted_at
        existing.is_late = is_late
        draft = _advance_assignment_draft_tombstone(
            db,
            draft=draft,
            assignment_id=assignment_id,
            student_id=current_user.id,
        )
        db.commit()
        db.refresh(existing)
        db.refresh(draft)
        
        return {
            "id": existing.id,
            "assignment_id": existing.assignment_id,
            "student_id": existing.student_id,
            "submitted_at": existing.submitted_at,
            "content": existing.content,
            "is_late": existing.is_late,
            "ai_percentage": existing.ai_percentage,
            "ai_highlighted_html": existing.ai_highlighted_html,
            "ai_sentence_analysis": existing.ai_sentence_analysis,
            "draft_revision": draft.revision,
        }

    new_submission = models.AssignmentSubmission(
        assignment_id=assignment_id,
        student_id=current_user.id,
        submitted_at=submitted_at,
        content=submission.content,
        is_late=is_late
    )
    db.add(new_submission)
    draft = _advance_assignment_draft_tombstone(
        db,
        draft=draft,
        assignment_id=assignment_id,
        student_id=current_user.id,
    )
    db.commit()
    db.refresh(new_submission)
    db.refresh(draft)
    
    return {
        "id": new_submission.id,
        "assignment_id": new_submission.assignment_id,
        "student_id": new_submission.student_id,
        "submitted_at": new_submission.submitted_at,
        "content": new_submission.content,
        "is_late": new_submission.is_late,
        "ai_percentage": new_submission.ai_percentage,
        "ai_highlighted_html": new_submission.ai_highlighted_html,
        "ai_sentence_analysis": new_submission.ai_sentence_analysis,
        "draft_revision": draft.revision,
    }

@app.get("/api/classes/{class_id}/assignments/{assignment_id}/submissions")
async def list_assignment_submissions(
    class_id: int,
    assignment_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    _db_class, assignment = _ensure_assignment_for_class(
        db,
        current_user,
        class_id,
        assignment_id,
    )
    submissions_query = db.query(models.AssignmentSubmission).filter(
        models.AssignmentSubmission.assignment_id == assignment.id
    )
    if current_user.role == models.UserRole.STUDENT:
        submissions_query = submissions_query.filter(
            models.AssignmentSubmission.student_id == current_user.id
        )
    submissions = submissions_query.all()

    results = []
    for submission in submissions:
        student = db.query(models.User).filter(models.User.id == submission.student_id).first()
        replies = db.query(models.AssignmentSubmissionReply).filter(
            models.AssignmentSubmissionReply.submission_id == submission.id
        ).order_by(models.AssignmentSubmissionReply.created_at.asc()).all()
        results.append({
            "id": submission.id,
            "assignment_id": submission.assignment_id,
            "student_id": submission.student_id,
            "submitted_at": submission.submitted_at,
            "content": submission.content,
            "is_late": submission.is_late,
            "ai_percentage": submission.ai_percentage,
            "ai_highlighted_html": submission.ai_highlighted_html,
            "ai_sentence_analysis": submission.ai_sentence_analysis,
            "student": {
                "id": student.id,
                "first_name": student.first_name,
                "last_name": student.last_name,
                "username": student.username,
                **(
                    {"email": student.email}
                    if current_user.role != models.UserRole.STUDENT
                    else {}
                ),
            } if student else None,
            "replies": [
                {
                    "id": reply.id,
                    "content": reply.content,
                    "created_at": reply.created_at,
                    "updated_at": reply.updated_at,
                    "user": {
                        "id": reply.user.id,
                        "first_name": reply.user.first_name,
                        "last_name": reply.user.last_name,
                        "username": reply.user.username,
                        "role": reply.user.role.value if hasattr(reply.user.role, "value") else str(reply.user.role)
                    } if reply.user else None
                }
                for reply in replies
            ]
        })

    return results

@app.get("/api/classes/{class_id}/assignments/{assignment_id}/submissions/{submission_id}/replies")
async def list_assignment_submission_replies(
    class_id: int,
    assignment_id: int,
    submission_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    _db_class, _assignment, submission = _ensure_submission_access(
        db,
        current_user,
        class_id,
        assignment_id,
        submission_id,
    )
    replies = db.query(models.AssignmentSubmissionReply).filter(
        models.AssignmentSubmissionReply.submission_id == submission_id
    ).order_by(models.AssignmentSubmissionReply.created_at.asc()).all()

    return [
        {
            "id": reply.id,
            "content": reply.content,
            "created_at": reply.created_at,
            "updated_at": reply.updated_at,
            "user": {
                "id": reply.user.id,
                "first_name": reply.user.first_name,
                "last_name": reply.user.last_name,
                "username": reply.user.username,
                "role": reply.user.role.value if hasattr(reply.user.role, "value") else str(reply.user.role)
            } if reply.user else None
        }
        for reply in replies
    ]

@app.post("/api/classes/{class_id}/assignments/{assignment_id}/submissions/{submission_id}/replies")
async def create_assignment_submission_reply(
    class_id: int,
    assignment_id: int,
    submission_id: int,
    payload: schemas.SubmissionReplyCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    db_class, _assignment, submission = _ensure_submission_access(
        db,
        current_user,
        class_id,
        assignment_id,
        submission_id,
    )
    _ensure_class_is_active(db_class)

    reply = models.AssignmentSubmissionReply(
        submission_id=submission_id,
        user_id=current_user.id,
        content=payload.content,
    )
    db.add(reply)
    db.commit()
    db.refresh(reply)

    return {
        "id": reply.id,
        "content": reply.content,
        "created_at": reply.created_at,
        "updated_at": reply.updated_at,
        "user": {
            "id": current_user.id,
            "first_name": current_user.first_name,
            "last_name": current_user.last_name,
            "username": current_user.username,
            "role": current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
        }
    }

@app.get("/api/classes/{class_id}/analytics")
async def get_class_analytics(
    class_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    db_class = _ensure_class_access(db, current_user, class_id)

    if current_user.role == models.UserRole.STUDENT:
        raise HTTPException(status_code=403, detail="Not authorized")

    total_students = _get_class_student_count(db, class_id)
    total_posts = db.query(models.Blog).filter(models.Blog.class_id == class_id).count()
    last_week = _utc_now_naive() - timedelta(days=7)
    posts_last_week = db.query(models.Blog).filter(
        models.Blog.class_id == class_id,
        models.Blog.created_at >= last_week
    ).count()
    start_of_day = datetime.combine(_utc_now_naive().date(), datetime.min.time())
    active_today = db.query(models.Blog.owner_id).filter(
        models.Blog.class_id == class_id,
        models.Blog.created_at >= start_of_day
    ).distinct().count()

    assignments = db.query(models.Assignment).filter(models.Assignment.class_id == class_id).all()
    assignments_total = len(assignments)
    submissions_total = 0
    on_time_total = 0
    late_total = 0
    missing_total = 0
    assignment_stats = []

    for assignment in assignments:
        stats = _get_assignment_stats(db, assignment, total_students)
        submissions_total += stats["submitted"]
        on_time_total += stats["on_time"]
        late_total += stats["late"]
        missing_total += stats["missing"]
        assignment_stats.append({
            "id": assignment.id,
            "title": assignment.title,
            "due_date": assignment.due_date,
            **stats
        })

    if assignments_total > 0 and total_students > 0:
        engagement_rate = min(
            100,
            round((submissions_total / (assignments_total * total_students)) * 100)
        )
    elif total_students > 0:
        engagement_rate = min(100, round((posts_last_week / total_students) * 100))
    else:
        engagement_rate = 0

    post_trend = _get_post_counts_last_days(db, class_id, days=7)

    return {
        "class_id": class_id,
        "class_name": db_class.name,
        "total_students": total_students,
        "total_posts": total_posts,
        "posts_last_week": posts_last_week,
        "active_today": active_today,
        "average_engagement": engagement_rate,
        "assignments_total": assignments_total,
        "submissions_total": submissions_total,
        "on_time_total": on_time_total,
        "late_total": late_total,
        "missing_total": missing_total,
        "assignment_stats": assignment_stats,
        "posts_last_7_days": post_trend
    }

@app.get("/api/teacher/analytics")
async def get_teacher_analytics(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if current_user.role != models.UserRole.TEACHER:
        raise HTTPException(status_code=403, detail="Not authorized")

    teacher = _get_teacher_record(db, current_user)
    if not teacher:
        return {
            "classes": [],
            "totals": {
                "classes": 0,
                "students": 0,
                "posts": 0,
                "assignments": 0,
                "submissions": 0,
                "on_time": 0,
                "late": 0,
                "missing": 0
            }
        }

    classes = db.query(models.Class).filter(models.Class.teacher_id == teacher.id).all()
    class_reports = []

    totals = {
        "classes": len(classes),
        "students": 0,
        "posts": 0,
        "assignments": 0,
        "submissions": 0,
        "on_time": 0,
        "late": 0,
        "missing": 0,
        "active_today": 0,
        "average_engagement": 0
    }

    engagement_sum = 0

    for class_ in classes:
        total_students = _get_class_student_count(db, class_.id)
        total_posts = db.query(models.Blog).filter(models.Blog.class_id == class_.id).count()
        assignments = db.query(models.Assignment).filter(models.Assignment.class_id == class_.id).all()
        start_of_day = datetime.combine(_utc_now_naive().date(), datetime.min.time())
        active_today = db.query(models.Blog.owner_id).filter(
            models.Blog.class_id == class_.id,
            models.Blog.created_at >= start_of_day
        ).distinct().count()
        submissions_total = 0
        on_time_total = 0
        late_total = 0
        missing_total = 0

        for assignment in assignments:
            stats = _get_assignment_stats(db, assignment, total_students)
            submissions_total += stats["submitted"]
            on_time_total += stats["on_time"]
            late_total += stats["late"]
            missing_total += stats["missing"]

        if len(assignments) > 0 and total_students > 0:
            class_engagement = min(
                100,
                round((submissions_total / (len(assignments) * total_students)) * 100)
            )
        elif total_students > 0:
            class_engagement = min(
                100,
                round((db.query(models.Blog).filter(
                    models.Blog.class_id == class_.id,
                    models.Blog.created_at >= _utc_now_naive() - timedelta(days=7)
                ).count() / total_students) * 100)
            )
        else:
            class_engagement = 0

        class_reports.append({
            "class_id": class_.id,
            "class_name": class_.name,
            "students": total_students,
            "posts": total_posts,
            "assignments": len(assignments),
            "submissions": submissions_total,
            "on_time": on_time_total,
            "late": late_total,
            "missing": missing_total,
            "active_today": active_today,
            "average_engagement": class_engagement
        })

        totals["students"] += total_students
        totals["posts"] += total_posts
        totals["assignments"] += len(assignments)
        totals["submissions"] += submissions_total
        totals["on_time"] += on_time_total
        totals["late"] += late_total
        totals["missing"] += missing_total
        totals["active_today"] += active_today
        engagement_sum += class_engagement

    totals["average_engagement"] = round(engagement_sum / totals["classes"], 0) if totals["classes"] else 0

    return {
        "classes": class_reports,
        "totals": totals
    }

@app.get("/api/classes/{class_id}/posts/{post_id}")
async def get_class_post(
    class_id: int,
    post_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    db_class, post = _ensure_post_access(db, current_user, class_id, post_id)
    
    # Get the author's information
    author = db.query(models.User).filter(models.User.id == post.owner_id).first()
    
    is_saved = db.query(models.SavedPost).filter(
        models.SavedPost.user_id == current_user.id,
        models.SavedPost.post_id == post.id,
    ).first() is not None

    # Return post with author info and content
    result = {
        "id": post.id,
        "title": post.title,
        "content": post.content,
        "created_at": post.created_at,
        "owner_id": post.owner_id,
        "class_id": post.class_id,
        "author": {
            "id": author.id,
            "first_name": author.first_name,
            "last_name": author.last_name,
            "profile_image": author.profile_image,
        },
        "is_saved": is_saved,
    }
    result.update(_post_analysis_payload(db, current_user, db_class, post))
    return result

@app.put("/api/classes/{class_id}/posts/{post_id}")
async def update_class_post(
    class_id: int,
    post_id: int,
    post: schemas.BlogCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    try:
        db_class, db_post = _ensure_post_access(db, current_user, class_id, post_id)
        _ensure_class_is_active(db_class)
        if not _can_moderate_post(db, current_user, db_class, db_post):
            raise HTTPException(status_code=403, detail="Not authorized to edit this post")

        _lock_upload_owner(db, db_post.owner_id)
        validate_structured_upload_references(post)
        content = _build_post_content(post)
        asset_keys = post_asset_keys(content)
        bind_post_assets(
            db,
            blog=db_post,
            actor_user_id=current_user.id,
            storage_keys=asset_keys,
            upload_root=UPLOAD_DIR,
            now=_utc_now_aware(),
        )
        db_post.title = post.title
        db_post.content = content
        db_post.updated_at = _utc_now_naive()
        db.commit()
        db.refresh(db_post)
    except Exception:
        db.rollback()
        raise
    
    # Return updated post
    result = {
        "id": db_post.id,
        "title": db_post.title,  # Make sure title is returned
        "content": db_post.content,
        "created_at": db_post.created_at,
        "owner_id": db_post.owner_id,
        "class_id": db_post.class_id,
        "author": f"{current_user.first_name} {current_user.last_name}",
        "author_profile_image": current_user.profile_image,
        "likes": len(db_post.likes) if hasattr(db_post, 'likes') else 0,
        "comments": len(db_post.comments) if hasattr(db_post, 'comments') else 0,
    }
    result.update(_post_analysis_payload(db, current_user, db_class, db_post))
    return result

@app.delete("/api/classes/{class_id}/posts/{post_id}")
async def delete_class_post(
    class_id: int,
    post_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    try:
        db_class, post = _ensure_post_access(db, current_user, class_id, post_id)
        _ensure_class_is_active(db_class)
        if not _can_moderate_post(db, current_user, db_class, post):
            raise HTTPException(status_code=403, detail="Not authorized to delete this post")
        _lock_upload_owner(db, post.owner_id)
        _lock_upload_blog(db, post.id)
        _delete_blogs_with_dependencies(db, [post.id])
        db.commit()
    except Exception:
        db.rollback()
        raise
    
    return {"message": "Post deleted successfully"}



def generate_unique_code(db: Session, length: int = 6) -> str:
    while True:
        alphabet = string.ascii_uppercase + string.digits
        code = "".join(secrets.choice(alphabet) for _ in range(length))
        existing = db.query(models.Class).filter(
            models.Class.access_code == code
        ).first()
        if not existing:
            return code

@app.get("/api/student/classes")
async def get_student_classes(
    status: Literal["active", "archived"] = "active",
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if current_user.role != models.UserRole.STUDENT:
        raise HTTPException(status_code=403, detail="Not a student")
    
    enrollments = db.query(models.ClassEnrollment).filter(
        models.ClassEnrollment.student_id == current_user.id
    ).all()
    
    classes = []
    for enrollment in enrollments:
        class_ = db.query(models.Class).filter(
            models.Class.id == enrollment.class_id,
            models.Class.status == status
        ).first()
        
        if class_:  # Only include classes with the requested status
            teacher = db.query(models.Teacher).filter(models.Teacher.id == class_.teacher_id).first()
            classes.append({
                "id": class_.id,
                "name": class_.name,
                "description": class_.description,
                "teacher_name": teacher.name,
                "status": class_.status
            })
    
    return classes

@app.post("/api/student/join-class")
async def join_class(
    class_data: schemas.JoinClassRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if current_user.role != models.UserRole.STUDENT:
        raise HTTPException(status_code=403, detail="Not a student")
    
    class_ = db.query(models.Class).filter(
        models.Class.access_code == class_data.access_code,
        models.Class.status == "active",
    ).first()
    
    if not class_:
        raise HTTPException(status_code=404, detail="Class not found")
    
    # Check if already enrolled
    existing_enrollment = db.query(models.ClassEnrollment).filter(
        models.ClassEnrollment.student_id == current_user.id,
        models.ClassEnrollment.class_id == class_.id
    ).first()
    
    if existing_enrollment:
        raise HTTPException(status_code=400, detail="Already enrolled in this class")
    
    enrollment = models.ClassEnrollment(
        student_id=current_user.id,
        class_id=class_.id
    )
    
    db.add(enrollment)
    db.commit()
    
    return {"message": "Successfully joined class"}

@app.get("/api/student/posts")
async def get_student_posts(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if current_user.role != models.UserRole.STUDENT:
        raise HTTPException(status_code=403, detail="Not a student")
    
    # Get all posts by the student
    posts = db.query(models.Blog).filter(
        models.Blog.owner_id == current_user.id
    ).order_by(models.Blog.created_at.desc()).all()
    
    # Add class information to each post
    posts_with_class = []
    for post in posts:
        class_ = db.query(models.Class).filter(models.Class.id == post.class_id).first()
        if class_ is None or not _can_access_class(db, current_user, class_):
            continue
        post_data = {
            "id": post.id,
            "title": post.title,
            "content": post.content,
            "created_at": post.created_at,
            "owner_id": post.owner_id,
            "class_id": post.class_id,
            "class_name": class_.name,
        }
        post_data.update(_post_analysis_payload(db, current_user, class_, post))
        posts_with_class.append(post_data)
    
    return posts_with_class

@app.post("/api/user/update-profile")
async def update_profile(
    profile_data: schemas.ProfileUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Update user profile information"""
    try:
        user = _lock_upload_owner(db, current_user.id)
        update_values = profile_data.model_dump(exclude_unset=True)
        cover_preset = update_values.pop("cover_preset", None)
        if cover_preset is not None:
            preset_urls = {
                "classroom-1": "/Classroom1.jpeg",
                "classroom-2": "/Classroom2.jpeg",
                "classroom-3": "/Classroom3.jpeg",
                "classroom-4": "/Classroom4.jpeg",
            }
            active_cover_assets = (
                db.query(models.UploadAsset)
                .filter(
                    models.UploadAsset.owner_user_id == user.id,
                    models.UploadAsset.purpose == "COVER_IMAGE",
                    models.UploadAsset.state == "ACTIVE",
                )
                .order_by(models.UploadAsset.storage_key)
                .with_for_update(of=models.UploadAsset)
                .all()
            )
            queue_assets(active_cover_assets, now=_utc_now_aware())
            user.cover_image = preset_urls[cover_preset]

        for field_name, value in update_values.items():
            setattr(user, field_name, value)
            
        db.commit()
        db.refresh(user)
        
        return {
            "message": "Profile updated successfully",
            "profile": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "bio": user.bio,
                "role": user.role.value if hasattr(user.role, "value") else user.role,
                "profile_image": user.profile_image,
                "cover_image": user.cover_image,
                "avatar_id": user.avatar_id,
                "avatar_color": user.avatar_color,
                "created_at": user.created_at
            }
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update profile") from e


async def _replace_profile_upload(
    file: UploadFile,
    *,
    purpose: str,
    profile_field: str,
    db: Session,
    current_user: models.User,
) -> str:
    prepared = None
    stored = None
    try:
        prepared = await _save_validated_upload(file, allowed_kinds={"image"})
        now = _utc_now_aware()
        configure_upload_transaction(db)
        user = _lock_upload_owner(db, current_user.id)
        enforce_rate_limit(db, current_user.id, now=now)
        enforce_quota(db, current_user.id, prepared.size)
        stored = await run_in_threadpool(_finalize_prepared_upload, prepared)
        add_active_profile_asset(
            db,
            owner_user_id=user.id,
            purpose=purpose,
            stored=stored,
            now=now,
        )
        setattr(user, profile_field, stored.url)
        db.commit()
        return stored.url
    except Exception as exc:
        _rollback_upload_session(db)
        await run_in_threadpool(_remove_upload_candidate, prepared)
        if stored is not None and await run_in_threadpool(
            _profile_upload_commit_is_visible,
            stored,
            owner_user_id=current_user.id,
            purpose=purpose,
            profile_field=profile_field,
        ):
            return stored.url
        if stored is not None or (
            prepared is not None and prepared.destination_path.is_file()
        ):
            raise _upload_reconciliation_error() from exc
        raise

@app.post("/api/user/upload-profile-image")
async def upload_profile_image(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Upload profile image"""
    try:
        image_url = await _replace_profile_upload(
            file,
            purpose="PROFILE_IMAGE",
            profile_field="profile_image",
            db=db,
            current_user=current_user,
        )
        return {"image_url": image_url}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to upload image") from e

@app.post("/api/user/upload-cover-image")
async def upload_cover_image(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Upload cover image"""
    try:
        image_url = await _replace_profile_upload(
            file,
            purpose="COVER_IMAGE",
            profile_field="cover_image",
            db=db,
            current_user=current_user,
        )
        return {"image_url": image_url}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to upload image") from e

def _collect_ids(query) -> List[int]:
    return [record_id for (record_id,) in query.all()]

def _delete_blogs_with_dependencies(db: Session, blog_ids: List[int]) -> None:
    if not blog_ids:
        return

    (
        db.query(models.Blog)
        .filter(models.Blog.id.in_(sorted(blog_ids)))
        .order_by(models.Blog.id)
        .with_for_update(of=models.Blog)
        .all()
    )
    queue_blog_assets(db, blog_ids, now=_utc_now_aware())

    comment_ids = _collect_ids(
        db.query(models.Comment.id).filter(models.Comment.blog_id.in_(blog_ids))
    )

    if comment_ids:
        db.query(models.CommentLike).filter(
            models.CommentLike.comment_id.in_(comment_ids)
        ).delete(synchronize_session=False)

    db.query(models.Comment).filter(
        models.Comment.blog_id.in_(blog_ids)
    ).delete(synchronize_session=False)

    db.query(models.PostLike).filter(
        models.PostLike.post_id.in_(blog_ids)
    ).delete(synchronize_session=False)

    db.query(models.SavedPost).filter(
        models.SavedPost.post_id.in_(blog_ids)
    ).delete(synchronize_session=False)

    db.query(models.Blog).filter(
        models.Blog.id.in_(blog_ids)
    ).delete(synchronize_session=False)

def _delete_assignments_with_dependencies(db: Session, assignment_ids: List[int]) -> None:
    if not assignment_ids:
        return

    db.query(models.AssignmentDraft).filter(
        models.AssignmentDraft.assignment_id.in_(assignment_ids)
    ).delete(synchronize_session=False)

    submission_ids = _collect_ids(
        db.query(models.AssignmentSubmission.id).filter(
            models.AssignmentSubmission.assignment_id.in_(assignment_ids)
        )
    )

    if submission_ids:
        db.query(models.AssignmentSubmissionReply).filter(
            models.AssignmentSubmissionReply.submission_id.in_(submission_ids)
        ).delete(synchronize_session=False)

    db.query(models.AssignmentSubmission).filter(
        models.AssignmentSubmission.assignment_id.in_(assignment_ids)
    ).delete(synchronize_session=False)

    db.query(models.AssignmentReminderNotification).filter(
        models.AssignmentReminderNotification.assignment_id.in_(assignment_ids)
    ).delete(synchronize_session=False)

    db.query(models.Assignment).filter(
        models.Assignment.id.in_(assignment_ids)
    ).delete(synchronize_session=False)

def _delete_classes_with_dependencies(db: Session, class_ids: List[int]) -> None:
    if not class_ids:
        return

    class_assignment_ids = _collect_ids(
        db.query(models.Assignment.id).filter(models.Assignment.class_id.in_(class_ids))
    )
    _delete_assignments_with_dependencies(db, class_assignment_ids)

    class_blog_ids = _collect_ids(
        db.query(models.Blog.id).filter(models.Blog.class_id.in_(class_ids))
    )
    _delete_blogs_with_dependencies(db, class_blog_ids)

    db.query(models.ClassEnrollment).filter(
        models.ClassEnrollment.class_id.in_(class_ids)
    ).delete(synchronize_session=False)

    db.query(models.Class).filter(
        models.Class.id.in_(class_ids)
    ).delete(synchronize_session=False)

def _delete_user_dependencies(db: Session, user: models.User) -> None:
    teacher_record = _get_teacher_record(db, user)

    if teacher_record:
        teacher_class_ids = _collect_ids(
            db.query(models.Class.id).filter(models.Class.teacher_id == teacher_record.id)
        )
        _delete_classes_with_dependencies(db, teacher_class_ids)

        db.query(models.Teacher).filter(
            models.Teacher.id == teacher_record.id
        ).delete(synchronize_session=False)

    created_assignment_ids = _collect_ids(
        db.query(models.Assignment.id).filter(models.Assignment.created_by == user.id)
    )
    _delete_assignments_with_dependencies(db, created_assignment_ids)

    owned_blog_ids = _collect_ids(
        db.query(models.Blog.id).filter(models.Blog.owner_id == user.id)
    )
    _delete_blogs_with_dependencies(db, owned_blog_ids)

    authored_comment_ids = _collect_ids(
        db.query(models.Comment.id).filter(models.Comment.user_id == user.id)
    )
    if authored_comment_ids:
        db.query(models.CommentLike).filter(
            models.CommentLike.comment_id.in_(authored_comment_ids)
        ).delete(synchronize_session=False)

    db.query(models.Comment).filter(
        models.Comment.user_id == user.id
    ).delete(synchronize_session=False)

    db.query(models.CommentLike).filter(
        models.CommentLike.user_id == user.id
    ).delete(synchronize_session=False)

    db.query(models.PostLike).filter(
        models.PostLike.user_id == user.id
    ).delete(synchronize_session=False)

    student_submission_ids = _collect_ids(
        db.query(models.AssignmentSubmission.id).filter(
            models.AssignmentSubmission.student_id == user.id
        )
    )
    if student_submission_ids:
        db.query(models.AssignmentSubmissionReply).filter(
            models.AssignmentSubmissionReply.submission_id.in_(student_submission_ids)
        ).delete(synchronize_session=False)

    db.query(models.AssignmentSubmissionReply).filter(
        models.AssignmentSubmissionReply.user_id == user.id
    ).delete(synchronize_session=False)

    db.query(models.AssignmentSubmission).filter(
        models.AssignmentSubmission.student_id == user.id
    ).delete(synchronize_session=False)

    db.query(models.AssignmentDraft).filter(
        models.AssignmentDraft.student_id == user.id
    ).delete(synchronize_session=False)

    db.query(models.ClassEnrollment).filter(
        models.ClassEnrollment.student_id == user.id
    ).delete(synchronize_session=False)

    db.query(models.PasswordReset).filter(
        models.PasswordReset.user_id == user.id
    ).delete(synchronize_session=False)

    queue_owner_assets(db, user.id, now=_utc_now_aware())
    db.flush()
    db.query(models.UploadAsset).filter(
        models.UploadAsset.owner_user_id == user.id
    ).update({models.UploadAsset.owner_user_id: None}, synchronize_session=False)

def _get_class_student_count(db: Session, class_id: int) -> int:
    return db.query(models.ClassEnrollment).filter(
        models.ClassEnrollment.class_id == class_id
    ).count()

def _get_assignment_stats(db: Session, assignment: models.Assignment, total_students: int) -> dict:
    submissions = db.query(models.AssignmentSubmission).filter(
        models.AssignmentSubmission.assignment_id == assignment.id
    ).all()

    on_time = 0
    late = 0
    for submission in submissions:
        if assignment.due_date and submission.submitted_at and submission.submitted_at <= assignment.due_date:
            on_time += 1
        else:
            late += 1

    submitted = len(submissions)
    missing = max(total_students - submitted, 0)

    return {
        "submitted": submitted,
        "on_time": on_time,
        "late": late,
        "missing": missing
    }

def _get_post_counts_last_days(db: Session, class_id: int, days: int = 7) -> list[dict]:
    today = _utc_now_naive().date()
    results = []
    for offset in range(days - 1, -1, -1):
        day = today - timedelta(days=offset)
        start = datetime.combine(day, datetime.min.time())
        end = start + timedelta(days=1)
        count = db.query(models.Blog).filter(
            models.Blog.class_id == class_id,
            models.Blog.created_at >= start,
            models.Blog.created_at < end
        ).count()
        results.append({
            "date": day.isoformat(),
            "count": count
        })
    return results

@app.get("/api/user/profile")
async def get_user_profile(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Get user profile information"""
    try:
        return {
            "id": current_user.id,
            "username": current_user.username,
            "email": current_user.email,
            "first_name": current_user.first_name,
            "last_name": current_user.last_name,
            "bio": current_user.bio,
            "role": current_user.role.value if hasattr(current_user.role, "value") else current_user.role,
            "profile_image": current_user.profile_image,
            "cover_image": current_user.cover_image,
            "avatar_id": current_user.avatar_id,
            "avatar_color": current_user.avatar_color,
            "class_ids": _get_user_class_ids(db, current_user),
            "created_at": current_user.created_at
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to fetch profile") from e

@app.get("/api/user/settings")
async def get_user_settings(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    settings = _get_or_create_user_settings(db, current_user)
    return _serialize_user_settings(settings, current_user.role)

@app.put("/api/user/settings")
async def update_user_settings(
    payload: UserSettingsUpdateRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    settings = _get_or_create_user_settings(db, current_user)
    next_payload = {
        **_serialize_user_settings(settings, current_user.role),
        **payload.model_dump(exclude_none=True),
    }
    _apply_user_settings_to_model(settings, next_payload, current_user.role)
    db.commit()
    db.refresh(settings)
    return _serialize_user_settings(settings, current_user.role)

@app.get("/api/push/public-key")
async def get_push_public_key(current_user: models.User = Depends(get_current_user)):
    return {
        "enabled": WEB_PUSH_ENABLED,
        "publicKey": VAPID_PUBLIC_KEY if WEB_PUSH_ENABLED else None,
    }

@app.get("/api/push/subscription")
async def get_push_subscription_status(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    subscription = (
        db.query(models.PushSubscription)
        .filter(models.PushSubscription.user_id == current_user.id)
        .first()
    )
    return {"subscribed": subscription is not None}

@app.post("/api/push/subscribe")
async def subscribe_push_notifications(
    payload: PushSubscriptionEnvelopeRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if not WEB_PUSH_ENABLED:
        raise HTTPException(status_code=503, detail="Web push notifications are not configured on the server")

    subscription = payload.subscription
    endpoint = (subscription.endpoint or "").strip()
    p256dh = (subscription.keys.p256dh or "").strip()
    auth = (subscription.keys.auth or "").strip()

    if not endpoint or not p256dh or not auth:
        raise HTTPException(status_code=400, detail="Invalid push subscription payload")

    existing = (
        db.query(models.PushSubscription)
        .filter(models.PushSubscription.endpoint == endpoint)
        .first()
    )

    if existing:
        if existing.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Push subscription is already registered",
            )
        existing.p256dh = p256dh
        existing.auth = auth
    else:
        db.add(
            models.PushSubscription(
                user_id=current_user.id,
                endpoint=endpoint,
                p256dh=p256dh,
                auth=auth,
            )
        )

    db.commit()
    return {"subscribed": True}

@app.delete("/api/push/unsubscribe")
async def unsubscribe_push_notifications(
    payload: PushSubscriptionEnvelopeRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    endpoint = (payload.subscription.endpoint or "").strip()
    if endpoint:
        db.query(models.PushSubscription).filter(
            models.PushSubscription.user_id == current_user.id,
            models.PushSubscription.endpoint == endpoint,
        ).delete(synchronize_session=False)
    else:
        db.query(models.PushSubscription).filter(
            models.PushSubscription.user_id == current_user.id
        ).delete(synchronize_session=False)

    db.commit()
    return {"subscribed": False}

@app.delete("/api/user/account")
async def delete_user_account(
    confirm: str,
    response: Response,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Delete the currently authenticated user account and related data."""
    if confirm.strip().upper() != "DELETE":
        raise HTTPException(status_code=400, detail="Confirmation must be DELETE")

    try:
        # Every account lifecycle operation locks the parent User before child
        # session/reset rows. This prevents reverse-order deadlocks and closes
        # the window for a newly issued session to survive account deletion.
        user = (
            db.query(models.User)
            .filter(
                models.User.id == current_user.id,
                models.User.disabled_at.is_(None),
            )
            .with_for_update(of=models.User)
            .first()
        )
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")

        revoke_all_sessions(db, user_id=user.id)
        _delete_user_dependencies(db, user)
        db.delete(user)
        db.commit()
        _clear_browser_session(response)
        return {"message": "Account deleted successfully"}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to delete account") from e

@app.get("/api/user/profile/{user_id}")
async def get_public_user_profile(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Get another user's profile if there is a shared class"""
    target_user = db.query(models.User).filter(models.User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    visible_class_ids = _ensure_profile_access(db, current_user, target_user)

    role_value = target_user.role.value if hasattr(target_user.role, "value") else str(target_user.role)
    is_owner_or_admin = current_user.id == target_user.id or _is_admin_role(current_user.role)
    target_settings = _get_or_create_user_settings(db, target_user)

    # Keep public teacher/admin profiles minimal for non-admin viewers.
    allow_extended_profile = is_owner_or_admin or role_value == "STUDENT"
    if role_value == "STUDENT" and not is_owner_or_admin and not target_settings.show_profile_to_classmates:
        allow_extended_profile = False

    return {
        "id": target_user.id,
        "username": target_user.username,
        "email": target_user.email if is_owner_or_admin else None,
        "first_name": target_user.first_name,
        "last_name": target_user.last_name,
        "bio": target_user.bio if allow_extended_profile else None,
        "role": role_value,
        "profile_image": target_user.profile_image,
        "cover_image": target_user.cover_image if allow_extended_profile else None,
        "avatar_id": target_user.avatar_id,
        "avatar_color": target_user.avatar_color,
        "class_ids": visible_class_ids,
        "created_at": target_user.created_at
    }

@app.get("/api/user/posts")
async def get_current_user_posts(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Get posts for the current user"""
    posts = db.query(models.Blog).filter(models.Blog.owner_id == current_user.id).all()

    posts_with_class = []
    for post in posts:
        class_ = db.query(models.Class).filter(models.Class.id == post.class_id).first()
        if class_ is None:
            continue
        post_data = {
            "id": post.id,
            "title": post.title,
            "content": post.content,
            "created_at": post.created_at,
            "owner_id": post.owner_id,
            "class_id": post.class_id,
            "class_name": class_.name,
        }
        post_data.update(_post_analysis_payload(db, current_user, class_, post))
        posts_with_class.append(post_data)

    return posts_with_class

@app.get("/api/user/{user_id}/posts")
async def get_user_posts(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Get another user's posts restricted to shared classes"""
    target_user = db.query(models.User).filter(models.User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    if current_user.id != target_user.id and not _is_admin_role(current_user.role):
        shared_classes = _ensure_profile_access(db, current_user, target_user)
        posts = db.query(models.Blog).filter(
            models.Blog.owner_id == target_user.id,
            models.Blog.class_id.in_(shared_classes)
        ).all()
    else:
        posts = db.query(models.Blog).filter(models.Blog.owner_id == target_user.id).all()

    posts_with_class = []
    for post in posts:
        class_ = db.query(models.Class).filter(models.Class.id == post.class_id).first()
        if class_ is None:
            continue
        post_data = {
            "id": post.id,
            "title": post.title,
            "content": post.content,
            "created_at": post.created_at,
            "owner_id": post.owner_id,
            "class_id": post.class_id,
            "class_name": class_.name,
        }
        post_data.update(_post_analysis_payload(db, current_user, class_, post))
        posts_with_class.append(post_data)

    return posts_with_class

@app.post("/api/classes/{class_id}/posts/{post_id}/save")
async def toggle_save_post(
    class_id: int,
    post_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Save or unsave a post for the current user."""
    _ensure_class_access(db, current_user, class_id)

    post = db.query(models.Blog).filter(
        models.Blog.id == post_id,
        models.Blog.class_id == class_id
    ).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    existing_saved = db.query(models.SavedPost).filter(
        models.SavedPost.post_id == post_id,
        models.SavedPost.user_id == current_user.id
    ).first()

    if existing_saved:
        db.delete(existing_saved)
        action = "unsaved"
        is_saved = False
    else:
        db.add(models.SavedPost(post_id=post_id, user_id=current_user.id))
        action = "saved"
        is_saved = True

    db.commit()

    return {
        "action": action,
        "post_id": post_id,
        "is_saved": is_saved,
    }

@app.get("/api/user/saved-posts")
async def get_saved_posts(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Return posts saved by the current user."""
    saved_entries = db.query(models.SavedPost).filter(
        models.SavedPost.user_id == current_user.id
    ).order_by(models.SavedPost.created_at.desc()).all()

    saved_posts = []
    for entry in saved_entries:
        post = db.query(models.Blog).filter(models.Blog.id == entry.post_id).first()
        if not post:
            continue

        class_ = db.query(models.Class).filter(models.Class.id == post.class_id).first()
        if class_ is None or not _can_access_class(db, current_user, class_):
            continue
        saved_posts.append({
            "id": post.id,
            "title": post.title,
            "content": post.content,
            "created_at": post.created_at,
            "class_id": post.class_id,
            "class_name": class_.name if class_ else "Unknown Class",
            "owner_id": post.owner_id,
            "likes": len(post.likes) if hasattr(post, 'likes') else 0,
            "comments": len(post.comments) if hasattr(post, 'comments') else 0,
            "saved_at": entry.created_at,
            "is_saved": True,
        })

    return saved_posts

@app.post("/api/classes/{class_id}/posts/{post_id}/like")
async def like_post(
    class_id: int,
    post_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Like or unlike a post"""
    db_class, post = _ensure_post_access(db, current_user, class_id, post_id)
    if db_class.status != "active":
        raise HTTPException(status_code=409, detail="This class is not active")
    
    # Check if the user already liked this post
    existing_like = db.query(models.PostLike).filter(
        models.PostLike.post_id == post_id,
        models.PostLike.user_id == current_user.id
    ).first()
    
    if existing_like:
        # Unlike - remove the like
        db.delete(existing_like)
        action = "unliked"
    else:
        # Like - add a new like
        new_like = models.PostLike(
            post_id=post_id,
            user_id=current_user.id
        )
        db.add(new_like)
        action = "liked"
    
    db.commit()
    
    # Get updated like count
    like_count = db.query(models.PostLike).filter(
        models.PostLike.post_id == post_id
    ).count()
    
    return {
        "action": action,
        "post_id": post_id,
        "like_count": like_count
    }

@app.get("/api/classes/{class_id}/posts/{post_id}/likes")
async def get_post_likes(
    class_id: int,
    post_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Get likes for a post"""
    _db_class, post = _ensure_post_access(db, current_user, class_id, post_id)
    
    # Check if the current user liked this post
    user_liked = db.query(models.PostLike).filter(
        models.PostLike.post_id == post_id,
        models.PostLike.user_id == current_user.id
    ).first() is not None
    
    # Get all likes
    likes = db.query(models.PostLike).filter(
        models.PostLike.post_id == post_id
    ).all()
    
    # Get users who liked
    like_users = []
    for like in likes:
        user = db.query(models.User).filter(models.User.id == like.user_id).first()
        if user:
            like_users.append({
                "id": user.id,
                "name": f"{user.first_name} {user.last_name}".strip(),
                "username": user.username
            })
    
    return {
        "post_id": post_id,
        "like_count": len(likes),
        "user_liked": user_liked,
        "users": like_users
    }

@app.get("/api/classes/{class_id}/posts/{post_id}/comments")
async def get_comments(
    class_id: int,
    post_id: int,
    skip: int = Query(default=0, ge=0, le=10_000),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Get comments for a post, with pagination support"""
    _db_class, post = _ensure_post_access(db, current_user, class_id, post_id)
    
    # Get root comments first (comments without a parent)
    root_comments = db.query(models.Comment).filter(
        models.Comment.blog_id == post_id,
        models.Comment.parent_id.is_(None)
    ).order_by(models.Comment.created_at.desc()).offset(skip).limit(limit).all()
    
    # Function to recursively get comment data with user info and likes
    def get_comment_data(comment, depth=0, max_depth=3):
        # Get user info
        user = db.query(models.User).filter(models.User.id == comment.user_id).first()
        
        # Get like count and current user's like status
        like_count = db.query(models.CommentLike).filter(
            models.CommentLike.comment_id == comment.id
        ).count()
        
        user_liked = db.query(models.CommentLike).filter(
            models.CommentLike.comment_id == comment.id,
            models.CommentLike.user_id == current_user.id
        ).first() is not None
        
        # Get replies, but limit depth to avoid excessive nesting
        replies_data = []
        if depth < max_depth:
            replies = db.query(models.Comment).filter(
                models.Comment.parent_id == comment.id
            ).order_by(models.Comment.created_at).all()
            
            for reply in replies:
                replies_data.append(get_comment_data(reply, depth + 1, max_depth))
        
        # Return formatted comment data
        return {
            "id": comment.id,
            "content": comment.content,
            "created_at": comment.created_at,
            "updated_at": comment.updated_at,
            "user": {
                "id": user.id,
                "username": user.username,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "profile_image": user.profile_image
            },
            "likes": like_count,
            "user_liked": user_liked,
            "replies": replies_data,
            "has_more_replies": len(comment.replies) > len(replies_data) if depth == max_depth else False,
            "reply_count": len(comment.replies)
        }
    
    # Get formatted comment data for all root comments
    comments_data = [get_comment_data(comment) for comment in root_comments]
    
    # Get total count for pagination
    total_root_comments = db.query(models.Comment).filter(
        models.Comment.blog_id == post_id,
        models.Comment.parent_id.is_(None)
    ).count()
    
    return {
        "comments": comments_data,
        "total": total_root_comments,
        "has_more": total_root_comments > skip + limit
    }

@app.get("/api/comments/{comment_id}/replies")
async def get_comment_replies(
    comment_id: int,
    skip: int = Query(default=0, ge=0, le=10_000),
    limit: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Get replies for a specific comment"""
    _db_class, _post, comment = _ensure_comment_access(db, current_user, comment_id)
    
    # Get replies with pagination
    replies = db.query(models.Comment).filter(
        models.Comment.parent_id == comment_id
    ).order_by(models.Comment.created_at).offset(skip).limit(limit).all()
    
    # Function to format reply data (similar to above but without deep recursion)
    def format_reply(reply):
        user = db.query(models.User).filter(models.User.id == reply.user_id).first()
        
        like_count = db.query(models.CommentLike).filter(
            models.CommentLike.comment_id == reply.id
        ).count()
        
        user_liked = db.query(models.CommentLike).filter(
            models.CommentLike.comment_id == reply.id,
            models.CommentLike.user_id == current_user.id
        ).first() is not None
        
        # Count number of replies to this reply
        reply_count = db.query(models.Comment).filter(
            models.Comment.parent_id == reply.id
        ).count()
        
        return {
            "id": reply.id,
            "content": reply.content,
            "created_at": reply.created_at,
            "updated_at": reply.updated_at,
            "user": {
                "id": user.id,
                "username": user.username,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "profile_image": user.profile_image
            },
            "likes": like_count,
            "user_liked": user_liked,
            "reply_count": reply_count,
            "has_replies": reply_count > 0
        }
    
    replies_data = [format_reply(reply) for reply in replies]
    
    # Get total for pagination
    total_replies = db.query(models.Comment).filter(
        models.Comment.parent_id == comment_id
    ).count()
    
    return {
        "replies": replies_data,
        "total": total_replies,
        "has_more": total_replies > skip + limit
    }

@app.post("/api/classes/{class_id}/posts/{post_id}/comments")
async def create_comment(
    class_id: int,
    post_id: int,
    comment_data: schemas.CommentCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Create a new comment on a post or reply to another comment"""
    db_class, post = _ensure_post_access(db, current_user, class_id, post_id)
    if db_class.status != "active":
        raise HTTPException(status_code=409, detail="This class is not active")
    
    # Check if this is a reply to another comment
    parent_id = comment_data.parent_id
    if parent_id:
        # Verify parent comment exists
        parent_comment = db.query(models.Comment).filter(
            models.Comment.id == parent_id,
            models.Comment.blog_id == post_id
        ).first()
        
        if not parent_comment:
            raise HTTPException(status_code=404, detail="Parent comment not found")
    
    # Create the comment
    new_comment = models.Comment(
        content=comment_data.content,
        user_id=current_user.id,
        blog_id=post_id,
        parent_id=parent_id
    )
    
    db.add(new_comment)
    db.commit()
    db.refresh(new_comment)
    
    # Return the created comment with user info
    user = db.query(models.User).filter(models.User.id == current_user.id).first()
    
    return {
        "id": new_comment.id,
        "content": new_comment.content,
        "created_at": new_comment.created_at,
        "updated_at": new_comment.updated_at,
        "user": {
            "id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "profile_image": user.profile_image
        },
        "parent_id": parent_id,
        "likes": 0,
        "user_liked": False,
        "replies": []
    }

@app.post("/api/comments/{comment_id}/like")
async def like_comment(
    comment_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Like or unlike a comment"""
    db_class, _post, comment = _ensure_comment_access(db, current_user, comment_id)
    if db_class.status != "active":
        raise HTTPException(status_code=409, detail="This class is not active")
    
    # Check if the user already liked this comment
    existing_like = db.query(models.CommentLike).filter(
        models.CommentLike.comment_id == comment_id,
        models.CommentLike.user_id == current_user.id
    ).first()
    
    if existing_like:
        # Unlike - remove the like
        db.delete(existing_like)
        action = "unliked"
    else:
        # Like - add a new like
        new_like = models.CommentLike(
            comment_id=comment_id,
            user_id=current_user.id
        )
        db.add(new_like)
        action = "liked"
    
    db.commit()
    
    # Get updated like count
    like_count = db.query(models.CommentLike).filter(
        models.CommentLike.comment_id == comment_id
    ).count()
    
    return {
        "action": action,
        "comment_id": comment_id,
        "like_count": like_count
    }

@app.get("/api/classes/{class_id}/students")
async def get_class_students(
    class_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Get all students enrolled in a class"""
    db_class = _ensure_class_access(db, current_user, class_id)
    can_view_private_roster = _is_admin_role(current_user.role) or _teacher_owns_class(
        db,
        current_user,
        db_class,
    )
    
    # Get all enrollments for this class
    enrollments = db.query(models.ClassEnrollment).filter(
        models.ClassEnrollment.class_id == class_id
    ).all()
    
    # Get student details for each enrollment
    students = []
    for enrollment in enrollments:
        student = db.query(models.User).filter(models.User.id == enrollment.student_id).first()
        if student:
            # Count posts by this student in this class
            post_count = db.query(models.Blog).filter(
                models.Blog.owner_id == student.id,
                models.Blog.class_id == class_id
            ).count()
            
            student_data = {
                "id": student.id,
                "username": student.username,
                "first_name": student.first_name,
                "last_name": student.last_name,
                "profile_image": student.profile_image,
                "posts_count": post_count,
            }
            if can_view_private_roster:
                student_data.update(
                    {
                        "email": student.email,
                        "created_at": student.created_at,
                    }
                )
            students.append(student_data)
    
    return students

@app.get("/api/uploads/{file_path:path}")
async def get_uploaded_file(
    file_path: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Serve only registered objects after a database-derived ACL decision."""
    try:
        storage_key = canonical_object_key(f"/api/uploads/{file_path}")
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid upload path",
        ) from exc

    asset = (
        db.query(models.UploadAsset)
        .filter(models.UploadAsset.storage_key == storage_key)
        .first()
    )
    if asset is None or not _can_read_upload_asset(db, current_user, asset):
        raise HTTPException(status_code=404, detail="File not found")

    opened_object = await run_in_threadpool(
        open_verified_registered_object,
        UPLOAD_DIR,
        storage_key=storage_key,
        size_bytes=asset.size_bytes,
        sha256_digest=asset.sha256_digest,
    )
    if opened_object is None:
        raise HTTPException(status_code=404, detail="File not found")
    return _safe_upload_file_response(
        opened_object,
        Path(storage_key),
        requested_filename=asset.original_filename,
    )


def _can_read_upload_asset(
    db: Session,
    current_user: models.User,
    asset: models.UploadAsset,
) -> bool:
    if _is_admin_role(current_user.role):
        return asset.state in {"PENDING", "ACTIVE"}
    if asset.owner_user_id == current_user.id:
        return asset.state in {"PENDING", "ACTIVE"}
    if asset.state != "ACTIVE":
        return False
    if asset.purpose == "POST":
        blog = db.query(models.Blog).filter(models.Blog.id == asset.blog_id).first()
        if blog is None:
            return False
        db_class = db.query(models.Class).filter(models.Class.id == blog.class_id).first()
        return db_class is not None and _can_access_class(db, current_user, db_class)
    if asset.purpose not in {"PROFILE_IMAGE", "COVER_IMAGE"}:
        return False
    owner = db.query(models.User).filter(models.User.id == asset.owner_user_id).first()
    if owner is None:
        return False
    try:
        _ensure_profile_access(db, current_user, owner)
    except HTTPException:
        return False
    if asset.purpose == "PROFILE_IMAGE":
        return True
    role_value = str(getattr(owner.role, "value", owner.role)).upper()
    if role_value != models.UserRole.STUDENT.value:
        return False
    owner_settings = (
        db.query(models.UserSettings)
        .filter(models.UserSettings.user_id == owner.id)
        .first()
    )
    return owner_settings is None or owner_settings.show_profile_to_classmates

@app.delete("/api/upload/{file_path:path}")
async def delete_file(
    file_path: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Queue an unbound upload; active resources must be removed via their parent."""
    try:
        try:
            storage_key = canonical_object_key(f"/api/uploads/{file_path}")
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid upload path",
            ) from exc
        _lock_upload_owner(db, current_user.id)
        asset = (
            db.query(models.UploadAsset)
            .filter(models.UploadAsset.storage_key == storage_key)
            .with_for_update(of=models.UploadAsset)
            .first()
        )
        if asset is None or asset.owner_user_id != current_user.id:
            raise HTTPException(status_code=404, detail="File not found")
        if asset.state == "ACTIVE":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Active uploads must be removed from their resource",
            )
        if asset.state != "PENDING":
            raise HTTPException(status_code=404, detail="File not found")
        asset.state = "DELETE_PENDING"
        asset.expires_at = None
        asset.delete_after = _utc_now_aware()
        db.commit()
        return {"message": "File deletion queued"}
    except Exception as e:
        db.rollback()
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete file",
        ) from e

# Add new endpoints for archiving and deleting classes

@app.put("/api/classes/{class_id}/archive")
async def archive_class(
    class_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Archive a class (for teachers)"""
    db_class = _ensure_class_owner(db, current_user, class_id)
    
    # Update the class status
    db_class.status = "archived"
    db.commit()
    
    return {"message": "Class archived successfully"}

@app.put("/api/classes/{class_id}/restore")
async def restore_class(
    class_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Restore an archived class (for teachers)"""
    db_class = _ensure_class_owner(db, current_user, class_id)
    
    # Update the class status
    db_class.status = "active"
    db.commit()
    
    return {"message": "Class restored successfully"}

@app.delete("/api/classes/{class_id}")
async def delete_class(
    class_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Delete a class (for teachers)"""
    try:
        _lock_upload_owner(db, current_user.id)
        _ensure_class_owner(db, current_user, class_id)
        _delete_classes_with_dependencies(db, [class_id])
        db.commit()
    except Exception:
        db.rollback()
        raise
    
    return {"message": "Class deleted successfully"}

@app.get("/api/classes/{class_id}/students/{student_id}")
async def get_student_details(
    class_id: int,
    student_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Get detailed information about a student in a class"""
    db_class = _ensure_class_owner(db, current_user, class_id)
    student, enrollment = _ensure_enrolled_student(db, class_id, student_id)
    
    # Core activity counts scoped to this class.
    posts_count = db.query(models.Blog).filter(
        models.Blog.owner_id == student_id,
        models.Blog.class_id == class_id
    ).count()

    comments_count = db.query(models.Comment).join(
        models.Blog,
        models.Comment.blog_id == models.Blog.id
    ).filter(
        models.Comment.user_id == student_id,
        models.Blog.class_id == class_id
    ).count()

    likes_count = db.query(models.PostLike).join(
        models.Blog,
        models.PostLike.post_id == models.Blog.id
    ).filter(
        models.PostLike.user_id == student_id,
        models.Blog.class_id == class_id
    ).count()

    # Build a real activity feed from posts, comments, likes, and enrollment.
    post_events = db.query(models.Blog).filter(
        models.Blog.owner_id == student_id,
        models.Blog.class_id == class_id
    ).order_by(models.Blog.created_at.desc()).limit(25).all()

    comment_events = db.query(models.Comment, models.Blog).join(
        models.Blog,
        models.Comment.blog_id == models.Blog.id
    ).filter(
        models.Comment.user_id == student_id,
        models.Blog.class_id == class_id
    ).order_by(models.Comment.created_at.desc()).limit(25).all()

    like_events = db.query(models.PostLike, models.Blog).join(
        models.Blog,
        models.PostLike.post_id == models.Blog.id
    ).filter(
        models.PostLike.user_id == student_id,
        models.Blog.class_id == class_id
    ).order_by(models.PostLike.created_at.desc()).limit(25).all()

    activity_timeline = []

    enrollment_ts = enrollment.enrolled_at or student.created_at or _utc_now_naive()
    activity_timeline.append({
        "type": "enrollment",
        "title": "Joined Class",
        "description": f"Enrolled in {db_class.name}",
        "timestamp": enrollment_ts,
    })

    for post in post_events:
        post_title = post.title or "Untitled Post"
        activity_timeline.append({
            "type": "post",
            "title": "Created Post",
            "description": f"Created a new post: '{post_title}'",
            "timestamp": post.created_at,
        })

    for comment, blog in comment_events:
        target_title = blog.title if blog and blog.title else "a class post"
        activity_timeline.append({
            "type": "comment",
            "title": "Posted Comment",
            "description": f"Commented on '{target_title}'",
            "timestamp": comment.created_at,
        })

    for post_like, blog in like_events:
        target_title = blog.title if blog and blog.title else "a class post"
        activity_timeline.append({
            "type": "like",
            "title": "Liked Post",
            "description": f"Liked '{target_title}'",
            "timestamp": post_like.created_at,
        })

    activity_timeline.sort(key=lambda item: item.get("timestamp") or datetime.min, reverse=True)

    recent_activity = [
        {
            "type": item["type"],
            "description": item["description"],
            "timestamp": item["timestamp"],
        }
        for item in activity_timeline[:5]
    ]

    # Simple weighted engagement score from real interaction counts.
    engagement_points = (posts_count * 5) + (comments_count * 3) + likes_count
    engagement_score = f"{min(100, engagement_points)}%"

    # Return student details
    return {
        "id": student.id,
        "username": student.username,
        "email": student.email,
        "first_name": student.first_name,
        "last_name": student.last_name,
        "enrollment_date": enrollment_ts,
        "posts_count": posts_count,
        "comments_count": comments_count,
        "likes_count": likes_count,
        "teacher_notes": enrollment.notes if hasattr(enrollment, 'notes') else None,
        "engagement_score": engagement_score,
        "recent_activity": recent_activity,
        "activity_timeline": activity_timeline[:50],
    }

@app.get("/api/classes/{class_id}/students/{student_id}/posts")
async def get_student_class_posts(
    class_id: int,
    student_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Get posts created by a student in a class"""
    _ensure_class_owner(db, current_user, class_id)
    _ensure_enrolled_student(db, class_id, student_id)
    
    # Get the student's posts in this class
    posts = db.query(models.Blog).filter(
        models.Blog.owner_id == student_id,
        models.Blog.class_id == class_id
    ).order_by(models.Blog.created_at.desc()).all()
    
    # Format posts with additional information
    formatted_posts = []
    for post in posts:
        # Count likes
        likes_count = db.query(models.PostLike).filter(
            models.PostLike.post_id == post.id
        ).count()
        
        # Count comments
        comments_count = db.query(models.Comment).filter(
            models.Comment.blog_id == post.id
        ).count()
        
        formatted_posts.append({
            "id": post.id,
            "title": post.title,
            "content": post.content,
            "created_at": post.created_at,
            "likes": likes_count,
            "comments": comments_count,
            "ai_percentage": post.ai_percentage,
            "ai_highlighted_html": post.ai_highlighted_html,
            "ai_sentence_analysis": post.ai_sentence_analysis
        })
    
    return formatted_posts

@app.put("/api/classes/{class_id}/students/{student_id}/notes")
async def update_student_notes(
    class_id: int,
    student_id: int,
    notes_data: schemas.StudentNotesUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Update teacher notes for a student"""
    _ensure_class_owner(db, current_user, class_id)
    _student, enrollment = _ensure_enrolled_student(db, class_id, student_id)
    
    enrollment.notes = notes_data.notes
    db.commit()
    
    return {"message": "Notes updated successfully"}

class ForgotPasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr = Field(max_length=100)

class ResetPasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=15, max_length=1_024)

    @field_validator("new_password")
    @classmethod
    def validate_password_size(cls, value: str) -> str:
        return schemas.validate_password_request_bytes(value)

EMAIL_HOST = settings.email_host
EMAIL_PORT = settings.email_port
EMAIL_SMTP_TIMEOUT_SECONDS = settings.email_smtp_timeout_seconds
EMAIL_USERNAME = settings.email_username
EMAIL_PASSWORD = _secret_value(settings.email_password)
EMAIL_FROM = settings.email_from


def send_password_reset_email(email: str, token: str) -> bool:
    """Send password reset email through the shared delivery primitive."""

    return password_reset_delivery.send_password_reset_email(
        password_reset_delivery.PasswordResetEmailSettings(
            frontend_url=FRONTEND_URL,
            email_host=EMAIL_HOST,
            email_port=EMAIL_PORT,
            email_smtp_timeout_seconds=EMAIL_SMTP_TIMEOUT_SECONDS,
            email_username=EMAIL_USERNAME,
            email_password=EMAIL_PASSWORD,
            email_from=str(EMAIL_FROM) if EMAIL_FROM is not None else None,
        ),
        email,
        token,
    )


PASSWORD_RESET_PENDING = password_reset_delivery.PASSWORD_RESET_PENDING
PASSWORD_RESET_PROCESSING = password_reset_delivery.PASSWORD_RESET_PROCESSING
PASSWORD_RESET_DELIVERED = password_reset_delivery.PASSWORD_RESET_DELIVERED
PASSWORD_RESET_FAILED = password_reset_delivery.PASSWORD_RESET_FAILED
PASSWORD_RESET_COOLDOWN = timedelta(minutes=5)
PASSWORD_RESET_LIFETIME = password_reset_delivery.PASSWORD_RESET_LIFETIME


def _password_reset_token_digest(token: str) -> str:
    return password_reset_delivery.password_reset_token_digest(token)


def _password_reset_claim_digest(claim_nonce: str) -> str:
    return password_reset_delivery.password_reset_claim_digest(claim_nonce)


def _usable_password_reset_filters(raw_token: str):
    token_digest = _password_reset_token_digest(raw_token)
    return (
        models.PasswordReset.token == token_digest,
        models.PasswordReset.expires_at > _utc_now_naive(),
        models.PasswordReset.used.is_(False),
        models.PasswordReset.delivery_status == PASSWORD_RESET_DELIVERED,
    )


def _queue_password_reset(db: Session, user: models.User) -> None:
    now = _utc_now_naive()
    cooldown_start = now - PASSWORD_RESET_COOLDOWN
    queued_values = {
        models.PasswordReset.token: None,
        models.PasswordReset.created_at: now,
        models.PasswordReset.expires_at: None,
        models.PasswordReset.used: False,
        models.PasswordReset.delivery_status: PASSWORD_RESET_PENDING,
        models.PasswordReset.delivery_attempted_at: None,
        models.PasswordReset.delivery_claim_digest: None,
    }

    try:
        updated = (
            db.query(models.PasswordReset)
            .filter(
                models.PasswordReset.user_id == user.id,
                models.PasswordReset.created_at <= cooldown_start,
            )
            .update(queued_values, synchronize_session=False)
        )
        if updated:
            db.commit()
            return

        db.add(
            models.PasswordReset(
                user_id=user.id,
                token=None,
                created_at=now,
                expires_at=None,
                used=False,
                delivery_status=PASSWORD_RESET_PENDING,
            )
        )
        db.commit()
    except IntegrityError:
        # A concurrent request already inserted the single per-user queue row.
        db.rollback()
    except Exception:
        db.rollback()


def _claim_password_reset_delivery() -> tuple[int, str, str] | None:
    return password_reset_delivery.claim_password_reset_delivery(
        SessionLocal,
        claim_timeout_seconds=PASSWORD_RESET_CLAIM_TIMEOUT_SECONDS,
    )


def _complete_password_reset_delivery(
    reset_id: int,
    claim_nonce: str,
    raw_token: str,
    delivered: bool,
) -> bool:
    return password_reset_delivery.complete_password_reset_delivery(
        SessionLocal,
        reset_id,
        claim_nonce,
        raw_token,
        delivered,
    )


def _dispatch_password_reset_emails_once(batch_size: int = 100) -> None:
    password_reset_delivery.dispatch_password_reset_batch(
        batch_size=batch_size,
        claim=_claim_password_reset_delivery,
        send=send_password_reset_email,
        complete=_complete_password_reset_delivery,
    )


@app.post("/api/auth/forgot-password", status_code=status.HTTP_202_ACCEPTED)
def forgot_password(request: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """Request a password reset token"""
    generic_response = {
        "message": "If an account exists, password reset instructions will be sent."
    }
    try:
        normalized_email = normalize_email(str(request.email))
    except (TypeError, ValueError):
        return generic_response
    
    # Find user by email
    user = (
        db.query(models.User)
        .filter(
            models.User.email == normalized_email,
            models.User.disabled_at.is_(None),
        )
        .with_for_update(of=models.User)
        .first()
    )
    
    if not user:
        db.commit()
        return generic_response

    _queue_password_reset(db, user)
    
    return generic_response


def _lock_usable_password_reset_user(
    db: Session,
    *,
    password_reset_id: int,
    raw_token: str,
) -> models.User | None:
    return (
        db.query(models.User)
        .join(
            models.PasswordReset,
            models.PasswordReset.user_id == models.User.id,
        )
        .filter(
            models.PasswordReset.id == password_reset_id,
            *_usable_password_reset_filters(raw_token),
            models.User.disabled_at.is_(None),
        )
        .with_for_update(of=models.User)
        .first()
    )

@app.post("/api/auth/reset-password")
def reset_password(request: ResetPasswordRequest, db: Session = Depends(get_db)):
    """Reset a password using a valid token"""

    token = request.token
    if not token:
        raise HTTPException(status_code=400, detail="Token is required")
    
    # Find token in database
    password_reset_id = (
        db.query(models.PasswordReset.id)
        .join(models.User, models.User.id == models.PasswordReset.user_id)
        .filter(
            *_usable_password_reset_filters(request.token),
            models.User.disabled_at.is_(None),
        )
        .scalar()
    )
    
    if password_reset_id is None:
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    # End the read transaction before the deliberately expensive password hash.
    # The following conditional UPDATE is the single atomic token-consumption point.
    db.rollback()
    # Hash the new password
    hashed_password = hash_password(request.new_password)

    user = _lock_usable_password_reset_user(
        db,
        password_reset_id=password_reset_id,
        raw_token=request.token,
    )
    if user is None:
        db.rollback()
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    consumed = db.execute(
        update(models.PasswordReset)
        .where(
            models.PasswordReset.id == password_reset_id,
            models.PasswordReset.user_id == user.id,
            *_usable_password_reset_filters(request.token),
        )
        .values(used=True)
        .execution_options(synchronize_session=False)
    )
    if consumed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    user.password = hashed_password
    revoke_all_sessions(db, user_id=user.id)
    db.commit()
    
    return {"message": "Password reset successfully"}

if __name__ == "__main__":
    # The production entrypoint intentionally accepts traffic from its reverse proxy.
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)  # nosec B104
