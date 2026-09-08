"""Safe orchestration checks; real Docker lifecycle is exercised separately in CI."""

import importlib.util
import os
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]


def smoke_module():
    path = ROOT / "deploy/container/smoke.py"
    assert path.is_file(), "Disposable container smoke runner is missing"
    spec = importlib.util.spec_from_file_location("container_smoke", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_smoke_environment_is_private_ephemeral_and_does_not_inherit_real_secrets(monkeypatch):
    module = smoke_module()
    monkeypatch.setenv("SECRET_KEY", "operator-secret-must-not-be-used")
    with module.private_environment("litblogs-smoke-0123456789ab", 15000) as path:
        content = path.read_text()
        assert "operator-secret-must-not-be-used" not in content
        assert "LITBLOGS_ORIGIN='https://litblogs-smoke.school.edu'" in content
        assert "EMAIL_HOST='127.0.0.1'" in content
        assert "GOOGLE_OAUTH_ENABLED='false'" in content
        assert "UPLOAD_BACKUP_RESTORE_VERIFIED='true'" in content
        assert "UPLOAD_LEGACY_IMPORT_COMPLETE='true'" in content
        assert "LITBLOGS_IMAGE_TAG='litblogs-smoke-0123456789ab'" in content
        assert "LITBLOGS_HTTP_PORT='15000'" in content
        secrets = [line.split("=", 1)[1] for line in content.splitlines() if "PASSWORD=" in line or "SECRET_KEY=" in line]
        assert len(secrets) >= 7 and len(set(secrets)) == len(secrets)
        if os.name == "posix":
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not path.exists()


@pytest.mark.parametrize("project", ["production", "litblogs-smoke-../escape", "", "litblogs-smoke-*", "--help"])
def test_runner_rejects_non_owned_project_names(project, tmp_path):
    module = smoke_module()
    with pytest.raises(module.SmokeError):
        module.SmokeSession(ROOT, project, tmp_path / "environment", 15000)


def test_child_failures_hide_secret_output_and_inherited_compose_overrides(monkeypatch, tmp_path, capsys):
    module = smoke_module()
    secret = "sensitive-child-output"
    monkeypatch.setenv("COMPOSE_FILE", "/operator/production.yml")
    monkeypatch.setenv("LITBLOGS_DB_PASSWORD", "operator-password")
    calls = []

    def run(command, **parameters):
        calls.append((command, parameters))
        return SimpleNamespace(returncode=1, stdout=secret, stderr=secret)

    session = module.SmokeSession(ROOT, "litblogs-smoke-0123456789ab", tmp_path / "environment", 15000, run=run)
    with pytest.raises(module.SmokeError) as error:
        session.compose(["up", "--detach"], stage="startup")
    assert secret not in str(error.value)
    command, parameters = calls[0]
    assert command[:2] == ["docker", "compose"]
    assert "COMPOSE_FILE" not in parameters["env"]
    assert "LITBLOGS_DB_PASSWORD" not in parameters["env"]
    assert "--env-file" in command and "--project-name" in command
    assert str(ROOT / "docker-compose.yml") in command
    assert parameters["stdout"] == subprocess.PIPE
    assert parameters["stderr"] == subprocess.PIPE
    assert secret not in capsys.readouterr().out


def test_cleanup_refuses_unclaimed_resources(tmp_path):
    module = smoke_module()
    calls = []
    session = module.SmokeSession(ROOT, "litblogs-smoke-0123456789ab", tmp_path / "environment", 15000,
                                  run=lambda *args, **kwargs: calls.append((args, kwargs)))
    session.cleanup()
    assert calls == []


def test_existing_project_collision_never_authorizes_cleanup(tmp_path):
    module = smoke_module()
    calls = []

    def run(command, **_parameters):
        calls.append(command)
        output = "linux" if "info" in command else "already-owned-resource"
        return SimpleNamespace(returncode=0, stdout=output, stderr="")

    session = module.SmokeSession(ROOT, "litblogs-smoke-0123456789ab", tmp_path / "environment", 15000, run=run)
    with pytest.raises(module.SmokeError, match="already exists"):
        session.claim()
    session.cleanup()
    assert not any("down" in command or "rm" in command for command in calls)


def test_failed_startup_cleans_only_claimed_project_and_image(tmp_path):
    module = smoke_module()
    calls = []

    def run(command, **_parameters):
        calls.append(command)
        output = "linux" if "info" in command else ""
        return SimpleNamespace(returncode=int("up" in command), stdout=output, stderr="suppressed failure")

    session = module.SmokeSession(ROOT, "litblogs-smoke-0123456789ab", tmp_path / "environment", 15000, run=run)
    with pytest.raises(module.SmokeError):
        module.run_session(session)
    cleanup = next(command for command in calls if "down" in command)
    assert "litblogs-smoke-0123456789ab" in cleanup
    assert "--volumes" in cleanup
    assert all("prune" not in command for command in calls)
    for command in calls:
        if "rm" in command:
            assert command[-1] == "litblogs-app:litblogs-smoke-0123456789ab"


def test_route_checks_require_password_registration_and_keep_unknown_api_404():
    module = smoke_module()
    responses = {
        "/help": (200, {"content-type": "text/html"}, b"<!doctype html><title>LitBlogs</title>"),
        "/api/missing": (404, {}, b"{}"),
        "/api/runtime-config": (200, {}, b'{"local_password_registration_enabled": true, "google_oauth_enabled": false}'),
    }
    module.check_routes(lambda path, **_kwargs: responses[path])
    responses["/api/missing"] = (200, {"content-type": "text/html"}, b"wrong SPA fallback")
    with pytest.raises(module.SmokeError):
        module.check_routes(lambda path, **_kwargs: responses[path])


def test_runtime_probe_checks_real_tls_role_and_private_custody():
    module = smoke_module()
    source = module.RUNTIME_PROBE
    assert "psycopg2.connect" in source
    assert 'sslmode="verify-full"' in source
    assert "pg_stat_ssl" in source
    assert "litblogs_runtime" in source
    assert "postgres-root-ca.pem" in source
    assert "10001" in source and "0o750" in source
    assert "print(os.environ" not in source


def test_synthetic_database_sentinel_is_owned_by_postgres_not_runtime():
    module = smoke_module()
    assert "CREATE SCHEMA litblogs_container_smoke AUTHORIZATION postgres" in module.CREATE_SENTINEL_SQL
    assert "GRANT" not in module.CREATE_SENTINEL_SQL
    assert "public.users" not in module.CREATE_SENTINEL_SQL


def test_recreation_targets_private_app_while_routes_use_gateway(tmp_path, monkeypatch):
    module = smoke_module()
    commands = []
    saved_sentinel = None

    def run(command, **parameters):
        nonlocal saved_sentinel
        commands.append(command)
        output = ""
        if "info" in command:
            output = "linux"
        elif module.RUNTIME_PROBE in command:
            output = '{"video": "/assets/tutorial-H4SH1234.mp4"}'
        elif "stat" in command:
            output = "999:999:600"
        elif module.UPLOAD_SENTINEL_PROBE in command:
            output = "verified"
        elif "psql" in command:
            if parameters.get("input") == module.CREATE_SENTINEL_SQL:
                saved_sentinel = next(argument.split("=", 2)[2] for argument in command if argument.startswith("--set=sentinel="))
            elif parameters.get("input") == module.READ_SENTINEL_SQL:
                output = saved_sentinel
        return SimpleNamespace(returncode=0, stdout=output, stderr="")

    session = module.SmokeSession(ROOT, "litblogs-smoke-0123456789ab", tmp_path / "environment", 15000, run=run)
    responses = {
        "/api/health/ready": (200, {}, b'{"status": "ready"}'),
        "/help": (200, {"content-type": "text/html"}, b"<html>help</html>"),
        "/api/missing": (404, {}, b"{}"),
        "/api/runtime-config": (200, {}, b'{"local_password_registration_enabled": true, "google_oauth_enabled": false}'),
        "/assets/tutorial-H4SH1234.mp4": (206, {"content-range": "bytes 0-15/1000"}, b"1234567890123456"),
    }
    monkeypatch.setattr(session, "http", lambda path, **_kwargs: responses[path])
    module.run_session(session)
    recreations = [command for command in commands if "--force-recreate" in command]
    assert recreations and recreations[0][-2:] == ["postgres", "app"]
    probes = [command for command in commands if module.RUNTIME_PROBE in command or module.UPLOAD_SENTINEL_PROBE in command]
    assert probes and all(command[command.index("-T") + 1] == "app" for command in probes)
