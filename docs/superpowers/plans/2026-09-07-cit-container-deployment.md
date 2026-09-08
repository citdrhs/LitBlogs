# CIT Deploy Container Implementation Plan

> **For agentic workers:** Use subagent-driven-development with scoped file ownership and review before integration.

**Goal:** Build and verify a Docker/Compose production package and concise CIT Deploy instructions without deploying the school server.

**Architecture:** Root-serving FastAPI plus a container-only React static adapter, PostgreSQL 17 and ClamAV services, separate initialization/migration and maintenance commands, persistent named volumes. An exclusive HTTPS hostname is a production prerequisite; shared-path auth is not enabled.

**Tech Stack:** Docker Compose, Node 24/Vite, Python 3.13/FastAPI/Starlette, PostgreSQL 17, ClamAV.

**Implementation status:** The container adapter, bootstrap, gateway, runtime,
workers, operator profiles, synthetic smoke runner, CI workflow, and CIT guide
are implemented. Focused test-first checks and independent reviews have run.
The final full-suite rerun and remote container CI remain release gates. Local
Docker Desktop fails before the engine starts; no school deployment is authorized.
Review refined the architecture to a private app behind a non-root Nginx gateway
so existing body and rate limits remain enforced.

## 1. Container frontend adapter

Files: `litblogs/container_frontend.py`, `litblogs/container_app.py`,
`litblogs/tests/test_container_frontend.py`.

- [ ] Add failing tests using a temporary `dist` and a real Starlette/FastAPI test
  client: `/help` returns index HTML, `/api/missing` remains 404, private uploads
  and dotfiles are never static, `/assets/missing.js` remains 404, hashed assets
  are immutable, HTML is no-store, VTT has `text/vtt`, MP4 Range returns 206.
- [ ] Run `python -m pytest -o addopts='' tests/test_container_frontend.py -q` and
  inspect the expected failure before implementing.
- [ ] Implement a narrowly scoped static adapter and container entrypoint using
  the existing backend; preserve API middleware and security headers.
- [ ] Re-run the test file and scoped Ruff; review and commit.

## 2. Fresh database and volume lifecycle

Files: `deploy/container/initialize.py`, `deploy/container/migrate.py`,
`deploy/container/postgres-init.sh`, `litblogs/tests/test_container_bootstrap.py`.

- [ ] Add failing tests for initialization reuse without overwriting keys/data,
  rejection of partial/unexpected storage, URL encoding and secret redaction,
  migration-only credentials and revocation after migration failure.
- [ ] Run the focused test file to observe failures.
- [ ] Implement TLS/custody initialization and exact current PostgreSQL role
  bootstrap; run Alembic separately with temporary identity-owner membership.
- [ ] Verify focused tests and the real disposable PostgreSQL startup/migration.
  Never point these commands at the user's existing database.

## 3. Image, Compose and workers

Files: `Dockerfile`, `.dockerignore`, `docker-compose.yml`,
`deploy/container/runtime.py`, `deploy/container/worker.py`,
`deploy/container/healthcheck.py`, `litblogs/tests/test_container_deployment.py`.

- [ ] Add failing contract/behavior tests for non-root web, runtime secret
  separation, persistent volumes, health/dependency ordering, private database
  and scanner ports, and required production settings.
- [ ] Implement multi-stage builds using locked dependencies, runtime-only
  configuration, signal-aware bounded maintenance loops and health checks.
- [ ] Run `docker compose config --quiet` using disposable synthetic settings;
  build the real image and execute a disposable container smoke test.
- [ ] Recreate services and prove database/upload persistence; check failure
  behavior without required settings. Do not delete unrelated Docker resources.

## 4. Operator handoff and publication

Files: `deploy/CIT_DEPLOY.md`, `deploy/container.env.example`, root README links,
and focused deployment tests/CI coverage where needed.

- [ ] Write a short field-by-field CIT Deploy guide covering dedicated hostname,
  environment setup, database initialization, persistent storage, recovery
  verification, first admin, teacher invitation, future Google and updates.
- [ ] State explicitly that the portal's shown shared paths are unsuitable for
  private production accounts, and do not press Import & deploy.
- [ ] Run affected/backend/frontend/browser tests, build, lint, secret scan and
  repository policy; review actual changes against the specification.
- [ ] Commit/push only verified task files. Create the PR when access allows and
  inspect CI/CodeQL. Keep the current local preview available for the user.
