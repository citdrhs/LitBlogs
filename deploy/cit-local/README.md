# Local LitBlogs installation on CIT

This deployment uses the root Dockerfile and Compose services, with this overlay
replacing the bundled Nginx gateway with HAProxy. The only published endpoint is
`127.0.0.1:18443`. It uses a private certificate for
`https://litblogs.cit.internal:18443`; no DNS, public routing, host Nginx,
other CIT services, or host PostgreSQL configuration is changed.

The source checkout is `/home/litblogs/www/LitBlogs`. Root-owned settings,
installed operations scripts, certificates, logs and recovery archives are in
`/home/litblogs/.local/state/cit-deploy` (directory mode 0700, environment 0600).
The stable Compose project is **litblogs-cit**. Never change its name to update
the application, and never delete its volumes to redeploy.

## Current follow-up

- **TODO: replace the rejected SMTP credentials and verify actual delivery.**
  Until then, email verification and password reset are unavailable even when
  container health checks pass. The initial administrator is provisioned through
  the trusted bootstrap command; this does not bypass verification for students.
- Public release still needs a dedicated approved HTTPS hostname and routing,
  appropriate trusted-proxy/rate-limit configuration, load validation and an
  off-host recovery schedule. This installation intentionally remains local.
- Store the backup encryption key separately from the encrypted archives, and
  monitor disk usage/retention. Automated backups are retained without deletion.

## Common commands

Log in using `ssh -p 4243 litblogs@drhscit.org`, then define this helper in a
trusted administrator shell. It always targets only the named LitBlogs stack:

```bash
lc() {
  sudo docker --host unix:///var/run/docker.sock compose \
    --project-name litblogs-cit \
    --project-directory /home/litblogs/www/LitBlogs \
    --env-file /home/litblogs/.local/state/cit-deploy/.env \
    -f /home/litblogs/www/LitBlogs/docker-compose.yml \
    -f /home/litblogs/.local/state/cit-deploy/compose.yaml "$@"
}
lc ps
sudo systemctl status litblogs-cit.service --no-pager
sudo systemctl list-timers 'litblogs-cit-*' --no-pager
sudo python3 /home/litblogs/.local/state/cit-deploy/verify.py
```

Do not print resolved `compose config` or environment contents into shared logs.
Use `lc config --quiet` for validation. To replace mail credentials, hold the
shared operation lock across editing and recreating the mail-related services,
keeping the private `.env` single-quoted `KEY='value'` format.
Set the approved `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USERNAME`, `EMAIL_PASSWORD`
and bare-address `EMAIL_FROM`, then recreate only these services:

```bash
sudo flock --exclusive /home/litblogs/.local/state/cit-deploy/operation.lock \
  bash -c 'nano /home/litblogs/.local/state/cit-deploy/.env &&
  docker --host unix:///var/run/docker.sock compose \
    --project-name litblogs-cit \
    --project-directory /home/litblogs/www/LitBlogs \
    --env-file /home/litblogs/.local/state/cit-deploy/.env \
    -f /home/litblogs/www/LitBlogs/docker-compose.yml \
    -f /home/litblogs/.local/state/cit-deploy/compose.yaml \
    up -d --no-deps --no-build app email reconcile'
```

Authenticate to the approved STARTTLS relay and verify registration/reset delivery
to an explicitly approved test recipient. No mail was sent during commissioning.
The two approved registration domains are `henricostudents.org` and
`henrico.k12.va.us`; teachers also require an email-bound invitation. Domain
membership alone does not grant teacher or administrator privileges.

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

Browser access needs a client-only hostname mapping and trust for the private
certificate. Do not add public DNS or route the shared CIT hostname to this
installation as part of local testing.

## Updates, scaling and reboot behavior

`litblogs-cit.service` starts the existing pinned containers at boot and waits for
all of them to be healthy. It never rebuilds, resets the database, or applies
migrations during boot. The services also have Docker `unless-stopped` restart
policies. An unhealthy status alone is an alert condition, not an automatic
Docker restart.

`litblogs-cit-update.timer` checks GitHub main approximately every two minutes.
Public read access suffices; no organization-wide GitHub key or inbound webhook
is needed. A new commit must have all nine required CI/container checks passing.
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
body limits and separate source-IP request limits. SSH clients share a source
bucket; broader use needs the routing and capacity review mentioned above.

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
into the private state directory. Install only `systemd/litblogs-cit*` units into
`/etc/systemd/system`, validate them with `systemd-analyze verify`, reload systemd,
and enable the main service and three timers after initial startup succeeds.
All maintenance uses `operation.lock`; timers skip when the main service is inactive
or an update failure needs review. Do not install the standalone host-deployment
Nginx or PostgreSQL examples from other guides onto this shared server.
