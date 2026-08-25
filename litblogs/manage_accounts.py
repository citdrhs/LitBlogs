import argparse
import sys
from getpass import getpass
from typing import Callable, TextIO

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from identity_controls import (
    normalize_email,
    operator_audit_resource_digest,
    validate_operator_identifier,
)
from operator_runtime import OperatorRuntime, build_operator_runtime

_EMAIL_ADAPTER = TypeAdapter(EmailStr)


class _PrivateArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        del message
        raise ValueError("invalid arguments")


def _parser() -> argparse.ArgumentParser:
    parser = _PrivateArgumentParser(
        prog="manage_accounts",
        description="Disable or enable an account from a trusted host.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("disable", "enable"):
        command_parser = commands.add_parser(command)
        command_parser.add_argument("--operator", required=True)
    return parser


def _validated_email(value: str) -> str:
    return normalize_email(str(_EMAIL_ADAPTER.validate_python(value)))


def _read_private_email(stdin: TextIO) -> str:
    if stdin is sys.stdin and stdin.isatty():
        return getpass("Target school email: ")
    value = stdin.readline(1_025)
    if not value or len(value) > 1_024:
        raise ValueError("private email input is invalid")
    return value.rstrip("\r\n")


def execute_account_status_command(
    db: Session,
    *,
    email: str,
    disabled: bool,
    actor_identifier: str,
    resource_digest: str,
    settings,
) -> str:
    """Invoke the fixed SECURITY DEFINER boundary; the role has no table DML."""

    del settings
    return db.execute(
        text(
            """
            SELECT public.operator_set_account_status(
                CAST(:email AS VARCHAR(100)),
                CAST(:disabled AS BOOLEAN),
                CAST(:actor_identifier AS VARCHAR(100)),
                CAST(:resource_digest AS VARCHAR(64))
            )
            """
        ),
        {
            "email": email,
            "disabled": disabled,
            "actor_identifier": actor_identifier,
            "resource_digest": resource_digest,
        },
    ).scalar_one()


def main(
    argv: list[str] | None = None,
    *,
    session_factory: Callable[[], Session] | None = None,
    settings=None,
    status_executor: Callable[..., str] | None = None,
    stdin: TextIO = sys.stdin,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    del stdout
    try:
        arguments = _parser().parse_args(argv)
        operator = validate_operator_identifier(arguments.operator)
        email = _validated_email(_read_private_email(stdin))
    except (TypeError, ValidationError, ValueError):
        stderr.write("Account command rejected\n")
        return 2

    runtime: OperatorRuntime | None = None
    if (session_factory is None) != (settings is None):
        stderr.write("Account command rejected\n")
        return 2
    if session_factory is None:
        try:
            runtime = build_operator_runtime(expected_purpose="account")
        except (OSError, RuntimeError, SQLAlchemyError, ValueError):
            stderr.write("Account command rejected\n")
            return 2
        active_session_factory = runtime.session_factory
        active_settings = runtime.settings
    else:
        active_session_factory = session_factory
        active_settings = settings
    active_status_executor = status_executor or execute_account_status_command

    db = None
    try:
        db = active_session_factory()
        disabled = arguments.command == "disable"
        outcome = active_status_executor(
            db,
            actor_identifier=operator,
            disabled=disabled,
            email=email,
            resource_digest=operator_audit_resource_digest(
                email,
                settings=active_settings,
            ),
            settings=active_settings,
        )
        if outcome not in {"SUCCEEDED", "NOT_FOUND"}:
            raise RuntimeError("account status command returned an invalid outcome")
        db.commit()
        if outcome == "NOT_FOUND":
            stderr.write("Account not found\n")
            return 1
        stderr.write("Account disabled\n" if disabled else "Account enabled\n")
        return 0
    except (OSError, RuntimeError, SQLAlchemyError):
        if db is not None:
            db.rollback()
        stderr.write("Account could not be updated\n")
        return 1
    finally:
        if db is not None:
            db.close()
        if runtime is not None:
            runtime.close()


if __name__ == "__main__":
    raise SystemExit(main())
