# LitBlog Security and Correctness Design

## Objective

Make LitBlog's student and teacher journeys executable as repeatable tests, close the confirmed authentication, authorization, content, upload, and secret-management failures, and establish a protected GitHub delivery path. The work must preserve the React/FastAPI/PostgreSQL architecture and the current user-facing workflows while replacing insecure implementation details.

## Confirmed baseline

- A clean `npm ci` fails because `eslint-plugin-react@7.22.0` is incompatible with ESLint 9.
- The repository has no frontend, backend, integration, or browser tests and no GitHub Actions workflows.
- The production build succeeds only after bypassing peer-dependency validation; lint crashes before checking source.
- `npm audit --omit=dev` reports a vulnerable runtime dependency set, including the bundled PDF renderer. `pip-audit` reports 53 findings across 16 pinned Python packages.
- A synthetic student/teacher API journey succeeds through create/join/post/like/comment/settings/archive/restore, but deleting a populated class returns 500. Teacher notes report success without persisting because the model has no notes column.
- The public repository tracks a populated `.env`, repeats secrets in history, and hard-codes a Microsoft client secret in `main.py`. Every exposed credential must be rotated outside this code change.
- Microsoft login/signup trust a browser-supplied email without validating an identity token. Any authenticated user can self-promote through `/api/update-role`. Public/debug endpoints expose posts and class codes. `/api/users` can serialize password hashes.
- Upload/download paths permit traversal and files are publicly mounted. Rich post HTML reaches unsafe render paths while bearer tokens and private drafts are stored in browser local storage.

## Chosen approach

Use an incremental, deny-by-default refactor delivered as four dependent pull requests:

1. Secure development baseline: remove tracked secrets, make installs reproducible, add test runners, CI/security checks, and repository contribution policy.
2. Identity and authorization: validate all identity assertions, issue short-lived secure-cookie sessions with CSRF protection, prevent role escalation, rate-limit authentication, and return explicit response schemas.
3. Student and teacher workflows: exercise and repair real use cases, centralize class ownership/membership checks, fix deletion and notes persistence, and restrict submission/profile data.
4. Content and privacy: sanitize rich content at write and render boundaries, validate and authorize uploads, remove the vulnerable PDF runtime, eliminate sensitive persistent browser storage, and run browser/PostgreSQL journeys.

A full backend rewrite is rejected for this pass because it would make behavior changes difficult to distinguish from existing defects. Perimeter-only controls are rejected because confirmed object-level authorization failures occur inside the API.

## Application architecture

The existing entry point remains `litblogs/main.py`, but focused security responsibilities move into small modules:

- `litblogs/config.py`: validated environment configuration and production fail-closed rules.
- `litblogs/auth_security.py`: password hashing/rehashing, JWT claims, secure cookies, CSRF comparison, OAuth claim verification, and access-code comparison.
- `litblogs/content_security.py`: one HTML allowlist used on writes and mirrored by DOMPurify on reads.
- `litblogs/upload_security.py`: canonical paths, extension/MIME/signature allowlists, size-limited streaming, and private response headers.
- `litblogs/access_control.py`: reusable admin, class-owner, class-member, assignment, submission, post, and shared-profile checks.

Routes keep their current URLs unless an insecure legacy route is removed. All request bodies gain typed Pydantic models and bounds. All sensitive response shapes become explicit so ORM password fields cannot be serialized accidentally.

## Identity and session model

- Local passwords require 15 characters for new/reset credentials. Existing bcrypt hashes continue to verify and are upgraded to Argon2id after a successful login.
- JWTs use one configured algorithm (`HS256`), a minimum 32-byte random secret, and required `sub`, `iss`, `aud`, `iat`, `nbf`, `exp`, and `jti` claims. Production startup fails if required settings are absent, placeholder-like, or unsafe.
- Browsers receive the JWT only in an `HttpOnly`, `Secure` (production), `SameSite=Strict` cookie. A separate non-secret CSRF cookie is compared in constant time with `X-CSRF-Token` for authenticated state changes.
- Bearer tokens remain temporarily supported for API tests and non-browser clients, but the React app stops persisting tokens. Logout clears cookies and all session-scoped user/draft state.
- Google identity tokens must pass signature, issuer, audience, expiry, and verified-email checks. The unverified decode fallback is removed.
- Microsoft requests must include an ID token. The backend validates its signature against Microsoft's JWKS, audience, issuer/tenant, expiry, and email claim before account lookup or creation. Raw `msUserData` is never an identity assertion.
- Public self-registration can create students only. Teacher enrollment requires the configured teacher code with rate limiting and constant-time comparison. Public admin creation and self-service role changes are removed; privileged role assignment is admin-only.
- Login, registration/code validation, password reset, and OAuth endpoints use configurable rate limits. The reverse proxy remains responsible for a second distributed rate-limit layer.
- Production cannot enable database reset-on-startup. Schema changes run through reviewed Alembic migrations, and startup performs a connectivity/readiness check without creating or dropping tables.

## Authorization and privacy matrix

| Resource/action | Student | Teacher | Admin |
| --- | --- | --- | --- |
| Join class | Own account, active class code | Denied | Operational override |
| View class/feed | Enrolled classes only | Owned classes only | Allowed |
| Create post/comment/like | Enrolled class only | Owned class only | Allowed |
| Edit/delete post | Own post; teacher policy cannot be bypassed | Own post or post in owned class | Allowed |
| Create/update assignment | Denied | Owned class only | Allowed |
| Draft/submit assignment | Own enrollment and own draft/submission | Denied | Operational override |
| View submissions | Own submission only | Submissions in owned class | Allowed |
| Reply to submission | Own submission thread | Owned-class submission | Allowed |
| View roster | Minimal peer identity for enrolled student | Full roster for owned class | Allowed |
| View student detail/posts/notes | Own profile or privacy-approved shared profile | Enrolled students in owned class | Allowed |
| Write teacher notes | Denied | Owned class only | Allowed |
| Archive/restore/delete class | Denied | Owned class only | Allowed |
| Read upload | Owner or authorized member of its class | Owner or authorized class teacher | Allowed |

Every object route first loads the resource and then checks this matrix. Knowing an integer ID or filename never grants access. Error responses avoid revealing whether a forbidden cross-class resource exists where practical.

## Student and teacher use-case suite

The API integration suite uses a fresh database and synthetic records. It covers:

- Student registration/login/logout, invalid credentials, session expiry, password reset, and privacy-preserving forgot-password responses.
- Teacher registration/login, invalid access codes, and blocked admin/self-role escalation.
- Teacher create/list/view/archive/restore/delete classes, including populated classes and denial against another teacher's class.
- Student join by code, duplicate join, archived/invalid class denial, active/archived lists, and nonmember denial.
- Student and teacher class posts: create, view, update, delete, sanitization, visibility, and ownership checks.
- Likes, comments, nested replies, counts, pagination bounds, and cross-class denial.
- Teacher assignment creation/update; student list/draft/save/submit/late rules; teacher submission review/reply; peer-submission denial.
- Profile edit/image, visibility setting, shared-class profile rules, student post history, teacher notes persistence, and account deletion.
- Settings round-trip for `editorFontSize` (`small`, `medium`, `large`) and the remaining booleans.
- Upload allowlists, magic mismatch, oversize body, SVG/HTML denial, traversal denial, unauthorized reads/deletes, and download headers.

The browser suite runs against a disposable PostgreSQL database and verifies representative UI journeys: teacher creates a class; student joins it, changes font size, posts, likes, and comments; teacher sees the student/profile/post, manages an assignment, archives/restores, and deletes the class. Tests assert both visible UI state and server-side results.

## Content and upload controls

- Rich text is sanitized server-side before persistence and with DOMPurify immediately before rendering. Escaped markup is never decoded after sanitization.
- Scripts, event handlers, `style` elements, external active embeds, unsafe protocols, SVG, and arbitrary IDs are removed. Links opened in new tabs receive `noopener noreferrer`.
- Upload names are UUID-based. Canonical resolved paths must remain below the configured upload root.
- Images, video, and PDFs use explicit extension, declared MIME, and file-signature agreement. Requests stream to a temporary file with per-kind size limits; partial files are deleted after failure.
- Files are not mounted as public static content. Authenticated handlers enforce ownership/class access and add `X-Content-Type-Options: nosniff`, private caching, and safe `Content-Disposition`.
- The vulnerable in-app PDF.js dependency is removed. PDFs download through the authorized endpoint; inline preview is not restored until a maintained renderer or isolated file origin is available.
- Production documentation requires antivirus/CDR scanning at the upload boundary. If server-side malware scanning is configured as required, an unavailable scanner fails closed.
- Push-subscription endpoints accept only HTTPS origins, reject local/private/link-local destinations, bound field sizes, and never expose provider response bodies. Production egress policy remains the final SSRF boundary.

## Repository and delivery model

- Use protected trunk-based development with short-lived `codex/*` branches and dependent draft pull requests. Merge bottom-up with squash commits.
- CI runs backend tests on PostgreSQL, frontend unit tests, lint, build, dependency audits, secret scanning, and SAST on pull requests, pushes to `main`, and merge-queue groups.
- `main` blocks force pushes/deletion, requires a pull request, current required checks, resolved conversations, linear history, and at least one independent approval. Increase to two approvals and required code-owner review as soon as a second adult maintainer/team is confirmed.
- Actions use least-privilege permissions and immutable action SHAs. Deployments use a protected environment and synthetic CI data only.
- Git history remediation, tag replacement, secret rotation, repository visibility, production TLS/proxy policy, backups, logging/SIEM, retention, and disaster recovery require coordinated school IT action and are documented as release blockers rather than silently attempted.

## Error handling and observability

- Clients receive stable, non-sensitive messages. Stack traces, provider responses, file-system paths, database errors, tokens, and emails are not returned.
- Security events log structured event type, request ID, outcome, and actor/resource IDs without post content, passwords, tokens, access codes, email bodies, or uploaded data.
- Database writes use rollback on failure. Destructive class/account operations delete dependent rows transactionally and are covered by regression tests.
- Enrollment and submission records have database uniqueness constraints so concurrent requests cannot create duplicate access or work products.
- Account/class deletion applies documented database and file-retention behavior; it cannot leave private orphan uploads behind or silently erase records subject to school retention policy.

## Acceptance criteria

- Fresh frontend and Python development installs succeed without compatibility bypasses.
- All role/API, frontend unit, PostgreSQL integration, and representative browser tests pass.
- Frontend lint/build and backend lint/static analysis pass with documented, narrow exceptions only.
- Runtime dependency audits contain no known high or critical findings; any unfixable lower finding has a written risk decision.
- No populated environment file or hard-coded secret remains in the proposed tree.
- Confirmed account takeover, role escalation, password-hash disclosure, cross-class submission exposure, XSS, and file traversal probes fail safely.
- Four dependent draft PRs are open with exact base branches and verification evidence.
- Active GitHub protection is applied only after its named checks have run, avoiding a permanently locked default branch.

## Required operator actions

Before any deployment, school IT must rotate the database password, JWT secret, teacher/admin access codes, VAPID key pair, email application password, and Microsoft client secret; invalidate existing sessions; update the private server's secret store; and review public history, stale PR text, tags, and school photographs. Code changes cannot revoke already copied values.
