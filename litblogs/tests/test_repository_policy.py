import ast
import json
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR_PATH = REPOSITORY_ROOT / "scripts" / "validate-repository-policy.py"
CI_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml"
RELEASE_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "release.yml"
BACKEND_ROOT = REPOSITORY_ROOT / "litblogs"
EDITOR_NOTICE_PATH = BACKEND_ROOT / "THIRD_PARTY_EDITOR_NOTICES.md"
MAIN_PATH = BACKEND_ROOT / "main.py"
IDENTITY_MIGRATION_PATH = BACKEND_ROOT / "migrations" / "0003_add_identity_controls.sql"
IDENTITY_RUNBOOK_PATH = BACKEND_ROOT / "migrations" / "README-identity-controls.md"

REVIEWED_TIPTAP_RUNTIME_DEPENDENCIES = {
    "@tiptap/core": "^3.30.3",
    "@tiptap/extension-character-count": "^3.30.3",
    "@tiptap/extension-color": "^3.30.3",
    "@tiptap/extension-font-family": "^3.30.3",
    "@tiptap/extension-highlight": "^3.30.3",
    "@tiptap/extension-image": "^3.30.3",
    "@tiptap/extension-link": "^3.30.3",
    "@tiptap/extension-placeholder": "^3.30.3",
    "@tiptap/extension-table": "^3.30.3",
    "@tiptap/extension-text-align": "^3.30.3",
    "@tiptap/extension-text-style": "^3.30.3",
    "@tiptap/extension-underline": "^3.30.3",
    "@tiptap/pm": "^3.30.3",
    "@tiptap/react": "^3.30.3",
    "@tiptap/starter-kit": "^3.30.3",
}
REVIEWED_PROSEMIRROR_PACKAGES = {
    "prosemirror-changeset",
    "prosemirror-commands",
    "prosemirror-dropcursor",
    "prosemirror-gapcursor",
    "prosemirror-history",
    "prosemirror-inputrules",
    "prosemirror-keymap",
    "prosemirror-model",
    "prosemirror-schema-list",
    "prosemirror-state",
    "prosemirror-tables",
    "prosemirror-transform",
    "prosemirror-view",
}
DEFAULT_EDITOR_NOTICE = object()

SQLITE_PYTEST_STEP = """      - name: Run isolated backend tests
        working-directory: litblogs
        env:
          APP_ENV: test
          DATABASE_URL: sqlite:////tmp/litblogs-ci-test.db
          RESET_DATABASE_ON_STARTUP: \"false\"
        run: |
          # Keep application tests isolated on sqlite:/// until the role integration layer.
          python -m pytest -q
"""

POSTGRES_PYTEST_STEP = """      - name: Run guarded PostgreSQL backend tests
        working-directory: litblogs
        env:
          APP_ENV: test
          TEST_DATABASE_URL: postgresql://litblog_ci:ci-only-postgres-password@localhost:5432/litblog_ci
          DATABASE_URL: postgresql://litblog_ci:ci-only-postgres-password@localhost:5432/litblog_ci
          TEST_POSTGRES_DATABASE: litblog_ci
          ALLOW_TEST_DATABASE_DDL: \"true\"
          RESET_DATABASE_ON_STARTUP: \"false\"
        run: python -m pytest -q
"""


@pytest.fixture
def policy_validator():
    spec = spec_from_file_location("repository_policy_validator", VALIDATOR_PATH)
    assert spec is not None and spec.loader is not None
    validator = module_from_spec(spec)
    spec.loader.exec_module(validator)
    return validator


def _workflow_with_postgresql_pytest() -> str:
    workflow = CI_PATH.read_text(encoding="utf-8")
    if POSTGRES_PYTEST_STEP in workflow:
        return workflow
    assert SQLITE_PYTEST_STEP in workflow
    return workflow.replace(SQLITE_PYTEST_STEP, POSTGRES_PYTEST_STEP)


def _validate_workflow(policy_validator, tmp_path, workflow):
    workflow_path = tmp_path / ".github" / "workflows" / "ci.yml"
    workflow_path.parent.mkdir(parents=True)
    workflow_path.write_text(workflow, encoding="utf-8")

    policy_validator.ROOT = tmp_path
    policy_validator.failures.clear()
    policy_validator.validate_ci()
    return policy_validator.failures


def _validate_release_workflow(policy_validator, tmp_path, workflow):
    workflow_path = tmp_path / ".github" / "workflows" / "release.yml"
    workflow_path.parent.mkdir(parents=True)
    workflow_path.write_text(workflow, encoding="utf-8")

    policy_validator.ROOT = tmp_path
    policy_validator.failures.clear()
    policy_validator.validate_release()
    return policy_validator.failures


def _validate_tiptap_policy(
    policy_validator,
    tmp_path,
    *,
    dependencies=None,
    runtime_source="",
    backend_source="",
    index_source="",
    package_updates=None,
    lock_root_dependencies=None,
    lock_package_updates=None,
    editor_notice=DEFAULT_EDITOR_NOTICE,
):
    if dependencies is None:
        dependencies = REVIEWED_TIPTAP_RUNTIME_DEPENDENCIES
    frontend_root = tmp_path / "litblogs"
    source_root = frontend_root / "src"
    source_root.mkdir(parents=True)
    package = {"dependencies": dependencies}
    package.update(package_updates or {})
    locked_packages = {
        f"node_modules/{package_name}": {
            "version": "3.30.3",
            "license": "MIT",
        }
        for package_name in REVIEWED_TIPTAP_RUNTIME_DEPENDENCIES
    }
    locked_packages.update(lock_package_updates or {})
    package_lock = {
        "lockfileVersion": 3,
        "packages": {
            "": {
                "dependencies": (
                    dependencies
                    if lock_root_dependencies is None
                    else lock_root_dependencies
                ),
            },
            **locked_packages,
        },
    }
    (frontend_root / "package.json").write_text(
        json.dumps(package), encoding="utf-8"
    )
    (frontend_root / "package-lock.json").write_text(
        json.dumps(package_lock), encoding="utf-8"
    )
    (source_root / "editor.js").write_text(runtime_source, encoding="utf-8")
    (frontend_root / "config.py").write_text(backend_source, encoding="utf-8")
    (frontend_root / "index.html").write_text(index_source, encoding="utf-8")
    if editor_notice is DEFAULT_EDITOR_NOTICE:
        editor_notice = EDITOR_NOTICE_PATH.read_text(encoding="utf-8")
    if editor_notice is not None:
        (frontend_root / "THIRD_PARTY_EDITOR_NOTICES.md").write_text(
            editor_notice, encoding="utf-8"
        )

    policy_validator.ROOT = tmp_path
    policy_validator.failures.clear()
    policy_validator.validate_tiptap_editor_policy()
    return policy_validator.failures


def _validate_real_tiptap_lock(policy_validator, tmp_path, package_lock):
    package = json.loads(
        (BACKEND_ROOT / "package.json").read_text(encoding="utf-8")
    )
    frontend_root = tmp_path / "litblogs"
    frontend_root.mkdir(parents=True)
    (frontend_root / "package.json").write_text(
        json.dumps(package), encoding="utf-8"
    )
    (frontend_root / "package-lock.json").write_text(
        json.dumps(package_lock), encoding="utf-8"
    )
    (frontend_root / "THIRD_PARTY_EDITOR_NOTICES.md").write_text(
        EDITOR_NOTICE_PATH.read_text(encoding="utf-8"), encoding="utf-8"
    )
    policy_validator.ROOT = tmp_path
    policy_validator.failures.clear()
    policy_validator.validate_tiptap_editor_policy()
    return policy_validator.failures


def test_tiptap_editor_policy_accepts_reviewed_oss_runtime_dependencies(
    policy_validator,
):
    package = json.loads(
        (BACKEND_ROOT / "package.json").read_text(encoding="utf-8")
    )
    declared = {
        package_name: version
        for package_name, version in package["dependencies"].items()
        if package_name.startswith("@tiptap")
    }

    assert declared == REVIEWED_TIPTAP_RUNTIME_DEPENDENCIES

    policy_validator.failures.clear()
    policy_validator.validate_tiptap_editor_policy()
    assert policy_validator.failures == []


def test_tiptap_editor_notice_matches_declared_and_locked_mit_dependencies():
    package = json.loads((BACKEND_ROOT / "package.json").read_text(encoding="utf-8"))
    package_lock = json.loads(
        (BACKEND_ROOT / "package-lock.json").read_text(encoding="utf-8")
    )
    declared = {
        package_name
        for package_name in package["dependencies"]
        if package_name.startswith("@tiptap/")
    }
    locked_licenses = {
        package_name: package_lock["packages"][f"node_modules/{package_name}"][
            "license"
        ]
        for package_name in declared
    }
    declared_prosemirror = set(
        package_lock["packages"]["node_modules/@tiptap/pm"]["dependencies"]
    )
    locked_prosemirror_licenses = {
        package_name: package_lock["packages"][f"node_modules/{package_name}"][
            "license"
        ]
        for package_name in declared_prosemirror
    }
    normalized_notice = " ".join(EDITOR_NOTICE_PATH.read_text(encoding="utf-8").split())

    assert declared == set(REVIEWED_TIPTAP_RUNTIME_DEPENDENCIES)
    assert set(locked_licenses) == declared
    assert set(locked_licenses.values()) == {"MIT"}
    assert declared_prosemirror == REVIEWED_PROSEMIRROR_PACKAGES
    assert set(locked_prosemirror_licenses) == declared_prosemirror
    assert set(locked_prosemirror_licenses.values()) == {"MIT"}
    assert all(
        f"- {package_name}" in normalized_notice
        for package_name in declared_prosemirror
    )
    assert "Copyright (c) 2025, Tiptap GmbH" in normalized_notice
    assert (
        "Copyright (C) 2015-2017 by Marijn Haverbeke "
        "<marijn@haverbeke.berlin> and others" in normalized_notice
    )
    assert normalized_notice.count(
        "Permission is hereby granted, free of charge, to any person obtaining a copy"
    ) == 2
    assert normalized_notice.count('THE SOFTWARE IS PROVIDED "AS IS"') == 2


def test_tiptap_editor_policy_requires_complete_third_party_notices(
    policy_validator, tmp_path
):
    failures = _validate_tiptap_policy(
        policy_validator,
        tmp_path,
        editor_notice="MIT License\n",
    )

    assert any("editor third-party notices" in failure for failure in failures)


def test_tiptap_editor_policy_requires_third_party_notice_file(
    policy_validator, tmp_path
):
    failures = _validate_tiptap_policy(
        policy_validator, tmp_path, editor_notice=None
    )

    assert any(
        "missing required file: litblogs/THIRD_PARTY_EDITOR_NOTICES.md" in failure
        for failure in failures
    )


def test_tiptap_editor_policy_rejects_non_mit_prosemirror_lock_metadata(
    policy_validator, tmp_path
):
    package_lock = json.loads(
        (BACKEND_ROOT / "package-lock.json").read_text(encoding="utf-8")
    )
    package_lock["packages"]["node_modules/prosemirror-model"][
        "license"
    ] = "Apache-2.0"

    failures = _validate_real_tiptap_lock(
        policy_validator, tmp_path, package_lock
    )

    assert any(
        "MIT license for ProseMirror editor dependency prosemirror-model" in failure
        for failure in failures
    )


def test_tiptap_editor_policy_rejects_unreviewed_tiptap_packages(
    policy_validator, tmp_path
):
    dependencies = {
        **REVIEWED_TIPTAP_RUNTIME_DEPENDENCIES,
        "@tiptap/extension-collaboration": "^3.30.2",
    }

    failures = _validate_tiptap_policy(
        policy_validator, tmp_path, dependencies=dependencies
    )

    assert any("unreviewed Tiptap package" in failure for failure in failures)


@pytest.mark.parametrize(
    "package_name",
    (
        "@tiptap-pro/provider",
        "@tiptap-cloud/provider",
        "@hocuspocus/provider",
    ),
)
def test_tiptap_editor_policy_rejects_cloud_and_service_packages(
    policy_validator, tmp_path, package_name
):
    dependencies = {
        **REVIEWED_TIPTAP_RUNTIME_DEPENDENCIES,
        package_name: "^3.30.2",
    }

    failures = _validate_tiptap_policy(
        policy_validator, tmp_path, dependencies=dependencies
    )

    assert any("Tiptap Cloud or service package" in failure for failure in failures)


def test_tiptap_editor_policy_rejects_service_package_aliases(
    policy_validator, tmp_path
):
    dependencies = {
        **REVIEWED_TIPTAP_RUNTIME_DEPENDENCIES,
        "editor-provider": "npm:@tiptap-pro/provider@^3.30.2",
    }

    failures = _validate_tiptap_policy(
        policy_validator, tmp_path, dependencies=dependencies
    )

    assert any("Tiptap Cloud or service package" in failure for failure in failures)


def test_tiptap_editor_policy_rejects_reviewed_packages_under_alias_keys(
    policy_validator, tmp_path
):
    dependencies = {
        **REVIEWED_TIPTAP_RUNTIME_DEPENDENCIES,
        "editor-core": "npm:@tiptap/core@^3.30.2",
    }

    failures = _validate_tiptap_policy(
        policy_validator, tmp_path, dependencies=dependencies
    )

    assert any("canonical dependency key" in failure for failure in failures)


def test_tiptap_editor_policy_rejects_unreviewed_lock_root_packages(
    policy_validator, tmp_path
):
    lock_root_dependencies = {
        **REVIEWED_TIPTAP_RUNTIME_DEPENDENCIES,
        "@tiptap/extension-collaboration": "^3.30.2",
    }

    failures = _validate_tiptap_policy(
        policy_validator,
        tmp_path,
        lock_root_dependencies=lock_root_dependencies,
    )

    assert any("package-lock root" in failure for failure in failures)


@pytest.mark.parametrize("mutation", ("node", "edge"))
def test_tiptap_editor_policy_rejects_unapproved_transitive_lock_closure(
    policy_validator, tmp_path, mutation
):
    package = json.loads(
        (BACKEND_ROOT / "package.json").read_text(encoding="utf-8")
    )
    package_lock = json.loads(
        (BACKEND_ROOT / "package-lock.json").read_text(encoding="utf-8")
    )
    if mutation == "node":
        package_lock["packages"][
            "node_modules/@tiptap/extension-collaboration"
        ] = {
            "version": "3.30.2",
            "license": "MIT",
            "peerDependencies": {"@tiptap/core": "3.30.2"},
        }
    else:
        package_lock["packages"]["node_modules/@tiptap/starter-kit"][
            "dependencies"
        ]["@tiptap/extension-collaboration"] = "3.30.2"

    frontend_root = tmp_path / "litblogs"
    frontend_root.mkdir(parents=True)
    (frontend_root / "package.json").write_text(
        json.dumps(package), encoding="utf-8"
    )
    (frontend_root / "package-lock.json").write_text(
        json.dumps(package_lock), encoding="utf-8"
    )
    policy_validator.ROOT = tmp_path
    policy_validator.failures.clear()
    policy_validator.validate_tiptap_editor_policy()

    assert any(
        "audited Tiptap package-lock closure" in failure
        for failure in policy_validator.failures
    )


@pytest.mark.parametrize(
    ("mutation", "alias_spec"),
    (
        (
            "node-and-edge",
            "npm:@tiptap/extension-collaboration@3.30.2",
        ),
        ("node", None),
        ("edge", "npm:@tiptap/extension-collaboration@3.30.2"),
        ("edge", "npm:@tiptap/extension-collaboration"),
        ("edge", "npm:@tiptap/extension-collaboration@"),
    ),
)
def test_tiptap_editor_policy_rejects_transitive_tiptap_alias_identity(
    policy_validator, tmp_path, mutation, alias_spec
):
    package_lock = json.loads(
        (BACKEND_ROOT / "package-lock.json").read_text(encoding="utf-8")
    )
    if mutation in {"node", "node-and-edge"}:
        package_lock["packages"]["node_modules/collaboration-extension"] = {
            "name": "@tiptap/extension-collaboration",
            "version": "3.30.2",
            "license": "MIT",
        }
    if mutation in {"edge", "node-and-edge"}:
        package_lock["packages"]["node_modules/@tiptap/starter-kit"][
            "dependencies"
        ]["collaboration-extension"] = alias_spec

    failures = _validate_real_tiptap_lock(
        policy_validator, tmp_path, package_lock
    )

    assert any(
        "audited Tiptap package-lock closure" in failure
        for failure in failures
    )


def test_tiptap_editor_policy_allows_non_tiptap_transitive_aliases(
    policy_validator, tmp_path
):
    package_lock = json.loads(
        (BACKEND_ROOT / "package-lock.json").read_text(encoding="utf-8")
    )
    package_lock["packages"]["node_modules/@tiptap/starter-kit"][
        "dependencies"
    ]["floating-engine"] = "npm:@floating-ui/dom@1.8.0"
    package_lock["packages"]["node_modules/floating-engine"] = {
        "name": "@floating-ui/dom",
        "version": "1.8.0",
        "license": "MIT",
    }

    failures = _validate_real_tiptap_lock(
        policy_validator, tmp_path, package_lock
    )

    assert failures == []


@pytest.mark.parametrize(
    ("mutation", "expected_failure"),
    (
        ("explicit-name", "canonical package identity"),
        ("resolved", "resolved artifact"),
        ("integrity", "sha512 integrity"),
        ("missing-integrity", "sha512 integrity"),
    ),
)
def test_tiptap_editor_policy_rejects_audited_node_metadata_substitution(
    policy_validator, tmp_path, mutation, expected_failure
):
    package_lock = json.loads(
        (BACKEND_ROOT / "package-lock.json").read_text(encoding="utf-8")
    )
    locked_core = package_lock["packages"]["node_modules/@tiptap/core"]
    if mutation == "explicit-name":
        locked_core["name"] = "innocent-editor-core"
    elif mutation == "resolved":
        locked_core["resolved"] = (
            "https://registry.npmjs.org/@tiptap/core/-/core-3.30.3-repacked.tgz"
        )
    elif mutation == "integrity":
        locked_core["integrity"] = "sha512-dGVzdC1wbGFjZWhvbGRlcg=="
    else:
        locked_core.pop("integrity")

    failures = _validate_real_tiptap_lock(
        policy_validator, tmp_path, package_lock
    )

    assert any(expected_failure in failure for failure in failures)


def test_tiptap_editor_policy_accepts_matching_explicit_lock_node_name(
    policy_validator, tmp_path
):
    package_lock = json.loads(
        (BACKEND_ROOT / "package-lock.json").read_text(encoding="utf-8")
    )
    package_lock["packages"]["node_modules/@tiptap/core"][
        "name"
    ] = "@tiptap/core"

    failures = _validate_real_tiptap_lock(
        policy_validator, tmp_path, package_lock
    )

    assert failures == []


@pytest.mark.parametrize(
    ("metadata", "expected_failure"),
    (
        ({"version": "3.30.1", "license": "MIT"}, "resolve reviewed Tiptap"),
        ({"version": "3.30.3", "license": "SEE LICENSE"}, "MIT license"),
    ),
)
def test_tiptap_editor_policy_rejects_unreviewed_lock_metadata(
    policy_validator, tmp_path, metadata, expected_failure
):
    failures = _validate_tiptap_policy(
        policy_validator,
        tmp_path,
        lock_package_updates={"node_modules/@tiptap/core": metadata},
    )

    assert any(expected_failure in failure for failure in failures)


@pytest.mark.parametrize(
    ("runtime_source", "expected_failure"),
    (
        (
            "const apiKey = import.meta.env.VITE_TIPTAP_API_KEY;",
            "Tiptap API key",
        ),
        (
            "import { Editor } from 'https://esm.sh/@tiptap/core';",
            "external editor runtime",
        ),
        (
            "const script = 'https://cdn.tiny.cloud/1/key/tinymce/8/tinymce.min.js';",
            "external editor runtime",
        ),
    ),
)
def test_tiptap_editor_policy_rejects_keys_and_external_editor_runtimes(
    policy_validator, tmp_path, runtime_source, expected_failure
):
    failures = _validate_tiptap_policy(
        policy_validator, tmp_path, runtime_source=runtime_source
    )

    assert any(expected_failure in failure for failure in failures)


def test_tiptap_editor_policy_rejects_any_remote_editor_script(
    policy_validator, tmp_path
):
    failures = _validate_tiptap_policy(
        policy_validator,
        tmp_path,
        index_source='<script src="https://cdn.example.test/editor.js"></script>',
    )

    assert any("external editor runtime" in failure for failure in failures)


def test_tiptap_editor_policy_rejects_backend_tiptap_credentials(
    policy_validator, tmp_path
):
    failures = _validate_tiptap_policy(
        policy_validator,
        tmp_path,
        backend_source="TIPTAP_CLOUD_SECRET = 'test-placeholder'",
    )

    assert any("Tiptap API key" in failure for failure in failures)


def test_policy_validator_accepts_guarded_postgresql_backend_pytest(
    policy_validator, tmp_path
):
    failures = _validate_workflow(
        policy_validator,
        tmp_path,
        _workflow_with_postgresql_pytest(),
    )

    assert failures == []


def test_policy_validator_rejects_sqlite_backend_pytest(policy_validator, tmp_path):
    sqlite_workflow = _workflow_with_postgresql_pytest().replace(
        "postgresql://litblog_ci:ci-only-postgres-password@localhost:5432/litblog_ci",
        "sqlite:////tmp/litblogs-ci-test.db",
    )

    failures = _validate_workflow(policy_validator, tmp_path, sqlite_workflow)

    assert any("guarded synthetic PostgreSQL" in failure for failure in failures)


def test_policy_validator_rejects_eol_node_major(policy_validator, tmp_path):
    node_24_workflow = CI_PATH.read_text(encoding="utf-8").replace(
        'node-version: "20"', 'node-version: "24"'
    )
    node_20_workflow = node_24_workflow.replace(
        'node-version: "24"', 'node-version: "20"'
    )

    failures = _validate_workflow(policy_validator, tmp_path, node_20_workflow)

    assert any("Node 24" in failure for failure in failures)


def test_node_runtime_contract_pins_supported_major_24(policy_validator):
    package = json.loads(
        (BACKEND_ROOT / "package.json").read_text(encoding="utf-8")
    )

    assert package["engines"] == {"node": "24.x"}
    assert (BACKEND_ROOT / ".nvmrc").read_text(encoding="utf-8") == "24\n"
    assert (BACKEND_ROOT / ".node-version").read_text(encoding="utf-8") == "24\n"

    policy_validator.failures.clear()
    policy_validator.validate_node_runtime_contract()
    assert policy_validator.failures == []


def test_security_reporting_rejects_a_stale_repository_host(
    policy_validator, tmp_path
):
    canonical = "https://github.com/citdrhs/LitBlogs/security/advisories/new"
    stale = "https://github.com/Antigro09/LitBlog/security/advisories/new"
    issue_config = tmp_path / ".github" / "ISSUE_TEMPLATE" / "config.yml"
    issue_config.parent.mkdir(parents=True)
    issue_config.write_text(
        "blank_issues_enabled: false\n"
        "contact_links:\n"
        "  - name: Private security report\n"
        f"    url: {canonical}\n"
        "    about: Private advisory\n",
        encoding="utf-8",
    )
    (tmp_path / "SECURITY.md").write_text(
        f"Report privately at {canonical}.\n", encoding="utf-8"
    )
    policy_validator.ROOT = tmp_path
    policy_validator.failures.clear()
    policy_validator.validate_security_reporting()
    assert policy_validator.failures == []

    issue_config.write_text(
        issue_config.read_text(encoding="utf-8").replace(canonical, stale),
        encoding="utf-8",
    )
    (tmp_path / "SECURITY.md").write_text(
        f"Report privately at {stale}.\n", encoding="utf-8"
    )
    policy_validator.failures.clear()
    policy_validator.validate_security_reporting()

    assert any("canonical private advisory" in failure for failure in policy_validator.failures)


def test_backend_entrypoint_does_not_mix_local_module_import_styles():
    tree = ast.parse(MAIN_PATH.read_text(encoding="utf-8"))
    local_modules = {path.stem for path in BACKEND_ROOT.glob("*.py")}
    directly_imported = {
        alias.name.partition(".")[0]
        for node in tree.body
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_from = {
        node.module.partition(".")[0]
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module
    }

    mixed_local_imports = local_modules & directly_imported & imported_from

    assert mixed_local_imports == set()


def test_identity_migration_is_additive_digest_only_and_indexed():
    migration = IDENTITY_MIGRATION_PATH.read_text(encoding="utf-8").casefold()

    assert "begin;" in migration
    assert "commit;" in migration
    assert "alter table users" in migration
    assert "add column if not exists disabled_at timestamptz" in migration
    assert "uq_users_email_normalized" in migration
    assert "on users (email varchar_pattern_ops)" in migration
    assert "create table browser_sessions" in migration
    assert "create table teacher_invitations" in migration
    assert "create table operator_audit_events" in migration
    assert "ck_users_email_ascii" in migration
    assert "octet_length(email) = char_length(email)" in migration
    assert "ck_users_email_canonical" in migration
    assert "ck_users_email_no_whitespace" in migration
    assert "ck_users_email_no_controls" in migration
    assert "[[:cntrl:]]" in migration
    assert "translate(" in migration
    assert 'collate "c"' in migration
    assert "lower(" not in migration
    assert "update users" in migration
    assert "set email = translate(" in migration
    assert "update teachers" in migration
    assert "set user_id" in migration
    assert "uq_teachers_user_id" in migration
    assert "ck_teachers_email_ascii" in migration
    assert "ck_teachers_email_canonical" in migration
    assert "ck_teachers_email_no_whitespace" in migration
    assert "ck_teachers_email_no_controls" in migration
    assert "alter column email type varchar(100)" in migration
    assert "delivery_claim_digest varchar(64)" in migration
    assert "ck_password_reset_delivery_claim_digest" in migration
    assert "update password_resets" in migration
    assert "token = null" in migration
    assert "expires_at = null" in migration
    assert "used = true" in migration
    assert "delivery_status = 'failed'" in migration
    assert "end;" in migration
    assert "jti_digest varchar(64)" in migration
    assert "token_digest varchar(64)" in migration
    assert "email_digest varchar(64)" in migration
    assert "length(jti_digest) = 64" in migration
    assert "length(token_digest) = 64" in migration
    assert "length(email_digest) = 64" in migration
    assert "references users(id) on delete cascade" in migration
    assert "uq_teacher_invitation_active_email" in migration
    assert "where consumed_at is null and revoked_at is null" in migration
    assert "ix_browser_sessions_expires_at" in migration
    assert "ix_browser_sessions_user_id" in migration
    assert "ix_browser_sessions_user_recency" in migration
    assert "ix_teacher_invitations_expires_at" in migration
    assert "ix_teacher_invitations_email_digest" in migration
    assert "actor_identifier varchar(100)" in migration
    assert "action varchar(64)" in migration
    assert "outcome varchar(16)" in migration
    assert "resource_digest varchar(64)" in migration
    assert "length(resource_digest) = 64" in migration
    assert "ck_operator_audit_action" in migration
    assert "ck_operator_audit_outcome" in migration
    assert "ck_operator_audit_actor_identifier" in migration
    assert "ck_teacher_invitation_created_by" in migration
    assert "ix_operator_audit_events_created_at" in migration

    for forbidden_column in ("token", "jti", "email", "session_token"):
        assert not any(
            line.strip().startswith(f"{forbidden_column} ")
            and "=" not in line
            for line in migration.splitlines()
        )
    assert "insert into browser_sessions" not in migration


def test_identity_migration_runbook_documents_invalidation_and_reversible_rollback():
    runbook = IDENTITY_RUNBOOK_PATH.read_text(encoding="utf-8").casefold()
    normalized_runbook = " ".join(runbook.split())

    assert "all pre-migration jwt" in runbook
    assert "no session backfill" in runbook
    assert "stop" in runbook
    assert "having count(*) > 1" in runbook
    assert "roll back the application code" in runbook
    assert "insert-only" in runbook
    assert "alter default privileges" in runbook
    assert "alembic" in runbook
    assert "0002_add_authorization_constraints.sql" in runbook
    assert "0003_add_identity_controls.sql" in runbook
    assert "must not ship" in runbook
    assert "must not retain the secret-bearing stdout" in runbook
    assert "command/output audit is retained" not in runbook
    assert "octet_length(email) <> char_length(email)" in runbook
    assert "translate(btrim(email)" in runbook
    assert 'collate "c"' in runbook
    assert "teachers.user_id" in runbook
    assert "password_resets" in runbook
    assert "retain the additive identity schema" in normalized_runbook
    assert "rotate the jwt signing key" in normalized_runbook
    assert "maximum token lifetime plus configured clock skew" in normalized_runbook
    assert "disabled-account containment" in normalized_runbook
    assert "export and retain" in normalized_runbook
    assert "separately approved schema-retirement migration" in normalized_runbook
    assert "drop table browser_sessions;" not in runbook
    assert "drop table operator_audit_events;" not in runbook
    assert "alter table users drop column disabled_at" not in runbook


def test_shared_teacher_code_and_public_invitation_contracts_are_absent():
    production_paths = (
        BACKEND_ROOT / "config.py",
        BACKEND_ROOT / "schemas.py",
        BACKEND_ROOT / "main.py",
        BACKEND_ROOT / "src" / "Sign-up.jsx",
        BACKEND_ROOT / ".env.example",
    )
    combined = "\n".join(
        path.read_text(encoding="utf-8") for path in production_paths
    )

    assert "TEACHER_ACCESS_CODE" not in combined
    assert "teacher_access_code" not in combined
    assert "accessCode" not in (BACKEND_ROOT / "src" / "Sign-up.jsx").read_text(
        encoding="utf-8"
    )


def test_workflows_isolate_pytest_migrations_and_coupled_operator_recovery():
    exact_owner_membership_grant = (
        "GRANT litblog_identity_owner TO litblogs_migrator "
        "WITH ADMIN FALSE, INHERIT TRUE, SET TRUE"
    )
    contracts = {
        CI_PATH: (
            "litblog_ci",
            "litblog_test_migrations_ci",
            "litblog_test_operator_ci",
            "postgresql://litblogs_migrator:ci-only-migrator-password@"
            "localhost:5432/litblog_test_migrations_ci",
        ),
        RELEASE_PATH: (
            "litblog_test_release_ci",
            "litblog_test_release_migrations_ci",
            "litblog_test_release_operator_ci",
            "postgresql://litblogs_migrator:release-ci-only-migrator-password@"
            "localhost:5432/litblog_test_release_migrations_ci",
        ),
    }

    for path, (
        pytest_database,
        migration_database,
        operator_database,
        migration_database_url,
    ) in contracts.items():
        workflow = path.read_text(encoding="utf-8")
        assert f"/{pytest_database}" in workflow
        assert f"/{migration_database}" in workflow
        assert f"/{operator_database}" in workflow
        assert f"CREATE DATABASE {migration_database} OWNER litblogs_migrator" in workflow
        assert f"TEST_DATABASE_URL: {migration_database_url}" in workflow
        assert f"LITBLOGS_MIGRATION_DATABASE_URL: {migration_database_url}" in workflow
        assert (
            f"CREATE DATABASE {operator_database} OWNER litblogs_migrator "
            f"TEMPLATE {migration_database}" in workflow
        )
        for role_name in (
            "litblogs_migrator",
            "litblogs_runtime",
            "litblog_identity_owner",
            "litblog_account_operator",
            "litblog_invitation_operator",
        ):
            assert f"CREATE ROLE {role_name}" in workflow
        assert (
            "CREATE ROLE litblogs_backup LOGIN INHERIT NOSUPERUSER NOCREATEDB "
            "NOCREATEROLE NOREPLICATION NOBYPASSRLS" in workflow
        )
        assert "GRANT pg_read_all_data TO litblogs_backup" in workflow
        assert "granted_role.rolname = 'pg_read_all_data'" in workflow
        assert "WHERE member_role.rolname = 'litblogs_backup'" in workflow
        assert "WHERE granted_role.rolname = 'litblogs_backup'" in workflow
        assert f"GRANT CONNECT ON DATABASE {operator_database} TO litblogs_backup" in workflow
        assert "REVOKE CONNECT, TEMPORARY ON DATABASE template1 FROM PUBLIC" in workflow
        assert "REVOKE CONNECT, TEMPORARY ON DATABASE template0 FROM PUBLIC" in workflow
        assert "has_database_privilege(" in workflow
        assert "'litblogs_backup', datname, 'CONNECT'" in workflow
        assert "'litblogs_backup', datname, 'CREATE'" in workflow
        assert "'litblogs_backup', datname, 'TEMPORARY'" in workflow
        assert "IS DISTINCT FROM (datname =" in workflow
        assert "POSTGRES_OPERATOR_BACKUP_DATABASE_URL" in workflow
        assert "POSTGRES_OPERATOR_RESTORE_DATABASE_URL" in workflow
        assert exact_owner_membership_grant in workflow
        assert "REVOKE litblog_identity_owner FROM litblogs_migrator" in workflow
        assert workflow.count(exact_owner_membership_grant) == workflow.count(
            "REVOKE litblog_identity_owner FROM litblogs_migrator"
        )
        assert "pg_auth_members" in workflow
        assert workflow.index(f"/{pytest_database}") < workflow.index(
            f"/{migration_database}"
        )

    browser_database_helper = (
        BACKEND_ROOT / "e2e/support/database.py"
    ).read_text(encoding="utf-8")
    browser_database_tree = ast.parse(browser_database_helper)
    assert exact_owner_membership_grant in {
        node.value
        for node in ast.walk(browser_database_tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }

    for document_path in (
        REPOSITORY_ROOT / "docs/operations/production-runbook.md",
        BACKEND_ROOT / "migrations/README-identity-controls.md",
    ):
        document = document_path.read_text(encoding="utf-8")
        assert exact_owner_membership_grant in document
        assert "REASSIGN OWNED" in document
        assert "does not" in document or "never" in document


def test_identity_primitives_do_not_log_or_print_raw_values():
    identity_source = (BACKEND_ROOT / "identity_controls.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(identity_source)
    forbidden_calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id == "print":
            forbidden_calls.append(node.func.id)
        if isinstance(node.func, ast.Attribute) and node.func.attr in {
            "debug",
            "info",
            "warning",
            "error",
            "exception",
            "critical",
        }:
            forbidden_calls.append(node.func.attr)

    assert forbidden_calls == []


def test_operator_target_email_is_private_input_not_process_metadata():
    cli_source = "\n".join(
        (BACKEND_ROOT / path).read_text(encoding="utf-8")
        for path in ("manage_accounts.py", "manage_teacher_invitations.py")
    )
    operator_docs = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            BACKEND_ROOT.parent / "README.md",
            IDENTITY_RUNBOOK_PATH,
        )
    ).casefold()

    assert 'add_argument("--email"' not in cli_source
    assert "from database import" not in cli_source
    assert "get_settings" not in cli_source
    assert "build_operator_runtime" in cli_source
    assert "--email" not in operator_docs
    assert "protected stdin" in operator_docs
    assert "never" in operator_docs and "argv" in operator_docs
    assert "file descriptor 3" in operator_docs
    assert "current_user" in operator_docs
    assert "sslmode=verify-full" in operator_docs
    assert "expected_database_role" not in operator_docs
    assert "/etc/litblogs/postgres-root-ca.pem" in operator_docs
    assert "root-owned" in operator_docs


def test_account_operator_is_limited_to_reviewed_user_columns():
    account_cli_source = (BACKEND_ROOT / "manage_accounts.py").read_text(
        encoding="utf-8"
    )
    runbook = IDENTITY_RUNBOOK_PATH.read_text(encoding="utf-8")
    normalized_runbook = " ".join(runbook.split())
    migration = IDENTITY_MIGRATION_PATH.read_text(encoding="utf-8")
    normalized_migration = " ".join(migration.split())

    assert "db.query(models.User)" not in account_cli_source
    assert "models.User.password" not in account_cli_source
    assert "update(models.User)" not in account_cli_source
    assert "public.operator_set_account_status" in account_cli_source
    assert "SECURITY DEFINER" in migration
    assert "SET search_path = pg_catalog, pg_temp" in normalized_migration
    assert "REVOKE ALL ON FUNCTION public.operator_set_account_status" in (
        normalized_migration
    )
    assert "REVOKE CREATE ON SCHEMA public FROM PUBLIC" in normalized_migration
    assert "CAST(:email AS VARCHAR(100))" in account_cli_source
    assert "CAST(:actor_identifier AS VARCHAR(100))" in account_cli_source
    assert "CAST(:resource_digest AS VARCHAR(64))" in account_cli_source
    assert "ck_operator_audit_resource_digest_lower_hex" in migration
    assert "ck_operator_audit_actor_identifier_format" in migration
    assert "ck_teacher_invitation_token_digest_lower_hex" in migration
    assert "ck_browser_session_jti_digest_lower_hex" in migration
    operator_runtime_source = (BACKEND_ROOT / "operator_runtime.py").read_text(
        encoding="utf-8"
    )
    assert "memberships.member = roles.oid" in operator_runtime_source
    assert "memberships.roleid = roles.oid" in operator_runtime_source
    assert "memberships.member = owners.oid" in operator_runtime_source
    assert "memberships.roleid = owners.oid" in operator_runtime_source
    assert (
        "has_schema_privilege( 'litblog_identity_owner', 'public', 'CREATE'"
        in " ".join(operator_runtime_source.split())
    )
    assert "operator_function_acl_is_exact" in operator_runtime_source
    assert "unexpected_roles.rolname" in operator_runtime_source
    assert '"-c search_path=pg_catalog "' in operator_runtime_source
    assert "GRANT EXECUTE ON FUNCTION public.operator_set_account_status" in (
        normalized_runbook
    )
    assert "no direct table privileges" in runbook
    assert "SELECT id, email, disabled_at, password FROM users" in normalized_runbook
    assert "UPDATE users SET password" in normalized_runbook
    assert "UPDATE password_resets SET token" in normalized_runbook
    assert "UPDATE browser_sessions SET revoked_at" in normalized_runbook
    assert "SQLSTATE 42501" in runbook
    assert "must not inherit" in runbook
    assert (
        "BEGIN; GRANT CREATE ON SCHEMA public TO litblog_identity_owner;"
        in normalized_runbook
    )
    handoff_start = normalized_runbook.index(
        "BEGIN; GRANT CREATE ON SCHEMA public TO litblog_identity_owner;"
    )
    handoff_revoke = normalized_runbook.index(
        "REVOKE CREATE ON SCHEMA public FROM litblog_identity_owner;",
        handoff_start,
    )
    handoff_commit = normalized_runbook.index("COMMIT;", handoff_revoke)
    assert handoff_start < handoff_revoke < handoff_commit
    assert "pg_catalog.aclexplode" in runbook
    assert "unexpected_function_grantee" in runbook


def test_policy_validator_accepts_protected_immutable_release_workflow(policy_validator):
    assert RELEASE_PATH.is_file()

    policy_validator.failures.clear()
    policy_validator.validate_release()

    assert policy_validator.failures == []


def test_gitignore_policy_blocks_private_uploads_and_local_databases(policy_validator):
    policy_validator.failures.clear()
    policy_validator.validate_privacy_ignores()

    assert policy_validator.failures == []


def test_policy_validator_requires_rich_text_security_release_admission(
    policy_validator, tmp_path
):
    workflow = RELEASE_PATH.read_text(encoding="utf-8")
    required = 'test -f "$staging/tree/litblogs/rich_text_security.py"'
    assert required in workflow

    failures = _validate_release_workflow(
        policy_validator,
        tmp_path,
        workflow.replace(required, "true # weakened rich-text runtime admission", 1),
    )

    assert any("rich_text_security.py" in failure for failure in failures)


def test_policy_validator_requires_editor_notice_release_admission(
    policy_validator, tmp_path
):
    workflow = RELEASE_PATH.read_text(encoding="utf-8")
    required = 'test -f "$staging/tree/litblogs/THIRD_PARTY_EDITOR_NOTICES.md"'
    assert required in workflow

    failures = _validate_release_workflow(
        policy_validator,
        tmp_path,
        workflow.replace(required, "true # weakened editor notice admission", 1),
    )

    assert any("THIRD_PARTY_EDITOR_NOTICES.md" in failure for failure in failures)


def test_ci_browser_gate_is_mandatory_and_uploads_only_sanitized_failures(
    policy_validator,
):
    workflow, _ = policy_validator.load_yaml(".github/workflows/ci.yml")
    browser_job = workflow["jobs"]["browser-journeys"]
    commands = policy_validator.step_commands(browser_job)

    assert browser_job["name"] == "Browser release journeys"
    assert browser_job["services"]["postgres"]["env"] == {
        "POSTGRES_USER": "litblogs_e2e_admin",
        "POSTGRES_PASSWORD": "e2e-ci-only-postgres-password",
        "POSTGRES_DB": "postgres",
        "POSTGRES_INITDB_ARGS": (
            "--auth-host=scram-sha-256 --auth-local=scram-sha-256"
        ),
    }
    assert "npm ci" in commands
    assert "node --test e2e/support/availability.test.mjs" in commands
    assert "node --test e2e/support/sanitized-reporter.test.mjs" in commands
    assert "npx playwright install --with-deps chromium" in commands
    assert "npm run test:e2e" in commands
    browser_steps = browser_job["steps"]
    journey_step = next(step for step in browser_steps if step.get("name") == "Run eight browser journeys")
    assert journey_step["env"] == {
        "CI": "true",
        "E2E_ADMIN_DATABASE_URL": (
            "postgresql+psycopg2://litblogs_e2e_admin:"
            "e2e-ci-only-postgres-password@127.0.0.1:5432/postgres"
        ),
        "E2E_DISPOSABLE_DATABASE_CONFIRMED": "litblogs-e2e-only",
        "E2E_REQUIRE_AVAILABLE": "true",
    }
    upload_step = next(
        step
        for step in browser_steps
        if str(step.get("uses", "")).startswith("actions/upload-artifact@")
    )
    assert upload_step["if"] == "failure()"
    assert upload_step["with"]["path"] == (
        "litblogs/test-results/e2e/sanitized-failures/*.json"
    )
    assert upload_step["with"]["retention-days"] == 3


def test_release_packaging_depends_on_unprivileged_browser_gate(policy_validator):
    workflow, _ = policy_validator.load_yaml(".github/workflows/release.yml")
    browser_job = workflow["jobs"]["browser-journeys"]
    commands = policy_validator.step_commands(browser_job)

    assert "environment" not in browser_job
    assert browser_job["permissions"] == {"contents": "read"}
    assert browser_job["if"] == "github.ref == 'refs/heads/main'"
    assert "node --test e2e/support/availability.test.mjs" in commands
    assert "node --test e2e/support/sanitized-reporter.test.mjs" in commands
    journey_step = next(
        step
        for step in browser_job["steps"]
        if step.get("name") == "Run eight browser journeys"
    )
    assert journey_step["env"]["E2E_REQUIRE_AVAILABLE"] == "true"
    assert workflow["jobs"]["build-release"]["needs"] == "browser-journeys"
    protected_jobs = [
        job_id
        for job_id, job in workflow["jobs"].items()
        if job.get("environment") == "production-release"
    ]
    assert protected_jobs == ["attest-release"]


def test_policy_validator_rejects_protected_browser_execution(
    policy_validator, tmp_path
):
    workflow = RELEASE_PATH.read_text(encoding="utf-8")
    unprivileged_browser = """    permissions:
      contents: read
    services:
"""
    assert unprivileged_browser in workflow
    protected_browser = """    environment: production-release
    permissions:
      contents: read
    services:
"""
    weakened = workflow.replace(unprivileged_browser, protected_browser, 1)

    failures = _validate_release_workflow(policy_validator, tmp_path, weakened)

    assert any("must not enter" in failure for failure in failures)


def test_policy_validator_rejects_weakened_browser_disposal_confirmation(
    policy_validator, tmp_path
):
    workflow = CI_PATH.read_text(encoding="utf-8")
    required = "E2E_DISPOSABLE_DATABASE_CONFIRMED: litblogs-e2e-only"
    assert required in workflow
    weakened = workflow.replace(
        required,
        "E2E_DISPOSABLE_DATABASE_CONFIRMED: acknowledged",
        1,
    )

    failures = _validate_workflow(policy_validator, tmp_path, weakened)

    assert any("disposable confirmation" in failure for failure in failures)


def test_policy_validator_rejects_raw_browser_artifact_uploads(
    policy_validator, tmp_path
):
    workflow = CI_PATH.read_text(encoding="utf-8")
    sanitized_path = "litblogs/test-results/e2e/sanitized-failures/*.json"
    assert sanitized_path in workflow
    weakened = workflow.replace(
        sanitized_path,
        "litblogs/test-results/e2e/**",
        1,
    )

    failures = _validate_workflow(policy_validator, tmp_path, weakened)

    assert any("sanitized failure artifact" in failure for failure in failures)


def test_browser_harness_forbids_raw_artifacts_and_proves_runtime_database_acl():
    playwright_config = (BACKEND_ROOT / "playwright.config.js").read_text(
        encoding="utf-8"
    )
    database_harness = (BACKEND_ROOT / "e2e" / "support" / "database.py").read_text(
        encoding="utf-8"
    )
    reporter = (
        BACKEND_ROOT / "e2e" / "support" / "sanitized-reporter.mjs"
    ).read_text(encoding="utf-8")
    reporter_test = (
        BACKEND_ROOT / "e2e" / "support" / "sanitized-reporter.test.mjs"
    ).read_text(encoding="utf-8")
    availability = (
        BACKEND_ROOT / "e2e" / "support" / "availability.mjs"
    ).read_text(encoding="utf-8")
    availability_test = (
        BACKEND_ROOT / "e2e" / "support" / "availability.test.mjs"
    ).read_text(encoding="utf-8")
    global_setup = (BACKEND_ROOT / "e2e" / "global-setup.mjs").read_text(
        encoding="utf-8"
    )
    spec_sources = [
        path.read_text(encoding="utf-8")
        for path in sorted((BACKEND_ROOT / "e2e" / "specs").glob("*.spec.js"))
    ]
    fixtures = (BACKEND_ROOT / "e2e" / "support" / "fixtures.js").read_text(
        encoding="utf-8"
    )
    ignore_policy = (BACKEND_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    for forbidden_capture in ("screenshot: 'off'", "trace: 'off'", "video: 'off'"):
        assert forbidden_capture in playwright_config
    assert "workers: 1" in playwright_config
    assert "fullyParallel: false" in playwright_config
    assert "retries: 0" in playwright_config
    assert "['list']" not in playwright_config
    assert "storageState" not in playwright_config
    for ignored_output in ("test-results/", "playwright-report/", "blob-report/"):
        assert ignored_output in ignore_policy
    assert sum(source.count("test('") for source in spec_sources) == 8
    assert any(
        "the LitBlogs editor preserves one rich post across every author and course view"
        in source
        for source in spec_sources
    )

    assert "Boolean(environment.CI)" in availability
    assert "environment.E2E_REQUIRE_AVAILABLE === 'true'" in availability
    assert "if (requiresAvailableEnvironment()) throw new Error(reason)" in global_setup
    assert "CI: 'false'" in availability_test
    assert "E2E_REQUIRE_AVAILABLE: 'true'" in availability_test
    assert "E2E_REQUIRE_AVAILABLE: 'TRUE'" in availability_test

    assert "SHOW server_version_num" in database_harness
    assert "170_000 <= version_number < 180_000" in database_harness
    assert "SCRAM-SHA-256$%" in database_harness
    assert "accepted an invalid runtime password" in database_harness
    assert '("litblogs_runtime", "litblogs_runtime")' in database_harness
    assert "E2E runtime database privileges are not exact" in database_harness

    assert "attachment.name === 'sanitized-failure.json'" in reporter
    assert "fs.rmSync(attachment.path, { force: true })" in reporter
    assert "mode: 0o600" in reporter
    assert "test-results/e2e/sanitized-failures" in reporter
    for callback in ("printsToStdio()", "onStdOut()", "onStdErr()", "onError()"):
        assert callback in reporter
    assert "safeFailureSummary(content)" in reporter
    assert "title: 'browser journey'" in reporter
    assert "E2E summary: total=${total} passed=${passed} failed=${failed} skipped=${skipped}" in reporter
    assert "streamed-private-output-canary" in reporter_test
    assert "unknownSessionCanary" in reporter_test
    assert "prints only a fixed aggregate summary after the run" in reporter_test
    assert "errors: testInfo.errors.map" not in fixtures
    assert "error_count: testInfo.errors.length" in fixtures
    assert all("cookies: document.cookie" not in source for source in spec_sources)
    for redaction_probe in ("password", "draftCanary", "stdout", "stderr"):
        assert redaction_probe in reporter_test
