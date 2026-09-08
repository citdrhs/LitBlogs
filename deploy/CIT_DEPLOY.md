# LitBlogs on CIT Deploy

Use **Custom Docker**, not the Flask template. The repository's
`docker-compose.yml` builds the app and runs its web gateway, PostgreSQL,
upload scanner, email delivery, and cleanup worker. No separate Python, Node,
or PostgreSQL installation is needed on the host.

## 1. Confirm these with school IT first

- **An exclusive HTTPS hostname**, such as `https://litblogs.YOUR-SCHOOL-DOMAIN`.
  The form's `drhscit.org/student/<slug>` and `drhscit.org/<slug>` addresses share
  an origin with other projects. They are **not suitable for private student
  accounts**. Do not enter either path as `LITBLOGS_ORIGIN` or weaken the cookie
  checks. IT must route the entire dedicated hostname, unchanged, to this stack.
- **Docker Compose support**, persistent named volumes, a terminal for staged
  first-time setup, and an x86-64 Linux host. Allow at least 6 GB RAM for the
  full stack, plus space for images, student uploads, database, and backups.
- **Approved SMTP credentials** with authenticated STARTTLS, an approved sender
  address, and the actual student/teacher email domains. Email verification and
  password resets cannot work without a mail service.
- **Encrypted, access-controlled backups and a restore rehearsal** before real
  users are admitted. Volumes survive redeploys, but volumes alone are not backups.

Only expose the `web` service. It listens on port **5000** and is published on
host loopback by default. A host proxy can use `127.0.0.1:5000`; a containerized
platform proxy needs IT to connect it to the stack's `edge` network and route to
`web:5000`. Do not route directly to `app`, PostgreSQL, or ClamAV. The portal's
Compose routing convention is not documented in the supplied form, so IT must
confirm this mapping. Require HTTPS at the outer proxy and preserve the Host
header. The included gateway enforces request size/time/rate limits; the outer
proxy must also permit the 102 MiB video-upload request limit.

## 2. Fill in the Custom Docker form

| Field | Value |
|---|---|
| Project name | `LitBlogs` |
| Repo slug | The unique slug IT approves; this is not a substitute for a dedicated hostname |
| Deployment target | The target IT has configured for that hostname |
| GitHub URL | `https://github.com/citdrhs/LitBlogs` |
| Dockerfile path | `Dockerfile` |
| Internal port | `5000` |

The form says Dockerfile path and internal port are ignored when Compose is
present. Keep `docker-compose.yml` in the repository root. Do not remove it to
force Dockerfile-only mode: the Dockerfile contains the application, not the
database, gateway, or workers.

Deploy only a reviewed main commit with passing CI **and Container verification**.
Have IT retain the exact commit, image digests, and build result, and require the
same review/checks for automatic redeploys. This source-build path differs from
the attested archive procedure in the standalone Ubuntu guide; do not claim a
portal build has that archive's attestation. If IT requires that attestation,
use the [standalone Ubuntu guide](FRESH_SERVER_SETUP.md) until the platform can
admit equivalent verified images.

## 3. Set the environment

Use [container.env.example](container.env.example) as the complete list. In CIT
Deploy use **Add variable** for each setting; do not put secrets in Git or in
Docker build arguments.

| Settings | What to enter |
|---|---|
| `LITBLOGS_ORIGIN` | The exclusive HTTPS hostname, with **no path** |
| `ALLOWED_EMAIL_DOMAINS` | Actual school domains, comma-separated; no `@` or wildcards |
| `EMAIL_HOST`, `EMAIL_PORT` | Approved SMTP host and STARTTLS port, usually `587` |
| `EMAIL_USERNAME`, `EMAIL_PASSWORD`, `EMAIL_FROM` | Approved mail login and sender; password at least 16 bytes |
| Six database passwords, `SECRET_KEY`, `TEACHER_INVITE_HMAC_KEY` | Eight **different** random secrets; generate each with `openssl rand -hex 48` |
| `GOOGLE_OAUTH_ENABLED` | `false`; leave `GOOGLE_CLIENT_ID` empty |
| Both `UPLOAD_*` attestation flags | Keep `false` until step 4 is complete |

For terminal-based setup, run from the reviewed repository root:

```bash
cp deploy/container.env.example .env
chmod 600 .env
nano .env
docker compose config --quiet
```

Keep `.env` private and backed up in the school secrets system. Do not run plain
`docker compose config` in shared logs: it prints resolved secrets. Passwords
are installed into PostgreSQL only on the **first** empty-volume initialization;
changing an environment value later does not rotate the corresponding DB role.
Keep the Compose project name stable so redeploys reuse the same volumes.

## 4. First startup, without admitting students

The portal must support this staged setup (or IT can run these commands from the
reviewed checkout). Do not press **Import & deploy** before the hosting and
recovery prerequisites are agreed.

```bash
docker compose build app
docker compose up -d postgres clamav
docker compose run --rm migrate
```

The initializer prepares private storage and PostgreSQL TLS. PostgreSQL creates
separate runtime, migration, operator, and backup roles. The migration job applies
the current schema and revokes its temporary identity-owner permission afterward.
It never resets an existing database or replaces existing uploads/keys.
Database TLS uses a locally generated, explicitly trusted certificate for the
private `postgres.internal` service, not a public HTTPS certificate. IT must
approve this trust/renewal arrangement or supply its managed equivalent; public
HTTPS remains the platform's responsibility.

Now have IT verify this is a genuinely **new, empty install**, then set
`UPLOAD_LEGACY_IMPORT_COMPLETE=true`. This is the no-legacy-data confirmation,
not an instruction to import last year's database.

Before setting `UPLOAD_BACKUP_RESTORE_VERIFIED=true`, IT must:

```bash
docker compose stop postgres clamav
docker compose ps --all
```

Confirm PostgreSQL has stopped cleanly before any physical-volume backup; never
copy a live `PGDATA` directory. Then complete the recovery checks:

1. Back up this stopped stack's PostgreSQL data, uploads, TLS/CA volumes, and
   deployment secrets together to encrypted storage inaccessible to the app.
2. Restore the backup into a **separate isolated Compose project** using the
   same image versions, volume ownership and configuration. Keep it off public
   routing, with mail delivery disabled at the network boundary.
3. Confirm PostgreSQL opens, the schema is current, private file contents and
   ownership match, and the restored data can be read. Record the date/result,
   recovery owner, schedule, and retention. Keep the original stack untouched.

Do not use the disposable CI smoke test as a production-backup attestation.
The host-specific backup helpers in the standalone guide are not drop-in
container-volume restore tools. IT must supply and verify the platform's backup
procedure; startup intentionally remains blocked until that is done.

After those checks, save both flags as `true` and start the application:

```bash
docker compose up -d
docker compose ps
```

Wait for `web`, `app`, `postgres`, `clamav`, `email`, and `reconcile` to be healthy.
ClamAV's first signature load can take several minutes. Initialization and
migration should finish successfully; they are not permanent services.

## 5. Create the first administrator and invite teachers

Before opening student registration, use the trusted host terminal:

```bash
docker compose --profile operators run --rm bootstrap-admin --confirm-empty-install
docker compose --profile operators run --rm invitation create --operator school-it --expires-hours 48
```

The first command privately prompts for the administrator username, school email,
and password. It refuses to bootstrap a populated installation. The second asks
for a teacher's allowed school email and returns a one-time invitation; send it
privately to that teacher. Never paste invitations/passwords into shared logs.

At the dedicated HTTPS URL, test a synthetic student signup, verification email,
sign-in, class join, post, attachment, sign-out, and password reset. Also verify
teacher preview and student visibility. Confirm the Help video and captions load
and seeking works. Remove synthetic accounts through the normal admin controls
before admitting students.

The gateway intentionally does not trust arbitrary forwarded IP headers. If the
platform hides all clients behind one proxy address, its default rate-limit
bucket is shared. IT must configure an exact trusted proxy CIDR and verify client
IP handling before wider rollout; never use `set_real_ip_from 0.0.0.0/0`.

## Updates and future Google sign-in

For each reviewed update: take a consistent backup, stop `web app email reconcile`,
build the new app image, run the migration job, then `docker compose up -d` and
repeat the smoke checks. Never use `docker compose down --volumes` on production.
Database migrations may not be reversible; rolling back an image alone is not a
database rollback. Keep the previous image and a verified coupled backup.

Once Google is approved, configure its Web client for this exact origin, set
`GOOGLE_CLIENT_ID`, change `GOOGLE_OAUTH_ENABLED=true`, and recreate `app` and
`reconcile`. Password accounts stay enabled. Existing password accounts are **not
automatically linked** to Google: the current backend only signs in identities
that were explicitly registered with that provider. A reviewed account-linking
flow is a separate prerequisite for moving existing users to SSO. Until then,
those users keep password sign-in. Do not delete/recreate accounts or posts to
work around linking. Microsoft stays disabled.
