# LitBlogs

A modern blogging platform for educational institutions, designed for teachers and students to share literary content, collaborate, and engage in classroom discussions.

## Table of Contents
- [Overview](#overview)
- [System Requirements](#system-requirements)
- [Development Setup](#development-setup)
- [Production Deployment](#production-deployment)
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

## Development Setup

### Prerequisites
1. Python 3.10+
2. Node.js 18+
3. PostgreSQL 12+
4. Git

### Clone Repository
Go to /var/www/ by running the following command:
```bash
cd /var/www/
```
Then clone the repository:
```bash
git clone https://github.com/Antigro09/LitBlogs.git
cd /LitBlogs/litblogs
```
Run the commmand with sudo if you need permissions to clone the repository.

### Backend Setup
1. Create and activate a virtual environment:
```bash
python -m venv myvenv
source myvenv/bin/activate # On Windows: myvenv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Add the upload directory to the backend:
While in /var/www/LitBlogs/litblogs, run the following command:
```bash
sudo mkdir -p uploads
cd uploads
sudo mkdir -p images
sudo mkdir -p files
sudo mkdir -p videos
sudo mkdir -p profile_images
sudo mkdir -p temp
sudo mkdir -p 2
```
Then go back to /var/www/LitBlogs/litblogs

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
Then go back to /var/www/LitBlogs/litblogs

5. Run the backend server:
```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000 &
```

### Frontend Setup

1. Install dependencies:
```bash
npm install --force
```
2. Add the following to vite.config.js:
```javascript
base: '/dren/',
```

3. Change the redirect/postLogoutRedirect URI in msalConfig.js to:
```javascript
redirectUri: 'https://drhscit.org/dren/',
postLogoutRedirectUri: 'https://drhscit.org/dren/',
```

4. Depending if it is a production or development environment, change the following urls of all pictures:
```javascript
".image.png" -> "/dren/image.png"
```

5. Run the frontend server:
```bash
npm run build
```
6. Go to the nginx directory and edit the file:
```bash
sudo nano /etc/nginx/sites-enabled/tutorial
```
Add the following to the file:
```bash
server {
    listen 7001;
    listen [::]:7001;
    server_name drhscit.org www.drhscit.org;
    root /var/www/LitBlog/litblogs/dist;
    index index.html;
    # For React Router (SPA) at /dren path
    location / {
            rewrite ^/dren(.*)$ /$1 last;
            #try_files $uri $uri/ /index.html;
            try_files $uri $uri/ /dren/$uri =404;
    }

    #location ~* \.(js|mjs|css|json|webmanifest|map)$ {
    #    add_header Content-Type application/javascript;
    #    try_files $uri =404;
    #}

    #location ~* ^/(.*\.(png|jpg|jpeg|gif|svg|webmanifest|map))$ {
        #rewrite ^/(.*)$ /dren/$1 break;
        #root /var/www/LitBlog/litblogs/dist;
        #try_files $uri =404;
    #}

    # API proxy - ensure this is working properly
    location /dren/api/ {
        rewrite ^/dren/api/(.*)$ /api/$1 break;
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
        # Important for CORS preflight requests
        proxy_pass_request_headers on;
    }

    location /uploads/ {
        alias /var/www/LitBlog/litblogs/uploads/;
        autoindex off;
    }

}
```



## Maintenance Guide

### Backend Maintenance

1. Check if the backend is running:
```bash
ps aux | grep uvicorn
```

2. Restart nginx:
```bash
sudo systemctl restart nginx
```

3. Check if nginx is running:
```bash
sudo systemctl status nginx
```