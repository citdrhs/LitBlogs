# Identity and Authorization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate forged identity, role escalation, credential disclosure, insecure browser token storage, and cross-object authorization gaps.

**Architecture:** Introduce validated settings, security primitives, and reusable authorization dependencies while preserving existing route URLs. Browser sessions move to HttpOnly cookies with CSRF protection; verified bearer tokens remain available to automated/API clients.

**Tech Stack:** FastAPI, Pydantic Settings, PyJWT/JWKS, pwdlib Argon2/bcrypt, SQLAlchemy, React, Axios, Vitest, pytest.

---

### Task 1: Lock configuration and token primitives

**Files:**
- Create: `litblogs/config.py`
- Create: `litblogs/auth_security.py`
- Create: `litblogs/tests/test_auth_security.py`
- Modify: `litblogs/database.py`
- Modify: `litblogs/main.py`

- [ ] Write failing tests for missing/short production secrets, required JWT claims, expiry, wrong audience/issuer, constant-time access-code checks, Argon2 hashing, and legacy bcrypt rehash.
- [ ] Run `pytest tests/test_auth_security.py -q`; confirm failures identify missing modules/behavior.
- [ ] Implement immutable validated settings and focused primitives. Fix JWT algorithm to HS256 and require `sub`, `iss`, `aud`, `iat`, `nbf`, `exp`, `jti` during decode.
- [ ] Run the focused test and full backend suite; expect pass.
- [ ] Commit `security: validate configuration and session tokens`.

### Task 2: Replace browser bearer persistence with cookie sessions

**Files:**
- Modify: `litblogs/main.py`
- Modify: `litblogs/src/main.jsx`
- Modify: `litblogs/src/utils/auth.js`
- Modify: `litblogs/src/components/ProtectedRoute.jsx`
- Modify: `litblogs/src/Sign-in.jsx`
- Modify: `litblogs/src/Sign-up.jsx`
- Create: `litblogs/src/utils/auth.test.js`
- Create: `litblogs/tests/test_session_security.py`

- [ ] Write failing backend tests asserting HttpOnly/SameSite/Secure production cookies, CSRF denial/acceptance, logout clearing, and bearer compatibility.
- [ ] Write failing frontend tests asserting no JWT is persisted and Axios sends credentials plus CSRF for unsafe requests.
- [ ] Implement cookie helpers, optional bearer extraction, CSRF middleware/dependency, `/api/auth/session`, and `/api/auth/logout`. Store only non-secret UI session metadata in `sessionStorage` and clear it on logout.
- [ ] Run focused backend/frontend tests and then both suites; expect pass.
- [ ] Commit `security: move browser authentication to protected cookies`.

### Task 3: Verify external identity providers

**Files:**
- Modify: `litblogs/main.py`
- Modify: `litblogs/src/Sign-in.jsx`
- Modify: `litblogs/src/Sign-up.jsx`
- Modify: `litblogs/src/config/msalConfig.js`
- Create: `litblogs/tests/test_oauth_security.py`

- [ ] Write failing tests proving forged `msUserData` is rejected, invalid/unsigned/expired/wrong-audience tokens are rejected, Google's timing error cannot trigger unsigned decode, and provider `HTTPException` status is preserved.
- [ ] Remove the Microsoft confidential-secret/token-exchange route and all unverified Google decode fallbacks. Validate Google verified email and Microsoft signed ID-token claims; optionally enforce configured tenant/domain allowlists.
- [ ] Change MSAL UI calls to send `idToken`, not profile JSON; move public client IDs to Vite environment configuration.
- [ ] Run focused tests, frontend tests, and build; expect pass.
- [ ] Commit `security: verify federated identity assertions`.

### Task 4: Enforce role and response boundaries

**Files:**
- Create: `litblogs/access_control.py`
- Modify: `litblogs/schemas.py`
- Modify: `litblogs/main.py`
- Create: `litblogs/tests/test_authorization_boundaries.py`

- [ ] Write failing tests for self-admin promotion, student `/api/users`, password-hash serialization, public blogs/debug classes, arbitrary user lookup, nonmember likes/comments, and cross-class object IDs.
- [ ] Remove debug/legacy public routes; replace `/api/update-role` with admin-only typed behavior or remove it. Add explicit safe response schemas and centralized class/post/comment/assignment/submission access checks.
- [ ] Verify every route in the route inventory either declares public intent or requires authenticated authorization.
- [ ] Run focused tests and full suite; expect pass.
- [ ] Commit `security: enforce deny-by-default role authorization`.

### Task 5: Harden password and abuse paths

**Files:**
- Create: `litblogs/rate_limit.py`
- Modify: `litblogs/schemas.py`
- Modify: `litblogs/main.py`
- Create: `litblogs/tests/test_password_reset.py`
- Create: `litblogs/tests/test_rate_limits.py`

- [ ] Write failing tests for password length/bounds, generic forgot-password response, hashed reset tokens, single use, revocation after password change, access-code throttling, and safe provider/error text.
- [ ] Implement bounded request models, rate-limit storage with a production Redis option and test reset hook, hashed reset tokens, prior-token revocation, generic responses, and transaction rollback.
- [ ] Run tests plus Bandit/Ruff; expect pass.
- [ ] Commit `security: harden credentials and abuse controls`.

### Task 6: Guard startup and outbound push boundaries

**Files:**
- Modify: `litblogs/database.py`
- Modify: `litblogs/main.py`
- Create: `litblogs/tests/test_production_guards.py`
- Create: `litblogs/tests/test_push_subscription_security.py`

- [ ] Write failing tests proving production rejects reset-on-startup and import/startup never drops or creates schemas implicitly.
- [ ] Write failing tests for non-HTTPS, loopback, private, link-local, oversized, and malformed push-subscription endpoints.
- [ ] Replace production `create_all`/reset behavior with explicit readiness plus Alembic deployment instructions, and validate push destinations before persistence/use.
- [ ] Run focused tests, Bandit, and the full backend suite; expect pass.
- [ ] Commit `security: guard database startup and push egress`.

### Task 7: Verify stack layer

- [ ] Run all backend/frontend tests, lint/build, dependency audits, and focused forgery/escalation probes.
- [ ] Request independent review of the previous stack commit through `HEAD`; fix Critical/Important findings test-first.
- [ ] Re-run the complete layer verification and record evidence.
