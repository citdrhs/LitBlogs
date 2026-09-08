#!/usr/bin/env bash
# Guarded orchestration for a new Ubuntu 24.04.4 LitBlogs server.
# Run this script only from the reviewed, attested, root-owned release tree.
set -euo pipefail
umask 027

readonly CONFIG_PATH=/etc/litblogs/fresh-install.conf
readonly PYTHON_VERSION=3.13.15
readonly PYTHON_SHA256=1e66a7945a48390ee4c2a4268a0e4185884059a13c4aab6d148aa208deea4a76

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

note() {
  printf '\n==> %s\n' "$*"
}

require_root() {
  test "${EUID:-$(id -u)}" -eq 0 || die 'Run this phase with sudo.'
}

require_ubuntu_24044() {
  grep -Fq 'Ubuntu 24.04.4 LTS' /etc/os-release || \
    die 'This helper is approved only for Ubuntu 24.04.4 LTS.'
}

read_config() {
  local line key value
  declare -gA CONFIG_SEEN=()
  test -f "$CONFIG_PATH" || die "Missing $CONFIG_PATH"
  test ! -L "$CONFIG_PATH" || die 'The install config may not be a symlink.'
  test "$(stat -Lc '%U:%G:%a' "$CONFIG_PATH")" = root:root:600 || \
    die "$CONFIG_PATH must be root:root mode 0600."

  while IFS= read -r line || test -n "$line"; do
    case "$line" in
      ''|'#'*) continue ;;
    esac
    [[ "$line" =~ ^([A-Z][A-Z0-9_]*)=(.*)$ ]] || die "Invalid config line: $line"
    key=${BASH_REMATCH[1]}
    value=${BASH_REMATCH[2]}
    case "$key" in
      SITE_HOST|SCHOOL_EMAIL_DOMAIN|ACME_CONTACT_EMAIL|RELEASE_ID|REVIEWED_SHA|\
      POSTGRES_SERVER_CERT_SOURCE|POSTGRES_SERVER_KEY_SOURCE|POSTGRES_ROOT_CA_SOURCE|\
      REVIEWED_OPERATOR|HOST_FIREWALL_APPROVED|EGRESS_POLICY_APPROVED|\
      RESTORE_REHEARSAL_APPROVED|RECOVERY_POLICY_APPROVED) ;;
      *) die "Unknown config key: $key" ;;
    esac
    test -z "${CONFIG_SEEN[$key]:-}" || die "Duplicate config key: $key"
    CONFIG_SEEN[$key]=1
    printf -v "$key" '%s' "$value"
  done <"$CONFIG_PATH"

  for key in SITE_HOST SCHOOL_EMAIL_DOMAIN ACME_CONTACT_EMAIL RELEASE_ID REVIEWED_SHA \
    POSTGRES_SERVER_CERT_SOURCE POSTGRES_SERVER_KEY_SOURCE POSTGRES_ROOT_CA_SOURCE \
    REVIEWED_OPERATOR HOST_FIREWALL_APPROVED EGRESS_POLICY_APPROVED \
    RESTORE_REHEARSAL_APPROVED RECOVERY_POLICY_APPROVED; do
    test -n "${CONFIG_SEEN[$key]:-}" || die "Missing config key: $key"
    value=${!key}
    case "$value" in
      ''|REPLACE_WITH*) die "Replace $key in $CONFIG_PATH" ;;
    esac
  done

  [[ "$SITE_HOST" =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$ ]] || die 'SITE_HOST is invalid.'
  [[ "$SCHOOL_EMAIL_DOMAIN" =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$ ]] || \
    die 'SCHOOL_EMAIL_DOMAIN is invalid.'
  [[ "$ACME_CONTACT_EMAIL" =~ ^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$ ]] || \
    die 'ACME_CONTACT_EMAIL is invalid.'
  [[ "$RELEASE_ID" =~ ^litblogs-[0-9a-f]{12}$ ]] || die 'RELEASE_ID is invalid.'
  [[ "$REVIEWED_SHA" =~ ^[0-9a-f]{40}$ ]] || die 'REVIEWED_SHA is invalid.'
  test "${REVIEWED_SHA:0:12}" = "${RELEASE_ID#litblogs-}" || \
    die 'RELEASE_ID does not match REVIEWED_SHA.'
  for key in HOST_FIREWALL_APPROVED EGRESS_POLICY_APPROVED \
    RESTORE_REHEARSAL_APPROVED RECOVERY_POLICY_APPROVED; do
    case "${!key}" in true|false) ;; *) die "$key must be true or false." ;; esac
  done

  RELEASE_ROOT="/opt/litblogs/releases/$RELEASE_ID"
  export SITE_HOST SCHOOL_EMAIL_DOMAIN ACME_CONTACT_EMAIL RELEASE_ID REVIEWED_SHA RELEASE_ROOT
}

require_release() {
  local self
  test -d "$RELEASE_ROOT" || die "Missing release $RELEASE_ROOT"
  test -f "$RELEASE_ROOT/RELEASE-MANIFEST" || die 'RELEASE-MANIFEST is missing.'
  grep -Fxq "commit=$REVIEWED_SHA" "$RELEASE_ROOT/RELEASE-MANIFEST" || \
    die 'RELEASE-MANIFEST does not match the reviewed commit.'
  self=$(readlink -f "$0")
  test "$self" = "$RELEASE_ROOT/deploy/scripts/fresh_server_setup.sh" || \
    die 'Run the helper from the admitted release, not from ~/www.'
  test -z "$(find "$RELEASE_ROOT" \( ! -user root -o ! -group root -o \( ! -type l -perm /022 \) \) \
    -print -quit)" || die 'The admitted release is not root-owned and immutable.'
}

require_approval() {
  local name=$1
  test "${!name}" = true || die "$name is still false; record the required approval first."
}

install_python() (
  # The web/worker accounts must be able to traverse the root-installed runtime.
  umask 022
  local build_dir
  if /usr/local/bin/python3.13 --version 2>/dev/null | grep -Fq "Python $PYTHON_VERSION"; then
    return
  fi
  build_dir=$(mktemp -d /tmp/litblogs-python.XXXXXXXX)
  trap 'rm -r -- "$build_dir"' RETURN
  cd "$build_dir"
  curl --fail --location --proto '=https' --tlsv1.2 \
    --output "Python-${PYTHON_VERSION}.tar.xz" \
    "https://www.python.org/ftp/python/${PYTHON_VERSION}/Python-${PYTHON_VERSION}.tar.xz"
  printf '%s  %s\n' "$PYTHON_SHA256" "Python-${PYTHON_VERSION}.tar.xz" | sha256sum --check -
  tar -xf "Python-${PYTHON_VERSION}.tar.xz"
  cd "Python-${PYTHON_VERSION}"
  ./configure --prefix=/usr/local --with-ensurepip=install --enable-optimizations
  make -j"$(nproc)"
  make altinstall
  /usr/local/bin/python3.13 -c 'import bz2,ctypes,curses,lzma,readline,sqlite3,ssl,uuid,zlib'
  cd /
  rm -r -- "$build_dir"
  trap - RETURN
)

install_node() (
  local arch node_arch node_sha tarball install_root download_dir
  local node_version=v24.20.0
  arch=$(dpkg --print-architecture)
  case "$arch" in
    amd64)
      node_arch=x64
      node_sha=2f2c0da162318f0de47665410c7c8c2ed3d36c8f3105de4bbc61176c70a7cbf2
      ;;
    arm64)
      node_arch=arm64
      node_sha=5f4ddab610c1ab2016b3c227cebdbf6d9495161487e4739c7b90090595f465f7
      ;;
    *) die 'Unsupported Node.js architecture.' ;;
  esac
  tarball="node-${node_version}-linux-${node_arch}.tar.xz"
  install_root="/opt/node-${node_version}-linux-${node_arch}"
  if test ! -d "$install_root"; then
    download_dir=$(mktemp -d /tmp/litblogs-node.XXXXXXXX)
    trap 'rm -r -- "$download_dir"' EXIT
    curl --fail --location --proto '=https' --tlsv1.2 \
      --output "$download_dir/$tarball" "https://nodejs.org/dist/${node_version}/${tarball}"
    printf '%s  %s\n' "$node_sha" "$download_dir/$tarball" | sha256sum --check -
    tar --extract --xz --file "$download_dir/$tarball" --directory /opt --no-same-owner
  fi
  chown -R root:root "$install_root"
  chmod -R go-w "$install_root"
  test -z "$(find "$install_root" \( ! -user root -o ! -group root -o \( ! -type l -perm /022 \) \) \
    -print -quit)" || die 'Node.js ownership validation failed.'
  for binary in node npm npx corepack; do
    ln -sfn "$install_root/bin/$binary" "/usr/local/bin/$binary"
  done
  node --version
  npm --version
)

phase_toolchain() {
  require_root
  require_ubuntu_24044
  require_release
  umask 022
  note 'Installing the exact host toolchain and services'
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y \
    build-essential ca-certificates curl git gnupg jq netcat-openbsd openssl \
    pkg-config snapd wget xz-utils postgresql-common \
    libbz2-dev libdb-dev libexpat1-dev libffi-dev libgdbm-dev \
    libgdbm-compat-dev liblzma-dev libncurses-dev libreadline-dev \
    libsqlite3-dev libssl-dev tk-dev uuid-dev zlib1g-dev nginx clamav clamav-daemon
  /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y postgresql-17 postgresql-client-17
  if ! command -v certbot >/dev/null 2>&1; then
    snap install --classic certbot
    ln -sfn /snap/bin/certbot /usr/local/bin/certbot
  fi
  install_python
  install_node

  id litblogs >/dev/null 2>&1 || die 'The bootstrap litblogs account is missing.'
  if ! id litblogs-reset >/dev/null 2>&1; then
    useradd --system --no-create-home --home-dir /nonexistent \
      --shell /usr/sbin/nologin --user-group litblogs-reset
    passwd --lock litblogs-reset
  fi
  test "$(id -G litblogs-reset | wc -w)" -eq 1 || die 'litblogs-reset has supplementary groups.'
  install -d -o root -g root -m 0755 /opt/litblogs /opt/litblogs/releases /etc/litblogs
  install -d -o root -g litblogs -m 0750 /var/lib/litblogs
  install -d -o litblogs -g litblogs -m 0750 /var/lib/litblogs/uploads /var/log/litblogs
  install -d -o litblogs -g litblogs -m 0700 \
    /var/lib/litblogs/uploads/objects /var/lib/litblogs/uploads/.incoming
  install -d -o root -g root -m 0700 /srv/litblogs-backups
  systemctl enable --now postgresql
  /usr/lib/postgresql/17/bin/postgres --version
  certbot --version
}

phase_stage_tests() {
  require_root
  require_release
  note 'Testing the exact reviewed commit in the disposable ~/www checkout'
  sudo -iu litblogs env REVIEWED_SHA="$REVIEWED_SHA" bash -se <<'LITBLOGS'
set -euo pipefail
cd ~/www/LitBlogs
git switch main
git pull --ff-only
test "$(git rev-parse HEAD)" = "$REVIEWED_SHA"
cd litblogs
/usr/local/bin/python3.13 -m venv .venv
.venv/bin/python -m pip install --require-hashes --only-binary=:all: -r requirements-dev.txt
npm ci
cd ..
litblogs/.venv/bin/python -m pytest litblogs/tests -q
npm --prefix litblogs run test:run
npm --prefix litblogs run lint
npm --prefix litblogs run build
litblogs/.venv/bin/python -m ruff check litblogs
litblogs/.venv/bin/python scripts/run-backend-bandit.py
litblogs/.venv/bin/python scripts/check-generic-secrets.py
litblogs/.venv/bin/python scripts/validate-repository-policy.py
LITBLOGS
  note 'Staging passed. Do not deploy the clone; production uses the admitted release.'
}

install_postgres_certificates() {
  for source in "$POSTGRES_SERVER_CERT_SOURCE" "$POSTGRES_SERVER_KEY_SOURCE" \
    "$POSTGRES_ROOT_CA_SOURCE"; do
    test -f "$source" || die "Missing PKI input: $source"
    test ! -L "$source" || die "PKI input may not be a symlink: $source"
  done
  install -o root -g postgres -m 0644 "$POSTGRES_SERVER_CERT_SOURCE" \
    /etc/postgresql/17/main/server.crt
  install -o root -g postgres -m 0640 "$POSTGRES_SERVER_KEY_SOURCE" \
    /etc/postgresql/17/main/server.key
  install -o root -g root -m 0644 "$POSTGRES_ROOT_CA_SOURCE" \
    /etc/litblogs/postgres-root-ca.pem
  openssl x509 -in /etc/postgresql/17/main/server.crt \
    -noout -subject -issuer -dates -ext subjectAltName | grep -F 'IP Address:127.0.0.1'
}

phase_postgres() {
  require_root
  require_release
  test "$(sudo -u postgres psql -Atqc "SELECT count(*) FROM pg_roles WHERE rolname IN ('litblogs_migrator','litblogs_runtime','litblog_identity_owner','litblog_account_operator','litblog_invitation_operator','litblogs_backup')")" -eq 0 || \
    die 'Application roles already exist. For an interrupted password ceremony, use postgres-passwords; otherwise follow the runbook.'
  test "$(sudo -u postgres psql -Atqc "SELECT count(*) FROM pg_database WHERE datname='litblogs'")" -eq 0 || \
    die 'The litblogs database already exists; this is not a fresh install.'
  install_postgres_certificates
  note 'Creating the fresh PostgreSQL 17 database and least-privilege roles'
  sudo -u postgres psql -v ON_ERROR_STOP=1 <<'SQL'
ALTER SYSTEM SET listen_addresses = '127.0.0.1';
ALTER SYSTEM SET ssl = 'on';
ALTER SYSTEM SET ssl_cert_file = '/etc/postgresql/17/main/server.crt';
ALTER SYSTEM SET ssl_key_file = '/etc/postgresql/17/main/server.key';
ALTER SYSTEM SET ssl_min_protocol_version = 'TLSv1.2';
ALTER SYSTEM SET password_encryption = 'scram-sha-256';
SELECT pg_reload_conf();
SQL
  cat >/etc/postgresql/17/main/pg_hba.conf <<'HBA'
local   all       postgres                                  peer
local   all       all                                       reject
hostssl litblogs  litblogs_migrator           127.0.0.1/32  scram-sha-256
hostssl litblogs  litblogs_runtime            127.0.0.1/32  scram-sha-256
hostssl litblogs  litblog_account_operator    127.0.0.1/32  scram-sha-256
hostssl litblogs  litblog_invitation_operator 127.0.0.1/32  scram-sha-256
hostssl litblogs  litblogs_backup             127.0.0.1/32  scram-sha-256
hostnossl litblogs all                        127.0.0.1/32  reject
host    all       all                         0.0.0.0/0     reject
host    all       all                         ::/0          reject
HBA
  sudo -u postgres psql -v ON_ERROR_STOP=1 <<'SQL'
CREATE ROLE litblogs_migrator LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE litblogs_runtime LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE litblog_identity_owner NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE litblog_account_operator LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE litblog_invitation_operator LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE litblogs_backup LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
GRANT pg_read_all_data TO litblogs_backup WITH ADMIN FALSE, INHERIT TRUE, SET TRUE;
CREATE DATABASE litblogs OWNER litblogs_migrator TEMPLATE template0 ENCODING 'UTF8';
REVOKE CONNECT, TEMPORARY ON DATABASE postgres FROM PUBLIC;
REVOKE CONNECT, TEMPORARY ON DATABASE template0 FROM PUBLIC;
REVOKE CONNECT, TEMPORARY ON DATABASE template1 FROM PUBLIC;
REVOKE ALL ON DATABASE litblogs FROM PUBLIC;
GRANT CONNECT ON DATABASE litblogs TO litblogs_migrator, litblogs_runtime,
  litblog_account_operator, litblog_invitation_operator, litblogs_backup;
SQL
  sudo -u postgres psql -d litblogs -v ON_ERROR_STOP=1 <<'SQL'
ALTER SCHEMA public OWNER TO litblogs_migrator;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SQL
  phase_postgres_passwords
}

phase_postgres_passwords() {
  local role role_url authenticated_role scram_ok
  require_root
  require_release
  test "$(sudo -u postgres psql --dbname litblogs -Atqc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")" -eq 0 || \
    die 'Password setup is only for an empty, not-yet-migrated install.'
  # Restart applies the TLS and SCRAM settings before the first password prompt.
  systemctl restart postgresql@17-main

  printf '%s\n' 'Set five staged passwords, one prompt at a time. Do not paste passwords.'
  sudo -u postgres psql --command '\password litblogs_migrator'
  sudo -u postgres psql --command '\password litblogs_runtime'
  sudo -u postgres psql --command '\password litblog_account_operator'
  sudo -u postgres psql --command '\password litblog_invitation_operator'
  sudo -u postgres psql --command '\password litblogs_backup'
  printf '%s\n' 'Rotate all five now. Retain each first value only for its ROTATED-OLD password test.'
  sudo -u postgres psql --command '\password litblogs_migrator'
  sudo -u postgres psql --command '\password litblogs_runtime'
  sudo -u postgres psql --command '\password litblog_account_operator'
  sudo -u postgres psql --command '\password litblog_invitation_operator'
  sudo -u postgres psql --command '\password litblogs_backup'

  systemctl restart postgresql@17-main
  sudo -u postgres psql -x -c \
    "SELECT line_number,type,database,user_name,address,auth_method,error FROM pg_hba_file_rules ORDER BY line_number;"
  scram_ok=$(sudo -u postgres psql --dbname postgres --tuples-only --no-align \
    --command "SELECT count(*) = 5 AND bool_and(rolpassword LIKE 'SCRAM-SHA-256$%') FROM pg_authid WHERE rolname IN ('litblogs_migrator','litblogs_runtime','litblog_account_operator','litblog_invitation_operator','litblogs_backup');")
  SCRAM_OK=$scram_ok
  test "$SCRAM_OK" = t || die 'The five login roles do not all use SCRAM.'

  for role in litblogs_migrator litblogs_runtime litblog_account_operator \
    litblog_invitation_operator litblogs_backup; do
    role_url="postgresql://${role}@127.0.0.1:5432/litblogs?sslmode=verify-full&sslrootcert=/etc/litblogs/postgres-root-ca.pem"
    printf 'Enter the CURRENT managed password for %s.\n' "$role"
    authenticated_role=$(/usr/lib/postgresql/17/bin/psql "$role_url" --password \
      --tuples-only --no-align --command 'SELECT current_user;')
    test "$authenticated_role" = "$role" || die 'Current credential failed.'
    printf 'Enter a deliberately wrong password for %s; it must fail.\n' "$role"
    if /usr/lib/postgresql/17/bin/psql "$role_url" --password --command 'SELECT 1;' >/dev/null; then
      die 'Wrong password was accepted'
    fi
    printf 'Enter the ROTATED-OLD password for %s; it must fail.\n' "$role"
    if /usr/lib/postgresql/17/bin/psql "$role_url" --password --command 'SELECT 1;' >/dev/null; then
      die 'Rotated-old password was accepted'
    fi
  done
  unset role_url authenticated_role SCRAM_OK
}

configure_clamav() {
  test -f /etc/clamav/clamd.conf || die 'ClamAV configuration is missing.'
  if test ! -f /etc/clamav/clamd.conf.before-litblogs; then
    cp /etc/clamav/clamd.conf /etc/clamav/clamd.conf.before-litblogs
  fi
  sed -i \
    -e '/^[#[:space:]]*TCPSocket[[:space:]]/d' \
    -e '/^[#[:space:]]*TCPAddr[[:space:]]/d' \
    -e '/^[#[:space:]]*StreamMaxLength[[:space:]]/d' \
    -e '/^[#[:space:]]*MaxFileSize[[:space:]]/d' /etc/clamav/clamd.conf
  printf '%s\n' '' '# LitBlogs loopback scanner' 'TCPSocket 3310' \
    'TCPAddr 127.0.0.1' 'StreamMaxLength 101M' 'MaxFileSize 101M' \
    >>/etc/clamav/clamd.conf
  # A fresh package may not yet have downloaded its first signature database.
  systemctl stop clamav-freshclam.service
  freshclam --quiet
  systemctl enable --now clamav-freshclam.service
  systemctl enable clamav-daemon.service
  systemctl restart clamav-daemon.service
  ss -H -ltn 'sport = :3310' | awk '{print $4}' | grep -Fx '127.0.0.1:3310'
  test "$(printf 'zPING\0' | nc -N -w 3 127.0.0.1 3310 | tr -d '\0')" = PONG || \
    die 'ClamAV did not answer PONG.'
}

assert_private_env() {
  local path=$1 owner_group=$2
  test -f "$path" || die "Missing $path"
  test ! -L "$path" || die "$path may not be a symlink."
  test "$(stat -Lc '%U:%G:%a' "$path")" = "$owner_group" || \
    die "$path ownership or mode is wrong."
  if grep -Eq '<[^>]+>|REPLACE_WITH|YOUR_[A-Z0-9_]*' "$path"; then
    die "$path still contains a placeholder."
  fi
}

validate_password_reset_env() {
  local path=${1:-/etc/litblogs/password-reset.env} line key
  declare -A seen=()
  while IFS= read -r line || test -n "$line"; do
    case "$line" in ''|'#'*) continue ;; esac
    [[ "$line" =~ ^([A-Z][A-Z0-9_]*)=.+$ ]] || \
      die 'Invalid or empty authentication-worker setting; check the private file.'
    key=${BASH_REMATCH[1]}
    case "$key" in
      DATABASE_URL|DB_POOL_SIZE|DB_MAX_OVERFLOW|DB_POOL_TIMEOUT_SECONDS|\
      DB_POOL_RECYCLE_SECONDS|DB_CONNECT_TIMEOUT_SECONDS|DB_STATEMENT_TIMEOUT_MS|\
      DB_LOCK_TIMEOUT_MS|FRONTEND_URL|EMAIL_HOST|EMAIL_PORT|\
      EMAIL_SMTP_TIMEOUT_SECONDS|EMAIL_USERNAME|EMAIL_PASSWORD|EMAIL_FROM|\
      PASSWORD_RESET_CLAIM_TIMEOUT_SECONDS) ;;
      *) die "Forbidden authentication-worker setting: $key" ;;
    esac
    test -z "${seen[$key]:-}" || die "Duplicate authentication-worker setting: $key"
    seen[$key]=1
  done <"$path"
  for key in DATABASE_URL DB_POOL_SIZE DB_MAX_OVERFLOW DB_POOL_TIMEOUT_SECONDS \
    DB_POOL_RECYCLE_SECONDS DB_CONNECT_TIMEOUT_SECONDS DB_STATEMENT_TIMEOUT_MS \
    DB_LOCK_TIMEOUT_MS FRONTEND_URL EMAIL_HOST EMAIL_PORT EMAIL_SMTP_TIMEOUT_SECONDS \
    EMAIL_USERNAME EMAIL_PASSWORD EMAIL_FROM PASSWORD_RESET_CLAIM_TIMEOUT_SECONDS; do
    test -n "${seen[$key]:-}" || die "Missing authentication-worker setting: $key"
  done
}

run_migration() (
  local migration_env=/run/litblogs-migration.env cleanup_status
  cleanup_migration() {
    cleanup_status=0
    sudo -u postgres psql -v ON_ERROR_STOP=1 -c \
      'REVOKE litblog_identity_owner FROM litblogs_migrator;' || cleanup_status=1
    rm -f -- "$migration_env" || cleanup_status=1
    return "$cleanup_status"
  }
  trap cleanup_migration EXIT
  trap 'exit 129' HUP
  trap 'exit 130' INT
  trap 'exit 143' TERM
  assert_private_env "$migration_env" root:root:600
  test "$(grep -Ec '^LITBLOGS_MIGRATION_DATABASE_URL=.+$' "$migration_env")" -eq 1 || \
    die 'Migration environment must contain one migration URL.'
  test "$(grep -Evc '^(#|$|LITBLOGS_MIGRATION_DATABASE_URL=)' "$migration_env")" -eq 0 || \
    die 'Migration environment contains an unexpected key.'
  sudo -u postgres psql -v ON_ERROR_STOP=1 -c \
    'GRANT litblog_identity_owner TO litblogs_migrator WITH ADMIN FALSE, INHERIT TRUE, SET TRUE;'
  systemd-run --wait --collect --pipe --quiet --service-type=exec \
    --uid=litblogs --gid=litblogs --working-directory="$RELEASE_ROOT/litblogs" \
    --property="EnvironmentFile=$migration_env" \
    "$RELEASE_ROOT/.venv/bin/python" -m alembic \
    -c "$RELEASE_ROOT/litblogs/alembic.ini" upgrade head
  sudo -u postgres psql -v ON_ERROR_STOP=1 -c \
    'REVOKE litblog_identity_owner FROM litblogs_migrator;'
  systemd-run --wait --collect --pipe --quiet --service-type=exec \
    --uid=litblogs --gid=litblogs --working-directory="$RELEASE_ROOT/litblogs" \
    --property="EnvironmentFile=$migration_env" \
    "$RELEASE_ROOT/.venv/bin/python" -m alembic \
    -c "$RELEASE_ROOT/litblogs/alembic.ini" current --check-heads
  systemd-run --wait --collect --pipe --quiet --service-type=exec \
    --uid=litblogs --gid=litblogs --working-directory="$RELEASE_ROOT/litblogs" \
    --property="EnvironmentFile=$migration_env" \
    "$RELEASE_ROOT/.venv/bin/python" -m alembic \
    -c "$RELEASE_ROOT/litblogs/alembic.ini" check
  cleanup_migration
  trap - EXIT HUP INT TERM
  unset -f cleanup_migration
)

create_initial_recovery_set() (
  local backup_env=/run/litblogs-backup.env
  cleanup_backup() { rm -f -- "$backup_env"; }
  trap cleanup_backup EXIT
  trap 'exit 129' HUP
  trap 'exit 130' INT
  trap 'exit 143' TERM
  assert_private_env "$backup_env" root:root:600
  test "$(grep -Ec '^DATABASE_URL=.+$' "$backup_env")" -eq 1 || \
    die 'Backup environment must contain one DATABASE_URL.'
  test "$(grep -Evc '^(#|$|DATABASE_URL=)' "$backup_env")" -eq 0 || \
    die 'Backup environment contains an unexpected key.'
  systemd-run --wait --collect --pipe --quiet --service-type=exec \
    --working-directory="$RELEASE_ROOT" --property="EnvironmentFile=$backup_env" \
    "$RELEASE_ROOT/.venv/bin/python" \
    "$RELEASE_ROOT/deploy/scripts/backup_postgres.py" \
    --output-dir /srv/litblogs-backups --upload-root /var/lib/litblogs/uploads \
    --confirm-writes-quiesced
  cleanup_backup
  trap - EXIT HUP INT TERM
  unset -f cleanup_backup
)

phase_prepare() {
  require_root
  # Both credential files already exist before this phase starts. Clean both
  # even when preflight fails before either credential-consuming command runs.
  trap 'rm -f -- /run/litblogs-migration.env /run/litblogs-backup.env' EXIT
  trap 'exit 129' HUP
  trap 'exit 130' INT
  trap 'exit 143' TERM
  require_release
  note 'Validating production secrets, migrating, and creating the coupled backup'
  assert_private_env /etc/litblogs/litblogs.env root:litblogs:640
  assert_private_env /etc/litblogs/password-reset.env root:litblogs-reset:640
  sudo -u litblogs test ! -r /etc/litblogs/password-reset.env || \
    die 'The web account can read the authentication-worker environment.'
  sudo -u litblogs-reset test ! -r /etc/litblogs/litblogs.env || \
    die 'The authentication worker can read the web environment.'
  sudo -u litblogs test -r /etc/litblogs/postgres-root-ca.pem
  sudo -u litblogs-reset test -r /etc/litblogs/postgres-root-ca.pem
  validate_password_reset_env
  for setting in \
    'APP_ENV=production' \
    'LOCAL_PASSWORD_REGISTRATION_ENABLED=true' \
    'GOOGLE_OAUTH_ENABLED=false' \
    'GOOGLE_CLIENT_ID=' \
    'MICROSOFT_OAUTH_ENABLED=false' \
    'MICROSOFT_CLIENT_ID=' \
    'PUSH_NOTIFICATIONS_ENABLED=false' \
    'UPLOAD_REGISTRY_SCHEMA_READY=false' \
    'UPLOAD_LEGACY_IMPORT_COMPLETE=false' \
    'UPLOAD_BACKUP_RESTORE_VERIFIED=false'; do
    grep -Fxq "$setting" /etc/litblogs/litblogs.env || die "Required setting is missing: $setting"
  done
  if grep -Eq '^(SECRET_KEY|TEACHER_INVITE_HMAC_KEY|GOOGLE_[A-Z0-9_]*|MICROSOFT_[A-Z0-9_]*|UPLOAD_[A-Z0-9_]*)=' \
    /etc/litblogs/password-reset.env; then
    die 'The authentication-worker environment contains a forbidden web secret.'
  fi
  configure_clamav

  (
    umask 022
    /usr/local/bin/python3.13 -m venv "$RELEASE_ROOT/.venv"
    "$RELEASE_ROOT/.venv/bin/python" -m pip install \
      --require-hashes --only-binary=:all: -r "$RELEASE_ROOT/litblogs/requirements.txt"
  )
  sudo -u litblogs "$RELEASE_ROOT/.venv/bin/python" -c 'import ssl, sqlalchemy'
  sudo -u litblogs-reset "$RELEASE_ROOT/.venv/bin/python" -c 'import ssl, sqlalchemy'
  systemd-run --wait --collect --pipe --quiet --service-type=exec \
    --uid=litblogs --gid=litblogs --working-directory="$RELEASE_ROOT/litblogs" \
    --property=EnvironmentFile=/etc/litblogs/litblogs.env \
    "$RELEASE_ROOT/.venv/bin/python" -m deployment_check --preflight
  chown -R root:root "$RELEASE_ROOT"
  chmod -R go-w "$RELEASE_ROOT"

  run_migration
  test "$(sudo -u postgres psql --dbname litblogs --tuples-only --no-align \
    --command 'SELECT count(*) FROM public.upload_assets;')" -eq 0
  test -z "$(find /var/lib/litblogs/uploads -mindepth 1 -maxdepth 1 \
    ! -name objects ! -name .incoming -print -quit)"
  for upload_dir in /var/lib/litblogs/uploads/objects /var/lib/litblogs/uploads/.incoming; do
    test -z "$(find "$upload_dir" -mindepth 1 -print -quit)"
  done
  create_initial_recovery_set
  trap - EXIT HUP INT TERM
  note 'Prepare passed. Complete the isolated restore before changing readiness flags.'
}

install_units_and_nginx() {
  local unit
  for unit in litblogs-web.service litblogs-password-reset.service \
    litblogs-password-reset.timer litblogs-upload-reconciliation.service \
    litblogs-upload-reconciliation.timer litblogs-reminders.service \
    litblogs-reminders.timer; do
    install -o root -g root -m 0644 "$RELEASE_ROOT/deploy/systemd/$unit" \
      "/etc/systemd/system/$unit"
  done
  systemctl daemon-reload
  systemctl disable --now litblogs-reminders.timer

  cat >/etc/nginx/sites-available/litblogs-bootstrap <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${SITE_HOST};
    location / { return 404; }
}
EOF
  ln -sfn /etc/nginx/sites-available/litblogs-bootstrap \
    /etc/nginx/sites-enabled/litblogs-bootstrap
  rm -f /etc/nginx/sites-enabled/default
  nginx -t
  systemctl enable --now nginx
  systemctl reload nginx
  certbot certonly --nginx --non-interactive --agree-tos --no-eff-email \
    --email "$ACME_CONTACT_EMAIL" -d "$SITE_HOST"
  certbot renew --dry-run
  sed \
    -e "s/litblogs\.school\.example/${SITE_HOST}/g" \
    -e "s#/etc/litblogs/tls/fullchain\.pem#/etc/letsencrypt/live/${SITE_HOST}/fullchain.pem#g" \
    -e "s#/etc/litblogs/tls/privkey\.pem#/etc/letsencrypt/live/${SITE_HOST}/privkey.pem#g" \
    "$RELEASE_ROOT/deploy/nginx/litblogs.conf" >/etc/nginx/sites-available/litblogs
  ln -sfn /etc/nginx/sites-available/litblogs /etc/nginx/sites-enabled/litblogs
  rm -f /etc/nginx/sites-enabled/litblogs-bootstrap
  nginx -t
  systemctl reload nginx
}

phase_post_restore() {
  require_root
  require_release
  require_approval HOST_FIREWALL_APPROVED
  require_approval EGRESS_POLICY_APPROVED
  require_approval RESTORE_REHEARSAL_APPROVED
  require_approval RECOVERY_POLICY_APPROVED
  assert_private_env /etc/litblogs/litblogs.env root:litblogs:640
  for setting in UPLOAD_REGISTRY_SCHEMA_READY=true \
    UPLOAD_LEGACY_IMPORT_COMPLETE=true UPLOAD_BACKUP_RESTORE_VERIFIED=true; do
    grep -Fxq "$setting" /etc/litblogs/litblogs.env || \
      die "Restore evidence exists, but $setting is not set."
  done
  systemd-run --wait --collect --pipe --quiet --service-type=exec \
    --uid=litblogs --gid=litblogs --working-directory="$RELEASE_ROOT/litblogs" \
    --property=EnvironmentFile=/etc/litblogs/litblogs.env \
    "$RELEASE_ROOT/.venv/bin/python" -m deployment_check
  install_units_and_nginx
  note 'Creating the only initial administrator with private prompts'
  systemd-run --wait --collect --pty --quiet --service-type=exec \
    --uid=litblogs --gid=litblogs --working-directory="$RELEASE_ROOT/litblogs" \
    --property=EnvironmentFile=/etc/litblogs/litblogs.env \
    "$RELEASE_ROOT/.venv/bin/python" -m bootstrap_admin --confirm-empty-install
}

phase_invite_teacher() {
  require_root
  require_release
  assert_private_env /etc/litblogs/invitation-operator.json root:root:600
  note 'Creating the first teacher invitation; disable terminal/session recording now'
  exec 3</etc/litblogs/invitation-operator.json
  cd "$RELEASE_ROOT/litblogs"
  /usr/bin/setpriv --reuid=litblogs --regid=litblogs --init-groups \
    --inh-caps=-all --bounding-set=-all \
    "$RELEASE_ROOT/.venv/bin/python" -m manage_teacher_invitations create \
    --expires-hours 24 --operator "$REVIEWED_OPERATOR"
  exec 3<&-
}

phase_activate() {
  require_root
  require_release
  require_approval HOST_FIREWALL_APPROVED
  require_approval EGRESS_POLICY_APPROVED
  require_approval RESTORE_REHEARSAL_APPROVED
  require_approval RECOVERY_POLICY_APPROVED
  "$RELEASE_ROOT/.venv/bin/python" "$RELEASE_ROOT/deploy/scripts/release_switch.py" \
    --root /opt/litblogs activate "$RELEASE_ID" \
    --confirm-release "$RELEASE_ID" --expected-commit "$REVIEWED_SHA"
  systemctl enable litblogs-web.service
  systemctl restart litblogs-web.service
  systemctl start litblogs-password-reset.service litblogs-upload-reconciliation.service
  systemctl enable --now litblogs-password-reset.timer litblogs-upload-reconciliation.timer
  systemctl disable --now litblogs-reminders.timer
}

phase_smoke() {
  local port bindings smoke_dir mp4_name vtt_name mp4_status vtt_status html_status
  local journal_errors
  require_root
  require_release
  for unit in postgresql@17-main clamav-daemon nginx litblogs-web \
    litblogs-password-reset.timer litblogs-upload-reconciliation.timer; do
    systemctl is-active --quiet "$unit" || die "$unit is not active."
  done
  if systemctl --quiet is-failed litblogs-web.service \
    litblogs-password-reset.service litblogs-upload-reconciliation.service; then
    die 'A LitBlogs service is failed.'
  fi
  for port in 8000 3310 5432; do
    bindings=$(ss -H -ltn "sport = :$port")
    test "$(printf '%s\n' "$bindings" | sed '/^$/d' | wc -l)" -eq 1 || \
      die "Port $port does not have exactly one listener."
    if printf '%s\n' "$bindings" | awk '{print $4}' | grep -Evq '^127\.0\.0\.1:'; then
      die "Port $port is not loopback-only"
    fi
  done
  curl --fail --silent --show-error -H "Host: $SITE_HOST" \
    http://127.0.0.1:8000/api/health/ready >/dev/null
  curl --fail --silent --show-error "https://$SITE_HOST/api/health/ready" >/dev/null
  smoke_dir=$(mktemp -d /tmp/litblogs-smoke.XXXXXXXX)
  trap 'rm -r -- "$smoke_dir"' RETURN
  curl --fail --silent --show-error --dump-header "$smoke_dir/runtime.headers" \
    --output "$smoke_dir/runtime.json" "https://$SITE_HOST/api/runtime-config"
  /usr/local/bin/python3.13 - "$smoke_dir/runtime.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    actual = json.load(stream)
expected = {
    "csrf_cookie_name": "__Host-litblogs-csrf",
    "google_oauth_enabled": False,
    "google_client_id": "",
    "microsoft_oauth_enabled": False,
    "microsoft_client_id": "",
    "microsoft_tenant_id": "",
    "local_password_registration_enabled": True,
}
if actual != expected:
    raise SystemExit("Password-only runtime configuration is not exact")
PY
  tr -d '\r' <"$smoke_dir/runtime.headers" | \
    grep -Eiq '^cache-control:[[:space:]]*no-store[[:space:]]*$'
  mp4_name=$(basename "$(find /opt/litblogs/current/litblogs/dist/assets -maxdepth 1 \
    -type f -name 'litblogs-tutorial-*.mp4' -print -quit)")
  vtt_name=$(basename "$(find /opt/litblogs/current/litblogs/dist/assets -maxdepth 1 \
    -type f -name 'litblogs-tutorial.en-*.vtt' -print -quit)")
  test -n "$mp4_name" -a -n "$vtt_name"
  test "$(find /opt/litblogs/current/litblogs/dist/assets -maxdepth 1 \
    -type f -name 'litblogs-tutorial-*.mp4' -printf '.\n' | wc -l)" -eq 1
  test "$(find /opt/litblogs/current/litblogs/dist/assets -maxdepth 1 \
    -type f -name 'litblogs-tutorial.en-*.vtt' -printf '.\n' | wc -l)" -eq 1
  mp4_status=$(curl --silent --show-error --dump-header "$smoke_dir/mp4.headers" \
    --output /dev/null --write-out '%{http_code}' -H 'Range: bytes=0-1' \
    "https://$SITE_HOST/assets/$mp4_name")
  MP4_STATUS=$mp4_status
  test "$MP4_STATUS" = 206
  tr -d '\r' <"$smoke_dir/mp4.headers" | grep -Eiq \
    '^cache-control:[[:space:]]*public,[[:space:]]*max-age=31536000,[[:space:]]*immutable[[:space:]]*$'
  vtt_status=$(curl --silent --show-error --head --dump-header "$smoke_dir/vtt.headers" \
    --output /dev/null --write-out '%{http_code}' "https://$SITE_HOST/assets/$vtt_name")
  VTT_STATUS=$vtt_status
  test "$VTT_STATUS" = 200
  tr -d '\r' <"$smoke_dir/vtt.headers" | grep -Eiq \
    '^content-type:[[:space:]]*text/vtt([;[:space:]]|$)'
  tr -d '\r' <"$smoke_dir/vtt.headers" | grep -Eiq \
    '^cache-control:[[:space:]]*public,[[:space:]]*max-age=31536000,[[:space:]]*immutable[[:space:]]*$'
  html_status=$(curl --silent --show-error --head --dump-header "$smoke_dir/html.headers" \
    --output /dev/null --write-out '%{http_code}' "https://$SITE_HOST/")
  HTML_STATUS=$html_status
  test "$HTML_STATUS" = 200
  tr -d '\r' <"$smoke_dir/html.headers" | grep -Eiq \
    '^cache-control:[[:space:]]*no-cache,[[:space:]]*no-store,[[:space:]]*must-revalidate[[:space:]]*$'
  journal_errors=$(journalctl --quiet --no-pager --output=cat --priority=err \
    --since '-10 minutes' --unit=postgresql@17-main.service \
    --unit=clamav-daemon.service --unit=nginx.service --unit=litblogs-web.service \
    --unit=litblogs-password-reset.service --unit=litblogs-upload-reconciliation.service)
  JOURNAL_ERRORS=$journal_errors
  test -z "$JOURNAL_ERRORS"
  rm -r -- "$smoke_dir"
  trap - RETURN
  unset MP4_STATUS VTT_STATUS HTML_STATUS JOURNAL_ERRORS
}

usage() {
  cat <<'USAGE'
Usage: sudo /opt/litblogs/releases/<release>/deploy/scripts/fresh_server_setup.sh PHASE

Phases (run in guide order):
  toolchain       Install pinned Python/Node/PostgreSQL/Nginx/ClamAV/Certbot
  stage-tests     Test the exact reviewed commit in ~/www (staging only)
  postgres        Configure TLS/SCRAM and prompt for role passwords
  postgres-passwords Resume interrupted passwords before any migrations
  prepare         Validate envs, preflight, migrate, and create coupled backup
  post-restore    Require restore evidence, postflight, bootstrap admin, install web stack
  invite-teacher Create the first private teacher invitation
  activate        Require all four approvals and start production
  smoke           Fail-closed production checks
USAGE
}

main() {
  local phase=${1:-}
  case "$phase" in
    -h|--help|'') usage; test -n "$phase" ;;
    *)
      require_root
      read_config
      case "$phase" in
        toolchain) phase_toolchain ;;
        stage-tests) phase_stage_tests ;;
        postgres) phase_postgres ;;
        postgres-passwords) phase_postgres_passwords ;;
        prepare) phase_prepare ;;
        post-restore) phase_post_restore ;;
        invite-teacher) phase_invite_teacher ;;
        activate) phase_activate ;;
        smoke) phase_smoke ;;
        *) usage; die "Unknown phase: $phase" ;;
      esac
      ;;
  esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
