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
