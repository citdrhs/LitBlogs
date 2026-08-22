"""Pure PostgreSQL runtime-role boundary verification."""

from sqlalchemy import text

EXPECTED_RUNTIME_DATABASE_BOUNDARY = (
    "litblogs_runtime",
    "litblogs_runtime",
    False,
    False,
    False,
    False,
    True,
    False,
    False,
    False,
    True,
    False,
    False,
    False,
    True,
)


def verify_runtime_database_identity(connection) -> None:
    """Require the exact production runtime role and its negative boundaries."""

    role_record = connection.execute(
        text(
            """
            SELECT
                session_user,
                current_user,
                roles.rolsuper,
                roles.rolinherit,
                roles.rolcreaterole,
                roles.rolcreatedb,
                roles.rolcanlogin,
                roles.rolreplication,
                roles.rolbypassrls,
                EXISTS (
                    SELECT 1
                    FROM pg_catalog.pg_auth_members AS memberships
                    WHERE memberships.member = roles.oid
                       OR memberships.roleid = roles.oid
                ) AS has_role_membership,
                pg_catalog.has_schema_privilege(
                    current_user,
                    'public',
                    'USAGE'
                ) AS has_public_usage,
                pg_catalog.has_schema_privilege(
                    current_user,
                    'public',
                    'CREATE'
                ) AS has_public_create,
                pg_catalog.has_database_privilege(
                    current_user,
                    pg_catalog.current_database(),
                    'CREATE'
                ) AS has_database_create,
                pg_catalog.has_database_privilege(
                    current_user,
                    pg_catalog.current_database(),
                    'TEMP'
                ) AS has_database_temporary,
                pg_catalog.current_schemas(FALSE) = ARRAY['public'::name]
                    AS has_exact_search_path
            FROM pg_catalog.pg_roles AS roles
            WHERE roles.rolname = current_user
            """
        )
    ).one()
    if tuple(role_record) != EXPECTED_RUNTIME_DATABASE_BOUNDARY:
        raise RuntimeError("Database runtime privilege boundary mismatch")
