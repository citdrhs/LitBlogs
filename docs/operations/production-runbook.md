# LitBlogs private-server production runbook

This runbook is an operator handoff, not an authorization to deploy. LitBlogs processes student work, profiles, class membership, and teacher feedback. Production stays offline until the application stack is reviewed, every required check is green, historically exposed credentials are rotated, legacy identities are mapped, and school IT signs the go/no-go record.

## Service objectives and ownership

The minimum recovery point objective (RPO) is 15 minutes. PostgreSQL WAL archiving or an equivalent managed point-in-time recovery service must meet that objective; the custom-format backup script is a portable recovery artifact, not a replacement for WAL archiving. The recovery time objective (RTO) is four hours from incident declaration to a verified read-only service, unless the school approves stricter targets.

School IT owns and records the approved RPO/RTO, service owner, database administrator, privacy officer, security incident lead, communications lead, and after-hours escalation contacts. Review those names and phone numbers every term.

## Hard deployment blockers

Abort the rollout if any item below is unresolved:

- Any historically committed or otherwise exposed application, database, email, OAuth, VAPID, access-code, admin-code, TLS, backup, or signing secret is still valid.
- The school cannot produce a trusted provider/issuer/subject mapping for every active legacy OAuth-only account. Email-only account linking or backfilling is prohibited.
- The production database has not been backed up and restored into a disposable `litblog_restore_verify_*` database on an isolated PostgreSQL instance.
- The restored copy has not completed the exact Alembic rehearsal and critical student/teacher journeys that will run in production.
- The database and upload store cannot be recovered to a mutually consistent point.
- The release artifact checksum, provenance attestation, commit manifest, independent review, or required checks cannot be verified.
- TLS, host firewall, reverse proxy, malware scanning, centralized audit logs, alerting, encrypted backup storage, restore credentials, or an on-call owner is missing.
- There is no approved maintenance window, rollback owner, or privacy/incident communications path.

## Production configuration preflight

Treat `litblogs/.env.example` as development-only. Its local cookie names are deliberately not `__Host-` names because local development uses `SESSION_COOKIE_SECURE=false`; neither that setting nor its placeholder values may be promoted. School IT renders the root-controlled `/etc/litblogs/litblogs.env` from the managed secret source, and a second operator compares every entry below with the approved DNS, identity-provider, database, email, and privacy records. Angle-bracketed entries are requirements, not literal values.

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

The PostgreSQL URL must include an explicit username and unique non-placeholder managed password of at least 16 UTF-8 bytes, contain exactly `sslmode=verify-full` and `sslrootcert=/etc/litblogs/postgres-root-ca.pem`, use one canonical DNS name or IP address, and contain no service, options, multi-host, or alternate-target override. Percent-encode every password character reserved by URL syntax before rendering the URL. Passwordless URLs, empty passwords, trust authentication, `.pgpass` fallback, and ambiguous peer/certificate-only authentication are deployment blockers; this release supports no alternate database authentication mechanism. The DBA must inspect the effective ordered `pg_hba.conf` and record that the actual matching rule for every runtime, migration, backup, and restore connection is a narrowly scoped `hostssl` rule using `scram-sha-256`, with no earlier broader `trust`, `md5`, peer, or certificate-only match. Record only a boolean that each login role's stored verifier is SCRAM, never the verifier. Against the exact hostname, port, database, role, `sslmode`, and CA path used in service, run a wrong-password probe and a rotated-old password probe; both must fail, while the managed current password must succeed. Keep all three probe credentials in the managed secret wrapper or protected file descriptor and out of arguments, shell history, tickets, and logs. Install that CA as a real non-symlinked regular file owned by `root:root` mode `0644` or `root:litblogs` mode `0640`; group/world write is forbidden. Every parent directory from `/etc/litblogs` through `/` must be root-owned and not group/world writable. Run preflight as the `litblogs` service identity so readability is proven rather than inferred from a root access check. `SECRET_KEY`, `TEACHER_ACCESS_CODE`, and `EMAIL_PASSWORD` must be independently generated, non-placeholder managed secrets; the application secret needs at least 32 bytes and 12 distinct characters, while the other two need at least 16 bytes. Never put any of them in command arguments, Git, tickets, or validation logs.

`JWT_ISSUER` and `FRONTEND_URL` must be HTTPS. `CORS_ALLOWED_ORIGINS` is a comma-separated list of explicit HTTPS origins. `ALLOWED_HOSTS` and `ALLOWED_EMAIL_DOMAINS` contain exact DNS names, not wildcards, URLs, ports, or paths. Localhost and reserved documentation domains such as `.example`, `.invalid`, and `.test` fail production preflight. The session and CSRF names must be distinct valid `__Host-` cookie names; retain Secure, path `/`, and no Domain attribute. Microsoft application and tenant identifiers must be UUIDs, the allowlist must include the fixed tenant, and the Google ID must be the exact registered `.apps.googleusercontent.com` value.

The authenticated school SMTP relay requires `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USERNAME`, `EMAIL_PASSWORD`, and `EMAIL_FROM`; verify certificate-validated TLS, sender policy, rate limits, bounce handling, and a synthetic reset-message delivery before go-live. Push dispatch is deliberately disabled in this release. Production must retain `PUSH_NOTIFICATIONS_ENABLED=false`, leave `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, and `VAPID_SUBJECT` unset, and do not enable litblogs-reminders.timer. A later push implementation requires separate endpoint-validation, egress, and bounded-timeout review. Changes to `JWT_CLOCK_SKEW_SECONDS`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `OAUTH_HTTP_TIMEOUT_SECONDS`, `OAUTH_JWKS_CACHE_SECONDS`, or any `DB_*` pool/timeout setting require the same review as a code change.

The browser obtains its public CSRF-cookie name and OAuth identifiers from backend settings at runtime through `/api/runtime-config`; never put environment-specific `VITE_*` identity values in the built bundle. On the unsealed candidate, run `/opt/litblogs/releases/<release-id>/.venv/bin/python -m deployment_check --preflight` with the approved production-shaped environment. This validates Python 3.13, configuration, the release manifest/required files, and the runtime-config frontend contract; the database check is deliberately skipped so it can run before migrations. The check emits only an allowlisted reason code (`config_invalid`, `interpreter_invalid`, `manifest_invalid`, or `frontend_contract_invalid`) and never a setting value. Run the default database postflight only after migrations with the least-privilege runtime database role; it adds `database_unreachable` or `migration_mismatch`. Record only the code and pass/fail outcome.

## Legacy OAuth identity and Alembic adoption

`migrations/0001_create_federated_identities.sql` was a temporary bridge and is superseded by the Alembic migration chain. Do not execute it for this rollout. Never run both the raw SQL identity script and the Alembic identity revision.

Every production or rehearsal Alembic CLI command below runs inside the approved migration wrapper with only `LITBLOGS_MIGRATION_DATABASE_URL` exposed. That URL names the migration role and contains the same strict `sslmode`/`sslrootcert` contract; do not expose `DATABASE_URL` or load application, JWT, SMTP, OAuth, teacher-code, or other runtime secrets into the migration process. A programmatic verifier may instead provide an already validated SQLAlchemy connection and no environment credential.

Before touching production, inventory whether the raw script was ever run. If its table or constraints already exist outside the Alembic ledger, abort the automated rollout. A DBA must compare the live definition and data with the reviewed revision, preserve any subject bindings, and approve a dedicated reconciliation path. Do not guess, delete the table, stamp past unverified work, or retry the identity revision blindly.

For an empty database, use only:

```text
cd /opt/litblogs/releases/<release-id>/litblogs
/opt/litblogs/releases/<release-id>/.venv/bin/python -m alembic -c /opt/litblogs/releases/<release-id>/litblogs/alembic.ini upgrade head
/opt/litblogs/releases/<release-id>/.venv/bin/python -m alembic -c /opt/litblogs/releases/<release-id>/litblogs/alembic.ini current --check-heads
/opt/litblogs/releases/<release-id>/.venv/bin/python -m alembic -c /opt/litblogs/releases/<release-id>/litblogs/alembic.ini check
```

For a verified pre-Alembic LitBlogs schema, a DBA first compares every table, column, constraint, index, and enum with baseline revision `985a04df032a`. `stamp` records history; it does not change or validate schema. Only after the comparison is signed and the disposable rehearsal succeeds, run:

```text
cd /opt/litblogs/releases/<release-id>/litblogs
/opt/litblogs/releases/<release-id>/.venv/bin/python -m alembic -c /opt/litblogs/releases/<release-id>/litblogs/alembic.ini stamp 985a04df032a
/opt/litblogs/releases/<release-id>/.venv/bin/python -m alembic -c /opt/litblogs/releases/<release-id>/litblogs/alembic.ini upgrade head
/opt/litblogs/releases/<release-id>/.venv/bin/python -m alembic -c /opt/litblogs/releases/<release-id>/litblogs/alembic.ini current --check-heads
/opt/litblogs/releases/<release-id>/.venv/bin/python -m alembic -c /opt/litblogs/releases/<release-id>/litblogs/alembic.ini check
```

The safe order for legacy OAuth is:

1. Before migration, export an inventory of active OAuth-only accounts and obtain immutable Google or Microsoft provider, issuer, and subject evidence from the identity provider or a supervised recovery ceremony. Do not treat matching email addresses as identity proof.
2. Abort if a trusted subject cannot be established for any account that must remain active. Put that account through school-approved recovery instead of implicit linking.
3. Rehearse baseline adoption and `alembic upgrade head` on the disposable restored database.
4. In the production maintenance window, stop the web and reminder services, take a final coupled database/upload recovery point, then run the reviewed Alembic path.
5. Populate the new identity bindings from the approved evidence while the application is still offline. Verify uniqueness, provider, issuer, subject, and intended user for every row with a second operator.
6. Rotate authentication secrets and invalidate pre-cutover sessions. Enable the application only after identity counts and supervised sample logins agree with the signed inventory.

## Backup procedure

Use a dedicated least-privilege backup role with only the PostgreSQL privileges required by `pg_dump`. The operator environment supplies `DATABASE_URL`; never paste a credential-bearing URL into a command argument, ticket, shell history, or log. The URL must use `sslmode=verify-full` so database authentication and backup data use encrypted transport with hostname and CA verification.

The script emits a custom-format dump with owner-only permissions, but it does not encrypt the archive itself. Fail the deployment unless the output directory is on a school-verified encrypted at rest volume and every replicated object destination enforces encryption with school-controlled keys. Record the volume/object policy and a recovery-key test in the go/no-go evidence. Encryption passphrases and database credentials must come from a managed secret facility or a protected file descriptor supplied by a reviewed operator wrapper; they must never appear in command lines, logs, tickets, environment files committed to the repo, or repository files. The absolute output path must be canonical with no symlink in its ancestor chain, and its immediate directory must already exist, be owned by the effective backup operator, and have exact owner-only mode `0700`. Every parent directory through `/` must be root- or operator-owned and not group/world writable. A group/world-writable non-sticky parent can rename the validated child and is a deployment blocker; production backup paths under `/srv` must not rely on a sticky temporary-directory exception.

```text
umask 077
/opt/litblogs/releases/<release-id>/.venv/bin/python \
  /opt/litblogs/releases/<release-id>/deploy/scripts/backup_postgres.py \
  --output-dir /srv/litblogs-backups/daily
```

Use only the approved release-local Python above. Before any secret-bearing PostgreSQL call, the operator entry point requires the canonical `/usr/lib/postgresql/17/bin` directory and its ancestor chain to contain no symlink, requires that client directory, every parent directory through `/`, and each executable to be root-owned and not group/world writable, and checks every client's reported PostgreSQL 17 major version. The immutable directory custody prevents a validated executable pathname from being swapped before a credential-bearing call. Commands never resolve through the inherited PATH; the child environment replaces it with `/usr/bin:/bin` and strips libpq target overrides. Abort if the site package layout differs until school IT reviews and updates the pinned code—do not add a PATH lookup or environment override.

The script fsyncs the completed custom archive and a private temporary JSON SHA-256 manifest, publishes each name atomically without overwriting an existing file, fsyncs the parent directory, and prints paths only after durable publication. Replicate both files together over encrypted transport to a separately administered encrypted destination. Verify the off-site object checksum after transfer. Enable immutable access logging for backup reads, writes, copies, restore access, retention changes, legal holds, and deletion approvals; alert on access outside the backup/restore roles. Database credentials do not belong in the archive directory.

A crash can leave a hidden `.*.partial` work file or an unacknowledged archive without its manifest. Scheduled replication and restore tooling must ignore these objects. Quarantine them, correlate the backup-job and storage audit records, and check legal-hold state; only the backup operator may delete an exact stale path after peer approval. Never rename a stale partial into service or synthesize a missing manifest. Run a fresh backup and accept only the newly reported archive/manifest pair.

The database administrator must additionally monitor WAL archival lag against the 15-minute RPO. Alert if a scheduled backup, manifest replication, or WAL segment fails. A successful process exit without an off-site copy is not a successful backup.

## Restore verification procedure

Run verification on an isolated host or cluster that has no route from students, teachers, the production application role, or the internet. The restore operator may create databases there but must have no production drop privilege. The restore script never drops a database, including on failure.

Choose a new lowercase name under the synthetic namespace and repeat it as the confirmation:

```text
/opt/litblogs/releases/<release-id>/.venv/bin/python \
  /opt/litblogs/releases/<release-id>/deploy/scripts/restore_verify_postgres.py \
  --archive /srv/litblogs-backups/daily/<archive>.dump \
  --manifest /srv/litblogs-backups/daily/<archive>.dump.manifest.json \
  --target-database litblog_restore_verify_20260821_a1 \
  --confirm-target litblog_restore_verify_20260821_a1
```

The script rejects default/production names, connection-target overrides, malformed manifests, non-custom archives, checksum mismatches, and existing databases. On POSIX the archive and manifest must share one absolute canonical staging directory with no symlink ancestor; that immediate directory is owned by the effective restore operator at exact mode `0700`, and both files are owned by that operator with mode `0600`. Every parent directory through `/` must be root- or operator-owned and not group/world writable; a non-sticky writable parent is rejected before database contact. After copying an encrypted replica into that isolated staging area, use an exact-path, no-overwrite copy procedure to set custody; verify checksum/audit custody again and never relax permissions to share the files. It validates custody and the complete archive hash before database contact, repeats both checks immediately before `pg_restore`, and restores in one transaction. It reports `pre_alembic` only when the complete expected legacy core table set, every expected core foreign key, readable core data, and all restored foreign/check constraints pass while both `alembic_version` and `federated_identities` are absent. It reports `current_head` only when both new tables exist, the ledger is exactly at the release's reviewed head, and the federated identity schema and data pass. Any partial, mixed, unknown, or old-revision state fails closed. A failed verification database is retained for investigation; deletion is a separate DBA change with an exact target, peer review, and legal-hold check.

When the first result is `pre_alembic`, a DBA must complete and sign the full baseline comparison described above before stamping. Then use that same isolated disposable copy to rehearse the exact adoption path; do not run `upgrade` against an unstamped legacy schema:

```text
cd /opt/litblogs/releases/<release-id>/litblogs
/opt/litblogs/releases/<release-id>/.venv/bin/python -m alembic -c /opt/litblogs/releases/<release-id>/litblogs/alembic.ini stamp 985a04df032a
/opt/litblogs/releases/<release-id>/.venv/bin/python -m alembic -c /opt/litblogs/releases/<release-id>/litblogs/alembic.ini upgrade head
/opt/litblogs/releases/<release-id>/.venv/bin/python -m alembic -c /opt/litblogs/releases/<release-id>/litblogs/alembic.ini current --check-heads
/opt/litblogs/releases/<release-id>/.venv/bin/python -m alembic -c /opt/litblogs/releases/<release-id>/litblogs/alembic.ini check
```

Populate federated identities only from the signed provider/issuer/subject inventory, while the disposable application remains offline. A second operator compares every binding to that inventory and records its approved total; an aggregate count is not a substitute for the row-by-row identity review. If the first restore already reported `current_head`, perform this inventory review before continuing anyway.

Run the read-only second verifier against the existing synthetic database. It requires the exact synthetic target and confirmation, performs no create, restore, or drop operation, requires the reviewed Alembic head, and compares the valid federated mapping count with the approved inventory without printing identities or counts:

```text
/opt/litblogs/releases/<release-id>/.venv/bin/python \
  /opt/litblogs/releases/<release-id>/deploy/scripts/restore_verify_postgres.py \
  --verify-existing \
  --target-database litblog_restore_verify_20260821_a1 \
  --confirm-target litblog_restore_verify_20260821_a1 \
  --expected-federated-identities <approved-inventory-count>
```

Abort unless this second verifier reports `current_head`. Then point a non-production application instance at the disposable database and restored upload snapshot. Run readiness, login, legacy OAuth recovery, student post/like/comment/enrollment/settings journeys, and teacher class/create/archive/delete/view/profile/post journeys. Record start/end times, restored revision, row-count checks, upload-reference audit, operators, failures, and measured RPO/RTO. Never copy restored student data to developer laptops or third-party services.

## Backup retention and legal hold

Unless the school records a stricter approved schedule, retain 35 daily recovery artifacts, 12 month-end artifacts, and the point-in-time recovery stream necessary to meet the RPO. Encryption keys must be stored separately from backup media, escrowed to two authorized school officers, rotated on schedule, and tested.

The privacy officer and records owner approve retention, deletion, litigation hold, and student-record obligations. A legal hold suspends normal expiry for exactly identified artifacts; it does not justify retaining every backup indefinitely. Keep an immutable audit trail of hold placement, access, release, and final destruction. A two-person review is required before backup destruction, and automated retention deletion must fail closed when hold state cannot be read.

Perform a quarterly restore drill using a randomly selected off-site artifact and the synthetic restore procedure. At least annually, include loss of the primary database host, upload store, and one key custodian. Track corrective actions to closure.

## Upload store coupling

Uploads live outside the source tree at `/var/lib/litblogs/uploads`; they contain private student content and are not public static files. Back up the upload store with encryption, malware controls, immutable retention, and access logging. A database backup and upload snapshot form one recovery set: record their common checkpoint or quiesce writes so database references cannot move ahead of file content.

During recovery, restore the database and upload store together, keep both isolated, and run an ownership/class-membership reference audit before enabling traffic. Report missing, orphaned, quarantined, oversized, or hash-mismatched files. Profile/cover replacement and post, class, or account deletion must follow the application retention policy; do not preserve retrievable orphan uploads merely because the database row was deleted. Legal hold is the only documented override.

## Versioned release activation

The workflow must build, test, and package under least privilege in `build-release` before any protected-environment approval. That read-only job creates the immutable bundle and SBOMs without attestation authority. The separately approved `attest-release` job then enters the protected environment, downloads those exact outputs, and issues provenance and SBOM attestations without executing bundle content or dependency tooling. Accept the bundle only after `attest-release` succeeds; protected-environment approval must never authorize untrusted build or dependency execution.

Only use that reviewed `main` artifact. Record its reviewed main SHA from the signed change record; do not infer approval from a filename or branch name. Before extraction, place the still-untrusted artifact, `SHA256SUMS`, and both SBOM files in a quarantined operator directory and run:

```text
sha256sum --check SHA256SUMS
gh attestation verify litblogs-<12-character-commit-prefix>.tar.gz \
  --repo citdrhs/LitBlogs \
  --signer-workflow citdrhs/LitBlogs/.github/workflows/release.yml \
  --source-ref refs/heads/main \
  --source-digest <reviewed-main-40-character-sha> \
  --deny-self-hosted-runners --format json
gh attestation verify litblogs-<12-character-commit-prefix>.tar.gz \
  --repo citdrhs/LitBlogs \
  --signer-workflow citdrhs/LitBlogs/.github/workflows/release.yml \
  --source-ref refs/heads/main \
  --source-digest <reviewed-main-40-character-sha> \
  --deny-self-hosted-runners \
  --predicate-type https://cyclonedx.org/bom --format json
```

School IT must pin the GitHub CLI/verifier version and package digest in the operator image. The first command verifies the default SLSA provenance predicate; the second explicitly verifies the non-default CycloneDX predicate. Require the first JSON result to contain exactly one build-provenance attestation and the second to contain exactly two SBOM attestations whose embedded content corresponds to the separately checksummed Python and frontend SBOM files. Abort on a missing, extra, untrusted, self-hosted, wrong-workflow, wrong-repository, wrong-ref, or wrong-commit attestation.

Only after checksum and attestation verification may the operator extract the artifact into a fresh, root-controlled candidate directory named `litblogs-<12-character-commit-prefix>` under `/opt/litblogs/releases`. It is not yet a sealed release. Verify that the embedded `RELEASE-MANIFEST` commit equals the complete reviewed main SHA and ensure no path is a symlink or group/world writable.

The activation operation is `release_switch.py activate`; it always requires the exact release identifier twice.

Build and validate the release-local virtual environment before the final root-owned seal:

```text
/usr/bin/python3.13 -m venv /opt/litblogs/releases/litblogs-<12-character-commit-prefix>/.venv
cd /opt/litblogs/releases/litblogs-<12-character-commit-prefix>/litblogs
/opt/litblogs/releases/litblogs-<12-character-commit-prefix>/.venv/bin/python -m pip install --require-hashes --only-binary=:all: -r /opt/litblogs/releases/litblogs-<12-character-commit-prefix>/litblogs/requirements.txt
/usr/sbin/runuser --user litblogs -- /opt/litblogs/releases/litblogs-<12-character-commit-prefix>/.venv/bin/python -m deployment_check --preflight
```

An unhashed install or any interpreter other than Python 3.13 is prohibited. The preflight verifies the candidate artifact, required operational files, production-shaped configuration, and compiled `/api/runtime-config` contract; its database check is deliberately skipped. After it passes, apply the final root-owned seal to the entire release, including `.venv`, and verify recursively that the `litblogs` service account cannot write any path. Never install or modify files in a sealed release.

Stop public traffic and all writers. Before migration, the database owner must transfer the `public` schema and every enumerated LitBlogs table, sequence, and enum/type from the signed inventory to `litblogs_migrator`; do not use a blanket `REASSIGN OWNED` that could capture unrelated objects. The owner then runs the following before relinquishing the session:

```sql
ALTER SCHEMA public OWNER TO litblogs_migrator;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
```

As `litblogs_migrator`, install default privileges before creating any new object:

```sql
ALTER DEFAULT PRIVILEGES FOR ROLE litblogs_migrator IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO litblogs_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE litblogs_migrator IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO litblogs_runtime;
```

The DBA's approved secret-execution wrapper must then supply only `LITBLOGS_MIGRATION_DATABASE_URL` to the release-local Alembic process. That role owns/alters only the application schema and has no application login, role-management, replication, database-creation, or server-file privilege. Never expose this URL as `DATABASE_URL`, place it in an argument, store it in `/etc/litblogs/litblogs.env`, or load any application secrets. Use the explicit release cwd and config, then require the read-only drift check before removing the credential:

```text
cd /opt/litblogs/releases/litblogs-<12-character-commit-prefix>/litblogs
/opt/litblogs/releases/litblogs-<12-character-commit-prefix>/.venv/bin/python -m alembic -c /opt/litblogs/releases/litblogs-<12-character-commit-prefix>/litblogs/alembic.ini upgrade head
/opt/litblogs/releases/litblogs-<12-character-commit-prefix>/.venv/bin/python -m alembic -c /opt/litblogs/releases/litblogs-<12-character-commit-prefix>/litblogs/alembic.ini current --check-heads
/opt/litblogs/releases/litblogs-<12-character-commit-prefix>/.venv/bin/python -m alembic -c /opt/litblogs/releases/litblogs-<12-character-commit-prefix>/litblogs/alembic.ini check
```

Abort on any `alembic check` drift even when the ledger says current head. Then explicitly provision the runtime role after migration. Run the following reviewed SQL as the migration owner (with database-level `CONNECT` revoke/grants performed separately by the database owner):

```sql
GRANT USAGE ON SCHEMA public TO litblogs_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO litblogs_runtime;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO litblogs_runtime;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON TABLE alembic_version FROM litblogs_runtime;
GRANT SELECT ON TABLE alembic_version TO litblogs_runtime;
```

Do not grant schema `CREATE`, table ownership, `TRUNCATE`, `REFERENCES`, `TRIGGER`, database creation, role administration, replication, bypass-RLS, or server-file privileges to `litblogs_runtime`. As a second operator, query `has_schema_privilege`, `has_table_privilege`, and `has_sequence_privilege` across every application relation and compare the result with the exact grant matrix; also confirm `pg_has_role('litblogs_runtime', 'litblogs_migrator', 'member')` is false. Save only relation names and booleans.

Finally connect as `litblogs_runtime`, run the representative read/write application smoke inside transactions that are rolled back, and run an isolated negative DDL probe:

```sql
BEGIN;
CREATE TABLE litblogs_runtime_privilege_probe (id integer);
ROLLBACK;
```

The negative probe must fail with insufficient_privilege; an exit zero is a deployment blocker even though the transaction rolls back. Verify that the probe relation does not exist. Run equivalent denied probes for `ALTER TABLE`, `TRUNCATE`, sequence ownership, and `INSERT`/`UPDATE`/`DELETE`/`TRUNCATE` against `alembic_version`; each ledger mutation must fail while `SELECT` succeeds. Then rerun the normal student/teacher journeys. Never weaken the grants merely to make a probe pass.

When Alembic exits, remove the migration-only credential from the wrapper's protected temporary scope and verify that it is absent from the operator environment and `/etc/litblogs/litblogs.env`. Replace it with the least-privilege runtime DATABASE_URL in the root-managed runtime secret profile; the runtime role has data access required by the app but cannot change schema. With that runtime profile, run the default postflight from the release's `litblogs` directory:

```text
/opt/litblogs/releases/litblogs-<12-character-commit-prefix>/.venv/bin/python -m deployment_check
```

It must confirm the reviewed Alembic head before any service start. Start a loopback-only candidate under the same runtime profile and pass readiness plus the smoke/journey checklist. The shipped web unit uses `Type=simple`, runs the equivalent database-head postflight with `/opt/litblogs/current/.venv/bin/python -m deployment_check`, loads the explicit privacy logging configuration, disables the Uvicorn access logger, and starts `/opt/litblogs/current/.venv/bin/uvicorn`. A shared mutable virtual environment makes application rollback unsafe. Push is disabled, so run `systemctl disable --now litblogs-reminders.timer` and do not enable `litblogs-reminders.timer`; the dormant reminder unit would use `/opt/litblogs/current/.venv/bin/python -m reminder_job` only after a later approved push release.

Activate only after the go/no-go signatures:

```text
/opt/litblogs/releases/litblogs-<12-character-commit-prefix>/.venv/bin/python /opt/litblogs/releases/litblogs-<12-character-commit-prefix>/deploy/scripts/release_switch.py \
  --root /opt/litblogs activate litblogs-<12-character-commit-prefix> \
  --confirm-release litblogs-<12-character-commit-prefix> \
  --expected-commit <reviewed-main-40-character-sha>
systemctl restart litblogs-web.service
curl --fail --silent --show-error https://litblogs.school.example/api/health/ready
```

The script validates that the release is a real direct child of `releases`, its commit matches `RELEASE-MANIFEST`, and every artifact is root-owned and not group/world writable. It rejects every release-tree symlink except the narrowly reviewed virtual-environment Python/lib64 links, whose final Python executable must be the root-owned immutable Python 3.13 running the switch. It serializes activation/rollback with a protected advisory lock, updates pointers atomically, fsyncs the pointer directory, and records the former current release as `previous`. It refuses to overwrite a real file or directory and fails closed when `previous` exists without `current`; clearing or reconstructing an orphan pointer requires a separate reviewed recovery operation.

## Rollback

Application rollback is allowed only when the previous binary remains compatible with the current schema. Favor additive, expand/contract migrations. Never improvise an Alembic downgrade after traffic has written new data. If schema rollback is unavoidable, stop all writers and use a separately reviewed reversible migration or restore the coupled database/upload recovery set.

The application rollback operation is `release_switch.py rollback`; it requires exact confirmation of the validated `previous` pointer. Rollback is intentionally one-way and idempotent: it moves `current` to that last-known release and does not swap `current` and `previous` or make the failed release a toggle target. Repeating the same confirmed rollback is harmless. Any later roll-forward requires a fresh `activate` with the reviewed full commit supplied as `--expected-commit`, all admission checks repeated, and a new go/no-go decision.

For a compatible application rollback:

```text
/opt/litblogs/previous/.venv/bin/python /opt/litblogs/previous/deploy/scripts/release_switch.py \
  --root /opt/litblogs rollback \
  --confirm-release litblogs-<previous-12-character-commit-prefix>
systemctl restart litblogs-web.service
curl --fail --silent --show-error https://litblogs.school.example/api/health/ready
```

Keep the failed release and evidence immutable until incident/change review is complete. Do not silently re-activate it.

After every activation or rollback, request `/index.html` and a client-side fallback route and require `Cache-Control: no-cache, no-store, must-revalidate`. Only sealed, content-hashed `/assets/` responses may carry the one-year `immutable` policy. Nginx add_header inheritance is all-or-nothing, so every location that adds `Cache-Control` must repeat the complete reviewed HSTS, CSP, frame, content-type, referrer, permissions, opener, and resource-policy set. Inspect `nginx -T` and probe `/index.html`, a fallback route, and a hashed asset for both their intended cache policy and every security header. Abort if any header is absent, or if the HTML entry point, a fallback response, or any unhashed file can be retained across a release switch.

## Monitoring and normal operations

- Alert on readiness failure, migration-head mismatch, authentication error spikes, authorization denials, upload quarantine/failure, storage/quota pressure, PostgreSQL saturation, reminder-job failure, certificate expiry, backup/WAL lag, and centralized-log delivery failure.
- Log request IDs, actor IDs where necessary, action, authorization outcome, and coarse resource type. Do not log passwords, tokens, cookie values, class access codes, post content, teacher notes, upload contents, OAuth assertions, reset links, or credential-bearing URLs.
- Review privileged access and database roles every term and within one business day of staff departure. Application runtime, migration, backup, and restore roles must be separate.
- Apply operating system, PostgreSQL, Nginx, Python, and dependency security updates through the same reviewed release process.

### Logging privacy gate

Keep the reviewed Nginx **access** format that intentionally omits raw paths, path identifiers, query strings, and referrers. Application logs may identify handlers only by normalized route templates, never by raw paths containing identifiers. The explicit `deploy/logging.json` enables those safe request events and protected exception events in the journal; the Uvicorn access logger is disabled with `--no-access-log`. Every server block sets the Nginx error log to `crit`, so ordinary 4xx and upstream warnings are not written by this server error log. Critical Nginx error logs are not guaranteed to be structurally redacted: treat them as sensitive, tightly restrict access, encrypt them, and apply the shortest school-approved retention. Never log request bodies, upload filenames, tokens, cookie values, reset links, email addresses, teacher notes, student content, upload content, OAuth assertions, or credential-bearing URLs on either success or error paths.

Treat IP addresses, user agents, actor IDs, and request IDs as personal or security-sensitive records. Forward logs over encrypted transport into encrypted storage, restrict SIEM access to named least-privilege school roles, alert on unauthorized access, and review access every term. The privacy officer and records owner must approve a purpose-specific retention period, routine deletion, incident preservation, and legal hold release; a legal hold suspends deletion only for the identified evidence.

Before each release, send unique synthetic redaction sentinels as a path identifier, upload filename, query value, referrer, email address, token, request body, and content field across successful and failing requests. Search Nginx access logs, application logs, the journal, and SIEM views and abort if any sentinel appears. Exercise a critical Nginx failure separately and handle any sentinel under the restricted critical-log incident procedure; do not claim arbitrary Nginx error text is redacted. Also test request-ID correlation across proxy and application logs, redaction of error events, centralized log-delivery-failure alerting, and unauthorized-SIEM-access alerting. Preserve only the setting names, test timestamps, request IDs, and pass/fail result, not the test values.

## Incident response and secret rotation checklist

1. Declare an incident, assign an incident commander and scribe, preserve timestamps/evidence, and move coordination away from a suspected channel.
2. Disable public ingress or switch to a static maintenance response. Stop reminder and web writers if data integrity is uncertain.
3. Restrict affected database, upload, backup, host, GitHub, identity-provider, email, and monitoring access. Preserve logs and snapshots; do not run cleanup commands before evidence capture.
4. Rotate historically exposed and incident-relevant database passwords, `SECRET_KEY`, Google/Microsoft OAuth credentials, email credentials, VAPID keys, access/admin/teacher codes, TLS private keys, backup credentials/keys, GitHub credentials, and service-account tokens. Never reuse old values.
5. Invalidate sessions and reset outstanding password-reset tokens. Revoke provider grants when indicated. Validate that old credentials fail from an independent host.
6. Determine affected students, teachers, classes, posts, comments, uploads, notes, identity bindings, backups, and time window. Use least-privilege forensic copies.
7. The privacy officer and counsel determine legally required school, guardian, regulator, insurer, and law-enforcement notifications. Record decisions and deadlines; this runbook is not legal advice.
8. Recover from a known-good coupled recovery set, run migrations/readiness/integrity/journeys, and obtain two-person approval before restoring traffic.
9. Monitor closely, complete a blameless post-incident review, and track every control gap to an owner and due date.

## School IT responsibilities

School IT, not the application repository, must supply and operate:

- DNS, trusted TLS certificates, HSTS readiness, host/network firewalls, loopback-only application binding, hardened Nginx, time synchronization, OS patching, endpoint protection, malware scanning, and capacity controls.
- An encrypted secrets store or root-owned environment files, documented two-person break-glass access, rotation evidence, and separation of application/migration/backup/restore database roles.
- PostgreSQL TLS verification, least-privilege grants, WAL/PITR, encrypted primary and off-site backups, alerting, quarterly restore drills, and measured RPO/RTO.
- Encrypted upload storage, coupled snapshots, quota/retention enforcement, legal-hold workflow, deletion evidence, and isolation of restored student data.
- Central immutable audit logs, privacy-preserving monitoring, on-call coverage, incident communications, and periodic access review.
- Protected GitHub environment approval, checksum/provenance/SBOM verification, release custody, maintenance-window authorization, rollback decision, and signed go/no-go records.

No one person should be able to author, approve, release, and deploy the same change.
