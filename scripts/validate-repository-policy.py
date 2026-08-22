#!/usr/bin/env python3
"""Validate LitBlog's committed CI and repository-governance contract."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml
from yaml.constructor import ConstructorError

ROOT = Path(__file__).resolve().parents[1]
ACTION_PIN = re.compile(
    r"^\s*uses:\s*(?P<action>(?:actions|github)/[^@\s]+)@(?P<sha>[0-9a-f]{40})"
    r"\s+#\s+(?P<version>v(?P<major>\d+)\.\d+\.\d+)\s*$"
)
MINIMUM_ACTION_GENERATIONS = {
    "actions/checkout": 7,
    "actions/setup-python": 7,
    "actions/setup-node": 7,
    "actions/upload-artifact": 7,
    "actions/download-artifact": 8,
    "actions/attest": 4,
    "github/codeql-action": 4,
}
EXPECTED_ACTION_PINS = {
    "actions/checkout": ("3d3c42e5aac5ba805825da76410c181273ba90b1", "v7.0.1"),
    "actions/setup-python": ("5fda3b95a4ea91299a34e894583c3862153e4b97", "v7.0.0"),
    "actions/setup-node": ("820762786026740c76f36085b0efc47a31fe5020", "v7.0.0"),
    "actions/upload-artifact": ("043fb46d1a93c77aae656e7c1c64a875d1fc6a0a", "v7.0.1"),
    "actions/download-artifact": ("3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c", "v8.0.1"),
    "actions/attest": ("508db95dd578ae2727ebd6217d5ba78e4fbda05d", "v4.2.1"),
    "github/codeql-action/init": ("db488ddef3bf6cb639b32c2e9a7c0a7ea8271d28", "v4.37.8"),
    "github/codeql-action/analyze": ("db488ddef3bf6cb639b32c2e9a7c0a7ea8271d28", "v4.37.8"),
}
BACKEND_RUFF_COMMAND = "python scripts/run-backend-ruff.py"
BACKEND_BANDIT_COMMAND = "python scripts/run-backend-bandit.py"
POSTGRES_OPERATOR_TEST = (
    "python -m pytest tests/test_postgres_operator_integration.py -q"
)
ALEMBIC_DRIFT_COMMAND = "python -m alembic check"
HASHED_BACKEND_INSTALL = (
    "python -m pip install --require-hashes --only-binary=:all: -r requirements-dev.txt"
)
HASHED_RELEASE_INSTALL = (
    "python -m pip install --require-hashes --only-binary=:all: "
    "-r litblogs/requirements-dev.txt"
)
LOCK_REGEN_INSTALL = (
    "python -m pip install --require-hashes --only-binary=:all: "
    "-r requirements-lock.txt"
)
LOCK_REGEN_COMMAND = "python ../scripts/compile-python-locks.py"
LOCK_DIFF_COMMAND = (
    "git diff --exit-code -- requirements.txt requirements-dev.txt requirements-lock.txt"
)
POSTGRES_CI_IMAGE = (
    "postgres:17.11-alpine3.24@"
    "sha256:7456ef82e5f5bc43d997f4781bbd7c0d6389bff397564649a356e206ba473aee"
)
NODE_MAJOR = "24"
NODE_ENGINE = "24.x"
SECURITY_ADVISORY_URL = (
    "https://github.com/citdrhs/LitBlogs/security/advisories/new"
)
EXPECTED_BANDIT_EXCLUSIONS = (
    "litblogs/tests/*",
    "litblogs/.venv/*",
    "*/__pycache__/*",
    "*/.pytest_cache/*",
    "*/.ruff_cache/*",
)

EXPECTED_CI_JOBS = {
    "backend-tests": "Backend tests",
    "frontend-tests": "Frontend tests",
    "frontend-lint": "Frontend lint",
    "frontend-build": "Frontend build",
    "dependency-audit": "Dependency audit",
    "secret-scan": "Secret scan",
    "sast": "SAST",
}


class GithubActionsLoader(yaml.SafeLoader):
    """YAML 1.2-ish loader that preserves GitHub's special ``on`` key."""


for initial, resolvers in list(GithubActionsLoader.yaml_implicit_resolvers.items()):
    GithubActionsLoader.yaml_implicit_resolvers[initial] = [
        (tag, pattern)
        for tag, pattern in resolvers
        if tag != "tag:yaml.org,2002:bool"
    ]


def construct_unique_mapping(
    loader: GithubActionsLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


GithubActionsLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, construct_unique_mapping
)


failures: list[str] = []


def fail(message: str) -> None:
    failures.append(message)


def read_text(relative_path: str) -> str:
    path = ROOT / relative_path
    if not path.is_file():
        fail(f"missing required file: {relative_path}")
        return ""
    return path.read_text(encoding="utf-8")


def load_yaml(relative_path: str) -> tuple[dict[str, Any], str]:
    text = read_text(relative_path)
    if not text:
        return {}, text
    try:
        parsed = yaml.load(text, Loader=GithubActionsLoader)
    except yaml.YAMLError as error:
        fail(f"invalid YAML in {relative_path}: {error}")
        return {}, text
    if not isinstance(parsed, dict):
        fail(f"expected a mapping at the root of {relative_path}")
        return {}, text
    return parsed, text


def expect(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def string_value(value: Any) -> str:
    return str(value).strip().lower()


def step_commands(job: dict[str, Any]) -> str:
    steps = job.get("steps", [])
    if not isinstance(steps, list):
        return ""
    return "\n".join(
        str(step.get("run", ""))
        for step in steps
        if isinstance(step, dict) and "run" in step
    )


def validate_action_pins(relative_path: str, text: str) -> None:
    uses_lines = [line for line in text.splitlines() if re.match(r"^\s*uses:", line)]
    expect(bool(uses_lines), f"{relative_path} must use pinned GitHub-owned actions")
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not re.match(r"^\s*uses:", line):
            continue
        match = ACTION_PIN.match(line)
        expect(
            match is not None,
            (
                f"{relative_path}:{line_number} action must be GitHub-owned, pinned "
                "to 40 lowercase hex characters, and have a version comment"
            ),
        )
        if match is None:
            continue

        action = match.group("action")
        action_family = (
            "github/codeql-action" if action.startswith("github/codeql-action/") else action
        )
        minimum_major = MINIMUM_ACTION_GENERATIONS.get(action_family)
        expect(
            minimum_major is not None and int(match.group("major")) >= minimum_major,
            f"{relative_path}:{line_number} {action} must use its current Node24 generation",
        )
        expected_pin = EXPECTED_ACTION_PINS.get(action)
        expect(expected_pin is not None, f"{relative_path}:{line_number} unexpected action {action}")
        if expected_pin is not None:
            expect(
                (match.group("sha"), match.group("version")) == expected_pin,
                (
                    f"{relative_path}:{line_number} {action} must use the reviewed peeled "
                    f"commit for {expected_pin[1]}"
                ),
            )


def validate_checkout_hardening(relative_path: str, workflow: dict[str, Any]) -> None:
    jobs = workflow.get("jobs", {})
    if not isinstance(jobs, dict):
        return
    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps", []):
            if not isinstance(step, dict) or not str(step.get("uses", "")).startswith(
                "actions/checkout@"
            ):
                continue
            options = step.get("with", {})
            expect(
                isinstance(options, dict)
                and string_value(options.get("persist-credentials")) == "false",
                f"{relative_path} job {job_id} checkout must disable persisted credentials",
            )


def validate_node_setup_versions(
    relative_path: str, workflow: dict[str, Any]
) -> None:
    jobs = workflow.get("jobs", {})
    setup_steps = [
        step
        for job in jobs.values()
        if isinstance(jobs, dict) and isinstance(job, dict)
        for step in job.get("steps", [])
        if isinstance(step, dict)
        and str(step.get("uses", "")).startswith("actions/setup-node@")
    ]
    expect(bool(setup_steps), f"{relative_path} must configure Node {NODE_MAJOR}")
    expect(
        bool(setup_steps)
        and all(
            isinstance(step.get("with"), dict)
            and string_value(step["with"].get("node-version")) == NODE_MAJOR
            for step in setup_steps
        ),
        f"{relative_path} every setup-node step must use Node {NODE_MAJOR}",
    )


def validate_ci() -> None:
    relative_path = ".github/workflows/ci.yml"
    ci, text = load_yaml(relative_path)
    if not ci:
        return

    triggers = ci.get("on", {})
    expect(
        isinstance(triggers, dict)
        and set(triggers) == {"pull_request", "push", "merge_group"},
        "CI triggers must be exactly pull_request, push, and merge_group",
    )
    push = triggers.get("push", {}) if isinstance(triggers, dict) else {}
    expect(
        isinstance(push, dict) and push.get("branches") == ["main"],
        "CI push trigger must be restricted to main",
    )

    permissions = ci.get("permissions", {})
    expect(
        permissions == {"contents": "read"},
        "CI top-level permissions must be exactly contents: read",
    )
    concurrency = ci.get("concurrency", {})
    expect(isinstance(concurrency, dict), "CI must define concurrency controls")
    if isinstance(concurrency, dict):
        expect(
            "github.workflow" in str(concurrency.get("group", ""))
            and "github.ref" in str(concurrency.get("group", "")),
            "CI concurrency group must be stable per workflow and ref",
        )
        expect(
            string_value(concurrency.get("cancel-in-progress")) == "true",
            "CI must cancel superseded in-progress runs",
        )

    jobs = ci.get("jobs", {})
    expect(isinstance(jobs, dict), "CI jobs must be a mapping")
    if not isinstance(jobs, dict):
        return
    expect(
        set(jobs) == set(EXPECTED_CI_JOBS),
        f"CI job IDs must be exactly: {', '.join(EXPECTED_CI_JOBS)}",
    )
    for job_id, display_name in EXPECTED_CI_JOBS.items():
        job = jobs.get(job_id, {})
        expect(isinstance(job, dict), f"CI job {job_id} must be a mapping")
        if not isinstance(job, dict):
            continue
        expect(job.get("name") == display_name, f"CI job {job_id} name must be {display_name!r}")
        try:
            timeout = int(job.get("timeout-minutes", 0))
        except (TypeError, ValueError):
            timeout = 0
        expect(1 <= timeout <= 30, f"CI job {job_id} needs a timeout from 1 to 30 minutes")
        expect("permissions" not in job, f"CI job {job_id} must not broaden permissions")

    backend = jobs.get("backend-tests", {})
    backend_services = backend.get("services", {}) if isinstance(backend, dict) else {}
    postgres = backend_services.get("postgres", {}) if isinstance(backend_services, dict) else {}
    postgres_env = postgres.get("env", {}) if isinstance(postgres, dict) else {}
    expect(
        isinstance(postgres, dict) and postgres.get("image") == POSTGRES_CI_IMAGE,
        "backend PostgreSQL service image must be pinned to the reviewed immutable digest",
    )
    synthetic_values = {
        "POSTGRES_USER": "litblog_ci",
        "POSTGRES_PASSWORD": "ci-only-postgres-password",
        "POSTGRES_DB": "litblog_ci",
    }
    expect(postgres_env == synthetic_values, "backend PostgreSQL service must use only synthetic values")
    postgres_options = str(postgres.get("options", "")) if isinstance(postgres, dict) else ""
    expect("pg_isready" in postgres_options, "backend PostgreSQL service needs a health check")
    backend_commands = step_commands(backend) if isinstance(backend, dict) else ""
    expect("SELECT 1" in backend_commands, "backend must run a PostgreSQL SELECT 1 smoke check")
    expect(
        re.search(r"python\s+-m\s+pytest\s+-q", backend_commands) is not None,
        "backend must run pytest",
    )
    expect(
        "python -m alembic upgrade head" in backend_commands
        and "python -m alembic downgrade 985a04df032a" in backend_commands
        and "python -m alembic downgrade base" in backend_commands
        and "python -m alembic current --check-heads" in backend_commands
        and ALEMBIC_DRIFT_COMMAND in backend_commands,
        "backend must apply, fully reverse, and verify Alembic on PostgreSQL",
    )

    backend_steps = backend.get("steps", []) if isinstance(backend, dict) else []
    pytest_steps = [
        step
        for step in backend_steps
        if isinstance(step, dict)
        and re.search(r"python\s+-m\s+pytest\s+-q", str(step.get("run", "")))
    ]
    expect(len(pytest_steps) == 1, "backend must have exactly one pytest step")
    pytest_environment = pytest_steps[0].get("env", {}) if len(pytest_steps) == 1 else {}
    guarded_postgres_url = (
        "postgresql://litblog_ci:ci-only-postgres-password@localhost:5432/litblog_ci"
    )
    expected_pytest_environment = {
        "APP_ENV": "test",
        "TEST_DATABASE_URL": guarded_postgres_url,
        "DATABASE_URL": guarded_postgres_url,
        "TEST_POSTGRES_DATABASE": "litblog_ci",
        "ALLOW_TEST_DATABASE_DDL": "true",
        "RESET_DATABASE_ON_STARTUP": "false",
    }
    migration_steps = [
        step
        for step in backend_steps
        if isinstance(step, dict)
        and "python -m alembic upgrade head" in str(step.get("run", ""))
    ]
    expect(len(migration_steps) == 1, "backend must have exactly one migration step")
    migration_environment = (
        migration_steps[0].get("env", {}) if len(migration_steps) == 1 else {}
    )
    expect(
        migration_environment
        == {
            "APP_ENV": "test",
            "TEST_DATABASE_URL": guarded_postgres_url,
            "LITBLOGS_MIGRATION_DATABASE_URL": guarded_postgres_url,
        },
        "backend migrations must use only the isolated migration URL contract",
    )
    expect(
        pytest_environment == expected_pytest_environment,
        "backend pytest must use the guarded synthetic PostgreSQL service environment",
    )
    expect(
        "sqlite" not in str(pytest_environment).lower(),
        "backend pytest must reject SQLite and exercise the PostgreSQL service",
    )
    expect(
        HASHED_BACKEND_INSTALL in backend_commands,
        "backend must install the complete hash-locked dependency graph",
    )
    operator_steps = [
        step
        for step in backend_steps
        if isinstance(step, dict) and str(step.get("run", "")).strip() == POSTGRES_OPERATOR_TEST
    ]
    expect(
        len(operator_steps) == 1,
        "backend must run the real PostgreSQL operator integration test exactly once",
    )
    operator_environment = operator_steps[0].get("env", {}) if len(operator_steps) == 1 else {}
    expect(
        operator_environment
        == {
            "POSTGRES_OPERATOR_CONTAINER_ID": "${{ job.services.postgres.id }}",
            "POSTGRES_OPERATOR_DATABASE_URL": (
                "postgresql://litblog_ci:ci-only-postgres-password@127.0.0.1:5432/"
                "litblog_ci?sslmode=verify-full&sslrootcert="
                "/etc/litblogs/postgres-root-ca.pem"
            ),
        },
        "backend operator smoke must use the service container ID and strict TLS parser URL",
    )

    for job_id in ("frontend-tests", "frontend-lint", "frontend-build", "dependency-audit"):
        commands = step_commands(jobs.get(job_id, {}))
        expect("npm ci" in commands, f"CI job {job_id} must use npm ci")
        expect(
            re.search(r"npm\s+install(?:\s|$)", commands) is None,
            f"CI job {job_id} must not use npm install",
        )

    dependency_commands = step_commands(jobs.get("dependency-audit", {}))
    for command in (LOCK_REGEN_INSTALL, LOCK_REGEN_COMMAND, LOCK_DIFF_COMMAND):
        expect(
            command in dependency_commands,
            f"dependency audit must verify reproducible Python locks with {command}",
        )
    expect(
        HASHED_BACKEND_INSTALL in dependency_commands,
        "dependency audit must install the complete hash-locked dependency graph",
    )
    expect(
        "python -m pip_audit -r requirements.txt" in dependency_commands,
        "dependency audit must hard-fail pip-audit for runtime requirements",
    )
    expect(
        "python -m pip_audit -r requirements-dev.txt" in dependency_commands,
        "dependency audit must hard-fail pip-audit for the installed build/test graph",
    )
    expect(
        "npm audit --omit=dev --audit-level=high" in dependency_commands,
        "dependency audit must hard-fail high-severity npm runtime findings",
    )
    expect(
        "npm audit --audit-level=high" in dependency_commands,
        "dependency audit must hard-fail the complete npm build graph",
    )
    expect("|| true" not in dependency_commands, "dependency audit must not suppress failures")

    secret_job = jobs.get("secret-scan", {})
    secret_commands = step_commands(secret_job)
    for command in (
        "check-no-tracked-secrets.ps1",
        "check-no-tracked-secrets.tests.ps1",
        "check-generic-secrets.tests.py",
        "check-generic-secrets.py",
        "validate-repository-policy.py",
    ):
        expect(command in secret_commands, f"secret scan must run {command}")
    secret_steps = secret_job.get("steps", []) if isinstance(secret_job, dict) else []
    expect(
        any(
            isinstance(step, dict)
            and str(step.get("uses", "")).startswith("actions/setup-python@")
            for step in secret_steps
        ),
        "secret scan must set up the pinned Python runtime",
    )
    secret_pip_installs = [
        line.strip()
        for line in secret_commands.splitlines()
        if "python -m pip install" in line
    ]
    expect(
        secret_pip_installs == [HASHED_BACKEND_INSTALL],
        "secret scan must install only the complete hash-locked policy dependency graph",
    )
    expect("git log" not in secret_commands, "secret scan must not inspect legacy history")
    expect("git diff" not in secret_commands, "secret scan must inspect the proposed tree, not diffs")

    sast_commands = step_commands(jobs.get("sast", {}))
    expect(
        HASHED_BACKEND_INSTALL in sast_commands,
        "SAST must install the complete hash-locked dependency graph",
    )
    expect(
        BACKEND_RUFF_COMMAND in sast_commands,
        "SAST must use the shared backend/operator Ruff runner",
    )
    expect(
        "python -m ruff check" not in sast_commands,
        "SAST must not duplicate the shared Ruff command",
    )
    expect(
        BACKEND_BANDIT_COMMAND in sast_commands,
        "SAST must use the shared backend Bandit runner",
    )
    expect(
        "python -m bandit" not in sast_commands,
        "SAST must not duplicate the shared backend Bandit command",
    )

    expect("python-version: \"3.13\"" in text, "CI must use Python 3.13")
    validate_node_setup_versions(relative_path, ci)
    validate_action_pins(relative_path, text)
    validate_checkout_hardening(relative_path, ci)


def validate_codeql() -> None:
    relative_path = ".github/workflows/codeql.yml"
    codeql, text = load_yaml(relative_path)
    if not codeql:
        return

    triggers = codeql.get("on", {})
    expect(
        isinstance(triggers, dict)
        and set(triggers) == {"pull_request", "push", "merge_group", "schedule"},
        "CodeQL triggers must be exactly pull_request, push, merge_group, and schedule",
    )
    push = triggers.get("push", {}) if isinstance(triggers, dict) else {}
    expect(
        isinstance(push, dict) and push.get("branches") == ["main"],
        "CodeQL push trigger must be restricted to main",
    )
    schedule = triggers.get("schedule", []) if isinstance(triggers, dict) else []
    expect(
        isinstance(schedule, list)
        and len(schedule) == 1
        and isinstance(schedule[0], dict)
        and bool(schedule[0].get("cron")),
        "CodeQL must have one scheduled scan",
    )
    expect(
        codeql.get("permissions") == {"contents": "read"},
        "CodeQL top-level permissions must be exactly contents: read",
    )

    jobs = codeql.get("jobs", {})
    expect(isinstance(jobs, dict) and set(jobs) == {"analyze"}, "CodeQL job ID must be analyze")
    analyze = jobs.get("analyze", {}) if isinstance(jobs, dict) else {}
    expect(
        isinstance(analyze, dict) and analyze.get("name") != "SAST",
        "CodeQL check name must not collide with CI SAST",
    )
    if isinstance(analyze, dict):
        permissions = analyze.get("permissions", {})
        expect(
            permissions == {"contents": "read", "security-events": "write"},
            "CodeQL analyze job must grant only contents: read and security-events: write",
        )
        matrix = analyze.get("strategy", {}).get("matrix", {})
        expect(
            matrix.get("language") == ["python", "javascript-typescript"],
            "CodeQL matrix must cover Python and JavaScript/TypeScript",
        )
        try:
            timeout = int(analyze.get("timeout-minutes", 0))
        except (TypeError, ValueError):
            timeout = 0
        expect(1 <= timeout <= 30, "CodeQL analyze job needs a timeout from 1 to 30 minutes")

    expect(
        text.count("security-events: write") == 1,
        "security-events: write must appear only in the CodeQL analyze job",
    )
    validate_action_pins(relative_path, text)
    validate_checkout_hardening(relative_path, codeql)


def validate_release() -> None:
    relative_path = ".github/workflows/release.yml"
    release, text = load_yaml(relative_path)
    if not release:
        return

    triggers = release.get("on", {})
    expect(
        isinstance(triggers, dict) and set(triggers) == {"workflow_dispatch"},
        "release workflow must be manual-only",
    )
    expect(
        release.get("permissions") == {"contents": "read"},
        "release top-level permissions must be exactly contents: read",
    )
    concurrency = release.get("concurrency", {})
    expect(
        isinstance(concurrency, dict)
        and "github.ref" in str(concurrency.get("group", ""))
        and string_value(concurrency.get("cancel-in-progress")) == "false",
        "release workflow must serialize runs per ref without cancelling an approved build",
    )

    jobs = release.get("jobs", {})
    expect(
        isinstance(jobs, dict) and set(jobs) == {"build-release", "attest-release"},
        "release workflow must contain only build-release and attest-release",
    )
    job = jobs.get("build-release", {}) if isinstance(jobs, dict) else {}
    if not isinstance(job, dict):
        return
    expect(
        job.get("name") == "Build immutable release artifact",
        "release job needs the stable immutable-artifact check name",
    )
    expect(
        job.get("if") == "github.ref == 'refs/heads/main'",
        "release job must refuse non-main refs",
    )
    expect(
        "environment" not in job,
        "release build job must not enter the protected attestation environment",
    )
    expect(
        job.get("permissions") == {"contents": "read"},
        "release build job permissions must be exactly contents: read",
    )
    try:
        timeout = int(job.get("timeout-minutes", 0))
    except (TypeError, ValueError):
        timeout = 0
    expect(1 <= timeout <= 30, "release job needs a timeout from 1 to 30 minutes")

    services = job.get("services", {})
    postgres = services.get("postgres", {}) if isinstance(services, dict) else {}
    expect(
        isinstance(postgres, dict)
        and postgres.get("image") == POSTGRES_CI_IMAGE
        and postgres.get("env")
        == {
            "POSTGRES_USER": "litblog_release_ci",
            "POSTGRES_PASSWORD": "release-ci-only-postgres-password",
            "POSTGRES_DB": "litblog_test_release_ci",
        }
        and "pg_isready" in str(postgres.get("options", "")),
        "release verification must use a healthy synthetic PostgreSQL service",
    )

    commands = step_commands(job)
    expect(
        HASHED_RELEASE_INSTALL in commands,
        "release verification must install the complete hash-locked dependency graph",
    )
    for required in (
        LOCK_REGEN_INSTALL,
        LOCK_REGEN_COMMAND,
        LOCK_DIFF_COMMAND,
        "python -m pytest -q",
        "python -m alembic upgrade head",
        "python -m alembic downgrade 985a04df032a",
        "python -m alembic downgrade base",
        "python -m alembic current --check-heads",
        ALEMBIC_DRIFT_COMMAND,
        POSTGRES_OPERATOR_TEST,
        BACKEND_RUFF_COMMAND,
        BACKEND_BANDIT_COMMAND,
        "npm --prefix litblogs run test:run",
        "npm --prefix litblogs run lint",
        "npm --prefix litblogs run build",
        "python -m pip_audit -r litblogs/requirements.txt",
        "python -m pip_audit -r litblogs/requirements-dev.txt",
        "npm --prefix litblogs audit --audit-level=high",
        "npm --prefix litblogs audit --omit=dev --audit-level=high",
        "check-generic-secrets.py",
        "validate-repository-policy.py",
        (
            "git archive --format=tar HEAD -- deploy docs/operations litblogs/*.py "
            "litblogs/alembic.ini litblogs/migrations/env.py "
            "litblogs/migrations/script.py.mako litblogs/migrations/versions "
            "litblogs/requirements.txt litblogs/requirements.in "
            "litblogs/requirements-lock.txt litblogs/requirements-lock.in"
        ),
        'test ! -e "$RUNNER_TEMP/litblogs-release-output"',
        'mkdir -m 0700 "$RUNNER_TEMP/litblogs-release-output"',
        'artifact="$RUNNER_TEMP/litblogs-release-output/',
        "sha256sum",
        "python-sbom.cdx.json",
        "frontend-sbom.cdx.json",
    ):
        expect(required in commands, f"release workflow must run {required}")
    expect(
        "litblogs/migrations/0001_create_federated_identities.sql" not in commands
        and "litblogs/migrations " not in commands,
        "release archive must exclude the superseded raw migration and whole migration tree",
    )
    release_migration_steps = [
        step
        for step in job.get("steps", [])
        if isinstance(step, dict)
        and "python -m alembic upgrade head" in str(step.get("run", ""))
    ]
    release_database_url = (
        "postgresql://litblog_release_ci:release-ci-only-postgres-password@"
        "localhost:5432/litblog_test_release_ci"
    )
    expect(
        len(release_migration_steps) == 1
        and release_migration_steps[0].get("env")
        == {
            "APP_ENV": "test",
            "TEST_DATABASE_URL": release_database_url,
            "LITBLOGS_MIGRATION_DATABASE_URL": release_database_url,
        },
        "release migrations must use only the isolated migration URL contract",
    )
    release_operator_steps = [
        step
        for step in job.get("steps", [])
        if isinstance(step, dict) and str(step.get("run", "")).strip() == POSTGRES_OPERATOR_TEST
    ]
    expect(
        len(release_operator_steps) == 1,
        "release must run the real PostgreSQL operator integration test exactly once",
    )
    release_operator_environment = (
        release_operator_steps[0].get("env", {})
        if len(release_operator_steps) == 1
        else {}
    )
    expect(
        release_operator_environment
        == {
            "POSTGRES_OPERATOR_CONTAINER_ID": "${{ job.services.postgres.id }}",
            "POSTGRES_OPERATOR_DATABASE_URL": (
                "postgresql://litblog_release_ci:release-ci-only-postgres-password@"
                "127.0.0.1:5432/litblog_test_release_ci?sslmode=verify-full&"
                "sslrootcert=/etc/litblogs/postgres-root-ca.pem"
            ),
        },
        "release operator smoke must use the service container ID and strict TLS parser URL",
    )
    for forbidden in ("scp ", "ssh ", "rsync ", "systemctl ", "kubectl ", "--reload"):
        expect(forbidden not in commands, f"release workflow must not deploy with {forbidden.strip()}")

    attestation_job = jobs.get("attest-release", {}) if isinstance(jobs, dict) else {}
    if not isinstance(attestation_job, dict):
        return
    expect(
        attestation_job.get("name") == "Attest reviewed release artifact",
        "release attestation job needs a stable name",
    )
    expect(
        attestation_job.get("needs") == "build-release",
        "release attestation job must depend on build-release",
    )
    expect(
        attestation_job.get("if") == "github.ref == 'refs/heads/main'",
        "release attestation job must refuse non-main refs",
    )
    expect(
        attestation_job.get("environment") == "production-release",
        "release attestation job must use the protected production-release environment",
    )
    expect(
        attestation_job.get("permissions")
        == {
            "contents": "read",
            "id-token": "write",
            "attestations": "write",
            "artifact-metadata": "write",
        },
        "release attestation job must grant only attestation permissions",
    )
    try:
        attestation_timeout = int(attestation_job.get("timeout-minutes", 0))
    except (TypeError, ValueError):
        attestation_timeout = 0
    expect(
        1 <= attestation_timeout <= 15,
        "release attestation job needs a timeout from 1 to 15 minutes",
    )
    expect(
        all("run" not in step for step in attestation_job.get("steps", []) if isinstance(step, dict)),
        "release attestation job must not execute downloaded release content",
    )

    build_uses = [
        str(step.get("uses", ""))
        for step in job.get("steps", [])
        if isinstance(step, dict) and step.get("uses")
    ]
    attestation_uses = [
        str(step.get("uses", ""))
        for step in attestation_job.get("steps", [])
        if isinstance(step, dict) and step.get("uses")
    ]
    expect(
        not any(value.startswith("actions/attest@") for value in build_uses),
        "release build job must not have attestation credentials",
    )
    expect(
        sum(value.startswith("actions/attest@") for value in attestation_uses) == 3,
        "release workflow must attest provenance and both dependency SBOMs",
    )
    expect(
        sum(value.startswith("actions/upload-artifact@") for value in build_uses) == 1,
        "release workflow must upload exactly one reviewed artifact bundle",
    )
    expect(
        sum(value.startswith("actions/download-artifact@") for value in attestation_uses) == 1,
        "release attestation job must download exactly one reviewed artifact bundle",
    )
    validate_action_pins(relative_path, text)
    validate_checkout_hardening(relative_path, release)
    validate_node_setup_versions(relative_path, release)


def validate_dependabot() -> None:
    dependabot, _ = load_yaml(".github/dependabot.yml")
    updates = dependabot.get("updates", []) if dependabot else []
    expect(isinstance(updates, list), "Dependabot updates must be a list")
    if not isinstance(updates, list):
        return
    actual = {
        (entry.get("package-ecosystem"), entry.get("directory"))
        for entry in updates
        if isinstance(entry, dict)
    }
    expected = {("npm", "/litblogs"), ("pip", "/litblogs"), ("github-actions", "/")}
    expect(actual == expected, "Dependabot ecosystems/directories must be npm, pip, and GitHub Actions")
    for entry in updates:
        if not isinstance(entry, dict):
            continue
        ecosystem = entry.get("package-ecosystem", "unknown")
        expect(
            entry.get("schedule", {}).get("interval") == "weekly",
            f"Dependabot {ecosystem} schedule must be weekly",
        )
        try:
            limit = int(entry.get("open-pull-requests-limit", 0))
        except (TypeError, ValueError):
            limit = 0
        expect(1 <= limit <= 10, f"Dependabot {ecosystem} needs a sensible open PR limit")
        expect(bool(entry.get("labels")), f"Dependabot {ecosystem} needs labels")
        groups = entry.get("groups", {})
        expect(
            isinstance(groups, dict)
            and any(
                isinstance(group, dict)
                and set(group.get("update-types", [])) == {"minor", "patch"}
                for group in groups.values()
            ),
            f"Dependabot {ecosystem} must group non-major updates",
        )


def validate_repository_documents() -> None:
    codeowners = read_text(".github/CODEOWNERS")
    for required_line in (
        "* @Antigro09",
        "/.github/ @Antigro09",
        "/scripts/ @Antigro09",
        "/SECURITY.md @Antigro09",
        "/litblogs/requirements*.in @Antigro09",
        "/litblogs/requirements*.txt @Antigro09",
        "/litblogs/package*.json @Antigro09",
    ):
        expect(required_line in codeowners, f"CODEOWNERS must include {required_line!r}")

    pull_request = read_text(".github/PULL_REQUEST_TEMPLATE.md").lower()
    for phrase in (
        "stack parent",
        "base branch",
        "student journey",
        "teacher journey",
        "negative authorization",
        "privacy",
        "migration",
        "rollback",
        "pip-audit",
        "npm audit",
        "screenshot",
    ):
        expect(phrase in pull_request, f"pull request template must cover {phrase}")

    for form_path in (
        ".github/ISSUE_TEMPLATE/bug_report.yml",
        ".github/ISSUE_TEMPLATE/feature_request.yml",
    ):
        form, _ = load_yaml(form_path)
        expect(bool(form.get("name")), f"{form_path} needs a name")
        expect(bool(form.get("description")), f"{form_path} needs a description")
        expect(isinstance(form.get("body"), list) and bool(form.get("body")), f"{form_path} needs fields")

    issue_config, _ = load_yaml(".github/ISSUE_TEMPLATE/config.yml")
    expect(
        string_value(issue_config.get("blank_issues_enabled")) == "false",
        "issue config must disable blank issues",
    )
    validate_security_reporting()

    contributing = read_text("CONTRIBUTING.md").lower()
    for phrase in (
        "codex/",
        "stacked",
        "draft pull request",
        "parent branch",
        "base branch",
        "squash",
        "direct push",
        "deployment",
        "conventional commits",
        "student",
        "personally identifiable information",
        "check-no-tracked-secrets",
    ):
        expect(phrase in contributing, f"CONTRIBUTING.md must document {phrase}")
    expect(
        BACKEND_BANDIT_COMMAND in contributing,
        "CONTRIBUTING.md must use the same shared backend Bandit runner as CI",
    )
    expect(
        "python -m bandit" not in contributing,
        "CONTRIBUTING.md must not duplicate the backend Bandit command",
    )

    security = read_text("SECURITY.md").lower()
    for phrase in (
        "personally identifiable information",
        "do not attach logs",
        "rotate",
        "incident",
    ):
        expect(phrase in security, f"SECURITY.md must include {phrase}")

    pre_commit, _ = load_yaml(".pre-commit-config.yaml")
    repositories = pre_commit.get("repos", []) if pre_commit else []
    expect(
        isinstance(repositories, list)
        and len(repositories) == 1
        and repositories[0].get("repo") == "local",
        "pre-commit must use only deterministic local hooks",
    )
    hooks_by_id = {
        hook.get("id"): hook
        for repository in repositories
        if isinstance(repository, dict)
        for hook in repository.get("hooks", [])
        if isinstance(hook, dict)
    }
    expect(
        set(hooks_by_id)
        == {"secret-check", "repository-policy", "backend-ruff", "backend-bandit", "frontend-lint"},
        "pre-commit hook IDs must cover secrets, policy, Ruff, Bandit, and frontend lint",
    )
    bandit_hook = hooks_by_id.get("backend-bandit", {})
    ruff_hook = hooks_by_id.get("backend-ruff", {})
    expect(
        isinstance(ruff_hook, dict)
        and ruff_hook.get("entry") == BACKEND_RUFF_COMMAND
        and ruff_hook.get("language") == "python"
        and ruff_hook.get("additional_dependencies") == ["ruff==0.16.4"]
        and "deploy/scripts" in str(ruff_hook.get("files", "")),
        "pre-commit Ruff hook must scan backend and operator Python with pinned Ruff",
    )
    expect(
        isinstance(bandit_hook, dict)
        and bandit_hook.get("entry") == BACKEND_BANDIT_COMMAND
        and bandit_hook.get("language") == "python"
        and bandit_hook.get("additional_dependencies") == ["bandit==1.9.4"],
        "pre-commit Bandit hook must invoke the shared runner with pinned Bandit",
    )
    expect(
        "deploy/scripts" in str(bandit_hook.get("files", "")),
        "pre-commit Bandit hook must include operator Python",
    )

    expect(
        (ROOT / "scripts/check-generic-secrets.py").is_file(),
        "missing proposed-tree generic secret scanner",
    )
    expect(
        (ROOT / "scripts/check-generic-secrets.tests.py").is_file(),
        "missing generic secret scanner regression suite",
    )
    bandit_runner = read_text("scripts/run-backend-bandit.py")
    for fragment in (
        *EXPECTED_BANDIT_EXCLUSIONS,
        '"-r"',
        '"litblogs"',
        '"deploy/scripts"',
        '"-x"',
        '"-ll"',
        "cwd=REPOSITORY_ROOT",
    ):
        expect(fragment in bandit_runner, f"shared backend Bandit runner must include {fragment}")
    ruff_runner = read_text("scripts/run-backend-ruff.py")
    for fragment in (
        '"litblogs/pyproject.toml"',
        '"litblogs"',
        '"deploy/scripts"',
        "REPOSITORY_ROOT",
    ):
        expect(fragment in ruff_runner, f"shared Ruff runner must include {fragment}")


def validate_security_reporting() -> None:
    issue_config, _ = load_yaml(".github/ISSUE_TEMPLATE/config.yml")
    contact_links = issue_config.get("contact_links", [])
    advisory_urls = [
        str(link.get("url", ""))
        for link in contact_links
        if isinstance(link, dict)
        and "security/advisories/new" in str(link.get("url", "")).lower()
    ] if isinstance(contact_links, list) else []
    expect(
        advisory_urls == [SECURITY_ADVISORY_URL],
        "issue config must use the exact canonical private advisory URL",
    )

    security = read_text("SECURITY.md")
    expect(
        SECURITY_ADVISORY_URL in security
        and "github.com/Antigro09/LitBlog/security/advisories/new" not in security,
        "SECURITY.md must use the exact canonical private advisory URL",
    )


def validate_node_runtime_contract() -> None:
    try:
        package = json.loads(read_text("litblogs/package.json"))
        package_lock = json.loads(read_text("litblogs/package-lock.json"))
    except (json.JSONDecodeError, TypeError):
        fail("frontend package metadata must be valid JSON")
        return

    expected_engines = {"node": NODE_ENGINE}
    expect(
        package.get("engines") == expected_engines,
        f"litblogs/package.json must require exactly Node {NODE_MAJOR}",
    )
    locked_root = package_lock.get("packages", {}).get("", {})
    expect(
        isinstance(locked_root, dict)
        and locked_root.get("engines") == expected_engines,
        "package-lock root metadata must preserve the exact Node engine",
    )
    for marker in ("litblogs/.nvmrc", "litblogs/.node-version"):
        expect(
            read_text(marker) == f"{NODE_MAJOR}\n",
            f"{marker} must pin Node {NODE_MAJOR}",
        )


def validate_python_dependency_locks() -> None:
    input_paths = (
        "litblogs/requirements.in",
        "litblogs/requirements-dev.in",
        "litblogs/requirements-lock.in",
    )
    lock_paths = (
        "litblogs/requirements.txt",
        "litblogs/requirements-dev.txt",
        "litblogs/requirements-lock.txt",
    )

    for path in input_paths:
        text = read_text(path)
        expect(text, f"missing Python dependency input {path}")
        for line in text.splitlines():
            requirement = line.strip()
            if not requirement or requirement.startswith(("#", "-r ")):
                continue
            expect(
                "==" in requirement
                and "git+" not in requirement.lower()
                and "http://" not in requirement.lower(),
                f"Python dependency input must use exact index pins: {path}",
            )

    for path in lock_paths:
        text = read_text(path)
        expect(text, f"missing Python dependency lock {path}")
        expect(
            "autogenerated by pip-compile" in text
            and "--generate-hashes" in text
            and "--hash=sha256:" in text,
            f"Python dependency lock must contain pip-compile SHA-256 hashes: {path}",
        )
        expect(
            "--index-url" not in text and "--trusted-host" not in text,
            f"Python dependency lock must not pin a private index or trusted host: {path}",
        )

    lock_tool_input = read_text("litblogs/requirements-lock.in")
    expect(
        "pip==26.1.2" in lock_tool_input and "pip-tools==7.6.0" in lock_tool_input,
        "lock regeneration must pin the mutually compatible pip and pip-tools versions",
    )
    compiler = read_text("scripts/compile-python-locks.py")
    for fragment in (
        'EXPECTED_PYTHON = (3, 13)',
        '"pip": "26.1.2"',
        '"pip-tools": "7.6.0"',
        'sys.platform != "linux"',
        '"--generate-hashes"',
        '"--no-emit-index-url"',
        '"--no-emit-trusted-host"',
    ):
        expect(fragment in compiler, f"Python lock compiler must include {fragment}")


def validate_privacy_ignores() -> None:
    required_patterns = {
        ".gitignore": {"litblogs/uploads/", "*.db", "*.sqlite*"},
        "litblogs/.gitignore": {"uploads/", "*.db", "*.sqlite*"},
    }
    for path, required in required_patterns.items():
        patterns = {
            line.strip()
            for line in read_text(path).splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        missing = required - patterns
        expect(
            not missing,
            f"{path} must ignore private uploads and local SQLite databases",
        )


def main() -> int:
    validate_ci()
    validate_codeql()
    validate_release()
    validate_dependabot()
    validate_repository_documents()
    validate_node_runtime_contract()
    validate_python_dependency_locks()
    validate_privacy_ignores()

    if failures:
        print("Repository policy validation failed:")
        for message in failures:
            print(f"- {message}")
        print(f"FAILURES={len(failures)}")
        return 1

    print("Repository policy validation passed.")
    print(f"CI_JOB_NAMES={','.join(EXPECTED_CI_JOBS.values())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
