# Security Policy

## Supported versions

The latest LitBlog release and the current `main` branch receive security fixes. Unsupported deployments should be upgraded before requesting a patch.

## Report vulnerabilities privately

Do not open a public issue. Submit a [private repository security advisory](https://github.com/citdrhs/LitBlogs/security/advisories/new) so the maintainers can investigate without exposing students, teachers, systems, or credentials.

Include a concise description, affected feature, sanitized reproduction steps, likely impact, and the version or commit tested. Use synthetic accounts and values. Do not attach logs, database exports, screenshots, or requests containing personally identifiable information (PII). If a minimal redacted excerpt is essential, remove names, email addresses, school identifiers, tokens, cookies, hostnames, and other identifying values first.

Report issues such as:

- authentication or authorization bypasses;
- cross-user exposure of student, teacher, or administrator data;
- injection, cross-site scripting, unsafe file/media handling, or request forgery;
- exposed secrets, tokens, private keys, or production configuration; and
- security control or deployment misconfiguration.

## Identity operations

Teacher provisioning uses one-time, email-bound, expiring invitations issued only by
the reviewed host-side operator command. Never create an invitation through an API,
reuse an invitation, share one across teachers, or paste a raw invitation into logs or
tickets. The raw value is shown once; only digests are stored.

Authentication cookies are accepted only while a corresponding digest-only server
session is active. Account disablement, password changes/resets, and account deletion
must revoke all active sessions transactionally. Operators must use the explicit
`manage_accounts` command for emergency disable/re-enable actions and preserve the
school’s approved administrative audit. Each command persists actor/action/outcome and
a domain-separated HMAC target reference in the same transaction; audit failure must
roll back the privileged change. Raw emails, invitations, and session identifiers are
never audit fields. The authenticated admin account-status route follows the same
transactional rule and identifies its actor by the authenticated administrator's
internal user ID, never by an untrusted request field.

Account disablement and a successful password change must also invalidate all queued
and delivered password-reset state in the same transaction. Reset queueing, delivery,
and consumption lock and recheck the enabled account before changing state. Delivery
reclaims use a digest-only random claim nonce and compare-and-swap completion; stale
workers cannot complete a newer lease. School
email identities are ASCII-only, remove only U+0020 edge padding, reject all remaining
spaces and C0/DEL control characters, and are stored lowercase. PostgreSQL uses ASCII
`translate(btrim(email), ...)` and `COLLATE "C"`, never locale-sensitive `lower()`, so
application normalization and uniqueness cannot
diverge. `teachers.user_id` is the unique canonical teacher/account association.
Account deletion locks the user row before session, reset, or content children.
Migration invalidates every pre-existing reset link, and runtime accepts only the
SHA-256 token digest representation—there is no plaintext legacy fallback.

Password registration does not verify mailbox control in this identity slice. A
production deployment must disable it in favor of verified school SSO or require a
reviewed pending-email/roster verification step before account activation.

Identity operator CLIs run from a minimal purpose-specific config delivered on a
protected inherited file descriptor. They do not load the web application Settings or
SessionLocal and must not inherit JWT, provider, SMTP, VAPID, or admin secrets. Each
config uses a separate least-privilege PostgreSQL role with verify-full TLS; the CLI
hard-binds purpose to the reviewed role and checks PostgreSQL `current_user`, dangerous
role flags/memberships, schema CREATE, direct table/sequence privileges, and exact
function EXECUTE grants before any privileged work. Operator roles have no direct DML;
fixed-search-path SECURITY DEFINER routines perform each state transition and audit
write atomically. The CA is the exact root-owned
`/etc/litblogs/postgres-root-ca.pem`, with an entirely root-owned, non-writable ancestor
chain.

An emergency application rollback must retain the additive session, invitation,
disabled-account, canonical-email, and audit schema. Traffic remains blocked until the
JWT signing key is rotated (or issuance is stopped for the full token lifetime plus
clock skew), disabled identities are contained outside any older application that
ignores them, and audit evidence is exported and retained.

## Suspected credential exposure or incident

Treat a suspected disclosure as an incident. Stop using and sharing the affected value, preserve only sanitized evidence, notify the maintainers through the private advisory, and rotate or revoke the credential through its issuing system. Removing a value from Git does not invalidate it. Maintainers should review access logs through an approved private channel, assess affected data and users, document containment and recovery, and follow applicable school or organizational incident procedures.

## Responsible disclosure

Allow reasonable time for triage, remediation, credential rotation, and coordinated notification before public disclosure. The maintainers will use the private advisory to acknowledge the report and coordinate next steps.
