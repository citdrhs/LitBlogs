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

The PostgreSQL URL must include an explicit username and unique non-placeholder managed password of at least 16 UTF-8 bytes, contain exactly `sslmode=verify-full` and `sslrootcert=/etc/litblogs/postgres-root-ca.pem`, use one canonical DNS name or IP address, and contain no service, options, multi-host, or alternate-target override. Percent-encode every password character reserved by URL syntax before rendering the URL. Passwordless URLs, empty passwords, trust authentication, `.pgpass` fallback, and ambiguous peer/certificate-only authentication are deployment blockers; this release supports no alternate database authentication mechanism. The DBA must inspect the effective ordered `pg_hba.conf` and record that the actual matching rule for every runtime, migration, backup, and restore connection is a narrowly scoped `hostssl` rule using `scram-sha-256`, with no earlier broader `trust`, `md5`, peer, or certificate-only match. Record only a boolean that each login role's stored verifier is SCRAM, never the verifier. Against the exact hostname, port, database, role, `sslmode`, and CA path used in service, run a wrong-password probe and a rotated-old password probe; both must fail, while the managed current password must succeed. Keep all three probe credentials in the managed secret wrapper or protected file descriptor and out of arguments, shell history, tickets, and logs. Install that CA only as a real non-symlinked `root:root` mode `0644` regular file; the former group-only `0640` alternative is prohibited. Every parent directory from `/etc/litblogs` through `/` must be root-owned and not group/world writable. Prove both service identities can read the public CA rather than inferring readability from a root check:

```text
runuser -u litblogs-reset -- test -r /etc/litblogs/postgres-root-ca.pem
runuser -u litblogs -- test -r /etc/litblogs/postgres-root-ca.pem
```

`SECRET_KEY`, `ADMIN_ACCESS_CODE`, `TEACHER_INVITE_HMAC_KEY`, and `EMAIL_PASSWORD` must be independently generated, non-placeholder managed secrets. The application and invitation-HMAC secrets need at least 32 bytes, `SECRET_KEY` needs at least 12 distinct characters, and the other managed secrets need at least 16 bytes. Never put any of them in command arguments, Git, tickets, or validation logs.

`JWT_ISSUER` and `FRONTEND_URL` must be HTTPS. `CORS_ALLOWED_ORIGINS` is a comma-separated list of explicit HTTPS origins. `ALLOWED_HOSTS` and `ALLOWED_EMAIL_DOMAINS` contain exact DNS names, not wildcards, URLs, ports, or paths. Localhost and reserved documentation domains such as `.example`, `.invalid`, and `.test` fail production preflight. The session and CSRF names must be distinct valid `__Host-` cookie names; retain Secure, path `/`, and no Domain attribute. Microsoft application and tenant identifiers must be UUIDs, the allowlist must include the fixed tenant, and the Google ID must be the exact registered `.apps.googleusercontent.com` value.

The authenticated school SMTP relay requires `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USERNAME`, `EMAIL_PASSWORD`, and `EMAIL_FROM`; verify certificate-validated TLS, sender policy, rate limits, bounce handling, and a synthetic reset-message delivery before go-live. Delivery runs only through the bounded external `litblogs-password-reset.service`, never an in-process web thread. Push dispatch is deliberately disabled in this release. Production must retain `PUSH_NOTIFICATIONS_ENABLED=false`, leave `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, and `VAPID_SUBJECT` unset, and do not enable litblogs-reminders.timer. A later push implementation requires separate endpoint-validation, egress, and bounded-timeout review. Changes to `JWT_CLOCK_SKEW_SECONDS`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `OAUTH_HTTP_TIMEOUT_SECONDS`, `OAUTH_JWKS_CACHE_SECONDS`, or any `DB_*` pool/timeout setting require the same review as a code change.

The browser obtains its public CSRF-cookie name and OAuth identifiers from backend settings at runtime through `/api/runtime-config`; never put environment-specific `VITE_*` identity values in the built bundle. On the unsealed candidate, run `/opt/litblogs/releases/<release-id>/.venv/bin/python -m deployment_check --preflight` with the approved production-shaped environment. This validates Python 3.13, configuration, the release manifest/required files, and the runtime-config frontend contract; the database check is deliberately skipped so it can run before migrations. The required-file inventory includes the executed `litblogs/password_reset_delivery.py` and `litblogs/runtime_database_identity.py` modules as well as `litblogs/migrations/sqlite_contract.py`; omission of any one is an incomplete release. The check emits only an allowlisted reason code (`config_invalid`, `interpreter_invalid`, `manifest_invalid`, or `frontend_contract_invalid`) and never a setting value. Run the default database postflight only after migrations with the least-privilege runtime database role; it adds `database_unreachable` or `migration_mismatch`. Record only the code and pass/fail outcome.

## Legacy OAuth identity and Alembic adoption

`migrations/0001_create_federated_identities.sql` was a temporary bridge and is superseded by the Alembic migration chain. Do not execute it for this rollout. Never run both the raw SQL identity script and the Alembic identity revision.

Every production or rehearsal Alembic CLI command below runs inside the approved migration wrapper with only `LITBLOGS_MIGRATION_DATABASE_URL` exposed. That URL names the migration role and contains the same strict `sslmode`/`sslrootcert` contract; do not expose `DATABASE_URL` or load application, JWT, SMTP, OAuth, teacher-code, or other runtime secrets into the migration process. A programmatic verifier may instead provide an already validated SQLAlchemy connection and no environment credential.

Before touching production, inventory whether the raw script was ever run. If its table or constraints already exist outside the Alembic ledger, abort the automated rollout. A DBA must compare the live definition and data with the reviewed revision, preserve any subject bindings, and approve a dedicated reconciliation path. Do not guess, delete the table, stamp past unverified work, or retry the identity revision blindly.

This section classifies adoption state only; it is not a runnable migration path. An empty database proceeds without a baseline stamp. For a verified pre-Alembic LitBlogs schema, a DBA first compares every table, column, constraint, index, and enum with baseline revision `985a04df032a`. `stamp` records history; it does not change or validate schema. Record the signed adoption decision, then continue to the single migration ceremony under **Versioned release activation**. Before any `stamp` or `upgrade`, that ceremony requires the legacy recovery checkpoint where applicable, stopped writers, all five exact roles, exact schema/object ownership, the bounded identity-owner membership, and the migration-only wrapper. Do not execute Alembic from this earlier section; the final ACL revision can skip missing role prerequisites and a successful command would not make that state safe.

The safe order for legacy OAuth is:

1. Before migration, export an inventory of active OAuth-only accounts and obtain immutable Google or Microsoft provider, issuer, and subject evidence from the identity provider or a supervised recovery ceremony. Do not treat matching email addresses as identity proof.
2. Abort if a trusted subject cannot be established for any account that must remain active. Put that account through school-approved recovery instead of implicit linking.
3. Rehearse baseline adoption and `alembic upgrade head` on the disposable restored database.
4. In the production maintenance window, follow the initial legacy cutover gate below. Take the storage-native pre-migration checkpoint while every writer is stopped, complete the reviewed migration and upload-registry import, and only then create the first current-head coupled recovery set.
5. Populate the new identity bindings from the approved evidence while the application is still offline. Verify uniqueness, provider, issuer, subject, and intended user for every row with a second operator.
6. Rotate authentication secrets and invalidate pre-cutover sessions. Enable the application only after identity counts and supervised sample logins agree with the signed inventory.

## Initial legacy database/upload cutover gate

The initial legacy rollout is blocked until two separately reviewable recovery points exist. Before the first Alembic chain, upload_assets does not exist and legacy files may not yet have canonical registry bindings. Therefore **do not run backup_postgres.py** against that legacy deployment: the normal tool intentionally fails closed instead of inventing an incomplete registry.

1. Stop public traffic, the web service, every maintenance timer/service, administrative upload/import tools, and any other database or upload writer. Prove there are no active writes.
2. While writes remain quiesced, create one storage-native pre-migration checkpoint. Bind a recoverable PostgreSQL volume snapshot or custom dump and a complete byte-for-byte snapshot of the legacy upload filesystem to one immutable checkpoint ID. Record canonical source roots, sizes, SHA-256 checksums, encryption/key custody, operators, timestamps, and a restore rehearsal. If the storage platform cannot take an atomic multi-volume snapshot, keep all writers stopped through both captures and document their exact order. This is the reviewed legacy recovery path; it is not a manifest synthesized by the current-head tool.
3. Run the separately reviewed offline legacy upload inventory and import. Apply the reviewed migration chain, inventory every legacy reference/file, bind it to a canonical `upload_assets` row, copy it into the private canonical tree, and reconcile registry versus filesystem while traffic remains off. Abort on any ambiguous owner, missing/orphan file, duplicate binding, noncanonical path, size/hash mismatch, or custody failure. Do not guess or silently discard an object.
4. After the database is at `f1ad78b2035f`, every legacy row/file is reconciled, and the registry readiness claims are true, create and restore-rehearse the first current-head coupled recovery set using the normal procedures below.
5. Set `UPLOAD_REGISTRY_SCHEMA_READY=true`, `UPLOAD_LEGACY_IMPORT_COMPLETE=true`, and `UPLOAD_BACKUP_RESTORE_VERIFIED=true` only from the signed evidence. Run production preflight and postflight before enabling any service.

The initial legacy rollout is blocked if either the storage-native pre-migration checkpoint or the first current-head coupled recovery set is absent, incomplete, unrehearsed, or cannot meet the approved RPO/RTO.

## Backup procedure

Provision `litblogs_backup` as the dedicated least-privilege backup database role: `LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS`, with a unique managed backup-only credential. Its sole membership is the built-in `pg_read_all_data` role, and its complete recursive membership closure is exactly that one direct, non-admin, inheritable/settable edge; `pg_read_all_data` itself must have no parent role. It has no application-role membership and no direct application-object ACL. Neither the backup role nor any role in its recursive membership closure may own a database, schema, relation, routine, or type; ownership would confer effective alter/drop authority even without an explicit ACL. That inherited read role makes `pg_dump` and the `public.upload_assets` registry query feasible without adding a grantee to the application archive. `pg_dump` preserves database object owners and ACL entries; its archive does not contain global role definitions or the backup role.

The backup login may connect only to the production LitBlogs database. Revoke default `PUBLIC CONNECT, TEMPORARY` from every other database, including non-connectable and connectable maintenance/template databases. On the production database, revoke `PUBLIC CONNECT, TEMPORARY`, then grant only `CONNECT` to `litblogs_runtime`, `litblogs_migrator`, `litblog_account_operator`, `litblog_invitation_operator`, and `litblogs_backup` (with the database owner's implicit rights reviewed separately). The backup role receives no `TEMPORARY` or `CREATE` privilege on any database and no direct object ACL or ownership. Require a database-specific `hostssl` SCRAM rule for `litblogs_backup` in `pg_hba.conf`, with no earlier broader rule. Before accepting the role, query every `pg_database` row with `has_database_privilege('litblogs_backup', datname, 'CONNECT')` and the equivalent `CREATE` and `TEMPORARY` calls: exactly the production database must return true for `CONNECT`, and every database must return false for `CREATE` and `TEMPORARY`. A real connection to the production database must succeed and attempts to every other connectable database must fail. Also verify the exact role attributes and that `pg_auth_members` contains only membership in `pg_read_all_data`; any additional membership, cross-database connection, direct application ACL, or role-admin capability is a deployment blocker.

The operator environment supplies `DATABASE_URL`; never paste a credential-bearing URL into a command argument, ticket, shell history, or log. The URL must use `sslmode=verify-full` so database authentication and backup data use encrypted transport with hostname and CA verification. Before reading the registry or invoking `pg_dump`, `backup_postgres.py` independently requires `session_user = current_user = litblogs_backup`, the exact non-admin attributes and recursive `pg_read_all_data` membership closure, the exact database privilege surface, no direct application ACL, no database/schema/relation/routine/type ownership anywhere in the effective role closure, and no reverse membership. Effective catalog probes deny schema `CREATE`; table or column `INSERT`, `UPDATE`, `DELETE`, `TRUNCATE`, `REFERENCES`, and `TRIGGER`; sequence `USAGE`/`UPDATE`; and non-system routine `EXECUTE`, including privilege inherited through `pg_read_all_data` or `PUBLIC`. A runtime, migrator, restore-DBA, transitively overprivileged read role, or other overprivileged backup URL fails closed.

The four output files have owner-only permissions but are not encrypted containers. Fail unless the output directory and every replica are encrypted at rest with school-controlled keys. Run this procedure only through a reviewed root-controlled backup wrapper. The canonical upload objects are `litblogs:litblogs` mode `0600` beneath the mode-`0750` root, so an unrelated non-root backup account cannot read them; the root-controlled wrapper is the approved bounded OS identity and must prove it can read every exact object without chmod, supplemental ACLs, group-read widening, or ownership changes. It owns the canonical output/staging directory at exact mode `0700`, receives the `litblogs_backup` database credential only inside its protected invocation, and removes that credential from its environment immediately afterward. The backup mount and every replica remain root-owned/mounted so the web `litblogs` service cannot read or write the backup mount; verify both denied read and denied write through the effective web unit sandbox and filesystem/mount controls. Do not add the backup mount to the web unit's writable or readable paths.

The absolute output directory must already exist, be canonical and non-symlinked, be owned by that root-controlled operator at exact mode `0700`, and have no replaceable ancestor. Every parent directory is verified; a non-sticky group/world-writable parent is a deployment blocker. The upload root is the existing local `/var/lib/litblogs/uploads`; this release does not invent an object-store backend. It must be the reviewed `litblogs:litblogs` root at exact mode `0750`, while every ancestor through `/` is root-owned and not group/world writable; a `litblogs`-owned `/var/lib/litblogs` parent is a deployment blocker because the service could rename the validated root. Its immediate entries must be exactly `objects` and `.incoming`. Stop public traffic and every web, maintenance, administrative import, database, and upload writer, then prove them inactive before making the explicit confirmation below.

```text
umask 077
/opt/litblogs/releases/<release-id>/.venv/bin/python \
  /opt/litblogs/releases/<release-id>/deploy/scripts/backup_postgres.py \
  --output-dir /srv/litblogs-backups/daily \
  --upload-root /var/lib/litblogs/uploads \
  --confirm-writes-quiesced
```

Use only the approved release-local Python above. Before any secret-bearing PostgreSQL call, the operator entry point requires the canonical `/usr/lib/postgresql/17/bin` directory and its ancestor chain to contain no symlink, requires that client directory, every parent directory through `/`, and each executable to be root-owned and not group/world writable, and checks every client's reported PostgreSQL 17 major version. The immutable directory custody prevents a validated executable pathname from being swapped before a credential-bearing call. Commands never resolve through the inherited PATH; the child environment replaces it with `/usr/bin:/bin` and strips libpq target overrides. Abort if the site package layout differs until school IT reviews and updates the pinned code—do not add a PATH lookup or environment override.

Inventory A and inventory B include every `upload_assets` row, including `DELETED` tombstones, and must match exactly. The deterministic uncompressed USTAR contains only file-backed `PENDING`, `ACTIVE`, and `DELETE_PENDING` objects. The script rejects missing, extra, linked, noncanonical, wrongly sized, hash-mismatched, or incorrectly owned files and requires an empty `.incoming` directory.

One accepted recovery set has exactly four owner-only files: the PostgreSQL custom dump, deterministic `.uploads.tar`, sorted `.assets.jsonl`, and top-level `.manifest.json`. The inventory records canonical storage key, state, size, SHA-256, and stable asset ID. The script fsyncs the database, upload archive, inventory, and output directory, publishes those three artifacts without overwrite, then durably publishes the manifest last. Only that final manifest declares an accepted set. Replicate all four files together over encrypted transport, verify the manifest-bound hashes after transfer, and never mix artifacts from different manifests. Enable immutable access logging for backup reads, writes, copies, restore access, retention changes, legal holds, and deletion approvals.

A crash or validation failure deliberately retains private `.*.partial` files or unmanifested artifacts for investigation. Replication and restore tooling must ignore them. Quarantine exact paths, correlate audit/legal-hold records, and delete only after peer approval; never promote a partial, synthesize a manifest, or silently clean up evidence. Run a fresh backup and accept only its newly reported four-file set.

The database administrator must additionally monitor WAL archival lag against the 15-minute RPO. Alert if a scheduled backup, complete four-file replication, or WAL segment fails. A successful process exit without an off-site copy is not a successful backup.

## Restore verification procedure

Run verification only on an isolated host/cluster with no route or credentials to production, students, teachers, or the internet. The restore credential is a temporary privileged DBA **only on that disposable cluster**, because applying preserved owners and ACLs requires it. Before restore, a role administrator pre-provisions exact-name stand-ins for `litblogs_migrator`, `litblogs_runtime`, `litblog_identity_owner`, `litblog_account_operator`, and `litblog_invitation_operator`; all five rehearsal roles are `NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS` with no memberships. They are intentionally different from the managed production login roles. Never promote or change an isolated stand-in before either exact verifier. After the final verifier, the only documented one-way synthetic runtime transition is the bounded `litblogs_runtime` LOGIN/CONNECT ceremony below; every other stand-in remains `NOLOGIN`. Never grant the restore DBA application ACLs, reuse the isolated environment for production recovery, or reuse a synthetic credential in production.

For an actual production recovery, a privileged production DBA first reconciles the migrator and four application roles to the exact production attributes in the migration section, using managed credentials only for roles that must log in, and then applies the preserved archive while all application access remains disabled. Every restored application schema, table, type, and sequence must be owned by `litblogs_migrator`; exactly the three reviewed `SECURITY DEFINER` routines must be owned by `litblog_identity_owner`. No legacy/source owner or restore-DBA grantee may remain. Production traffic is blocked until the same catalog-wide ownership/grant probes pass exactly. The restore script never drops a database, including on failure.

Copy all four manifest-bound files into one canonical owner-only staging directory at mode `0700`; every file must be owned by the restore operator at mode `0600`, and no ancestor may be replaceable. Create a new empty private synthetic upload root named `litblog_restore_uploads_*`, owned by the effective restore operator at exact mode `0700`; its full ancestor chain must have trusted owners and no non-sticky group/world-writable component. Choose a new lowercase synthetic database name and repeat it as confirmation:

```text
  /opt/litblogs/releases/<release-id>/.venv/bin/python \
  /opt/litblogs/releases/<release-id>/deploy/scripts/restore_verify_postgres.py \
  --manifest /srv/litblogs-restore/staging/<set>.manifest.json \
  --upload-target /srv/litblogs-restore/litblog_restore_uploads_20260822_a1 \
  --target-database litblog_restore_verify_20260822_a1 \
  --confirm-target litblog_restore_verify_20260822_a1
```

The script verifies custody and all manifest-bound sizes/hashes before database contact and again before restore. `pg_restore` intentionally preserves trusted owner and ACL entries; neither backup nor restore uses `--no-owner` or `--no-acl`. It restores the database in one transaction, extracts only regular canonical USTAR members into the empty synthetic root, and then requires the exact current Alembic head, schema/data integrity, every registry row including tombstones, every file-backed object, and each ACTIVE file hash. Its catalog-wide `f1ad78b2035f` probe compares exact schema/table/column/sequence/function ACLs, rejects `PUBLIC` or unexpected grantees/grant options, requires no application-role memberships, and verifies the three `SECURITY DEFINER` routine owners and fixed `search_path`. At verifier startup it strictly extracts the three byte-exact `prosrc` bodies from the reviewed c513 creating migration and compares each restored body plus exact language, return type, volatility, parallel safety, strict/leakproof flags, function kind, argument-default count, owner, security-definer flag, and configuration; missing, extra, duplicate, altered, or ambiguously parsed routines fail. It also requires `public` to be the only non-system schema, the exact global default-function ACL to contain only the migrator owner's `EXECUTE` entry, no schema-scoped default-function ACL, and no non-owner target-database `CONNECT` or `TEMPORARY` ACL. An Alembic ledger match alone is never sufficient.

Any malformed set, old/pre-Alembic database, role prerequisite failure, owner/ACL drift, registry mismatch, unsafe archive member, or file mismatch fails closed before application access. The database, restored files, and private partials remain for investigation; deletion is a separate DBA change with an exact target, peer review, and legal-hold check.

The normal coupled restore CLI never accepts a `pre_alembic` recovery point. Rehearsal of the separately reviewed legacy checkpoint uses an isolated storage-native recovery workflow, followed by the baseline comparison, stamp, migration, offline upload inventory/import, and first current-head coupled backup described above. Do not weaken the current-head registry or ACL checks to make a legacy snapshot appear coupled.

Populate federated identities only from the signed provider/issuer/subject inventory while the disposable application remains offline. A second operator compares every binding to that inventory and records its approved total; an aggregate count is not a substitute for the row-by-row identity review.

Run the read-only second verifier against the same manifest, database, and upload root. It performs no create, restore, extraction, or drop and repeats current-head, exact registry/file, and ownership/ACL checks without printing identities or counts:

```text
/opt/litblogs/releases/<release-id>/.venv/bin/python \
  /opt/litblogs/releases/<release-id>/deploy/scripts/restore_verify_postgres.py \
  --verify-existing \
  --manifest /srv/litblogs-restore/staging/<set>.manifest.json \
  --upload-target /srv/litblogs-restore/litblog_restore_uploads_20260822_a1 \
  --target-database litblog_restore_verify_20260822_a1 \
  --confirm-target litblog_restore_verify_20260822_a1 \
  --expected-federated-identities <approved-inventory-count>
```

Abort unless this second verifier reports `current_head`. That result is the final exact recovery-verifier evidence: at this point `litblogs_runtime` is still `NOLOGIN` and the synthetic target still has no non-owner `CONNECT` grant. Preserve the report before the following one-way test transition. On this disposable isolated cluster only, generate a new managed synthetic runtime password inside the approved secret-execution wrapper. Never print it, place it in a command argument or shell history, or reuse it outside this rehearsal. Through a parameter-bound DBA operation inside that wrapper, make only this change:

```sql
ALTER ROLE litblogs_runtime LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
GRANT CONNECT ON DATABASE litblog_restore_verify_<synthetic-suffix> TO litblogs_runtime;
```

Set the password in the same protected operation without interpolating it into the SQL shown above. Prove only a boolean that PostgreSQL stored a SCRAM verifier. Through the exact synthetic target hostname, port, database, TLS mode, CA, and `litblogs_runtime` role, require the managed password to authenticate and a separately generated wrong password to fail. Recheck that runtime retains no memberships, target `CREATE`/`TEMPORARY` and schema `CREATE` remain denied, the target database's sole new non-owner ACL is runtime `CONNECT`, all other application roles remain `NOLOGIN` with their exact non-admin attributes, and every membership direction remains empty.

Never use the restore DBA for application checks. Point the non-production application instance at the disposable database and restored upload root using only that synthetic runtime credential. Run the default release postflight, which invokes `database.check_database_readiness` and proves the exact runtime identity/head/schema boundary, before readiness, login, legacy OAuth recovery, upload, student, and teacher journeys. Record the manifest, restored revision, exact registry result, ownership/ACL result, operators, failures, and measured RPO/RTO. The LOGIN and CONNECT transition intentionally changes the isolated-verifier invariants: after it, operators must not rerun or claim the exact restore verifier unless they first return the five stand-ins and database ACL to the exact pre-transition state and obtain a new second-verifier result; never carry the synthetic credential to production. Revoke and destroy it only as part of destroying the entire isolated environment; destroy the disposable cluster after the evidence is retained. Never copy restored student data to developer laptops or third-party services.

## Backup retention and legal hold

Unless the school records a stricter approved schedule, retain 35 daily recovery artifacts, 12 month-end artifacts, and the point-in-time recovery stream necessary to meet the RPO. Encryption keys must be stored separately from backup media, escrowed to two authorized school officers, rotated on schedule, and tested.

The privacy officer and records owner approve retention, deletion, litigation hold, and student-record obligations. A legal hold suspends normal expiry for exactly identified artifacts; it does not justify retaining every backup indefinitely. Keep an immutable audit trail of hold placement, access, release, and final destruction. A two-person review is required before backup destruction, and automated retention deletion must fail closed when hold state cannot be read.

Perform a quarterly restore drill using a randomly selected off-site artifact and the synthetic restore procedure. At least annually, include loss of the primary database host, upload store, and one key custodian. Track corrective actions to closure.

## Upload store coupling

Uploads live outside the source tree at `/var/lib/litblogs/uploads`; they contain private student content and are not public static files. Use only the manifest-last coupled procedure above after registry cutover. Restore database and files together, keep both isolated, and fail on any exact inventory or ACTIVE-object mismatch. Retention and legal-hold decisions operate on complete recovery sets, never on one artifact in isolation.

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

Stop public traffic and all writers. Disable scheduling first, wait for any active one-shot to stop, and verify all three services are inactive before migration:

```text
systemctl stop litblogs-password-reset.timer litblogs-upload-reconciliation.timer
systemctl stop litblogs-password-reset.service litblogs-upload-reconciliation.service litblogs-web.service
```

Before migration, a role administrator must create or reconcile the migrator and four fixed application roles. Create an absent role under a separately reviewed DBA change, then enforce the attributes below. Supply passwords or certificate mappings for the four direct `LOGIN` roles through the managed secret workflow; never put a password in this SQL, a command argument, or deployment evidence.

```sql
ALTER ROLE litblogs_migrator WITH LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
ALTER ROLE litblogs_runtime WITH LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
ALTER ROLE litblog_identity_owner WITH NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
ALTER ROLE litblog_account_operator WITH LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
ALTER ROLE litblog_invitation_operator WITH LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
```

Outside the one-command ownership-transfer exception below, the five roles must have no memberships and no role may inherit another role. The migrator's managed credential is migration-only and is never used as the web/runtime login. The account and invitation operators are direct logins because `SET ROLE` is deliberately unavailable; their separate managed credentials must not be shared with the web service. Have a second operator inspect `pg_roles` for the exact `LOGIN`/`NOLOGIN`, `NOINHERIT`, `NOSUPERUSER`, `NOCREATEDB`, `NOCREATEROLE`, `NOREPLICATION`, and `NOBYPASSRLS` values and inspect both directions of `pg_auth_members`. Abort on a missing fixed role or any unexpected membership. The final ACL migration conditionally configures roles that exist; a successful Alembic exit cannot compensate for a missing prerequisite.

The database owner must also transfer the `public` schema and every enumerated LitBlogs table, sequence, and enum/type from the signed inventory to `litblogs_migrator`; do not use a blanket `REASSIGN OWNED` that could capture unrelated objects. Verify that `litblogs_migrator` owns that exact inventory and no unrelated object. The owner then runs the following before relinquishing the session:

```sql
ALTER SCHEMA public OWNER TO litblogs_migrator;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
```

The DBA's approved secret-execution wrapper must supply only `LITBLOGS_MIGRATION_DATABASE_URL` to the release-local Alembic process. The migrator is a direct `LOGIN` role solely so that wrapper can connect; it is never an application login. It owns/alters only the application schema and has no role-management, replication, database-creation, or server-file privilege. Never expose this URL as `DATABASE_URL`, place it in an argument, store it in `/etc/litblogs/litblogs.env`, or load any application secrets.

For the signed pre-Alembic adoption case only, run the baseline stamp now, inside this same guarded wrapper and after all prerequisites above. Empty databases and databases already carrying the Alembic ledger skip this command:

```text
cd /opt/litblogs/releases/litblogs-<12-character-commit-prefix>/litblogs
/opt/litblogs/releases/litblogs-<12-character-commit-prefix>/.venv/bin/python -m alembic -c /opt/litblogs/releases/litblogs-<12-character-commit-prefix>/litblogs/alembic.ini stamp 985a04df032a
```

The final migration must transfer ownership of exactly three `SECURITY DEFINER` routines to `litblog_identity_owner`. After the optional stamp is complete and immediately before the upgrade, the role administrator grants the migrator the one temporary direct membership required for that ownership handoff. Its PostgreSQL 17 options must be exactly `ADMIN FALSE`, `INHERIT TRUE`, and `SET TRUE`; an edge with default options, a pre-existing/unreviewed edge, or any otherwise different edge is not acceptable:

```sql
GRANT litblog_identity_owner TO litblogs_migrator WITH ADMIN FALSE, INHERIT TRUE, SET TRUE;
```

Do not grant `litblogs_migrator` membership in either operator role or the runtime role; its sole bounded exception is the identity-owner membership immediately around this one upgrade. Then run the one authorized upgrade path using the explicit release cwd and config:

```text
cd /opt/litblogs/releases/litblogs-<12-character-commit-prefix>/litblogs
/opt/litblogs/releases/litblogs-<12-character-commit-prefix>/.venv/bin/python -m alembic -c /opt/litblogs/releases/litblogs-<12-character-commit-prefix>/litblogs/alembic.ini upgrade head
```

Whether the upgrade succeeds or fails, the role administrator must immediately run the following from a separate protected session before any drift check, application connection, retry, or maintenance-window exit:

```sql
REVOKE litblog_identity_owner FROM litblogs_migrator;
```

Prove through `pg_auth_members` that the membership is absent. If the upgrade failed, keep all application writers stopped and investigate; do not leave the membership in place for convenience. If it succeeded, require the release-local read-only drift checks before removing the migration credential:

```text
/opt/litblogs/releases/litblogs-<12-character-commit-prefix>/.venv/bin/python -m alembic -c /opt/litblogs/releases/litblogs-<12-character-commit-prefix>/litblogs/alembic.ini current --check-heads
/opt/litblogs/releases/litblogs-<12-character-commit-prefix>/.venv/bin/python -m alembic -c /opt/litblogs/releases/litblogs-<12-character-commit-prefix>/litblogs/alembic.ini check
```

Abort on any `alembic check` drift even when the ledger says current head. Revision `f1ad78b2035f` is the sole authority for application ACLs. Post-migration blanket table, sequence, and default-privilege grants are prohibited. Do not run `ALTER DEFAULT PRIVILEGES` or manual grant repairs: a mismatch means the release is rejected and the migration or prerequisite must be corrected under review.

Have a second operator compare the complete PostgreSQL catalogs with this exact matrix. `litblogs_runtime` receives schema `USAGE` and no schema `CREATE`:

| Object set | Exact runtime privileges |
| --- | --- |
| Runtime CRUD tables: `assignment_drafts`, `assignment_reminder_notifications`, `assignment_submission_replies`, `assignment_submissions`, `assignments`, `blogs`, `browser_sessions`, `class_enrollments`, `classes`, `comment_likes`, `comments`, `federated_identities`, `password_resets`, `post_likes`, `push_subscriptions`, `saved_posts`, `teachers`, `upload_assets`, `user_settings`, `users` | `SELECT`, `INSERT`, `UPDATE`, `DELETE` |
| `teacher_invitations` | `SELECT (id, token_digest, email_digest, expires_at, consumed_at, revoked_at)`, `UPDATE (consumed_at, revoked_at)` |
| `operator_audit_events` | `INSERT (actor_identifier, action, outcome, resource_digest)` |
| `alembic_version` | `SELECT` |
| Sequences named `<table>_id_seq` for every runtime CRUD table above, plus `operator_audit_events_id_seq` (not `teacher_invitations_id_seq`) | `USAGE`, `SELECT` |

`litblog_identity_owner` receives schema `USAGE`, no schema `CREATE`, no broad table access, and only the following routine-body privileges:

| Relation | Exact identity-owner privileges |
| --- | --- |
| `users` | `SELECT (id, email)`, `UPDATE (disabled_at)` |
| `browser_sessions` | `SELECT (user_id, revoked_at, expires_at)`, `UPDATE (revoked_at)` |
| `password_resets` | `SELECT (user_id)`, `UPDATE (token, expires_at, used, delivery_status, delivery_attempted_at, delivery_claim_digest)` |
| `teacher_invitations` | `SELECT (email_digest, consumed_at, revoked_at, expires_at)`, `INSERT (token_digest, email_digest, expires_at, created_by)`, `UPDATE (revoked_at)` |
| `operator_audit_events` | `INSERT (actor_identifier, action, outcome, resource_digest)` |
| `teacher_invitations_id_seq`, `operator_audit_events_id_seq` | `USAGE` |

It owns only `operator_set_account_status(VARCHAR, BOOLEAN, VARCHAR, VARCHAR)`, `operator_create_teacher_invitation(VARCHAR, VARCHAR, TIMESTAMPTZ, VARCHAR, VARCHAR)`, and `operator_revoke_teacher_invitation(VARCHAR, VARCHAR, VARCHAR)`. Confirm each is `SECURITY DEFINER`, has the reviewed safe `search_path`, and has no unexpected owner or grant.

`litblog_account_operator` and `litblog_invitation_operator` each receive schema `USAGE`, no schema `CREATE`, no table or sequence privilege, and no ownership. The account operator receives `EXECUTE` only on `operator_set_account_status`; the invitation operator receives `EXECUTE` only on the create/revoke invitation routines. Neither operator, `litblogs_runtime`, nor `PUBLIC` may execute another privileged routine. `PUBLIC` must have no schema, table, sequence, or function ACL, including default function execution.

Run catalog-wide checks, not a few positive samples. Use `has_schema_privilege`, `has_table_privilege`, `has_column_privilege`, `has_sequence_privilege`, and `has_function_privilege` for every matrix cell and every privilege outside it; use `pg_catalog.aclexplode` to prove there is no unexpected grantee or `PUBLIC` entry. Inspect `pg_proc` for the three exact signatures, owner, `prosecdef`, and configured `search_path`. Inspect both directions of `pg_auth_members` and require no memberships after the temporary migrator grant is revoked. Save only role/object names and booleans, never rows of student or credential data.

Do not grant schema `CREATE`, table ownership, `TRUNCATE`, `REFERENCES`, `TRIGGER`, database creation, role administration, replication, bypass-RLS, or server-file privileges to any application role. Any result outside the exact matrix is a deployment blocker.

Finally connect as `litblogs_runtime`, run the representative read/write application smoke inside transactions that are rolled back, and run an isolated negative DDL probe:

```sql
BEGIN;
CREATE TABLE litblogs_runtime_privilege_probe (id integer);
ROLLBACK;
```

The negative probe must fail with insufficient_privilege; an exit zero is a deployment blocker even though the transaction rolls back. Verify that the probe relation does not exist. Run equivalent denied probes for `ALTER TABLE`, `TRUNCATE`, sequence ownership, and `INSERT`/`UPDATE`/`DELETE`/`TRUNCATE` against `alembic_version`; each ledger mutation must fail while `SELECT` succeeds. Also require denied runtime probes for `INSERT`/`DELETE`, `SELECT (created_by, created_at)`, and `UPDATE (token_digest, email_digest, expires_at)` on `teacher_invitations`; `SELECT`/`UPDATE`/`DELETE`/`TRUNCATE` on `operator_audit_events`; insertion into audit `id` or `created_at`; access to `teacher_invitations_id_seq`; and all three operator routines. As each operator login, require direct table/sequence and schema-creation probes to fail, then invoke only that operator's approved routine through the protected CLI. Then rerun the normal student/teacher journeys. Never weaken the grants merely to make a probe pass.

When Alembic exits, remove the migration-only credential from the wrapper's protected temporary scope and verify that it is absent from the operator environment and `/etc/litblogs/litblogs.env`. Replace it with the least-privilege runtime DATABASE_URL in the root-managed runtime secret profile; the runtime role has data access required by the app but cannot change schema. The postflight must prove `session_user` and `current_user` are both exactly `litblogs_runtime`, the login has the exact non-admin `LOGIN NOINHERIT` attributes and no membership in either direction, `pg_catalog.current_schemas(false) = ARRAY['public']`, `public` grants `USAGE` but no `CREATE`, and the target database grants connection but neither `CREATE` nor `TEMPORARY`. With that runtime profile, run the default postflight from the release's `litblogs` directory:

```text
/opt/litblogs/releases/litblogs-<12-character-commit-prefix>/.venv/bin/python -m deployment_check
```

It must confirm the reviewed Alembic head before any service start. Start a loopback-only candidate under the same runtime profile and pass readiness plus the smoke/journey checklist. The shipped web unit uses `Type=simple`, runs the equivalent database-head postflight with `/opt/litblogs/current/.venv/bin/python -m deployment_check`, loads the explicit privacy logging configuration, disables the Uvicorn access logger, and starts `/opt/litblogs/current/.venv/bin/uvicorn`. Password-reset delivery and upload reconciliation are external `Type=oneshot` services with `RuntimeMaxSec=300` plus the effective `TimeoutStartSec=300` one-shot bound; the web process starts no maintenance threads. A shared mutable virtual environment makes application rollback unsafe. Push is disabled, so run `systemctl disable --now litblogs-reminders.timer` and do not enable `litblogs-reminders.timer`; the dormant reminder unit would use `/opt/litblogs/current/.venv/bin/python -m reminder_job` only after a later approved push release.

### External maintenance workers

Provision `litblogs-reset` as a locked system account with `/usr/sbin/nologin`, primary group `litblogs-reset`, and no supplementary groups, especially no `litblogs` membership. Render `/etc/litblogs/password-reset.env` independently from the web environment as `root:litblogs-reset` mode `0640`. Its only permitted keys are `DATABASE_URL`, `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT_SECONDS`, `DB_POOL_RECYCLE_SECONDS`, `DB_CONNECT_TIMEOUT_SECONDS`, `DB_STATEMENT_TIMEOUT_MS`, `DB_LOCK_TIMEOUT_MS`, `FRONTEND_URL`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_SMTP_TIMEOUT_SECONDS`, `EMAIL_USERNAME`, `EMAIL_PASSWORD`, `EMAIL_FROM`, and `PASSWORD_RESET_CLAIM_TIMEOUT_SECONDS`. Do not copy signing, OAuth, administrator, upload, scanner, or other web-only values into it. Prove `litblogs` cannot read this file and that the reset identity cannot read `/etc/litblogs/litblogs.env` through either discretionary permissions or the service sandbox.

Keep `litblogs-password-reset.timer` and `litblogs-upload-reconciliation.timer` disabled while configuring egress. Each shipped service and timer refuses to start unless both its root-controlled `/etc/systemd/system/<service>.d/egress.conf` and its boot-ephemeral `/run/litblogs-maintenance-egress/<job>.port-policy-ready` marker exist; each service also has `IPAddressDeny=any`. The upload reconciliation drop-in may contain only exact resolved PostgreSQL addresses, one `IPAddressAllow=<postgres-ip>/32` or IPv6 `/128` entry per address. `IPAddressAllow` is address-only defense in depth, not destination-port enforcement and not database-only egress by itself. Install a unit/cgroup-specific host-firewall policy or isolated network namespace that permits only the exact resolved PostgreSQL addresses at the port configured in `DATABASE_URL`; reject every other address and port. No subnet, public default route, proxy, web service, SMTP relay, malware scanner, or DNS server address is allowed. The cleanup path performs no malware scanner call and receives no scanner-socket access. Use the reviewed local resolver or a root-controlled canonical mapping rather than broadening the unit's process egress.

The password-reset drop-in contains only the exact resolved PostgreSQL addresses and exact resolved SMTP addresses required by the authenticated TLS relay, again as individual `/32` or `/128` entries. Its external unit/cgroup or namespace policy permits only those PostgreSQL addresses at the configured database port and those SMTP addresses at the configured `EMAIL_PORT`. Password reset needs SMTP; it has no general-purpose Internet access. Install both `egress.conf` files as non-symlinked `root:root` files, mode `0644` or stricter, beneath root-owned non-writable ancestors. Resolve and review every address against the approved database and relay records. If either file is absent, empty, stale after address rotation, broader than a host prefix, contains another destination, or lacks exact-port enforcement, both the affected one-shot and its timer must remain disabled.

The upload-reconciliation entry module imports its reviewed one-shot function from `main`, whose fail-closed startup check validates the global private-upload configuration. Before any reconciliation smoke, create `/var/lib/litblogs/uploads/objects` and `/var/lib/litblogs/uploads/.incoming` as real non-linked `litblogs:litblogs` directories at exact mode `0700`; reject a missing, linked, differently owned, or broader-writable child. Upload reconciliation alone exposes `/var/lib/litblogs/uploads` through `ReadWritePaths`. Password reset runs as `litblogs-reset` through the dedicated `password_reset_delivery.py` module and its minimal worker settings: the verified runtime database URL plus bounded pool/timeouts, HTTPS frontend reset origin, SMTP host/port/TLS-timeout credentials and sender, and reset-claim timeout only. It does not import `main` or validate `UPLOAD_ROOT`, has neither upload `ReadWritePaths` nor upload prechecks, and invokes no upload routine. The effective reset unit must retain `InaccessiblePaths=/etc/litblogs/litblogs.env /var/lib/litblogs/uploads`. Before enabling it, run service-context read and write probes under a transient unit with the same `User`, `Group`, and `InaccessiblePaths`: reads of the web environment and reads or writes of the upload root must fail, while reads of `/etc/litblogs/password-reset.env` and the canonical PostgreSQL CA must succeed. Record only boolean results, not environment contents. Both units restrict address families to `AF_INET AF_INET6`, excluding `AF_UNIX`; scanner Unix sockets must fail the service-context negative probes.

On every boot and after any database, SMTP, address, port, unit, or firewall change, remove both `.port-policy-ready` markers before installing the rules. Run `systemctl daemon-reload`; then use `systemctl cat` and host-firewall tracing to prove the policy is bound to the exact service cgroup or isolated namespace. From each service context, positively probe only the configured PostgreSQL IP:port and, for password reset, configured SMTP IP:port. Negatively probe an alternate port on every allowed IP, every unlisted address, every malware-scanner network endpoint, and every scanner Unix socket; all must fail. Only after the full probe set passes may root create `/run/litblogs-maintenance-egress` as `root:root` and non-writable to service identities and create the matching root-owned `password-reset.port-policy-ready` or `upload-reconciliation.port-policy-ready` marker. Recreate and revalidate the marker on every boot and address or policy change; its existence never replaces the retained firewall and probe evidence. Keep both timers disabled until this gate passes and the release activation below changes `current` to the reviewed candidate and web readiness succeeds; a pre-activation service run could execute the previous release and is not valid evidence. systemd prevents overlap of the same service on one host; reset delivery uses lease-digest compare-and-swap and upload reconciliation uses database row locks, so concurrent hosts remain idempotent. Push is unrelated and remains disabled; do not enable `litblogs-reminders.timer`.

Activate only after the go/no-go signatures:

```text
/opt/litblogs/releases/litblogs-<12-character-commit-prefix>/.venv/bin/python /opt/litblogs/releases/litblogs-<12-character-commit-prefix>/deploy/scripts/release_switch.py \
  --root /opt/litblogs activate litblogs-<12-character-commit-prefix> \
  --confirm-release litblogs-<12-character-commit-prefix> \
  --expected-commit <reviewed-main-40-character-sha>
systemctl restart litblogs-web.service
curl --fail --silent --show-error https://litblogs.school.example/api/health/ready
systemctl start litblogs-password-reset.service litblogs-upload-reconciliation.service
systemctl enable --now litblogs-password-reset.timer litblogs-upload-reconciliation.timer
```

Require each manual one-shot to exit zero inside five minutes before enabling its timer, and inspect the journal only for bounded generic outcomes. Never retain reset links, email addresses, upload names, or content in evidence. Confirm only the approved PostgreSQL/SMTP IP:port pairs appeared in firewall evidence and every required negative probe was denied. Alert on maintenance failure/timeout, and repeat the drop-in, exact-port policy, marker, and probe review after every PostgreSQL or SMTP address or port change.

The script validates that the release is a real direct child of `releases`, its commit matches `RELEASE-MANIFEST`, and every artifact is root-owned and not group/world writable. It rejects every release-tree symlink except the narrowly reviewed virtual-environment Python/lib64 links, whose final Python executable must be the root-owned immutable Python 3.13 running the switch. It serializes activation/rollback with a protected advisory lock, updates pointers atomically, fsyncs the pointer directory, and records the former current release as `previous`. It refuses to overwrite a real file or directory and fails closed when `previous` exists without `current`; clearing or reconstructing an orphan pointer requires a separate reviewed recovery operation.

## Rollback

Application rollback is allowed only when the previous binary remains compatible with the current schema. Favor additive, expand/contract migrations. Never improvise an Alembic downgrade after traffic has written new data. If schema rollback is unavoidable, stop all writers and use a separately reviewed reversible migration or restore the coupled database/upload recovery set.

An explicitly approved downgrade across `f1ad78b2035f` remains an exceptional schema-recovery operation, not the normal rollback path. With writers stopped, first prove the five fixed roles have no memberships, then grant the exact direct `litblog_identity_owner` membership to `litblogs_migrator` with `ADMIN FALSE`, `INHERIT TRUE`, and `SET TRUE` immediately before the release-local Alembic downgrade:

```sql
GRANT litblog_identity_owner TO litblogs_migrator WITH ADMIN FALSE, INHERIT TRUE, SET TRUE;
-- Run only the separately approved release-local Alembic downgrade.
REVOKE litblog_identity_owner FROM litblogs_migrator;
```

The `f1ad78b2035f` downgrade must first prove cluster-wide that `litblog_identity_owner` owns exactly the three reviewed operator routines and no other object. It transfers only those exact signatures with explicit `ALTER FUNCTION ... OWNER TO CURRENT_USER`; it never runs `REASSIGN OWNED`. Whether the downgrade succeeds or fails, the separate protected role-administrator session must execute the revoke immediately and prove both membership directions are empty before any retry, application connection, or maintenance exit. If the exact pre-grant, immediate revoke, or catalog proof cannot be guaranteed, do not downgrade; restore the coupled recovery set instead.

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
