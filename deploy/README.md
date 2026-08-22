# Private-server deployment assets

These files are reviewed examples for a school-managed Linux server. Replace the example hostname and certificate paths in a reviewed site-specific copy; do not commit real credentials, student data, private keys, or internal hostnames.

## Least privilege layout

- `/opt/litblogs/releases/litblogs-<commit-prefix>`: immutable root-owned release trees, mode `0755` or stricter; application users cannot write here.
- `/opt/litblogs/current` and `/opt/litblogs/previous`: symlinks managed only by the release operator.
- `/var/lib/litblogs/uploads`: private writable upload store, owner `litblogs:litblogs`, mode `0750`; never expose it with an Nginx `alias`.
- `/var/lib/litblogs`: application state only, owner `litblogs:litblogs`, mode `0750`.
- `/var/log/litblogs`: application/service logs if file logging is enabled, owner `litblogs:litblogs`, mode `0750`; prefer the journal forwarding to the school SIEM.
- `/etc/litblogs/litblogs.env`: production settings, owner `root:litblogs`, mode `0640`. It must not contain shell syntax and must never enter Git.
- `/etc/litblogs/tls`: TLS certificate chain readable by Nginx and private key readable only by root/Nginx, mode `0640` or stricter.
- `/srv/litblogs-backups`: encrypted backup mount whose canonical, non-symlinked immediate output directory is owned by the effective backup operator at exact mode `0700`; the web service must not write here.

Create a locked service account with no interactive shell. Separate application runtime, migration, backup, and restore database roles. The runtime role has no database creation, role management, schema ownership, replication, or server-file privileges.

## Production environment contract

`litblogs/.env.example` is development-only. Its local non-`__Host-` cookie names are intentional only with `SESSION_COOKIE_SECURE=false`; do not copy those values to a deployed server. School IT must render `/etc/litblogs/litblogs.env` from the managed secrets system. Run the release-local `deployment_check --preflight` after the candidate virtual environment is installed but before migrations, then run the default database postflight after migrations and before service start. The block below is a shape checklist: angle-bracketed values describe site-specific managed values and must never be installed literally.

```text
APP_ENV=production
DATABASE_URL=postgresql://litblogs_runtime:<percent-encoded-managed-password>@<school-postgres-host>/litblogs?sslmode=verify-full&sslrootcert=/etc/litblogs/postgres-root-ca.pem
SECRET_KEY=<at-least-32-random-bytes-with-at-least-12-distinct-characters>
JWT_ISSUER=https://<school-approved-host>
JWT_AUDIENCE=litblogs-production
FRONTEND_URL=https://<school-approved-host>
BASE_URL=https://<school-approved-host>
CORS_ALLOWED_ORIGINS=https://<school-approved-host>
ALLOWED_HOSTS=<school-approved-host>
ALLOWED_EMAIL_DOMAINS=<school-approved-email-domain>
GOOGLE_CLIENT_ID=<registered-google-client-id.apps.googleusercontent.com>
MICROSOFT_CLIENT_ID=<registered-application-uuid>
MICROSOFT_TENANT_ID=<fixed-school-tenant-uuid>
MICROSOFT_ALLOWED_TENANT_IDS=<comma-separated-approved-tenant-uuids-including-the-fixed-tenant>
SESSION_COOKIE_NAME=__Host-litblogs-session
CSRF_COOKIE_NAME=__Host-litblogs-csrf
SESSION_COOKIE_SECURE=true
TEACHER_ACCESS_CODE=<managed-random-value-of-at-least-16-bytes>
RESET_DATABASE_ON_STARTUP=false
API_DOCS_ENABLED=false
EMAIL_HOST=<school-approved-smtp-host>
EMAIL_PORT=587
EMAIL_USERNAME=<managed-smtp-account>
EMAIL_PASSWORD=<managed-random-smtp-secret-of-at-least-16-bytes>
EMAIL_FROM=<school-approved-sender-address>
PUSH_NOTIFICATIONS_ENABLED=false
```

`DATABASE_URL` must name PostgreSQL, include an explicit username and unique non-placeholder managed password of at least 16 UTF-8 bytes, contain exactly `sslmode=verify-full` plus the canonical `/etc/litblogs/postgres-root-ca.pem`, use one DNS/IP host, and contain no libpq target override. Percent-encode every password character reserved by URL syntax before rendering the URL. Passwordless URLs, empty passwords, trust authentication, `.pgpass` fallback, and ambiguous peer/certificate-only authentication are deployment blockers; this release supports no alternate database authentication mechanism. A DBA must inspect the effective, ordered `pg_hba.conf` rules and prove the actual matching rule for each runtime, migration, backup, and restore connection is an exact `hostssl` rule using `scram-sha-256`, with no earlier broader `trust`, `md5`, peer, or certificate-only match. Confirm each login role has a SCRAM verifier without recording it. Through the same hostname, port, database, role, TLS mode, and CA path used by the service, a wrong-password probe and a rotated-old password probe must both fail while the managed current password succeeds; never place probe passwords in arguments or logs. Install the CA as a non-symlinked `root:root` `0644` or `root:litblogs` `0640` file, never group/world writable, and execute preflight as the `litblogs` identity to prove it is readable. Every parent directory from `/etc/litblogs` through `/` must be root-owned and not group/world writable, so the CA cannot be replaced after validation. Supply the runtime credential through the protected environment file or an approved credential provider, never through a unit command line. `JWT_ISSUER` and `FRONTEND_URL` must be unambiguous HTTPS URLs. `CORS_ALLOWED_ORIGINS` must contain explicit HTTPS origins; `ALLOWED_HOSTS` and `ALLOWED_EMAIL_DOMAINS` are comma-separated exact DNS names without wildcards, schemes, ports, or paths. Localhost and reserved documentation domains such as `.example`, `.invalid`, and `.test` are production blockers, not acceptable placeholders. The two valid `__Host-` cookie names must remain distinct; their prefix also requires Secure transport, path `/`, and no Domain attribute.

Google and Microsoft IDs must be the exact registered values. `MICROSOFT_CLIENT_ID` and every tenant ID must be UUIDs, and `MICROSOFT_ALLOWED_TENANT_IDS` must include `MICROSOFT_TENANT_ID`. The browser obtains its public CSRF-cookie and OAuth identifiers from backend settings at runtime through `/api/runtime-config`; do not bake environment-specific `VITE_*` identity values into the frontend bundle. `EMAIL_HOST`, `EMAIL_USERNAME`, `EMAIL_PASSWORD`, and `EMAIL_FROM` are mandatory; `EMAIL_PORT` defaults to 587 but must be recorded explicitly for the school relay. Permit only an authenticated, certificate-validated TLS SMTP relay and test delivery without logging reset links or credentials.

Push delivery is deliberately disabled in this release: production must set `PUSH_NOTIFICATIONS_ENABLED=false`, leave `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, and `VAPID_SUBJECT` unset, and do not enable litblogs-reminders.timer. Enabling push remains a deployment blocker until endpoint validation, egress policy, and bounded dispatch behavior have a separately reviewed implementation. The bounded defaults for `JWT_CLOCK_SKEW_SECONDS`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `OAUTH_HTTP_TIMEOUT_SECONDS`, `OAUTH_JWKS_CACHE_SECONDS`, and the `DB_*` pool/timeout settings may be changed only through a reviewed capacity or security change.

## systemd installation

1. Review every unit in `deploy/systemd/` with school IT. Copy it with root ownership and mode `0644` into `/etc/systemd/system/`; never symlink system units to a writable checkout.
2. Install `/etc/litblogs/litblogs.env` as `root:litblogs` mode `0640`. Use the school secrets system to render it and rotate it; do not paste values into unit arguments.
3. In a fresh candidate tree, create the release-local environment with Python 3.13 and install from `litblogs/requirements.txt` using `python -m pip install --require-hashes --only-binary=:all: -r requirements.txt`. Run the release-local artifact/config `deployment_check --preflight`, then apply the final root-owned seal; never modify the sealed release. An unhashed install or any install that permits a source distribution is prohibited in production. The shipped web unit uses `Type=simple`, runs its database-head postflight with `/opt/litblogs/current/.venv/bin/python -m deployment_check`, and starts `/opt/litblogs/current/.venv/bin/uvicorn`. The shipped reminder unit runs `/opt/litblogs/current/.venv/bin/python -m reminder_job`. Do not override these commands with a shared mutable virtual environment: source rollback without dependency rollback is not safe.
4. Run `systemd-analyze security litblogs-web.service` and review every exception. Then run `systemctl daemon-reload`, enable only `litblogs-web.service`, and verify the service still has only the documented writable paths. While push is disabled, run `systemctl disable --now litblogs-reminders.timer` and do not enable `litblogs-reminders.timer`.
5. Bind Uvicorn only to loopback. Only the Nginx account may reach the loopback port through local policy; no host firewall rule exposes it.

Keep Uvicorn in the foreground under the shipped `Type=simple` unit and validate startup plus readiness behavior in staging before enabling it. Treat an early process exit, configuration-gate failure, or readiness failure as a deployment blocker, not a reason to weaken service protections.

## Nginx installation

1. Replace `litblogs.school.example` and the example certificate paths in an untracked school configuration. Provision a trusted TLS certificate and confirm the renewal job and expiry alert.
2. Copy the reviewed configuration to the distribution's enabled-site directory with root ownership and mode `0644`.
3. Keep `/api/` proxied only to loopback. Do not add a direct upload/static alias; authorization must stay in the application.
4. Preserve the exact `/index.html` and SPA fallback `Cache-Control: no-cache, no-store, must-revalidate` policy across activation and rollback. Only sealed, content-hashed `/assets/` filenames receive `immutable`; never extend immutable caching to the HTML entry point or unhashed files. Nginx add_header inheritance is all-or-nothing: each location that sets `Cache-Control` must also retain the complete reviewed HSTS, CSP, frame, content-type, referrer, permissions, opener, and resource-policy header set. Verify all three location classes in `nginx -T` and with response-header probes.
5. Preserve the TLS-only listener, HSTS, security headers, request/body/time limits, and authentication/API rate limits. Coordinate the body cap with the application's stricter per-file limits.
6. Run `nginx -t`, inspect the complete rendered configuration with `nginx -T`, reload, and verify HTTP redirects to HTTPS while the backend port is unreachable remotely.

School IT must validate TLS protocol/cipher policy, DNS, firewall rules, proxy trust boundaries, certificate renewal, log forwarding, rate-limit capacity, and denial-of-service protections. The example does not replace those controls.

## Logging and privacy gate

The reviewed Nginx **access** log format intentionally omits raw paths, path identifiers, query strings, and referrers; the explicit application logger records only normalized route templates. The Uvicorn access logger is disabled with `--no-access-log`; `deploy/logging.json` enables the privacy-safe request and protected error streams in the journal. Every Nginx server uses `error_log ... crit`, so ordinary 4xx and upstream warnings are not written by this server error log. Critical Nginx error logs are not structurally redacted and remain sensitive: restrict their access, encrypt them, and give them the shortest school-approved retention. Never add request bodies, upload filenames, tokens, cookie values, reset links, email addresses, teacher notes, or student content to proxy, application, database, error, or analytics logs.

IP addresses, user agents, and correlated request IDs remain personal or security-sensitive data even after content fields are excluded. Encrypt log transport and encrypted storage, restrict SIEM access to named school roles, audit that access, and document the school-approved retention, deletion, and legal hold rules. Before enabling traffic, inject unique synthetic sentinels into a path identifier, upload filename, query, referrer, body, token, email, and content field; exercise success and error paths and prove the sentinels are absent from Nginx access, application, journal, and SIEM views. Test request-ID correlation, redaction, log-delivery-failure alerting, and unauthorized-access alerting; retain only non-sensitive pass/fail evidence.

## Dependency lock maintenance

`requirements.in` and `requirements-dev.in` are review inputs; `requirements.txt` and `requirements-dev.txt` are the generated SHA-256 lock files used for installation. Regenerate them only in an isolated Python 3.13 environment. First install the separately locked toolchain with `python -m pip install --require-hashes --only-binary=:all: -r requirements-lock.txt`, then use that environment's `pip-compile` commands recorded in the generated lock headers. The toolchain lock deliberately carries compatible pip and pip-tools versions; update and review them together rather than installing an unpinned compiler from the network.

Review the input and generated diff, verify every generated entry retains hashes, run the complete dependency/security gates, and commit all related input/lock changes together. Never replace a hash-locked install with `pip install -r ...`, and never hand-edit generated dependency pins.

## Operator scripts

- Invoke operator scripts only with the absolute approved release-local Python path. They pin `/usr/lib/postgresql/17/bin` clients, require the canonical non-symlinked client directory, each executable, and every parent directory through `/` to be root-owned and not group/world writable, verify PostgreSQL 17 versions, replace inherited `PATH` with `/usr/bin:/bin`, and never search for database tools by name.
- `scripts/backup_postgres.py` fsyncs and atomically publishes a custom-format archive plus SHA-256 manifest in an existing canonical directory owned by the effective backup operator at exact mode `0700`; every parent directory through `/` must be non-symlinked, root- or operator-owned, and not group/world writable. A group/world-writable non-sticky parent is a deployment blocker because it can swap the validated directory; production `/srv` paths must not rely on a sticky temporary-directory exception. It reads the TLS PostgreSQL URL only from `DATABASE_URL`; no credential belongs in command-line arguments. Ignore and quarantine stale hidden `.*.partial` files or an archive without its manifest; never promote them, and delete an exact stale path only after audit/legal-hold review and peer approval.
- `scripts/restore_verify_postgres.py` accepts only a new `litblog_restore_verify_*` target, requires exact confirmation, never drops a database, and performs post-restore checks. Its `--verify-existing` mode is read-only, requires the approved federated-identity inventory count, and accepts only the current Alembic head after the disposable migration rehearsal. Copied archive/manifest inputs must share one canonical non-symlink staging directory owned by the restore operator at exact mode `0700`; both files must be owned by that operator and mode `0600`. Every parent directory through `/` has the same immutable ancestor requirement, including rejection of a non-sticky group/world-writable parent. The script verifies custody and checksum before database contact and repeats the full verification immediately before `pg_restore`.
- `scripts/release_switch.py` recursively validates root ownership and immutable modes, rejects unreviewed release-tree symlinks, verifies the release-local link resolves to reviewed root-owned Python 3.13, serializes switches with a protected lock, atomically replaces pointers, and fsyncs their directory. It refuses path traversal, real-file pointer replacement, and an orphan `previous` pointer without `current`; pointer recovery is a separate reviewed operator change.

Follow `docs/operations/production-runbook.md` for identity migration ordering, backup/restore drills, versioned activation and rollback, upload coupling, incident response, and school IT sign-off.

## Backup custody gate

The PostgreSQL script produces an owner-only custom archive, not an encrypted container. Fail the deployment unless `/srv/litblogs-backups` and every object-store replica provide verified encrypted at rest storage with school-controlled recovery keys. PostgreSQL and replication must use encrypted transport; the PostgreSQL URL specifically requires `sslmode=verify-full`. Use a separate least-privilege backup role, immutable checksum and access logging, and the runbook's retention, legal hold, and two-person deletion controls.

Credentials and encryption passphrases come only from a managed secret service or a protected file descriptor handled by a reviewed wrapper. They must not appear in command arguments, logs, tickets, or repo files.

## Artifact admission gate

The release workflow must build, test, and package under least privilege in `build-release` first. That job has read-only repository access and never enters the protected environment. Only after those outputs are complete may the separately approved `attest-release` job enter the protected environment, download the immutable bundle, and issue provenance and SBOM attestations; it must not execute bundle content or dependency tooling. Operators may accept the bundle only after `attest-release` succeeds.

Before extraction, verify the complete downloaded set with `sha256sum --check SHA256SUMS`, then use a school-pinned `gh attestation verify` with `--repo citdrhs/LitBlogs`, the exact `--signer-workflow`, `--source-ref refs/heads/main`, `--source-digest <reviewed-main-40-character-sha>`, and `--deny-self-hosted-runners`. Run it once for default build provenance and again with `--predicate-type https://cyclonedx.org/bom`. Require exactly one trusted provenance result and two SBOM attestations for the checksummed Python and frontend CycloneDX files. After extraction, require the embedded manifest commit to equal the complete reviewed main SHA. Pass that SHA to `release_switch.py activate` as `--expected-commit`; activation fails if it differs.
