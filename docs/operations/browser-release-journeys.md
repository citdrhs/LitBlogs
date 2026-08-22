# Browser release journeys

The Chromium release gate builds the React application, starts real Uvicorn, and uses a disposable PostgreSQL 17 database migrated through Alembic. It runs seven serial journeys covering authentication and role guards, teacher setup, student draft and submission privacy, upload ACLs, account disable/enable, and logout storage cleanup.

CI and the protected release workflow provide a dedicated loopback PostgreSQL service and set `E2E_DISPOSABLE_DATABASE_CONFIRMED=litblogs-e2e-only`. The harness creates random users and a random database, migrates and seeds with the migrator credential, runs the application only as `litblogs_runtime`, verifies SCRAM plus a wrong-password rejection, and removes the database and application roles afterward.

For a local run, install Chromium with `npm run test:e2e:install`, point `E2E_ADMIN_DATABASE_URL` at the `postgres` database of a disposable loopback PostgreSQL 17 service, set the same confirmation sentinel, and run `npm run test:e2e` from `litblogs/`. Never point the harness at a shared or remote database cluster.

Screenshots, traces, and video are disabled. On a CI or release failure, the reporter writes only mode-`0600` redacted JSON under `test-results/e2e/sanitized-failures/`; those files are kept for three days and raw Playwright output is not uploaded.
