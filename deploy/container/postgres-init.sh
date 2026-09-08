#!/usr/bin/env bash
# The official PostgreSQL entrypoint runs this only for an empty PGDATA volume.
set +x
set -eu

[ "${POSTGRES_USER:-}" = postgres ] && [ "${POSTGRES_DB:-}" = litblogs ] || {
    printf '%s\n' 'The container requires POSTGRES_USER=postgres and POSTGRES_DB=litblogs.' >&2
    exit 1
}
: "${LITBLOGS_DB_PASSWORD:?Runtime database password is required}"
: "${LITBLOGS_MIGRATOR_PASSWORD:?Migration database password is required}"
: "${LITBLOGS_ACCOUNT_OPERATOR_PASSWORD:?Account operator password is required}"
: "${LITBLOGS_INVITATION_OPERATOR_PASSWORD:?Invitation operator password is required}"
: "${LITBLOGS_BACKUP_PASSWORD:?Backup password is required}"

# Suppress statement/error echo both in psql and in this server session. Passwords
# are read from the process environment, quoted as SQL literals, never shell args.
if ! psql --no-psqlrc --no-password --host=/var/run/postgresql --username=postgres --dbname=litblogs \
    --set=ON_ERROR_STOP=1 --set=VERBOSITY=terse --set=ECHO=none >/dev/null 2>&1 <<'SQL'
SET log_statement = 'none';
SET log_min_duration_statement = -1;
SET log_min_error_statement = 'panic';
SET log_parameter_max_length_on_error = 0;
SET password_encryption = 'scram-sha-256';
BEGIN;
CREATE ROLE litblogs_migrator LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE litblogs_runtime LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE litblog_identity_owner NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE litblog_account_operator LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE litblog_invitation_operator LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE litblogs_backup LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
GRANT pg_read_all_data TO litblogs_backup WITH ADMIN FALSE, INHERIT TRUE, SET TRUE;
ALTER DATABASE litblogs OWNER TO litblogs_migrator;
REVOKE CONNECT, TEMPORARY ON DATABASE postgres FROM PUBLIC;
REVOKE CONNECT, TEMPORARY ON DATABASE template0 FROM PUBLIC;
REVOKE CONNECT, TEMPORARY ON DATABASE template1 FROM PUBLIC;
REVOKE ALL ON DATABASE litblogs FROM PUBLIC;
GRANT CONNECT ON DATABASE litblogs TO litblogs_migrator, litblogs_runtime,
    litblog_account_operator, litblog_invitation_operator, litblogs_backup;
ALTER SCHEMA public OWNER TO litblogs_migrator;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
\getenv litblogs_db_password LITBLOGS_DB_PASSWORD
\getenv litblogs_migrator_password LITBLOGS_MIGRATOR_PASSWORD
\getenv litblogs_account_operator_password LITBLOGS_ACCOUNT_OPERATOR_PASSWORD
\getenv litblogs_invitation_operator_password LITBLOGS_INVITATION_OPERATOR_PASSWORD
\getenv litblogs_backup_password LITBLOGS_BACKUP_PASSWORD
SELECT format('ALTER ROLE litblogs_runtime PASSWORD %L', :'litblogs_db_password') \gexec
SELECT format('ALTER ROLE litblogs_migrator PASSWORD %L', :'litblogs_migrator_password') \gexec
SELECT format('ALTER ROLE litblog_account_operator PASSWORD %L', :'litblogs_account_operator_password') \gexec
SELECT format('ALTER ROLE litblog_invitation_operator PASSWORD %L', :'litblogs_invitation_operator_password') \gexec
SELECT format('ALTER ROLE litblogs_backup PASSWORD %L', :'litblogs_backup_password') \gexec
COMMIT;
SQL
then
    printf '%s\n' 'Fresh database role initialization failed; sensitive diagnostics were suppressed.' >&2
    exit 1
fi
printf '%s\n' 'Fresh database roles and credentials initialized.'
