import ast
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR_PATH = REPOSITORY_ROOT / "scripts" / "validate-repository-policy.py"
CI_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml"
BACKEND_ROOT = REPOSITORY_ROOT / "litblogs"
MAIN_PATH = BACKEND_ROOT / "main.py"
IDENTITY_MIGRATION_PATH = BACKEND_ROOT / "migrations" / "0003_add_identity_controls.sql"
IDENTITY_RUNBOOK_PATH = BACKEND_ROOT / "migrations" / "README-identity-controls.md"

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
    assert 'on users (email collate "c")' in migration
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
