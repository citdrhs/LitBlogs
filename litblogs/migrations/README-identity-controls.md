# Identity controls migration runbook

`0002_add_authorization_constraints.sql` and `0003_add_identity_controls.sql` are
executable semantic references for this branch's pre-Alembic lineage. The enterprise
deployment stack uses a single-head Alembic history: both files must be converted into
ordered Alembic revisions, followed by a model-drift check, before release. Raw SQL
must not ship or be applied alongside that Alembic history. The standalone SQL
commands below are retained only for isolated validation of this branch's required
DDL semantics.

Migration `0003` follows `0002` and adds revocable server-side browser sessions,
digest-only teacher invitations, a privacy-preserving operator audit trail, and the
account-disabled timestamp.

It also adds `password_resets.delivery_claim_digest`: a nullable 64-character digest
used as the compare-and-swap lease version for SMTP delivery. Every claim/reclaim
rotates the nonce, only its digest is persisted, and a stale worker cannot complete a
newer lease.
All password-reset rows that predate `0003` are invalidated during migration. Their
token and expiry are cleared, they become used/failed, and any claim is cleared. This is
intentional: legacy deployments may have stored raw account-takeover bearer tokens, and
runtime no longer accepts plaintext-token fallback. Announce that outstanding reset
links will stop working and users must request a new one.

There is intentionally no session backfill. All pre-migration JWT cookies become
invalid as soon as the new application version is active, so every user must sign in
again. Announce this planned logout to the school before the maintenance window.

## Preflight

1. Stop application writes and background workers.
2. Take and verify a restorable PostgreSQL backup.
3. Generate a new, random `TEACHER_INVITE_HMAC_KEY` of at least 32 bytes in the
   approved secret store. It must be different from `SECRET_KEY` and must never be
   placed in Git, shell history, logs, or an invitation message.
   Provision two separate protected operator-config JSON documents, one with purpose
   `invitation` and one with purpose `account`. Each contains exactly `purpose`, a
   dedicated least-privilege `database_url`, the invitation HMAC key, and
   `allowed_email_domains`; the account document may use an empty domain list. There is
   no configurable expected-role field: purpose is hard-bound to
   `litblog_invitation_operator` or `litblog_account_operator`, and extra fields are
   rejected. Never include JWT signing, OAuth/provider, SMTP, VAPID, admin-code, or web
   runtime secrets. The PostgreSQL URL must use its hard-bound role, an explicit strong
   password, exact target `127.0.0.1:5432/litblogs`, `sslmode=verify-full`, and exact CA path
   `/etc/litblogs/postgres-root-ca.pem`, with no connection-target overrides. The CA,
   `/etc/litblogs`, `/etc`, and `/` must all be root-owned and not group/world writable;
   the CA must be a regular file and no component may be a symlink. A root-mediated
   wrapper or equivalent secret broker opens the applicable document on inherited file
   descriptor 3 (or sets the non-secret numeric `LITBLOG_OPERATOR_CONFIG_FD`). The
   descriptor must be a regular file or FIFO owned by root/the operator effective UID
   with no group/world permissions; anonymous protected pipes are preferred. Runtime
   rechecks the fixed database role, role flags/memberships, direct privileges, function
   ownership, and the exact EXECUTE-only boundary before returning a session.
4. Remove `TEACHER_ACCESS_CODE` from the deployment environment.
5. Confirm the operator shell is access-controlled and its command metadata audit is
   retained under the school's administrative policy. Invitation creation prints the
   raw invitation exactly once. The operator shell must not retain the secret-bearing stdout.
   Exclude it from session recordings, CI artifacts, command transcripts, and logs;
   deliver it only through an approved private channel.
6. Run the queries below and stop if any returns a row. The application accepts ASCII
   school email identities only, removes U+0020 padding, stores them lowercase, and
   rejects every remaining space and ASCII control (C0 plus DEL). PostgreSQL enforces the exact same
   locale-independent ASCII `translate(btrim(email), ...)` canonical form and pins
   byte comparisons/indexing to `COLLATE "C"`. Resolve invalid or duplicate legacy identities
   through the reviewed account-reconciliation process before applying the boundary;
   do not delete or merge school records ad hoc. `teachers.user_id` is the canonical
   teacher/account association; the migration only backfills a null association when
   its denormalized email maps to exactly one teacher account.

```sql
SELECT id
FROM users
WHERE octet_length(email) <> char_length(email)
   OR email ~ '[[:cntrl:]]'
   OR btrim(email) = ''
   OR btrim(email) ~ '[[:space:]]';

SELECT translate(
           btrim(email),
           'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
           'abcdefghijklmnopqrstuvwxyz'
       ) COLLATE "C" AS normalized_email,
       count(*)
FROM users
GROUP BY translate(
             btrim(email),
             'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
             'abcdefghijklmnopqrstuvwxyz'
         ) COLLATE "C"
HAVING count(*) > 1;

SELECT teacher.id
FROM teachers AS teacher
LEFT JOIN users AS account ON account.id = teacher.user_id
WHERE teacher.email IS NULL
   OR octet_length(teacher.email) <> char_length(teacher.email)
   OR teacher.email ~ '[[:cntrl:]]'
   OR char_length(btrim(teacher.email)) > 100
   OR btrim(teacher.email) = ''
   OR btrim(teacher.email) ~ '[[:space:]]'
   OR (
       teacher.user_id IS NOT NULL
       AND (
           account.id IS NULL
           OR account.role::text <> 'TEACHER'
           OR translate(
                  btrim(teacher.email),
                  'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
                  'abcdefghijklmnopqrstuvwxyz'
              ) COLLATE "C" <> translate(
                  btrim(account.email),
                  'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
                  'abcdefghijklmnopqrstuvwxyz'
              ) COLLATE "C"
       )
   )
   OR (
       teacher.user_id IS NULL
       AND (
           SELECT count(*)
           FROM users AS candidate
           WHERE candidate.role::text = 'TEACHER'
             AND translate(
                     btrim(candidate.email),
                     'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
                     'abcdefghijklmnopqrstuvwxyz'
                 ) COLLATE "C" = translate(
                     btrim(teacher.email),
                     'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
                     'abcdefghijklmnopqrstuvwxyz'
                 ) COLLATE "C"
       ) <> 1
   );
```

## Apply and verify

Do not apply the raw semantic-reference SQL to staging or production. The deployment
stack must first convert `0002` and `0003` into reviewed, ordered Alembic revisions and
pass the model-drift check. Run the final revision through the approved database service
configuration, `.pgpass`, or equivalent secret provider; never put a credential-bearing
database URL in process arguments. From the release directory the deployment command is:

```sh
alembic upgrade head
```

Verify the new objects:

```sql
SELECT table_name
FROM information_schema.tables
WHERE table_name IN (
    'browser_sessions',
    'teacher_invitations',
    'operator_audit_events'
)
ORDER BY table_name;

SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'users' AND column_name = 'disabled_at';

SELECT indexname
FROM pg_indexes
WHERE indexname IN (
    'ix_browser_sessions_user_id',
    'ix_browser_sessions_user_recency',
    'ix_browser_sessions_expires_at',
    'uq_users_email_normalized',
    'uq_teachers_user_id',
    'ix_teacher_invitations_email_digest',
    'ix_teacher_invitations_expires_at',
    'uq_teacher_invitation_active_email',
    'ix_operator_audit_events_actor_identifier',
    'ix_operator_audit_events_action',
    'ix_operator_audit_events_resource_digest',
    'ix_operator_audit_events_created_at'
)
ORDER BY indexname;
```

Restart the reviewed application version with the new configuration. Confirm an old
cookie receives `401`, then sign in with a synthetic account and confirm logout makes
that cookie unusable. Confirm a password change invalidates every active session. The
application serializes issuance on the user row and retains no more than ten session
rows per account; the `(user_id)` and expiry indexes are required for this bounded
cleanup path.

After the reviewed wrapper opens the correct purpose-specific operator config on file
descriptor 3, the following commands prompt for the target email without echo. Never pass the email
through argv or an environment variable: those surfaces are commonly captured by
process listings, auditd, and session tooling. The operator identifier is intended
audit metadata:

```sh
python -m manage_teacher_invitations create --expires-hours 24 --operator "$REVIEWED_OPERATOR"
python -m manage_teacher_invitations revoke --operator "$REVIEWED_OPERATOR"
python -m manage_accounts disable --operator "$REVIEWED_OPERATOR"
python -m manage_accounts enable --operator "$REVIEWED_OPERATOR"
```

For reviewed non-interactive automation, supply exactly one email line through a
protected stdin file descriptor from the approved PII store. Do not put the raw address
in the file name, command line, environment, transcript, or operator audit metadata;
restrict the input file/descriptor to the operator account and remove it after use.
The operator process must not inherit the web application's environment or secret
store. Close the config descriptor after each command and destroy any ephemeral config
material under the approved credential-lifecycle policy.

Verify every successful operator action has a matching actor/action/outcome event in
`operator_audit_events`. The actor identifier is intended audit data; the target is a
domain-separated HMAC digest. Verify that raw session identifiers, invitation tokens,
and invitee/account email addresses do not exist in the new tables or logs.

Apply least-privilege grants with the fixed reviewed role names:

- The web runtime needs `SELECT`, `INSERT`, `UPDATE`, and bounded cleanup `DELETE`
  on `browser_sessions`; `SELECT` and `UPDATE` on `teacher_invitations`; and
  INSERT-only access on `operator_audit_events`. Its existing account lifecycle paths
  also need the reviewed `users` privileges required to update password/disabled state
  and `UPDATE` on `password_resets` so disable can invalidate every queued or delivered
  reset in the same transaction.
- The invitation operator receives only EXECUTE on the fixed invitation create/revoke
  routines. The account operator receives only EXECUTE on the fixed account-status
  routine. Both have no direct table privileges and no sequence privileges. Each
  routine validates bounded lowercase-hex digests and actor identifiers, performs the
  exact state transition, and writes its audit outcome in one transaction.
- Both operator roles are `NOINHERIT`, have no role memberships, and are not function,
  schema, table, or sequence owners. They must not inherit the web runtime,
  schema-owner, migration, superuser, or `BYPASSRLS` roles. A separate non-login
  `litblog_identity_owner` owns the SECURITY DEFINER routines. A separate audit-review
  role alone receives `SELECT` on `operator_audit_events`.

Do not grant the web or operator roles `UPDATE` or `DELETE` on the audit table. Revoke
broad `PUBLIC` privileges. The integrated migration is created by exact deployment role
`litblogs_migrator`; configure its future objects with matching `ALTER DEFAULT
PRIVILEGES` and verify that it remains the actual creator. The semantic SQL cannot
establish environment role membership on its own.

After revoking every pre-existing object/role-membership grant, the reviewed privilege
migration must establish the exact boundary below. Function signatures must match the
Alembic revision exactly:

```sql
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE CREATE ON SCHEMA public
    FROM litblog_account_operator, litblog_invitation_operator;

REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public
    FROM litblog_account_operator, litblog_invitation_operator;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public
    FROM litblog_account_operator, litblog_invitation_operator;
REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public
    FROM PUBLIC, litblog_account_operator, litblog_invitation_operator;

ALTER DEFAULT PRIVILEGES FOR ROLE litblogs_migrator IN SCHEMA public
    REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;

-- The non-login definer owns only the three routines and receives the least
-- underlying privileges their fixed bodies need.
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public
    FROM litblog_identity_owner;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public
    FROM litblog_identity_owner;
GRANT USAGE ON SCHEMA public TO litblog_identity_owner;
GRANT SELECT (id, email), UPDATE (disabled_at)
    ON users TO litblog_identity_owner;
GRANT SELECT (user_id, revoked_at, expires_at), UPDATE (revoked_at)
    ON browser_sessions TO litblog_identity_owner;
GRANT SELECT (user_id), UPDATE (
    token, expires_at, used, delivery_status, delivery_attempted_at,
    delivery_claim_digest
) ON password_resets TO litblog_identity_owner;
GRANT SELECT (email_digest, consumed_at, revoked_at, expires_at),
      INSERT (token_digest, email_digest, expires_at, created_by),
      UPDATE (revoked_at)
    ON teacher_invitations TO litblog_identity_owner;
GRANT INSERT (actor_identifier, action, outcome, resource_digest)
    ON operator_audit_events TO litblog_identity_owner;
GRANT USAGE ON SEQUENCE teacher_invitations_id_seq,
                        operator_audit_events_id_seq
    TO litblog_identity_owner;

-- Run this bounded ownership handoff as the reviewed database bootstrap admin.
-- The CREATE grant and membership exist only for these ALTER statements.
BEGIN;
GRANT CREATE ON SCHEMA public TO litblog_identity_owner;
GRANT litblog_identity_owner TO litblogs_migrator;
ALTER FUNCTION public.operator_set_account_status(
    VARCHAR, BOOLEAN, VARCHAR, VARCHAR
) OWNER TO litblog_identity_owner;
ALTER FUNCTION public.operator_create_teacher_invitation(
    VARCHAR, VARCHAR, TIMESTAMPTZ, VARCHAR, VARCHAR
) OWNER TO litblog_identity_owner;
ALTER FUNCTION public.operator_revoke_teacher_invitation(
    VARCHAR, VARCHAR, VARCHAR
) OWNER TO litblog_identity_owner;
REVOKE litblog_identity_owner FROM litblogs_migrator;
REVOKE CREATE ON SCHEMA public FROM litblog_identity_owner;

REVOKE ALL ON FUNCTION public.operator_set_account_status(
    VARCHAR, BOOLEAN, VARCHAR, VARCHAR
) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.operator_create_teacher_invitation(
    VARCHAR, VARCHAR, TIMESTAMPTZ, VARCHAR, VARCHAR
) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.operator_revoke_teacher_invitation(
    VARCHAR, VARCHAR, VARCHAR
) FROM PUBLIC;

-- Remove every stale explicit grantee, including an old login or support role.
-- The purpose grants below are then rebuilt from an exact empty boundary.
DO $operator_acl$
DECLARE
    privilege_record RECORD;
BEGIN
    FOR privilege_record IN
        SELECT
            pg_catalog.format(
                '%I.%I(%s)',
                namespaces.nspname,
                procedures.proname,
                pg_catalog.pg_get_function_identity_arguments(procedures.oid)
            ) AS function_signature,
            grantees.rolname AS unexpected_function_grantee
        FROM pg_catalog.pg_proc AS procedures
        JOIN pg_catalog.pg_namespace AS namespaces
          ON namespaces.oid = procedures.pronamespace
        CROSS JOIN LATERAL pg_catalog.aclexplode(
            COALESCE(
                procedures.proacl,
                pg_catalog.acldefault('f', procedures.proowner)
            )
        ) AS privileges
        JOIN pg_catalog.pg_roles AS grantees
          ON grantees.oid = privileges.grantee
        WHERE procedures.oid IN (
            'public.operator_set_account_status(VARCHAR,BOOLEAN,VARCHAR,VARCHAR)'
                ::pg_catalog.regprocedure,
            'public.operator_create_teacher_invitation(VARCHAR,VARCHAR,TIMESTAMPTZ,VARCHAR,VARCHAR)'
                ::pg_catalog.regprocedure,
            'public.operator_revoke_teacher_invitation(VARCHAR,VARCHAR,VARCHAR)'
                ::pg_catalog.regprocedure
        )
          AND privileges.privilege_type = 'EXECUTE'
          AND privileges.grantee <> procedures.proowner
          AND (
              grantees.rolname <> CASE procedures.proname
                  WHEN 'operator_set_account_status'
                      THEN 'litblog_account_operator'
                  ELSE 'litblog_invitation_operator'
              END
              OR privileges.is_grantable
          )
    LOOP
        EXECUTE pg_catalog.format(
            'REVOKE ALL PRIVILEGES ON FUNCTION %s FROM %I',
            privilege_record.function_signature,
            privilege_record.unexpected_function_grantee
        );
    END LOOP;
END;
$operator_acl$;

GRANT EXECUTE ON FUNCTION public.operator_set_account_status(
    VARCHAR, BOOLEAN, VARCHAR, VARCHAR
) TO litblog_account_operator;
GRANT EXECUTE ON FUNCTION public.operator_create_teacher_invitation(
    VARCHAR, VARCHAR, TIMESTAMPTZ, VARCHAR, VARCHAR
) TO litblog_invitation_operator;
GRANT EXECUTE ON FUNCTION public.operator_revoke_teacher_invitation(
    VARCHAR, VARCHAR, VARCHAR
) TO litblog_invitation_operator;
GRANT USAGE ON SCHEMA public
    TO litblog_account_operator, litblog_invitation_operator;
COMMIT;
```

The release gate must run real database privilege probes as each role. Run successful
function probes inside transactions that are always rolled back. Run every negative
probe in a fresh transaction and require PostgreSQL `SQLSTATE 42501`
(`insufficient_privilege`), not an empty result:

```sql
-- Account role: the mediated call succeeds and is rolled back.
BEGIN;
SET ROLE litblog_account_operator;
SELECT public.operator_set_account_status(
    CAST('release-probe@example.invalid' AS VARCHAR(100)),
    CAST(TRUE AS BOOLEAN),
    CAST('release-probe' AS VARCHAR(100)),
    CAST(repeat('a', 64) AS VARCHAR(64))
);
ROLLBACK;

-- Invitation role: both mediated calls succeed and are rolled back.
BEGIN;
SET ROLE litblog_invitation_operator;
SELECT public.operator_create_teacher_invitation(
    CAST(repeat('b', 64) AS VARCHAR(64)),
    CAST(repeat('c', 64) AS VARCHAR(64)),
    CAST(CURRENT_TIMESTAMP + INTERVAL '1 hour' AS TIMESTAMPTZ),
    CAST('release-probe' AS VARCHAR(100)),
    CAST(repeat('d', 64) AS VARCHAR(64))
);
SELECT public.operator_revoke_teacher_invitation(
    CAST(repeat('e', 64) AS VARCHAR(64)),
    CAST('release-probe' AS VARCHAR(100)),
    CAST(repeat('f', 64) AS VARCHAR(64))
);
ROLLBACK;

-- Every block below is a separate transaction. The marked statement must raise
-- SQLSTATE 42501; the external harness catches that error and executes ROLLBACK.
BEGIN;
SET LOCAL ROLE litblog_account_operator;
SELECT id, email, disabled_at, password FROM users LIMIT 0; -- must deny
ROLLBACK;

BEGIN;
SET LOCAL ROLE litblog_account_operator;
UPDATE password_resets SET token = repeat('a', 64) WHERE FALSE; -- must deny
ROLLBACK;

BEGIN;
SET LOCAL ROLE litblog_account_operator;
UPDATE users SET password = password WHERE FALSE; -- must deny
ROLLBACK;

BEGIN;
SET LOCAL ROLE litblog_account_operator;
UPDATE browser_sessions SET revoked_at = CURRENT_TIMESTAMP WHERE FALSE; -- must deny
ROLLBACK;

BEGIN;
SET LOCAL ROLE litblog_account_operator;
SELECT id, content FROM blogs LIMIT 0; -- must deny private content
ROLLBACK;

BEGIN;
SET LOCAL ROLE litblog_account_operator;
SELECT nextval('operator_audit_events_id_seq'); -- must deny
ROLLBACK;

BEGIN;
SET LOCAL ROLE litblog_account_operator;
SELECT public.operator_create_teacher_invitation( -- wrong purpose; must deny
    CAST(repeat('b', 64) AS VARCHAR(64)),
    CAST(repeat('c', 64) AS VARCHAR(64)),
    CAST(CURRENT_TIMESTAMP + INTERVAL '1 hour' AS TIMESTAMPTZ),
    CAST('release-probe' AS VARCHAR(100)),
    CAST(repeat('d', 64) AS VARCHAR(64))
);
ROLLBACK;

BEGIN;
SET LOCAL ROLE litblog_invitation_operator;
SELECT token_digest, email_digest FROM teacher_invitations LIMIT 0; -- must deny
ROLLBACK;

BEGIN;
SET LOCAL ROLE litblog_invitation_operator;
INSERT INTO operator_audit_events ( -- must deny direct audit forgery
    actor_identifier, action, outcome, resource_digest
) VALUES ('forged', 'ACCOUNT_DISABLED', 'SUCCEEDED', repeat('a', 64));
ROLLBACK;

BEGIN;
SET LOCAL ROLE litblog_invitation_operator;
SELECT id, content FROM assignment_submissions LIMIT 0; -- must deny
ROLLBACK;

BEGIN;
SET LOCAL ROLE litblog_invitation_operator;
SELECT public.operator_set_account_status( -- wrong purpose; must deny
    CAST('release-probe@example.invalid' AS VARCHAR(100)),
    CAST(TRUE AS BOOLEAN),
    CAST('release-probe' AS VARCHAR(100)),
    CAST(repeat('a', 64) AS VARCHAR(64))
);
ROLLBACK;

BEGIN;
SET LOCAL ROLE litblog_invitation_operator;
CREATE TABLE public.operator_escape_probe (id INTEGER); -- must deny
ROLLBACK;
```

Also prove each role receives `42501` for the other purpose's function and for CREATE
in schema `public`. Assert from `pg_roles`, `pg_auth_members`, `pg_proc`, and ACL
catalogs that both operators are `NOINHERIT`, non-superuser, cannot `BYPASSRLS`, have
no membership edges in either direction, no direct privilege on any public-schema
relation or sequence, own no routine, and can execute only
their purpose routines. Assert all three routines are owned by the non-login identity
owner, have `prosecdef = TRUE`, and exact `proconfig = ARRAY['search_path=pg_catalog,
pg_temp']`. The identity owner must be `NOLOGIN`, `NOINHERIT`, non-superuser,
non-`BYPASSRLS`, have no membership edge in either direction, and have no schema
CREATE privilege. Confirm no public-schema routine remains executable by `PUBLIC`, and
that `litblogs_migrator` owns/creates future objects so its default-privilege rule is
effective. A grant inspection alone is insufficient: the positive and negative
statements above are mandatory integration probes after every migration or membership
change.

## Application rollback and later schema retirement

An application rollback changes the authentication security model and requires explicit
incident or change approval. Disable new sign-ins and token issuance, stop application
traffic and workers, and take another verified backup. Export and retain the operator
audit evidence under the school's incident-retention policy before any rollback work.
Record the disabled identities in a separately protected incident artifact without
weakening the live append-only audit grants.

Roll back the application code only while traffic remains blocked. Retain the additive
identity schema: `browser_sessions`, `teacher_invitations`, `operator_audit_events`,
`users.disabled_at`, the canonical-email constraints, and their indexes stay in place.
Older code may ignore these objects, but leaving them intact preserves revocation,
disabled-account, invitation, and audit evidence for forward recovery and review.

Before any older stateless application can receive traffic, choose and document one of
these token-containment controls:

1. Preferably rotate the JWT signing key, remove the old key from every instance and
   secret cache, restart the fleet, and verify that a token signed with the retired key
   receives `401`.
2. If emergency key rotation is impossible, keep all issuance and traffic stopped for
   the maximum token lifetime plus configured clock skew after the last possible token
   issuance, then verify that every pre-rollback token is expired. The maintenance
   window remains closed throughout that wait.

The older application does not enforce `users.disabled_at`. Complete explicit
disabled-account containment before restoring traffic: reconcile each disabled identity
and block it at the reviewed identity provider, reverse proxy, or another fail-closed
control that the older application cannot bypass. If that containment cannot be proved,
do not restore traffic. Likewise, keep public teacher/admin provisioning blocked unless
the rolled-back version has an independently reviewed one-time provisioning control.

Keep the audit table and exported evidence available to authorized reviewers. Retire the
invitation HMAC key only through the school's secret-retirement process; never reuse it
for another purpose. Lowercased ASCII email canonicalization is not reversed
automatically; a reviewed backup restore is required if original display casing itself
must be recovered.

Dropping identity tables, disabled-account state, constraints, indexes, or audit evidence
is not part of application rollback. Such removal requires a separately approved
schema-retirement migration after the retention period, after every disabled identity is
reconciled, and only when no supported application version depends on the additive
schema.
