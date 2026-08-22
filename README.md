# LitBlogs

A modern blogging platform for educational institutions, designed for teachers and students to share literary content, collaborate, and engage in classroom discussions.

## Table of Contents
- [Overview](#overview)
- [System Requirements](#system-requirements)
- [Production Deployment](#production-deployment)
- [Environment Configuration](#environment-configuration)
- [Maintenance Guide](#maintenance-guide)
## Overview

LitBlogs is a full-stack web application built with:
- **Backend**: FastAPI (Python)
- **Frontend**: React with Vite
- **Database**: PostgreSQL
- **Authentication**: JWT, Google OAuth, Microsoft OAuth

The platform supports role-based access (students, teachers, admins), class management, rich-text blog posts, comments, and user profiles.

## System Requirements

### Production Server
- Ubuntu 20.04 LTS or newer
- Python 3.10+
- Node.js 18+
- PostgreSQL 12+
- NGINX
- 2GB RAM minimum (4GB recommended)
- 20GB storage minimum

## Production Deployment

### Prerequisites
1. Python 3.10+
2. Node.js 18+
3. PostgreSQL 12+
4. Git

### Clone Repository
Run this to get into the LitBlogs account model:
```bash
sudo su litblogs
```
Go to /www/ by running the following command:
```bash
cd ~
cd www
```
Then clone the repository:
```bash
git clone https://github.com/citdrhs/LitBlogs.git
cd LitBlogs/litblogs
```
Run the commmand with sudo if you need permissions to clone the repository.

### Backend Setup
1. Create and activate a virtual environment:
```bash
python -m venv myvenv
chown -R $USER:$USER /var/www/LitBlogs/litblogs/myvenv
chown -R $USER:$USER /var/www/LitBlogs/litblogs
source myvenv/bin/activate # On Windows: myvenv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

`requirements.txt` now includes `pywebpush`, which is required for browser push notifications.

3. Add the upload directory to the backend:
While in /www/LitBlogs/litblogs, run the following command:
```bash
mkdir -p uploads
cd uploads
mkdir -p images
mkdir -p files
mkdir -p videos
mkdir -p profile_images
mkdir -p cover_images
```
Then go back to the main account by running
```bash
exit
```

4. Install postgres:
```bash
sudo apt-get install postgresql postgresql-contrib
```
Create a user with the following command:
```bash
sudo -u postgres psql -c "CREATE USER postgres WITH PASSWORD 'postgres';"
```
Open psql:
```bash
sudo -u postgres psql
```
Create a database with the following command:
```bash
CREATE DATABASE litblogs;
```
Then exit psql:
```bash
\q
```
Or type exit
Then run the service called blog to start the backend(service was already created)

5. Run the backend server:
```bash
chmod +x /home/litblogs/www/LitBlogs/litblogs/run.sh
sudo systemctl start blog
```

### Frontend Setup
Go back to the litblogs account model and go to /www/LitBlogs/litblogs
1. Install dependencies:
```bash
npm install --force
```

2. Run the frontend server:
```bash
npm run build
```
Go back to the main account by running
```bash
exit
```
3. Go to the nginx directory and edit the file:
```bash
sudo nano /etc/nginx/sites-enabled/tutorial
```
Add the following to the file:
```bash
server {
    listen 7001;
    listen [::]:7001;
    server_name drhscit.org www.drhscit.org;

    root /home/litblogs/www/LitBlogs/litblogs/dist;
    index index.html;

    # Frontend SPA
    location / {
        rewrite ^/dren(.*)$ /$1 last;
        try_files $uri $uri/ /dren/index.html;
    }

    # Backend API proxy
    location /dren/api/ {
        rewrite ^/dren/api/(.*)$ /api/$1 break;
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
        proxy_pass_request_headers on;
    }

    # Uploads route
    location ^~ /uploads/ {
        return 307 /dren/api$uri$is_args$args;
    }
}
```




## Identity and session operations

Browser authentication is backed by digest-only server-side session records. Logout
revokes the current session; password changes, password resets, account disablement,
and account deletion revoke all sessions. Issuance is serialized per account and keeps
only the ten newest session rows, invalidating the deterministic oldest token when the
cap is reached. Disabling an account also invalidates every pending, processing, or
delivered password-reset row in the same transaction, and a successful password change
does the same before commit. Reset delivery and consumption serialize against the
enabled account row. Each reset-delivery lease stores only a random claim digest;
completion uses compare-and-swap on that digest, so a timed-out worker cannot overwrite
a newer reclaimed delivery. Account deletion takes that same user-row lock before touching
session, reset, or content rows, so issuance and deletion cannot leave an orphaned live
session or deadlock in reverse lock order. Deploying migration `0003` intentionally
invalidates older stateless JWT cookies, because no session backfill is performed.
The migration also invalidates every outstanding password-reset row so plaintext bearer
tokens from legacy releases cannot remain usable at rest; users request a new link.

Teacher accounts use one-time, expiring invitations bound to the normalized school
email address. There is no public invitation endpoint and no shared teacher access
code. Configure a dedicated random `TEACHER_INVITE_HMAC_KEY` (at least 32 bytes,
different from `SECRET_KEY`) in the server secret store. Run the operator commands
only from the trusted application host through the reviewed operator wrapper. That
wrapper supplies a minimal purpose-specific JSON config on inherited file descriptor 3:
only `purpose`, the dedicated least-privilege PostgreSQL URL, invitation HMAC key, and
allowed school domains. Purpose hard-binds the exact operator role; a configurable
expected-role field is rejected. It must not expose the application JWT, OAuth, SMTP,
VAPID, or admin secrets. The URL uses exact target `127.0.0.1:5432/litblogs`, a dedicated strong
credential, `sslmode=verify-full`, and exact root-owned CA path
`/etc/litblogs/postgres-root-ca.pem`; runtime verifies every ancestor is root-owned and
not group/world writable. The CLI also verifies `current_user`, role attributes and
memberships, and an EXECUTE-only SECURITY DEFINER boundary with no direct table or
sequence privileges.
The target email is read from a no-echo prompt
and must never be placed in argv, an environment variable, shell history, or process
metadata. The operator identifier is intended audit data:

```bash
python -m manage_teacher_invitations create --expires-hours 24 --operator "$REVIEWED_OPERATOR"
python -m manage_teacher_invitations revoke --operator "$REVIEWED_OPERATOR"
python -m manage_accounts disable --operator "$REVIEWED_OPERATOR"
python -m manage_accounts enable --operator "$REVIEWED_OPERATOR"
```

For non-interactive operation, provide exactly one email line on a protected stdin file
descriptor sourced from the approved secret/PII store. The file path and descriptor
metadata must not contain the address, and the file must be owner-readable only.
The protected config descriptor and stdin email channel are separate; neither secret is
accepted from command arguments or the web application's environment.

The create command prints the raw invitation once. Deliver it only through an approved
private channel and exclude that stdout from session recordings, CI artifacts, command
transcripts, and logs. Every operator command transaction records its bounded actor,
action/outcome, and a domain-separated HMAC target reference; it never records the raw
email, invitation, or session value. The database stores only invitation/session
digests. The admin-only account-status API uses the same transactional audit contract,
and rolls back account/session changes if its audit record cannot be stored. See
`litblogs/migrations/README-identity-controls.md` for migration, smoke tests, and the
token-safe application rollback procedure.

Email identity is restricted to ASCII school addresses and is case-insensitive. New
accounts remove U+0020 padding and store a lowercase address; every remaining space,
ASCII control character (C0 plus DEL), and non-ASCII byte is rejected. PostgreSQL
uses locale-independent ASCII `translate(btrim(email), ...)`, equivalent control checks, and a
`COLLATE "C"` canonical index rather than locale-sensitive `lower()`, plus
canonical uniqueness. The teacher/account association is the unique, non-null
`teachers.user_id`; the denormalized teacher email is reconciled to the user row.
Migration preflight must reconcile any invalid, unmappable, or duplicate legacy
identities through a reviewed school process before the constraints and indexes are
created. Password registration accepts only the
configured school email domains in production and returns the same generic accepted
response when an address is ineligible.

Generic acceptance prevents direct account enumeration, but password registration in
this slice does not prove control of the submitted school mailbox. Production must keep
password registration disabled in favor of verified school SSO, or add a reviewed
pending-email/roster verification flow before activating password accounts.

## Environment Configuration

Push reminders (outside the app) require VAPID keys and related settings in your backend env.

In `.env` (or your active environment file), set:

```dotenv
VAPID_PUBLIC_KEY=<your_public_key>
VAPID_PRIVATE_KEY=<your_private_key>
VAPID_SUBJECT=mailto:your-email@example.com
PUSH_REMINDER_INTERVAL_SECONDS=300
PUSH_ALLOWED_ENDPOINT_HOSTS=fcm.googleapis.com,updates.push.services.mozilla.com,web.push.apple.com,.notify.windows.com
PUSH_DELIVERY_TIMEOUT_SECONDS=5
```

Generate keys with:

```bash
npx web-push generate-vapid-keys
```

Important notes:
- Push notifications require HTTPS in production.
- In development, localhost works for service workers and notification testing.
- The server checks reminders on startup, then every `PUSH_REMINDER_INTERVAL_SECONDS`.
- Push endpoints must match `PUSH_ALLOWED_ENDPOINT_HOSTS`; keep this list limited to
  browser push providers approved by school IT. Enforce the same destinations at the
  server egress firewall to prevent DNS rebinding, and keep
  `PUSH_DELIVERY_TIMEOUT_SECONDS` at 10 seconds or less.

Password resets require a STARTTLS-capable SMTP relay in production. Configure
`EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USERNAME`, `EMAIL_PASSWORD`, `EMAIL_FROM`, and:

```dotenv
EMAIL_SMTP_TIMEOUT_SECONDS=5
PASSWORD_RESET_WORKER_ENABLED=true
PASSWORD_RESET_WORKER_INTERVAL_SECONDS=5
PASSWORD_RESET_CLAIM_TIMEOUT_SECONDS=120
```

The public reset request only commits a concurrency-safe outbox row and returns the
same `202` response for known and unknown addresses; it never waits for SMTP. A
background worker claims each per-user row before delivery, and the token becomes
usable only after a successful send. Reset links place the token in a URL fragment so
reverse proxies do not receive it; the frontend removes the fragment from browser
history immediately. Run one worker-enabled application instance during deployment
smoke testing and monitor reset rows stuck in `PROCESSING` or ending in `FAILED`.


## Maintenance Guide

### Backend Maintenance

1. Check if the backend is running:
```bash
sudo systemctl status blog
```

2. Restart blog service:
```bash
sudo systemctl restart blog
```

3. View logs of blog service:
```bash
sudo journalctl -xeu blog.service
```

4. Restart nginx:
```bash
sudo systemctl restart nginx
```

5. Check if nginx is running:
```bash
sudo systemctl status nginx
```
