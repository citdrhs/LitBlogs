# LitBlogs at the approved CIT /dren route

This is the manually operated deployment at **https://drhscit.org/dren/**.
The path is lowercase. It reuses the persistent `litblogs-cit` Docker stack and
the existing host certificate. Only the old LitBlogs `location /dren` block in
`/etc/nginx/sites-available/default` is replaced. No other site, DNS record,
host service configuration, database volume or upload volume is replaced.

## Hosting boundary

The path deployment is an explicit temporary choice. Other CIT applications
share its browser origin; cookie paths and scoped local storage do not provide
the isolation of a dedicated hostname. Move to a dedicated HTTPS hostname
before treating this as isolated hosting for private student information.

The application uses Secure, HttpOnly session cookies scoped to `/dren/`, with
SameSite=Strict and no Domain attribute. The CSRF cookie is readable by this
frontend and uses the same path. Root-host deployments retain `__Host-` cookies;
the explicit prefix deployment uses `__Secure-litblogs-*` names. Changing modes
requires logging in again. Stored media paths and database rows are unchanged.

The CIT SMTP replacement and a real password-reset delivery were verified on
September 12, 2026. Credentials remain in the private server environment, outside
Git. Health checks alone do not attest mail delivery; retest after credential changes.

## Invite a teacher

Any active administrator can select **Invite Teacher** on the admin dashboard,
enter the teacher's allowed school email, and choose **Create invitation**.
Copy the invitation and share it privately with that teacher. The code is shown
only in this dialog, works once for that email, and expires after 48 hours.
Creating another invitation replaces an unused previous code for the same email.
This action does not send an invitation email or create an account automatically.

The teacher opens `https://drhscit.org/dren/sign-up`, registers with that same
email, selects **Teacher**, and enters the code in **Teacher invitation token**.
They must verify their school email before signing in and creating classes.
Existing accounts are not promoted through this invitation action.

## Private settings and application build

Keep the settings in the root-owned state `.env`, outside Git, using its existing
single-quoted format. The nonsecret routing settings are:

```dotenv
LITBLOGS_ORIGIN='https://drhscit.org'
LITBLOGS_BASE_PATH='/dren'
LITBLOGS_GATEWAY_HOST='drhscit.org'
```

`LITBLOGS_TRUSTED_PROXY_CIDR` must be the exact current IPv4 gateway address of
the existing `litblogs-cit_edge` Docker network followed by `/32`. Verify it
from the running network; never trust the entire subnet. Host Nginx overwrites
`X-LitBlogs-Client-IP`; HAProxy accepts it only from that peer for rate limiting
and removes it before passing the request to the application.

Build the reviewed, passing revision with `VITE_APP_BASE_PATH=/dren/`.
Compose derives this argument from `LITBLOGS_BASE_PATH`; the installed updater
does the same for future GitHub updates. An existing root-built image must be
rebuilt when changing the prefix. Runtime origin and prefix must match the
compiled frontend. CORS and the token issuer use the origin without a path.

Under the existing operation lock, back up the private settings and installed
controls, take a consistent encrypted backup, install the reviewed controls,
and recreate only `app`, `email`, `reconcile` and `web` with the new image.
Keep PostgreSQL and ClamAV running. Preserve the existing Compose project name
and volumes. Verify readiness, database identity, uploads and administrator
access before exposing the route. These changes need no schema migration.

## Stage, test, then reload the host route

`nginx-dren.conf` forwards `/dren/` to the verified private TLS gateway at
`127.0.0.1:18443`, stripping the prefix once. `/dren` redirects to `/dren/`.
The route enforces HTTPS and the canonical Host, clears supplied proxy headers,
preserves application security/cache headers, and disables access logging for
this path. It leaves the shared host's HSTS policy to its administrator.

Install the reviewed helper and snippet into the root-only directory
`/home/litblogs/.local/state/cit-deploy/public-route`. Keep all complete shared
configuration snapshots there, never in Git. Run the helper as root while
holding the existing LitBlogs operation lock:

1. `python3 nginx_route.py stage` saves the original and builds a candidate
   without changing the live file. It tests the complete candidate with
   `nginx -t` and snapshots the shared configuration to detect concurrent edits.
2. Exercise the same route in a temporary Nginx process bound only to a free
   loopback port with its own PID. `public_verify.py --canary-port 18444` checks
   the real HTTPS route, asset prefix, private-path rejection and administrator
   cookies/CSRF/logout without sending mail.
3. `python3 nginx_route.py commit` rechecks the candidate and shared-file hashes,
   replaces only the reviewed site file, runs **`nginx -t` again**, then reloads
   Nginx. If validation or reload fails, it restores the original as described
   in the helper's tested recovery paths. Concurrent changes stop the operation.
4. `python3 public_verify.py` exercises the public URL with certificate
   verification. Check unaffected CIT routes and container identities against
   the baseline, then remove only the temporary canary process and its files.

`python3 nginx_route.py rollback` restores the saved LitBlogs route only if the
shared configuration still matches the expected snapshot. It does not roll
back the application or database. Preserve the private backup for recovery;
do not reset the database to undo a routing change.

The existing startup service, bounded one-to-three application autoscaler,
CI-gated updates and encrypted backup timer remain in use. See
[../cit-local/README.md](../cit-local/README.md) for operation and recovery.
