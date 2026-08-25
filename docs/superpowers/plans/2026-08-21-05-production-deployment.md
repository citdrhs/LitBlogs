# Production Deployment Readiness Implementation Plan

**Goal:** Make the private-school deployment reproducible, migration-driven, observable, reversible, and fail-closed without embedding school credentials or production data in Git.

**Stack position:** This is the final application stack layer. It is developed from the federated-identity layer and must be rebased after the resource-authorization and content/upload layers before its pull request is opened.

## Task 1: Replace startup DDL with versioned migrations

- Add Alembic as a pinned runtime dependency and configure it from the validated application settings.
- Create an idempotent baseline migration that represents the current schema, including the federated identity table, and a migration ledger test.
- Remove all production `create_all`, `drop_all`, and reset-on-startup behavior. Test-only fixtures retain explicit, guarded DDL.
- Fail readiness when the database cannot be reached or the Alembic revision is not at the expected head.
- Test upgrade from an empty disposable PostgreSQL database and downgrade/upgrade of reversible application migrations in CI.

## Task 2: Harden production database connections and health checks

- Require PostgreSQL with TLS in production and reject SQLite, plaintext, libpq service indirection, and unsafe URL overrides.
- Configure bounded pools, pre-ping, recycle, connection timeout, lock timeout, and statement timeout.
- Provide separate liveness and readiness endpoints; readiness returns only a generic status and performs a bounded `SELECT 1` plus migration-head check.
- Keep test SQLite support isolated behind the existing test guard.

## Task 3: Separate scheduled work from web workers

- Remove the per-process reminder thread from the FastAPI lifespan.
- Add a one-shot, lock-protected reminder command suitable for a systemd timer. Multiple invocations must not duplicate notifications.
- Add unit tests for lock contention, failure rollback, and non-sensitive logging.

## Task 4: Ship least-privilege service and reverse-proxy examples

- Add hardened systemd web and reminder units with a dedicated unprivileged account, read-only application tree, writable state paths only, private temp, system-call/filesystem restrictions, bounded restarts, and an environment-file reference outside Git.
- Add an Nginx TLS-only example with an explicit host, HSTS/security headers, request/body/time limits, authentication rate limits, no direct upload/static alias, and proxying only to loopback.
- Disable public API docs/OpenAPI in production unless explicitly enabled for an internal admin deployment.
- Document firewall, certificate, DNS, secrets-store, malware-scanning, and trusted-proxy requirements that school IT must supply.

## Task 5: Add backup, restore, retention, and rollback controls

- Add safe operator scripts for encrypted PostgreSQL custom-format backups, checksum manifests, restore into a newly named verification database, and post-restore integrity checks.
- Never accept a production database name as a restore target; require a synthetic verification prefix and explicit operator confirmation.
- Document RPO/RTO, retention/legal-hold ownership, upload backup coupling, quarterly restore drills, migration rollback rules, and incident handling.
- Add static regression tests for destructive-command guards and redaction.

## Task 6: Build immutable release artifacts and a protected deployment handoff

- Add a release workflow that runs only after the full required checks, builds the frontend once, creates a source/runtime artifact with a commit manifest and dependency SBOMs, and emits SHA-256 checksums.
- Do not deploy directly from GitHub Actions. Publish a reviewed artifact for the private server and require a protected GitHub environment/manual school-IT approval for release promotion metadata.
- Add a smoke-check command that validates config, migration revision, readiness, and static assets before traffic switch.
- Document blue/green or versioned-directory activation and atomic symlink rollback.

## Task 7: Verify the complete final stack

- Rebase this layer after authorization and content/upload work, resolve startup/storage conflicts, and add private upload ACL/quota/lifecycle migrations.
- Run fresh installs, the full PostgreSQL backend suite, frontend tests/lint/build, browser journeys, Ruff, Bandit, audits, secret scans, policy validation, migration tests, and deployment-config regressions.
- Obtain independent Critical/Important review and repeat all gates after fixes.
- Open the final dependent draft pull request with exact migration, operator-action, rollback, and unresolved external-action notes. Do not merge or deploy until school IT rotates all historically exposed secrets and completes the legacy OAuth identity-mapping preflight.
