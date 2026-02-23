#!/bin/bash
source /var/www/LitBlogs/litblogs/myvenv/bin/activate
uvicorn main:app --reload --host 0.0.0.0 --port 8000
