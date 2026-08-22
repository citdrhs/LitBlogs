import argparse
import hashlib
import secrets
import sys
from datetime import timedelta
from getpass import getpass
from typing import Callable, TextIO

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from identity_controls import (
    invitation_email_digest,
    normalize_email,
    operator_audit_resource_digest,
    utc_now,
    validate_operator_identifier,
)
from operator_runtime import OperatorRuntime, build_operator_runtime

MIN_INVITATION_HOURS = 1
MAX_INVITATION_HOURS = 720
_EMAIL_ADAPTER = TypeAdapter(EmailStr)


class _PrivateArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        del message
        raise ValueError("invalid arguments")


def _parser() -> argparse.ArgumentParser:
    parser = _PrivateArgumentParser(
        prog="manage_teacher_invitations",
        description="Manage one-time teacher invitations from a trusted host.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("create", "revoke"):
        command_parser = commands.add_parser(command)
        command_parser.add_argument("--operator", required=True)
        if command == "create":
            command_parser.add_argument(
                "--expires-hours",
                type=int,
                required=True,
            )
    return parser


def _validated_email(value: str, *, settings) -> str:
    validated = str(_EMAIL_ADAPTER.validate_python(value))
    normalized = normalize_email(validated)
    domain = normalized.rsplit("@", 1)[1]
    if settings.allowed_email_domains and domain not in settings.allowed_email_domains:
        raise ValueError("email domain is not allowed")
    return normalized


def _read_private_email(stdin: TextIO) -> str:
    if stdin is sys.stdin and stdin.isatty():
        return getpass("Target school email: ")
    value = stdin.readline(1_025)
    if not value or len(value) > 1_024:
        raise ValueError("private email input is invalid")
    return value.rstrip("\r\n")


def execute_invitation_command(
    db: Session,
    *,
    command: str,
    token_digest: str | None,
    email_digest: str,
    expires_at,
    actor_identifier: str,
    resource_digest: str,
    email: str,
    settings,
) -> str:
    """Invoke fixed SECURITY DEFINER transitions; the role has no table DML."""

    del email, settings
    if command == "create":
        return db.execute(
            text(
                """
                SELECT public.operator_create_teacher_invitation(
                    CAST(:token_digest AS VARCHAR(64)),
                    CAST(:email_digest AS VARCHAR(64)),
                    CAST(:expires_at AS TIMESTAMPTZ),
                    CAST(:actor_identifier AS VARCHAR(100)),
                    CAST(:resource_digest AS VARCHAR(64))
                )
                """
            ),
            {
                "token_digest": token_digest,
                "email_digest": email_digest,
                "expires_at": expires_at,
                "actor_identifier": actor_identifier,
                "resource_digest": resource_digest,
            },
        ).scalar_one()
    if command == "revoke":
        return db.execute(
            text(
                """
                SELECT public.operator_revoke_teacher_invitation(
                    CAST(:email_digest AS VARCHAR(64)),
                    CAST(:actor_identifier AS VARCHAR(100)),
                    CAST(:resource_digest AS VARCHAR(64))
                )
                """
            ),
            {
                "email_digest": email_digest,
                "actor_identifier": actor_identifier,
                "resource_digest": resource_digest,
            },
        ).scalar_one()
    raise ValueError("invitation command is invalid")


def main(
    argv: list[str] | None = None,
    *,
    session_factory: Callable[[], Session] | None = None,
    settings=None,
    command_executor: Callable[..., str] | None = None,
    stdin: TextIO = sys.stdin,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    try:
        arguments = _parser().parse_args(argv)
        operator = validate_operator_identifier(arguments.operator)
        if arguments.command == "create" and not (
            MIN_INVITATION_HOURS
            <= arguments.expires_hours
            <= MAX_INVITATION_HOURS
        ):
            raise ValueError("invitation expiry is invalid")
        raw_email = _read_private_email(stdin)
    except (TypeError, ValidationError, ValueError):
        stderr.write("Invitation command rejected\n")
        return 2

    runtime: OperatorRuntime | None = None
    if (session_factory is None) != (settings is None):
        stderr.write("Invitation command rejected\n")
        return 2
    if session_factory is None:
        try:
            runtime = build_operator_runtime(expected_purpose="invitation")
        except (OSError, RuntimeError, SQLAlchemyError, ValueError):
            stderr.write("Invitation command rejected\n")
            return 2
        active_session_factory = runtime.session_factory
        active_settings = runtime.settings
    else:
        active_session_factory = session_factory
        active_settings = settings
    active_command_executor = command_executor or execute_invitation_command
    try:
        email = _validated_email(raw_email, settings=active_settings)
    except (TypeError, ValidationError, ValueError):
        if runtime is not None:
            runtime.close()
        stderr.write("Invitation command rejected\n")
        return 2

    db = None
    try:
        db = active_session_factory()
        email_digest = invitation_email_digest(email, settings=active_settings)
        resource_digest = operator_audit_resource_digest(
            email,
            settings=active_settings,
        )
        if arguments.command == "create":
            token = secrets.token_urlsafe(32)
            expires_at = utc_now() + timedelta(hours=arguments.expires_hours)
            outcome = active_command_executor(
                db,
                command="create",
                email=email,
                email_digest=email_digest,
                token_digest=hashlib.sha256(token.encode("utf-8")).hexdigest(),
                expires_at=expires_at,
                actor_identifier=operator,
                resource_digest=resource_digest,
                settings=active_settings,
            )
            if outcome not in {"SUCCEEDED", "CONFLICT"}:
                raise RuntimeError("invitation create returned an invalid outcome")
            db.commit()
            if outcome == "CONFLICT":
                stderr.write("Invitation could not be created\n")
                return 1
            stdout.write(f"{token}\n")
            stderr.write("Invitation created\n")
            return 0

        outcome = active_command_executor(
            db,
            command="revoke",
            email=email,
            email_digest=email_digest,
            token_digest=None,
            expires_at=None,
            actor_identifier=operator,
            resource_digest=resource_digest,
            settings=active_settings,
        )
        if outcome not in {"SUCCEEDED", "NOT_FOUND"}:
            raise RuntimeError("invitation revoke returned an invalid outcome")
        db.commit()
        if outcome == "NOT_FOUND":
            stderr.write("Invitation not found\n")
            return 1
        stderr.write("Invitation revoked\n")
        return 0
    except (SQLAlchemyError, RuntimeError, TypeError, ValueError):
        if db is not None:
            db.rollback()
        if arguments.command == "create":
            stderr.write("Invitation could not be created\n")
        else:
            stderr.write("Invitation not found\n")
        return 1
    finally:
        if db is not None:
            db.close()
        if runtime is not None:
            runtime.close()


if __name__ == "__main__":
    raise SystemExit(main())
