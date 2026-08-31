# Fresh Production Setup and Password Authentication Design

## Goal

Provide a concise, copy-paste-oriented Ubuntu 24.04.4 LTS guide for a brand-new LitBlog production server with no data migration. The initial deployment uses verified school email/password accounts. Google and Microsoft SSO remain disabled until approved, but can later be enabled through environment configuration without rebuilding the frontend or locking out existing password users.

## Decisions

- Add `deploy/FRESH_SERVER_SETUP.md`; keep the detailed production runbook as the reference for ongoing operations.
- Use `~/www/LitBlogs` only as the interactive `litblogs` user's clone/build workspace. Package each release into a root-owned `/opt/litblogs/releases/litblogs-<commit>` tree because the checked-in Nginx and systemd policies intentionally cannot execute from a home directory.
- Target Python 3.13, Node 24, PostgreSQL 17, Nginx, ClamAV over loopback TCP, systemd, and HTTPS on Ubuntu 24.04.4 LTS.
- Permit production password self-registration only with mandatory email verification and an allowed school email domain.
- Add explicit `GOOGLE_OAUTH_ENABLED` and `MICROSOFT_OAUTH_ENABLED` flags. Disabled providers require no credentials, expose no frontend button, and reject their backend endpoints before token parsing.
- Preserve password login independently from self-registration so registration can later be disabled without locking out existing accounts.
- Do not automatically merge a password account with a future Google identity based only on matching email. Account linking requires a separate authenticated ceremony or reviewed school mapping.

## Authentication Configuration

The initial production environment uses:

```text
LOCAL_PASSWORD_REGISTRATION_ENABLED=true
GOOGLE_OAUTH_ENABLED=false
MICROSOFT_OAUTH_ENABLED=false
```

Production validation requires at least one usable sign-up method. Google credentials are required and validated only when Google is enabled. Microsoft client and tenant values are required and validated only when Microsoft is enabled. Runtime configuration publishes explicit provider states and only the public identifiers for enabled providers.

After county approval, Google can be introduced by setting `GOOGLE_OAUTH_ENABLED=true` and adding the approved client ID. Password login remains available. Operators may later stop new password registrations by setting `LOCAL_PASSWORD_REGISTRATION_ENABLED=false`.

## Email Verification

Add `users.email_verified_at` and a dedicated `email_verifications` outbox table. Existing accounts are backfilled as verified during upgrade; a fresh database has no rows to backfill. Google and Microsoft accounts are marked verified only after the existing provider claim verification succeeds.

Password registration keeps its enumeration-safe generic `202` response. An eligible registration atomically creates an unverified account and a pending verification-delivery row. It never creates a session. A dedicated verification record is used instead of overloading password-reset rows, keeping token purposes separate.

The existing isolated SMTP worker is generalized into an authentication-email worker that services password-reset and email-verification queues with separate claim, token, template, and completion logic. Verification tokens use 256 bits of randomness, are stored only as domain-separated digests after successful delivery, expire after 24 hours, and travel in a URL fragment that the browser removes before React renders. Failed delivery does not verify the account.

Endpoints:

- `POST /api/auth/register`: generic accepted response and pending verification.
- `POST /api/auth/resend-verification`: generic accepted response, five-minute cooldown, prior-token invalidation.
- `POST /api/auth/verify-email`: single-use token consumption with a generic invalid/expired error.

Password login performs the normal real-or-dummy password verification and refuses unverified users with the same generic invalid-credentials response used for unknown, disabled, or wrong-password accounts. Session issuance rechecks verification while holding the account row lock. Password resets ignore unverified accounts. Disabling an account invalidates its verification token.

The frontend captures the verification fragment at bootstrap, clears browser history, posts the token from a dedicated verification page, and provides bounded resend guidance. Signup confirmation tells the user to check their school email before signing in.

## First Administrator

Add a one-time `bootstrap_admin.py` operator command. It is available only after migrations and postflight on a database with no users. It requires an explicit empty-install confirmation, takes a transaction-scoped advisory lock, verifies database identity and schema head, privately prompts for username, school email, and password, and atomically creates one active, verified administrator. It never accepts a password in command arguments and permanently refuses reuse after any user exists.

No public bootstrap endpoint or reusable admin access code is added.

## Truthful Deployment Admission

The current preflight is circular because it requires upload schema, legacy import, and backup/restore attestations that cannot truthfully be complete before migrations. Move those three post-migration attestations into a runtime-readiness validator.

- `deployment_check --preflight` validates the artifact, Python version, production configuration, PostgreSQL CA custody, upload path, scanner configuration, and all other safety rules while allowing the three readiness flags to remain false.
- Normal application settings and postflight continue to require all three flags true.
- The guide orders work as: preflight, fresh migration, empty-upload proof, coupled backup/restore rehearsal, set readiness flags true, postflight, bootstrap administrator, start services.

## Fresh Server Guide

`deploy/FRESH_SERVER_SETUP.md` is organized into short numbered sections:

1. Fill in a small variable checklist: real hostname, school email domain, repository URL, SMTP values, and protected passwords.
2. Install supported Ubuntu packages and exact Python, Node, and PostgreSQL versions.
3. Create service/storage/config directories with verified ownership and modes.
4. Clone `main` under `~/www`, run tests/build, and assemble a root-owned release under `/opt/litblogs` with `RELEASE-MANIFEST`.
5. Configure local PostgreSQL 17 with TLS, SCRAM, least-privilege roles, and the fresh database.
6. Configure ClamAV, the production environment, SMTP, upload storage, migrations, backup/restore evidence, and the first administrator.
7. Install the checked-in systemd and edited Nginx configuration, obtain/attach the real TLS certificate, and start the app.
8. Run exact local and HTTPS health, service, port, cache, MIME, and range-request checks.

The guide does not include legacy migration/adoption steps. It links to the detailed runbook for future releases, backups, rollback, worker egress, and incident response. Placeholders are visually obvious, never valid production values, and are defined once rather than repeated throughout the guide.

## Help Content

Update signup instructions, FAQ text, transcript, captions, and tutorial narration so the public help flow says to verify the school email before signing in. Re-render the tutorial after its earlier timing/cursor corrections: scenes end shortly after narration, click targets hold through their pulse, and no scene is clipped by accidental duration props.

## Testing and Verification

Add unit, integration, migration, and E2E coverage for:

- password-only production configuration with no OAuth credentials;
- explicit provider enablement and disabled-endpoint rejection;
- generic registration/resend responses and concurrency;
- verification delivery, expiry, replay, cooldown, and failure behavior;
- login/session blocking before verification and success afterward;
- disablement invalidation and password-reset exclusion;
- exact PostgreSQL schema/ACL/backup inventory;
- one-time administrator bootstrap and concurrent refusal;
- truthful preflight versus strict postflight;
- production frontend signup, verification page, and provider visibility;
- the complete register, verify, sign-in browser journey;
- the Ubuntu guide's commands, placeholders, paths, and required environment keys;
- FAQ/tutorial source, exported captions/transcript, rendered video integrity, and visual review.

Run the complete frontend, backend, migration/deployment, media, lint, build, security, and browser suites before pushing. Push the branch and wait for CI and CodeQL to finish.
