# LitBlogs

LitBlogs is a private-school blogging and classroom collaboration application. It uses a React/Vite frontend, a FastAPI backend, and PostgreSQL. Students can publish rich-text posts, comment, react, manage profiles, and complete assignments; teachers can manage classes, assignments, rosters, and student work.

## Local development

Supported development versions are Python 3.13 and Node.js 24 LTS. The frontend package, `.nvmrc`, and `.node-version` fail closed on a different Node major.

```bash
cd litblogs
python -m venv .venv
python -m pip install --require-hashes --only-binary=:all: -r requirements-dev.txt
npm ci
```

Copy `litblogs/.env.example` to an ignored local environment file and replace the development placeholders. The example is intentionally development-only; it is not a production secret template.

Initialize or advance the local SQLite schema explicitly before starting the API. The migration loader accepts this file only when `APP_ENV=development`, `LITBLOGS_MIGRATION_DATABASE_URL` exactly equals `DATABASE_URL`, and the named `.db`/`.sqlite*` file resolves inside `litblogs` without a symlink escape:

```bash
cd litblogs
set -a
. ./.env
set +a
python -m alembic -c alembic.ini upgrade head
python -m alembic -c alembic.ini current --check-heads
```

`upgrade head` is idempotent and is the required fresh-local initialization path; application startup never creates or resets schema.

Run the quality gates from the repository root:

```bash
python -m pytest litblogs/tests -q
npm --prefix litblogs run test:run
npm --prefix litblogs run lint
npm --prefix litblogs run build
python -m ruff check litblogs
python scripts/run-backend-bandit.py
```

## Identity and session operations

Browser authentication is backed by digest-only server-side session records. Logout
revokes the current session; password changes, password resets, account disablement,
and account deletion revoke all sessions. Issuance is serialized per account and keeps
only the ten newest session rows, invalidating the deterministic oldest token when the
cap is reached. Disabling an account also invalidates every pending, processing, or
delivered password-reset row in the same transaction, and a successful password change
does the same before commit. Reset delivery and consumption serialize against the
enabled account row. Each reset-delivery lease stores only a random claim digest;
completion uses compare-and-swap on that digest, so a timed-out worker cannot overwrite
a newer reclaimed delivery. Account deletion takes that same user-row lock before touching
session, reset, or content rows, so issuance and deletion cannot leave an orphaned live
session or deadlock in reverse lock order. Deploying migration `0003` intentionally
invalidates older stateless JWT cookies, because no session backfill is performed.
The migration also invalidates every outstanding password-reset row so plaintext bearer
tokens from legacy releases cannot remain usable at rest; users request a new link.

Teacher accounts use one-time, expiring invitations bound to the normalized school
email address. There is no public invitation endpoint and no shared teacher access
code. Configure a dedicated random `TEACHER_INVITE_HMAC_KEY` (at least 32 bytes,
different from `SECRET_KEY`) in the server secret store. Run the operator commands
only from the trusted application host through the reviewed operator wrapper. That
wrapper supplies a minimal purpose-specific JSON config on inherited file descriptor 3:
only `purpose`, the dedicated least-privilege PostgreSQL URL, invitation HMAC key, and
allowed school domains. Purpose hard-binds the exact operator role; a configurable
expected-role field is rejected. It must not expose the application JWT, OAuth, SMTP,
VAPID, or admin secrets. The URL uses exact target `127.0.0.1:5432/litblogs`, a dedicated strong
credential, `sslmode=verify-full`, and exact root-owned CA path
`/etc/litblogs/postgres-root-ca.pem`; runtime verifies every ancestor is root-owned and
not group/world writable. The CLI also verifies `current_user`, role attributes and
memberships, and an EXECUTE-only SECURITY DEFINER boundary with no direct table or
sequence privileges.

The target email is read from a no-echo prompt and must never be placed in argv, an
environment variable, shell history, or process metadata. The operator identifier is
intended audit data:

```bash
python -m manage_teacher_invitations create --expires-hours 24 --operator "$REVIEWED_OPERATOR"
python -m manage_teacher_invitations revoke --operator "$REVIEWED_OPERATOR"
python -m manage_accounts disable --operator "$REVIEWED_OPERATOR"
python -m manage_accounts enable --operator "$REVIEWED_OPERATOR"
```

For non-interactive operation, provide exactly one email line on a protected stdin file
descriptor sourced from the approved secret/PII store. The file path and descriptor
metadata must not contain the address, and the file must be owner-readable only.
The protected config descriptor and stdin email channel are separate; neither secret is
accepted from command arguments or the web application's environment.

The create command prints the raw invitation once. Deliver it only through an approved
private channel and exclude that stdout from session recordings, CI artifacts, command
transcripts, and logs. Every operator command transaction records its bounded actor,
action/outcome, and a domain-separated HMAC target reference; it never records the raw
email, invitation, or session value. The database stores only invitation/session
digests. The admin-only account-status API uses the same transactional audit contract,
and rolls back account/session changes if its audit record cannot be stored. See
`litblogs/migrations/README-identity-controls.md` for migration, smoke tests, and the
token-safe application rollback procedure.

Email identity is restricted to ASCII school addresses and is case-insensitive. New
accounts remove U+0020 padding and store a lowercase address; every remaining space,
ASCII control character (C0 plus DEL), and non-ASCII byte is rejected. PostgreSQL
uses locale-independent ASCII `translate(btrim(email), ...)`, equivalent control checks,
`COLLATE "C"` canonical comparisons, and a bytewise `varchar_pattern_ops` unique
index rather than locale-sensitive `lower()`. The teacher/account association is the unique, non-null
`teachers.user_id`; the denormalized teacher email is reconciled to the user row.
Migration preflight must reconcile any invalid, unmappable, or duplicate legacy
identities through a reviewed school process before the constraints and indexes are
created. Password registration accepts only the configured school email domains in
production and returns the same generic accepted response when an address is ineligible.

Generic acceptance prevents direct account enumeration, but password registration does
not prove control of the submitted school mailbox. Production must keep password
registration disabled in favor of verified school SSO, or add a reviewed pending-email
or roster-verification flow before activating password accounts.

## Environment configuration

Production push delivery remains disabled until its endpoint validation, redirect,
timeout, and network-egress controls pass the deployment review. Do not enable it from
the development example. The reviewed production runbook is the authority for runtime
settings and secret custody.

Password resets require a STARTTLS-capable SMTP relay in production. Configure
`EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USERNAME`, `EMAIL_PASSWORD`, `EMAIL_FROM`, and:

```dotenv
EMAIL_SMTP_TIMEOUT_SECONDS=5
PASSWORD_RESET_WORKER_ENABLED=true
PASSWORD_RESET_WORKER_INTERVAL_SECONDS=5
PASSWORD_RESET_CLAIM_TIMEOUT_SECONDS=120
```

The public reset request commits a concurrency-safe outbox row and returns the same
`202` response for known and unknown addresses; it never waits for SMTP. A background
worker claims each per-user row before delivery, and the token becomes usable only after
a successful send. Reset links place the token in a URL fragment so reverse proxies do
not receive it; the frontend removes the fragment from browser history immediately.
Run one worker-enabled application instance during deployment smoke testing and monitor
reset rows stuck in `PROCESSING` or ending in `FAILED`.

## Production deployment

Do not deploy a Git branch, a developer checkout, or locally assembled files. Production releases must come from the reviewed, attested artifact produced by the `Build reviewed release artifact` GitHub Actions workflow.

- [Deployment layout and prerequisites](deploy/README.md)
- [Production deployment, migration, backup, restore, rollback, and incident runbook](docs/operations/production-runbook.md)

The deployment design keeps private uploads outside the source tree, runs the API only on loopback behind TLS-terminating Nginx, applies schema changes through Alembic, installs hash-locked dependencies, and uses hardened systemd units. A release remains blocked until the runbook's backup/restore rehearsal, migration checks, legacy federated-identity mapping, security gates, and smoke tests all pass.

## Security

Please report vulnerabilities privately using the process in [SECURITY.md](SECURITY.md). Never commit credentials, student data, production database copies, upload files, or environment files.

## Contribution workflow

All changes go through short-lived branches and reviewed pull requests. See [CONTRIBUTING.md](CONTRIBUTING.md) for required checks and repository workflow.
