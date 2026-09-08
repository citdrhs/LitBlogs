"""Translate deployment settings into a least-privilege production process."""

import os
import sys
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit

APPLICATION = Path(__file__).resolve().parents[2] / "litblogs"
sys.path.insert(0, str(APPLICATION))

from config import _canonical_https_origin  # noqa: E402


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
        raise ValueError("LITBLOGS_ORIGIN must be a root HTTPS origin on an exclusive hostname")
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
        "FRONTEND_URL": origin,
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
        "SESSION_COOKIE_NAME": "__Host-litblogs-session",
        "CSRF_COOKIE_NAME": "__Host-litblogs-csrf",
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
    mode = sys.argv[1] if len(sys.argv) == 2 else ""
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
    except Exception:
        print("Container configuration rejected. Check required settings, storage custody, and readiness attestations; no secrets were logged.", file=sys.stderr)
        return 1
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
