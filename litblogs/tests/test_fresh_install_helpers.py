"""Execute the non-mutating shell contracts used during fresh deployment."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SETUP = ROOT / "deploy/scripts/fresh_server_setup.sh"
RESTORE = ROOT / "deploy/scripts/fresh_restore_rehearsal.sh"


def _bash(arguments, source):
    if os.name == "nt":
        executable = shutil.which("wsl.exe")
        prefix = [executable, "bash"] if executable else None
    else:
        executable = shutil.which("bash")
        prefix = [executable] if executable else None
    if prefix is None:
        pytest.skip("Bash is unavailable")
    result = subprocess.run(
        [*prefix, *arguments],
        input=source.encode("utf-8"),
        capture_output=True,
        check=False,
        timeout=30,
    )
    result.stdout = result.stdout.decode("utf-8")
    result.stderr = result.stderr.decode("utf-8")
    return result


def _definitions(path):
    return path.read_text(encoding="utf-8").split(
        'if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then', 1
    )[0]


@pytest.mark.parametrize("path", [SETUP, RESTORE])
def test_fresh_helper_is_lf_shell_source(path):
    data = path.read_bytes()
    assert b"\r" not in data
    result = _bash(["-n"], data.decode("utf-8"))
    assert result.returncode == 0, result.stderr


def _check_worker_environment(extra):
    environment = (
        ROOT / "deploy/password-reset.production.env.example"
    ).read_text(encoding="utf-8")
    # Define helpers without running a root phase or touching the host.
    source = _definitions(SETUP) + (
        "\nvalidate_password_reset_env /dev/stdin <<'WORKER_CONFIG'\n"
        + environment + extra + "\nWORKER_CONFIG\n"
    )
    return _bash(["-s"], source)


def test_auth_worker_template_matches_the_allowed_environment():
    result = _check_worker_environment("")
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "extra, message",
    [
        ("SECRET_KEY=private-canary-926\n", "Forbidden authentication-worker setting"),
        ("EMAIL_HOST=duplicate.example\n", "Duplicate authentication-worker setting"),
        ("bad private-canary-926\n", "Invalid or empty authentication-worker setting"),
        ("EMAIL_PASSWORD=\n", "Invalid or empty authentication-worker setting"),
    ],
)
def test_auth_worker_rejects_extra_keys_duplicates_and_malformed_lines(extra, message):
    result = _check_worker_environment(extra)
    assert result.returncode != 0
    assert message in result.stderr
    assert "private-canary-926" not in result.stdout + result.stderr


def test_prepare_cleans_both_credentials_when_preflight_fails():
    # Stub every external effect. The function must reach the early failure,
    # then run its EXIT cleanup even though migration never began.
    source = _definitions(SETUP) + """
require_root() { :; }
require_release() { :; }
assert_private_env() { return 37; }
rm() { printf 'cleanup:%s\\n' "$*"; }
phase_prepare
"""
    result = _bash(["-s"], source)
    assert result.returncode == 37
    assert "cleanup:-f -- /run/litblogs-migration.env /run/litblogs-backup.env" in result.stdout


def test_restore_cleans_credential_when_isolation_guard_fails():
    source = _definitions(RESTORE) + """
require_root() { :; }
require_release() { :; }
rm() { printf 'cleanup:%s\\n' "$*"; }
ISOLATION_APPROVED=false
phase_restore_verify
"""
    result = _bash(["-s"], source)
    assert result.returncode != 0
    assert "cleanup:-f -- /run/litblogs-restore.env" in result.stdout


def test_migration_revokes_role_and_cleans_credential_when_validation_fails():
    source = _definitions(SETUP) + """
assert_private_env() { return 37; }
sudo() { printf 'database-cleanup:%s\\n' "$*"; }
rm() { printf 'cleanup:%s\\n' "$*"; }
run_migration
"""
    result = _bash(["-s"], source)
    assert result.returncode == 37
    assert "REVOKE litblog_identity_owner FROM litblogs_migrator;" in result.stdout
    assert "cleanup:-f -- /run/litblogs-migration.env" in result.stdout
