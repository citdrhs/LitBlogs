# Fresh Production Password Authentication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a production-safe password-first LitBlog deployment with verified school email accounts, optional future OAuth providers, a truthful fresh-server admission path, a one-time administrator bootstrap, a concise Ubuntu 24.04.4 guide, and matching Help media.

**Architecture:** Preserve the existing generic-registration and isolated-worker security patterns. Add explicit provider flags, a dedicated verification outbox and token domain, and a reusable authentication-email worker while keeping password-reset and verification state separate. Keep `~/www` as the operator's source workspace and activate root-owned releases under `/opt/litblogs` through the existing Nginx/systemd boundary.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, PostgreSQL 17, Pydantic Settings, React/Vite, Vitest, Playwright, systemd, Nginx, ClamAV, Remotion, Node 24, Python 3.13.

---

### Task 1: Explicit authentication providers and truthful runtime readiness

**Files:**
- Modify: `litblogs/config.py`
- Modify: `litblogs/main.py`
- Modify: `litblogs/oauth_security.py`
- Modify: `litblogs/deployment_check.py`
- Modify: `litblogs/.env.example`
- Test: `litblogs/tests/test_deployment_readiness.py`
- Test: `litblogs/tests/test_oauth_security.py`
- Test: `litblogs/tests/test_identity_controls.py`

- [ ] **Step 1: Write failing configuration and preflight tests**

Add tests proving that production accepts password registration with both OAuth providers explicitly disabled, rejects malformed boolean strings, conditionally requires provider credentials, rejects a disabled provider before invoking its verifier, and allows preflight with the three upload readiness attestations false while postflight and normal settings loading reject them.

```python
def test_password_only_production_does_not_require_oauth(production_settings):
    settings = production_settings(
        LOCAL_PASSWORD_REGISTRATION_ENABLED="true",
        GOOGLE_OAUTH_ENABLED="false",
        MICROSOFT_OAUTH_ENABLED="false",
        GOOGLE_CLIENT_ID=None,
        MICROSOFT_CLIENT_ID=None,
        MICROSOFT_TENANT_ID=None,
        MICROSOFT_ALLOWED_TENANT_IDS=None,
    )
    assert settings.local_password_registration_enabled is True
    assert settings.google_oauth_enabled is False
    assert settings.microsoft_oauth_enabled is False


def test_preflight_skips_only_postmigration_attestations(production_environment):
    production_environment.update(
        UPLOAD_REGISTRY_SCHEMA_READY="false",
        UPLOAD_LEGACY_IMPORT_COMPLETE="false",
        UPLOAD_BACKUP_RESTORE_VERIFIED="false",
    )
    assert deployment_check.run(mode="preflight") == 0
    assert deployment_check.run(mode="postflight") == 1
```

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
python -m pytest litblogs/tests/test_deployment_readiness.py litblogs/tests/test_oauth_security.py litblogs/tests/test_identity_controls.py -q
```

Expected: failures because provider flags and runtime-readiness separation do not exist and production still rejects local registration.

- [ ] **Step 3: Implement explicit provider flags**

Add strict boolean fields and conditional production validation:

```python
google_oauth_enabled: bool = False
microsoft_oauth_enabled: bool = False

@field_validator(
    "local_password_registration_enabled",
    "google_oauth_enabled",
    "microsoft_oauth_enabled",
    mode="before",
)
@classmethod
def validate_authentication_flag(cls, value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value == "true":
        return True
    if value == "false":
        return False
    raise ValueError("authentication flags must be literal true or false")
```

Require Google and Microsoft identifiers only when their explicit flags are true. Remove the production prohibition on local registration; Task 4 will bind it to verification. Return explicit provider booleans from `/api/runtime-config`, blank identifiers for disabled providers, and fail closed in disabled OAuth endpoints before parsing tokens or making network calls.

- [ ] **Step 4: Split runtime readiness from configuration validity**

Create:

```python
def require_production_runtime_readiness(settings: Settings) -> Settings:
    if settings.app_env != "production":
        return settings
    required = {
        "UPLOAD_REGISTRY_SCHEMA_READY": settings.upload_registry_schema_ready,
        "UPLOAD_LEGACY_IMPORT_COMPLETE": settings.upload_legacy_import_complete,
        "UPLOAD_BACKUP_RESTORE_VERIFIED": settings.upload_backup_restore_verified,
    }
    missing = [name for name, ready in required.items() if not ready]
    if missing:
        raise ValueError(f"Missing production readiness attestation: {missing[0]}")
    return settings
```

Make normal `load_settings()` enforce it. Make `deployment_check --preflight` load validated settings without this one post-migration gate; make postflight call it before database checks. Do not weaken secret, HTTPS, CA, upload-custody, scanner, SMTP, or provider validation.

- [ ] **Step 5: Verify GREEN and commit**

Run the focused tests, then:

```bash
git add litblogs/config.py litblogs/main.py litblogs/oauth_security.py litblogs/deployment_check.py litblogs/.env.example litblogs/tests
git commit -m "feat(auth): support explicit production sign-in providers"
```

### Task 2: Email verification schema and exact PostgreSQL privileges

**Files:**
- Modify: `litblogs/models.py`
- Create: `litblogs/migrations/versions/a82f8f2b1d7c_email_verification.py`
- Modify: `litblogs/migrations/env.py`
- Modify: `litblogs/runtime_database_identity.py`
- Modify: `litblogs/password_reset_delivery.py`
- Modify: `deploy/README.md`
- Modify: `docs/operations/production-runbook.md`
- Modify: `litblogs/migrations/README-identity-controls.md`
- Modify: `deploy/scripts/restore_verify_postgres.py`
- Test: `litblogs/tests/test_migration_stack.py`
- Test: `litblogs/tests/test_database_isolation.py`
- Test: `litblogs/tests/test_coupled_backup_restore.py`
- Test: `litblogs/tests/test_operational_controls.py`

- [ ] **Step 1: Write failing migration and model tests**

Assert that `users.email_verified_at` exists, `email_verifications` has one row per user, digest/status constraints match the password-reset safety contract, the current revision advances from `f1ad78b2035f`, exact runtime ACLs include only required CRUD/sequence privileges, and backup/restore inventory includes the new table and sequence.

- [ ] **Step 2: Run tests and verify RED**

```bash
python -m pytest litblogs/tests/test_migration_stack.py litblogs/tests/test_database_isolation.py litblogs/tests/test_coupled_backup_restore.py -q
```

Expected: missing column/table/revision/inventory assertions.

- [ ] **Step 3: Add the model and migration**

Model shape:

```python
class EmailVerification(Base):
    __tablename__ = "email_verifications"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    token_digest = Column(String(64), unique=True, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    delivery_status = Column(String(16), nullable=False)
    delivery_attempted_at = Column(DateTime(timezone=True), nullable=True)
    delivery_claim_digest = Column(String(64), nullable=True)
```

Add constrained lowercase-hex digests and valid delivery-state checks. Add `users.email_verified_at TIMESTAMPTZ NULL`, backfill existing users to migration time, then keep the column nullable for pending local accounts. Grant the runtime only the exact DML and sequence privileges required by registration, worker claims, verification, and invalidation. Preserve identity-owner and operator SECURITY DEFINER boundaries.

- [ ] **Step 4: Update exact inventories and verify GREEN**

Update schema-head constants, table/sequence inventories, runtime identity checks, and backup/restore verification. Run focused tests and commit:

```bash
git add litblogs/models.py litblogs/migrations litblogs/runtime_database_identity.py deploy/scripts/restore_verify_postgres.py litblogs/tests
git commit -m "feat(auth): add email verification persistence"
```

### Task 3: Asynchronous verification delivery

**Files:**
- Create: `litblogs/email_verification_delivery.py`
- Create: `litblogs/auth_email_job.py`
- Modify: `litblogs/password_reset_delivery.py`
- Modify: `deploy/systemd/litblogs-password-reset.service`
- Modify: `deploy/systemd/litblogs-password-reset.timer`
- Modify: `litblogs/deployment_check.py`
- Test: `litblogs/tests/test_email_verification_delivery.py`
- Test: `litblogs/tests/test_password_reset_delivery.py`
- Test: `litblogs/tests/test_maintenance_jobs.py`

- [ ] **Step 1: Write failing delivery tests**

Cover one claimant under concurrency, stale-claim recovery after 120 seconds, token creation only inside the worker, domain-separated digest storage after successful SMTP, 24-hour expiry, failure state without token persistence, disabled-account refusal, lost-claim compare-and-swap, and absence of tokens/emails/SMTP secrets in logs and exceptions.

- [ ] **Step 2: Verify RED**

```bash
python -m pytest litblogs/tests/test_email_verification_delivery.py litblogs/tests/test_password_reset_delivery.py litblogs/tests/test_maintenance_jobs.py -q
```

Expected: the verification delivery module and neutral auth-email job are missing.

- [ ] **Step 3: Implement separate verification semantics with shared plumbing**

Use separate constants and token domain:

```python
EMAIL_VERIFICATION_LIFETIME = timedelta(hours=24)
EMAIL_VERIFICATION_RESEND_COOLDOWN = timedelta(minutes=5)

def email_verification_token_digest(raw_token: str) -> str:
    return hashlib.sha256(f"litblogs-email-verification-v1:{raw_token}".encode()).hexdigest()
```

Extract only neutral SMTP connection and bounded batch plumbing from password reset. Keep query filters, claim functions, token digests, templates, completion updates, and tables separate. The neutral systemd job dispatches one bounded password-reset batch and one bounded verification batch using the same protected SMTP/runtime database environment.

- [ ] **Step 4: Verify GREEN and commit**

```bash
git add litblogs/email_verification_delivery.py litblogs/auth_email_job.py litblogs/password_reset_delivery.py deploy/systemd litblogs/deployment_check.py litblogs/tests
git commit -m "feat(auth): deliver verification email asynchronously"
```

### Task 4: Registration, verification, resend, and login enforcement

**Files:**
- Modify: `litblogs/main.py`
- Modify: `litblogs/schemas.py`
- Modify: `litblogs/identity_controls.py`
- Modify: `litblogs/config.py`
- Test: `litblogs/tests/test_identity_controls.py`
- Test: `litblogs/tests/test_session_security.py`
- Test: `litblogs/tests/test_auth_security.py`

- [ ] **Step 1: Write failing API/security tests**

Test generic registration across success, duplicate email/username, denied domain, invalid teacher invite, disabled registration, and forbidden ADMIN role; one account/outbox under concurrent requests; generic resend behavior and cooldown; valid/expired/replayed/concurrent verification; no session before verification; session after verification; no password reset for pending accounts; disablement invalidation; and second verification checks during row-locked session issuance.

- [ ] **Step 2: Verify RED**

```bash
python -m pytest litblogs/tests/test_identity_controls.py litblogs/tests/test_session_security.py litblogs/tests/test_auth_security.py -q
```

- [ ] **Step 3: Implement API behavior**

Use responses:

```python
REGISTRATION_ACCEPTED_RESPONSE = {
    "message": "If registration can be completed, verification instructions will be sent."
}
RESEND_ACCEPTED_RESPONSE = {
    "message": "If the account can be verified, verification instructions will be sent."
}
INVALID_VERIFICATION_DETAIL = "Invalid or expired verification link"
```

Eligible local registration creates the user with `email_verified_at=None` and a pending verification row in one transaction. Resend requeues only active unverified local accounts after cooldown while returning the same `202` for every input. Verification atomically sets the timestamp and invalidates the row. OAuth creation sets the timestamp only after verified provider claims.

Login must still verify the supplied password against a real or dummy hash before rejecting an unverified user. Include `email_verified_at IS NOT NULL` in the session issuance lock predicate and current-user validity checks. Extend both Python and operator disable paths to invalidate verification rows.

- [ ] **Step 4: Bind production local registration to verification**

Production `LOCAL_PASSWORD_REGISTRATION_ENABLED=true` is valid only when authenticated SMTP and the verification worker are enabled. There is no production opt-out for verification.

- [ ] **Step 5: Verify GREEN and commit**

```bash
git add litblogs/main.py litblogs/schemas.py litblogs/identity_controls.py litblogs/config.py litblogs/tests
git commit -m "feat(auth): require verified email for password sessions"
```

### Task 5: Frontend provider flags and verification experience

**Files:**
- Create: `litblogs/src/VerifyEmail.jsx`
- Create: `litblogs/src/utils/verificationToken.js`
- Create: `litblogs/src/utils/verificationToken.test.js`
- Modify: `litblogs/src/bootstrap.js`
- Modify: `litblogs/src/App.jsx`
- Modify: `litblogs/src/Sign-up.jsx`
- Modify: `litblogs/src/Sign-in.jsx`
- Modify: `litblogs/src/config/runtimeConfig.js`
- Modify: `litblogs/src/config/registrationConfig.js`
- Modify: `litblogs/src/config/msalConfig.js`
- Modify: `litblogs/src/main.jsx`
- Test: `litblogs/src/SignupIdentityControls.test.jsx`
- Test: `litblogs/src/OAuthConfigFailClosed.test.jsx`
- Test: `litblogs/src/config/*.test.js`

- [ ] **Step 1: Write failing frontend tests**

Cover production runtime password registration, disabled providers hidden despite stale identifiers, disabled Microsoft avoiding MSAL initialization, signup's check-email state, fragment capture/removal before React, verification success/error/replay UI, resend generic response, and no token persistence or console output.

- [ ] **Step 2: Verify RED**

```bash
npm --prefix litblogs run test:run -- src/SignupIdentityControls.test.jsx src/OAuthConfigFailClosed.test.jsx src/config src/utils/verificationToken.test.js
```

- [ ] **Step 3: Implement runtime/provider behavior**

Trust the same-origin backend's validated runtime flag in production. Require both an explicit provider-enabled boolean and a valid public identifier before rendering or initializing OAuth. Keep password sign-in visible for existing users even if registration is later turned off.

- [ ] **Step 4: Implement safe token bootstrap and page**

Follow the password-reset fragment pattern:

```javascript
export const captureEmailVerificationTokenAtBootstrap = () => {
  const params = new URLSearchParams(window.location.hash.replace(/^#/, ""));
  const token = params.get("token") || "";
  if (token) window.history.replaceState({}, "", window.location.pathname + window.location.search);
  verificationToken = token;
};
```

Keep the token only in module memory, consume it once, clear it after success or terminal error, and never write it to storage, URLs, logs, analytics, or error text.

- [ ] **Step 5: Verify GREEN and commit**

```bash
git add litblogs/src
git commit -m "feat(auth): add email verification experience"
```

### Task 6: One-time administrator bootstrap

**Files:**
- Create: `litblogs/bootstrap_admin.py`
- Modify: `litblogs/deployment_check.py`
- Test: `litblogs/tests/test_bootstrap_admin.py`
- Test: `litblogs/tests/test_deployment_readiness.py`

- [ ] **Step 1: Write failing operator tests**

Test exact confirmation flag, empty database success, nonempty refusal, wrong runtime role/schema refusal, concurrent execution yielding exactly one administrator, allowed-domain validation, password policy, verified timestamp, no argv password, and non-reflective output.

- [ ] **Step 2: Verify RED**

```bash
python -m pytest litblogs/tests/test_bootstrap_admin.py litblogs/tests/test_deployment_readiness.py -q
```

- [ ] **Step 3: Implement the command**

The CLI accepts only `--confirm-empty-install`. It loads the protected production environment, verifies runtime database identity and migration head, takes a PostgreSQL transaction advisory lock, locks/inspects users, and fails if any row exists. Prompt username/email/password/confirmation through `input`/`getpass`, normalize email, enforce school domain and the existing password policy, and insert:

```python
models.User(
    username=username,
    email=email,
    password=hash_password(password),
    role=models.UserRole.ADMIN,
    is_admin=True,
    email_verified_at=_utc_now_naive(),
)
```

Output only `bootstrap-admin: created` or bounded reason codes.

- [ ] **Step 4: Verify GREEN and commit**

```bash
git add litblogs/bootstrap_admin.py litblogs/deployment_check.py litblogs/tests
git commit -m "feat(ops): add one-time administrator bootstrap"
```

### Task 7: Concise Ubuntu 24.04.4 fresh-server guide

**Files:**
- Create: `deploy/FRESH_SERVER_SETUP.md`
- Modify: `deploy/README.md`
- Modify: `README.md`
- Test: `litblogs/tests/test_deployment_readiness.py`
- Test: `litblogs/tests/test_repository_policy.py`

- [ ] **Step 1: Write failing documentation-contract tests**

Assert that the guide names Ubuntu 24.04.4, Python 3.13, Node 24, PostgreSQL 17, Nginx, ClamAV, Certbot/TLS, `~/www` staging, `/opt/litblogs` runtime, PostgreSQL TLS/SCRAM roles, protected environment paths, verification worker, fresh Alembic migration, coupled backup/restore before readiness flags, administrator bootstrap, systemd/Nginx activation, smoke checks, and future Google enablement. Reject literal example secrets and instructions to run Vite dev/preview in production.

- [ ] **Step 2: Verify RED**

```bash
python -m pytest litblogs/tests/test_deployment_readiness.py litblogs/tests/test_repository_policy.py -q
```

- [ ] **Step 3: Write the guide**

Use eight short numbered sections and copy-paste blocks. Define site values once. Start the source workflow with:

```bash
sudo -iu litblogs
mkdir -p ~/www
cd ~/www
git clone https://github.com/citdrhs/LitBlogs.git
cd LitBlogs
git switch main
git pull --ff-only
```

Explain that `~/www` is staging only because the shipped service has `ProtectHome=true`. Package a root-owned candidate under `/opt/litblogs/releases`, generate `RELEASE-MANIFEST`, install hash-locked binary Python dependencies, and use the checked-in release switcher. Provide exact PostgreSQL 17 TLS/SCRAM setup, roles, migration membership grant/revoke, ClamAV loopback configuration, environment template, truthful preflight/postflight order, empty backup/restore rehearsal, admin bootstrap, Nginx/TLS/systemd setup, and health/cache/range checks.

Use variables such as `YOUR_REAL_HOST` only in explanatory templates and add a mandatory search command that fails until every placeholder is replaced.

- [ ] **Step 4: Verify GREEN and commit**

```bash
git add deploy/FRESH_SERVER_SETUP.md deploy/README.md README.md litblogs/tests
git commit -m "docs(deploy): add fresh Ubuntu production guide"
```

### Task 8: Help, FAQ, and tutorial synchronization

**Files:**
- Modify: `litblogs/src/components/FAQ.jsx`
- Modify: `litblogs/src/components/FAQ.test.jsx`
- Modify: `media/tutorial-video/src/manifest.js`
- Modify: `media/tutorial-video/src/TutorialVideo.jsx`
- Modify: `media/tutorial-video/src/styles.css`
- Modify: `media/tutorial-video/tests/*.test.mjs`
- Regenerate: `litblogs/src/assets/tutorial/litblogs-tutorial.mp4`
- Regenerate: `litblogs/src/assets/tutorial/litblogs-tutorial.en.vtt`
- Regenerate: `litblogs/src/assets/tutorial/litblogs-tutorial-transcript.txt`
- Regenerate: `litblogs/src/assets/tutorial/litblogs-tutorial-poster.jpg`

- [ ] **Step 1: Write failing source/media tests**

Assert that signup instructions include email verification, scene duration never trails narration by more than a short closing beat, cursor clicks hold target coordinates through the pulse, no nested accidental `durationInFrames` props clip scenes, captions stay within duration, and poster/transcript duration labels match the manifest.

- [ ] **Step 2: Verify RED**

```bash
npm --prefix litblogs run test:run -- src/components/FAQ.test.jsx
npm --prefix media/tutorial-video test
```

- [ ] **Step 3: Retiming and cursor implementation**

For every click keyframe, create an implicit 12-frame hold at the same coordinates before movement resumes. Make the pulse begin at the click frame and fade forward rather than symmetrically appearing after the cursor has departed. Set each scene end to the later of (a) measured narration duration plus 24 frames and (b) its final required action plus 18 frames, then proportionally retime camera, capture, cursor, and callout keyframes into that bounded duration. Update signup narration to tell users to open the verification email before sign-in.

- [ ] **Step 4: Regenerate and validate media**

```bash
npm --prefix media/tutorial-video run voice
npm --prefix media/tutorial-video run music
npm --prefix media/tutorial-video run accessibility/export
npm --prefix media/tutorial-video run poster/stills
npm --prefix media/tutorial-video run render
npm --prefix media/tutorial-video run validate
```

Inspect frames at every click, scene boundary, and final verification result. Confirm H.264/AAC, 1280x720, 30 fps, fast-start, under 120 seconds, under 20 MB, captions within bounds, and no blank/clipped frames.

- [ ] **Step 5: Verify GREEN and commit**

```bash
git add litblogs/src/components litblogs/src/assets/tutorial media/tutorial-video
git commit -m "docs(help): add verified-email tutorial flow"
```

### Task 9: End-to-end verification and delivery

**Files:**
- Modify: `litblogs/e2e/specs/release-journey.spec.js`

- [ ] **Step 1: Add the production-shaped browser journey**

Add a disposable PostgreSQL/mail-catcher test for register -> capture verification fragment -> verify -> sign in. Assert password-only runtime configuration has no OAuth controls and pre-verification login creates no cookies.

- [ ] **Step 2: Run all local gates**

```bash
python -m pytest litblogs/tests -q
npm --prefix litblogs run test:run
npm --prefix litblogs run lint
npm --prefix litblogs run build
python -m ruff check litblogs
python scripts/run-backend-bandit.py
python scripts/check-generic-secrets.py
python scripts/validate-repository-policy.py
npm --prefix media/tutorial-video test
npm --prefix media/tutorial-video run validate
npm --prefix litblogs run test:e2e
git diff --check
```

Expected: every command exits zero; existing bounded warnings may remain only where already documented.

- [ ] **Step 3: Independent code and spec review**

Compare the branch against `origin/main`, verify every design requirement has direct test or runtime evidence, and resolve every actionable finding.

- [ ] **Step 4: Push and open/update the pull request**

```bash
git push -u origin codex/fresh-production-setup
```

Create one pull request into `main`, then wait for CI and CodeQL. If any job fails, inspect the exact logs, implement the tested fix, push, and wait again until all required checks pass.
