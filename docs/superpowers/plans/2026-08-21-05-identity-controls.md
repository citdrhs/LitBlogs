# Enterprise Identity Controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add digest-only server-side browser sessions, transactional account lifecycle revocation, email-bound one-time teacher invitations, and a generic no-auto-login password-registration contract.

**Architecture:** Preserve signed JWT cookies and bearer tokens, but require each JWT `jti` digest to match an active database session on every request. Put session and invitation primitives in a focused `identity_controls.py` module, keep routes as transaction coordinators, and expose privileged identity operations through default-deny API/explicit non-public CLIs. Teacher invitations store only token SHA-256 and domain-separated email HMAC digests.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy, PostgreSQL/SQLite test database, Pydantic, PyJWT, React, Axios, Vitest, Pytest.

**Execution constraint:** The parent requested one new final implementation commit from `753d957`; do not make intermediate commits, amend, push, or open a pull request. Preserve RED/GREEN command output as evidence at each task boundary.

---

## File map

- Create `litblogs/identity_controls.py`: digest-only session and teacher-invitation persistence primitives.
- Create `litblogs/manage_teacher_invitations.py`: operator-only create/revoke commands.
- Create `litblogs/manage_accounts.py`: operator-only disable/enable commands.
- Create `litblogs/tests/test_identity_controls.py`: abuse, race, persistence, CLI, and lifecycle tests.
- Create `litblogs/migrations/0003_add_identity_controls.sql`: additive production migration.
- Create `litblogs/migrations/README-identity-controls.md`: apply, smoke-test, and rollback runbook.
- Modify `litblogs/models.py`: `User.disabled_at`, `BrowserSession`, and `TeacherInvitation`.
- Modify `litblogs/config.py` and `litblogs/.env.example`: dedicated invite HMAC key; remove teacher shared code.
- Modify `litblogs/schemas.py`: strict invitation field and lifecycle request schemas.
- Modify `litblogs/main.py`: persisted-session auth, lifecycle routes, generic registration, and atomic OAuth invitation use.
- Modify `litblogs/access_control.py`: inventory new protected routes without changing the public allowlist.
- Modify backend tests that currently mint stateless JWTs or assert shared-code/auto-login behavior.
- Modify `litblogs/src/Sign-up.jsx` and focused frontend tests: invitation naming and generic sign-in direction.
- Modify `litblogs/src/PrivacyPolicy.jsx`, `README.md`, `SECURITY.md`, and migration docs for the new operator/deployment contract.

### Task 1: Lock persistence and configuration contracts with RED tests

**Files:**
- Create: `litblogs/tests/test_identity_controls.py`
- Modify: `litblogs/tests/conftest.py`
- Modify: `litblogs/tests/test_auth_security.py`
- Modify: `litblogs/models.py`
- Modify: `litblogs/config.py`

- [ ] **Step 1: Write failing model and configuration tests**

Add tests that express the desired model without importing any future implementation helper:

```python
def test_identity_models_store_only_digests():
    assert set(models.BrowserSession.__table__.columns.keys()) == {
        "id", "jti_digest", "user_id", "created_at", "expires_at", "revoked_at"
    }
    assert set(models.TeacherInvitation.__table__.columns.keys()) == {
        "id", "token_digest", "email_digest", "created_at", "expires_at",
        "consumed_at", "revoked_at", "created_by",
    }
    forbidden = {"token", "jti", "email", "raw_token", "session_token"}
    assert forbidden.isdisjoint(models.BrowserSession.__table__.columns.keys())
    assert forbidden.isdisjoint(models.TeacherInvitation.__table__.columns.keys())


def test_production_requires_dedicated_invitation_hmac_key(production_settings_kwargs):
    kwargs = production_settings_kwargs()
    kwargs.pop("teacher_invite_hmac_key", None)
    with pytest.raises(ValueError, match="TEACHER_INVITE_HMAC_KEY"):
        Settings(**kwargs)


def test_invitation_hmac_key_must_differ_from_jwt_key(production_settings_kwargs):
    kwargs = production_settings_kwargs()
    kwargs["teacher_invite_hmac_key"] = kwargs["secret_key"]
    with pytest.raises(ValueError, match="must differ"):
        Settings(**kwargs)


def test_shared_teacher_access_code_is_not_a_setting():
    assert "teacher_access_code" not in Settings.model_fields
```

Update the test environment to set `TEACHER_INVITE_HMAC_KEY=test-only-teacher-invite-hmac-key-` plus at least 32 random-looking bytes and remove `TEACHER_ACCESS_CODE`.

- [ ] **Step 2: Run the focused tests and record RED**

Run:

```powershell
Set-Location litblogs
python -m pytest tests/test_identity_controls.py tests/test_auth_security.py -q
```

Expected: failures because the two models, `disabled_at`, and `teacher_invite_hmac_key` do not exist and `teacher_access_code` still does.

- [ ] **Step 3: Add the minimal persistence and configuration model**

Add `User.disabled_at` and relationships with cascade behavior. Define digest-only models with strict lengths and constraints:

```python
class BrowserSession(Base):
    __tablename__ = "browser_sessions"
    id = Column(Integer, primary_key=True)
    jti_digest = Column(String(64), nullable=False, unique=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    user = relationship("User", back_populates="browser_sessions")
    __table_args__ = (CheckConstraint("length(jti_digest) = 64", name="ck_browser_session_jti_digest"),)


class TeacherInvitation(Base):
    __tablename__ = "teacher_invitations"
    id = Column(Integer, primary_key=True)
    token_digest = Column(String(64), nullable=False, unique=True, index=True)
    email_digest = Column(String(64), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    consumed_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(String(100), nullable=False)
    __table_args__ = (
        CheckConstraint("length(token_digest) = 64", name="ck_teacher_invitation_token_digest"),
        CheckConstraint("length(email_digest) = 64", name="ck_teacher_invitation_email_digest"),
        Index(
            "uq_teacher_invitation_active_email",
            "email_digest",
            unique=True,
            sqlite_where=and_(consumed_at.is_(None), revoked_at.is_(None)),
            postgresql_where=and_(consumed_at.is_(None), revoked_at.is_(None)),
        ),
    )
```

Replace `teacher_access_code` with `teacher_invite_hmac_key: SecretStr | None`, require at least 32 UTF-8 bytes in production, reject placeholder/low-diversity values, and reject equality with `SECRET_KEY` using `hmac.compare_digest` on bytes. Keep `ADMIN_ACCESS_CODE` unchanged because admin registration is not part of this slice.

- [ ] **Step 4: Re-run the focused tests and keep them GREEN**

Run the same Pytest command. Expected: all new persistence/config tests pass; update only existing test fixtures whose shared teacher code expectations intentionally changed.

### Task 2: Build and prove digest-only identity primitives

**Files:**
- Create: `litblogs/identity_controls.py`
- Modify: `litblogs/tests/test_identity_controls.py`

- [ ] **Step 1: Write RED unit/integration tests for digest and transaction primitives**

Cover these exact public APIs: `IssuedBrowserSession(token: str, expires_at: datetime)`, `issue_browser_session(db, *, user_id, settings)`, `find_active_browser_session(db, *, user_id, jti, now=None)`, `revoke_session(db, *, session_id, now=None)`, `revoke_all_sessions(db, *, user_id, now=None)`, `delete_expired_sessions(db, *, now=None, limit=500)`, `create_teacher_invitation(db, *, email, created_by, expires_at, settings)`, `consume_teacher_invitation(db, *, token, email, settings, now=None)`, and `revoke_teacher_invitation(db, *, email, settings, now=None)`.

Assertions must prove:

- a valid JWT produces exactly one session row containing only a 64-character digest;
- `decode_access_token(token)["jti"]`, the raw JWT, raw invite token, and normalized email never appear in any persisted text column or captured log record;
- an active session matches only its own user/jti and expired/revoked sessions do not match;
- deleting expired rows leaves active and revoked-but-unexpired audit rows intact and never deletes more than `limit`;
- revocation is idempotent;
- invitation email normalization is ASCII-only, trim/lower stable, and domain separated;
- mismatched, expired, revoked, and replayed invitations return false;
- two database connections racing to consume one invite yield exactly one true result.

- [ ] **Step 2: Run RED and verify the failure is the missing module/API**

Run:

```powershell
python -m pytest tests/test_identity_controls.py -q
```

Expected: collection or assertion failures caused by missing `identity_controls` APIs, not fixture or database errors.

- [ ] **Step 3: Implement the minimal primitives**

Use SHA-256 for session/token digests and a domain-separated HMAC for email:

```python
INVITATION_EMAIL_DOMAIN = b"litblog:teacher-invite-email:v1\0"

def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

def normalize_email(value: str) -> str:
    normalized = value.strip(" ")
    if not normalized.isascii():
        raise ValueError("email must use ASCII characters")
    if any(character.isspace() for character in normalized):
        raise ValueError("email must not contain whitespace")
    return normalized.lower()

def invitation_email_digest(email: str, *, settings: Settings) -> str:
    key = settings.teacher_invite_hmac_key
    if key is None:
        raise RuntimeError("TEACHER_INVITE_HMAC_KEY is required")
    return hmac.new(
        key.get_secret_value().encode("utf-8"),
        INVITATION_EMAIL_DOMAIN + normalize_email(email).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
```

Generate invite tokens with `secrets.token_urlsafe(32)`. Decode the application-issued JWT to obtain its controlled `jti` and `exp`, persist only the digest, and return the token only to the route caller. Implement consume/revoke through one conditional SQLAlchemy update with `RETURNING`, with all eligibility predicates repeated in the update. Do not commit inside primitives; callers own transactions.

- [ ] **Step 4: Run focused GREEN tests**

Run `python -m pytest tests/test_identity_controls.py -q`. Expected: all primitive/race tests pass repeatedly.

### Task 3: Replace registration and shared teacher codes test-first

**Files:**
- Modify: `litblogs/tests/test_identity_controls.py`
- Modify: `litblogs/tests/test_session_security.py`
- Modify: `litblogs/tests/test_oauth_security.py`
- Modify: `litblogs/schemas.py`
- Modify: `litblogs/main.py`

- [ ] **Step 1: Write RED password-registration privacy tests**

Create a parameterized endpoint test that compares status, JSON, and `Set-Cookie` headers for successful student registration, duplicate email, duplicate username, ADMIN role, teacher missing/invalid/mismatched/expired/replayed invite, and successful teacher invite:

```python
EXPECTED_ACCEPTED = {
    "message": "If registration can be completed, sign in with the submitted credentials."
}

assert response.status_code == 202
assert response.json() == EXPECTED_ACCEPTED
assert response.headers.get_list("set-cookie") == []
```

Verify only valid student and valid teacher requests create users, only the valid teacher request consumes the invite, hashing occurs before account-existence lookup using an instrumented real hash wrapper, and legacy `access_code` receives HTTP 422 due to `extra="forbid"`.

- [ ] **Step 2: Run RED and capture exact current leaks**

Run:

```powershell
python -m pytest tests/test_identity_controls.py -k "registration or invitation" -q
```

Expected: current responses differ (200/400 and distinct details), registration sets cookies, and the shared field is accepted.

- [ ] **Step 3: Implement the generic registration coordinator**

Change `UserCreate.access_code` to bounded `teacher_invitation_token`. Add a strict `RegistrationAcceptedResponse`. In `/api/auth/register`:

1. hash the supplied password before private queries;
2. normalize requested role without returning role-specific failures;
3. decide eligibility without changing the response;
4. for teachers, atomically consume the invitation in the same transaction as `User` insertion;
5. catch expected `IntegrityError`, roll back, and return the generic response;
6. return HTTP 202 for every structurally valid request;
7. never call session issuance or set cookies.

Use one constant response object and do not log the request, token, email, username, or database exception. Preserve schema-level 422 responses for malformed bodies.

- [ ] **Step 4: Run registration GREEN plus existing auth tests**

Run:

```powershell
python -m pytest tests/test_identity_controls.py tests/test_session_security.py tests/test_auth_security.py -q
```

Update existing session tests to register then explicitly log in; remove assertions that registration is a browser-session success route.

### Task 4: Enforce persisted sessions and lifecycle revocation test-first

**Files:**
- Modify: `litblogs/tests/test_identity_controls.py`
- Modify: `litblogs/tests/test_session_security.py`
- Modify: `litblogs/tests/test_resource_authorization.py`
- Modify: `litblogs/main.py`
- Modify: `litblogs/schemas.py`
- Modify: `litblogs/access_control.py`

- [ ] **Step 1: Write RED request-level session abuse tests**

Cover:

- a cryptographically valid JWT with no database session row returns 401;
- bearer and cookie forms both require the persisted row;
- a session row with a different user, `revoked_at`, or elapsed `expires_at` returns 401;
- disabling a user invalidates already-issued sessions immediately;
- two logins create independent sessions; logout with session A revokes A only and session B stays valid;
- concurrent/repeated logout does not revive or corrupt a session;
- password change verifies the current password, updates it, revokes all sessions, clears cookies, and permits a new login only with the new password;
- successful reset revokes every session in the same transaction;
- account deletion locks the user row before child cleanup and removes/revokes all session rows;
- admin status is 401/403 to anonymous, students, and teachers; admin disable revokes all sessions; admin enable does not auto-login; admin self-disable is rejected;
- route inventory becomes 74 handlers while the explicit public allowlist remains unchanged.

Update test authentication helpers to create real `BrowserSession` rows from issued tokens; never add a test-only auth bypass.

- [ ] **Step 2: Run RED and verify stateless acceptance/current missing routes**

Run:

```powershell
python -m pytest tests/test_identity_controls.py tests/test_session_security.py tests/test_authorization_policy.py -q
```

Expected: signed stateless tokens still authenticate, logout does not revoke, lifecycle routes are missing, and reset/disable assertions fail.

- [ ] **Step 3: Implement persisted authentication and lifecycle routes**

Refactor session setting into two operations:

```python
def _set_browser_session_cookies(response: Response, token: str) -> None:
    max_age = settings.access_token_expire_minutes * 60
    cookie_options = {
        "max_age": max_age,
        "path": "/",
        "secure": settings.session_cookie_secure,
        "samesite": "strict",
    }
    response.set_cookie(
        _session_cookie_name(), token, httponly=True, **cookie_options
    )
    response.set_cookie(
        _csrf_cookie_name(),
        secrets.token_urlsafe(32),
        httponly=False,
        **cookie_options,
    )


def _commit_new_browser_session(db: Session, user: models.User) -> str:
    issued = issue_browser_session(db, user_id=user.id, settings=settings)
    db.commit()
    return issued.token
```

Every login/OAuth route creates the row, commits, then sets cookies. `get_current_user` decodes the token, loads a matching active `BrowserSession`, rejects `User.disabled_at`, and writes `request.state.browser_session_id`. Logout accepts `Request` and `Session`, conditionally revokes the current row, commits, and clears cookies.

Add strict schemas:

```python
class ChangePasswordRequest(StrictRequest):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=15, max_length=1024)

class UserStatusUpdate(StrictRequest):
    disabled: bool
```

Add protected `POST /api/auth/change-password` and admin-only `PUT /api/users/{user_id}/status`. Use SQL conditional updates, `revoke_all_sessions`, and password-reset invalidation before the one commit. Add all-session revocation to successful reset and account deletion. Treat disabled users as absent in password login, OAuth, forgot-password queueing, delivery, completion, and reset consumption. Serialize reset/change/disable/delete by locking the enabled user row before any child-row mutation. Clear cookies after change/delete success.

- [ ] **Step 4: Run focused GREEN tests and route policy**

Run the RED command again. Expected: all session/lifecycle tests and explicit route-inventory assertions pass.

### Task 5: Make verified-provider OAuth atomic with invitations and sessions

**Files:**
- Modify: `litblogs/tests/test_oauth_security.py`
- Modify: `litblogs/tests/test_identity_controls.py`
- Modify: `litblogs/main.py`

- [ ] **Step 1: Write RED OAuth invitation/session tests**

For Google and Microsoft, assert:

- a new teacher needs `teacherInvitationToken` and the provider-verified email must match its HMAC binding;
- mismatch, expired, revoked, and replayed invitation attempts return the same generic external-authentication error and create no account/session;
- concurrent signup consumes an invitation once and never creates two teachers;
- a new teacher user, federated identity, consumed invite, and browser session commit as one logical transaction;
- existing identities sign in without consuming a new invitation;
- disabled identities cannot login or signup and existing sessions remain invalid;
- `accessCode` is rejected as an extra field;
- OAuth responses and captured logs contain no raw invite/session identifier.

- [ ] **Step 2: Run OAuth RED**

Run:

```powershell
python -m pytest tests/test_oauth_security.py tests/test_identity_controls.py -k "oauth or google or microsoft or federated" -q
```

Expected: current shared-code behavior and internally committing `_create_federated_user` violate atomic invitation/session assertions.

- [ ] **Step 3: Refactor federated account creation into one caller-owned transaction**

Rename the payload field to `teacherInvitationToken`. Make `_create_federated_user` add/flush, not commit. For a new teacher, consume the invitation using the verified provider email before adding the user. Add the session row before the single commit, then set cookies. Resolve unique races by rolling back and loading the winning identity only when it is active; never reuse or re-consume an invite. Reject disabled identities with the same external-authentication response used for other failures.

- [ ] **Step 4: Run OAuth GREEN and the complete focused identity set**

Run:

```powershell
python -m pytest tests/test_identity_controls.py tests/test_session_security.py tests/test_oauth_security.py tests/test_auth_security.py tests/test_authorization_policy.py -q
```

Expected: all identity and route-policy tests pass.

### Task 6: Add explicit operator CLIs test-first

**Files:**
- Create: `litblogs/manage_teacher_invitations.py`
- Create: `litblogs/manage_accounts.py`
- Modify: `litblogs/tests/test_identity_controls.py`

- [ ] **Step 1: Write RED CLI behavior and secrecy tests**

Invoke CLI `main(argv, session_factory=SessionLocal)` entry points directly and through `python -m` smoke subprocesses. Assert:

- invitation `create --expires-hours --operator` reads its email from a protected stdin/no-echo prompt, creates one digest-only row, and stdout contains exactly one raw token line;
- stderr/audit logging contains no raw token, normalized email, token digest, email digest, or database identifier;
- invitation `revoke --operator` reads its email privately, conditionally revokes an active invitation, and prints only `Invitation revoked` or `Invitation not found`;
- account `disable --operator` reads its email privately, sets `disabled_at`, revokes all sessions, invalidates all password-reset state, and prints only `Account disabled`;
- account `enable --operator` reads its email privately, clears `disabled_at`, prints only `Account enabled`, and creates no session;
- ambiguous/missing users and repeated operations are generic failures and never list candidate accounts;
- operator identifiers, expiry hours, and emails are strictly bounded;
- no FastAPI route contains `invite`, `invitation`, or operator command functionality.

- [ ] **Step 2: Run CLI RED**

Run `python -m pytest tests/test_identity_controls.py -k "cli or operator" -q`. Expected: modules/commands are absent.

- [ ] **Step 3: Implement minimal explicit commands**

Use `argparse` subcommands. `main()` constructs one database session, calls the already-tested primitives, commits exactly once, returns a process code, and closes the session in `finally`. `create` writes only the token to stdout; generic status and errors go to stderr without exception strings. `revoke`, `disable`, and `enable` never print identifiers. Do not add HTTP routes.

- [ ] **Step 4: Run CLI GREEN**

Run the RED command again. Expected: all command/secrecy tests pass.

### Task 7: Update frontend registration contract test-first

**Files:**
- Create: `litblogs/src/SignupIdentityControls.test.jsx`
- Modify: `litblogs/src/Sign-up.jsx`
- Modify: `litblogs/src/PrivacyPolicy.jsx`

- [ ] **Step 1: Write RED frontend tests**

Render signup with mocked Axios and auth utilities. Assert:

- the teacher field is labelled `Teacher invitation token`, is bounded, and sends `teacher_invitation_token` for password signup and `teacherInvitationToken` for provider signup;
- source/request bodies contain neither `accessCode` nor `access_code` for teacher provisioning;
- a password registration HTTP 202 shows the generic message and a direct sign-in link/direction;
- password registration never calls `fetchBrowserSession`, never writes legacy local auth state, and never navigates as an authenticated user;
- the privacy policy describes one-time email-bound invitations, not shared access codes.

- [ ] **Step 2: Run frontend RED**

Run:

```powershell
npm test -- --run src/SignupIdentityControls.test.jsx
```

Expected: current shared-code labels/payload and post-registration session fetch fail the assertions.

- [ ] **Step 3: Implement the minimal UI contract**

Rename local state to `teacherInvitationToken`, remove client-side shared-code semantics, send the backend field names above, and replace auto-login behavior with generic accepted-state rendering and a sign-in action. Do not expose invite validity or add an invitation-management UI.

- [ ] **Step 4: Run frontend GREEN and auth-focused tests**

Run:

```powershell
npm test -- --run src/SignupIdentityControls.test.jsx src/OAuthFlows.test.jsx src/utils/auth.test.js
```

Expected: all selected tests pass.

### Task 8: Add migration, runbook, and source policy regressions

**Files:**
- Create: `litblogs/migrations/0003_add_identity_controls.sql`
- Create: `litblogs/migrations/README-identity-controls.md`
- Modify: `litblogs/tests/test_repository_policy.py`
- Modify: `litblogs/tests/test_auth_security.py`
- Modify: `litblogs/.env.example`
- Modify: `README.md`
- Modify: `SECURITY.md`

- [ ] **Step 1: Write RED migration and repository-policy tests**

Assert that migration 0003:

- uses additive `ALTER TABLE users ADD COLUMN disabled_at` and creates the session, invitation, and operator-audit tables/indexes;
- has digest-length checks, foreign-key cascade, expiry/user indexes, and PostgreSQL partial active-email uniqueness;
- contains no raw `token`, `jti`, or invitee `email` columns;
- contains a token-safe application rollback sequence that retains additive identity/audit schema;
- does not backfill sessions;
- has a runbook that explicitly warns deployment invalidates all pre-migration JWTs.

Add source scans proving `TEACHER_ACCESS_CODE`, shared-code payload fields, raw identity logger calls, and public invitation routes are absent outside migration/history text that explicitly documents removal.

- [ ] **Step 2: Run policy RED**

Run:

```powershell
python -m pytest tests/test_repository_policy.py tests/test_auth_security.py -q
```

Expected: 0003/runbook are absent and legacy setting/contracts remain.

- [ ] **Step 3: Add additive migration and deployment documentation**

Use transactional PostgreSQL DDL with named constraints/indexes, locale-independent ASCII translate/btrim checks pinned to `COLLATE "C"`, and legacy user/teacher preflight. Make `teachers.user_id` the unique, non-null canonical association and stop on ambiguous mappings. Application rollback must stop traffic and issuance, retain the additive identity/audit schema, rotate the JWT key (or wait the full token lifetime plus skew), contain disabled identities outside older code, and retain audit evidence; destructive schema retirement is a separate approved migration. Update `.env.example` to require a distinct 32+ byte `TEACHER_INVITE_HMAC_KEY` and remove `TEACHER_ACCESS_CODE`. Document exact invite create/revoke and account disable/enable commands without example secrets or real emails. Privileged CLI changes and known no-op outcomes must persist actor/action/outcome with only a domain-separated HMAC target; audit failure rolls back state changes.

- [ ] **Step 4: Run policy GREEN and diff hygiene**

Run the RED command plus `git diff --check`. Expected: tests pass and no whitespace errors.

### Task 9: Independent review, full verification, and the single local commit

**Files:**
- Review all changes from `753d957b25b6719cddfbcf9bfceb0b2765d29e1a`.

- [ ] **Step 1: Run the complete backend/frontend/security verification matrix**

From `litblogs` run fresh commands and retain counts/exit codes:

```powershell
python -m pytest -q
python -m ruff check .
python -m bandit -r . -x tests,.venv
npm test -- --run
npm run lint
npm run build
python -m pip_audit -r requirements.txt -r requirements-dev.txt
npm audit --audit-level=high
```

From the repository root run the established secret scanners, pre-commit hooks, repository-policy tests, and `git diff --check`. If a command differs in this repository, inspect `package.json`, `pyproject.toml`, `.pre-commit-config.yaml`, and prior plan 04, then run the exact established equivalent and record it.

- [ ] **Step 2: Request an independent Critical/Important review**

Give the reviewer:

- base SHA `753d957b25b6719cddfbcf9bfceb0b2765d29e1a`;
- the written design and this plan;
- RED/GREEN counts;
- explicit focus on session replay/revocation races, invite atomicity/secrecy, OAuth transaction boundaries, account enumeration/timing, operator CLI output, migrations, and default-deny route inventory;
- explicit exclusion of known upload/content findings owned by commit `48acb01`.

- [ ] **Step 3: Fix every Critical/Important finding test-first and request re-review**

For each valid finding: reproduce with one failing test, record RED, implement the smallest root-cause fix, run focused GREEN plus impacted suites, and send the exact delta back to the independent reviewer. Do not proceed while any patch-local Critical/Important issue remains open.

- [ ] **Step 4: Perform final verification-before-completion**

Re-run the full matrix after the final review change, inspect `git status --short`, `git diff --stat`, `git diff --check`, and a source scan proving no raw invite/session identifiers or `TEACHER_ACCESS_CODE` remain. Confirm no upload/content file was changed unintentionally.

- [ ] **Step 5: Create the authorized local commit**

Stage only this identity slice and commit once with an exact security-scoped message chosen with the parent before the commit. Do not amend `753d957`, push, or open a PR. Report commit SHA, exact changed paths, RED/GREEN evidence, reviewer closure, behavior changes, migration impact, and remaining stack blockers.
