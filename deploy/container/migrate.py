"""Run current Alembic with migration-only credentials and bounded role membership."""

import os
import signal
import subprocess
import sys
from urllib.parse import quote, urlencode

CA_CERTIFICATE = "/etc/litblogs/postgres-root-ca.pem"
GRANT_IDENTITY_OWNER = (
    "GRANT litblog_identity_owner TO litblogs_migrator WITH ADMIN FALSE, INHERIT TRUE, SET TRUE"
)
REVOKE_IDENTITY_OWNER = "REVOKE litblog_identity_owner FROM litblogs_migrator"


class BootstrapError(RuntimeError):
    """Safe failure text; never include driver exceptions or child-process output."""


def database_url(role, password):
    if not role or not password or "\x00" in role or "\x00" in password:
        raise BootstrapError("A required database credential is missing or invalid.")
    query = urlencode({"sslmode": "verify-full", "sslrootcert": CA_CERTIFICATE})
    return f"postgresql+psycopg2://{quote(role, safe='')}:{quote(password, safe='')}@postgres.internal:5432/litblogs?{query}"


def run_migrations(environment=None, *, connect=None, run=None):
    environment = os.environ if environment is None else environment
    admin_password = environment.get("POSTGRES_PASSWORD", "")
    migration_url = database_url("litblogs_migrator", environment.get("LITBLOGS_MIGRATOR_PASSWORD", ""))
    if not admin_password or "\x00" in admin_password:
        raise BootstrapError("A required database credential is missing or invalid.")
    if connect is None:
        import psycopg2

        connect = psycopg2.connect
    run = subprocess.run if run is None else run
    child_environment = {key: environment[key] for key in ("PATH", "LANG", "LC_ALL") if key in environment}
    child_environment.update(APP_ENV="production", LITBLOGS_MIGRATION_DATABASE_URL=migration_url)
    connection = None
    attempted_grant = False
    failed = False
    revoke_failed = False
    try:
        connection = connect(
            host="postgres.internal", port=5432, dbname="litblogs", user="postgres",
            password=admin_password, sslmode="verify-full", sslrootcert=CA_CERTIFICATE, connect_timeout=10,
        )
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute("SELECT session_user, current_user, current_database()")
            if tuple(cursor.fetchone()) != ("postgres", "postgres", "litblogs"):
                raise BootstrapError("Database administrator identity verification failed.")
            cursor.execute("SET lock_timeout = '30s'")
            cursor.execute("SELECT pg_advisory_lock(741619620)")
            attempted_grant = True
            cursor.execute(GRANT_IDENTITY_OWNER)
        result = run(
            [sys.executable, "-m", "alembic", "upgrade", "head"], cwd="/opt/litblogs/litblogs",
            env=child_environment, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, check=False, timeout=1800,
        )
        failed = result.returncode != 0
    except Exception:
        failed = True
    finally:
        if connection is not None:
            try:
                if attempted_grant:
                    with connection.cursor() as cursor:
                        cursor.execute(REVOKE_IDENTITY_OWNER)
            except Exception:
                revoke_failed = True
            finally:
                try:
                    connection.close()
                except Exception:
                    failed = True
    if revoke_failed:
        raise BootstrapError("Migration privilege revocation failed; administrator review is required before startup.")
    if failed:
        raise BootstrapError("Database migration failed; any granted temporary privileges were revoked.")


def main():
    def interrupted(_signum, _frame):
        # Raising through subprocess.run terminates its child before the outer
        # finally block revokes membership. SIGKILL cannot be handled by a process.
        raise BootstrapError("Database migration interrupted; startup was stopped.")

    previous_handlers = {}
    try:
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous_handlers[signum] = signal.signal(signum, interrupted)
        run_migrations()
    except BootstrapError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception:
        print("Database migration could not start; sensitive diagnostics were suppressed.", file=sys.stderr)
        return 1
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
    print("Database migrations completed; temporary identity-owner membership was revoked.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
