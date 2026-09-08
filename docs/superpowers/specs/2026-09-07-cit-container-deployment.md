# CIT Deploy container deployment

## Outcome

Package LitBlogs with a root Dockerfile and Docker Compose stack so CIT Deploy
can build it without its Flask template or manual Python/Node/PostgreSQL installs.
Keep the existing Ubuntu instructions as an alternative. Do not deploy the live
school application in this task.

## Hosting boundary

The supplied Custom Docker form accepts `docker-compose.yml` and runtime
environment variables. Its shown CIT and Student targets publish sibling paths
on `drhscit.org`. Those paths are not isolated browser origins. Production needs
an exclusively controlled HTTPS hostname routed to the web service; retain the
root-origin and `__Host-` cookie requirements. Do not claim the default shared
path is safe for student information.

## Architecture

- A multi-stage Dockerfile builds React with the locked Node dependencies and
  installs the hash-locked Python runtime dependencies. The final non-root app
  image serves the built frontend and existing FastAPI routes on port 5000.
- A container-only static frontend adapter provides SPA deep links, hashed-asset
  caching, captions/video MIME types, byte-range playback, and existing security
  headers. It never serves uploaded files directly or converts unknown API paths
  into HTML. The development entrypoint is unchanged.
- Compose manages PostgreSQL 17, private ClamAV, the web service, bounded email
  delivery, and upload reconciliation. A one-shot initialization step prepares
  fresh storage/TLS, and a separate migration job uses migration credentials.
- Database and uploaded files use named volumes that survive normal redeploys.
  PostgreSQL and ClamAV have no published host ports. Only the web service is
  routed by the host. Never mount the Docker socket or use privileged containers.
- Supply production origin, school email domain, signing keys, database secrets,
  and SMTP details at runtime. Never bake secrets into images. OAuth remains off
  by default. Keep migration/operator/DBA secrets away from the web environment.
- Preserve production database-role, TLS, upload-custody, scanner and readiness
  checks. Container startup must not fabricate backup/restore or school-approval
  attestations. The guide must identify the required recovery verification before
  admitting real users and the first-admin/teacher-invitation steps.

### Review-driven refinement

Compose exposes a separate non-root Nginx `web` gateway on port 5000 and keeps
the FastAPI/React `app` service private. This preserves the reviewed ordinary
body cap, upload exceptions, auth/API rate limits, and request timeouts. Docker
DNS re-resolution keeps the gateway working after the app is recreated. No
forwarded client IP is trusted without an exact school-approved proxy boundary.

## Verification

Use test-first unit/integration tests for static routing and bootstrap behavior,
then build the real image, validate Compose, and start a disposable stack. Check
API health, SPA deep links, media ranges/captions, database roles/migrations,
private ports, persistence across recreation, failure on missing configuration,
and existing signup/student/teacher flows. Run affected suites and repository
security checks before committing/pushing. Explicitly distinguish local container
verification from school-host deployment, which is not authorized here.
