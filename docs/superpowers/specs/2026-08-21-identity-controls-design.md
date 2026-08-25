# Enterprise Identity Controls Design

**Date:** 2026-08-21

**Branch:** `codex/05-authorization-wip`
**Base commit:** `753d957b25b6719cddfbcf9bfceb0b2765d29e1a`

## Goal

Add durable browser-session revocation, one-time email-bound teacher invitations, and a non-enumerating password-registration contract without weakening the authorization and privacy controls already implemented on this branch. The work must not modify the separately owned upload/content security layer.

## Scope

This slice adds three connected identity controls:

1. Every authenticated browser or bearer request must prove that its signed JWT still maps to an active server-side session.
2. Teacher account creation must require a one-time invitation bound to the teacher's normalized email address; the shared `TEACHER_ACCESS_CODE` path is removed.
3. Password registration must return the same generic HTTP 202 response for accepted, duplicate, and invalid-invitation requests, and it must not automatically sign the browser in.

It also adds the account lifecycle operations required to make session revocation complete: current-session logout, password change, password reset, administrative disable/enable, and account deletion.

## Architecture

### Durable browser sessions

The application keeps its signed JWT cookie and bearer-token format, including the random `jti` claim, but adds a `browser_sessions` database table. Only a SHA-256 digest of the JWT `jti` is stored. The raw JWT and raw `jti` remain client-side and must never be stored or logged.

Each authenticated request follows this sequence:

1. Preserve the existing ambiguous-cookie-and-bearer rejection and CSRF rules.
2. Decode and validate the signed JWT.
3. Hash its `jti` using SHA-256.
4. Load an unrevoked, unexpired session with that digest and the same subject user.
5. Load the user and reject the request if the account is disabled.
6. Put the current session identifier on `request.state` for operations such as logout.

If any step fails, authentication is denied. There is no compatibility fallback for stateless legacy tokens; deployment of the migration intentionally logs existing users out.

`browser_sessions` contains:

- a database primary key;
- a unique, indexed 64-character `jti_digest`;
- an indexed `user_id` foreign key with delete cascade;
- `created_at` and `expires_at` timestamps;
- a nullable `revoked_at` timestamp.

Session issuance and revocation are transactional:

- Sign-in and successful verified-provider OAuth create the session row and commit it before setting response cookies.
- Logout conditionally revokes only the current session and remains safe if repeated concurrently.
- Password change, successful password reset, account disable, and account deletion revoke every active session for that user in the same transaction as the lifecycle change. Disable also permanently invalidates pending, processing, and delivered password-reset rows in that transaction. Account deletion locks and revalidates the parent user before touching any session, reset, or content child, preserving the same user-to-child lock order as issuance, reset, change, and disable.
- Account enable clears `disabled_at` but creates no session; the user must sign in.
- Expired sessions are deleted opportunistically during session issuance, and the cleanup operation is idempotent and bounded by an indexed expiry predicate.
- Session issuance holds the user-row lock and retains at most ten session rows for that user. Before inserting a new row it deterministically deletes rows older than the nine newest by `(created_at, id)`, so concurrent logins cannot exceed the active-session cap or grow per-user storage without bound; deleted tokens fail closed exactly like revoked tokens.

The `users` table gains nullable `disabled_at` and a unique canonical-byte index. School email identities are explicitly ASCII-only. Normalization removes only U+0020 edge padding, rejects every remaining space and ASCII control character (C0 plus DEL), and lowercases the result. PostgreSQL uses explicit ASCII `translate(btrim(email), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')`, `[[:cntrl:]]`, and `COLLATE "C"` checks plus a bytewise `varchar_pattern_ops` unique index instead of locale-sensitive `lower()`, so Python normalization and database uniqueness cannot diverge under Turkish/Azeri or tailored ICU collations, Unicode case-folding, NUL/control input, or legacy whitespace. The migration preflight must stop on invalid legacy identities or canonical duplicates and require reviewed reconciliation rather than choosing an account implicitly. `teachers.user_id` becomes the non-null, unique canonical teacher/account association; null legacy associations are backfilled only on an unambiguous canonical email match, conflicting mappings stop migration, and the denormalized teacher email is synchronized to the user. Runtime ownership lookup and teacher creation use only the user-id association. Password login, OAuth, recovery, and authenticated request paths treat disabled accounts as unavailable without exposing account existence through public error details.

### Password change and account status

An authenticated `POST /api/auth/change-password` endpoint accepts bounded current and new passwords. It verifies the current password, conditionally updates the password hash, revokes all sessions, and invalidates every outstanding password-reset row atomically before clearing authentication cookies. Reset consumption locks the same enabled user row before its conditional token update, so password change, reset, and disable have one serialized winner. A successful response requires the user to sign in again.

Password-reset delivery claims use a fresh random nonce on every initial claim or stale reclaim, persist only its SHA-256 domain-separated digest, and return the raw nonce only in worker memory. Completion locks/rechecks the enabled user and compare-and-swaps the exact processing status plus claim digest before publishing or failing a token. A stale worker therefore cannot overwrite a newer reclaimed delivery, regardless of whether the stale SMTP attempt succeeded or failed.

Only SHA-256 reset-token digests are accepted at runtime. Migration invalidates every pre-existing password-reset row (token/expiry cleared, used true, status failed, claim cleared) rather than retaining potentially plaintext bearer tokens from a legacy release. Existing reset links intentionally stop working and users request a new link.

An admin-only, default-deny `PUT /api/users/{user_id}/status` endpoint accepts a strict bounded `{ "disabled": boolean }` request. Disabling sets `disabled_at`, revokes all sessions, and invalidates all password-reset/outbox rows atomically. Enabling clears `disabled_at` but never restores reset state. Each successful change writes the same actor/action/outcome audit contract in the transaction, using `admin-user:<id>` as the authenticated actor and a domain-separated HMAC target; an audit-storage failure rolls back the account status, session revocation, and reset invalidation together. Administrators cannot disable their own active account through this endpoint. The route remains protected by the existing admin policy and route-inventory checks.

The same lifecycle operations are exposed through explicit non-public operator commands, `python -m manage_accounts disable` and `python -m manage_accounts enable`, run from the `litblogs` application directory. Each command requires an exact normalized email and a bounded operator identifier, changes exactly one account in one transaction, and emits only a generic success/failure status. It never prints a database identifier, session identifier, token, password hash, or email digest. Disabling through the CLI revokes every active session atomically. Successful and target-not-found outcomes persist an operator audit event in the same transaction; an audit-write failure rolls back the privileged state change.

### One-time teacher invitations

Teacher invitation management is not exposed through FastAPI. From the `litblogs` application directory, a reviewed operator runs `python -m manage_teacher_invitations create` with a lifetime and operator identifier; the invitee email is supplied only through the no-echo prompt or a protected stdin file descriptor, never argv or environment. The command emits the raw random invitation token exactly once to standard output. The operator can revoke an unconsumed invitation with `python -m manage_teacher_invitations revoke`, supplying the exact invitee email through the same private channel; revocation prints only a generic status and never reveals invitation or database identifiers. Every create/revoke outcome persists actor, bounded action/outcome, and a domain-separated HMAC target digest. Logs and database rows contain neither the raw token nor the raw email.

The operator commands do not import the web `SessionLocal` or call the full application settings loader. A root-mediated wrapper provides a minimal, purpose-specific JSON config on protected inherited file descriptor 3: purpose, a dedicated least-privilege PostgreSQL URL, invitation HMAC key, and allowed school domains only. Purpose hard-binds the exact database role; no caller-configurable expected-role field exists. JWT signing, OAuth/provider, SMTP, VAPID, admin-code, and other web secrets are forbidden. The URL requires the reviewed psycopg2 driver, a strong dedicated credential, exact target `127.0.0.1:5432/litblogs`, `sslmode=verify-full`, and exact root-owned CA `/etc/litblogs/postgres-root-ca.pem` with a root-owned, non-writable ancestor chain. The session factory requires `session_user = current_user` to equal the purpose role, rejects unsafe flags or membership edges, direct privileges on any public-schema relation/sequence, schema CREATE, public/unexpected routine EXECUTE, or unsafe function ownership/configuration. Operator roles receive EXECUTE only on purpose-specific fixed-search-path SECURITY DEFINER routines; those routines perform each bounded transition and audit write atomically. Invitation and account configs cannot be interchanged.

The `teacher_invitations` table contains:

- a database primary key;
- a unique 64-character SHA-256 `token_digest`;
- an indexed 64-character email HMAC digest;
- `created_at` and `expires_at` timestamps;
- nullable `consumed_at` and `revoked_at` timestamps;
- a bounded operator audit identifier.

Email matching uses the same ASCII-only normalized email (U+0020 edge trim plus lowercase, with remaining spaces and C0/DEL controls rejected) and a dedicated production-required `TEACHER_INVITE_HMAC_KEY`. The email digest is:

```text
HMAC-SHA256(
  TEACHER_INVITE_HMAC_KEY,
  "litblog:teacher-invite-email:v1\0" || normalized_email
)
```

The key is at least 32 bytes, must not be a placeholder, and must differ from the JWT signing key. It is used only for normalized-email HMACs in this identity slice: invitation binding and operator-audit target references use distinct domain prefixes. It is never reused as an OAuth, reset-token, JWT, or public/provider secret.

Invitation consumption is a conditional database update with `RETURNING`. The predicate checks token digest, email digest, expiration, `consumed_at IS NULL`, and `revoked_at IS NULL`. Account creation and invitation consumption occur in one transaction, so a duplicate or concurrent request cannot replay the invitation, and a failed user insert rolls the invitation state back.

Password and verified-provider OAuth teacher registration use the same invitation service. OAuth binds the invitation to the provider-verified email, not a client-supplied unverified address. An existing valid federated identity can sign in without consuming another invitation, while a new teacher identity must consume one atomically.

The legacy `TEACHER_ACCESS_CODE` setting, backend payload field, frontend state and labels, environment documentation, and production validation are removed. A structurally strict `teacher_invitation_token` / `teacherInvitationToken` field replaces it only on account-creation requests.

### Registration privacy contract

Password registration never creates a browser session and always returns HTTP 202 with the same body for every structurally valid request:

```json
{
  "message": "If registration can be completed, sign in with the submitted credentials."
}
```

This includes successful student registration, successful teacher registration, duplicate email or username, an email outside the configured school domains, invalid/expired/mismatched/replayed teacher invitations, and attempts to request the admin role. Account email inputs are bounded to the persisted 100-character contract before application work. The application performs the password hashing work before private account/invitation decisions so the common valid-request paths have comparable application-side work. No error body identifies which private condition occurred.

The frontend shows the generic message and directs the user to sign in. It does not fetch the browser session or assume that the account was created. This closes direct registration-endpoint enumeration. Password sign-in returns one generic 401 for an unknown, disabled, or wrong-password account and performs the same offloaded password-verification primitive against a runtime-generated dummy hash when no active user exists. A successful sign-in still necessarily proves valid credentials; fully hiding that distinction would require a separate email-verification product flow and is outside this slice.

Malformed requests rejected by schema validation receive a generic HTTP 422 body on credential-bearing authentication routes. This both reveals no account state and prevents FastAPI's default validation serialization from reflecting password, reset-token, or teacher-invitation input values.

## Components and boundaries

- `litblogs/identity_controls.py` owns `jti` hashing, session issuance metadata, transactional session lookup/revocation/cleanup, email normalization/HMAC, and atomic invitation consumption. It does not import FastAPI response objects or expose raw secret values.
- `litblogs/models.py` owns the `BrowserSession`, `TeacherInvitation`, and `User.disabled_at` persistence model.
- `litblogs/config.py` validates the dedicated invitation HMAC key and removes the shared teacher access code.
- `litblogs/main.py` remains the route composition layer. It calls the identity-control primitives and is responsible for committing before setting cookies.
- `litblogs/manage_teacher_invitations.py` is the non-public operator CLI. It creates and revokes invitation rows and prints a newly created token once.
- `litblogs/manage_accounts.py` is the non-public operator CLI for transactional account disable/re-enable and all-session revocation.
- `litblogs/migrations/0003_add_identity_controls.sql` is the deterministic PostgreSQL migration. The runbook documents that no session backfill occurs and existing tokens become invalid.
- Frontend signup code owns only input collection and generic success messaging; it never interprets invitation validity.

## Error and concurrency behavior

- Public registration and recovery-related decisions use generic responses and never echo database, invitation, session, SMTP, or provider exception details.
- Authentication failures remain generic HTTP 401 responses. Authorization failures retain the existing default-deny policy behavior.
- Conditional updates make logout, session revocation, invitation consumption, and password-reset token consumption safe under retries and races.
- Password mutations and all-session revocation share one transaction; neither can commit without the other.
- Cookies are written only after their session row commits. A database failure cannot leave the browser holding a newly accepted but untracked session.
- No new route or operator command logs credentials, invitation tokens, JWTs, `jti` values, reset tokens, or HMAC key material.

## Migration and deployment

The raw SQL migration is numbered after the current `0002` migration and captures this standalone branch's required DDL semantics. The enterprise deployment stack must convert both raw `0002` and `0003` files into ordered, single-head Alembic revisions and pass a model-drift check; the raw files must not ship or be applied alongside Alembic. Migration `0003`:

1. adds `users.disabled_at`, canonical email checks, and canonical uniqueness;
2. preflights/reconciles the `teachers.user_id` association, makes it non-null and unique, bounds `teachers.email` to `VARCHAR(100)`, and synchronizes the denormalized email;
3. adds the nullable, digest-only `password_resets.delivery_claim_digest` lease version and its length check;
4. creates `browser_sessions` with foreign key, uniqueness, and expiry/user indexes;
5. creates `teacher_invitations` with digest-only columns, checks, and indexes;
6. adds a PostgreSQL partial unique index that prevents more than one unconsumed, unrevoked invitation for the same email digest; and
7. creates an append-only-by-privilege operator audit table with bounded actor/action/outcome fields and a domain-separated HMAC target reference.

The deployment runbook requires backup, legacy ASCII/collision preflight, migration application, configuration of a fresh `TEACHER_INVITE_HMAC_KEY`, removal of `TEACHER_ACCESS_CODE`, service restart, an operator invitation smoke test, and sign-in/session/reset-invalidation smoke tests. Existing JWTs intentionally fail after deployment because they have no corresponding server-side session row. Application rollback retains the additive identity/audit schema and blocks traffic until old JWTs are contained by signing-key rotation (or a full maximum-lifetime-plus-skew wait with issuance stopped), disabled identities are contained, and audit evidence is retained. Destructive schema retirement is a separate approved migration.

## Test strategy

All production behavior is introduced test-first. RED evidence must cover:

- a cryptographically valid JWT without a database session is rejected;
- active, revoked, expired, wrong-user, and disabled-user sessions behave correctly;
- two sessions coexist, logout revokes only the current one, and password reset/change/disable/delete revoke all;
- expired-session cleanup and concurrent revocation are idempotent;
- raw JWTs, raw `jti` values, invitation tokens, and invitee emails are absent from persistence and logs;
- password registration success, duplicates, invalid invitation cases, and admin-role attempts return the same HTTP 202 body and no cookies;
- teacher invitations are email-bound, expiring, one-time, digest-only, and atomically consumed under concurrency;
- shared access-code request fields are rejected and the setting/UI contract is absent;
- the operator CLI is the only creation path and prints the raw token once;
- explicit operator revocation and account disable/re-enable commands are transactional and reveal no identifiers;
- verified-provider teacher creation consumes the invitation bound to the provider email;
- the admin status endpoint is admin-only and disabling immediately invalidates every existing session;
- route inventory and public-route allowlist remain machine checked;
- frontend password registration does not fetch a session and displays the generic sign-in direction.

Focused backend and frontend suites run throughout RED/GREEN cycles. Before the commit, run the complete backend/frontend tests, Ruff, Bandit, ESLint, frontend build, dependency audits, secret scanners, policy checks, migration/source regressions, and an independent Critical/Important review. Critical and Important findings must be fixed test-first and independently re-reviewed before committing.

## Explicit non-goals and blockers

- The known upload traversal, static-mount privacy, asset ACL, and quota work belongs to the separate content/upload stack and is not changed here.
- Network egress enforcement remains a deployment prerequisite owned by the deployment stack.
- This slice does not add public invitation-management endpoints, invitation emails, a new admin UI, Redis, refresh tokens, or a full email-verification registration workflow. Password registration therefore remains a deployment blocker until production disables it in favor of verified school SSO or adds generic pending email/roster verification before account activation.
- No branch push or pull request is authorized for this subtask.
