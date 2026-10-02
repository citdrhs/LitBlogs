"""Translate deployment settings into a least-privilege production process."""

import os
import sys
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit

from pydantic import ValidationError

APPLICATION = Path(__file__).resolve().parents[2] / "litblogs"
sys.path.insert(0, str(APPLICATION))

from config import _canonical_https_origin, validate_app_base_path  # noqa: E402

# Diagnostics contain only reviewed constants, never exception text, input, or
# validation context. A model-level error may otherwise include its entire env.
_SETTING_NAMES = frozenset({
    "LITBLOGS_ORIGIN", "LITBLOGS_BASE_PATH", "LITBLOGS_DB_PASSWORD", "DATABASE_URL",
    "APP_ENV", "APP_BASE_PATH", "SECRET_KEY", "TEACHER_INVITE_HMAC_KEY",
    "ALLOWED_EMAIL_DOMAINS", "ALLOWED_HOSTS", "FRONTEND_URL", "BASE_URL",
    "JWT_ISSUER", "JWT_AUDIENCE", "CORS_ALLOWED_ORIGINS", "EMAIL_HOST", "EMAIL_PORT",
    "EMAIL_USERNAME", "EMAIL_PASSWORD", "EMAIL_FROM", "GOOGLE_OAUTH_ENABLED",
    "GOOGLE_CLIENT_ID", "MICROSOFT_OAUTH_ENABLED", "SESSION_COOKIE_NAME",
    "CSRF_COOKIE_NAME", "SESSION_COOKIE_SECURE", "UPLOAD_ROOT", "UPLOAD_SCANNER_HOST",
    "UPLOAD_SCANNER_ALLOWED_HOSTS", "UPLOAD_REGISTRY_SCHEMA_READY",
    "UPLOAD_LEGACY_IMPORT_COMPLETE", "UPLOAD_BACKUP_RESTORE_VERIFIED",
})
_SAFE_FIELDS = {name.lower(): name for name in _SETTING_NAMES}
_SAFE_ERROR_CODES = frozenset({
    "missing", "value_error", "bool_parsing", "bool_type", "int_parsing", "int_type",
    "float_parsing", "float_type", "finite_number", "greater_than_equal",
    "less_than_equal", "string_type", "string_too_short", "string_too_long",
    "path_type",
})
_SAFE_REQUIREMENTS = frozenset({
    "LITBLOGS_ORIGIN must be a root HTTPS origin",
    "APP_BASE_PATH must be empty or canonical path segments without a trailing slash",
    "SECRET_KEY must contain at least 32 bytes in production",
    "SECRET_KEY must not be a placeholder in production",
    "SECRET_KEY must be randomly generated in production",
    "TEACHER_INVITE_HMAC_KEY must contain at least 32 bytes in production",
    "TEACHER_INVITE_HMAC_KEY must be randomly generated in production",
    "TEACHER_INVITE_HMAC_KEY must differ from SECRET_KEY",
    "EMAIL_PASSWORD must contain at least 12 bytes in production",
    "EMAIL_PASSWORD must contain at least 16 bytes in production",
    "EMAIL_PASSWORD must not be a placeholder in production",
    "EMAIL_PASSWORD must be a non-placeholder secret",
    "EMAIL_PORT must use STARTTLS; implicit TLS port 465 is unsupported",
    "EMAIL_HOST must be an exact DNS hostname or IP address in production",
    "EMAIL_HOST must be an exact network host",
    "EMAIL_FROM must not use a reserved example domain in production",
    "EMAIL_FROM must use a non-reserved DNS domain",
    "DATABASE_URL must use PostgreSQL in production",
    "DATABASE_URL must use PostgreSQL with sslmode=verify-full and no target overrides",
    "DATABASE_URL must be a verified PostgreSQL URL",
    "DATABASE_URL must use the litblogs_runtime role",
    "ALLOWED_EMAIL_DOMAINS must contain valid DNS domains in production",
    "ALLOWED_HOSTS must contain exact DNS hostnames in production",
    "ALLOWED_HOSTS must include the FRONTEND_URL hostname",
    "FRONTEND_URL must use HTTPS with its path equal to APP_BASE_PATH",
    "FRONTEND_URL must use the root HTTPS origin in production",
    "FRONTEND_URL must be a root HTTPS origin",
    "CORS_ALLOWED_ORIGINS must contain explicit HTTPS origins in production",
    "CORS_ALLOWED_ORIGINS must include the FRONTEND_URL origin",
    "UPLOAD_SCANNER_HOST is required when upload scanning is required",
    "UPLOAD_SCANNER_HOST must identify a local or private service",
    "UPLOAD_SCANNER_ALLOWED_HOSTS must include UPLOAD_SCANNER_HOST",
    "UPLOAD_ROOT must be /var/lib/litblogs/uploads in production",
    "UPLOAD_ROOT custody validation failed",
    "authentication flags must be literal true or false",
    "worker setting must be nonempty",
}).union(
    f"Required container setting is missing or invalid: {name}" for name in _SETTING_NAMES
).union(
    f"Missing required production setting: {name}" for name in _SETTING_NAMES
).union(
    f"Missing production readiness attestation: {name}"
    for name in ("UPLOAD_REGISTRY_SCHEMA_READY", "UPLOAD_LEGACY_IMPORT_COMPLETE", "UPLOAD_BACKUP_RESTORE_VERIFIED")
)
_SAFE_MESSAGES = {f"Value error, {requirement}": requirement for requirement in _SAFE_REQUIREMENTS}


def report_configuration_failure(error):
    print("Configuration validation failed", file=sys.stderr)
    if isinstance(error, ValidationError):
        for detail in error.errors(include_input=False, include_context=False, include_url=False)[:8]:
            location = detail["loc"]
            field = _SAFE_FIELDS.get(location[0], "settings") if location else "settings"
            code = detail["type"] if detail["type"] in _SAFE_ERROR_CODES else "invalid"
            print(f"  {field}: {code}", file=sys.stderr)
            requirement = _SAFE_MESSAGES.get(detail["msg"])
            if requirement:
                print(f"  {requirement}", file=sys.stderr)
    elif isinstance(error, ValueError) and error.args:
        requirement = error.args[0]
        if isinstance(requirement, str) and requirement in _SAFE_REQUIREMENTS:
            print(f"  {requirement}", file=sys.stderr)


def required(environment, key):
    value = environment.get(key, "")
    if not value or "\x00" in value:
        raise ValueError(f"Required container setting is missing or invalid: {key}")
    return value


def build_environment(mode, environment):
    if mode not in {"web", "email", "reconcile"}:
        raise ValueError("Unknown container mode")
    origin = _canonical_https_origin(environment.get("LITBLOGS_ORIGIN", ""))
    if origin is None:
        raise ValueError("LITBLOGS_ORIGIN must be a root HTTPS origin")
    base_path = validate_app_base_path(environment.get("LITBLOGS_BASE_PATH", ""))
    password = required(environment, "LITBLOGS_DB_PASSWORD")
    query = urlencode({"sslmode": "verify-full", "sslrootcert": "/etc/litblogs/postgres-root-ca.pem"})
    # Never pass inherited administrative secrets, loader paths, or shell startup files.
    result = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "APP_ENV": "production",
        "DATABASE_URL": f"postgresql+psycopg2://litblogs_runtime:{quote(password, safe='')}@postgres.internal:5432/litblogs?{query}",
        "APP_BASE_PATH": base_path,
        "FRONTEND_URL": f"{origin}{base_path}",
        "LITBLOGS_ORIGIN": origin,
        "EMAIL_PORT": environment.get("EMAIL_PORT", "587"),
    }
    for key in ("EMAIL_HOST", "EMAIL_USERNAME", "EMAIL_PASSWORD", "EMAIL_FROM"):
        result[key] = required(environment, key)
    if mode == "email":
        return result
    result.update({
        "BASE_URL": origin,
        "JWT_ISSUER": origin,
        "JWT_AUDIENCE": "litblogs-students",
        "CORS_ALLOWED_ORIGINS": origin,
        "ALLOWED_HOSTS": urlsplit(origin).hostname,
        "LOCAL_PASSWORD_REGISTRATION_ENABLED": "true",
        "GOOGLE_OAUTH_ENABLED": environment.get("GOOGLE_OAUTH_ENABLED", "false"),
        "MICROSOFT_OAUTH_ENABLED": "false",
        "SESSION_COOKIE_NAME": "__Secure-litblogs-session" if base_path else "__Host-litblogs-session",
        "CSRF_COOKIE_NAME": "__Secure-litblogs-csrf" if base_path else "__Host-litblogs-csrf",
        "SESSION_COOKIE_SECURE": "true",
        "API_DOCS_ENABLED": "false",
        "RESET_DATABASE_ON_STARTUP": "false",
        "PUSH_NOTIFICATIONS_ENABLED": "false",
        "PASSWORD_RESET_WORKER_ENABLED": "true",
        "UPLOAD_ROOT": "/var/lib/litblogs/uploads",
        "UPLOAD_SCANNER_REQUIRED": "true",
        "UPLOAD_SCANNER_HOST": "clamav",
        "UPLOAD_SCANNER_ALLOWED_HOSTS": "clamav",
        "UPLOAD_SCANNER_PORT": "3310",
        "UPLOAD_SCANNER_TIMEOUT_SECONDS": "30",
        # Compose waits for the current schema migration. The other two assertions
        # are operator-owned evidence, not automatically invented by a container.
        "UPLOAD_REGISTRY_SCHEMA_READY": "true",
        "UPLOAD_LEGACY_IMPORT_COMPLETE": environment.get("UPLOAD_LEGACY_IMPORT_COMPLETE", "false"),
        "UPLOAD_BACKUP_RESTORE_VERIFIED": environment.get("UPLOAD_BACKUP_RESTORE_VERIFIED", "false"),
    })
    for key in ("SECRET_KEY", "TEACHER_INVITE_HMAC_KEY", "ALLOWED_EMAIL_DOMAINS"):
        result[key] = required(environment, key)
    if result["GOOGLE_OAUTH_ENABLED"] == "true":
        result["GOOGLE_CLIENT_ID"] = required(environment, "GOOGLE_CLIENT_ID")
    return result


def main():
    arguments = sys.argv[1:]
    if (
        len(arguments) not in {1, 2}
        or arguments[0] not in {"web", "email", "reconcile"}
        or (len(arguments) == 2 and arguments[1] != "--check")
    ):
        print("Usage: runtime.py {web|email|reconcile} [--check]", file=sys.stderr)
        return 1
    mode = arguments[0]
    check_only = len(arguments) == 2
    try:
        environment = build_environment(mode, os.environ)
        os.environ.clear()
        os.environ.update(environment)
        if mode == "email":
            from auth_email_delivery import AuthEmailWorkerSettings

            AuthEmailWorkerSettings(_env_file=None)
        else:
            from config import Settings, require_production_runtime_readiness

            require_production_runtime_readiness(Settings(_env_file=None))
    except Exception as error:
        report_configuration_failure(error)
        return 1
    if check_only:
        return 0
    os.chdir(APPLICATION)
    if mode == "web":
        command = [
            # Only this container port is routed; Compose binds the host to loopback.
            sys.executable, "-m", "uvicorn", "container_app:app", "--host", "0.0.0.0",  # nosec B104
            "--port", "5000", "--workers", "2", "--no-access-log", "--no-proxy-headers",
            "--log-config", str(APPLICATION.parent / "deploy/logging.json"),
        ]
    else:
        command = [sys.executable, str(Path(__file__).with_name("worker.py")), mode]
    os.execve(sys.executable, command, environment)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
