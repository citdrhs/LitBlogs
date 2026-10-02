# Local LitBlogs installation on CIT

This deployment uses the root Dockerfile and Compose services, with this overlay
replacing the bundled Nginx gateway with HAProxy. The only published endpoint is
`127.0.0.1:18443`. It uses a private certificate for
`https://litblogs.cit.internal:18443`. The optional, explicitly approved public
route is documented in [../cit-public/README.md](../cit-public/README.md).
The private stack never publishes PostgreSQL or its application port.

The source checkout is `/home/litblogs/www/LitBlogs`. Root-owned settings,
installed operations scripts, certificates, logs and recovery archives are in
`/home/litblogs/.local/state/cit-deploy` (directory mode 0700, environment 0600).
The stable Compose project is **litblogs-cit**. Never change its name to update
the application, and never delete its volumes to redeploy.

## Current follow-up

- The SMTP replacement and real password-reset delivery were verified on
  September 12, 2026. Keep credentials private and retest actual delivery after
  changing them; healthy containers alone do not prove working email.
- The temporary `/dren/` route shares a browser origin with other CIT projects.
  A dedicated hostname remains necessary for browser isolation. Load validation
  and an off-host recovery schedule remain operational follow-ups.
- Store the backup encryption key separately from the encrypted archives, and
  monitor disk usage/retention. Automated backups are retained without deletion.

## Common commands

Log in using `ssh -p 4243 litblogs@drhscit.org`. The permanent command works from
any directory and needs no exported variables:

```bash
sudo litblogs status
sudo litblogs start
sudo litblogs check
sudo litblogs logs
```

`status` reports the unit, recovery latch and service health counts. `start`
recovers the existing installed containers without building images or running
initialization/migrations. Healthy running containers remain running. It uses
validated exact container IDs; do not substitute `docker compose start`, which
can traverse dependencies. A maintenance lock or recovery latch blocks startup.
If the oneshot unit is already active, the command invokes the installed startup
helper directly; otherwise it starts the unit so systemd tracks the deployment.
`check` verifies private HTTPS and runtime controls without sending mail. `logs`
saves up to 100 recent lines per container from the last 24 hours, capped at 2 MiB,
in root-only `logs/operator-latest.log` and prints that path. Inspect this file
privately; it may contain application details. Startup diagnostics remain in
`logs/service-start.log`.

The private `.env` persists outside Git across logout, reboot and source updates.
The command always uses that file, the installed HAProxy overlay, project
`litblogs-cit` and the local Docker socket. It discards inherited shell settings;
no `export`, copied secrets or `.env` in the source checkout are required. For
the current public route, these nonsecret settings remain separate in the private
file:

```dotenv
LITBLOGS_ORIGIN='https://drhscit.org'
LITBLOGS_BASE_PATH='/dren'
```

Do not put `/dren` in `LITBLOGS_ORIGIN` or run plain `docker compose` from the
repository to recover this installation. If containers or private settings are
missing, stop for operator review rather than recreating the database or guessing
credentials. Do not print resolved `compose config`, environment contents or
private log contents into shared transcripts.

### Replace SMTP settings safely

Use an approved SMTP account and its generated application password. For Zoho's
US `.com` service, use the exact account-specific server from Zoho's account
settings: `smtp.zoho.com` or `smtppro.zoho.com`. These exact hosts accept Zoho's
12-character generated application passwords; other hosts retain the 16-byte
minimum. Use the full mailbox address for `EMAIL_USERNAME` and an approved bare
sender address for `EMAIL_FROM`. Use STARTTLS on port `587`. Port `465` uses
implicit TLS and is unsupported by this sender. A normal mailbox login password
is not an application password. Other Zoho regions need a reviewed configuration;
do not shorten credentials or add spaces to satisfy a length check.

See [Zoho SMTP settings](https://www.zoho.com/mail/help/zoho-smtp.html) and
[Zoho application-specific passwords](https://help.zoho.com/portal/en/kb/accounts/manage-your-zoho-account/articles/mfa-application-specific-passwords).
SMTP authentication and accepted messages still require an actual inbox test;
healthy containers do not prove school mail filtering accepts the sender.

This procedure requires an installed application image with `runtime.py --check`
support. Deploy the reviewed image through the normal updater before using it;
an old image will reject the check instead of silently proceeding. Pause the
three LitBlogs timers and let any active jobs finish as described in
[the maintenance guide](../../maintenence.md#9-planned-maintenance-reboots-and-timer-recovery).
Record the current `app` replica count and replace `N` below with that count
(one to three). Preserve every other setting and the current image pin.

The command keeps the shared operation lock across a root-only environment
backup, editing, validation and recreation. Edit only `EMAIL_HOST`, `EMAIL_PORT`,
`EMAIL_USERNAME`, `EMAIL_PASSWORD` and `EMAIL_FROM`, preserving single-quoted
`KEY='value'` format. All three preflights validate configuration without running
the application, workers, migrations or database writers. A failed check restores
the previous private file and leaves the current services running. A failed
recreation also attempts to restore the previous configuration and services.

```bash
sudo env -i PATH=/usr/bin:/bin HOME=/root LANG=C.UTF-8 TERM="${TERM:-xterm}" \
  flock --exclusive /home/litblogs/.local/state/cit-deploy/operation.lock \
  bash -c '
    set -eu
    umask 077
    app_replicas=N
    case "$app_replicas" in 1|2|3) ;; *) echo "Set the recorded app count first" >&2; exit 1 ;; esac
    state=/home/litblogs/.local/state/cit-deploy
    env_file="$state/.env"
    previous=$(mktemp "$state/smtp-before.XXXXXXXX.env")
    install -o root -g root -m 0600 "$env_file" "$previous"
    printf "Private configuration backup: %s\n" "$previous"
    compose() {
      docker --host unix:///var/run/docker.sock compose \
        --project-name litblogs-cit \
        --project-directory /home/litblogs/www/LitBlogs \
        --env-file "$env_file" \
        -f /home/litblogs/www/LitBlogs/docker-compose.yml \
        -f "$state/compose.yaml" "$@"
    }
    preflight() {
      compose run --rm --no-deps -T --pull never --entrypoint python \
        app /opt/litblogs/deploy/container/runtime.py web --check &&
      compose run --rm --no-deps -T --pull never --entrypoint python \
        email /opt/litblogs/deploy/container/runtime.py email --check &&
      compose run --rm --no-deps -T --pull never --entrypoint python \
        reconcile /opt/litblogs/deploy/container/runtime.py reconcile --check
    }
    restore_env() { install -o root -g root -m 0600 "$previous" "$env_file"; }
    recreate() {
      compose up -d --no-deps --no-build --wait --wait-timeout 360 \
        --scale "app=$app_replicas" app email reconcile
    }
    if ! nano "$env_file" || ! preflight; then
      restore_env
      echo "Configuration check failed; previous settings restored and current services retained" >&2
      exit 1
    fi
    if ! recreate; then
      restore_env
      if ! preflight || ! recreate; then
        echo "Previous settings restored; service recovery needs operator review" >&2
        exit 1
      fi
      echo "Replacement failed; previous settings and services restored" >&2
      exit 1
    fi
  '
```

Run `sudo litblogs status` and `sudo litblogs check`, verify registration/reset
delivery to an explicitly approved test recipient, then restore the timers after
validation. Keep the root-only backup until the replacement is verified. Retire
old credentials only after replacement delivery works. `sudo litblogs start`
reuses existing container settings; it does not apply an edited `.env`.
The two approved registration domains are `henricostudents.org` and
`henrico.k12.va.us`; teachers also require an email-bound invitation. Domain
membership alone does not grant teacher or administrator privileges.

Active administrators can create 48-hour, single-use teacher invitations through
**Admin Dashboard → Invite Teacher**. Copy the resulting code and share it privately
with the intended teacher; invitation creation does not send email. The teacher
uses that same email and selects **Teacher** at signup, then verifies their email.
A new invitation replaces a previous unused code for that email. The trusted
host operator command remains available for IT.

The initial administrator credentials are kept separately in
`/home/litblogs/.litblogs-admin-initial.json`, readable only by the LitBlogs account.
Change the initial password through the application after first access, then
remove that credential file and the root commissioning copy
`/home/litblogs/.local/state/cit-deploy/bootstrap-admin.json`.

## Local access

An SSH tunnel keeps the endpoint private:

```bash
ssh -p 4243 -L 127.0.0.1:18443:127.0.0.1:18443 litblogs@drhscit.org
```

A client with the public `server.crt` can verify it without changing DNS:

```bash
curl --cacert server.crt \
  --resolve litblogs.cit.internal:18443:127.0.0.1 \
  https://litblogs.cit.internal:18443/api/health/ready
```

In private mode, browser access needs a client-only hostname mapping and trust
for the private certificate. After public-route activation, use
`https://drhscit.org/dren/`; internal probes still verify the private certificate
but send `Host: drhscit.org`. Run `verify.py` for this mode-aware verification.

## Updates, scaling and reboot behavior

`litblogs-cit.service` starts validated existing container IDs at boot and waits
for all of them to be healthy. It never rebuilds, resets the database, or applies
migrations during boot. The services also have Docker `unless-stopped` restart
policies. An unhealthy status alone is an alert condition, not an automatic
Docker restart.

`litblogs-cit-update.timer` checks GitHub main approximately every two minutes.
Public read access suffices; no organization-wide GitHub key or inbound webhook
is needed. A new commit must have all eleven required CI/container checks passing,
including both CodeQL analysis jobs; any present CodeQL alert check or CIT local
deployment controls check must also have completed successfully for that commit.
The updater builds it separately, records a failure latch, pauses application
writers for a consistent encrypted backup, applies newly added Alembic revisions,
and starts the new application image. **The PostgreSQL container is not restarted
or replaced.** Existing records and uploads remain in their named volumes.

Application updates and consistent backups have a short maintenance interval.
This is not a zero-downtime rollout. New ORM columns require an Alembic revision;
changing a Python model alone does not change an existing database schema.
Historical migration edits and infrastructure changes require operator review.

On a failed code-only update, the updater attempts to restore the prior app image.
After a migration attempt, it preserves the database and stops application writers
instead of guessing a safe schema downgrade. In both failure cases,
`update-blocked.json` blocks retries and autoscaling. Review private state, the
saved backup, schema and images before recovering and removing the latch.
The updater does not automatically install new versions of these root-owned
operations scripts or the overlay.

After an abrupt host failure during activation, inspect the latch and actual
container state before admitting traffic: Docker restart policies operate
independently of the systemd startup condition. The latch does not itself prevent
Docker from restarting a container that was running at the time of host failure.

`litblogs-cit-autoscale.timer` samples once per minute and scales only **app** from
one to three replicas. Each has two Uvicorn workers, 1 CPU and 1 GiB RAM. Two
consecutive samples averaging at least 65% CPU add one replica; five below 20%
remove one. A five-minute cooldown, healthy-container checks and at least 2 GiB
available host memory gate changes. PostgreSQL, mail and cleanup remain singletons.
At three app replicas the steady-state caps total 10.25 GiB and 8.5 CPUs.
This is bounded scaling on one server, not unlimited student capacity or a cluster.

The local gateway permits HTTP/1.1, rejects chunked bodies, applies route-specific
body limits and separate source-IP request limits. In public mode, only the exact
configured Docker gateway address can attest the client IP overwritten by host
Nginx. Other callers cannot select a bucket using a forwarded header.

## Backup and restore

`litblogs-cit-backup.timer` takes a nightly backup around 07:15 UTC. Backups also
run before application updates. The helper stops existing web/app/mail/cleanup
writers, keeps PostgreSQL running, and collects a custom database dump, roles,
uploads, PostgreSQL TLS/CA, environment, local gateway configuration and certificate.
It encrypts using PBKDF2/AES-256-CBC and authenticates the ciphertext with HMAC;
verification checks authentication before decryption, then all member checksums.

```bash
sudo python3 /home/litblogs/.local/state/cit-deploy/backup.py backup
sudo python3 /home/litblogs/.local/state/cit-deploy/backup.py verify-archive \
  /home/litblogs/.local/state/cit-deploy/backups/backup-YYYYMMDDTHHMMSSZ-ID
sudo python3 /home/litblogs/.local/state/cit-deploy/restore_rehearsal.py \
  /home/litblogs/.local/state/cit-deploy/backups/backup-YYYYMMDDTHHMMSSZ-ID
```

The restore rehearsal creates a randomly named `litblogs-cit-restore-*` project,
validates that all resources are distinct, restores roles/data/uploads/TLS,
checks migrations, and deletes only its own test resources. It starts no app,
email or public listener. It does not restore over the running installation.
Actual incident recovery over the live database requires a separate deliberate
operation with all writers stopped.

The encrypted archive requires `backup.key`, which is deliberately stored outside
the archive. Keep an independently protected off-host copy of both. The
commissioning restore tested database and upload content, file ownership, a
repeated migration, and preservation of data when a column was added.

## Validation and installation of these controls

```bash
python3 -m unittest discover -s deploy/cit-local/tests -v
LITBLOGS_TEST_HAPROXY_RUNTIME=1 python3 -m unittest discover \
  -s deploy/cit-local/tests -p test_haproxy_runtime.py -v
```

Install reviewed copies of the Python helpers, overlay and HAProxy configuration
into the private state directory. The shared `lifecycle.py` must be installed
alongside `service.py` and `backup.py` before either updated helper is used. All
installed helper files are root:root mode 0600; the state and logs directories
remain root:root mode 0700, and `.env` remains root:root mode 0600. The operator
command refuses unexpected ownership, permissions or symlinks.

From the reviewed repository root, an administrator can install the operation
helpers and permanent command under the existing maintenance lock:

```bash
sudo env -i PATH=/usr/bin:/bin HOME=/root LANG=C.UTF-8 \
  flock --exclusive /home/litblogs/.local/state/cit-deploy/operation.lock \
  /bin/sh -eu -c '
    for helper in lifecycle.py backup.py service.py verify.py autoscale.py update.py restore_rehearsal.py admin_probe.py; do
      install -o root -g root -m 0600 "$1/$helper" "$2/$helper"
    done
    install -o root -g root -m 0755 "$1/operator.py" /usr/local/bin/litblogs
  ' sh "$PWD/deploy/cit-local" /home/litblogs/.local/state/cit-deploy
sudo litblogs status
sudo litblogs check
```

Copy `operator.py` only to `/usr/local/bin/litblogs`, not into the state directory;
its source name would conflict with Python's standard `operator` module there.
Never link the installed command to a writable source checkout. These commands
do not replace the private `.env`, overlay, certificates or data. The application
updater does not install new operation helpers automatically.

Install only `systemd/litblogs-cit*` units into
`/etc/systemd/system`, validate them with `systemd-analyze verify`, reload systemd,
and enable the main service and three timers after initial startup succeeds.
All maintenance uses `operation.lock`; timers skip when the main service is inactive
or an update failure needs review. Do not install the standalone host-deployment
Nginx or PostgreSQL examples from other guides onto this shared server.
