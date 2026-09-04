"""One-time administrator bootstrap for a reviewed empty production install."""

from __future__ import annotations

import hmac
import sys
from datetime import UTC, datetime
from getpass import getpass
from pathlib import Path
from typing import Callable, TextIO

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from pydantic import EmailStr, TypeAdapter
from sqlalchemy import insert, text

import models
from auth_security import hash_password
from config import get_settings, require_production_runtime_readiness
from identity_controls import normalize_email
from runtime_database_identity import verify_runtime_database_identity
from schemas import validate_new_password_policy

# First eight SHA-256 bytes of the public namespace "litblogs.bootstrap-admin.v1",
# interpreted as a signed bigint. The stable namespace serializes every attempt.
BOOTSTRAP_LOCK_ID = -5930309780944446322
CONFIRMATION_ARGUMENT = "--confirm-empty-install"
USERNAME_PROMPT = "Administrator username: "
EMAIL_PROMPT = "Administrator school email: "
PASSWORD_PROMPT = "Administrator password: "
PASSWORD_CONFIRMATION_PROMPT = "Confirm administrator password: "
_EMAIL_ADAPTER = TypeAdapter(EmailStr)


class _BootstrapFailure(Exception):
    """Carry only an allowlisted, non-reflective operator failure code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _verify_alembic_head(connection) -> None:
    """Compare the live transaction revision with this release's graph head."""

    config = Config(str(Path(__file__).resolve().parent / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    expected_revision = scripts.get_current_head()
    current_revision = MigrationContext.configure(connection).get_current_revision()
    if not expected_revision or current_revision != expected_revision:
        raise RuntimeError("Database schema is not at the current release head")


def _normalized_username(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("username is invalid")
    normalized = value.strip(" ")
    if not 3 <= len(normalized) <= 50:
        raise ValueError("username is invalid")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in normalized):
        raise ValueError("username is invalid")
    return normalized


def _validated_email(value: str, *, allowed_domains: tuple[str, ...]) -> str:
    normalized = normalize_email(str(_EMAIL_ADAPTER.validate_python(value)))
    if not allowed_domains or normalized.rsplit("@", 1)[-1] not in allowed_domains:
        raise ValueError("email domain is not allowed")
    return normalized


def _utc_naive(now: datetime) -> datetime:
    if not isinstance(now, datetime):
        raise TypeError("clock returned an invalid timestamp")
    if now.tzinfo is None:
        return now
    return now.astimezone(UTC).replace(tzinfo=None)


def _prompt_credentials(
    *,
    settings,
    input_fn: Callable[[str], str],
    password_fn: Callable[[str], str],
) -> tuple[str, str, str]:
    try:
        username = _normalized_username(input_fn(USERNAME_PROMPT))
        email = _validated_email(
            input_fn(EMAIL_PROMPT),
            allowed_domains=tuple(settings.allowed_email_domains),
        )
        password = password_fn(PASSWORD_PROMPT)
        confirmation = password_fn(PASSWORD_CONFIRMATION_PROMPT)
        if not isinstance(password, str) or not isinstance(confirmation, str):
            raise ValueError("password is invalid")
        validate_new_password_policy(password)
        if not hmac.compare_digest(password.encode("utf-8"), confirmation.encode("utf-8")):
            raise ValueError("password confirmation does not match")
    except (KeyboardInterrupt, EOFError):
        raise _BootstrapFailure("cancelled") from None
    except Exception:
        raise _BootstrapFailure("credentials_invalid") from None
    return username, email, password


def _select_runtime(app_settings, candidate_engine, readiness_check):
    try:
        settings = app_settings or get_settings()
        if settings.app_env != "production":
            raise ValueError("not production")
        require_production_runtime_readiness(settings)
    except Exception:
        raise _BootstrapFailure("config_invalid") from None

    if candidate_engine is None or readiness_check is None:
        try:
            from database import check_database_readiness, engine
        except Exception:
            raise _BootstrapFailure("database_unready") from None
        candidate_engine = candidate_engine or engine
        readiness_check = readiness_check or check_database_readiness

    if getattr(getattr(candidate_engine, "dialect", None), "name", None) != "postgresql":
        raise _BootstrapFailure("database_invalid")
    try:
        readiness_check(candidate_engine)
    except Exception:
        raise _BootstrapFailure("database_unready") from None
    return settings, candidate_engine


def _create_admin(
    *,
    settings,
    candidate_engine,
    identity_check: Callable,
    head_check: Callable,
    input_fn: Callable[[str], str],
    password_fn: Callable[[str], str],
    password_hasher: Callable[[str], str],
    now_fn: Callable[[], datetime],
) -> None:
    try:
        with candidate_engine.begin() as connection:
            connection.execute(
                text("SELECT pg_catalog.pg_advisory_xact_lock(:lock_id)"),
                {"lock_id": BOOTSTRAP_LOCK_ID},
            )
            connection.execute(text("LOCK TABLE public.users IN SHARE ROW EXCLUSIVE MODE"))
            try:
                identity_check(connection)
            except Exception:
                raise _BootstrapFailure("database_unready") from None
            try:
                head_check(connection)
            except Exception:
                raise _BootstrapFailure("schema_mismatch") from None

            user_count = connection.execute(text("SELECT count(*) FROM public.users")).scalar_one()
            if user_count != 0:
                raise _BootstrapFailure("users_exist")

            username, email, password = _prompt_credentials(
                settings=settings,
                input_fn=input_fn,
                password_fn=password_fn,
            )
            try:
                password_hash = password_hasher(password)
                verified_at = _utc_naive(now_fn())
            except Exception:
                raise _BootstrapFailure("creation_failed") from None
            connection.execute(
                insert(models.User),
                {
                    "username": username,
                    "email": email,
                    "password": password_hash,
                    "role": models.UserRole.ADMIN,
                    "is_admin": True,
                    "disabled_at": None,
                    "email_verified_at": verified_at,
                },
            )
    except _BootstrapFailure:
        raise
    except (KeyboardInterrupt, EOFError):
        raise _BootstrapFailure("cancelled") from None
    except Exception:
        raise _BootstrapFailure("creation_failed") from None


def run(
    *,
    app_settings=None,
    candidate_engine=None,
    readiness_check=None,
    identity_check=None,
    head_check=None,
    input_fn: Callable[[str], str] = input,
    password_fn: Callable[[str], str] = getpass,
    password_hasher=None,
    now_fn=None,
) -> None:
    """Validate the production runtime and create exactly one initial admin."""

    settings, selected_engine = _select_runtime(
        app_settings,
        candidate_engine,
        readiness_check,
    )
    _create_admin(
        settings=settings,
        candidate_engine=selected_engine,
        identity_check=identity_check or verify_runtime_database_identity,
        head_check=head_check or _verify_alembic_head,
        input_fn=input_fn,
        password_fn=password_fn,
        password_hasher=password_hasher or hash_password,
        now_fn=now_fn or (lambda: datetime.now(UTC)),
    )


def main(
    argv: list[str] | None = None,
    *,
    app_settings=None,
    candidate_engine=None,
    readiness_check=None,
    identity_check=None,
    head_check=None,
    input_fn: Callable[[str], str] = input,
    password_fn: Callable[[str], str] = getpass,
    password_hasher=None,
    now_fn=None,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    """Accept one fixed confirmation flag and emit only bounded status lines."""

    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments != [CONFIRMATION_ARGUMENT]:
        stderr.write("bootstrap-admin: failed code=arguments_invalid\n")
        return 1
    try:
        run(
            app_settings=app_settings,
            candidate_engine=candidate_engine,
            readiness_check=readiness_check,
            identity_check=identity_check,
            head_check=head_check,
            input_fn=input_fn,
            password_fn=password_fn,
            password_hasher=password_hasher,
            now_fn=now_fn,
        )
    except _BootstrapFailure as failure:
        stderr.write(f"bootstrap-admin: failed code={failure.code}\n")
        return 1
    except (KeyboardInterrupt, EOFError):
        stderr.write("bootstrap-admin: failed code=cancelled\n")
        return 1
    except Exception:
        stderr.write("bootstrap-admin: failed code=creation_failed\n")
        return 1

    stdout.write("bootstrap-admin: created\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
