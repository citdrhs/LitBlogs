import ast
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR_PATH = REPOSITORY_ROOT / "scripts" / "validate-repository-policy.py"
CI_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml"
BACKEND_ROOT = REPOSITORY_ROOT / "litblogs"
MAIN_PATH = BACKEND_ROOT / "main.py"

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
