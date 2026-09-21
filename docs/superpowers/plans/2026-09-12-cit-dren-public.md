# Publish LitBlogs at /dren

**Goal:** Serve the existing LitBlogs installation at `https://drhscit.org/dren/`,
using only its existing location in the shared Nginx site. Preserve all database
records, uploads, other applications and unrelated Nginx configuration. SMTP
replacement and delivery verification remain explicitly deferred by the owner.

**Architecture:** Host Nginx redirects the exact `/dren` entry to `/dren/`,
requires HTTPS/canonical host within this route, and strips the prefix before
proxying over verified private TLS to the existing loopback HAProxy gateway.
Backend routes remain `/api/...` internally so authorization, body limits and
logging guards retain their existing behavior. A validated `LITBLOGS_BASE_PATH`
setting supplies the frontend build and public email-link base. Root deployments
remain supported. No database migration is required.

**Trust limitation:** Different paths on `drhscit.org` share a browser origin.
The requested temporary path deployment cannot isolate private accounts from
other same-origin applications. Prefixed cookies use Secure/no-Domain and
`Path=/dren/` with `__Secure-` names to avoid automatically sending them to sibling
backends; root deployments retain `__Host-` cookies. This reduces accidental
disclosure and is not an origin security boundary. A dedicated origin remains
necessary for isolation before private student use. Do not claim otherwise.

**Scope:** No shared Docker restart, PostgreSQL recreation, volume deletion,
database reset, public DNS change, new subdomain, SMTP send, or edits to any other
Nginx location. No proxy response-body rewriting or authentication bypass.

- [x] Inspect the current source, deployment, Nginx baseline and exact old `/dren`
  upstream; verify current configuration syntax and isolate worktree.
- [ ] Add strict origin/prefix settings and matching cookie issue/delete rules;
  test root defaults, prefixed login/CSRF and verification/reset link generation.
- [ ] Build frontend assets at `/dren/`; adapt validated rich-text display URLs,
  CSRF lookup, storage ownership and service-worker scope without changing stored
  canonical upload references or sibling browser storage.
- [ ] Parameterize gateway Host/health checks, accept client rate-limit identity
  only from the exact trusted host-proxy address, and preserve the build prefix
  during future CI-gated automatic updates. Test spoof rejection and separate
  client limits with the pinned gateway image.
- [ ] Run backend/frontend/deployment validation, security checks and an
  independent review; publish only the reviewed LitBlogs changes.
- [ ] Save private rollback copies of the environment, installed controls and
  original Nginx file, plus database/container and user/upload fingerprints.
- [ ] Build the reviewed candidate, authenticate an encrypted backup and activate
  only LitBlogs application/gateway configuration under the existing operation
  lock. Keep PostgreSQL and its start time unchanged.
- [ ] Test the new route with a loopback-only temporary Nginx instance before
  changing the shared file: HTTPS/Host handling, redirects, deep-link HTML,
  JavaScript/CSS, runtime configuration, private-path rejection, video Range,
  login/session cookies, CSRF and logout. Do not send mail.
- [ ] Create a candidate shared config with exactly the old LitBlogs location
  replaced. Validate full Nginx configuration against that candidate, verify the
  original file has not changed, atomically replace its resolved target, run
  `nginx -t` and reload. Roll back only the saved LitBlogs change if validation
  or route checks fail. Defer upstream HSTS to the existing host policy.
- [ ] Verify public HTTPS and browser journeys, unchanged sibling config/route
  behavior, preserved database/uploads and active maintenance services. Open the
  public page in the user's Codex preview and update the private handoff.

File ownership: backend agent owns settings/runtime/email/cookie code and tests;
frontend agent owns browser code and tests; operations agent owns local gateway,
updater/probes and their tests; root owns Dockerfile/root Compose, Nginx staging
and replacement tooling, integration verification, publication and handoff.
