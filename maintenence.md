# LitBlogs maintenance guide

Last reviewed: September 25, 2026. Applies to the **manually managed CIT installation** at **https://drhscit.org/dren/**, using the recovery controls introduced in PR #67. The public path is lowercase.

This guide is for the LitBlogs maintainers and CIT teacher. Commands below run on the CIT server after connecting with SSH. No passwords, app passwords, invitation codes, or secret environment values belong in this file.

## 1. Connect and check the application

Connect from your terminal:

```bash
ssh -p 4243 litblogs@drhscit.org
```

These commands work from any directory on that server:

```bash
sudo litblogs status
sudo litblogs check
```

Then open https://drhscit.org/dren/sign-in and confirm that the page loads and an authorized account can sign in.

Expected results:

- `unit` is `active`, and `recovery_blocked` is `false`.
- `app` has between **one and three** containers. All should be running and healthy.
- `postgres`, `clamav`, `email`, `reconcile`, and `web` each have **one** running, healthy container.
- `sudo litblogs check` reports success. It checks private HTTPS, readiness, assets, and runtime controls; it **does not send email**.

The main systemd unit may show `active (exited)`. That is normal for its startup controller and does not prove the containers are healthy; always inspect `litblogs status` too.

`initialize` and `migrate` are one-time jobs, not permanent services. A completed job being stopped is expected. An exit code of `1` is a failed job and should be investigated, not blindly rerun. The September 2026 incident left a historical failed migration container; recovery no longer starts it.

## 2. Protect the shared server and persistent data

| Item | Location or name |
| --- | --- |
| Public application | `https://drhscit.org/dren/` |
| Source checkout | `/home/litblogs/www/LitBlogs` |
| Compose project | `litblogs-cit` |
| Private configuration and installed helpers | `/home/litblogs/.local/state/cit-deploy` |
| Persistent environment file | `/home/litblogs/.local/state/cit-deploy/.env` |
| Private gateway | `127.0.0.1:18443` |
| Encrypted backups | `/home/litblogs/.local/state/cit-deploy/backups` |
| Backup encryption key | `/home/litblogs/.local/state/cit-deploy/backup.key` |

- Use `sudo litblogs start` for recovery. **Do not substitute plain `docker compose start` or `docker compose up -d`.** They can load the wrong settings or start initialization/migration dependencies.
- Do not delete the repository, `www`, database, uploads, or Docker volumes to fix an outage.
- Do not use `docker compose down -v`, broad Docker prune commands, or a global Docker restart as LitBlogs maintenance.
- Keep the project name `litblogs-cit`; changing it can create a different set of volumes and make the existing data appear missing.
- Do not install host PostgreSQL, replace shared Nginx configuration, or change another CIT project's containers for this application.
- Keep private state directories root-owned with mode `0700`, and `.env` and installed Python helpers root-owned with mode `0600`. `/usr/local/bin/litblogs` is root-owned with mode `0755`. Preserve the separate permissions needed by container-mounted configuration and certificates; do not recursively change everything to `0600` or loosen permissions to work around an error.

## 3. Maintenance schedule

| When | Actions |
| --- | --- |
| Each school day / before a class uses it | Run the two health commands, load the public sign-in page, and check for reported login, upload, or email problems. |
| Weekly | Check timer activity and the most recent backup result; inspect disk usage, update failures, and private error logs. |
| Monthly | Verify a recent encrypted archive, run an isolated restore rehearsal, check certificate expiry, review security updates and administrator access, and confirm the approved off-host backup is current. |
| After every deployment or configuration change | Repeat health and public sign-in checks. If email settings changed, test real delivery to an approved recipient. |
| Before each term or a large class launch | Review teacher access, capacity, backup ownership, recovery contacts, and any remaining operational follow-ups. |

These are recommended human checks. Only the update, autoscale, and nightly-backup timers described below are configured automation; this checklist does not create monitoring or reminders.

## 4. Inspect automation, backups, and logs

Check that the main service and all three timers are enabled and active:

```bash
sudo systemctl is-enabled litblogs-cit.service litblogs-cit-update.timer litblogs-cit-autoscale.timer litblogs-cit-backup.timer
sudo systemctl is-active litblogs-cit.service litblogs-cit-update.timer litblogs-cit-autoscale.timer litblogs-cit-backup.timer
sudo systemctl list-timers 'litblogs-cit-*' --all --no-pager
```

Expected schedules:

- **Updates:** approximately every two minutes after a run finishes; first check about five minutes after boot.
- **Autoscaling:** approximately every minute; first check about six minutes after boot.
- **Backups:** nightly at **07:15 UTC**, with up to five minutes of delay. This is 3:15 a.m. during Eastern daylight time or 2:15 a.m. during Eastern standard time. A missed scheduled backup can run after the timer starts again.

The job services normally return to `inactive` after completing. Inspect their result and logs, rather than expecting them to stay active:

```bash
sudo systemctl show litblogs-cit-backup.service litblogs-cit-update.service litblogs-cit-autoscale.service -p Id -p ActiveState -p Result -p ExecMainStatus
sudo journalctl -u litblogs-cit-backup.service --since '2 days ago' -n 100 --no-pager
sudo journalctl -u litblogs-cit-update.service --since '2 days ago' -n 100 --no-pager
sudo ls -lt /home/litblogs/.local/state/cit-deploy/backups
```

A successful job result alone is not enough: check that a new backup directory was actually published and that the application is healthy afterward. A skipped job can have no new backup.

To collect application logs:

```bash
sudo litblogs logs
sudo less /home/litblogs/.local/state/cit-deploy/logs/operator-latest.log
sudo less /home/litblogs/.local/state/cit-deploy/logs/service-start.log
```

`litblogs logs` saves a private snapshot of up to 100 recent lines per container from the last 24 hours, capped at 2 MiB. Save a private copy before collecting again if you need to preserve an incident. Review logs privately and remove secrets, tokens, and student information before sharing excerpts.

## 5. Recover from a 502 or stopped application

1. Record the time, failing URL, and what changed recently. Check whether an update or backup is currently running; both have a brief maintenance interval.
2. Inspect the services and collect logs:

   ```bash
   sudo litblogs status
   sudo litblogs logs
   sudo systemctl show litblogs-cit-update.service litblogs-cit-backup.service -p Id -p ActiveState -p SubState
   ```

3. If maintenance is running, allow it to finish. If the recovery command reports a busy lock, wait and check the job's progress. Do not remove `operation.lock` or launch competing commands.
4. If there is no recovery block or active maintenance, recover the installed containers:

   ```bash
   sudo litblogs start
   sudo litblogs status
   sudo litblogs check
   ```

5. Reopen the public sign-in page and verify login. When the installed administrator probe credentials are available, IT can also run:

   ```bash
   sudo python3 /home/litblogs/.local/state/cit-deploy/public-route/public_verify.py
   ```

   This checks the public route and administrator login/cookies/CSRF/logout without sending email. A stale probe password must be corrected privately; do not reset real accounts just to make the probe pass.
6. If startup fails, reports missing containers/configuration, or `recovery_blocked` is `true`, preserve the data and involve the CIT teacher. Inspect private logs and `update-blocked.json`. Review the failed update, image versions, schema, and backup before a deliberate recovery. **Do not delete the block file merely to make retries run.**
7. If private checks pass but the public page still fails, investigate the LitBlogs `/dren/` proxy route and host certificate with IT. Do not restart the database or replace the shared Nginx file.

The September 2026 outage was caused by a backup using `docker compose start`, which reran an old migration and left the application stopped. The current recovery command starts validated existing container IDs and waits for health. It does not build images, apply migrations, or reset data. An already-running unhealthy container may still require diagnosis; repeatedly running `start` is not a repair for every failure.

## 6. Deploy application updates safely

1. Make and review changes through GitHub. Database changes need a **new Alembic migration**; do not rewrite migrations that have already run.
2. Merge the reviewed change to `main`. The updater waits for the required CI checks on the exact main commit; merging alone does not prove deployment succeeded.
3. Let the timer perform the deployment. It builds the candidate, takes a consistent encrypted backup, applies new migrations when required, and activates the app. PostgreSQL remains in place. Expect a short application maintenance interval.
4. Check update logs and repeat the health/public-login checks. The root-only `last-update.json` records the last successful deployment; compare its `commit` with the intended merge. A failed attempt is recorded in the recovery latch and logs, so an older success record does not prove the newest update worked.
5. If blocked, use the recovery procedure above. After a migration attempt, do not assume that deploying older code or downgrading the schema is safe.

To ask the installed updater whether a passing main revision is available without deploying it:

```bash
sudo python3 /home/litblogs/.local/state/cit-deploy/update.py --check-only
```

Do not manually `git pull` or edit tracked files in the live checkout. The updater expects a clean checkout matching its installed image pin.

**Root-owned operational helpers are installed separately.** Merging changes to `deploy/cit-local` does not replace the installed controller files. IT must review, test, back up, and install the changed helpers under the maintenance lock, then verify their ownership and update the private control manifest. Install `lifecycle.py` before updated `backup.py` or `service.py`; copy `operator.py` only to `/usr/local/bin/litblogs`, not into the state directory. Follow the [control installation instructions](deploy/cit-local/README.md#validation-and-installation-of-these-controls).

## 7. Create, verify, and rehearse a backup

Run a manual backup before planned changes that could affect data or configuration. Choose a quiet period because writers pause during the snapshot:

```bash
sudo python3 /home/litblogs/.local/state/cit-deploy/backup.py backup
sudo litblogs status
sudo litblogs check
```

Keep the exact backup directory printed by the command. Each backup contains the database, roles, uploads, database TLS material, environment, and gateway configuration/certificate in an authenticated encrypted archive. Do not use `--leave-stopped` for routine manual backups.

Replace `backup-YYYYMMDDTHHMMSSZ-ID` below with that actual directory name:

```bash
sudo python3 /home/litblogs/.local/state/cit-deploy/backup.py verify-archive \
  /home/litblogs/.local/state/cit-deploy/backups/backup-YYYYMMDDTHHMMSSZ-ID

sudo python3 /home/litblogs/.local/state/cit-deploy/restore_rehearsal.py \
  /home/litblogs/.local/state/cit-deploy/backups/backup-YYYYMMDDTHHMMSSZ-ID
```

The rehearsal uses a separate temporary project, restores the archive, checks the schema, and removes only its own resources. It does not overwrite the live database or start an email sender or public listener. Check that it succeeds and retain the private `restore-evidence.json` with the maintenance record.

Maintain an IT-approved **off-host** copy of both the encrypted backup and its separately protected `backup.key`. Keep the complete backup directory, including its authentication metadata. A backup without its key cannot be restored; a key without its archive is not a backup. Use an approved transfer/storage method, not Git or ordinary email.

Backups currently have **no automatic deletion policy**. Agree on retention with the teacher and school IT, monitor capacity, and verify an off-host copy and restore before removing any approved old archives. Never delete live volumes or all previous backups to free space. Restoring over production requires a separate recovery plan; the commands above are validation, not a live restore.

## 8. Maintain `.env`, SMTP, and credentials

The private `.env` already persists across logouts, restarts, and application updates. Normal maintenance needs **no exports** and no `.env` in the Git checkout.

For the current public route, keep these nonsecret values separate:

```dotenv
LITBLOGS_ORIGIN='https://drhscit.org'
LITBLOGS_BASE_PATH='/dren'
LITBLOGS_GATEWAY_HOST='drhscit.org'
```

Preserve the file's single-quoted `KEY='value'` format. Do not put `/dren` in `LITBLOGS_ORIGIN` or print the resolved environment/Compose configuration into shared logs.

For an SMTP change:

1. Obtain working credentials from the account owner. Gmail uses an app password with the account's verification setup; do not use its normal login password as the SMTP credential.
2. Choose a quiet period, create a verified backup, and retain the previous configuration privately for recovery.
3. Pause the three timers and wait for active jobs as described in section 9. Record the current `app` container count from `litblogs status` (one to three).
4. Have IT edit only `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USERNAME`, `EMAIL_PASSWORD`, and the bare-address `EMAIL_FROM` under the shared operation lock. Use the fixed project, private environment, clean shell environment, and overlay from the [locked SMTP configuration procedure](deploy/cit-local/README.md#common-commands). For its interactive `nano` editor, add `TERM="${TERM:-xterm}"` alongside `PATH`, `HOME`, and `LANG` in the `env -i` command so the terminal can initialize. Preserve the current image and all other settings.
5. Before running that procedure's Compose recreation, add `--wait --wait-timeout 360 --scale app=N` to its existing `up -d --no-deps --no-build` arguments, replacing `N` with the recorded app count. Recreate only `app email reconcile`. This preserves capacity and waits for health instead of just starting containers. `litblogs start` alone does **not** apply changes to `.env`, because it reuses existing container configuration.
6. Run `litblogs status` and `litblogs check`, then send a registration/reset test to an approved recipient and confirm actual delivery. Restore the timers after validation.
7. Secure the new credentials and retire the old ones only after the replacement works. Do not commit either version.

Database passwords, signing secrets, invitation keys, and TLS settings need their own coordinated rotation plan. Changing a DB password only in `.env` does not change the existing PostgreSQL role password. Do not rerun initialization to rotate it.

## 9. Planned maintenance, reboots, and timer recovery

A CIT host reboot or Docker service restart affects other projects. Coordinate it with the teacher and server administrator, use an approved window, and take a verified backup first. Do not reboot the shared host simply because LitBlogs has a 502.

If IT needs to pause scheduled LitBlogs activity during a controlled change:

```bash
sudo systemctl stop litblogs-cit-update.timer litblogs-cit-autoscale.timer litblogs-cit-backup.timer
```

Stopping timers does **not** cancel an already-running job. Check the job services and let active work finish. Use the shared operation lock for configuration/controller changes; pausing timers alone is not a lock. This temporary pause also does **not survive a reboot**: enabled timers start again automatically. Maintenance that must remain paused across reboot needs an explicitly recorded, IT-managed persistent hold and deliberate re-enablement afterward.

After the work or an approved reboot:

```bash
sudo litblogs start
sudo litblogs status
sudo litblogs check
sudo systemctl start litblogs-cit-update.timer litblogs-cit-autoscale.timer litblogs-cit-backup.timer
```

Recheck public login and the enabled/active timer checks in section 4. Start the timers only after resolving any intentional maintenance pause or recovery block. If these existing units have accidentally become disabled, and IT has confirmed there is no intentional hold, restore boot enablement:

```bash
sudo systemctl enable litblogs-cit.service litblogs-cit-update.timer litblogs-cit-autoscale.timer litblogs-cit-backup.timer
```

Use `litblogs start` for app recovery, not `systemctl restart litblogs-cit.service`: restarting that unit also stops PostgreSQL and ClamAV. Docker restart policies do not automatically repair every unhealthy container.

## 10. Capacity, certificates, and access reviews

Weekly capacity checks are read-only:

```bash
df -h /home/litblogs /var/lib/docker
free -h
sudo du -sh /home/litblogs/.local/state/cit-deploy/backups
```

Investigate sustained growth or low free space before it affects PostgreSQL or backup creation. Ask IT to investigate Docker storage usage rather than pruning the shared host.

Autoscaling only changes `app`, from one to three replicas. It requires healthy containers, sustained load, cooldown periods, and sufficient available memory. At the limit, involve IT and measure realistic concurrent classroom activity before increasing resource caps. Mail, reconciliation, PostgreSQL, and ClamAV remain singletons. Keep ClamAV healthy and review signature-update errors; do not disable scanning to make uploads work.

Monthly, have IT check expiry and renewal ownership for all three certificate boundaries: the public `drhscit.org` certificate, the private HAProxy certificate, and PostgreSQL TLS. Plan rotation before expiry and test afterward. Do not regenerate database certificates by deleting TLS volumes or disabling verification.

Review GitHub security and dependency alerts regularly. Update application dependencies and pinned container images through reviewed changes, CI, and the deployment procedure. Coordinate host OS and Docker updates with the CIT server administrator because those affect every hosted project.

Nginx changes require review of only the LitBlogs route, staging and testing, and **`sudo nginx -t` before any reload**. Follow the [public route procedure](deploy/cit-public/README.md#stage-test-then-reload-the-host-route); never replace the complete shared configuration with a generic template.

At each term change, review who needs administrator and teacher access. Any active administrator can use **Admin Dashboard → Invite Teacher**. Invitations work once, for the specified school email, and expire after 48 hours; creating one does not send an email. Share it privately. New teachers register at `/dren/sign-up`, choose Teacher, and verify their email. Do not grant administrator access merely to invite a teacher.

For account support, check the address and **Email unverified** status in the admin dashboard before resetting a password. An admin can create a one-use verification link for an enabled, unverified account; once verified, the admin can queue a recovery email or create a one-use password-recovery link. Confirm the recipient's identity before sharing a manual link through a trusted private channel. A queued message is not proof that it reached the school inbox. Copy a manual link before closing the dialog; it is shown only once. Never record links in tickets, shared logs, or this guide.

**Delete account** permanently removes an otherwise empty user's profile and login data after exact-email confirmation. It blocks deletion when classes, schoolwork, enrollments, or registered uploads need preservation or transfer. Disable the account while resolving those records. Audit history and encrypted backups retain historical information under their normal retention rules; account deletion is not immediate erasure from backups.

## 11. Record work and remaining follow-ups

For each maintenance operation, record the date, operator, reason, deployed revision, backup directory, actions taken, verification results, and unresolved issues in an access-controlled operations log. Record credential storage locations, never credential values. For an outage, also preserve the timestamps, affected URL, container health, relevant job result, and sanitized error excerpt for the CIT teacher.

Track these items with the teacher; do not assume they are already automated:

- An approved off-host backup destination, retention policy, owner, and recovery contact.
- An independent availability/failure alert process. The existing timers run jobs; they do not guarantee that someone receives an outage notification.
- Certificate renewal/rotation ownership and deadlines.
- A dedicated HTTPS hostname for LitBlogs. `/dren/` currently shares a browser origin with other CIT apps.
- Capacity testing before broad classroom use.

For implementation details, use the [CIT operations runbook](deploy/cit-local/README.md), [public route runbook](deploy/cit-public/README.md), and [deployment overview](deploy/CIT_DEPLOY.md). Preserve the live database and involve the CIT teacher whenever a recovery step is unclear.
