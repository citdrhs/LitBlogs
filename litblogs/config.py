import os
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from dotenv import dotenv_values
from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent
VALID_APP_ENVIRONMENTS = frozenset({"development", "test", "production"})
SECRET_KEY_MIN_BYTES = 32
_PLACEHOLDER_FRAGMENTS = (
    "changeme",
    "change-me",
    "placeholder",
    "replace-me",
    "replace-with",
    "replace_with",
    "test-",
    "test-only",
    "your-secret",
)


def _csv_tuple(value: Any, *, lowercase: bool = False, strip_slash: bool = False) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        values = value.split(",")
    elif isinstance(value, (list, tuple, set, frozenset)):
        values = value
    else:
        raise ValueError("value must be a comma-separated string or sequence")

    normalized = []
    for item in values:
        text = str(item).strip()
        if strip_slash:
            text = text.rstrip("/")
        if lowercase:
            text = text.lower()
        if text and text not in normalized:
            normalized.append(text)
    return tuple(normalized)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        case_sensitive=False,
        enable_decoding=False,
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
        hide_input_in_errors=True,
    )

    app_env: str = "development"
    database_url: str | None = None
    secret_key: SecretStr | None = None
    jwt_issuer: str | None = None
    jwt_audience: str | None = None
    jwt_clock_skew_seconds: int = Field(default=5, ge=0, le=60)
    access_token_expire_minutes: int = Field(default=30, ge=1, le=60)

    frontend_url: str | None = None
    base_url: str | None = None
    cors_allowed_origins: tuple[str, ...] = ()
    allowed_email_domains: tuple[str, ...] = ()
    microsoft_allowed_tenant_ids: tuple[str, ...] = ()

    google_client_id: str | None = None
    microsoft_client_id: str | None = None
    microsoft_client_secret: SecretStr | None = None
    microsoft_tenant_id: str | None = None
    microsoft_redirect_uri: str | None = None

    session_cookie_name: str | None = None
    csrf_cookie_name: str | None = None
    session_cookie_secure: bool = False

    teacher_access_code: SecretStr | None = None
    admin_access_code: SecretStr | None = None
    admin_code: SecretStr | None = None

    reset_database_on_startup: bool = False
    vapid_public_key: str = ""
    vapid_private_key: SecretStr | None = None
    vapid_subject: str = "mailto:admin@litblogs.local"
    push_reminder_interval_seconds: int = Field(default=300, ge=60, le=86_400)
    email_host: str | None = None
    email_port: int = Field(default=587, ge=1, le=65_535)
    email_username: str | None = None
    email_password: SecretStr | None = None
    email_from: str | None = None

    @field_validator("app_env", mode="before")
    @classmethod
    def normalize_app_env(cls, value: Any) -> str:
        normalized = str(value or "development").strip().lower()
        if normalized not in VALID_APP_ENVIRONMENTS:
            allowed = ", ".join(sorted(VALID_APP_ENVIRONMENTS))
            raise ValueError(f"APP_ENV must be one of: {allowed}")
        return normalized

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def normalize_origins(cls, value: Any) -> tuple[str, ...]:
        return _csv_tuple(value, strip_slash=True)

    @field_validator("allowed_email_domains", "microsoft_allowed_tenant_ids", mode="before")
    @classmethod
    def normalize_lowercase_csv(cls, value: Any) -> tuple[str, ...]:
        return _csv_tuple(value, lowercase=True)

    @field_validator(
        "database_url",
        "jwt_issuer",
        "jwt_audience",
        "frontend_url",
        "base_url",
        "google_client_id",
        "microsoft_client_id",
        "microsoft_tenant_id",
        "microsoft_redirect_uri",
        "session_cookie_name",
        "csrf_cookie_name",
        "email_host",
        "email_username",
        "email_from",
        mode="before",
    )
    @classmethod
    def strip_optional_text(cls, value: Any) -> Any:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_production_safety(self):
        if self.app_env != "production":
            return self

        secret = self.secret_key.get_secret_value() if self.secret_key else ""
        if len(secret.encode("utf-8")) < SECRET_KEY_MIN_BYTES:
            raise ValueError("SECRET_KEY must contain at least 32 bytes in production")
        lowered_secret = secret.lower()
        if any(fragment in lowered_secret for fragment in _PLACEHOLDER_FRAGMENTS):
            raise ValueError("SECRET_KEY must not be a placeholder in production")
        if len(set(secret)) < 12:
            raise ValueError("SECRET_KEY must be randomly generated in production")

        required = {
            "DATABASE_URL": self.database_url,
            "JWT_ISSUER": self.jwt_issuer,
            "JWT_AUDIENCE": self.jwt_audience,
            "FRONTEND_URL": self.frontend_url,
            "CORS_ALLOWED_ORIGINS": self.cors_allowed_origins,
            "GOOGLE_CLIENT_ID": self.google_client_id,
            "MICROSOFT_CLIENT_ID": self.microsoft_client_id,
            "MICROSOFT_CLIENT_SECRET": self.microsoft_client_secret,
            "MICROSOFT_TENANT_ID": self.microsoft_tenant_id,
            "SESSION_COOKIE_NAME": self.session_cookie_name,
            "CSRF_COOKIE_NAME": self.csrf_cookie_name,
            "TEACHER_ACCESS_CODE": self.teacher_access_code,
            "ADMIN_ACCESS_CODE": self.admin_access_code,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(f"Missing required production setting: {missing[0]}")

        placeholder_checked = {
            "JWT_ISSUER": self.jwt_issuer,
            "JWT_AUDIENCE": self.jwt_audience,
            "GOOGLE_CLIENT_ID": self.google_client_id,
            "MICROSOFT_CLIENT_ID": self.microsoft_client_id,
            "MICROSOFT_CLIENT_SECRET": _reveal_secret(self.microsoft_client_secret),
            "MICROSOFT_TENANT_ID": self.microsoft_tenant_id,
            "SESSION_COOKIE_NAME": self.session_cookie_name,
            "CSRF_COOKIE_NAME": self.csrf_cookie_name,
            "TEACHER_ACCESS_CODE": _reveal_secret(self.teacher_access_code),
            "ADMIN_ACCESS_CODE": _reveal_secret(self.admin_access_code),
        }
        if self.admin_code is not None:
            placeholder_checked["ADMIN_CODE"] = _reveal_secret(self.admin_code)
        for name, value in placeholder_checked.items():
            if any(fragment in str(value).lower() for fragment in _PLACEHOLDER_FRAGMENTS):
                raise ValueError(f"{name} must not be a placeholder in production")

        minimum_lengths = {
            "GOOGLE_CLIENT_ID": (self.google_client_id, 8),
            "MICROSOFT_CLIENT_ID": (self.microsoft_client_id, 8),
            "MICROSOFT_CLIENT_SECRET": (_reveal_secret(self.microsoft_client_secret), 16),
            "MICROSOFT_TENANT_ID": (self.microsoft_tenant_id, 8),
            "TEACHER_ACCESS_CODE": (_reveal_secret(self.teacher_access_code), 16),
            "ADMIN_ACCESS_CODE": (_reveal_secret(self.admin_access_code), 16),
        }
        if self.admin_code is not None:
            minimum_lengths["ADMIN_CODE"] = (_reveal_secret(self.admin_code), 16)
        for name, (value, minimum_bytes) in minimum_lengths.items():
            if len(str(value).encode("utf-8")) < minimum_bytes:
                raise ValueError(f"{name} must contain at least {minimum_bytes} bytes in production")

        if not self.session_cookie_secure:
            raise ValueError("SESSION_COOKIE_SECURE must be true in production")
        if not _is_https_url(self.frontend_url):
            raise ValueError("FRONTEND_URL must use HTTPS in production")
        if any(origin == "*" or not _is_https_origin(origin) for origin in self.cors_allowed_origins):
            raise ValueError("CORS_ALLOWED_ORIGINS must contain explicit HTTPS origins in production")
        return self


def _is_https_url(value: str | None) -> bool:
    parsed = urlsplit(value or "")
    return parsed.scheme == "https" and bool(parsed.netloc)


def _reveal_secret(value: SecretStr | None) -> str:
    return value.get_secret_value() if value else ""


def _is_https_origin(value: str) -> bool:
    parsed = urlsplit(value)
    return parsed.scheme == "https" and bool(parsed.netloc) and not parsed.path.rstrip("/")


def _selected_app_env(base_dir: Path) -> str:
    process_value = os.getenv("APP_ENV")
    if process_value is not None:
        raw_value = process_value
    else:
        raw_value = dotenv_values(base_dir / ".env").get("APP_ENV", "development")
    normalized = str(raw_value or "development").strip().lower()
    if normalized not in VALID_APP_ENVIRONMENTS:
        allowed = ", ".join(sorted(VALID_APP_ENVIRONMENTS))
        raise ValueError(f"APP_ENV must be one of: {allowed}")
    return normalized


def load_settings(*, base_dir: Path | str = BASE_DIR) -> Settings:
    resolved_base_dir = Path(base_dir).resolve()
    app_env = _selected_app_env(resolved_base_dir)
    env_files = tuple(
        path
        for path in (
            resolved_base_dir / ".env",
            resolved_base_dir / f".env.{app_env}",
        )
        if path.exists()
    )
    return Settings(
        app_env=app_env,
        _env_file=env_files or None,
        _env_file_encoding="utf-8",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
