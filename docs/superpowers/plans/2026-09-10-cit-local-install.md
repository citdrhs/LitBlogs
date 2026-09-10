# CIT local installation plan

> **For agentic workers:** Use subagent-driven-development with scoped file ownership; root alone operates the shared server.

**Goal:** Install and verify only LitBlogs on CIT, without Nginx, DNS or public routing changes, with persistent PostgreSQL and bounded automatic updates/scaling.

**Architecture:** Use the repository Dockerfile and Compose services under stable project `litblogs-cit`. A separate Compose overlay replaces the gateway with a loopback-only HAProxy HTTPS listener. Reuse current migrations and named volumes, generate new database/application secrets, recover only requested SMTP configuration, and test actual coupled backup/restore before readiness attestations. Keep all runtime configuration and operations under the LitBlogs account; install only specifically named LitBlogs systemd units.

**Tech Stack:** Existing Python 3.13/Node 24 application image, PostgreSQL 17, ClamAV, Docker Compose, HAProxy, Python standard library and systemd.

- [x] Read deploy/CIT_DEPLOY.md; inspect existing account, repository, shared ports, resources and Docker availability.
- [x] Build reviewed main commit 7e5764105ce52d119012025777b8fda074dd4021 and inspect its GitHub checks.
- [x] Add deployment-only overlay and HTTPS configuration, loopback port 18443, hostname litblogs.cit.internal, explicit CPU/memory/PID limits and log rotation. Do not install/start Nginx.
- [x] Generate private deployment secrets and configure allowed school domains. Recovered SMTP authentication failed; the user explicitly deferred replacement and delivery testing as a TODO.
- [x] Start only the named LitBlogs database/scanner and run the supplied migration command. Verify empty initial users and upload storage before the fresh-install assertion.
- [x] Authenticate/decrypt the coupled backup, restore into a separate private Compose project, and verify schema, data and upload bytes/custody before setting the readiness flag.
- [x] Start all six services and pass actual HTTPS, static/video, admin authentication, cookie/CSRF, database TLS/roles and scanner checks.
- [x] Force application container replacement while preserving the administrator and upload; prove adding a column preserves a record in the isolated restored database.
- [x] Implement and rehearse the update sequence against the currently admitted SHA, including encrypted backup, app replacement and unchanged PostgreSQL container/start time. Verify the real GitHub polling path; future new-commit deployment remains automatic after required CI passes.
- [x] Verify one-to-three-to-one healthy app replicas and local HTTPS routing; install bounded CPU-based autoscaling with a shared operation lock.
- [x] Install/enable the main systemd service and three timers; run startup, update, autoscale and backup services successfully. Preserve existing containers on boot. Backups are retained without deletion; disk retention and off-host scheduling are documented. Administrator provisioning is complete, with credentials kept privately outside Git.
- [x] Review deployment changes, rerun relevant checks, publish the authorized deployment changes as PR #62, and retain exact remote deployment evidence.

No broad cleanup, shared host configuration changes, global Docker operations, database resets, unrelated repository edits, or automatic schema downgrades are permitted. Failure recovery preserves database/uploads and the previous application image.

Validation: the deployment-control suite passes on Linux, including the six real
HAProxy runtime tests and the Git permission regression; Ruff passes. Existing
focused application tests passed (121 passed, 19 platform-dependent skips).
Current application GitHub CI, browser journeys and container persistence checks
were verified successful. Actual CIT backup, isolated restore, application
replacement, scaling, admin authentication and service/timer evidence is retained
privately in the deployment state directory and copied off-host.

Publication checks identified a TLS-version warning in the disposable gateway
test and a newly reported js-yaml development-dependency advisory. The test now
states its TLS 1.2 minimum explicitly, and only the affected lockfile entry moves
from 4.3.1 to 4.3.2. CI admission also requires both CodeQL analysis jobs and honors
any present CodeQL alert or CIT control check for the exact candidate commit.
