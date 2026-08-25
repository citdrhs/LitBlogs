# Private-server deployment assets

These files are reviewed examples for a school-managed Linux server. Replace the example hostname and certificate paths in a reviewed site-specific copy; do not commit real credentials, student data, private keys, or internal hostnames.

## Least privilege layout

- `/opt/litblogs/releases/litblogs-<commit-prefix>`: immutable root-owned release trees, mode `0755` or stricter; application users cannot write here.
- `/opt/litblogs/current` and `/opt/litblogs/previous`: symlinks managed only by the release operator.
- `/var/lib/litblogs/uploads`: private writable upload store, owner `litblogs:litblogs`, mode `0750`; never expose it with an Nginx `alias`.
- `/var/lib/litblogs`: root-controlled parent, owner `root:litblogs`, mode `0750`; the service-owned upload root is its only writable child in this release.
- `/var/log/litblogs`: application/service logs if file logging is enabled, owner `litblogs:litblogs`, mode `0750`; prefer the journal forwarding to the school SIEM.
- `/etc/litblogs/litblogs.env`: production settings, owner `root:litblogs`, mode `0640`. It must not contain shell syntax and must never enter Git.
- `/etc/litblogs/password-reset.env`: the password-reset worker's minimal settings, owner `root:litblogs-reset`, mode `0640`; neither the web account nor unrelated services may read it.
- `/etc/litblogs/postgres-root-ca.pem`: the shared public PostgreSQL CA, a real non-symlinked `root:root` mode `0644` file beneath root-owned non-writable ancestors.
- `/etc/litblogs/tls`: TLS certificate chain readable by Nginx and private key readable only by root/Nginx, mode `0640` or stricter.
- `/srv/litblogs-backups`: encrypted, root-owned backup mount whose canonical, non-symlinked immediate output directory is owned by the reviewed root-controlled backup wrapper at exact mode `0700`; the `litblogs` web service cannot read or write this mount.

Create the web account as a locked service account with no interactive shell. Separately provision `litblogs-reset` as a locked system account with `/usr/sbin/nologin`, primary group `litblogs-reset`, and no supplementary groups, especially no `litblogs` membership. Separate application runtime, migration, backup, and restore database roles. The runtime role has no database creation, role management, schema ownership, replication, or server-file privileges.

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
LOCAL_PASSWORD_REGISTRATION_ENABLED=false
ADMIN_ACCESS_CODE=<managed-random-value-of-at-least-16-bytes>
TEACHER_INVITE_HMAC_KEY=<distinct-managed-random-value-of-at-least-32-bytes>
RESET_DATABASE_ON_STARTUP=false
API_DOCS_ENABLED=false
EMAIL_HOST=<school-approved-smtp-host>
EMAIL_PORT=587
EMAIL_USERNAME=<managed-smtp-account>
EMAIL_PASSWORD=<managed-random-smtp-secret-of-at-least-16-bytes>
EMAIL_FROM=<school-approved-sender-address>
PASSWORD_RESET_WORKER_ENABLED=true
PUSH_NOTIFICATIONS_ENABLED=false
UPLOAD_ROOT=/var/lib/litblogs/uploads
UPLOAD_SCANNER_REQUIRED=true
UPLOAD_SCANNER_HOST=<school-approved-private-scanner-host>
UPLOAD_SCANNER_ALLOWED_HOSTS=<comma-separated-exact-private-scanner-hosts>
UPLOAD_SCANNER_PORT=3310
UPLOAD_SCANNER_TIMEOUT_SECONDS=5
UPLOAD_REGISTRY_SCHEMA_READY=true
UPLOAD_LEGACY_IMPORT_COMPLETE=true
UPLOAD_BACKUP_RESTORE_VERIFIED=true
```

`DATABASE_URL` must name PostgreSQL, include an explicit username and unique non-placeholder managed password of at least 16 UTF-8 bytes, contain exactly `sslmode=verify-full` plus the canonical `/etc/litblogs/postgres-root-ca.pem`, use one DNS/IP host, and contain no libpq target override. Percent-encode every password character reserved by URL syntax before rendering the URL. Passwordless URLs, empty passwords, trust authentication, `.pgpass` fallback, and ambiguous peer/certificate-only authentication are deployment blockers; this release supports no alternate database authentication mechanism. A DBA must inspect the effective, ordered `pg_hba.conf` rules and prove the actual matching rule for each runtime, migration, backup, and restore connection is an exact `hostssl` rule using `scram-sha-256`, with no earlier broader `trust`, `md5`, peer, or certificate-only match. Confirm each login role has a SCRAM verifier without recording it. Through the same hostname, port, database, role, TLS mode, and CA path used by the service, a wrong-password probe and a rotated-old password probe must both fail while the managed current password succeeds; never place probe passwords in arguments or logs. Install the CA only as a real non-symlinked `root:root` mode `0644` regular file; the former group-only `0640` alternative is prohibited. Every parent directory from `/etc/litblogs` through `/` must be root-owned and not group/world writable, so the CA cannot be replaced after validation. Prove both service identities can read the public CA:

```text
runuser -u litblogs-reset -- test -r /etc/litblogs/postgres-root-ca.pem
runuser -u litblogs -- test -r /etc/litblogs/postgres-root-ca.pem
```

Supply the runtime credential through the protected environment file or an approved credential provider, never through a unit command line. `JWT_ISSUER` and `FRONTEND_URL` must be unambiguous HTTPS URLs. `CORS_ALLOWED_ORIGINS` must contain explicit HTTPS origins; `ALLOWED_HOSTS` and `ALLOWED_EMAIL_DOMAINS` are comma-separated exact DNS names without wildcards, schemes, ports, or paths. Localhost and reserved documentation domains such as `.example`, `.invalid`, and `.test` are production blockers, not acceptable placeholders. The two valid `__Host-` cookie names must remain distinct; their prefix also requires Secure transport, path `/`, and no Domain attribute.

Google and Microsoft IDs must be the exact registered values. `MICROSOFT_CLIENT_ID` and every tenant ID must be UUIDs, and `MICROSOFT_ALLOWED_TENANT_IDS` must include `MICROSOFT_TENANT_ID`. The browser obtains its public CSRF-cookie and OAuth identifiers from backend settings at runtime through `/api/runtime-config`; do not bake environment-specific `VITE_*` identity values into the frontend bundle. `EMAIL_HOST`, `EMAIL_USERNAME`, `EMAIL_PASSWORD`, and `EMAIL_FROM` are mandatory; `EMAIL_PORT` defaults to 587 but must be recorded explicitly for the school relay. Permit only an authenticated, certificate-validated TLS SMTP relay and test delivery without logging reset links or credentials.

Push delivery is deliberately disabled in this release: production must set `PUSH_NOTIFICATIONS_ENABLED=false`, leave `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, and `VAPID_SUBJECT` unset, and do not enable litblogs-reminders.timer. Enabling push remains a deployment blocker until endpoint validation, egress policy, and bounded dispatch behavior have a separately reviewed implementation. The bounded defaults for `JWT_CLOCK_SKEW_SECONDS`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `OAUTH_HTTP_TIMEOUT_SECONDS`, `OAUTH_JWKS_CACHE_SECONDS`, and the `DB_*` pool/timeout settings may be changed only through a reviewed capacity or security change.

## systemd installation

1. Review every unit in `deploy/systemd/` with school IT. Copy it with root ownership and mode `0644` into `/etc/systemd/system/`; never symlink system units to a writable checkout.
2. Install `/etc/litblogs/litblogs.env` as `root:litblogs` mode `0640`. Use the school secrets system to render it and rotate it; do not paste values into unit arguments. Render `/etc/litblogs/password-reset.env` separately as `root:litblogs-reset` mode `0640`. Its only permitted keys are `DATABASE_URL`, `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT_SECONDS`, `DB_POOL_RECYCLE_SECONDS`, `DB_CONNECT_TIMEOUT_SECONDS`, `DB_STATEMENT_TIMEOUT_MS`, `DB_LOCK_TIMEOUT_MS`, `FRONTEND_URL`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_SMTP_TIMEOUT_SECONDS`, `EMAIL_USERNAME`, `EMAIL_PASSWORD`, `EMAIL_FROM`, and `PASSWORD_RESET_CLAIM_TIMEOUT_SECONDS`; omit all web, signing, OAuth, administrator, upload, and scanner settings.
3. In a fresh candidate tree, create the release-local environment with Python 3.13 and install from `litblogs/requirements.txt` using `python -m pip install --require-hashes --only-binary=:all: -r requirements.txt`. Run the release-local artifact/config `deployment_check --preflight`, then apply the final root-owned seal; never modify the sealed release. An unhashed install or any install that permits a source distribution is prohibited in production. The shipped web unit uses `Type=simple`, runs its database-head postflight with `/opt/litblogs/current/.venv/bin/python -m deployment_check`, and starts `/opt/litblogs/current/.venv/bin/uvicorn`. Password-reset delivery and upload reconciliation are external bounded one-shot services; they are never in-process web threads. The dormant reminder unit runs `/opt/litblogs/current/.venv/bin/python -m reminder_job`. Do not override these commands with a shared mutable virtual environment: source rollback without dependency rollback is not safe.
   The release allowlist and preflight must include `litblogs/migrations/sqlite_contract.py` with the Alembic environment, template, and reviewed revisions, plus the executed top-level `litblogs/password_reset_delivery.py` and `litblogs/runtime_database_identity.py` modules. These are runtime code; a candidate missing any of them is incomplete and must not start.
4. Run `systemd-analyze security` for the web service and both maintenance services and review every exception. Then run `systemctl daemon-reload`, enable `litblogs-web.service`, and verify every service still has only its documented writable paths. The maintenance timers must remain disabled until the exact egress drop-ins below pass review and both one-shot smoke runs succeed. While push is disabled, run `systemctl disable --now litblogs-reminders.timer` and do not enable `litblogs-reminders.timer`.
5. Bind Uvicorn only to loopback. Only the Nginx account may reach the loopback port through local policy; no host firewall rule exposes it.

Keep Uvicorn in the foreground under the shipped `Type=simple` unit and validate startup plus readiness behavior in staging before enabling it. Treat an early process exit, configuration-gate failure, or readiness failure as a deployment blocker, not a reason to weaken service protections.

### Maintenance egress and timer gate

Both maintenance service/timer pairs ship with two root-controlled `ConditionPathExists` gates: the service-specific `egress.conf` and its boot-ephemeral `/run/litblogs-maintenance-egress/<job>.port-policy-ready` marker. Each service also has `IPAddressDeny=any`. Create `/etc/systemd/system/litblogs-upload-reconciliation.service.d/egress.conf` only after resolving and recording every PostgreSQL address used by the runtime URL; its `[Service]` section contains one exact `IPAddressAllow=<postgres-ip>/32` (or `/128`) per address. `IPAddressAllow` filters addresses, not destination ports, so it is defense in depth and is not database-only egress by itself. Install a unit/cgroup-specific host-firewall rule or an isolated network namespace that permits only each exact resolved PostgreSQL address at the port configured in `DATABASE_URL` and rejects every other address and port. Do not permit a subnet, DNS resolver, proxy, web endpoint, or public default route. The reconciliation job performs registry/object cleanup only: it has no malware scanner or scanner-socket access and must not receive it. Use the host's reviewed local name-resolution path or a root-controlled canonical address mapping so runtime resolution cannot require broader process egress.

Create `/etc/systemd/system/litblogs-password-reset.service.d/egress.conf` with exact resolved PostgreSQL addresses and exact resolved SMTP addresses only, again as individual `/32` or `/128` `IPAddressAllow` entries. Its external unit/cgroup or namespace policy permits only those PostgreSQL addresses at the configured database port and those SMTP addresses at the configured `EMAIL_PORT`. Password reset needs the authenticated TLS SMTP relay as well as PostgreSQL; it needs no other Internet access. Both `egress.conf` files and every ancestor must be non-symlinked, `root:root`, not group/world writable, and reviewed after any database or SMTP address change. An absent, empty, stale, broad, or unreviewed allowlist or exact-port policy is a deployment blocker; `litblogs-password-reset.timer` and `litblogs-upload-reconciliation.timer` must remain disabled.

The upload-reconciliation entry module reuses its reviewed function from `main`, whose import validates the global private-upload configuration. Pre-create `/var/lib/litblogs/uploads/objects` and `/var/lib/litblogs/uploads/.incoming` as real `litblogs:litblogs` directories at mode `0700`; upload reconciliation alone receives that root as a narrow writable path. Password reset runs as the dedicated `litblogs-reset` identity through `password_reset_delivery.py` and its minimal worker settings: the verified runtime database URL plus bounded pool/timeouts, HTTPS frontend reset origin, SMTP host/port/TLS-timeout credentials and sender, and reset-claim timeout only. It does not import `main` or validate `UPLOAD_ROOT`, has no upload `ReadWritePaths` or upload precheck, and invokes no upload routine. The effective unit must retain `InaccessiblePaths=/etc/litblogs/litblogs.env /var/lib/litblogs/uploads`. Before enabling it, run service-context read and write probes under a transient unit with the same `User`, `Group`, and `InaccessiblePaths`: reading the web environment and reading or writing the upload root must all fail, while reading `/etc/litblogs/password-reset.env` and the canonical PostgreSQL CA must succeed. Also prove `litblogs` cannot read the reset environment and that `litblogs-reset` has no supplementary groups. Both maintenance services allow only `AF_INET` and `AF_INET6`, so `AF_UNIX` scanner sockets are unavailable and must fail the service-context negative probes.

On every boot and after every database, SMTP, address, port, unit, or firewall change, remove both `.port-policy-ready` markers before installing the rules. After `systemctl daemon-reload`, inspect the effective units with `systemctl cat` and prove the policy is tied to the exact service cgroup or isolated namespace. Positive probes must reach only the configured PostgreSQL IP:port and, for password reset, configured SMTP IP:port. Negative probes from each service context must reject an alternate port on every allowed IP, every unlisted address, every scanner network endpoint, and every scanner Unix socket. Only after those probes pass may root create `/run/litblogs-maintenance-egress` as `root:root` and non-writable to service identities, then create the matching root-owned `password-reset.port-policy-ready` or `upload-reconciliation.port-policy-ready` marker. The markers are recreated and revalidated each boot and after every address or policy change; existence never substitutes for retained firewall evidence. Require each one-shot to exit zero, complete within the effective five-minute `TimeoutStartSec=300` bound, and emit no secret/content logging. Then enable `litblogs-password-reset.timer` and `litblogs-upload-reconciliation.timer`; they must remain disabled otherwise. systemd serializes each service on one host; the database claim/version and row-lock protocol serializes concurrent workers across hosts. Alert on nonzero or timed-out units. Push remains separate and disabled: do not enable `litblogs-reminders.timer`.

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
- `scripts/backup_postgres.py` requires `--confirm-writes-quiesced` and the local `/var/lib/litblogs/uploads` root. Before registry/file reads or `pg_dump`, it requires the exact `litblogs_backup` session, non-admin role attributes, a complete recursive membership closure containing only the direct non-admin `pg_read_all_data` edge, target-database `CONNECT` without `CREATE`/`TEMPORARY`, no effective schema/table/column/sequence/function write or execute privilege, and no direct application ACL or reverse membership. Neither the backup role nor any role in its recursive membership closure may own a database, schema, relation, routine, or type. It requires the upload root to be the reviewed `litblogs:litblogs` mode-`0750` directory, while every ancestor through `/` is root-owned and not group/world writable; a service-owned `/var/lib/litblogs` parent is rejected because it could rename the validated root. The root's immediate entries must be exactly `objects` and `.incoming`. It compares complete registry inventories before/after capture, including `DELETED` tombstones, creates a deterministic USTAR only for file-backed states, preserves PostgreSQL owners/ACLs, and fsyncs/publishes exactly the dump, upload tar, sorted inventory, and manifest in manifest-last order. The existing output directory is canonical, operator-owned mode `0700`, encrypted at rest, and has no replaceable ancestor. Every parent directory is checked; a non-sticky group/world-writable parent is rejected. Ignore and quarantine private partials or unmanifested artifacts; never promote or silently delete them.
- `scripts/restore_verify_postgres.py` accepts only one four-file manifest, a new empty private `litblog_restore_uploads_*` root under a non-replaceable trusted ancestor chain, and a new `litblog_restore_verify_*` database with exact confirmation. On an isolated cluster, a temporary privileged restore DBA applies preserved owner/ACL entries after five exact-name NOLOGIN stand-ins (including `litblogs_migrator`) are provisioned. The script then proves all application schema/table/type/sequence ownership is `litblogs_migrator`, exactly three reviewed routines are owned by `litblog_identity_owner`, and each routine's byte-exact body plus language, return, volatility, parallel, strict/leakproof, kind, defaults, security-definer, and configuration metadata matches the reviewed c513 source. It also proves `public` is the only non-system schema, the exact global default-function ACL has only the migrator owner entry and no schema-scoped substitute, the target database has no non-owner `CONNECT`/`TEMPORARY` ACL, and the complete f1 ACL/grantee/membership matrix matches. It restores/extracts safely, compares every registry row and file-backed object, and never drops a database or deletes failed evidence. `--verify-existing` repeats the read-only database/file checks.
- `scripts/release_switch.py` recursively validates root ownership and immutable modes, rejects unreviewed release-tree symlinks, verifies the release-local link resolves to reviewed root-owned Python 3.13, serializes switches with a protected lock, atomically replaces pointers, and fsyncs their directory. It refuses path traversal, real-file pointer replacement, and an orphan `previous` pointer without `current`; pointer recovery is a separate reviewed operator change.

Follow `docs/operations/production-runbook.md` for identity migration ordering, backup/restore drills, versioned activation and rollback, upload coupling, incident response, and school IT sign-off.

## Initial legacy recovery gate

The initial legacy rollout is blocked because upload_assets does not exist before the first migration and legacy files may be unmapped. Do not run backup_postgres.py against that state. With every writer stopped, school IT must take one separately reviewed storage-native pre-migration checkpoint that binds a recoverable PostgreSQL snapshot/custom dump and the entire legacy upload filesystem by an immutable ID, hashes, custody, encryption, and restore evidence. Then complete the offline legacy upload inventory and import, reconcile every registry/file binding, reach `f1ad78b2035f`, and create/rehearse the first current-head coupled recovery set. Traffic remains blocked until both recovery paths pass.

## Backup custody gate

The four-file recovery set is owner-only, not an encrypted container. Fail the deployment unless `/srv/litblogs-backups` and every replica provide verified encryption at rest with school-controlled recovery keys. PostgreSQL and replication must use encrypted transport; the PostgreSQL URL specifically requires `sslmode=verify-full`. Use only the dedicated `litblogs_backup` login with the exact non-admin attributes in the runbook, sole membership in `pg_read_all_data`, no application-role membership or direct application-object ACL, no ownership anywhere in the effective role closure, and `CONNECT` to exactly the production LitBlogs database. Revoke `PUBLIC CONNECT,TEMPORARY` on that database, grant the backup role only `CONNECT`, revoke default cross-database access, enforce the database-specific `hostssl` rule, and prove the exact `pg_database`/`has_database_privilege` result before use. Retain immutable checksum/access logging and the runbook's retention, legal hold, and two-person deletion controls. Replicate all four manifest-bound files together and accept only a durably published manifest.

Credentials and encryption passphrases come only from a managed secret service or a protected file descriptor handled by a reviewed wrapper. They must not appear in command arguments, logs, tickets, or repo files.

## Artifact admission gate

The release workflow must build, test, and package under least privilege in `build-release` first. That job has read-only repository access and never enters the protected environment. Only after those outputs are complete may the separately approved `attest-release` job enter the protected environment, download the immutable bundle, and issue provenance and SBOM attestations; it must not execute bundle content or dependency tooling. Operators may accept the bundle only after `attest-release` succeeds.

Before extraction, verify the complete downloaded set with `sha256sum --check SHA256SUMS`, then use a school-pinned `gh attestation verify` with `--repo citdrhs/LitBlogs`, the exact `--signer-workflow`, `--source-ref refs/heads/main`, `--source-digest <reviewed-main-40-character-sha>`, and `--deny-self-hosted-runners`. Run it once for default build provenance and again with `--predicate-type https://cyclonedx.org/bom`. Require exactly one trusted provenance result and two SBOM attestations for the checksummed Python and frontend CycloneDX files. After extraction, require the embedded manifest commit to equal the complete reviewed main SHA. Pass that SHA to `release_switch.py activate` as `--expected-commit`; activation fails if it differs.
