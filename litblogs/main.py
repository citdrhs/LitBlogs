# main.py
# To run locally run:
# uvicorn main:app --reload --host 0.0.0.0 --port 8000 &
import hashlib
import json
import os
import random
import re
import secrets
import shutil
import smtplib
import ssl
import string
import threading
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from ipaddress import ip_address
from pathlib import Path
from typing import List, Literal
from urllib.parse import urlsplit

import bleach
import uvicorn
from bleach.css_sanitizer import CSSSanitizer
from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import OAuth2PasswordBearer
from fastapi.staticfiles import StaticFiles
from google.oauth2 import id_token
from jwt.exceptions import InvalidTokenError
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from sqlalchemy import and_, or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import models
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
    provisioning_code_matches,
    verify_and_update_password,
)
from config import get_settings
from database import SessionLocal, get_db, initialize_database, reset_database
from oauth_security import verify_google_id_token, verify_microsoft_id_token

settings = get_settings()


def _utc_now_naive() -> datetime:
    """Return UTC as a naive datetime for the app's existing database columns."""
    return datetime.now(UTC).replace(tzinfo=None)

try:
    from pywebpush import WebPushException, webpush
except Exception:
    webpush = None
    WebPushException = Exception

def _should_reset_database_on_startup() -> bool:
    return settings.reset_database_on_startup

def _secret_value(value) -> str | None:
    return value.get_secret_value() if value is not None else None

FRONTEND_URL = (settings.frontend_url or "https://drhscit.org/dren").rstrip("/")
CORS_ALLOWED_ORIGINS = list(settings.cors_allowed_origins)
VAPID_PUBLIC_KEY = settings.vapid_public_key
VAPID_PRIVATE_KEY = settings.vapid_private_key.get_secret_value() if settings.vapid_private_key else ""
VAPID_SUBJECT = settings.vapid_subject
WEB_PUSH_ENABLED = bool(VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY and webpush)
PUSH_REMINDER_INTERVAL_SECONDS = settings.push_reminder_interval_seconds
PUSH_ALLOWED_ENDPOINT_HOSTS = settings.push_allowed_endpoint_hosts
PUSH_DELIVERY_TIMEOUT_SECONDS = settings.push_delivery_timeout_seconds
PASSWORD_RESET_WORKER_ENABLED = settings.password_reset_worker_enabled
PASSWORD_RESET_WORKER_INTERVAL_SECONDS = settings.password_reset_worker_interval_seconds
PASSWORD_RESET_CLAIM_TIMEOUT_SECONDS = settings.password_reset_claim_timeout_seconds

_push_scheduler_stop_event = threading.Event()
_push_scheduler_thread: threading.Thread | None = None
_password_reset_worker_stop_event = threading.Event()
_password_reset_worker_thread: threading.Thread | None = None

if "*" in CORS_ALLOWED_ORIGINS:
    raise RuntimeError("CORS_ALLOWED_ORIGINS must not contain a wildcard when credentials are enabled")

@asynccontextmanager
async def lifespan(app: FastAPI):
    if _should_reset_database_on_startup():
        reset_database()
        print("RESET_DATABASE_ON_STARTUP is enabled. Database was reset on startup.")
    else:
        initialize_database()

    _start_push_scheduler()
    _start_password_reset_worker()
    try:
        yield
    finally:
        _stop_password_reset_worker()
        _stop_push_scheduler()

app = FastAPI(lifespan=lifespan)

OAUTH_AUTH_PATHS = frozenset(
    {
        "/api/auth/google-login",
        "/api/auth/google-signup",
        "/api/auth/microsoft-login",
        "/api/auth/microsoft-signup",
    }
)
GOOGLE_IDENTITY_ISSUER = "https://accounts.google.com"


@app.exception_handler(RequestValidationError)
async def safe_oauth_request_validation_error(request: Request, exc: RequestValidationError):
    if request.url.path in OAUTH_AUTH_PATHS:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "External authentication failed"},
        )
    return await request_validation_exception_handler(request, exc)

# Fix CORS middleware setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"

def _sanitize_filename(filename: str | None, fallback: str = "upload") -> str:
    clean_name = Path(filename or fallback).name
    if not clean_name or clean_name in {".", ".."}:
        clean_name = fallback
    return re.sub(r"[^A-Za-z0-9._-]", "_", clean_name)

def _build_unique_filename(filename: str | None, prefix: str | None = None) -> str:
    safe_name = _sanitize_filename(filename)
    stem = Path(safe_name).stem or "upload"
    suffix = Path(safe_name).suffix
    timestamp = _utc_now_naive().strftime("%Y%m%d%H%M%S")
    random_str = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
    name_parts = [part for part in [prefix, timestamp, random_str, stem] if part]
    return f"{'_'.join(name_parts)}{suffix}"

def _upload_path(*parts: str) -> Path:
    return UPLOAD_DIR.joinpath(*parts)

def _upload_url(*parts: str) -> str:
    normalized_parts = [str(part).replace("\\", "/").strip("/") for part in parts if str(part).strip("/")]
    return f"/uploads/{'/'.join(normalized_parts)}"

def _resolve_upload_bucket(file: UploadFile) -> str:
    content_type = (file.content_type or "").lower()
    extension = Path(file.filename or "").suffix.lower()

    image_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg"}
    video_exts = {".mp4", ".webm", ".ogg", ".mov", ".m4v", ".avi", ".mkv"}

    if content_type.startswith("image/") or extension in image_exts:
        return "images"
    if content_type.startswith("video/") or extension in video_exts:
        return "videos"
    return "files"

def _is_pdf_upload(file: UploadFile) -> bool:
    content_type = (file.content_type or "").lower()
    extension = Path(file.filename or "").suffix.lower()
    return content_type == "application/pdf" or extension == ".pdf"

def _is_allowed_video_upload(file: UploadFile) -> bool:
    content_type = (file.content_type or "").lower()
    extension = Path(file.filename or "").suffix.lower()

    allowed_mime_types = {
        "video/mp4",
        "video/webm",
        "video/ogg",
        "video/x-msvideo",
        "video/x-matroska",
        "video/x-m4v",
    }
    allowed_extensions = {".mp4", ".webm", ".ogg", ".m4v", ".avi", ".mkv"}

    return content_type in allowed_mime_types or extension in allowed_extensions

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

    # Login performs an exact lookup against an already-validated stored address.
    # A bounded string preserves synthetic/reserved-domain test and recovery accounts.
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=1_024)


class SessionMetadataResponse(BaseModel):
    user_id: int
    username: str
    first_name: str | None = None
    last_name: str | None = None
    role: str
    is_admin: bool


class OAuthLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idToken: str = Field(min_length=1, max_length=16_384)


class OAuthSignupRequest(OAuthLoginRequest):
    role: str | None = Field(default=None, max_length=16)
    accessCode: str | None = Field(default=None, max_length=256)


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
        "url": "/class-feed",
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

def _dispatch_assignment_push_reminders_once() -> None:
    if not WEB_PUSH_ENABLED:
        return

    db = SessionLocal()
    try:
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
                .filter(models.Assignment.class_id.in_(class_ids))
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
    except Exception:
        print("Push reminder dispatcher failed")
    finally:
        db.close()

def _push_scheduler_loop() -> None:
    while not _push_scheduler_stop_event.is_set():
        _dispatch_assignment_push_reminders_once()
        _push_scheduler_stop_event.wait(PUSH_REMINDER_INTERVAL_SECONDS)

def _start_push_scheduler() -> None:
    global _push_scheduler_thread
    if _push_scheduler_thread and _push_scheduler_thread.is_alive():
        return

    _push_scheduler_stop_event.clear()
    _push_scheduler_thread = threading.Thread(target=_push_scheduler_loop, name="push-reminder-scheduler", daemon=True)
    _push_scheduler_thread.start()

def _stop_push_scheduler() -> None:
    global _push_scheduler_thread
    _push_scheduler_stop_event.set()
    if _push_scheduler_thread and _push_scheduler_thread.is_alive():
        _push_scheduler_thread.join(timeout=2)
    _push_scheduler_thread = None

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


def _set_browser_session(response: Response, user: models.User) -> None:
    max_age = settings.access_token_expire_minutes * 60
    cookie_options = {
        "max_age": max_age,
        "path": "/",
        "secure": settings.session_cookie_secure,
        "samesite": "strict",
    }
    response.set_cookie(
        _session_cookie_name(),
        create_access_token(data={"sub": str(user.id)}),
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
    if db.query(models.User).filter(models.User.email == email).first() is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="External authentication failed",
        )

    user = models.User(
        username=f"oauth-{secrets.token_hex(12)}",
        email=email,
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
        db.commit()
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
    db.refresh(user)
    return user


@app.post("/api/auth/register", response_model=SessionMetadataResponse)
async def register(
    user_data: schemas.UserCreate,
    response: Response,
    db: Session = Depends(get_db),
):
    """Register a new user"""
    # Check if email already exists
    existing_user = db.query(models.User).filter(models.User.email == user_data.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # Validate role
    try:
        role = models.UserRole[user_data.role]
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid role"
        ) from exc

    if role == models.UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid role",
        )

    # Public registration may provision teachers only with the configured code.
    if role == models.UserRole.TEACHER:
        if not user_data.access_code:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{role.name.lower()} access code is required"
            )
        
        # Verify the access code
        if role == models.UserRole.TEACHER and not provisioning_code_matches(
            user_data.access_code,
            _secret_value(settings.teacher_access_code),
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid teacher access code"
            )
    
    # Hash the password
    hashed_password = hash_password(user_data.password)
    
    # Create new user
    new_user = models.User(
        username=user_data.username,
        email=user_data.email,
        password=hashed_password,
        first_name=user_data.first_name,
        last_name=user_data.last_name,
        role=role,
        is_admin=False,
    )
    
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    _set_browser_session(response, new_user)
    return _session_metadata(new_user)

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

    if cookie_token and request.method.upper() in UNSAFE_HTTP_METHODS:
        if not csrf_token_matches(
            request.headers.get(CSRF_HEADER_NAME),
            request.cookies.get(_csrf_cookie_name()),
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="CSRF validation failed",
            )
    
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if user is None:
        raise credentials_exception
    return user

@app.get("/api/auth/session", response_model=SessionMetadataResponse)
async def get_browser_session(current_user: models.User = Depends(get_current_user)):
    return _session_metadata(current_user)


@app.post("/api/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    current_user: models.User = Depends(get_current_user),
):
    del current_user
    _clear_browser_session(response)


@app.post("/api/auth/login", response_model=SessionMetadataResponse)
async def login(
    login_data: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    user = db.query(models.User).filter(models.User.email == login_data.email).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Invalid email or password"
        )
    
    # Check if this is a social login account by trying to verify password
    # If password verification fails, it might be a social account
    verified_password_hash = user.password
    password_valid, upgraded_password_hash = verify_and_update_password(
        login_data.password,
        verified_password_hash,
    )
    if not password_valid:
        # Check if this user signed up with either Google or Microsoft
        # Since we don't have the ID fields, we need to rely on other signals
        # One approach is to tell users to use social login if password is invalid
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Invalid email or password. If you signed up with Google or Microsoft, please use those login methods."
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
    
    _set_browser_session(response, user)
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
            _set_browser_session(response, user)
            return _session_metadata(user)

        selected_role = (token_data.role or "STUDENT").upper()
        access_code = token_data.accessCode

        if selected_role not in {"STUDENT", "TEACHER"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid role",
            )
        if selected_role == "TEACHER" and not provisioning_code_matches(
            access_code,
            _secret_value(settings.teacher_access_code),
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid teacher access code",
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

        _set_browser_session(response, user)
        return _session_metadata(user)

    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="External authentication failed",
        ) from exc
    except Exception as exc:
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
        
        _set_browser_session(response, user)
        return _session_metadata(user)
        
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="External authentication failed",
        ) from exc
    except Exception as exc:
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
        
        _set_browser_session(response, user)
        return _session_metadata(user)
        
    except HTTPException:
        raise
    except Exception as exc:
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
            _set_browser_session(response, existing_user)
            return _session_metadata(existing_user)

        role = (microsoft_data.role or "STUDENT").upper()
        access_code = microsoft_data.accessCode

        if role not in {"STUDENT", "TEACHER"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid role",
            )
        if role == "TEACHER" and not provisioning_code_matches(
            access_code,
            _secret_value(settings.teacher_access_code),
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid teacher access code",
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

        _set_browser_session(response, user)
        return _session_metadata(user)
        
    except HTTPException:
        raise
    except Exception as exc:
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

def sanitize_html(content: str) -> str:
    # Define allowed tags and attributes
    ALLOWED_TAGS = [
        'p', 'div', 'span', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
        'strong', 'em', 'u', 'strike', 'br', 'ul', 'ol', 'li',
        'blockquote', 'pre', 'code', 'hr', 'a', 'img', 'table',
        'thead', 'tbody', 'tr', 'th', 'td', 'style', 'b', 'i', 's',
        'font', 'mark', 'del'
    ]
    
    ALLOWED_ATTRIBUTES = {
        '*': ['class', 'style', 'id', 'data-mce-style'],
        'a': ['href', 'title', 'target'],
        'img': ['src', 'alt', 'title'],
        'td': ['colspan', 'rowspan'],
        'th': ['colspan', 'rowspan', 'scope'],
        'font': ['color', 'size', 'face'],
        'p': ['align', 'style'],
        'div': ['align', 'style'],
        'span': ['style'],
        'h1': ['style'],
        'h2': ['style'],
        'h3': ['style'],
        'h4': ['style'],
        'h5': ['style'],
        'h6': ['style']
    }
    
    # Define allowed CSS properties
    ALLOWED_STYLES = [
        'color', 'background-color', 'font-size', 'text-align', 
        'font-family', 'font-weight', 'font-style', 'text-decoration'
    ]
    
    # Create a CSS sanitizer with allowed styles
    css_sanitizer = CSSSanitizer(allowed_css_properties=ALLOWED_STYLES)
    
    # Create a Bleach cleaner with the allowed tags, attributes, and CSS sanitizer
    cleaner = bleach.Cleaner(
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        css_sanitizer=css_sanitizer,
        strip=False  # Don't strip tags that aren't in the whitelist
    )
    
    # Sanitize the content
    sanitized_content = cleaner.clean(content)
    
    return sanitized_content

def _build_post_content(post: schemas.BlogCreate) -> str:
    content = sanitize_html(post.content)

    if post.code_snippets:
        for snippet in post.code_snippets:
            content += f"\n[CODE:{snippet.language}]{snippet.code}\n"

    if post.media:
        for media in post.media:
            if media.type == 'gif':
                content += f"\n[GIF:{media.url}]\n"
            elif media.type == 'image':
                content += f"\n[IMAGE:{media.url}]\n"

    if post.polls:
        for poll in post.polls:
            options = ','.join(poll.options)
            content += f"\n[POLL:{options}]\n"

    if post.files:
        for file in post.files:
            content += f"\n[FILE:{file.name}|{file.url}]\n"

    return content


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
    db_class = _ensure_active_class_access(db, current_user, class_id)
    
    content = _build_post_content(post)
    
    # Create new post with processed content
    new_post = models.Blog(
        title=post.title,
        content=content,
        owner_id=current_user.id,
        class_id=class_id
    )
    
    db.add(new_post)
    db.commit()
    db.refresh(new_post)
    
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

@app.get("/api/users")
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

# Create upload directories if they don't exist
UPLOAD_DIR.mkdir(exist_ok=True)
(UPLOAD_DIR / "images").mkdir(exist_ok=True)
(UPLOAD_DIR / "videos").mkdir(exist_ok=True)
(UPLOAD_DIR / "files").mkdir(exist_ok=True)
(UPLOAD_DIR / "profile_images").mkdir(exist_ok=True)
(UPLOAD_DIR / "cover_images").mkdir(exist_ok=True)

# Add these new endpoints
@app.post("/api/upload/image")
async def upload_image(file: UploadFile = File(...), current_user: models.User = Depends(get_current_user)):
    try:
        filename = _build_unique_filename(file.filename, "image")
        file_path = _upload_path("images", filename)
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        return {"url": _upload_url("images", filename)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

@app.post("/api/upload/video")
async def upload_video(file: UploadFile = File(...), current_user: models.User = Depends(get_current_user)):
    try:
        if not _is_allowed_video_upload(file):
            raise HTTPException(status_code=400, detail="Unsupported video type. MOV is not allowed.")

        filename = _build_unique_filename(file.filename, "video")
        file_path = _upload_path("videos", filename)
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        return {"url": _upload_url("videos", filename)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

@app.post("/api/upload/file")
async def upload_file(file: UploadFile = File(...), current_user: models.User = Depends(get_current_user)):
    try:
        if not _is_pdf_upload(file):
            raise HTTPException(status_code=400, detail="Only PDF files are allowed")

        filename = _build_unique_filename(file.filename, "file")
        file_path = _upload_path("files", filename)
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        return {"url": _upload_url("files", filename)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

@app.post("/api/upload")
async def upload_generic_file(
    file: UploadFile = File(...),
    current_user: models.User = Depends(get_current_user)
):
    """Upload a file and return its URL"""
    try:
        bucket = _resolve_upload_bucket(file)
        if bucket == "files" and not _is_pdf_upload(file):
            raise HTTPException(status_code=400, detail="Only PDF files are allowed")
        if bucket == "videos" and not _is_allowed_video_upload(file):
            raise HTTPException(status_code=400, detail="Unsupported video type. MOV is not allowed.")

        user_dir = _upload_path(bucket, str(current_user.id))
        user_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate a unique filename
        filename = _build_unique_filename(file.filename)
        
        # Save the file
        file_path = user_dir / filename
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # Return the file URL
        file_url = _upload_url(bucket, str(current_user.id), filename)
        
        return {
            "url": file_url,
            "filename": file.filename,
            "size": os.path.getsize(file_path)
        }
    except Exception as e:
        print(f"File upload error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload file: {str(e)}"
        ) from e

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
        # Find the teacher record for this user
        teacher = db.query(models.Teacher).filter(
            models.Teacher.email == current_user.email
        ).first()
        
        if not teacher:
            # Create a teacher record if it doesn't exist
            teacher = models.Teacher(
                name=f"{current_user.first_name} {current_user.last_name}",
                email=current_user.email,
                user_id=current_user.id
            )
            db.add(teacher)
            db.commit()
            db.refresh(teacher)
        
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

@app.get("/api/classes/{class_id}/assignments")
async def list_assignments(
    class_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    _ensure_class_access(db, current_user, class_id)
    assignments = db.query(models.Assignment).filter(
        models.Assignment.class_id == class_id
    ).order_by(models.Assignment.due_date.asc()).all()

    total_students = _get_class_student_count(db, class_id)
    response = []

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

        response.append({
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
                "updated_at": draft.updated_at
            } if draft and draft.content else None
        })

    return response

@app.get("/api/assignments/{assignment_id}/draft")
async def get_assignment_draft(
    assignment_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if current_user.role != models.UserRole.STUDENT:
        raise HTTPException(status_code=403, detail="Only students can access assignment drafts")

    assignment = db.query(models.Assignment).filter(models.Assignment.id == assignment_id).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    _ensure_class_access(db, current_user, assignment.class_id)

    draft = db.query(models.AssignmentDraft).filter(
        models.AssignmentDraft.assignment_id == assignment_id,
        models.AssignmentDraft.student_id == current_user.id
    ).first()

    return {
        "content": draft.content if draft and draft.content else "",
        "saved_at": draft.updated_at if draft and draft.content else None,
        "has_draft": bool(draft and draft.content)
    }

@app.put("/api/assignments/{assignment_id}/draft")
async def save_assignment_draft(
    assignment_id: int,
    payload: schemas.AssignmentDraftUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if current_user.role != models.UserRole.STUDENT:
        raise HTTPException(status_code=403, detail="Only students can save assignment drafts")

    assignment = db.query(models.Assignment).filter(models.Assignment.id == assignment_id).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    _ensure_active_class_access(db, current_user, assignment.class_id)

    draft = db.query(models.AssignmentDraft).filter(
        models.AssignmentDraft.assignment_id == assignment_id,
        models.AssignmentDraft.student_id == current_user.id
    ).first()

    content = payload.content if payload.content is not None else ""
    if content == "":
        if draft:
            db.delete(draft)
            db.commit()
        return {
            "content": "",
            "saved_at": None,
            "has_draft": False
        }

    if not draft:
        draft = models.AssignmentDraft(
            assignment_id=assignment_id,
            student_id=current_user.id,
            content=content
        )
        db.add(draft)
    else:
        draft.content = content

    draft.updated_at = _utc_now_naive()
    db.commit()
    db.refresh(draft)

    return {
        "content": draft.content,
        "saved_at": draft.updated_at,
        "has_draft": True
    }

@app.post("/api/assignments/{assignment_id}/submit")
async def submit_assignment(
    assignment_id: int,
    submission: schemas.AssignmentSubmissionCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if current_user.role != models.UserRole.STUDENT:
        raise HTTPException(status_code=403, detail="Only students can submit assignments")

    assignment = db.query(models.Assignment).filter(models.Assignment.id == assignment_id).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    _ensure_active_class_access(db, current_user, assignment.class_id)

    draft = db.query(models.AssignmentDraft).filter(
        models.AssignmentDraft.assignment_id == assignment_id,
        models.AssignmentDraft.student_id == current_user.id
    ).first()

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
        if draft:
            db.delete(draft)
        db.commit()
        db.refresh(existing)
        
        return {
            "id": existing.id,
            "assignment_id": existing.assignment_id,
            "student_id": existing.student_id,
            "submitted_at": existing.submitted_at,
            "content": existing.content,
            "is_late": existing.is_late,
            "ai_percentage": existing.ai_percentage,
            "ai_highlighted_html": existing.ai_highlighted_html,
            "ai_sentence_analysis": existing.ai_sentence_analysis
        }

    new_submission = models.AssignmentSubmission(
        assignment_id=assignment_id,
        student_id=current_user.id,
        submitted_at=submitted_at,
        content=submission.content,
        is_late=is_late
    )
    db.add(new_submission)
    if draft:
        db.delete(draft)
    db.commit()
    db.refresh(new_submission)
    
    return {
        "id": new_submission.id,
        "assignment_id": new_submission.assignment_id,
        "student_id": new_submission.student_id,
        "submitted_at": new_submission.submitted_at,
        "content": new_submission.content,
        "is_late": new_submission.is_late,
        "ai_percentage": new_submission.ai_percentage,
        "ai_highlighted_html": new_submission.ai_highlighted_html,
        "ai_sentence_analysis": new_submission.ai_sentence_analysis
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
    db_class, db_post = _ensure_post_access(db, current_user, class_id, post_id)
    _ensure_class_is_active(db_class)
    if not _can_moderate_post(db, current_user, db_class, db_post):
        raise HTTPException(status_code=403, detail="Not authorized to edit this post")
    
    # Update the post - make sure title and content are both updated
    db_post.title = post.title
    db_post.content = _build_post_content(post)
    db_post.updated_at = _utc_now_naive()
    
    db.commit()
    db.refresh(db_post)
    
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
    db_class, post = _ensure_post_access(db, current_user, class_id, post_id)
    _ensure_class_is_active(db_class)
    if not _can_moderate_post(db, current_user, db_class, post):
        raise HTTPException(status_code=403, detail="Not authorized to delete this post")
    
    # Delete the post
    db.delete(post)
    db.commit()
    
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
        # Get the user from database
        user = db.query(models.User).filter(models.User.id == current_user.id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        for field_name, value in profile_data.model_dump(exclude_unset=True).items():
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
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update profile") from e

@app.post("/api/user/upload-profile-image")
async def upload_profile_image(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Upload profile image"""
    try:
        upload_dir = _upload_path("profile_images")
        upload_dir.mkdir(parents=True, exist_ok=True)
        unique_filename = _build_unique_filename(file.filename, f"profile_{current_user.id}")
        file_path = upload_dir / unique_filename
        
        # Save file
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # Update user record in database
        user = db.query(models.User).filter(models.User.id == current_user.id).first()
        user.profile_image = _upload_url("profile_images", unique_filename)
        db.commit()
        db.refresh(user)
        
        return {"image_url": user.profile_image}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to upload image: {str(e)}") from e

@app.post("/api/user/upload-cover-image")
async def upload_cover_image(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Upload cover image"""
    try:
        upload_dir = _upload_path("cover_images")
        upload_dir.mkdir(parents=True, exist_ok=True)
        unique_filename = _build_unique_filename(file.filename, f"cover_{current_user.id}")
        file_path = upload_dir / unique_filename
        
        # Save file
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # Update user record in database
        user = db.query(models.User).filter(models.User.id == current_user.id).first()
        user.cover_image = _upload_url("cover_images", unique_filename)
        db.commit()
        db.refresh(user)
        
        return {"image_url": user.cover_image}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to upload image: {str(e)}") from e

def _collect_ids(query) -> List[int]:
    return [record_id for (record_id,) in query.all()]

def _delete_blogs_with_dependencies(db: Session, blog_ids: List[int]) -> None:
    if not blog_ids:
        return

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
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Delete the currently authenticated user account and related data."""
    if confirm.strip().upper() != "DELETE":
        raise HTTPException(status_code=400, detail="Confirmation must be DELETE")

    user = db.query(models.User).filter(models.User.id == current_user.id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        _delete_user_dependencies(db, user)
        db.delete(user)
        db.commit()
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

# Add this after creating the app
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

@app.get("/api/uploads/{file_path:path}")
async def get_uploaded_file(
    file_path: str,
    current_user: models.User = Depends(get_current_user),
):
    """Serve uploaded files with compatibility for both legacy and bucketed paths."""
    del current_user
    normalized_path = file_path.replace("\\", "/").lstrip("/")

    # 1) Exact path hit (works for /api/uploads/images/<user>/<file> and legacy /api/uploads/<user>/<file>)
    direct_path = _upload_path(normalized_path)
    if direct_path.exists() and direct_path.is_file():
        return FileResponse(path=direct_path)

    parts = [part for part in normalized_path.split("/") if part]

    # 2) Legacy URL fallback: /api/uploads/<user>/<file> -> search bucketed locations
    if len(parts) >= 2 and parts[0].isdigit():
        user_id = parts[0]
        trailing_parts = parts[1:]
        for bucket in ("images", "videos", "files"):
            candidate = _upload_path(bucket, user_id, *trailing_parts)
            if candidate.exists() and candidate.is_file():
                return FileResponse(path=candidate)

    # 3) Bucketed URL fallback: /api/uploads/<bucket>/<user>/<file> -> legacy location
    if len(parts) >= 3 and parts[0] in {"images", "videos", "files"} and parts[1].isdigit():
        user_id = parts[1]
        trailing_parts = parts[2:]
        legacy_candidate = _upload_path(user_id, *trailing_parts)
        if legacy_candidate.exists() and legacy_candidate.is_file():
            return FileResponse(path=legacy_candidate)

    # 4) Filename fallback: if paths changed, try locating the same filename anywhere under uploads.
    if parts:
        target_name = Path(parts[-1]).name
        if target_name:
            for candidate in UPLOAD_DIR.rglob(target_name):
                if candidate.is_file():
                    return FileResponse(path=candidate)

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"File not found: {normalized_path}"
    )

@app.delete("/api/upload/{file_path:path}")
async def delete_file(
    file_path: str,
    current_user: models.User = Depends(get_current_user)
):
    """Delete an uploaded file"""
    try:
        # Ensure the file belongs to the current user.
        # Supports both legacy uploads/<user_id>/... and new uploads/<bucket>/<user_id>/... layouts.
        user_dir = f"{current_user.id}"
        allowed_prefixes = {
            user_dir,
            f"images/{user_dir}",
            f"videos/{user_dir}",
            f"files/{user_dir}",
        }
        normalized_path = file_path.replace("\\", "/").lstrip("/")
        if not any(normalized_path.startswith(prefix) for prefix in allowed_prefixes):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to delete this file"
            )
        
        # Construct the full file path
        full_path = _upload_path(file_path)
        
        # Check if file exists
        if not full_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="File not found"
            )
        
        # Delete the file
        full_path.unlink()
        
        return {"message": "File deleted successfully"}
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        print(f"File deletion error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete file: {str(e)}"
        ) from e

@app.get("/api/download")
async def download_file(
    url: str,
    filename: str,
    current_user: models.User = Depends(get_current_user)
):
    """Force download a file with the specified filename"""
    try:        
        # Extract the file path from the URL.
        # Supports both /uploads/... and /api/uploads/... forms.
        upload_match = re.search(r"(?:/api)?/uploads/(.+)$", url)
        if upload_match:
            file_path = upload_match.group(1)
        elif url.startswith('/uploads/'):
            file_path = url[9:]
        elif url.startswith('/api/uploads/'):
            file_path = url[13:]
        elif url.startswith('http'):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid file URL"
            )
        else:
            file_path = url
        
        # Construct the full path
        full_path = _upload_path(file_path)
        
        # Check if file exists
        if not full_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"File not found: {full_path}"
            )
        
        # Return the file as an attachment to force download
        return FileResponse(
            path=full_path,
            filename=filename,
            media_type='application/octet-stream',
            headers={"Content-Disposition": f"attachment; filename=\"{filename}\""}
        )
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        print(f"Download error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to download file: {str(e)}"
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
    _ensure_class_owner(db, current_user, class_id)
    try:
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

    email: EmailStr

class ResetPasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=15, max_length=1_024)

EMAIL_HOST = settings.email_host
EMAIL_PORT = settings.email_port
EMAIL_SMTP_TIMEOUT_SECONDS = settings.email_smtp_timeout_seconds
EMAIL_USERNAME = settings.email_username
EMAIL_PASSWORD = _secret_value(settings.email_password)
EMAIL_FROM = settings.email_from


def send_password_reset_email(email: str, token: str) -> bool:
    """Send password reset email with reset link"""
    reset_url = f"{FRONTEND_URL}/reset-password#token={token}"
    if not all([EMAIL_HOST, EMAIL_USERNAME, EMAIL_PASSWORD, EMAIL_FROM]):
        return False
    
    message = MIMEMultipart("alternative")
    message["Subject"] = "Reset Your LitBlog Password"
    message["From"] = EMAIL_FROM
    message["To"] = email
    
    # Create HTML version of the message
    html = f"""
        <html>
            <head></head>
            <body style="margin:0; padding:0; background-color:#f3f4f6;">
                <div style="max-width:640px; margin:0 auto; padding:32px 16px;">
                    <div style="background-color:#ffffff; border-radius:16px; padding:32px; font-family: Arial, sans-serif; color:#111827; box-shadow:0 10px 30px rgba(0,0,0,0.08);">
                        <div style="text-align:center; margin-bottom:24px;">
                            <h1 style="margin:0; font-size:24px; font-weight:700;">Reset your LitBlog password</h1>
                            <p style="margin:8px 0 0; color:#6b7280; font-size:14px;">We received a request to reset your password.</p>
                        </div>
                        <p style="font-size:16px; line-height:1.6; margin:0 0 24px;">
                            Click the button below to set a new password. This link will expire in <strong>1 hour</strong>.
                        </p>
                        <div style="text-align:center; margin:24px 0;">
                            <a href="{reset_url}" style="display:inline-block; background-color:#4F46E5; color:#ffffff; text-decoration:none; padding:12px 24px; border-radius:999px; font-weight:600;">Reset Password</a>
                        </div>
                        <p style="font-size:14px; color:#6b7280; line-height:1.6; margin:0 0 16px;">
                            If you didn't request a password reset, you can safely ignore this email.
                        </p>
                        <div style="background-color:#f9fafb; border-radius:12px; padding:16px; font-size:12px; color:#6b7280;">
                            Having trouble with the button? Copy and paste this link into your browser:<br />
                            <span style="word-break:break-all; color:#4F46E5;">{reset_url}</span>
                        </div>
                    </div>
                    <p style="text-align:center; color:#9ca3af; font-size:12px; margin-top:16px;">&copy; {_utc_now_naive().year} LitBlog</p>
                </div>
            </body>
        </html>
        """
    
    # Attach HTML part
    part = MIMEText(html, "html")
    message.attach(part)
    
    # Send email
    try:
        with smtplib.SMTP(
            EMAIL_HOST,
            EMAIL_PORT,
            timeout=EMAIL_SMTP_TIMEOUT_SECONDS,
        ) as server:
            server.starttls(context=ssl.create_default_context())
            server.login(EMAIL_USERNAME, EMAIL_PASSWORD)
            server.sendmail(EMAIL_FROM, email, message.as_string())
        return True
    except Exception:
        return False


PASSWORD_RESET_PENDING = "PENDING"
PASSWORD_RESET_PROCESSING = "PROCESSING"
PASSWORD_RESET_DELIVERED = "DELIVERED"
PASSWORD_RESET_FAILED = "FAILED"
PASSWORD_RESET_COOLDOWN = timedelta(minutes=5)
PASSWORD_RESET_LIFETIME = timedelta(hours=1)


def _password_reset_token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _usable_password_reset_filters(raw_token: str):
    token_digest = _password_reset_token_digest(raw_token)
    return (
        or_(
            models.PasswordReset.token == token_digest,
            # Preserve outstanding links created before the digest migration.
            models.PasswordReset.token == raw_token,
        ),
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


def _claim_password_reset_delivery() -> tuple[int, str] | None:
    db = SessionLocal()
    try:
        now = _utc_now_naive()
        stale_before = now - timedelta(seconds=PASSWORD_RESET_CLAIM_TIMEOUT_SECONDS)
        claimable = or_(
            models.PasswordReset.delivery_status == PASSWORD_RESET_PENDING,
            and_(
                models.PasswordReset.delivery_status == PASSWORD_RESET_PROCESSING,
                or_(
                    models.PasswordReset.delivery_attempted_at.is_(None),
                    models.PasswordReset.delivery_attempted_at <= stale_before,
                ),
            ),
        )
        candidate_ids = [
            reset_id
            for (reset_id,) in (
                db.query(models.PasswordReset.id)
                .filter(claimable)
                .order_by(models.PasswordReset.created_at, models.PasswordReset.id)
                .limit(25)
                .all()
            )
        ]

        for reset_id in candidate_ids:
            claimed = (
                db.query(models.PasswordReset)
                .filter(models.PasswordReset.id == reset_id, claimable)
                .update(
                    {
                        models.PasswordReset.delivery_status: PASSWORD_RESET_PROCESSING,
                        models.PasswordReset.delivery_attempted_at: now,
                    },
                    synchronize_session=False,
                )
            )
            if not claimed:
                db.rollback()
                continue

            db.commit()
            reset_request = (
                db.query(models.PasswordReset)
                .filter(models.PasswordReset.id == reset_id)
                .first()
            )
            if reset_request is None:
                return None
            user = db.query(models.User).filter(models.User.id == reset_request.user_id).first()
            if user is None:
                reset_request.delivery_status = PASSWORD_RESET_FAILED
                reset_request.token = None
                reset_request.expires_at = None
                db.commit()
                continue
            return reset_request.id, user.email
        return None
    except Exception:
        db.rollback()
        return None
    finally:
        db.close()


def _complete_password_reset_delivery(reset_id: int, raw_token: str, delivered: bool) -> None:
    db = SessionLocal()
    try:
        reset_request = (
            db.query(models.PasswordReset)
            .filter(
                models.PasswordReset.id == reset_id,
                models.PasswordReset.delivery_status == PASSWORD_RESET_PROCESSING,
            )
            .first()
        )
        if reset_request is None:
            return

        if delivered:
            reset_request.token = _password_reset_token_digest(raw_token)
            reset_request.expires_at = _utc_now_naive() + PASSWORD_RESET_LIFETIME
            reset_request.delivery_status = PASSWORD_RESET_DELIVERED
        else:
            reset_request.token = None
            reset_request.expires_at = None
            reset_request.delivery_status = PASSWORD_RESET_FAILED
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def _dispatch_password_reset_emails_once(batch_size: int = 100) -> None:
    for _ in range(batch_size):
        claimed = _claim_password_reset_delivery()
        if claimed is None:
            return
        reset_id, email = claimed
        raw_token = secrets.token_urlsafe(32)
        delivered = send_password_reset_email(email, raw_token)
        _complete_password_reset_delivery(reset_id, raw_token, delivered)


def _password_reset_worker_loop() -> None:
    while not _password_reset_worker_stop_event.is_set():
        _dispatch_password_reset_emails_once()
        _password_reset_worker_stop_event.wait(PASSWORD_RESET_WORKER_INTERVAL_SECONDS)


def _start_password_reset_worker() -> None:
    global _password_reset_worker_thread
    if not PASSWORD_RESET_WORKER_ENABLED:
        return
    if _password_reset_worker_thread and _password_reset_worker_thread.is_alive():
        return

    _password_reset_worker_stop_event.clear()
    _password_reset_worker_thread = threading.Thread(
        target=_password_reset_worker_loop,
        name="password-reset-delivery-worker",
        daemon=True,
    )
    _password_reset_worker_thread.start()


def _stop_password_reset_worker() -> None:
    global _password_reset_worker_thread
    _password_reset_worker_stop_event.set()
    if _password_reset_worker_thread and _password_reset_worker_thread.is_alive():
        _password_reset_worker_thread.join(timeout=2)
    _password_reset_worker_thread = None

@app.post("/api/auth/forgot-password", status_code=status.HTTP_202_ACCEPTED)
def forgot_password(request: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """Request a password reset token"""
    generic_response = {
        "message": "If an account exists, password reset instructions will be sent."
    }
    
    # Find user by email
    user = db.query(models.User).filter(models.User.email == request.email).first()
    
    if not user:
        db.commit()
        return generic_response

    _queue_password_reset(db, user)
    
    return generic_response

@app.post("/api/auth/reset-password")
def reset_password(request: ResetPasswordRequest, db: Session = Depends(get_db)):
    """Reset a password using a valid token"""

    token = request.token
    if not token:
        raise HTTPException(status_code=400, detail="Token is required")
    
    # Find token in database
    password_reset_id = (
        db.query(models.PasswordReset.id)
        .filter(*_usable_password_reset_filters(request.token))
        .scalar()
    )
    
    if password_reset_id is None:
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    # End the read transaction before the deliberately expensive password hash.
    # The following conditional UPDATE is the single atomic token-consumption point.
    db.rollback()
    # Hash the new password
    hashed_password = hash_password(request.new_password)

    consumed_user_id = db.execute(
        update(models.PasswordReset)
        .where(
            models.PasswordReset.id == password_reset_id,
            *_usable_password_reset_filters(request.token),
        )
        .values(used=True)
        .returning(models.PasswordReset.user_id)
    ).scalar_one_or_none()
    if consumed_user_id is None:
        db.rollback()
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    user = db.query(models.User).filter(models.User.id == consumed_user_id).first()
    if user is None:
        db.rollback()
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    user.password = hashed_password
    db.commit()
    
    return {"message": "Password reset successfully"}

if __name__ == "__main__":
    # The production entrypoint intentionally accepts traffic from its reverse proxy.
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)  # nosec B104
