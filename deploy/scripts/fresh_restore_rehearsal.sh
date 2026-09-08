#!/usr/bin/env bash
# Guarded coupled database/upload restore rehearsal for an isolated host.
set -euo pipefail
umask 077

readonly CONFIG_PATH=/etc/litblogs/fresh-restore.conf
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
    die 'The rehearsal host must run Ubuntu 24.04.4 LTS.'
}

read_config() {
  local line key value
  declare -gA CONFIG_SEEN=()
  test -f "$CONFIG_PATH" || die "Missing $CONFIG_PATH"
  test ! -L "$CONFIG_PATH" || die 'The restore config may not be a symlink.'
  test "$(stat -Lc '%U:%G:%a' "$CONFIG_PATH")" = root:root:600 || \
    die "$CONFIG_PATH must be root:root mode 0600."
  while IFS= read -r line || test -n "$line"; do
    case "$line" in ''|'#'*) continue ;; esac
    [[ "$line" =~ ^([A-Z][A-Z0-9_]*)=(.*)$ ]] || die "Invalid config line: $line"
    key=${BASH_REMATCH[1]}
    value=${BASH_REMATCH[2]}
    case "$key" in
      RESTORE_RELEASE|REVIEWED_SHA|RESTORE_MANIFEST|RESTORE_UPLOAD_TARGET|RESTORE_DATABASE|\
      POSTGRES_SERVER_CERT_SOURCE|POSTGRES_SERVER_KEY_SOURCE|POSTGRES_ROOT_CA_SOURCE|\
      ISOLATION_APPROVED) ;;
      *) die "Unknown restore config key: $key" ;;
    esac
    test -z "${CONFIG_SEEN[$key]:-}" || die "Duplicate restore config key: $key"
    CONFIG_SEEN[$key]=1
    printf -v "$key" '%s' "$value"
  done <"$CONFIG_PATH"
  for key in RESTORE_RELEASE REVIEWED_SHA RESTORE_MANIFEST RESTORE_UPLOAD_TARGET RESTORE_DATABASE \
    POSTGRES_SERVER_CERT_SOURCE POSTGRES_SERVER_KEY_SOURCE POSTGRES_ROOT_CA_SOURCE \
    ISOLATION_APPROVED; do
    test -n "${CONFIG_SEEN[$key]:-}" || die "Missing restore config key: $key"
    value=${!key}
    case "$value" in ''|*REPLACE_WITH*) die "Replace $key in $CONFIG_PATH" ;; esac
  done
  case "$ISOLATION_APPROVED" in true|false) ;; *) die 'ISOLATION_APPROVED must be true or false.' ;; esac
  [[ "$RESTORE_RELEASE" =~ ^/opt/litblogs/releases/litblogs-[0-9a-f]{12}$ ]] || \
    die 'RESTORE_RELEASE is invalid.'
  [[ "$REVIEWED_SHA" =~ ^[0-9a-f]{40}$ ]] || die 'REVIEWED_SHA is invalid.'
  test "${REVIEWED_SHA:0:12}" = "${RESTORE_RELEASE##*/litblogs-}" || \
    die 'RESTORE_RELEASE does not match REVIEWED_SHA.'
  [[ "$RESTORE_MANIFEST" =~ ^/srv/litblogs-restore/staging/[A-Za-z0-9._-]+\.manifest\.json$ ]] || \
    die 'RESTORE_MANIFEST is invalid.'
  [[ "$RESTORE_UPLOAD_TARGET" =~ ^/srv/litblogs-restore/[A-Za-z0-9._-]+$ ]] || \
    die 'RESTORE_UPLOAD_TARGET is invalid.'
  [[ "$RESTORE_DATABASE" =~ ^litblog_restore_verify_[a-z0-9_]+$ ]] || \
    die 'RESTORE_DATABASE must be a new lowercase synthetic restore database name.'
}

require_release() {
  local self
  test -f "$RESTORE_RELEASE/RELEASE-MANIFEST" || die 'The admitted release is missing.'
  grep -Fxq "commit=$REVIEWED_SHA" "$RESTORE_RELEASE/RELEASE-MANIFEST" || \
    die 'The restore release manifest does not match REVIEWED_SHA.'
  self=$(readlink -f "$0")
  test "$self" = "$RESTORE_RELEASE/deploy/scripts/fresh_restore_rehearsal.sh" || \
    die 'Run the helper from the copied admitted release.'
  test -z "$(find "$RESTORE_RELEASE" \( ! -user root -o ! -group root -o \( ! -type l -perm /022 \) \) \
    -print -quit)" || die 'The restore release is not root-owned and immutable.'
}

install_python() (
  umask 022
  local build_dir
  if /usr/local/bin/python3.13 --version 2>/dev/null | grep -Fq "Python $PYTHON_VERSION"; then
    return
  fi
  build_dir=$(mktemp -d /tmp/litblogs-restore-python.XXXXXXXX)
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

phase_install_host() {
  require_root
  require_ubuntu_24044
  require_release
  note 'Installing restore prerequisites before network isolation'
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y \
    build-essential ca-certificates curl gnupg openssl postgresql-common xz-utils \
    libbz2-dev libdb-dev libexpat1-dev libffi-dev libgdbm-dev \
    libgdbm-compat-dev liblzma-dev libncurses-dev libreadline-dev \
    libsqlite3-dev libssl-dev tk-dev uuid-dev zlib1g-dev
  /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y postgresql-17 postgresql-client-17
  install_python
  # Release artifacts contain locked requirements, never a machine-local venv.
  # Install this while the disposable host still has internet access.
  /usr/local/bin/python3.13 -m venv "$RESTORE_RELEASE/.venv"
  "$RESTORE_RELEASE/.venv/bin/python" -m pip install \
    --require-hashes --only-binary=:all: -r "$RESTORE_RELEASE/litblogs/requirements.txt"
  "$RESTORE_RELEASE/.venv/bin/python" -c 'import psycopg2, sqlalchemy, alembic'
  systemctl enable --now postgresql
  /usr/lib/postgresql/17/bin/postgres --version
  note 'Do not run any internet installer after the isolation boundary is enabled.'
}

phase_restore_prepare() {
  local scram_ok restore_dba_url
  require_root
  require_release
  for source in "$POSTGRES_SERVER_CERT_SOURCE" "$POSTGRES_SERVER_KEY_SOURCE" \
    "$POSTGRES_ROOT_CA_SOURCE"; do
    test -f "$source" || die "Missing rehearsal PKI input: $source"
    test ! -L "$source" || die "Rehearsal PKI input may not be a symlink: $source"
  done
  install -d -o root -g root -m 0755 /etc/litblogs
  install -o root -g postgres -m 0644 "$POSTGRES_SERVER_CERT_SOURCE" \
    /etc/postgresql/17/main/server.crt
  install -o root -g postgres -m 0640 "$POSTGRES_SERVER_KEY_SOURCE" \
    /etc/postgresql/17/main/server.key
  install -o root -g root -m 0644 "$POSTGRES_ROOT_CA_SOURCE" \
    /etc/litblogs/postgres-root-ca.pem
  openssl x509 -in /etc/postgresql/17/main/server.crt \
    -noout -subject -issuer -dates -ext subjectAltName | grep -F 'IP Address:127.0.0.1'
  test "$(sudo -u postgres psql -Atqc "SELECT count(*) FROM pg_roles WHERE rolname='litblogs_restore_dba'")" -eq 0 || \
    die 'The restore DBA already exists; use a fresh rehearsal cluster.'
  sudo -u postgres psql -v ON_ERROR_STOP=1 <<'SQL'
ALTER SYSTEM SET listen_addresses = '127.0.0.1';
ALTER SYSTEM SET ssl = 'on';
ALTER SYSTEM SET ssl_cert_file = '/etc/postgresql/17/main/server.crt';
ALTER SYSTEM SET ssl_key_file = '/etc/postgresql/17/main/server.key';
ALTER SYSTEM SET ssl_min_protocol_version = 'TLSv1.2';
ALTER SYSTEM SET password_encryption = 'scram-sha-256';
SELECT pg_reload_conf();
CREATE ROLE litblogs_restore_dba WITH LOGIN NOINHERIT SUPERUSER CREATEDB CREATEROLE NOREPLICATION NOBYPASSRLS;
SQL
  cat >/etc/postgresql/17/main/pg_hba.conf <<'HBA'
local   all  postgres                                      peer
local   all  all                                           reject
hostssl all  litblogs_restore_dba  127.0.0.1/32            scram-sha-256
hostnossl all all                   127.0.0.1/32            reject
host    all  all                    0.0.0.0/0               reject
host    all  all                    ::/0                    reject
HBA
  systemctl restart postgresql@17-main
  printf '%s\n' 'Set the rehearsal-only restore DBA password now.'
  sudo -u postgres psql --dbname postgres --command '\password litblogs_restore_dba'
  systemctl restart postgresql@17-main
  scram_ok=$(sudo -u postgres psql --dbname postgres --tuples-only --no-align \
    --command "SELECT rolsuper AND rolcanlogin AND rolpassword LIKE 'SCRAM-SHA-256$%' FROM pg_authid WHERE rolname='litblogs_restore_dba';")
  test "$scram_ok" = t || die 'Restore DBA is not a SCRAM-enabled superuser.'
  restore_dba_url='postgresql://litblogs_restore_dba@127.0.0.1:5432/postgres?sslmode=verify-full&sslrootcert=/etc/litblogs/postgres-root-ca.pem'
  printf '%s\n' 'Confirm the rehearsal-only password once more.'
  test "$(/usr/lib/postgresql/17/bin/psql "$restore_dba_url" --password \
    --tuples-only --no-align --command 'SELECT current_user;')" = litblogs_restore_dba
  install -d -o root -g root -m 0700 /srv/litblogs-restore /srv/litblogs-restore/staging
  test -z "$(find /srv/litblogs-restore/staging -mindepth 1 -print -quit)" || \
    die 'Restore staging must be empty before the transfer.'
  create_stand_in_roles
  note 'TRANSFER PAUSE: disconnect every route, obtain signed isolation approval, then copy exactly four accepted recovery files.'
}

create_stand_in_roles() {
  test "$(sudo -u postgres psql -Atqc "SELECT count(*) FROM pg_roles WHERE rolname IN ('litblogs_migrator','litblogs_runtime','litblog_identity_owner','litblog_account_operator','litblog_invitation_operator')")" -eq 0 || \
    die 'One or more passwordless stand-in roles already exist.'
  sudo -u postgres psql --dbname postgres -v ON_ERROR_STOP=1 <<'SQL'
CREATE ROLE litblogs_migrator NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE litblogs_runtime NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE litblog_identity_owner NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE litblog_account_operator NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE litblog_invitation_operator NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
SQL
}

phase_restore_verify() {
  local restore_env=/run/litblogs-restore.env
  require_root
  cleanup_restore() { rm -f -- "$restore_env"; }
  trap cleanup_restore EXIT
  trap 'exit 129' HUP
  trap 'exit 130' INT
  trap 'exit 143' TERM
  require_release
  test "$ISOLATION_APPROVED" = true || \
    die 'ISOLATION_APPROVED is false; obtain the signed school IT isolation check.'
  test -z "$(ip route show default)" || \
    die 'The rehearsal host still has a default route.'
  # The signed check must also prove no route or credential to production,
  # students, teachers, or the internet; this local route check is only a guard.
  test -z "$(find /srv/litblogs-restore/staging -mindepth 1 -maxdepth 1 \
    ! -type f -print -quit)" || die 'Restore staging contains a link or non-file entry.'
  test "$(find /srv/litblogs-restore/staging -mindepth 1 -maxdepth 1 \
    -type f -printf '.\n' | wc -l)" -eq 4 || die 'Restore staging must contain exactly four files.'
  find /srv/litblogs-restore/staging -mindepth 1 -maxdepth 1 -type f \
    -exec chown root:root -- {} + -exec chmod 0600 -- {} +
  test -z "$(find /srv/litblogs-restore/staging -mindepth 1 -maxdepth 1 \
    -type f \( ! -user root -o ! -group root -o ! -perm 0600 \) -print -quit)" || \
    die 'Recovery files are not in root custody.'
  test -f "$RESTORE_MANIFEST" || die 'The selected accepted manifest is missing.'
  test ! -e "$RESTORE_UPLOAD_TARGET" || die 'Choose a new restore upload target.'
  test -f "$restore_env" || die "Create $restore_env with only DATABASE_URL first."
  test ! -L "$restore_env"
  test "$(stat -Lc '%U:%G:%a' "$restore_env")" = root:root:600
  test "$(grep -Ec '^DATABASE_URL=.+$' "$restore_env")" -eq 1
  test "$(grep -Evc '^(#|$|DATABASE_URL=)' "$restore_env")" -eq 0
  install -d -o root -g root -m 0700 "$RESTORE_UPLOAD_TARGET"
  systemd-run --wait --collect --pipe --quiet --service-type=exec \
    --working-directory="$RESTORE_RELEASE" --property="EnvironmentFile=$restore_env" \
    "$RESTORE_RELEASE/.venv/bin/python" \
    "$RESTORE_RELEASE/deploy/scripts/restore_verify_postgres.py" \
    --manifest "$RESTORE_MANIFEST" --upload-target "$RESTORE_UPLOAD_TARGET" \
    --target-database "$RESTORE_DATABASE" --confirm-target "$RESTORE_DATABASE"
  systemd-run --wait --collect --pipe --quiet --service-type=exec \
    --working-directory="$RESTORE_RELEASE" --property="EnvironmentFile=$restore_env" \
    "$RESTORE_RELEASE/.venv/bin/python" \
    "$RESTORE_RELEASE/deploy/scripts/restore_verify_postgres.py" \
    --verify-existing --expected-federated-identities 0 \
    --manifest "$RESTORE_MANIFEST" --upload-target "$RESTORE_UPLOAD_TARGET" \
    --target-database "$RESTORE_DATABASE" --confirm-target "$RESTORE_DATABASE"
  cleanup_restore
  trap - EXIT HUP INT TERM
  unset -f cleanup_restore
  note 'Preserve both reports. The second must report current_head before approving production.'
}

usage() {
  cat <<'USAGE'
Usage: sudo /opt/litblogs/releases/<release>/deploy/scripts/fresh_restore_rehearsal.sh PHASE

  install-host     Install Python 3.13.15 and PostgreSQL 17 before isolation
  restore-prepare  Configure the disposable TLS cluster and empty staging area
  restore-verify   Require isolation and verify the coupled recovery set twice
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
        install-host) phase_install_host ;;
        restore-prepare) phase_restore_prepare ;;
        restore-verify) phase_restore_verify ;;
        *) usage; die "Unknown phase: $phase" ;;
      esac
      ;;
  esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
