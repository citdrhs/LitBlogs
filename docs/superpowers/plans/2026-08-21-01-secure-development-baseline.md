# Secure Development Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make clean installs, tests, security scans, and reviewed GitHub delivery reproducible without retaining live secrets.

**Architecture:** Keep runtime behavior stable in this layer. Add explicit development/test dependencies, minimal smoke tests, least-privilege CI, and repository governance files; remove tracked credentials and the hard-coded Microsoft secret before any branch is pushed.

**Tech Stack:** npm, Vite, Vitest, React Testing Library, pytest, FastAPI TestClient, PostgreSQL service containers, GitHub Actions, Dependabot, Gitleaks, Bandit, pip-audit.

---

### Task 1: Remove live secrets from the proposed tree

**Files:**
- Delete from Git index: `litblogs/.env`
- Create: `litblogs/.env.example`
- Create: `.gitignore`
- Modify: `litblogs/main.py:932-936`

- [ ] **Step 1: Add a secret-regression check**

Create `scripts/check-no-tracked-secrets.ps1` that fails when `git ls-files` contains `.env` (except `.env.example`) or when Python/JavaScript files contain assignments for known server secret names with non-environment values.

- [ ] **Step 2: Verify the check fails**

Run: `pwsh -File scripts/check-no-tracked-secrets.ps1`

Expected: nonzero with `litblogs/.env is tracked` and the Microsoft secret location, without printing values.

- [ ] **Step 3: Remove and replace secret sources**

Run `git rm --cached -- litblogs/.env`. Add all `*.env`/`.env.*` files to `.gitignore` with `!.env.example`, and create a placeholder-only `.env.example` listing every required key. Replace Microsoft constants with `os.getenv("MICROSOFT_CLIENT_ID")` and `os.getenv("MICROSOFT_CLIENT_SECRET")` pending their full removal in stack layer 2.

- [ ] **Step 4: Verify and commit**

Run the secret check and `git diff --check`; expect exit 0. Stage only the four named paths and commit `security: remove tracked application secrets`.

### Task 2: Make frontend installation and checks reproducible

**Files:**
- Modify: `litblogs/package.json`
- Modify: `litblogs/package-lock.json`
- Create: `litblogs/src/test/setup.js`
- Create: `litblogs/src/utils/urlUtils.test.js`
- Modify: `litblogs/vite.config.js`

- [ ] **Step 1: Add a failing frontend smoke test**

Add Vitest/Testing Library dev dependencies and a `test:run` script. Test that `apiPath('/classes')` keeps the configured API prefix and that media URL normalization never converts an external URL into a local trusted path.

- [ ] **Step 2: Verify RED**

Run: `npm run test:run -- src/utils/urlUtils.test.js`

Expected: fail because Vitest is not configured and the safety assertion is unmet where applicable.

- [ ] **Step 3: Repair the toolchain**

Upgrade `eslint-plugin-react` to an ESLint-9-compatible release, add Vitest/jsdom/testing-library, remove unused Giphy/Auth0 dependencies, and add `test`, `test:run`, and `audit:prod` scripts. Configure `test.environment = 'jsdom'` and the setup file.

- [ ] **Step 4: Verify GREEN**

Run `npm ci`, `npm run test:run`, `npm run lint`, and `npm run build`. Expect all commands to exit 0 without using `--legacy-peer-deps`.

- [ ] **Step 5: Commit**

Stage only package/config/test files and commit `test: establish frontend quality baseline`.

### Task 3: Add backend test and quality configuration

**Files:**
- Modify: `litblogs/requirements.txt`
- Create: `litblogs/requirements-dev.txt`
- Create: `litblogs/pyproject.toml`
- Create: `litblogs/tests/conftest.py`
- Create: `litblogs/tests/test_health.py`
- Modify: `litblogs/schemas.py`

- [ ] **Step 1: Write a failing isolated health test**

In `conftest.py`, set test-only environment variables before importing the app, create a temporary SQLite database, and expose `TestClient`. Assert `/api/` returns 200 and an unauthenticated protected route returns 401.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_health.py -q`

Expected: fail until test dependencies and warning-producing Pydantic configuration are corrected.

- [ ] **Step 3: Define runtime and development dependencies**

Keep runtime dependencies in `requirements.txt`; put pytest, pytest-cov, httpx, Ruff, Bandit, pip-audit, and pre-commit in `requirements-dev.txt`. Replace `orm_mode` with `from_attributes`, and configure pytest/Ruff coverage targets in `pyproject.toml`.

- [ ] **Step 4: Verify GREEN**

Run `python -m pip install -r requirements.txt -r requirements-dev.txt`, `python -m pytest -q`, `python -m ruff check .`, `python -m bandit -r main.py database.py models.py schemas.py -ll`, and `python -m pip_audit -r requirements.txt`. Expect tests/lint/static analysis to exit 0; dependency audit must have no high/critical finding.

- [ ] **Step 5: Commit**

Commit only the dependency/config/test/schema paths as `test: establish backend quality baseline`.

### Task 4: Add CI and repository policy

**Files:**
- Create: `.github/workflows/ci.yml`
- Create: `.github/workflows/codeql.yml`
- Modify: `.github/dependabot.yml`
- Create: `.github/CODEOWNERS`
- Create: `.github/PULL_REQUEST_TEMPLATE.md`
- Create: `.github/ISSUE_TEMPLATE/bug_report.yml`
- Create: `.github/ISSUE_TEMPLATE/feature_request.yml`
- Create: `.github/ISSUE_TEMPLATE/config.yml`
- Create: `CONTRIBUTING.md`
- Modify: `SECURITY.md`

- [ ] **Step 1: Add CI jobs with stable names**

Create jobs named `backend-tests`, `frontend-tests`, `frontend-lint`, `frontend-build`, `dependency-audit`, `secret-scan`, and `sast`. Trigger on `pull_request`, `push` to `main`, and `merge_group`; default permissions are `contents: read`. Backend tests use a synthetic PostgreSQL service and test-only credentials.

- [ ] **Step 2: Add review policy**

Assign `@Antigro09` as the current code owner, describe stacked draft PRs and squash merging in `CONTRIBUTING.md`, require use-case evidence in the PR template, and route private reports to GitHub private advisories.

- [ ] **Step 3: Correct dependency automation**

Configure npm `/litblogs`, pip `/litblogs`, and GitHub Actions `/`; remove the nonexistent Docker ecosystem entry and group non-major safe updates.

- [ ] **Step 4: Validate and commit**

Parse YAML, run all local equivalents, run `git diff --check`, and commit `ci: add protected delivery quality gates`.

### Task 5: Final layer verification

**Files:**
- Modify only if verification exposes a baseline defect.

- [ ] **Step 1:** Run fresh `npm ci`, frontend tests/lint/build/audit, Python install/tests/Ruff/Bandit/pip-audit, and the secret regression check.
- [ ] **Step 2:** Inspect `git status`, staged/unstaged diffs, and commits for accidental secret values or generated artifacts.
- [ ] **Step 3:** Request independent code review of `origin/main..HEAD` and resolve all Critical/Important findings.
- [ ] **Step 4:** Re-run the complete verification commands and record counts for the PR body.

