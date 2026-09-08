# Fresh LitBlogs server setup

This is the complete short path for one new **Ubuntu 24.04.4 LTS** server with no LitBlogs data to migrate. Run the eight stages in order. The deterministic work is in the reviewed helper. If a stage fails, use the matching section of [`docs/operations/production-runbook.md`](../docs/operations/production-runbook.md).

## Quick path

1. Bootstrap the host and clone `main` into `~/www`.
2. Admit the exact reviewed, attested release artifact.
3. Let the release-local helper install and test the toolchain.
4. Configure PostgreSQL and private environments.
5. Migrate and make the first coupled backup.
6. Prove that backup on an isolated restore host.
7. Record the four approvals, bootstrap, and activate.
8. Run fail-closed smoke tests.

This page has eight paste blocks, followed by four final commands. Keep one sudo-capable shell open. Run each editor, login, or password command alone. Keep secrets out of Git, shell history, argv, and exported shell variables; enter them only in the named private files or password prompts.

## 1. Bootstrap Ubuntu and clone the staging checkout

**Approval gate:** school IT must provide DNS, the email domain and STARTTLS SMTP relay, an ACME contact, and a school-CA-issued PostgreSQL certificate/key/CA whose SAN contains `iPAddress:127.0.0.1`. It must approve the exact GitHub CLI package version and SHA-256. The host firewall/NAT must preserve approved management/SSH, allow inbound TCP `80` and `443`, and keep PostgreSQL `5432`, ClamAV `3310`, and Uvicorn `8000` loopback-only. Record the active host firewall; never guess a rule that could lock you out. A self-signed leaf certificate is not production approval.

Edit the five public values, then paste stage 1:

```bash
set -euo pipefail
export SITE_HOST='REPLACE_WITH_PUBLIC_DNS_NAME'
export SCHOOL_EMAIL_DOMAIN='REPLACE_WITH_SCHOOL_EMAIL_DOMAIN'
export ACME_CONTACT_EMAIL='REPLACE_WITH_ACME_CONTACT_EMAIL'
export GH_VERSION='REPLACE_WITH_SCHOOL_APPROVED_APT_VERSION'
export GH_DEB_SHA256='REPLACE_WITH_SCHOOL_APPROVED_64_HEX_SHA256'
for value in "$SITE_HOST" "$SCHOOL_EMAIL_DOMAIN" "$ACME_CONTACT_EMAIL" \
  "$GH_VERSION" "$GH_DEB_SHA256"; do
  case "$value" in ''|REPLACE_WITH*) echo 'Replace every stage-1 value.' >&2; exit 1;; esac
done
[[ "$SITE_HOST" =~ ^[a-z0-9.-]+$ && "$SCHOOL_EMAIL_DOMAIN" =~ ^[a-z0-9.-]+$ ]]
[[ "$ACME_CONTACT_EMAIL" == *@*.* && "$GH_DEB_SHA256" =~ ^[0-9a-f]{64}$ ]]

sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
  ca-certificates curl git gnupg jq postgresql-common wget
sudo install -d -o root -g root -m 0755 /etc/apt/keyrings
GH_KEYRING=$(mktemp)
wget -nv -O "$GH_KEYRING" https://cli.github.com/packages/githubcli-archive-keyring.gpg
sudo install -o root -g root -m 0644 "$GH_KEYRING" /etc/apt/keyrings/githubcli-archive-keyring.gpg
rm -f -- "$GH_KEYRING"
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | \
  sudo tee /etc/apt/sources.list.d/github-cli.list >/dev/null
sudo apt-get update
GH_PACKAGE_DIR=$(mktemp -d)
(cd "$GH_PACKAGE_DIR" && apt-get download "gh=$GH_VERSION")
GH_DEB=$(find "$GH_PACKAGE_DIR" -maxdepth 1 -type f -name 'gh_*.deb' -print -quit)
printf '%s  %s\n' "$GH_DEB_SHA256" "$GH_DEB" | sha256sum --check -
sudo apt-get install -y "$GH_DEB"
sudo apt-mark hold gh
rm -r -- "$GH_PACKAGE_DIR"

if id litblogs >/dev/null 2>&1; then
  test "$(getent passwd litblogs | cut -d: -f6)" = /home/litblogs
  test "$(getent passwd litblogs | cut -d: -f7)" = /bin/bash
  test "$(id -gn litblogs)" = litblogs
else
  sudo useradd --system --create-home --home-dir /home/litblogs \
    --shell /bin/bash --user-group litblogs
fi
test "$(id -u litblogs)" -lt 1000
test "$(id -G litblogs | wc -w)" -eq 1
sudo passwd --lock litblogs
sudo install -d -o litblogs -g litblogs -m 0750 /home/litblogs
sudo install -d -o root -g root -m 0755 /etc/litblogs
sudo install -d -o root -g root -m 0700 /srv/litblogs-release-quarantine
sudo -iu litblogs bash -se <<'LITBLOGS'
set -euo pipefail
mkdir -p ~/www
cd ~/www
git clone https://github.com/citdrhs/LitBlogs.git
cd LitBlogs
git switch main
git pull --ff-only
LITBLOGS
```

The clone is for staging and tests only. **Do not deploy the clone.**

## 2. Admit the reviewed release

GitHub login is interactive, so run `gh auth login --hostname github.com --git-protocol https` by itself.

Stage 2 dispatches the protected workflow, proves the exact SHA and attestation counts, and transfers files into root custody. Do not generate `RELEASE-MANIFEST` locally or deploy locally assembled files.

```bash
set -euo pipefail
gh auth status --hostname github.com
sudo -iu litblogs git -C /home/litblogs/www/LitBlogs pull --ff-only
REVIEWED_SHA=$(sudo -iu litblogs git -C /home/litblogs/www/LitBlogs rev-parse HEAD)
[[ "$REVIEWED_SHA" =~ ^[0-9a-f]{40}$ ]]
SHORT_SHA=${REVIEWED_SHA:0:12}
RELEASE_ID="litblogs-$SHORT_SHA"
DISPATCHED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
gh workflow run release.yml --repo citdrhs/LitBlogs --ref main
RUN_ID=''
for attempt in $(seq 1 30); do
  RUN_ID=$(gh run list --repo citdrhs/LitBlogs --workflow release.yml --branch main \
    --commit "$REVIEWED_SHA" --event workflow_dispatch --limit 20 \
    --json databaseId,createdAt \
    --jq "[.[] | select(.createdAt >= \"$DISPATCHED_AT\")][0].databaseId // empty")
  test -n "$RUN_ID" && break
  sleep 5
done
test -n "$RUN_ID"
gh run watch "$RUN_ID" --repo citdrhs/LitBlogs --exit-status
test "$(gh run view "$RUN_ID" --repo citdrhs/LitBlogs --json headSha --jq .headSha)" = "$REVIEWED_SHA"

DOWNLOAD_DIR="$HOME/litblogs-release-download-$SHORT_SHA"
test ! -e "$DOWNLOAD_DIR"
install -d -m 0700 "$DOWNLOAD_DIR"
gh run download "$RUN_ID" --repo citdrhs/LitBlogs --name "litblogs-$SHORT_SHA" --dir "$DOWNLOAD_DIR"
cd "$DOWNLOAD_DIR"
sha256sum --check SHA256SUMS
gh attestation verify "litblogs-$SHORT_SHA.tar.gz" --repo citdrhs/LitBlogs \
  --signer-workflow citdrhs/LitBlogs/.github/workflows/release.yml \
  --source-ref refs/heads/main --source-digest "$REVIEWED_SHA" \
  --deny-self-hosted-runners --format json >provenance-attestations.json
gh attestation verify "litblogs-$SHORT_SHA.tar.gz" --repo citdrhs/LitBlogs \
  --signer-workflow citdrhs/LitBlogs/.github/workflows/release.yml \
  --source-ref refs/heads/main --source-digest "$REVIEWED_SHA" \
  --deny-self-hosted-runners --predicate-type https://cyclonedx.org/bom \
  --format json >sbom-attestations.json
PROVENANCE_COUNT=$(jq length provenance-attestations.json)
SBOM_COUNT=$(jq length sbom-attestations.json)
test "$PROVENANCE_COUNT" -eq 1
test "$SBOM_COUNT" -eq 2
jq -S -c '.[].verificationResult.statement.predicate' sbom-attestations.json | sort >verified_predicates
jq -S -c . python-sbom.cdx.json frontend-sbom.cdx.json | sort >checksummed_predicates
cmp verified_predicates checksummed_predicates
printf '%s\n' "$REVIEWED_SHA" >REVIEWED-COMMIT
chmod 0600 ./*
sha256sum "litblogs-$SHORT_SHA.tar.gz" SHA256SUMS python-sbom.cdx.json \
  frontend-sbom.cdx.json provenance-attestations.json sbom-attestations.json \
  REVIEWED-COMMIT >CUSTODY-SHA256
QUARANTINE="/srv/litblogs-release-quarantine/$RELEASE_ID"
sudo install -d -o root -g root -m 0700 "$QUARANTINE"
for file in "litblogs-$SHORT_SHA.tar.gz" SHA256SUMS python-sbom.cdx.json \
  frontend-sbom.cdx.json provenance-attestations.json sbom-attestations.json \
  REVIEWED-COMMIT CUSTODY-SHA256; do
  sudo install -o root -g root -m 0600 "$file" "$QUARANTINE/$file"
done
sudo sh -c 'cd "$1" && sha256sum --check CUSTODY-SHA256' sh "$QUARANTINE"
printf 'Run ID: %s\nReviewed SHA: %s\nRelease ID: %s\n' "$RUN_ID" "$REVIEWED_SHA" "$RELEASE_ID"
```

**Approval gate:** record the run, 40-character SHA, checksum, one provenance result, and two SBOM results. Then run `read -r -p 'Enter REPLACE_WITH_APPROVED_RELEASE_ID: ' APPROVED_RELEASE_ID` alone. Stage 3 refuses any value except the just-verified release:

```bash
set -euo pipefail
test "$APPROVED_RELEASE_ID" = "$RELEASE_ID"
# From this point, never re-select it from the mutable staging checkout.
REVIEWED_SHA=$(sudo sed -n '1p' "$QUARANTINE/REVIEWED-COMMIT")
RELEASE="/opt/litblogs/releases/$RELEASE_ID"
sudo test ! -e "$RELEASE"
sudo install -d -o root -g root -m 0755 /opt/litblogs /opt/litblogs/releases "$RELEASE"
sudo sh -c 'cd "$1" && sha256sum --check CUSTODY-SHA256' sh "$QUARANTINE"
sudo tar --extract --gzip --no-same-owner --file "$QUARANTINE/litblogs-$SHORT_SHA.tar.gz" --directory "$RELEASE"
sudo grep -Fx "commit=$REVIEWED_SHA" "$RELEASE/RELEASE-MANIFEST"
sudo chown -R root:root "$RELEASE"
sudo chmod -R go-w "$RELEASE"
sudo install -o root -g root -m 0600 "$RELEASE/deploy/fresh-install.conf.example" \
  /etc/litblogs/fresh-install.conf
HELPER="$RELEASE/deploy/scripts/fresh_server_setup.sh"
```

## 3. Install the exact toolchain and test `main`

Run `sudoedit /etc/litblogs/fresh-install.conf` by itself. Copy the public values, printed release ID/SHA, three PostgreSQL PKI paths, and audit operator ID. Leave all four approvals `false`.

Paste stage 4:

```bash
sudo "$HELPER" toolchain
sudo "$HELPER" stage-tests
```

This installs checksummed **Python 3.13.15** and **Node.js 24.20.0**, then PostgreSQL 17, Nginx, ClamAV, and Certbot. Node uses `--no-same-owner`, then `chown -R root:root`; PGDG uses `apt.postgresql.org.sh -y`. The staging checkout is never a release.

## 4. Configure PostgreSQL and the private environments

Use independent managed passwords: migrator/runtime/backup need 16 UTF-8 bytes; each operator needs at least 32 UTF-8 bytes with at least 8 distinct characters. Stage 5 prompts for staged and current values, then proves current succeeds while wrong and ROTATED-OLD passwords fail. Run it alone; if interrupted during passwords, resume with `sudo "$HELPER" postgres-passwords` before migrating:

```bash
sudo "$HELPER" postgres
```

Install each template, then run each editor command **alone**:

- `sudo install -o root -g litblogs -m 0640 "$RELEASE/deploy/litblogs.production.env.example" /etc/litblogs/litblogs.env`
- `sudoedit /etc/litblogs/litblogs.env`
- `sudo install -o root -g litblogs-reset -m 0640 "$RELEASE/deploy/password-reset.production.env.example" /etc/litblogs/password-reset.env`
- `sudoedit /etc/litblogs/password-reset.env`
- `sudo install -o root -g root -m 0600 /dev/null /run/litblogs-migration.env`
- `sudoedit /run/litblogs-migration.env` — enter only `LITBLOGS_MIGRATION_DATABASE_URL=<protected-migrator-url>`.
- `sudo install -o root -g root -m 0600 /dev/null /run/litblogs-backup.env`
- `sudoedit /run/litblogs-backup.env` — enter only `DATABASE_URL=<protected-litblogs_backup-url>`.

Keep `UPLOAD_REGISTRY_SCHEMA_READY=false`, `UPLOAD_LEGACY_IMPORT_COMPLETE=false`,
and `UPLOAD_BACKUP_RESTORE_VERIFIED=false`. The supplied production template
enables email/password registration and mandatory email verification delivery;
both OAuth providers are disabled and their IDs are blank.

## 5. Migrate and create the first recovery set

Stage 6 runs `deployment_check --preflight`, grants `litblog_identity_owner` only around Alembic, always revokes it, proves upload storage is empty, and runs `backup_postgres.py`. Temporary credentials are removed on success, error, hangup, or interrupt.

```bash
sudo "$HELPER" prepare
```

Do not start the app yet. Preserve the complete four-file coupled recovery set
from `/srv/litblogs-backups` for the next stage.

## 6. Prove restore on an isolated host

On a disposable Ubuntu 24.04.4 host, copy the same admitted release to the same `/opt/litblogs/releases/...` path, root-owned with no group/other writes, and copy rehearsal-only PKI. Run `read -r -p 'Admitted release directory: ' RESTORE_RELEASE` alone and enter that absolute path. Run `sudo install -d -o root -g root -m 0755 /etc/litblogs`. While the host contains no real data and still has internet, install the template and edit it alone:
`sudo install -o root -g root -m 0600 "$RESTORE_RELEASE/deploy/fresh-restore.conf.example" /etc/litblogs/fresh-restore.conf`,
then `sudoedit /etc/litblogs/fresh-restore.conf`. Enter the same 40-character `REVIEWED_SHA`; leave `ISOLATION_APPROVED=false`.

Paste stage 7. This installs the restore Python environment before isolation and prompts for the rehearsal-only password:

```bash
RESTORE_HELPER="$RESTORE_RELEASE/deploy/scripts/fresh_restore_rehearsal.sh"
sudo "$RESTORE_HELPER" install-host
sudo "$RESTORE_HELPER" restore-prepare
```

**TRANSFER PAUSE:** remove every default route and every firewall, VPN, proxy, management, or credential path to production, students, teachers, and the internet. School IT signs the isolation check. Change only `ISOLATION_APPROVED=true`, then transfer exactly the accepted dump, upload archive, inventory, and manifest into `/srv/litblogs-restore/staging`.
The restore host must have no route or credential to production, students, teachers, or the internet.

Run `sudo install -o root -g root -m 0600 /dev/null /run/litblogs-restore.env`, then run
`sudoedit /run/litblogs-restore.env` alone. Enter only
`DATABASE_URL=<protected-isolated-restore-DBA-url>`. Paste stage 8:

```bash
sudo "$RESTORE_HELPER" restore-verify
```

The script requires `test -z "$(ip route show default)"`, exact release SHA custody, four root-owned files, five passwordless `NOLOGIN` stand-ins, and two `restore_verify_postgres.py` passes; the second reports `current_head` and zero federated identities. Preserve both reports. If verification fails, retain its output, choose new synthetic database/upload targets in the restore config, and recreate the temporary credential file before retrying; never delete or overwrite the failed targets.

## 7. Record approvals, bootstrap, and activate

Back on production, run `sudoedit /etc/litblogs/litblogs.env` alone and change the three upload-readiness values to `true`. Run `sudoedit /etc/litblogs/fresh-install.conf` alone and change a gate only after attaching its evidence:

- `HOST_FIREWALL_APPROVED=true`: the recorded host rules meet stage 1.
- `EGRESS_POLICY_APPROVED=true`: the root-owned systemd drop-ins, exact-address
  allowlist, exact-port cgroup/network policy, negative probes, and boot markers
  from the long runbook pass. `IPAddressAllow` alone is not an exact-port rule.
- `RESTORE_REHEARSAL_APPROVED=true`: stage 6 and both reports passed.
- `RECOVERY_POLICY_APPROVED=true`: school IT owns continuous WAL archiving for
  a 15-minute RPO, recurring coupled backups, encrypted off-host copies,
  alerts, 35-daily/12-month-end retention, legal hold, and recurring isolated
  restore rehearsal.

Install and edit the invitation config alone:
`sudo install -o root -g root -m 0600 "$RELEASE/deploy/invitation-operator.example.json" /etc/litblogs/invitation-operator.json`,
then `sudoedit /etc/litblogs/invitation-operator.json`.

Run these four commands one at a time. `post-restore` runs postflight, privately
bootstraps the only initial admin, installs systemd/Nginx, obtains TLS with
`--non-interactive --agree-tos --no-eff-email`, and leaves push/reminders off.
Disable session recording before `invite-teacher`; the raw invitation is shown once. Teachers cannot self-select that role.

1. `sudo "$HELPER" post-restore`
2. `sudo "$HELPER" invite-teacher`
3. `sudo "$HELPER" activate`
4. `sudo "$HELPER" smoke`

Activation uses `release_switch.py`, enables the password-reset/email
verification and upload-reconciliation timers, and keeps
`litblogs-reminders.timer` disabled because `PUSH_NOTIFICATIONS_ENABLED=false`.
The service's `ProtectHome=true` policy means production cannot read the `~/www` clone.

## 8. Verify users now; enable Google only after approval

In a private browser with synthetic accounts, verify the invited teacher must open the email verification link before sign-in, then can create a class and join code. Verify a student can sign up, verify email, sign in, reset the password, join, post, upload/remove image/video/PDF, and see the rendered post in teacher/student views. Retain no private data in logs.

Email/password remains the production signup method. After county approval,
create a Google Web Application client for the exact site origin, change only
these protected values, rerun preflight/postflight, and restart the web service:

```dotenv
GOOGLE_OAUTH_ENABLED=true
GOOGLE_CLIENT_ID=<approved-client-id>.apps.googleusercontent.com
LOCAL_PASSWORD_REGISTRATION_ENABLED=true
```

No frontend rebuild is required. Keep password sign-in until Google is proven.
Do not auto-link existing accounts by email; that needs a separately reviewed,
authenticated account-link flow.
