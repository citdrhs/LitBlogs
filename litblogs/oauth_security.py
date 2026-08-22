from __future__ import annotations

import time
from collections.abc import Callable
from functools import lru_cache
from threading import RLock
from typing import Any
from uuid import UUID

import jwt
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from config import Settings

GOOGLE_ISSUERS = frozenset({"accounts.google.com", "https://accounts.google.com"})
GOOGLE_OAUTH2_CERTS_URL = "https://www.googleapis.com/oauth2/v1/certs"
GOOGLE_CERT_FAILURE_BACKOFF_SECONDS = 1.0
MICROSOFT_JWT_ALGORITHM = "RS256"
MICROSOFT_REQUIRED_CLAIMS = (
    "iss",
    "aud",
    "tid",
    "sub",
    "email",
    "iat",
    "nbf",
    "exp",
)
MAX_ID_TOKEN_BYTES = 16_384


class OAuthVerificationError(ValueError):
    """An external identity assertion failed local trust policy."""


class _BoundedGoogleCertRequest:
    def __init__(
        self,
        *,
        cache_seconds: int,
        timeout_seconds: float,
        transport: Callable[..., Any] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._cache_seconds = cache_seconds
        self._timeout_seconds = timeout_seconds
        self._transport = transport or google_requests.Request()
        self._monotonic = monotonic
        self._lock = RLock()
        self._cached_response: tuple[float, Any] | None = None
        self._failure_expires_at: float | None = None

    def __call__(
        self,
        url: str,
        method: str = "GET",
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> Any:
        del timeout
        cacheable = method.upper() == "GET" and url == GOOGLE_OAUTH2_CERTS_URL
        with self._lock:
            now = self._monotonic()
            if cacheable and self._cached_response is not None:
                expires_at, response = self._cached_response
                if now < expires_at:
                    return response
                self._cached_response = None
            if (
                cacheable
                and self._failure_expires_at is not None
                and now < self._failure_expires_at
            ):
                raise OAuthVerificationError("Google certificate service unavailable")

            try:
                response = self._transport(
                    url,
                    method=method,
                    body=body,
                    headers=headers,
                    timeout=self._timeout_seconds,
                    **kwargs,
                )
            except Exception as exc:
                if cacheable:
                    self._failure_expires_at = (
                        self._monotonic() + GOOGLE_CERT_FAILURE_BACKOFF_SECONDS
                    )
                    raise OAuthVerificationError(
                        "Google certificate service unavailable"
                    ) from exc
                raise
            if cacheable:
                if getattr(response, "status", None) != 200:
                    self._failure_expires_at = (
                        self._monotonic() + GOOGLE_CERT_FAILURE_BACKOFF_SECONDS
                    )
                    raise OAuthVerificationError(
                        "Google certificate service unavailable"
                    )
                self._failure_expires_at = None
                self._cached_response = (
                    self._monotonic() + self._cache_seconds,
                    response,
                )
            return response


def verify_google_id_token(
    raw_token: str,
    *,
    settings: Settings,
    verifier: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    token = _validated_raw_token(raw_token)
    client_id = _required_text(settings.google_client_id)
    allowed_domains = _required_domains(settings.allowed_email_domains)
    selected_verifier = verifier or google_id_token.verify_oauth2_token
    claims = selected_verifier(
        token,
        _google_request(
            settings.oauth_jwks_cache_seconds,
            settings.oauth_http_timeout_seconds,
        ),
        client_id,
        clock_skew_in_seconds=settings.jwt_clock_skew_seconds,
    )
    if not isinstance(claims, dict):
        raise OAuthVerificationError("invalid Google claims")

    if claims.get("aud") != client_id:
        raise OAuthVerificationError("invalid Google audience")
    if claims.get("iss") not in GOOGLE_ISSUERS:
        raise OAuthVerificationError("invalid Google issuer")

    subject = _required_claim_text(claims, "sub", max_length=255)
    email = _required_claim_text(claims, "email", max_length=254).lower()
    if claims.get("email_verified") is not True:
        raise OAuthVerificationError("Google email is not verified")

    email_domain = _email_domain(email)
    hosted_domain = _required_claim_text(claims, "hd", max_length=253).lower()
    if hosted_domain != email_domain or email_domain not in allowed_domains:
        raise OAuthVerificationError("Google email domain is not allowed")

    _validate_timestamps(
        claims,
        leeway=settings.jwt_clock_skew_seconds,
        now=time.time(),
        require_nbf=False,
    )
    return {
        **claims,
        "sub": subject,
        "email": email,
    }


def verify_microsoft_id_token(
    raw_token: str,
    *,
    settings: Settings,
    jwk_client_factory: Callable[..., jwt.PyJWKClient] | None = None,
) -> dict[str, Any]:
    token = _validated_raw_token(raw_token)
    client_id = _required_text(settings.microsoft_client_id)
    tenant_id = _validated_tenant_id(settings.microsoft_tenant_id)
    trusted_tenants = _trusted_microsoft_tenants(settings, tenant_id)
    allowed_domains = _required_domains(settings.allowed_email_domains)

    header = jwt.get_unverified_header(token)
    if not isinstance(header, dict) or header.get("alg") != MICROSOFT_JWT_ALGORITHM:
        raise OAuthVerificationError("invalid Microsoft token algorithm")
    if not isinstance(header.get("kid"), str) or not header["kid"].strip():
        raise OAuthVerificationError("missing Microsoft signing key ID")

    issuer = f"https://login.microsoftonline.com/{tenant_id}/v2.0"
    jwks_url = (
        f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
    )
    if jwk_client_factory is None:
        jwk_client = _microsoft_jwk_client(
            jwks_url,
            settings.oauth_jwks_cache_seconds,
            settings.oauth_http_timeout_seconds,
        )
    else:
        jwk_client = jwk_client_factory(
            jwks_url,
            cache_keys=False,
            cache_jwk_set=True,
            lifespan=settings.oauth_jwks_cache_seconds,
            timeout=settings.oauth_http_timeout_seconds,
        )
    signing_key = jwk_client.get_signing_key_from_jwt(token).key
    claims = jwt.decode(
        token,
        signing_key,
        algorithms=[MICROSOFT_JWT_ALGORITHM],
        audience=client_id,
        issuer=issuer,
        leeway=settings.jwt_clock_skew_seconds,
        options={"require": list(MICROSOFT_REQUIRED_CLAIMS)},
    )

    if claims.get("aud") != client_id:
        raise OAuthVerificationError("invalid Microsoft audience")
    if claims.get("iss") != issuer:
        raise OAuthVerificationError("invalid Microsoft issuer")
    token_tenant = _required_claim_text(claims, "tid", max_length=36).lower()
    if token_tenant != tenant_id or token_tenant not in trusted_tenants:
        raise OAuthVerificationError("invalid Microsoft tenant")

    subject = _required_claim_text(claims, "sub", max_length=255)
    email = _required_claim_text(claims, "email", max_length=254).lower()
    if _email_domain(email) not in allowed_domains:
        raise OAuthVerificationError("Microsoft email domain is not allowed")
    _validate_timestamps(
        claims,
        leeway=settings.jwt_clock_skew_seconds,
        now=time.time(),
    )
    return {
        **claims,
        "sub": subject,
        "email": email,
    }


@lru_cache(maxsize=8)
def _google_request(
    cache_seconds: int,
    timeout_seconds: float,
) -> _BoundedGoogleCertRequest:
    return _BoundedGoogleCertRequest(
        cache_seconds=cache_seconds,
        timeout_seconds=timeout_seconds,
    )


def reset_google_request_cache() -> None:
    _google_request.cache_clear()


@lru_cache(maxsize=8)
def _microsoft_jwk_client(
    jwks_url: str,
    cache_seconds: int,
    timeout_seconds: float,
) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(
        jwks_url,
        cache_keys=False,
        cache_jwk_set=True,
        lifespan=cache_seconds,
        timeout=timeout_seconds,
    )


def reset_microsoft_jwk_client_cache() -> None:
    _microsoft_jwk_client.cache_clear()


def _validated_raw_token(raw_token: object) -> str:
    if not isinstance(raw_token, str) or not raw_token.strip():
        raise OAuthVerificationError("identity token is required")
    if len(raw_token.encode("utf-8")) > MAX_ID_TOKEN_BYTES:
        raise OAuthVerificationError("identity token is too large")
    return raw_token


def _required_text(value: str | None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OAuthVerificationError("OAuth provider is not configured")
    return value.strip()


def _required_domains(values: tuple[str, ...]) -> frozenset[str]:
    domains = frozenset(value.strip().lower() for value in values if value.strip())
    if not domains:
        raise OAuthVerificationError("OAuth email domains are not configured")
    return domains


def _validated_tenant_id(value: str | None) -> str:
    tenant_id = _required_text(value).lower()
    try:
        parsed = UUID(tenant_id)
    except ValueError as exc:
        raise OAuthVerificationError("Microsoft tenant is not configured safely") from exc
    return str(parsed)


def _trusted_microsoft_tenants(settings: Settings, configured_tenant: str) -> frozenset[str]:
    configured = frozenset(
        tenant.strip().lower()
        for tenant in settings.microsoft_allowed_tenant_ids
        if tenant.strip()
    )
    trusted = configured or frozenset({configured_tenant})
    if configured_tenant not in trusted:
        raise OAuthVerificationError("Microsoft tenant is not trusted")
    return trusted


def _required_claim_text(
    claims: dict[str, Any],
    name: str,
    *,
    max_length: int,
) -> str:
    value = claims.get(name)
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise OAuthVerificationError(f"invalid {name} claim")
    return value.strip()


def _email_domain(email: str) -> str:
    local_part, separator, domain = email.rpartition("@")
    if separator != "@" or not local_part or not domain or "@" in local_part:
        raise OAuthVerificationError("invalid email claim")
    return domain.lower()


def _validate_timestamps(
    claims: dict[str, Any],
    *,
    leeway: int,
    now: float,
    require_nbf: bool = True,
) -> None:
    timestamps = {name: _numeric_date(claims, name) for name in ("iat", "exp")}
    not_before = (
        _numeric_date(claims, "nbf")
        if require_nbf or "nbf" in claims
        else None
    )
    if timestamps["iat"] > now + leeway:
        raise OAuthVerificationError("identity token issued in the future")
    if not_before is not None and not_before > now + leeway:
        raise OAuthVerificationError("identity token is not active")
    if timestamps["exp"] <= now - leeway:
        raise OAuthVerificationError("identity token has expired")
    if timestamps["iat"] >= timestamps["exp"] or (
        not_before is not None and not_before >= timestamps["exp"]
    ):
        raise OAuthVerificationError("invalid identity token lifetime")


def _numeric_date(claims: dict[str, Any], name: str) -> float:
    value = claims.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise OAuthVerificationError(f"invalid {name} claim")
    return float(value)
