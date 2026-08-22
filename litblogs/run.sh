#!/usr/bin/env bash
set -euo pipefail

if [[ "${APP_ENV:-development}" == "production" ]]; then
  echo "Production must start through the reviewed systemd unit." >&2
  exit 1
fi

exec python -m uvicorn main:app \
  --host "${LITBLOG_DEV_HOST:-127.0.0.1}" \
  --port "${LITBLOG_DEV_PORT:-8000}"
