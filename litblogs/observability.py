import json
import logging
import secrets
import time
import traceback
from pathlib import Path

from starlette.responses import JSONResponse

request_logger = logging.getLogger("litblogs.requests")
error_logger = logging.getLogger("litblogs.errors")
API_SECURITY_HEADERS = (
    (b"pragma", b"no-cache"),
    (b"referrer-policy", b"no-referrer"),
    (b"x-content-type-options", b"nosniff"),
)
DEFAULT_API_CACHE_CONTROL = b"no-store"
PRIVATE_API_CACHE_CONTROL = b"private, no-store"


class RequestObservabilityMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        request_id = _request_id_from_scope(scope) or secrets.token_hex(16)
        state = scope.setdefault("state", {})
        if isinstance(state, dict):
            state["request_id"] = request_id
        started = time.monotonic()
        response_status = 500
        response_started = False

        async def send_with_request_id(message):
            nonlocal response_started, response_status
            if message.get("type") == "http.response.start":
                response_started = True
                response_status = int(message.get("status", 500))
                original_headers = message.get("headers", [])
                enforced_headers = [(b"x-request-id", request_id.encode("ascii"))]
                if str(scope.get("path", "")).startswith("/api/"):
                    cache_control = _safe_api_cache_control(original_headers)
                    enforced_headers.append((b"cache-control", cache_control))
                    enforced_headers.extend(API_SECURITY_HEADERS)
                enforced_names = {name for name, _value in enforced_headers}
                headers = [
                    (name, value)
                    for name, value in original_headers
                    if name.lower() not in enforced_names
                ]
                headers.extend(enforced_headers)
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception as exc:
            _log_exception(request_id=request_id, exc=exc)
            _log_request(
                scope,
                request_id=request_id,
                status=500,
                duration_ms=_duration_ms(started),
                event="request_failed",
            )
            if response_started:
                raise
            response = JSONResponse(
                status_code=500,
                content={"detail": "Internal server error"},
            )
            await response(scope, receive, send_with_request_id)
            return

        _log_request(
            scope,
            request_id=request_id,
            status=response_status,
            duration_ms=_duration_ms(started),
            event="request_complete",
        )


def _safe_api_cache_control(headers) -> bytes:
    values = [value for name, value in headers if name.lower() == b"cache-control"]
    if len(values) != 1:
        return DEFAULT_API_CACHE_CONTROL
    normalized = b", ".join(
        directive.strip().lower()
        for directive in values[0].split(b",")
        if directive.strip()
    )
    if normalized == PRIVATE_API_CACHE_CONTROL:
        return PRIVATE_API_CACHE_CONTROL
    return DEFAULT_API_CACHE_CONTROL


def _duration_ms(started: float) -> int:
    return max(0, round((time.monotonic() - started) * 1_000))


def _request_id_from_scope(scope) -> str | None:
    for raw_name, raw_value in scope.get("headers", []):
        if raw_name.lower() != b"x-request-id":
            continue
        try:
            candidate = raw_value.decode("ascii")
        except UnicodeDecodeError:
            return None
        if len(candidate) == 32 and all(character in "0123456789abcdef" for character in candidate):
            return candidate
        return None
    return None


class PrivacyExceptionFilter(logging.Filter):
    """Replace fallback exception records before a formatter can expose details."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.exc_info or record.exc_text or record.stack_info:
            record.msg = json.dumps(
                {
                    "event": "server_exception_redacted",
                    "logger": record.name,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            record.args = ()
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
        return True


class PrivacyFallbackFilter(logging.Filter):
    """Replace every unapproved root-logger record with a bounded event."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = '{"event":"untrusted_logger_event_redacted"}'
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        return True


def _log_exception(*, request_id: str, exc: Exception) -> None:
    exception_type = type(exc)
    frames = traceback.extract_tb(exc.__traceback__, limit=32)
    payload = {
        "event": "request_exception",
        "exception_class": f"{exception_type.__module__}.{exception_type.__qualname__}",
        "request_id": request_id,
        "stack": [
            {
                "file": Path(frame.filename).name,
                "function": frame.name,
                "line": frame.lineno,
            }
            for frame in frames
        ],
    }
    error_logger.error(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def _log_request(scope, *, request_id: str, status: int, duration_ms: int, event: str) -> None:
    route = scope.get("route")
    route_template = getattr(route, "path", "unmatched")
    payload = {
        "duration_ms": duration_ms,
        "event": event,
        "method": str(scope.get("method", "UNKNOWN")),
        "request_id": request_id,
        "route": route_template,
        "status": status,
    }
    request_logger.info(json.dumps(payload, sort_keys=True, separators=(",", ":")))
