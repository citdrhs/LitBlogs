# Administrator Teacher Invitations Implementation Plan

> Execution: subagent-driven-development, with root integration and independent security review.

**Goal:** Let every active administrator create teacher invitations from the existing dashboard.

**Architecture:** Keep the current email-bound signup tokens and add an authenticated, CSRF-protected creation endpoint. Use a narrow database transition rather than giving the web app operator credentials. The React dialog displays and copies a newly created code without persisting it.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic/PostgreSQL, React, Vitest, pytest.

## Backend and database

- [ ] Add failing endpoint and database tests for the contract in the design, including denial for nonadmins and invalid CSRF, no plaintext persistence, replacement and successful signup consumption.
- [ ] Add request/response schemas in `litblogs/schemas.py`, invitation handling in a focused backend module, and endpoint wiring in `litblogs/main.py`.
- [ ] Add an additive migration and runtime identity checks for a narrow admin invitation transition if existing grants require one. Preserve existing operator routines and privilege boundaries.
- [ ] Run focused pytest tests, then the full backend suite and real PostgreSQL migration/role checks using a disposable local database or hosted CI.

## Dashboard

- [ ] Add failing tests for Invite Teacher, email submission to `/api/admin/teacher-invitations`, pending/error/success states, replacing prior codes, copying, and clearing the token.
- [ ] Add a small `TeacherInvitationDialog` component and integrate the button with `AdminDashboard.jsx`, preserving existing appearance, access checks, and axios CSRF behavior.
- [ ] Run frontend tests, lint, and the `/dren/` production build. Inspect the resulting browser UI.

## Integration and deployment

- [ ] Update operator/deployment documentation with dashboard invitation steps and the verified SMTP setup; remove obsolete host-specific SMTP TODO claims.
- [ ] Independently review the final diff for permissions, secrets, races, and scope. Resolve findings and verify the affected checks.
- [ ] Commit and push the focused branch, create a reviewable PR, and verify required checks for the exact revision before merging.
- [ ] Let the approved CIT updater deploy the passing main commit. Verify migration success, service health, database identity/start time, preserved unrelated projects, and restored maintenance timers.
- [ ] Verify public admin access and the new invitation form without sending invitations to unapproved recipients. Record commissioning evidence privately and show the updated dashboard.
