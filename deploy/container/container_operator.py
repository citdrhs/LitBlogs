"""Interactive container operations, named distinctly from Python's operator module."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote, urlencode

APPLICATION = Path(__file__).resolve().parents[2] / "litblogs"
sys.path.insert(0, str(APPLICATION))

from operator_runtime import OperatorSettings  # noqa: E402

OPERATOR_MODULES = {"invitation": "manage_teacher_invitations", "account": "manage_accounts"}
MINIMAL_ENVIRONMENT = {
    "PATH": "/usr/local/bin:/usr/bin:/bin",
    "LANG": "C.UTF-8",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONUNBUFFERED": "1",
}


def build_operator_config(purpose: str, environment) -> dict:
    """Build only this fixed role's private config, never the web/admin settings."""
    if purpose not in OPERATOR_MODULES:
        raise ValueError("Invalid container operator purpose")
    password = environment.get(f"LITBLOGS_{purpose.upper()}_OPERATOR_PASSWORD", "")
    key = environment.get("TEACHER_INVITE_HMAC_KEY", "")
    domains = environment.get("ALLOWED_EMAIL_DOMAINS", "")
    if not password or not key or not domains.strip():
        raise ValueError("Missing container operator configuration")
    query = urlencode({"sslmode": "verify-full", "sslrootcert": "/etc/litblogs/postgres-root-ca.pem"})
    settings = OperatorSettings.model_validate({
        "purpose": purpose,
        "database_url": (
            f"postgresql+psycopg2://litblog_{purpose}_operator:{quote(password, safe='')}"
            f"@postgres.internal:5432/litblogs?{query}"
        ),
        "teacher_invite_hmac_key": key,
        "allowed_email_domains": [domain.strip() for domain in domains.split(",")],
    })
    return {
        "purpose": settings.purpose,
        "database_url": settings.database_url.get_secret_value(),
        "teacher_invite_hmac_key": settings.teacher_invite_hmac_key.get_secret_value(),
        "allowed_email_domains": list(settings.allowed_email_domains),
    }


def run_operator(purpose: str, arguments: list[str], environment) -> int:
    payload = build_operator_config(purpose, environment)
    # TemporaryFile is created privately and unlinked on POSIX. Only this open
    # descriptor is inherited; no config pathname, credential or email is an arg.
    with tempfile.TemporaryFile(mode="w+b") as config_file:
        descriptor = config_file.fileno()
        if not 3 <= descriptor <= 1024:
            raise ValueError("Invalid container operator descriptor")
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        config_file.write(json.dumps(payload).encode("utf-8"))
        config_file.flush()
        config_file.seek(0)
        child_environment = {**MINIMAL_ENVIRONMENT, "LITBLOG_OPERATOR_CONFIG_FD": str(descriptor)}
        result = subprocess.run(
            [sys.executable, "-m", OPERATOR_MODULES[purpose], *arguments],
            cwd=APPLICATION,
            env=child_environment,
            pass_fds=(descriptor,),
            check=False,
        )
        # Inherit the interactive terminal: existing private prompts and the
        # intentionally returned one-time invitation token must remain usable.
        return result.returncode


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0] not in {*OPERATOR_MODULES, "bootstrap-admin"}:
        print("container-operator: rejected", file=sys.stderr)
        return 2
    mode, command_arguments = arguments[0], arguments[1:]
    if mode == "bootstrap-admin" and command_arguments != ["--confirm-empty-install"]:
        print("container-operator: rejected", file=sys.stderr)
        return 2
    try:
        if mode == "bootstrap-admin":
            from runtime import build_environment

            environment = build_environment("web", os.environ)
            os.environ.clear()
            os.environ.update(environment)
            import bootstrap_admin

            return bootstrap_admin.main(command_arguments)
        return run_operator(mode, command_arguments, os.environ)
    except (Exception, KeyboardInterrupt):
        print("container-operator: rejected", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
