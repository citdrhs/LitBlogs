#!/usr/bin/env python3
"""Validate LitBlog's committed CI and repository-governance contract."""

from __future__ import annotations

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
    "github/codeql-action": 4,
}
EXPECTED_ACTION_PINS = {
    "actions/checkout": ("3d3c42e5aac5ba805825da76410c181273ba90b1", "v7.0.1"),
    "actions/setup-python": ("5fda3b95a4ea91299a34e894583c3862153e4b97", "v7.0.0"),
    "actions/setup-node": ("820762786026740c76f36085b0efc47a31fe5020", "v7.0.0"),
    "github/codeql-action/init": ("db488ddef3bf6cb639b32c2e9a7c0a7ea8271d28", "v4.37.8"),
    "github/codeql-action/analyze": ("db488ddef3bf6cb639b32c2e9a7c0a7ea8271d28", "v4.37.8"),
}

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
        "sqlite:///" in backend_commands,
        "backend pytest must be explicitly isolated to a synthetic SQLite database",
    )
    expect(
        "python -m pip install -r requirements.txt -r requirements-dev.txt" in backend_commands,
        "backend must install both exact requirements files",
    )

    for job_id in ("frontend-tests", "frontend-lint", "frontend-build", "dependency-audit"):
        commands = step_commands(jobs.get(job_id, {}))
        expect("npm ci" in commands, f"CI job {job_id} must use npm ci")
        expect(
            re.search(r"npm\s+install(?:\s|$)", commands) is None,
            f"CI job {job_id} must not use npm install",
        )

    dependency_commands = step_commands(jobs.get("dependency-audit", {}))
    expect(
        "python -m pip_audit -r requirements.txt" in dependency_commands,
        "dependency audit must hard-fail pip-audit for runtime requirements",
    )
    expect(
        "npm audit --omit=dev --audit-level=high" in dependency_commands,
        "dependency audit must hard-fail high-severity npm runtime findings",
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
        secret_pip_installs == ["python -m pip install PyYAML==6.0.3"],
        "secret scan must install only the exact pinned PyYAML validator dependency",
    )
    expect("git log" not in secret_commands, "secret scan must not inspect legacy history")
    expect("git diff" not in secret_commands, "secret scan must inspect the proposed tree, not diffs")

    sast_commands = step_commands(jobs.get("sast", {}))
    expect("python -m ruff check ." in sast_commands, "SAST must run Ruff")
    expect(
        (
            'python -m bandit -r . -x '
            '"./tests/*,./.venv/*,*/__pycache__/*,*/.pytest_cache/*,*/.ruff_cache/*" -ll'
        )
        in sast_commands,
        "SAST must run Bandit across the complete backend runtime package",
    )

    expect("python-version: \"3.13\"" in text, "CI must use Python 3.13")
    expect("node-version: \"20\"" in text, "CI must use Node 20")
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
    contact_links = issue_config.get("contact_links", [])
    expect(
        isinstance(contact_links, list)
        and any(
            isinstance(link, dict)
            and "security/advisories/new" in str(link.get("url", ""))
            for link in contact_links
        ),
        "issue config must redirect security reports to a private advisory",
    )

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

    security = read_text("SECURITY.md").lower()
    for phrase in (
        "https://github.com/antigro09/litblog/security/advisories/new",
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
    hook_ids = {
        hook.get("id")
        for repository in repositories
        if isinstance(repository, dict)
        for hook in repository.get("hooks", [])
        if isinstance(hook, dict)
    }
    expect(
        hook_ids == {"secret-check", "repository-policy", "backend-ruff", "frontend-lint"},
        "pre-commit hook IDs must cover secrets, policy, Ruff, and frontend lint",
    )

    expect(
        (ROOT / "scripts/check-generic-secrets.py").is_file(),
        "missing proposed-tree generic secret scanner",
    )
    expect(
        (ROOT / "scripts/check-generic-secrets.tests.py").is_file(),
        "missing generic secret scanner regression suite",
    )


def main() -> int:
    validate_ci()
    validate_codeql()
    validate_dependabot()
    validate_repository_documents()

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
