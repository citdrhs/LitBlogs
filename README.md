# LitBlog
The new and improved version of the CIT's English Blog website, LitBlog!

## Table of Contents
- [Overview](#overview)
- [System Requirements](#system-requirements)
- [Development Setup](#development-setup)
  - [Prerequisites](#prerequisites)
  - [Backend Setup](#backend-setup)
  - [Frontend Setup](#frontend-setup)
- [Deployment Guide](#deployment-guide)
  - [Server Preparation](#server-preparation)
  - [Database Setup](#database-setup)
  - [Application Deployment](#application-deployment)
  - [NGINX Configuration](#nginx-configuration)
  - [HTTPS Setup](#https-setup)
  - [Supervisor Setup](#supervisor-setup)
- [Maintenance Guide](#maintenance-guide)
  - [Updating the Application](#updating-the-application)
  - [Database Backups](#database-backups)
  - [Log Management](#log-management)
  - [User Management](#user-management)
  - [Common Issues](#common-issues)

## Overview
LitBlog is a web platform designed for CIT's English Department, allowing students and teachers to create, share, and collaborate on literary content. The application features role-based access, class management, rich-text blog posts, and user profiles.

## System Requirements

### Production Server
- Ubuntu 20.04 LTS or newer
- Python 3.10+
- Node.js 18+
- PostgreSQL 12+
- NGINX
- Supervisor
- 2GB RAM minimum (4GB recommended)
- 20GB storage minimum

### Development Environment
- Python 3.10+
- Node.js 18+
- PostgreSQL 12+
- Git

## Development Setup

### Prerequisites

1. **Install Python 3.10+**
   # Ubuntu/Debian
   sudo apt update
   sudo apt install python3.10 python3.10-dev python3.10-venv python3-pip
   

   # Ubuntu/Debian
    sudo apt install postgresql postgresql-contrib


   # Clone Repository
    git clone https://github.com/Atigro09/LitBlog.git
    cd litblogs

   # Create VENV
    python3 -m venv venv
    source venv/bin/activate

   # Install Python dependencies
    pip install -r requirements.txt

   # Install Node.js dependencies
    npm install --force


  ## DEPLOYMENT GUIDE
    s
   # Build Node.js files
    npm run build

   # Start python backend
    In /litblogs run
    uvicorn main:app --reload --host 0.0.0.0 --port 8000 &

   
  ### Maintinance Guide
   
   ## Updating the Website

    # Pull the latest changes
    cd /var/www/LitBlog/litblogs
    git pull