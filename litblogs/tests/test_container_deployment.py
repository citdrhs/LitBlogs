"""Production container boundaries, independent of a Docker daemon."""

import importlib.util
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[2]


def runtime_module():
    spec = importlib.util.spec_from_file_location("container_runtime", ROOT / "deploy/container/runtime.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def environment():
    return {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "LITBLOGS_ORIGIN": "https://litblogs.school.edu",
        "LITBLOGS_DB_PASSWORD": "encoded:/@?#%& password",
        "SECRET_KEY": "fixture-signing-private-value",
        "TEACHER_INVITE_HMAC_KEY": "fixture-invitation-private-value",
        "EMAIL_HOST": "smtp.school.edu",
        "EMAIL_USERNAME": "fixture-mail@school.edu",
        "EMAIL_PASSWORD": "fixture-smtp-private-value",
        "EMAIL_FROM": "mail@school.edu",
        "ALLOWED_EMAIL_DOMAINS": "school.edu",
        "POSTGRES_PASSWORD": "administrator-private-value",
        "LITBLOGS_MIGRATOR_PASSWORD": "migrator-private-value",
        "LITBLOGS_ACCOUNT_OPERATOR_PASSWORD": "operator-private-value",
        "PYTHONPATH": "/untrusted/code",
        "RESET_DATABASE_ON_STARTUP": "true",
        "APP_ENV": "development",
    }


def test_runtime_database_is_encoded_and_certificate_verified(environment):
    result = runtime_module().build_environment("web", environment)
    url = urlsplit(result["DATABASE_URL"])
    assert url.username == "litblogs_runtime"
    assert url.hostname == "postgres.internal"
    assert "%40" in url.password and "%2F" in url.password
    assert parse_qs(url.query) == {
        "sslmode": ["verify-full"],
        "sslrootcert": ["/etc/litblogs/postgres-root-ca.pem"],
    }
    assert result["APP_ENV"] == "production"
    assert result["RESET_DATABASE_ON_STARTUP"] == "false"
    assert result["SESSION_COOKIE_SECURE"] == "true"
    assert result["SESSION_COOKIE_NAME"].startswith("__Host-")
    assert result["UPLOAD_BACKUP_RESTORE_VERIFIED"] == "false"
    assert result["UPLOAD_LEGACY_IMPORT_COMPLETE"] == "false"
    assert result["FRONTEND_URL"] == result["CORS_ALLOWED_ORIGINS"] == environment["LITBLOGS_ORIGIN"]
    assert result["GOOGLE_OAUTH_ENABLED"] == "false"


@pytest.mark.parametrize("mode", ["web", "email", "reconcile"])
def test_runtime_never_inherits_privileged_credentials_or_pythonpath(mode, environment):
    result = runtime_module().build_environment(mode, environment)
    for key in ("POSTGRES_PASSWORD", "LITBLOGS_MIGRATOR_PASSWORD", "LITBLOGS_ACCOUNT_OPERATOR_PASSWORD", "PYTHONPATH"):
        assert key not in result
        assert environment[key] not in repr(result)


def test_email_worker_has_no_signing_or_upload_authority(environment):
    result = runtime_module().build_environment("email", environment)
    assert "SECRET_KEY" not in result
    assert "TEACHER_INVITE_HMAC_KEY" not in result
    assert "UPLOAD_ROOT" not in result
    assert "EMAIL_PASSWORD" in result


@pytest.mark.parametrize("mode", ["web", "email", "reconcile"])
def test_runtime_subpath_keeps_origin_and_routes_separate(mode, environment):
    environment["LITBLOGS_BASE_PATH"] = "/dren"
    result = runtime_module().build_environment(mode, environment)
    assert result["APP_BASE_PATH"] == "/dren"
    assert result["FRONTEND_URL"] == "https://litblogs.school.edu/dren"
    assert result["LITBLOGS_ORIGIN"] == "https://litblogs.school.edu"
    if mode != "email":
        assert result["JWT_ISSUER"] == result["CORS_ALLOWED_ORIGINS"] == result["LITBLOGS_ORIGIN"]
        assert result["ALLOWED_HOSTS"] == "litblogs.school.edu"
        assert result["SESSION_COOKIE_NAME"] == "__Secure-litblogs-session"
        assert result["CSRF_COOKIE_NAME"] == "__Secure-litblogs-csrf"
        assert result["SESSION_COOKIE_SECURE"] == "true"


@pytest.mark.parametrize("prefix", ["/", "/dren/", "/../dren", "/dren%2fother", " /dren"])
def test_runtime_rejects_invalid_subpath_before_worker_start(prefix, environment):
    environment["LITBLOGS_BASE_PATH"] = prefix
    with pytest.raises(ValueError, match="APP_BASE_PATH"):
        runtime_module().build_environment("email", environment)


@pytest.mark.parametrize("origin", ["http://school.edu", "https://drhscit.org/student/litblogs", "https://school.edu/?x=y", "https://user:pw@school.edu", "https://school.edu/#hash"])
def test_shared_paths_and_ambiguous_origins_fail_closed(origin, environment):
    environment["LITBLOGS_ORIGIN"] = origin
    with pytest.raises(ValueError, match="root HTTPS"):
        runtime_module().build_environment("web", environment)


def test_readiness_requires_explicit_attestations_and_google_is_opt_in(environment):
    environment.update(UPLOAD_LEGACY_IMPORT_COMPLETE="true", UPLOAD_BACKUP_RESTORE_VERIFIED="true", GOOGLE_OAUTH_ENABLED="true", GOOGLE_CLIENT_ID="approved.apps.googleusercontent.com")
    result = runtime_module().build_environment("web", environment)
    assert result["UPLOAD_LEGACY_IMPORT_COMPLETE"] == "true"
    assert result["UPLOAD_BACKUP_RESTORE_VERIFIED"] == "true"
    assert result["GOOGLE_CLIENT_ID"] == environment["GOOGLE_CLIENT_ID"]
    assert result["LOCAL_PASSWORD_REGISTRATION_ENABLED"] == "true"


def test_missing_password_does_not_echo_other_secrets(environment):
    environment.pop("LITBLOGS_DB_PASSWORD")
    with pytest.raises(ValueError) as error:
        runtime_module().build_environment("web", environment)
    assert "private-value" not in str(error.value)


def test_unknown_mode_rejected(environment):
    with pytest.raises(ValueError, match="mode"):
        runtime_module().build_environment("shell", environment)


def test_image_uses_locked_builds_nonroot_and_runtime_only_secrets():
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "npm ci" in dockerfile and "--require-hashes" in dockerfile
    assert "USER litblogs" in dockerfile and "EXPOSE 5000" in dockerfile
    assert "sha256:" in dockerfile
    assert "COPY . ." not in dockerfile
    assert "COPY litblogs/THIRD_PARTY_EDITOR_NOTICES.md" in dockerfile
    for secret in ("SECRET_KEY", "POSTGRES_PASSWORD", "EMAIL_PASSWORD"):
        assert f"ARG {secret}" not in dockerfile
        assert f"ENV {secret}" not in dockerfile


def test_compose_keeps_state_and_private_services_isolated():
    import yaml

    config = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    services = config["services"]
    assert list(services)[0] == "web"
    assert services["web"]["user"] == "101:101"
    assert services["web"]["read_only"] is True
    assert services["web"]["depends_on"]["app"]["condition"] == "service_healthy"
    assert services["app"]["user"] == "10001:10001"
    assert services["app"]["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
    for name, service in services.items():
        if name != "web":
            assert "ports" not in service
        assert "privileged" not in service
        assert "/var/run/docker.sock" not in str(service)
    for name in ("web", "app", "email", "reconcile"):
        assert "POSTGRES_PASSWORD" not in services[name].get("environment", {})
        assert "LITBLOGS_MIGRATOR_PASSWORD" not in services[name].get("environment", {})
    assert set(config["volumes"]) >= {"postgres-data", "uploads", "postgres-tls", "postgres-ca", "clamav-data"}
    assert config["networks"]["database"]["internal"] is True
    assert "uploads" not in str(services["email"].get("volumes", []))
    # The official image's temporary initialization server is socket-only.
    # Readiness must wait for the final TCP listener, after all init SQL commits.
    assert "-h 127.0.0.1" in str(services["postgres"]["healthcheck"]["test"])


def test_operator_profiles_do_not_leak_privileged_credentials_to_web():
    import yaml

    services = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]
    for purpose in ("invitation", "account"):
        service = services[purpose]
        assert service["profiles"] == ["operators"]
        assert set(service["environment"]) == {
            f"LITBLOGS_{purpose.upper()}_OPERATOR_PASSWORD", "TEACHER_INVITE_HMAC_KEY", "ALLOWED_EMAIL_DOMAINS",
        }
        assert "uploads" not in str(service["volumes"])
    assert services["bootstrap-admin"]["profiles"] == ["operators"]


def test_tmpfs_options_remain_one_absolute_mount_per_service():
    import yaml

    services = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]
    for name, service in services.items():
        if "tmpfs" not in service:
            continue
        size = "512m" if name == "web" else "256m"
        # Unquoted commas in a YAML flow list become separate relative mounts.
        assert service["tmpfs"] == [f"/tmp:rw,noexec,nosuid,size={size},mode=1777"], name


def test_build_context_excludes_secrets_and_local_data():
    ignore = (ROOT / ".dockerignore").read_text().splitlines()
    for pattern in ("**/.env", "**/.env.*", "**/*.env", "**/.venv", "**/node_modules", "**/*.sqlite*", "**/*.db-*", ".git", "media"):
        assert pattern in ignore


def test_container_python_is_in_canonical_security_gates():
    for script in ("run-backend-ruff.py", "run-backend-bandit.py"):
        assert '"deploy/container"' in (ROOT / "scripts" / script).read_text()
