# Contributing to LitBlog

LitBlog serves student and teacher workflows. Keep changes reviewable, protect role and data boundaries, and use synthetic data for every test and screenshot.

## Branches and stacked pull requests

Create work on a `codex/*` branch. A direct push to `main` or `Deployment` is prohibited; those branches are protected delivery targets, not development branches.

Use a stacked draft pull request flow for work that needs multiple layers:

1. Branch the first layer from `main`, open a draft pull request, and record `none` as its stack parent and `main` as its base branch.
2. Branch each later layer from its immediate parent branch. Open another draft pull request whose base branch is that parent branch, and link the stack parent.
3. When a parent changes, update the child from the parent and rerun all affected checks. When a parent is squash-merged, update the child's base branch to `main`, remove the merged parent commits cleanly, and verify the resulting diff before requesting review.
4. Keep every layer independently understandable. Never mix work intended for a child layer into its parent.

Mark a draft ready only after its parent/base metadata and PR checklist are current.

## Commits, review, and merge

Use Conventional Commits such as `fix:`, `feat:`, `test:`, `docs:`, `security:`, and `ci:`. Keep each commit scoped and free of generated output.

Every change reaches `main` through a reviewed pull request. Resolve code-owner feedback and require these stable CI checks:

- Backend tests
- Frontend tests
- Frontend lint
- Frontend build
- Dependency audit
- Secret scan
- SAST

CodeQL analysis must also complete when required. Use squash merge so `main` remains linear. Force pushes and branch deletion rules are controlled by repository policy.

## Local quality gates

Install from committed dependency definitions, then run the same gates as CI:

```powershell
Set-Location litblogs
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q
python -m ruff check .
python -m bandit -r main.py database.py models.py schemas.py -ll
python -m pip_audit -r requirements.txt
npm ci
npm run test:run
npm run lint
npm run build
npm audit --omit=dev --audit-level=high
Set-Location ..
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check-no-tracked-secrets.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check-no-tracked-secrets.tests.ps1
python scripts/check-generic-secrets.tests.py
python scripts/check-generic-secrets.py
python scripts/validate-repository-policy.py
git diff --check
```

Run `python -m pre_commit run --all-files` as a fast deterministic pre-review check. The local hooks cover the proposed-tree secret scan, repository policy, backend Ruff, and frontend lint; the full commands above remain the source of truth.

## Journey, authorization, and data evidence

For behavior changes, record both the student journey and teacher journey. Add positive evidence for intended access and negative authorization tests for every role or user who must be denied. Privacy tests must prove that APIs, pages, logs, and exported media do not expose another user's data.

Document database migrations and a tested rollback. Attach redacted before/after screenshots for visual changes. Use `not applicable` only with a brief reason.

## Secrets and personal data

Never commit a real credential, token, production host, private key, raw log, or personally identifiable information. Use clearly synthetic test values and keep local environment files untracked. The repository checker (`scripts/check-no-tracked-secrets.ps1`) and generic proposed-tree scanner are guardrails, not permission to include sensitive material.

If a secret may have been exposed, stop sharing it, notify the maintainer privately, rotate it, and follow [SECURITY.md](SECURITY.md). Report vulnerabilities through a private repository security advisory, never a public issue.
