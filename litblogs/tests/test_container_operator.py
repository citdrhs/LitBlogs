import importlib.util
import json
import os
import secrets
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy.engine import make_url

from operator_runtime import OperatorSettings

CONTAINER_DIRECTORY = Path(__file__).resolve().parents[2] / "deploy" / "container"


@pytest.fixture
def operator_environment():
    return {
        "LITBLOGS_ORIGIN": "https://litblogs.school.edu",
        "LITBLOGS_DB_PASSWORD": secrets.token_urlsafe(48),
        "LITBLOGS_ACCOUNT_OPERATOR_PASSWORD": secrets.token_urlsafe(48) + "@:/?%+",
        "LITBLOGS_INVITATION_OPERATOR_PASSWORD": secrets.token_urlsafe(48) + "@:/?%+",
        "LITBLOGS_MIGRATOR_PASSWORD": secrets.token_urlsafe(48),
        "POSTGRES_PASSWORD": secrets.token_urlsafe(48),
        "TEACHER_INVITE_HMAC_KEY": secrets.token_urlsafe(48),
        "SECRET_KEY": secrets.token_urlsafe(48),
        "ALLOWED_EMAIL_DOMAINS": "school.example, staff.school.example",
        "EMAIL_HOST": "smtp.school.example", "EMAIL_USERNAME": "school-mailer",
        "EMAIL_PASSWORD": secrets.token_urlsafe(48), "EMAIL_FROM": "noreply@school.example",
        "UPLOAD_LEGACY_IMPORT_COMPLETE": "true", "UPLOAD_BACKUP_RESTORE_VERIFIED": "true",
        "LD_PRELOAD": "/untrusted/loader", "PYTHONPATH": "/untrusted/python", "BASH_ENV": "/untrusted/shell",
    }


def operator_payload(operator_environment, host="postgres.internal"):
    from urllib.parse import quote, urlencode

    query = urlencode({"sslmode": "verify-full", "sslrootcert": "/etc/litblogs/postgres-root-ca.pem"})
    password = quote(operator_environment["LITBLOGS_INVITATION_OPERATOR_PASSWORD"], safe="")
    return {
        "purpose": "invitation",
        "database_url": f"postgresql+psycopg2://litblog_invitation_operator:{password}@{host}:5432/litblogs?{query}",
        "teacher_invite_hmac_key": operator_environment["TEACHER_INVITE_HMAC_KEY"],
        "allowed_email_domains": ["school.example"],
    }


def test_operator_runtime_accepts_only_the_fixed_container_tls_target(operator_environment):
    settings = OperatorSettings.model_validate(operator_payload(operator_environment))
    assert make_url(settings.database_url.get_secret_value()).host == "postgres.internal"


@pytest.mark.parametrize("host", ["127.0.0.1", "postgres.internal"])
def test_operator_runtime_retains_reviewed_host_choices(operator_environment, host):
    settings = OperatorSettings.model_validate(operator_payload(operator_environment, host))
    assert make_url(settings.database_url.get_secret_value()).host == host


@pytest.mark.parametrize("host", ["localhost", "postgres", "arbitrary.school.example", "127.0.0.2", "POSTGRES.INTERNAL"])
def test_operator_runtime_still_denies_unreviewed_targets(operator_environment, host):
    with pytest.raises(ValidationError):
        OperatorSettings.model_validate(operator_payload(operator_environment, host))


@pytest.mark.parametrize(
    "replacement",
    [
        {"sslmode": "require"}, {"sslrootcert": "/untrusted/ca.pem"},
        {"hostaddr": "127.0.0.2"}, {"service": "untrusted-service"},
    ],
)
def test_container_operator_tls_cannot_be_downgraded_or_redirected(operator_environment, replacement):
    payload = operator_payload(operator_environment)
    url = make_url(payload["database_url"]).update_query_dict(replacement)
    payload["database_url"] = url.render_as_string(hide_password=False)
    with pytest.raises(ValidationError):
        OperatorSettings.model_validate(payload)


@pytest.fixture
def container_operator(monkeypatch):
    monkeypatch.syspath_prepend(str(CONTAINER_DIRECTORY))
    spec = importlib.util.spec_from_file_location("container_operator_test", CONTAINER_DIRECTORY / "container_operator.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("purpose", ["invitation", "account"])
def test_operator_config_contains_only_its_exact_role_credentials(container_operator, operator_environment, purpose):
    payload = container_operator.build_operator_config(purpose, operator_environment)
    assert set(payload) == {"purpose", "database_url", "teacher_invite_hmac_key", "allowed_email_domains"}
    settings = OperatorSettings.model_validate(payload)
    url = make_url(settings.database_url.get_secret_value())
    assert url.username == f"litblog_{purpose}_operator"
    assert url.password == operator_environment[f"LITBLOGS_{purpose.upper()}_OPERATOR_PASSWORD"]
    assert url.host == "postgres.internal"
    assert url.port == 5432
    assert url.database == "litblogs"
    assert dict(url.query) == {"sslmode": "verify-full", "sslrootcert": "/etc/litblogs/postgres-root-ca.pem"}
    assert payload["teacher_invite_hmac_key"] == operator_environment["TEACHER_INVITE_HMAC_KEY"]
    assert payload["allowed_email_domains"] == ["school.example", "staff.school.example"]
    serialized = json.dumps(payload)
    for key in ("POSTGRES_PASSWORD", "LITBLOGS_DB_PASSWORD", "LITBLOGS_MIGRATOR_PASSWORD", "SECRET_KEY", "EMAIL_PASSWORD"):
        assert operator_environment[key] not in serialized


@pytest.mark.parametrize("missing", ["LITBLOGS_INVITATION_OPERATOR_PASSWORD", "TEACHER_INVITE_HMAC_KEY", "ALLOWED_EMAIL_DOMAINS"])
def test_operator_config_requires_only_its_minimal_inputs(container_operator, operator_environment, missing):
    environment = {key: operator_environment[key] for key in (
        "LITBLOGS_INVITATION_OPERATOR_PASSWORD", "TEACHER_INVITE_HMAC_KEY", "ALLOWED_EMAIL_DOMAINS",
    )}
    assert container_operator.build_operator_config("invitation", environment)["purpose"] == "invitation"
    environment.pop(missing)
    with pytest.raises(ValueError):
        container_operator.build_operator_config("invitation", environment)


@pytest.mark.parametrize("purpose,module_name,args", [
    ("invitation", "manage_teacher_invitations", ["create", "--operator", "school-it", "--expires-hours", "24"]),
    ("account", "manage_accounts", ["disable", "--operator", "school-it"]),
])
def test_operator_child_gets_private_fd_and_minimal_environment(
    container_operator, operator_environment, purpose, module_name, args, monkeypatch,
):
    descriptors = []

    def inspect_child(command, **kwargs):
        assert command == [sys.executable, "-m", module_name, *args]
        assert kwargs["cwd"] == container_operator.APPLICATION
        assert set(kwargs["env"]) == {"PATH", "LANG", "PYTHONDONTWRITEBYTECODE", "PYTHONUNBUFFERED", "LITBLOG_OPERATOR_CONFIG_FD"}
        descriptor = int(kwargs["env"]["LITBLOG_OPERATOR_CONFIG_FD"])
        assert 3 <= descriptor <= 1024
        assert kwargs["pass_fds"] == (descriptor,)
        metadata = os.fstat(descriptor)
        assert stat.S_ISREG(metadata.st_mode)
        if os.name == "posix":
            assert stat.S_IMODE(metadata.st_mode) == 0o600
        with os.fdopen(os.dup(descriptor), "rb") as stream:
            payload = json.load(stream)
        assert payload == container_operator.build_operator_config(purpose, operator_environment)
        assert all(secret not in " ".join(command) for key, secret in operator_environment.items() if "PASSWORD" in key)
        assert "stdin" not in kwargs and "stdout" not in kwargs and "stderr" not in kwargs
        descriptors.append(descriptor)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(container_operator.subprocess, "run", inspect_child)
    assert container_operator.run_operator(purpose, args, operator_environment) == 0
    assert len(descriptors) == 1
    with pytest.raises(OSError):
        os.fstat(descriptors[0])


def test_operator_child_failure_is_returned_and_descriptor_closed(container_operator, operator_environment, monkeypatch):
    descriptors = []

    def fail_child(command, **kwargs):
        descriptors.extend(kwargs["pass_fds"])
        return subprocess.CompletedProcess(command, 2)

    monkeypatch.setattr(container_operator.subprocess, "run", fail_child)
    assert container_operator.run_operator("account", ["enable", "--operator", "school-it"], operator_environment) == 2
    with pytest.raises(OSError):
        os.fstat(descriptors[0])


@pytest.mark.parametrize("arguments", [[], ["unknown-secret"], ["bootstrap-admin"], ["bootstrap-admin", "--wrong-secret"]])
def test_operator_cli_rejects_unknown_mode_and_requires_explicit_admin_confirmation(container_operator, arguments, capsys):
    assert container_operator.main(arguments) == 2
    assert capsys.readouterr() == ("", "container-operator: rejected\n")


def test_bootstrap_uses_existing_command_after_clearing_inherited_environment(
    container_operator, operator_environment, monkeypatch,
):
    import runtime

    expected = runtime.build_environment("web", operator_environment)
    calls = []

    def bootstrap_main(arguments):
        assert dict(os.environ) == expected
        calls.append(arguments)
        return 0

    monkeypatch.setattr(os, "environ", dict(operator_environment))
    monkeypatch.setitem(sys.modules, "bootstrap_admin", SimpleNamespace(main=bootstrap_main))
    assert container_operator.main(["bootstrap-admin", "--confirm-empty-install"]) == 0
    assert calls == [["--confirm-empty-install"]]


def test_operator_wrapper_errors_do_not_expose_configuration(container_operator, operator_environment, monkeypatch, capsys):
    def fail_spawn(*args, **kwargs):
        raise OSError("secret database URL or loader path")

    monkeypatch.setattr(container_operator.subprocess, "run", fail_spawn)
    monkeypatch.setattr(os, "environ", dict(operator_environment))
    assert container_operator.main(["invitation", "create", "--operator", "school-it", "--expires-hours", "24"]) == 1
    assert capsys.readouterr() == ("", "container-operator: rejected\n")


@pytest.mark.parametrize("script,exit_code,error", [
    ("container_operator.py", 2, "container-operator: rejected\n"),
    ("worker.py", 2, "litblogs-worker: failed\n"),
    ("healthcheck.py", 1, ""),
])
def test_direct_container_cli_startup_does_not_shadow_standard_library(script, exit_code, error):
    result = subprocess.run(
        [sys.executable, str(CONTAINER_DIRECTORY / script), "invalid-mode"],
        cwd=CONTAINER_DIRECTORY.parents[1], capture_output=True, text=True, check=False, timeout=20,
    )
    assert result.returncode == exit_code
    assert result.stdout == ""
    assert result.stderr == error


@pytest.mark.skipif(os.name != "posix", reason="POSIX pass_fds inheritance is required by the production container")
def test_operator_fd_round_trip_in_a_real_isolated_child(container_operator, operator_environment, monkeypatch):
    real_run = subprocess.run

    def read_private_descriptor(_command, **kwargs):
        command = [sys.executable, "-c", (
            "import json, os; "
            "data=json.load(os.fdopen(int(os.environ['LITBLOG_OPERATOR_CONFIG_FD']))); "
            "assert set(data)=={'purpose','database_url','teacher_invite_hmac_key','allowed_email_domains'}; "
            "assert data['purpose']=='invitation'; "
            "assert 'postgres.internal:5432' in data['database_url']; "
            "assert 'DATABASE_URL' not in os.environ; "
            "assert 'POSTGRES_PASSWORD' not in os.environ"
        )]
        return real_run(command, **kwargs, capture_output=True, timeout=20)

    monkeypatch.setattr(container_operator.subprocess, "run", read_private_descriptor)
    assert container_operator.run_operator("invitation", ["create", "--operator", "school-it", "--expires-hours", "24"],
                                           operator_environment) == 0
