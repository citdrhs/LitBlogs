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
BROWSER_E2E_SERVICE_ENV = {
    "POSTGRES_USER": "litblogs_e2e_admin",
    "POSTGRES_PASSWORD": "e2e-ci-only-postgres-password",
    "POSTGRES_DB": "postgres",
    "POSTGRES_INITDB_ARGS": "--auth-host=scram-sha-256 --auth-local=scram-sha-256",
}
BROWSER_E2E_ADMIN_URL = (
    "postgresql+psycopg2://litblogs_e2e_admin:e2e-ci-only-postgres-password@"
    "127.0.0.1:5432/postgres"
)
BROWSER_E2E_CONFIRMATION = "litblogs-e2e-only"
BROWSER_E2E_ARTIFACT_PATH = (
    "litblogs/test-results/e2e/sanitized-failures/*.json"
)
NODE_MAJOR = "24"
NODE_ENGINE = "24.x"
TIPTAP_VERSION = "^3.30.2"
TIPTAP_LOCK_VERSION = "3.30.2"
REVIEWED_TIPTAP_RUNTIME_PACKAGES = frozenset(
    {
        "@tiptap/core",
        "@tiptap/extension-character-count",
        "@tiptap/extension-color",
        "@tiptap/extension-font-family",
        "@tiptap/extension-highlight",
        "@tiptap/extension-image",
        "@tiptap/extension-link",
        "@tiptap/extension-placeholder",
        "@tiptap/extension-table",
        "@tiptap/extension-text-align",
        "@tiptap/extension-text-style",
        "@tiptap/extension-underline",
        "@tiptap/pm",
        "@tiptap/react",
        "@tiptap/starter-kit",
    }
)
AUDITED_TIPTAP_LOCK_PACKAGES = frozenset(
    {
        "@tiptap/core",
        "@tiptap/extension-blockquote",
        "@tiptap/extension-bold",
        "@tiptap/extension-bubble-menu",
        "@tiptap/extension-bullet-list",
        "@tiptap/extension-character-count",
        "@tiptap/extension-code",
        "@tiptap/extension-code-block",
        "@tiptap/extension-color",
        "@tiptap/extension-document",
        "@tiptap/extension-dropcursor",
        "@tiptap/extension-floating-menu",
        "@tiptap/extension-font-family",
        "@tiptap/extension-gapcursor",
        "@tiptap/extension-hard-break",
        "@tiptap/extension-heading",
        "@tiptap/extension-highlight",
        "@tiptap/extension-horizontal-rule",
        "@tiptap/extension-image",
        "@tiptap/extension-italic",
        "@tiptap/extension-link",
        "@tiptap/extension-list",
        "@tiptap/extension-list-item",
        "@tiptap/extension-list-keymap",
        "@tiptap/extension-ordered-list",
        "@tiptap/extension-paragraph",
        "@tiptap/extension-placeholder",
        "@tiptap/extension-strike",
        "@tiptap/extension-table",
        "@tiptap/extension-text",
        "@tiptap/extension-text-align",
        "@tiptap/extension-text-style",
        "@tiptap/extension-underline",
        "@tiptap/extensions",
        "@tiptap/pm",
        "@tiptap/react",
        "@tiptap/starter-kit",
    }
)
AUDITED_TIPTAP_LOCK_INTEGRITIES = {
    "@tiptap/core": "sha512-QbZC/s1OOqcoUdkhIY16TjR/gCtR0qAk9e4bJwUqOJqZuv5ozqCL5hzWm22jjTPp6c6Ei2tPd6t30VwfIKW4lQ==",
    "@tiptap/extension-blockquote": "sha512-BOkwhZenek7vzXBOgKppSrlx4YryBdAYu1p1MXKn0R9A9eNmE2HVhmm0gG49+E8BhsE/TG8wKVclwET42JJiIg==",
    "@tiptap/extension-bold": "sha512-MsvJhPgYejY2D9MhwYJv8AmscozvLBI8qtJ7YLdYZBWkMR4bgmxHq5+xqEfBsao9bOMMwBon9p3+P+/Tq5ReWA==",
    "@tiptap/extension-bubble-menu": "sha512-oS0WiWNXHKpiPYMkcnHm1j7iEvufTGGtLFtcJJd3olb5OS6V2acoXVDL0nNJDmRQ32K3QXut3fbRcMseMxT+lw==",
    "@tiptap/extension-bullet-list": "sha512-+awIL/TUz4aB3rL68igU1rWfaaoBIAkPcakkktkRq8gYf0bd9eSb48P6kHkpx/3q+JyK7g9vsnltLNHNh6twnA==",
    "@tiptap/extension-character-count": "sha512-9Mnej4qOLf2/kFPAmGxkxwdpFNRq8+D9nQVnyFF50x32myaKl/BXcCftsm+EiKpnH9JNT5mhZA0nh4JoH7OwrA==",
    "@tiptap/extension-code": "sha512-r8EZk3R9yGpF6v5xxafAU1HwrD/e+RpbfnmVi2TeB/ZHAsVO62fW96E32G0t6IdaCtOFtAd85hkDAaOfCT4yGg==",
    "@tiptap/extension-code-block": "sha512-9otGKaQZmePHrLXFtCtz+BYDn5z4sSumTkUqQIQHz0gVxwPoTi7g51RedwxvViTb/zu2XV5ROXYLHIxKxypMPg==",
    "@tiptap/extension-color": "sha512-VNct6qKePIoruJZ4PR30JtA3YfENOqESrUtDLF1YMJYf/oU26Bx4ePJGTy428IA0mouyE+uHruyUGfZXnT73Iw==",
    "@tiptap/extension-document": "sha512-+xIv67V+/2L1uvz98FAT5W7kWEfHwfNV3MD7b4UsKPU0lhcCWuVOXy0JB8yYmdNExqpI7xT9g3MWzREoBvBQSg==",
    "@tiptap/extension-dropcursor": "sha512-nyRKUmItATnKI9AiRChmjhcBbCEsNxRu+AaCz+cx8EvnAcNHsVRdNYL5PmBs3WlNA/Et4Eb2DG0hVQDnNF61eg==",
    "@tiptap/extension-floating-menu": "sha512-A8PLvvh8W6PUMrqh+EpBerxm+Ucr0irGxJvwAnzYQmNGNIJ9U4OVgw4OcEU+9JH0gMmEzDcHzMPP2s/s1lIcyw==",
    "@tiptap/extension-font-family": "sha512-syg9Gfo+TN3rhxPxACgHSKRjcpl08enBHNinjCQI2pg8BMGDLG7DTrSAlIK/uEhTxxzSqBUOBaGrue+Q0oJQmg==",
    "@tiptap/extension-gapcursor": "sha512-7Xk0ut6FM+RAsvKxDN3bAtk7zvYZ6Aa8pawJ6s7dLAmLR9JwrZevlcL4FSrj4bR7rqKOj92RYCFxzgTEbWimag==",
    "@tiptap/extension-hard-break": "sha512-IxSNgmG3d4OZdUTeebrOI7SxdIWXXJqlcGiSNDabWqxipUitfy3mZ3gDDE6G01koKxZRbhz4KIplAZlpxnTFSg==",
    "@tiptap/extension-heading": "sha512-PblDvgSJ05p1t6hzyPi02xeiBjB0M2abReoGEImqSWCy79UqnAGacgsZo4EeEawtJV1NEP8chhvmX+nRtzdT1A==",
    "@tiptap/extension-highlight": "sha512-LY1/LTEluP/z82JkoPVE3ffCVO7Bt6ltVeBMXsfb6S7GLS8eXput2KU1XlyLqTCQADvjaS1oTMfaplH+tS7Meg==",
    "@tiptap/extension-horizontal-rule": "sha512-j8aswLTsuEdJKC62DF+kw0EgvIRL7QMUyAVp2fdjR0qgM0ZVlEwCC4qIEq3kK9tFVU4kRtQ5BSj/jn6QwrlbCA==",
    "@tiptap/extension-image": "sha512-K/BPlWauHXI6Y4s7se2A1BLcZ2pnWmRQTEDkPJYe/8kmv1GyJzPu34sZed5Mvfu5chUH8u6aNZ/utZbvSbI/0Q==",
    "@tiptap/extension-italic": "sha512-pp8uaiuXsUbLm5rYzR1jlWbwm1mAahRajdHwAKBtthFRB2rDvC7ZWhKaCSoKhZvfIDRmu9/B67+uAHoutL0dCA==",
    "@tiptap/extension-link": "sha512-jwdcymKcrbFpj5hRAuGVLCq8FieVkGFnENyroYmvkad+XAt8ZLy/MTFYRN6SK3ukH6PZMY7H4iObGtciQaC5nw==",
    "@tiptap/extension-list": "sha512-MIUpo1Bd9Rf1Qg+TNYNwDZ4xsfFeQahjU9Xhy6UcaszKQzbAM7KCzn5BObNytK1NdcqNHsC8Wj5vFvMKEzrXdw==",
    "@tiptap/extension-list-item": "sha512-HWgRCRlGxulE+hN1VUcnWD6P2NE08VBgGtcaxOfdXVqaI93BCK6AhRQZGpLsfKgajLk+5DXTBraaitwnBqzCxg==",
    "@tiptap/extension-list-keymap": "sha512-TTve3WOlQaYu1ahMqsQ/T0wzaxfgZvcOl3/OuPyInOi8QtxXhqGhFjmYe5jOr56G9W2QDuFWVsZecVwfDte9zg==",
    "@tiptap/extension-ordered-list": "sha512-Z7OO1HcF0idda1n6vodXeQ3h2ylN9JR4IfIGUYkar5Xl9JusK8PDETTBQZQn//96p49I2d+GoWsD2LXPtjHXXg==",
    "@tiptap/extension-paragraph": "sha512-ulEu3LNt+kPVAWEnrhoz13Fs8Q/v/8NUxQbAeteuBchQ8joxJXuWExhpy1fUfZir5+b+W5z7/NesgPjZQfv47w==",
    "@tiptap/extension-placeholder": "sha512-Bj1seUvPCoRrD/LpzMoKD+jQIjxuc+oq931GpPq4wobSUUbD4pF/0NMwpCLpiHO19QnTQz8+9p2dqPdlc44LHA==",
    "@tiptap/extension-strike": "sha512-fBLxMXz6hYIURzLOD+/L6aVATztsKham00ANWmGi13vN0hx2lQMYZffN+gR+QqiCDfMQxBXzrf5a7tJuDiQHLQ==",
    "@tiptap/extension-table": "sha512-zWp0ehZnx6N5lwRa8anSTn17GBEF3wxHXfOJGbBugf4Vwmp5keUEAXrgeIS4j7gIdxjN3XawdwjuMImG93N+Fg==",
    "@tiptap/extension-text": "sha512-n/iZnirgRmXet6f97kolAnP3j8DsgLSiTbz/KLWc8eBYiFmkjRzkuisOm5xuGdfGIxwpB4x3tlSF4ef4DLnbRg==",
    "@tiptap/extension-text-align": "sha512-zexiz0uJlX2KzeAyYI/uEoBsl0Zw3Ua0CTV/kRKTnk7K9vCOnwvJXtXdkHA4WC12ACqUsPnyc4yMTwDR22fKFw==",
    "@tiptap/extension-text-style": "sha512-o3YMN3JNHg/rCCLZB3PUcAfl4bkrsXDoYoHRXvrbE9cl/RT+qAEFAAssI8kBC1fp9en9V2F4Z7Uy2uuzkbecKw==",
    "@tiptap/extension-underline": "sha512-SZiTMnvqXcnrtJX+X25ZbYsuDO83haGOVMBD/O+mAWYNYXhaSc5Rkph5czzItxrd+Yyp/vs4PiwD7XTNbfqmpA==",
    "@tiptap/extensions": "sha512-2LqAHXk26QDsryW+beECxYeBzv5Ylk4GuB3cOmfghS7/G37R2W+Te3TkUK7BT0EWoDryvBT57/5q0DEFIhfZZg==",
    "@tiptap/pm": "sha512-BJN8tUx4ppFN3R3cV/FJfrJbJkvo1lj4uciq+nwpjwzdRvFzqIuglWf+HLcJ6CwlYpLOHp7ArgkBg4Q5e60Gog==",
    "@tiptap/react": "sha512-7hGaTstpUeTmQ008mCPkjz+GSlChWhucgy+PeX0z93v4+nh7qM5F+0lh+kJ9zo6Os5abO7v36GtgHRZdQI6+FQ==",
    "@tiptap/starter-kit": "sha512-fJSrhW1CyD4sjYA20evSP4Cp13B/HhbxCdM974K0xpHOVqvCtNU9w2s9hfq9mg2yGoU7MSNHKNYMkJjIi2/Xyw==",
}
TIPTAP_STARTER_KIT_LOCK_DEPENDENCIES = frozenset(
    {
        "@tiptap/core",
        "@tiptap/extension-blockquote",
        "@tiptap/extension-bold",
        "@tiptap/extension-bullet-list",
        "@tiptap/extension-code",
        "@tiptap/extension-code-block",
        "@tiptap/extension-document",
        "@tiptap/extension-dropcursor",
        "@tiptap/extension-gapcursor",
        "@tiptap/extension-hard-break",
        "@tiptap/extension-heading",
        "@tiptap/extension-horizontal-rule",
        "@tiptap/extension-italic",
        "@tiptap/extension-link",
        "@tiptap/extension-list",
        "@tiptap/extension-list-item",
        "@tiptap/extension-list-keymap",
        "@tiptap/extension-ordered-list",
        "@tiptap/extension-paragraph",
        "@tiptap/extension-strike",
        "@tiptap/extension-text",
        "@tiptap/extension-underline",
        "@tiptap/extensions",
        "@tiptap/pm",
    }
)
TIPTAP_CORE_ONLY_LOCK_PEERS = frozenset(
    {
        "@tiptap/extension-bold",
        "@tiptap/extension-code",
        "@tiptap/extension-document",
        "@tiptap/extension-hard-break",
        "@tiptap/extension-heading",
        "@tiptap/extension-highlight",
        "@tiptap/extension-image",
        "@tiptap/extension-italic",
        "@tiptap/extension-paragraph",
        "@tiptap/extension-strike",
        "@tiptap/extension-text",
        "@tiptap/extension-text-align",
        "@tiptap/extension-text-style",
        "@tiptap/extension-underline",
    }
)
TIPTAP_CORE_PM_LOCK_PEERS = frozenset(
    {
        "@tiptap/extension-blockquote",
        "@tiptap/extension-bubble-menu",
        "@tiptap/extension-code-block",
        "@tiptap/extension-floating-menu",
        "@tiptap/extension-horizontal-rule",
        "@tiptap/extension-link",
        "@tiptap/extension-list",
        "@tiptap/extension-table",
        "@tiptap/extensions",
        "@tiptap/react",
    }
)
TIPTAP_LIST_LOCK_PEERS = frozenset(
    {
        "@tiptap/extension-bullet-list",
        "@tiptap/extension-list-item",
        "@tiptap/extension-list-keymap",
        "@tiptap/extension-ordered-list",
    }
)
TIPTAP_EXTENSIONS_LOCK_PEERS = frozenset(
    {
        "@tiptap/extension-character-count",
        "@tiptap/extension-dropcursor",
        "@tiptap/extension-gapcursor",
        "@tiptap/extension-placeholder",
    }
)
TIPTAP_TEXT_STYLE_LOCK_PEERS = frozenset(
    {
        "@tiptap/extension-color",
        "@tiptap/extension-font-family",
    }
)
TIPTAP_LOCK_DEPENDENCY_SECTIONS = (
    "dependencies",
    "devDependencies",
    "optionalDependencies",
    "peerDependencies",
)
TIPTAP_SERVICE_PACKAGE_PREFIXES = (
    "@hocuspocus/",
    "@tiptap-cloud/",
    "@tiptap-pro/",
)
TIPTAP_SERVICE_PACKAGES = frozenset({"y-webrtc", "y-websocket"})
TIPTAP_API_KEY = re.compile(
    r"\b(?:(?:VITE|REACT_APP)_)?TIPTAP(?:_CLOUD)?_(?:API_KEY|SECRET|TOKEN)\b"
    r"|\btiptap(?:Cloud)?(?:ApiKey|Secret|Token)\b",
    re.IGNORECASE,
)
EXTERNAL_EDITOR_RUNTIME = re.compile(
    r"(?:(?:https?|wss):)?//[^\s\"'`<>]*(?:tiptap|tinymce|prosemirror)"
    r"[^\s\"'`<>]*",
    re.IGNORECASE,
)
EXTERNAL_SCRIPT_SRC = re.compile(
    r"<script\b[^>]*\bsrc\s*=\s*(?:[\"']\s*)?(?:https?:)?//",
    re.IGNORECASE,
)
TIPTAP_PACKAGE_REFERENCE = re.compile(r"@tiptap/[a-z0-9][a-z0-9._-]*", re.IGNORECASE)
FRONTEND_RUNTIME_SUFFIXES = frozenset(
    {".css", ".html", ".js", ".jsx", ".mjs", ".ts", ".tsx"}
)
EDITOR_POLICY_EXCLUDED_DIRECTORIES = frozenset({"__tests__", "test", "tests"})
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
MAINTENANCE_RELEASE_FILES = (
    "deploy/systemd/litblogs-password-reset.service",
    "deploy/systemd/litblogs-password-reset.timer",
    "deploy/systemd/litblogs-upload-reconciliation.service",
    "deploy/systemd/litblogs-upload-reconciliation.timer",
    "litblogs/password_reset_delivery.py",
    "litblogs/password_reset_job.py",
    "litblogs/runtime_database_identity.py",
    "litblogs/upload_reconciliation_job.py",
)
COUPLED_RECOVERY_RELEASE_FILES = (
    "deploy/scripts/upload_snapshot_common.py",
    "deploy/scripts/backup_postgres.py",
    "deploy/scripts/restore_verify_postgres.py",
)

EXPECTED_CI_JOBS = {
    "backend-tests": "Backend tests",
    "browser-journeys": "Browser release journeys",
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


def validate_browser_job(relative_path: str, job: Any) -> None:
    label = f"{relative_path} browser journey job"
    expect(isinstance(job, dict), f"{label} must be a mapping")
    if not isinstance(job, dict):
        return

    expect(job.get("name") == "Browser release journeys", f"{label} needs a stable name")
    try:
        timeout = int(job.get("timeout-minutes", 0))
    except (TypeError, ValueError):
        timeout = 0
    expect(1 <= timeout <= 30, f"{label} needs a timeout from 1 to 30 minutes")

    services = job.get("services", {})
    postgres = services.get("postgres", {}) if isinstance(services, dict) else {}
    expect(
        isinstance(postgres, dict) and postgres.get("image") == POSTGRES_CI_IMAGE,
        f"{label} must use the immutable PostgreSQL 17 service",
    )
    postgres_env = postgres.get("env", {}) if isinstance(postgres, dict) else {}
    expect(
        postgres_env == BROWSER_E2E_SERVICE_ENV,
        f"{label} must require SCRAM on the dedicated disposable service",
    )
    expect(
        postgres.get("ports") == ["5432:5432"] if isinstance(postgres, dict) else False,
        f"{label} must expose only the dedicated PostgreSQL service port",
    )
    postgres_options = str(postgres.get("options", "")) if isinstance(postgres, dict) else ""
    expect(
        "pg_isready -U litblogs_e2e_admin -d postgres" in postgres_options,
        f"{label} needs a PostgreSQL health check against the admin database",
    )

    steps = job.get("steps", [])
    expect(isinstance(steps, list), f"{label} steps must be a list")
    if not isinstance(steps, list):
        return
    expect(
        all(
            not isinstance(step, dict) or "continue-on-error" not in step
            for step in steps
        ),
        f"{label} must not make any browser gate step advisory",
    )
    commands = step_commands(job)
    for required in (
        HASHED_BACKEND_INSTALL,
        "npm ci",
        "python -m pytest -q e2e/support/test_database.py",
        "node --test e2e/support/sanitized-reporter.test.mjs",
        "npx playwright install --with-deps chromium",
        "npm run test:e2e",
    ):
        expect(required in commands, f"{label} must run {required}")
    expect(
        re.search(r"npm\s+install(?:\s|$)", commands) is None,
        f"{label} must use npm ci instead of npm install",
    )
    expect("|| true" not in commands, f"{label} must not suppress browser failures")

    python_steps = [
        step
        for step in steps
        if isinstance(step, dict)
        and str(step.get("uses", "")).startswith("actions/setup-python@")
    ]
    expect(
        len(python_steps) == 1
        and isinstance(python_steps[0].get("with"), dict)
        and string_value(python_steps[0]["with"].get("python-version")) == "3.13",
        f"{label} must set up Python 3.13 exactly once",
    )
    node_steps = [
        step
        for step in steps
        if isinstance(step, dict)
        and str(step.get("uses", "")).startswith("actions/setup-node@")
    ]
    expect(
        len(node_steps) == 1
        and isinstance(node_steps[0].get("with"), dict)
        and string_value(node_steps[0]["with"].get("node-version")) == NODE_MAJOR,
        f"{label} must set up Node {NODE_MAJOR} exactly once",
    )

    journey_steps = [
        step
        for step in steps
        if isinstance(step, dict) and step.get("name") == "Run seven browser journeys"
    ]
    expected_journey_environment = {
        "CI": "true",
        "E2E_ADMIN_DATABASE_URL": BROWSER_E2E_ADMIN_URL,
        "E2E_DISPOSABLE_DATABASE_CONFIRMED": BROWSER_E2E_CONFIRMATION,
    }
    expect(
        len(journey_steps) == 1
        and str(journey_steps[0].get("run", "")).strip() == "npm run test:e2e",
        f"{label} must run the seven-journey suite exactly once",
    )
    journey_environment = journey_steps[0].get("env", {}) if len(journey_steps) == 1 else {}
    expect(
        journey_environment == expected_journey_environment,
        f"{label} must use the explicit loopback admin URL and disposable confirmation",
    )

    upload_steps = [
        step
        for step in steps
        if isinstance(step, dict)
        and str(step.get("uses", "")).startswith("actions/upload-artifact@")
    ]
    expect(len(upload_steps) == 1, f"{label} must have one failure artifact step")
    upload_step = upload_steps[0] if len(upload_steps) == 1 else {}
    upload_options = upload_step.get("with", {}) if isinstance(upload_step, dict) else {}
    expect(
        upload_step.get("if") == "failure()"
        and isinstance(upload_options, dict)
        and upload_options.get("path") == BROWSER_E2E_ARTIFACT_PATH
        and upload_options.get("if-no-files-found") == "ignore"
        and upload_options.get("retention-days") == 3
        and string_value(upload_options.get("include-hidden-files")) == "false",
        f"{label} must upload only the sanitized failure artifact for three days",
    )


def validate_browser_e2e_contract() -> None:
    config = read_text("litblogs/playwright.config.js")
    package_text = read_text("litblogs/package.json")
    ignore_policy = read_text("litblogs/.gitignore")
    global_setup = read_text("litblogs/e2e/global-setup.mjs")
    fixtures = read_text("litblogs/e2e/support/fixtures.js")
    database_harness = read_text("litblogs/e2e/support/database.py")
    reporter = read_text("litblogs/e2e/support/sanitized-reporter.mjs")
    reporter_test = read_text("litblogs/e2e/support/sanitized-reporter.test.mjs")

    for marker in (
        "fullyParallel: false",
        "workers: 1",
        "retries: 0",
        "preserveOutput: 'failures-only'",
        "browserName: 'chromium'",
        "./e2e/support/sanitized-reporter.mjs",
        "outputDirectory: 'test-results/e2e/sanitized-failures'",
    ):
        expect(marker in config, f"Playwright release config must retain {marker}")
    for capture in ("screenshot", "trace", "video"):
        expect(
            config.count(f"{capture}:") == 1 and f"{capture}: 'off'" in config,
            f"Playwright release config must disable {capture} artifacts",
        )
    expect("storageState" not in config, "Playwright release config must not reuse storage state")
    expect(
        "['list']" not in config,
        "Playwright release config must not stream raw output through the list reporter",
    )
    expect(
        "firefox" not in config.lower() and "webkit" not in config.lower(),
        "Playwright release config must run only serial Chromium",
    )
    for ignored_output in ("test-results/", "playwright-report/", "blob-report/"):
        expect(
            ignored_output in ignore_policy.splitlines(),
            f"browser raw output must remain ignored: {ignored_output}",
        )
    for callback in ("printsToStdio()", "onStdOut()", "onStdErr()", "onError()"):
        expect(
            callback in reporter,
            f"browser reporter must suppress streamed failure output via {callback}",
        )
    expect(
        "errors: testInfo.errors.map" not in fixtures
        and "error_count: testInfo.errors.length" in fixtures,
        "browser failure summaries must not serialize raw error messages",
    )

    try:
        package = json.loads(package_text)
    except json.JSONDecodeError as error:
        fail(f"invalid litblogs/package.json while validating browser journeys: {error}")
        package = {}
    scripts = package.get("scripts", {}) if isinstance(package, dict) else {}
    dev_dependencies = package.get("devDependencies", {}) if isinstance(package, dict) else {}
    expect(
        isinstance(scripts, dict)
        and scripts.get("test:e2e") == "playwright test --project=chromium",
        "package.json must expose the mandatory Chromium-only E2E command",
    )
    expect(
        isinstance(dev_dependencies, dict) and "@playwright/test" in dev_dependencies,
        "package.json must lock the Playwright test runner",
    )

    spec_directory = ROOT / "litblogs" / "e2e" / "specs"
    spec_paths = sorted(spec_directory.glob("*.spec.js")) if spec_directory.is_dir() else []
    spec_source = "\n".join(path.read_text(encoding="utf-8") for path in spec_paths)
    journey_titles = (
        "serves the built sign-in shell in real Chromium",
        "login uses runtime config, HttpOnly sessions, CSRF, and role guards",
        "teacher creates a class plus student-visible and staff-only assignments",
        "students join, autosave and submit, while private work stays concealed",
        "pending uploads bind to a class post without escaping class ACLs",
        "admin disable revokes a live session and enable restores only sign-in",
        "logout revokes the cookie session and purges legacy durable private state",
    )
    expect(
        len(re.findall(r"(?m)^\s*test\(", spec_source)) == len(journey_titles)
        and all(title in spec_source for title in journey_titles),
        "browser release suite must contain exactly the seven reviewed journeys",
    )

    for marker in (
        "Browser journeys require Node.js 24",
        "CI browser journeys require a disposable E2E_ADMIN_DATABASE_URL",
        "E2E_DISPOSABLE_DATABASE_CONFIRMED",
        "'litblogs-e2e-only'",
        "'--auth-local', 'scram-sha-256'",
        "'--auth-host', 'scram-sha-256'",
        "password_encryption=scram-sha-256",
        "const migratorUrl = databaseMetadata.migrator_url",
        "const runtimeUrl = databaseMetadata.runtime_url",
        "DATABASE_URL: runtimeUrl",
        "E2E_SEED_DATABASE_URL: migratorUrl",
        "['-m', 'alembic', 'upgrade', 'head']",
        "['-m', 'uvicorn', 'main:app'",
        "[viteCli, 'build'",
    ):
        expect(marker in global_setup, f"browser harness must retain {marker}")
    expect(
        "if (process.env.CI) throw new Error(reason)" in global_setup,
        "browser harness must fail rather than skip when CI prerequisites are absent",
    )

    for marker in (
        "SHOW server_version_num",
        "170_000 <= version_number < 180_000",
        "LOOPBACK_HOSTS",
        'url.database != "postgres"',
        "SCRAM-SHA-256$%",
        "accepted an invalid runtime password",
        '("litblogs_runtime", "litblogs_runtime")',
        "E2E runtime database privileges are not exact",
    ):
        expect(marker in database_harness, f"browser database harness must retain {marker}")
    expect(
        fixtures.count("browser.newContext({ baseURL })") == 2
        and "storageState" not in fixtures,
        "browser role fixtures must create fresh contexts without storage-state reuse",
    )
    expect(
        "attachment.name === 'sanitized-failure.json'" in reporter
        and "fs.rmSync(attachment.path, { force: true })" in reporter
        and "mode: 0o600" in reporter
        and "test-results/e2e/sanitized-failures" in reporter,
        "browser reporter must publish only mode-0600 sanitized files and delete raw files",
    )
    for redaction_probe in ("password", "draftCanary", "stdout", "stderr"):
        expect(
            redaction_probe in reporter_test,
            f"browser reporter regression must cover {redaction_probe} redaction",
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

    validate_browser_job(relative_path, jobs.get("browser-journeys"))

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
    migration_database_url = (
        "postgresql://litblogs_migrator:ci-only-migrator-password@localhost:5432/"
        "litblog_test_migrations_ci"
    )
    expect(
        migration_environment
        == {
            "APP_ENV": "test",
            "PGHOST": "localhost",
            "PGPORT": "5432",
            "PGDATABASE": "postgres",
            "PGUSER": "litblog_ci",
            "PGPASSWORD": "ci-only-postgres-password",
            "TEST_DATABASE_URL": migration_database_url,
            "LITBLOGS_MIGRATION_DATABASE_URL": migration_database_url,
        },
        "backend migrations must use the same isolated migrator URL contract",
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
            "POSTGRES_OPERATOR_BACKUP_DATABASE_URL": (
                "postgresql://litblogs_backup:ci-only-backup-password@127.0.0.1:5432/"
                "litblog_test_operator_ci?sslmode=verify-full&sslrootcert="
                "/etc/litblogs/postgres-root-ca.pem"
            ),
            "POSTGRES_OPERATOR_RESTORE_DATABASE_URL": (
                "postgresql://litblog_ci:ci-only-postgres-password@127.0.0.1:5432/"
                "litblog_test_operator_ci?sslmode=verify-full&sslrootcert="
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
        isinstance(jobs, dict)
        and set(jobs) == {"browser-journeys", "build-release", "attest-release"},
        "release workflow must contain browser-journeys, build-release, and attest-release",
    )
    browser_job = jobs.get("browser-journeys", {}) if isinstance(jobs, dict) else {}
    validate_browser_job(relative_path, browser_job)
    if isinstance(browser_job, dict):
        expect(
            browser_job.get("if") == "github.ref == 'refs/heads/main'",
            "release browser journey job must refuse non-main refs",
        )
        expect(
            "environment" not in browser_job,
            "release browser journey job must not enter the protected environment",
        )
        expect(
            browser_job.get("permissions") == {"contents": "read"},
            "release browser journey permissions must be exactly contents: read",
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
        job.get("needs") == "browser-journeys",
        "release packaging must depend on the unprivileged browser journey gate",
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
        'test -f "$staging/tree/litblogs/rich_text_security.py"',
        (
            "git archive --format=tar HEAD -- deploy docs/operations litblogs/*.py "
            "litblogs/rich_text_contract.json "
            "litblogs/alembic.ini litblogs/migrations/env.py "
            "litblogs/migrations/sqlite_contract.py "
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
        "postgresql://litblogs_migrator:release-ci-only-migrator-password@"
        "localhost:5432/litblog_test_release_migrations_ci"
    )
    expect(
        len(release_migration_steps) == 1
        and release_migration_steps[0].get("env")
        == {
            "APP_ENV": "test",
            "PGHOST": "localhost",
            "PGPORT": "5432",
            "PGDATABASE": "postgres",
            "PGUSER": "litblog_release_ci",
            "PGPASSWORD": "release-ci-only-postgres-password",
            "TEST_DATABASE_URL": release_database_url,
            "LITBLOGS_MIGRATION_DATABASE_URL": release_database_url,
        },
        "release migrations must use the same isolated migrator URL contract",
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
            "POSTGRES_OPERATOR_BACKUP_DATABASE_URL": (
                "postgresql://litblogs_backup:release-ci-only-backup-password@"
                "127.0.0.1:5432/litblog_test_release_operator_ci?sslmode=verify-full&"
                "sslrootcert=/etc/litblogs/postgres-root-ca.pem"
            ),
            "POSTGRES_OPERATOR_RESTORE_DATABASE_URL": (
                "postgresql://litblog_release_ci:release-ci-only-postgres-password@"
                "127.0.0.1:5432/litblog_test_release_operator_ci?sslmode=verify-full&"
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
    protected_environment_jobs = [
        job_id
        for job_id, candidate in jobs.items()
        if isinstance(candidate, dict)
        and candidate.get("environment") == "production-release"
    ]
    expect(
        protected_environment_jobs == ["attest-release"],
        "release attestation must be the sole protected-environment job",
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


def editor_runtime_policy_paths() -> list[Path]:
    frontend_root = ROOT / "litblogs"
    paths = [
        frontend_root / "index.html",
        frontend_root / ".env.example",
    ]
    paths.extend(frontend_root.glob("vite.config.*"))
    paths.extend(frontend_root.glob("*.py"))
    for directory_name in ("public", "src"):
        directory = frontend_root / directory_name
        if not directory.is_dir():
            continue
        paths.extend(
            path
            for path in directory.rglob("*")
            if path.is_file()
            and path.suffix.lower() in FRONTEND_RUNTIME_SUFFIXES
            and not EDITOR_POLICY_EXCLUDED_DIRECTORIES.intersection(path.parts)
            and ".test." not in path.name
            and ".spec." not in path.name
        )
    return sorted({path for path in paths if path.is_file()})


def canonical_tiptap_package_reference(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    match = TIPTAP_PACKAGE_REFERENCE.search(value)
    return match.group(0).casefold() if match else None


def audited_tiptap_lock_edges() -> frozenset[tuple[str, str, str, str]]:
    edges = {
        ("", "dependencies", package_name, TIPTAP_VERSION)
        for package_name in REVIEWED_TIPTAP_RUNTIME_PACKAGES
    }
    edges.update(
        (
            "@tiptap/starter-kit",
            "dependencies",
            package_name,
            TIPTAP_LOCK_VERSION,
        )
        for package_name in TIPTAP_STARTER_KIT_LOCK_DEPENDENCIES
    )
    edges.add(
        (
            "@tiptap/core",
            "peerDependencies",
            "@tiptap/pm",
            TIPTAP_LOCK_VERSION,
        )
    )
    edges.update(
        (
            package_name,
            "peerDependencies",
            "@tiptap/core",
            TIPTAP_LOCK_VERSION,
        )
        for package_name in TIPTAP_CORE_ONLY_LOCK_PEERS
    )
    edges.update(
        (package_name, "peerDependencies", peer_name, TIPTAP_LOCK_VERSION)
        for package_name in TIPTAP_CORE_PM_LOCK_PEERS
        for peer_name in ("@tiptap/core", "@tiptap/pm")
    )
    edges.update(
        (
            package_name,
            "peerDependencies",
            "@tiptap/extension-list",
            TIPTAP_LOCK_VERSION,
        )
        for package_name in TIPTAP_LIST_LOCK_PEERS
    )
    edges.update(
        (
            package_name,
            "peerDependencies",
            "@tiptap/extensions",
            TIPTAP_LOCK_VERSION,
        )
        for package_name in TIPTAP_EXTENSIONS_LOCK_PEERS
    )
    edges.update(
        (
            package_name,
            "peerDependencies",
            "@tiptap/extension-text-style",
            TIPTAP_LOCK_VERSION,
        )
        for package_name in TIPTAP_TEXT_STYLE_LOCK_PEERS
    )
    edges.update(
        (
            "@tiptap/react",
            "optionalDependencies",
            package_name,
            TIPTAP_VERSION,
        )
        for package_name in (
            "@tiptap/extension-bubble-menu",
            "@tiptap/extension-floating-menu",
        )
    )
    return frozenset(edges)


def validate_tiptap_editor_policy() -> None:
    try:
        package = json.loads(read_text("litblogs/package.json"))
        package_lock = json.loads(read_text("litblogs/package-lock.json"))
    except (json.JSONDecodeError, TypeError):
        fail("Tiptap editor package metadata must be valid JSON")
        return

    dependencies = package.get("dependencies", {})
    expect(
        isinstance(dependencies, dict),
        "litblogs/package.json must declare runtime dependencies as a mapping",
    )
    if not isinstance(dependencies, dict):
        dependencies = {}

    expected_tiptap_dependencies = {
        package_name: TIPTAP_VERSION
        for package_name in REVIEWED_TIPTAP_RUNTIME_PACKAGES
    }
    declared_reviewed_dependencies = {
        package_name: version
        for package_name, version in dependencies.items()
        if package_name in REVIEWED_TIPTAP_RUNTIME_PACKAGES
    }
    expect(
        declared_reviewed_dependencies == expected_tiptap_dependencies,
        (
            "Tiptap OSS runtime dependencies must contain the reviewed package set "
            f"at {TIPTAP_VERSION}"
        ),
    )

    aliased_tiptap_dependencies = []
    for section_name in (
        "dependencies",
        "devDependencies",
        "optionalDependencies",
        "peerDependencies",
    ):
        section = package.get(section_name, {})
        if not isinstance(section, dict):
            continue
        for dependency_name, dependency_spec in section.items():
            for package_name in TIPTAP_PACKAGE_REFERENCE.findall(
                str(dependency_spec)
            ):
                if dependency_name.casefold() != package_name.casefold():
                    aliased_tiptap_dependencies.append(
                        f"{section_name}.{dependency_name} -> {package_name}"
                    )
    expect(
        not aliased_tiptap_dependencies,
        (
            "Tiptap package aliases must use the canonical dependency key: "
            f"{', '.join(sorted(aliased_tiptap_dependencies))}"
        ),
    )

    package_source = json.dumps(package, sort_keys=True)
    referenced_tiptap_packages = {
        package_name.casefold()
        for package_name in TIPTAP_PACKAGE_REFERENCE.findall(package_source)
    }
    unreviewed_tiptap_packages = sorted(
        package_name
        for package_name in referenced_tiptap_packages
        if package_name not in REVIEWED_TIPTAP_RUNTIME_PACKAGES
    )
    expect(
        not unreviewed_tiptap_packages,
        (
            "unreviewed Tiptap package is forbidden: "
            f"{', '.join(unreviewed_tiptap_packages)}"
        ),
    )

    service_packages = sorted(
        marker
        for marker in (*TIPTAP_SERVICE_PACKAGE_PREFIXES, *TIPTAP_SERVICE_PACKAGES)
        if marker.casefold() in package_source.casefold()
    )
    expect(
        not service_packages,
        (
            "Tiptap Cloud or service package is forbidden: "
            f"{', '.join(service_packages)}"
        ),
    )

    locked_packages = package_lock.get("packages", {})
    package_lock_source = json.dumps(package_lock, sort_keys=True)
    locked_root = locked_packages.get("", {}) if isinstance(locked_packages, dict) else {}
    locked_dependencies = (
        locked_root.get("dependencies", {}) if isinstance(locked_root, dict) else {}
    )
    locked_reviewed_dependencies = {
        package_name: version
        for package_name, version in locked_dependencies.items()
        if package_name in REVIEWED_TIPTAP_RUNTIME_PACKAGES
    } if isinstance(locked_dependencies, dict) else {}
    expect(
        locked_reviewed_dependencies == expected_tiptap_dependencies,
        (
            "package-lock root metadata must preserve the reviewed Tiptap OSS "
            f"runtime dependencies at {TIPTAP_VERSION}"
        ),
    )
    expect(
        isinstance(locked_dependencies, dict) and locked_dependencies == dependencies,
        "package-lock root dependencies must match package.json runtime dependencies",
    )

    if isinstance(locked_packages, dict):
        expected_tiptap_lock_nodes = {
            (f"node_modules/{package_name}", package_name)
            for package_name in AUDITED_TIPTAP_LOCK_PACKAGES
        }
        actual_tiptap_lock_nodes = set()
        actual_tiptap_lock_edges = set()
        for package_path, locked_package in locked_packages.items():
            normalized_path = str(package_path).replace("\\", "/")
            package_name = (
                ""
                if not normalized_path
                else normalized_path.rsplit("node_modules/", 1)[-1]
            )
            path_identity = canonical_tiptap_package_reference(package_name)
            locked_name_identity = (
                canonical_tiptap_package_reference(locked_package.get("name"))
                if isinstance(locked_package, dict)
                else None
            )
            package_identity = locked_name_identity or path_identity
            if package_identity:
                actual_tiptap_lock_nodes.add(
                    (normalized_path, package_identity)
                )
            if not isinstance(locked_package, dict):
                continue
            for section_name in TIPTAP_LOCK_DEPENDENCY_SECTIONS:
                section = locked_package.get(section_name, {})
                if not isinstance(section, dict):
                    continue
                for target_name, target_version in section.items():
                    target_identity = canonical_tiptap_package_reference(
                        target_name
                    ) or canonical_tiptap_package_reference(target_version)
                    if target_identity:
                        actual_tiptap_lock_edges.add(
                            (
                                package_identity or package_name,
                                section_name,
                                target_identity,
                                str(target_version),
                            )
                        )
        expected_tiptap_lock_edges = audited_tiptap_lock_edges()
        expect(
            actual_tiptap_lock_nodes == expected_tiptap_lock_nodes
            and actual_tiptap_lock_edges == expected_tiptap_lock_edges,
            (
                "package-lock must match the audited Tiptap package-lock closure "
                f"(unexpected nodes={len(actual_tiptap_lock_nodes - expected_tiptap_lock_nodes)}, "
                f"missing nodes={len(expected_tiptap_lock_nodes - actual_tiptap_lock_nodes)}, "
                f"unexpected edges={len(actual_tiptap_lock_edges - expected_tiptap_lock_edges)}, "
                f"missing edges={len(expected_tiptap_lock_edges - actual_tiptap_lock_edges)})"
            ),
        )
        locked_service_packages = sorted(
            package_path
            for package_path in locked_packages
            if (
                any(
                    f"node_modules/{prefix}" in package_path.replace("\\", "/")
                    for prefix in TIPTAP_SERVICE_PACKAGE_PREFIXES
                )
                or any(
                    package_path.replace("\\", "/").endswith(
                        f"node_modules/{package_name}"
                    )
                    for package_name in TIPTAP_SERVICE_PACKAGES
                )
            )
        )
        expect(
            not locked_service_packages,
            "package-lock must not contain Tiptap Cloud or service packages",
        )
        expect(
            not any(
                marker.casefold() in package_lock_source.casefold()
                for marker in TIPTAP_SERVICE_PACKAGE_PREFIXES
            ),
            "package-lock must not reference Tiptap Cloud or service packages",
        )
        expect(
            frozenset(AUDITED_TIPTAP_LOCK_INTEGRITIES)
            == AUDITED_TIPTAP_LOCK_PACKAGES,
            "audited Tiptap integrity policy must cover the exact package set",
        )
        for package_name in AUDITED_TIPTAP_LOCK_PACKAGES:
            locked_package = locked_packages.get(f"node_modules/{package_name}", {})
            explicit_name = (
                locked_package.get("name")
                if isinstance(locked_package, dict)
                else None
            )
            expect(
                isinstance(locked_package, dict)
                and locked_package.get("version") == TIPTAP_LOCK_VERSION,
                (
                    "package-lock must resolve reviewed Tiptap package "
                    f"{package_name} to {TIPTAP_LOCK_VERSION}"
                ),
            )
            expect(
                isinstance(locked_package, dict)
                and locked_package.get("license") == "MIT",
                f"package-lock must preserve the MIT license for {package_name}",
            )
            expect(
                isinstance(locked_package, dict)
                and (explicit_name is None or explicit_name == package_name),
                (
                    "package-lock must preserve the canonical package identity "
                    f"for {package_name}"
                ),
            )
            package_slug = package_name.removeprefix("@tiptap/")
            expected_resolved = (
                f"https://registry.npmjs.org/{package_name}/-/"
                f"{package_slug}-{TIPTAP_LOCK_VERSION}.tgz"
            )
            expect(
                isinstance(locked_package, dict)
                and locked_package.get("resolved") == expected_resolved,
                (
                    "package-lock must preserve the exact npm resolved artifact "
                    f"for {package_name}"
                ),
            )
            expect(
                isinstance(locked_package, dict)
                and locked_package.get("integrity")
                == AUDITED_TIPTAP_LOCK_INTEGRITIES.get(package_name),
                (
                    "package-lock must preserve the audited sha512 integrity "
                    f"for {package_name}"
                ),
            )

    expect(
        TIPTAP_API_KEY.search(package_source) is None,
        "litblogs/package.json must not contain a Tiptap API key",
    )
    expect(
        EXTERNAL_EDITOR_RUNTIME.search(package_source) is None,
        "litblogs/package.json must not load an external editor runtime",
    )

    for path in editor_runtime_policy_paths():
        source = path.read_text(encoding="utf-8")
        relative_path = path.relative_to(ROOT).as_posix()
        expect(
            TIPTAP_API_KEY.search(source) is None,
            f"{relative_path} must not contain a Tiptap API key",
        )
        expect(
            EXTERNAL_EDITOR_RUNTIME.search(source) is None
            and EXTERNAL_SCRIPT_SRC.search(source) is None,
            f"{relative_path} must not load an external editor runtime",
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


def validate_maintenance_release_contract() -> None:
    deployment_check = read_text("litblogs/deployment_check.py")
    for path in MAINTENANCE_RELEASE_FILES:
        read_text(path)
        expect(
            f'"{path}"' in deployment_check,
            f"release admission must require maintenance file {path}",
        )

    service_contracts = {
        "deploy/systemd/litblogs-password-reset.service": (
            "password_reset_job",
            "/run/litblogs-maintenance-egress/password-reset.port-policy-ready",
        ),
        (
            "deploy/systemd/litblogs-upload-reconciliation.service"
        ): (
            "upload_reconciliation_job",
            "/run/litblogs-maintenance-egress/upload-reconciliation.port-policy-ready",
        ),
    }
    for path, (module, port_policy_marker) in service_contracts.items():
        unit = read_text(path)
        for fragment in (
            "Type=oneshot",
            "RuntimeMaxSec=300",
            "TimeoutStartSec=300",
            "IPAddressDeny=any",
            "RestrictAddressFamilies=AF_INET AF_INET6",
            "NoNewPrivileges=true",
            "ProtectSystem=strict",
            f"ExecStart=/opt/litblogs/current/.venv/bin/python -m {module}",
            f"ConditionPathExists=/etc/systemd/system/{Path(path).stem}.service.d/egress.conf",
            f"ConditionPathExists={port_policy_marker}",
        ):
            expect(fragment in unit, f"{path} must retain {fragment}")
        expect("AF_UNIX" not in unit, f"{path} must deny Unix-domain sockets")

    password_reset_unit = read_text(
        "deploy/systemd/litblogs-password-reset.service"
    )
    password_reset_job = read_text("litblogs/password_reset_job.py")
    password_reset_delivery = read_text("litblogs/password_reset_delivery.py")
    runtime_database_identity = read_text("litblogs/runtime_database_identity.py")
    expect(
        "import password_reset_delivery" in password_reset_job,
        "password-reset entry point must import the standalone delivery runtime",
    )
    for forbidden in (
        "from main import",
        "import main",
        "import database",
        "from database import",
        "fastapi",
        "upload_assets",
        "upload_scanner",
    ):
        expect(
            forbidden not in password_reset_job.lower(),
            f"password-reset entry point must not import {forbidden}",
        )
        expect(
            forbidden not in password_reset_delivery.lower(),
            f"password-reset delivery runtime must not import {forbidden}",
        )
    for fragment in (
        "class PasswordResetWorkerSettings",
        "database_url:",
        "frontend_url:",
        "email_host:",
        "email_port:",
        "email_smtp_timeout_seconds:",
        "password_reset_claim_timeout_seconds:",
        "verify_runtime_database_identity",
    ):
        expect(
            fragment in password_reset_delivery,
            f"password-reset delivery runtime must retain {fragment}",
        )
    expect(
        "def verify_runtime_database_identity" in runtime_database_identity,
        "runtime database identity helper must retain the shared verifier",
    )
    password_reset_lines = set(password_reset_unit.splitlines())
    for fragment in (
        "User=litblogs-reset",
        "Group=litblogs-reset",
        "EnvironmentFile=/etc/litblogs/password-reset.env",
        "InaccessiblePaths=/etc/litblogs/litblogs.env /var/lib/litblogs/uploads",
    ):
        expect(
            fragment in password_reset_lines,
            f"password-reset service must retain its dedicated boundary: {fragment}",
        )
    for fragment in ("ExecStartPre=", "ReadWritePaths="):
        expect(
            fragment not in password_reset_unit,
            f"password-reset service must not expose upload access through {fragment}",
        )
    for forbidden_line in (
        "User=litblogs",
        "Group=litblogs",
        "EnvironmentFile=/etc/litblogs/litblogs.env",
    ):
        expect(
            forbidden_line not in password_reset_lines,
            f"password-reset service must not reuse the web boundary: {forbidden_line}",
        )
    reconciliation_unit = read_text(
        "deploy/systemd/litblogs-upload-reconciliation.service"
    )
    expect(
        "ReadWritePaths=/var/lib/litblogs/uploads" in reconciliation_unit,
        "upload reconciliation must retain its narrow upload write path",
    )

    timer_conditions = {
        "deploy/systemd/litblogs-password-reset.timer": (
            (
                "ConditionPathExists=/etc/systemd/system/"
                "litblogs-password-reset.service.d/egress.conf"
            ),
            (
                "ConditionPathExists=/run/litblogs-maintenance-egress/"
                "password-reset.port-policy-ready"
            ),
        ),
        "deploy/systemd/litblogs-upload-reconciliation.timer": (
            (
                "ConditionPathExists=/etc/systemd/system/"
                "litblogs-upload-reconciliation.service.d/egress.conf"
            ),
            (
                "ConditionPathExists=/run/litblogs-maintenance-egress/"
                "upload-reconciliation.port-policy-ready"
            ),
        ),
    }
    for path, conditions in timer_conditions.items():
        timer = read_text(path)
        for fragment in (
            "OnCalendar=",
            "Persistent=true",
            "RandomizedDelaySec=",
            *conditions,
        ):
            expect(fragment in timer, f"{path} must retain {fragment}")

    for path in (
        "deploy/README.md",
        "docs/operations/production-runbook.md",
    ):
        operator_document = read_text(path)
        for fragment in (
            "IPAddressAllow` filters addresses, not destination ports"
            if path == "deploy/README.md"
            else "`IPAddressAllow` is address-only defense in depth",
            "/run/litblogs-maintenance-egress",
            "password-reset.port-policy-ready",
            "upload-reconciliation.port-policy-ready",
            "unit/cgroup-specific host-firewall",
            "configured PostgreSQL IP:port",
            "configured SMTP IP:port",
            "alternate port on every allowed IP",
            "every scanner Unix socket",
            "password_reset_delivery.py",
            "minimal worker settings",
            "does not import `main`",
            "`litblogs-reset`",
            "`/usr/sbin/nologin`",
            "no supplementary groups",
            "`/etc/litblogs/password-reset.env`",
            "`root:litblogs-reset` mode `0640`",
            "`InaccessiblePaths=/etc/litblogs/litblogs.env /var/lib/litblogs/uploads`",
            "`root:root` mode `0644`",
            "runuser -u litblogs-reset -- test -r /etc/litblogs/postgres-root-ca.pem",
            "runuser -u litblogs -- test -r /etc/litblogs/postgres-root-ca.pem",
            "service-context read and write probes",
            "recreated and revalidated each boot"
            if path == "deploy/README.md"
            else "Recreate and revalidate the marker on every boot",
            "must remain disabled",
        ):
            expect(fragment in operator_document, f"{path} must document {fragment}")

    release = read_text(".github/workflows/release.yml")
    expect(
        "git archive --format=tar HEAD -- deploy docs/operations litblogs/*.py" in release,
        "release archive must include deploy assets and maintenance entry modules",
    )
    for path in (
        "litblogs/password_reset_delivery.py",
        "litblogs/rich_text_contract.json",
        "litblogs/rich_text_contract.py",
        "litblogs/rich_text_security.py",
        "litblogs/runtime_database_identity.py",
        "litblogs/migrations/sqlite_contract.py",
    ):
        expect(
            f'test -f "$staging/tree/{path}"' in release,
            f"release packaging must prove required runtime file {path}",
        )


def validate_coupled_recovery_contract() -> None:
    deployment_check = read_text("litblogs/deployment_check.py")
    postgres_common = read_text("deploy/scripts/postgres_common.py")
    for path, source in (
        ("litblogs/deployment_check.py", deployment_check),
        ("deploy/scripts/postgres_common.py", postgres_common),
    ):
        for fragment in (
            "_postgres_ca_metadata_matches_contract",
            "required_owner_uid: int = 0",
            "required_group_gid: int = 0",
            "required_mode: int = 0o644",
            "stat.S_IMODE(metadata.st_mode) == required_mode",
        ):
            expect(fragment in source, f"{path} must retain exact CA custody: {fragment}")
    for path in COUPLED_RECOVERY_RELEASE_FILES:
        source = read_text(path)
        expect(source.strip() != "", f"coupled recovery file must not be empty: {path}")
        expect(
            f'"{path}"' in deployment_check,
            f"release admission must require coupled recovery file {path}",
        )

    backup = read_text("deploy/scripts/backup_postgres.py")
    restore = read_text("deploy/scripts/restore_verify_postgres.py")
    helper = read_text("deploy/scripts/upload_snapshot_common.py")
    for fragment in (
        '"--confirm-writes-quiesced"',
        '"--upload-root"',
        "BACKUP_ROLE_PRECHECK_SQL",
        "validate_backup_principal(connection, runner)",
        "CURRENT_USER = 'litblogs_backup'",
        "pg_catalog.current_schemas(FALSE) = ARRAY['public'::name]",
        "pg_read_all_data",
        "expected_database_acl",
        "unexpected_database_privilege",
        "direct_application_acl",
        "effective_roles",
        "database.datdba = role.role_oid",
        "namespace.nspowner = role.role_oid",
        "relation.relowner = role.role_oid",
        "routine.proowner = role.role_oid",
        "type_record.typowner = role.role_oid",
        "owned_application_objects",
        "upload_custody or production_upload_custody()",
        "require_stable_registry",
        "write_coupled_manifest",
    ):
        expect(fragment in backup, f"coupled backup must retain {fragment}")
    for forbidden in ('"--no-owner"', '"--no-acl"'):
        expect(forbidden not in backup, f"database backup must preserve {forbidden[3:-1]}")
        expect(forbidden not in restore, f"database restore must preserve {forbidden[3:-1]}")
    for fragment in (
        '"--manifest"',
        '"--upload-target"',
        "EXPECTED_ALEMBIC_HEAD = \"f1ad78b2035f\"",
        "pg_catalog.aclexplode",
        "pg_catalog.pg_auth_members",
        "expected_default_function_acl",
        "actual_default_function_acl",
        "expected_user_schemas",
        "actual_user_schemas",
        "database_acl_valid",
        "litblogs_migrator",
        "litblog_identity_owner",
        "extract_upload_archive",
        "verify_upload_tree",
    ):
        expect(fragment in restore, f"coupled restore must retain {fragment}")
    expect(
        'add_argument("--archive"' not in restore,
        "production restore CLI must not expose database-only archive restore",
    )
    for fragment in (
        "litblogs-coupled-recovery-v1",
        "USTAR_FORMAT",
        "DELETED",
        "DELETE_PENDING",
        "PRODUCTION_UPLOAD_USER = \"litblogs\"",
        "PRODUCTION_UPLOAD_ROOT_MODE = 0o750",
        "ancestor_owner_uids=frozenset({0})",
        "_ancestor_metadata_matches_contract",
        "allow_root_owned_sticky_ancestors=True",
        "allow_root_owned_sticky_ancestors=False",
        "custody.allow_root_owned_sticky_ancestors",
        "UPLOAD_ROOT_ENTRIES",
        "_require_pinned_directory",
        "restore-partial",
    ):
        expect(fragment in helper, f"coupled snapshot helper must retain {fragment}")

    recovery_docs = "\n".join(
        (
            read_text("deploy/README.md"),
            read_text("docs/operations/production-runbook.md"),
        )
    ).casefold()
    for phrase in (
        "initial legacy rollout is blocked",
        "storage-native pre-migration checkpoint",
        "upload_assets does not exist",
        "do not run backup_postgres.py",
        "offline legacy upload inventory and import",
        "current-head coupled recovery set",
        "--confirm-writes-quiesced",
        "--upload-target",
        "manifest last",
        "preserves trusted owner and acl entries",
        "exact global default-function acl",
        "schema-scoped default-function acl",
        "only non-system schema",
        "sole membership is the built-in `pg_read_all_data` role",
        "neither the backup role nor any role in its recursive membership closure may own",
        "has_database_privilege('litblogs_backup', datname, 'connect')",
        "this section classifies adoption state only",
        "not a runnable migration path",
        "do not execute alembic from this earlier section",
        "downgrade across `f1ad78b2035f`",
        "grant litblog_identity_owner to litblogs_migrator with admin false, inherit true, set true;",
        "it never runs `reassign owned`",
        "prove both membership directions are empty",
        "pg_catalog.current_schemas(false) = array['public']",
    ):
        expect(phrase in recovery_docs, f"recovery documentation must retain: {phrase}")

    workflow_contracts = {
        ".github/workflows/ci.yml": (
            "litblog_ci",
            "litblog_test_migrations_ci",
            "litblog_test_operator_ci",
        ),
        ".github/workflows/release.yml": (
            "litblog_test_release_ci",
            "litblog_test_release_migrations_ci",
            "litblog_test_release_operator_ci",
        ),
    }
    for path, (pytest_database, migration_database, operator_database) in (
        workflow_contracts.items()
    ):
        workflow = read_text(path)
        for fragment in (
            f"/{pytest_database}",
            f"/{migration_database}",
            f"/{operator_database}",
            f"CREATE DATABASE {migration_database} OWNER litblogs_migrator",
            (
                f"--dbname={migration_database} --command=\"ALTER SCHEMA public "
                "OWNER TO litblogs_migrator\""
            ),
            (
                f"CREATE DATABASE {operator_database} OWNER litblogs_migrator "
                f"TEMPLATE {migration_database}"
            ),
            "CREATE ROLE litblogs_migrator",
            "CREATE ROLE litblogs_runtime LOGIN NOINHERIT",
            "CREATE ROLE litblog_identity_owner",
            "CREATE ROLE litblog_account_operator LOGIN NOINHERIT",
            "CREATE ROLE litblog_invitation_operator LOGIN NOINHERIT",
            (
                "CREATE ROLE litblogs_backup LOGIN INHERIT NOSUPERUSER NOCREATEDB "
                "NOCREATEROLE NOREPLICATION NOBYPASSRLS"
            ),
            "GRANT pg_read_all_data TO litblogs_backup",
            "granted_role.rolname = 'pg_read_all_data'",
            "WHERE member_role.rolname = 'litblogs_backup'",
            "WHERE granted_role.rolname = 'litblogs_backup'",
            f"GRANT CONNECT ON DATABASE {operator_database} TO litblogs_backup",
            "REVOKE CONNECT, TEMPORARY ON DATABASE template1 FROM PUBLIC",
            "REVOKE CONNECT, TEMPORARY ON DATABASE template0 FROM PUBLIC",
            "has_database_privilege(",
            "'litblogs_backup', datname, 'CONNECT'",
            "'litblogs_backup', datname, 'CREATE'",
            "'litblogs_backup', datname, 'TEMPORARY'",
            "IS DISTINCT FROM (datname =",
            "POSTGRES_OPERATOR_BACKUP_DATABASE_URL",
            "POSTGRES_OPERATOR_RESTORE_DATABASE_URL",
            "GRANT litblog_identity_owner TO litblogs_migrator WITH ADMIN FALSE, INHERIT TRUE, SET TRUE",
            "REVOKE litblog_identity_owner FROM litblogs_migrator",
            "pg_auth_members",
            "ALTER ROLE litblogs_migrator NOLOGIN",
            "ALTER ROLE litblogs_runtime NOLOGIN",
            "ALTER ROLE litblog_account_operator NOLOGIN",
            "ALTER ROLE litblog_invitation_operator NOLOGIN",
        ):
            expect(fragment in workflow, f"{path} must retain recovery isolation: {fragment}")
        expect(
            workflow.count(
                "GRANT litblog_identity_owner TO litblogs_migrator "
                "WITH ADMIN FALSE, INHERIT TRUE, SET TRUE"
            )
            == workflow.count("REVOKE litblog_identity_owner FROM litblogs_migrator")
            >= 4,
            f"{path} must scope and revoke every temporary owner membership",
        )


def main() -> int:
    validate_ci()
    validate_codeql()
    validate_release()
    validate_browser_e2e_contract()
    validate_dependabot()
    validate_repository_documents()
    validate_tiptap_editor_policy()
    validate_node_runtime_contract()
    validate_python_dependency_locks()
    validate_privacy_ignores()
    validate_maintenance_release_contract()
    validate_coupled_recovery_contract()

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
