import hmac
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError
from pwdlib.hashers.argon2 import Argon2Hasher
from pwdlib.hashers.bcrypt import BcryptHasher

from config import Settings, get_settings

JWT_ALGORITHM = "HS256"
REQUIRED_ACCESS_TOKEN_CLAIMS = ("sub", "iss", "aud", "iat", "nbf", "exp", "jti")
MAX_PASSWORD_BYTES = 1024
LEGACY_BCRYPT_MAX_BYTES = 72
_BCRYPT_PREFIXES = ("$2a$", "$2b$", "$2y$")
_PASSWORD_HASH = PasswordHash((Argon2Hasher(), BcryptHasher(rounds=12)))


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def issue_access_token(
    subject: str | int,
    *,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> str:
    normalized_subject = str(subject).strip() if subject is not None else ""
    if not normalized_subject:
        raise ValueError("token subject must be nonempty")

    selected_settings = settings or get_settings()
    issued_at = _as_utc(now or utc_now()).replace(microsecond=0)
    expires_at = issued_at + timedelta(minutes=selected_settings.access_token_expire_minutes)
    payload = {
        "sub": normalized_subject,
        "iss": _required_setting(selected_settings.jwt_issuer, "JWT_ISSUER"),
        "aud": _required_setting(selected_settings.jwt_audience, "JWT_AUDIENCE"),
        "iat": issued_at,
        "nbf": issued_at,
        "exp": expires_at,
        "jti": str(uuid4()),
    }
    return jwt.encode(
        payload,
        _secret_key(selected_settings),
        algorithm=JWT_ALGORITHM,
    )


def decode_access_token(token: str, *, settings: Settings | None = None) -> dict:
    selected_settings = settings or get_settings()
    payload = jwt.decode(
        token,
        _secret_key(selected_settings),
        algorithms=[JWT_ALGORITHM],
        audience=_required_setting(selected_settings.jwt_audience, "JWT_AUDIENCE"),
        issuer=_required_setting(selected_settings.jwt_issuer, "JWT_ISSUER"),
        leeway=selected_settings.jwt_clock_skew_seconds,
        options={"require": list(REQUIRED_ACCESS_TOKEN_CLAIMS)},
    )
    for claim in ("sub", "jti"):
        value = payload.get(claim)
        if not isinstance(value, str) or not value.strip():
            raise jwt.InvalidTokenError(f"Token claim {claim!r} must be a nonempty string")
    return payload


def provisioning_code_matches(supplied: object, configured: object) -> bool:
    if not isinstance(supplied, str) or not isinstance(configured, str):
        return False
    if not supplied.strip() or not configured.strip():
        return False
    return hmac.compare_digest(supplied.encode("utf-8"), configured.encode("utf-8"))


def hash_password(password: str) -> str:
    _validated_password_bytes(password)
    return _PASSWORD_HASH.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    password_bytes = _validated_password_bytes(password)
    verification_password = _legacy_verification_password(
        password,
        password_bytes,
        password_hash,
    )
    try:
        return _PASSWORD_HASH.verify(verification_password, password_hash)
    except (TypeError, ValueError, UnknownHashError):
        return False


def verify_and_update_password(password: str, password_hash: str) -> tuple[bool, str | None]:
    password_bytes = _validated_password_bytes(password)
    verification_password = _legacy_verification_password(
        password,
        password_bytes,
        password_hash,
    )
    try:
        if verification_password is not password:
            if not _PASSWORD_HASH.verify(verification_password, password_hash):
                return False, None
            return True, _PASSWORD_HASH.hash(password)
        return _PASSWORD_HASH.verify_and_update(verification_password, password_hash)
    except (TypeError, ValueError, UnknownHashError):
        return False, None


def _validated_password_bytes(password: str) -> bytes:
    if not isinstance(password, str):
        raise TypeError("password must be a string")
    password_bytes = password.encode("utf-8")
    if len(password_bytes) > MAX_PASSWORD_BYTES:
        raise ValueError(f"password exceeds the maximum of {MAX_PASSWORD_BYTES} UTF-8 bytes")
    return password_bytes


def _legacy_verification_password(password: str, password_bytes: bytes, password_hash: str) -> str | bytes:
    if (
        isinstance(password_hash, str)
        and password_hash.startswith(_BCRYPT_PREFIXES)
        and len(password_bytes) > LEGACY_BCRYPT_MAX_BYTES
    ):
        return password_bytes[:LEGACY_BCRYPT_MAX_BYTES]
    return password


def _secret_key(settings: Settings) -> str:
    if settings.secret_key is None:
        raise RuntimeError("SECRET_KEY is required")
    return settings.secret_key.get_secret_value()


def _required_setting(value: str | None, name: str) -> str:
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("token timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)
