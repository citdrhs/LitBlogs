## Summary

Describe the user-visible outcome and the smallest coherent scope of this change.

## Stack

- Stack parent: <!-- PR number or `none` -->
- Base branch: <!-- `main` for the first layer; the parent branch for later layers -->
- [ ] This draft pull request targets the current parent/base and contains no child-layer work.
- [ ] Parent changes were merged or rebased into this branch before requesting final review.

## Journey evidence

- Student journey: <!-- steps exercised and result -->
- Teacher journey: <!-- steps exercised and result -->
- [ ] Affected student and teacher journeys have automated or reproducible manual evidence.

## Security and privacy

- [ ] Negative authorization tests prove disallowed roles/users cannot perform the action.
- [ ] Privacy tests prove responses, UI, logs, and screenshots do not expose another user's data.
- [ ] No secret, credential, production host, or personally identifiable information is included.

## Data changes

- Migration: <!-- command/plan, or `not applicable` -->
- Rollback: <!-- command/plan, or `not applicable` -->
- [ ] Migration and rollback behavior were exercised where applicable.

## Verification

- [ ] Backend tests, Ruff, and Bandit pass.
- [ ] Frontend tests, lint, and build pass.
- [ ] The pip-audit gate (`python -m pip_audit -r requirements.txt`) passes.
- [ ] `npm audit --omit=dev --audit-level=high` passes.
- [ ] Repository policy and both secret regression suites pass.

## Screenshots

<!-- Add redacted before/after screenshots for UI changes. Use `not applicable` otherwise. -->
