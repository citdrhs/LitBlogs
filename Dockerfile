# syntax=docker/dockerfile:1
FROM node:24-bookworm-slim@sha256:ba849c60be29959425b8734d57b8b4b7d56f98edd9504c9af091d5281095a71e AS frontend
WORKDIR /build
COPY litblogs/package.json litblogs/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY litblogs/index.html litblogs/vite.config.js litblogs/postcss.config.js litblogs/tailwind.config.js ./
COPY litblogs/rich_text_contract.json ./
COPY litblogs/src ./src
COPY litblogs/public ./public
ARG VITE_APP_BASE_PATH=/
ENV VITE_APP_BASE_PATH=${VITE_APP_BASE_PATH}
RUN npm run build

FROM python:3.13-slim-bookworm@sha256:ed86c82274b3c69b52fb5820f358f0bd7df0b603332063cb5c6e32bd220c3e6e AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates openssl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 litblogs \
    && useradd --uid 10001 --gid litblogs --no-create-home --shell /usr/sbin/nologin litblogs \
    && install -d -o root -g root -m 0755 /opt/litblogs /var/lib/litblogs /etc/litblogs
WORKDIR /opt/litblogs/litblogs
COPY litblogs/requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir --require-hashes --only-binary=:all: -r requirements.txt
COPY litblogs/*.py litblogs/alembic.ini litblogs/rich_text_contract.json ./
COPY litblogs/THIRD_PARTY_EDITOR_NOTICES.md ./
COPY litblogs/migrations ./migrations
COPY deploy/container /opt/litblogs/deploy/container
COPY deploy/logging.json /opt/litblogs/deploy/logging.json
COPY --from=frontend /build/dist ./dist
USER litblogs
EXPOSE 5000
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD ["python", "/opt/litblogs/deploy/container/healthcheck.py", "web"]
ENTRYPOINT ["python", "/opt/litblogs/deploy/container/runtime.py"]
CMD ["web"]
