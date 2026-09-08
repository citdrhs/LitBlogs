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
    True,
    True,
    True,
    True,
    True,
    True,
)


def verify_runtime_database_identity(connection) -> None:
    """Require the exact production runtime role and its negative boundaries."""

    role_record = connection.execute(
        text(
            """
            WITH runtime_crud_tables(table_name) AS (
                VALUES
                    ('assignment_drafts'),
                    ('assignment_reminder_notifications'),
                    ('assignment_submission_replies'),
                    ('assignment_submissions'),
                    ('assignments'),
                    ('blogs'),
                    ('browser_sessions'),
                    ('class_enrollments'),
                    ('classes'),
                    ('comment_likes'),
                    ('comments'),
                    ('email_verifications'),
                    ('federated_identities'),
                    ('password_resets'),
                    ('post_likes'),
                    ('push_subscriptions'),
                    ('saved_posts'),
                    ('teachers'),
                    ('upload_assets'),
                    ('user_settings'),
                    ('users')
            ),
            runtime_sequences(sequence_name) AS (
                VALUES
                    ('assignment_drafts_id_seq'),
                    ('assignment_reminder_notifications_id_seq'),
                    ('assignment_submission_replies_id_seq'),
                    ('assignment_submissions_id_seq'),
                    ('assignments_id_seq'),
                    ('blogs_id_seq'),
                    ('browser_sessions_id_seq'),
                    ('class_enrollments_id_seq'),
                    ('classes_id_seq'),
                    ('comment_likes_id_seq'),
                    ('comments_id_seq'),
                    ('email_verifications_id_seq'),
                    ('federated_identities_id_seq'),
                    ('operator_audit_events_id_seq'),
                    ('password_resets_id_seq'),
                    ('post_likes_id_seq'),
                    ('push_subscriptions_id_seq'),
                    ('saved_posts_id_seq'),
                    ('teachers_id_seq'),
                    ('upload_assets_id_seq'),
                    ('user_settings_id_seq'),
                    ('users_id_seq')
            ),
            expected_schema_acl(role_name, privilege_type, is_grantable) AS (
                VALUES ('litblogs_runtime', 'USAGE', FALSE)
            ),
            actual_schema_acl(role_name, privilege_type, is_grantable) AS (
                SELECT
                    COALESCE(grantee.rolname, 'PUBLIC'),
                    acl.privilege_type,
                    acl.is_grantable
                FROM pg_catalog.pg_namespace AS namespace
                CROSS JOIN LATERAL pg_catalog.aclexplode(
                    COALESCE(
                        namespace.nspacl,
                        pg_catalog.acldefault('n', namespace.nspowner)
                    )
                ) AS acl
                LEFT JOIN pg_catalog.pg_roles AS grantee
                  ON grantee.oid = acl.grantee
                WHERE namespace.nspname = 'public'
                  AND (
                      acl.grantee = 0
                      OR grantee.rolname = 'litblogs_runtime'
                  )
            ),
            expected_table_acl(
                role_name,
                table_name,
                privilege_type,
                is_grantable
            ) AS (
                SELECT
                    'litblogs_runtime',
                    table_name,
                    privilege_type,
                    FALSE
                FROM runtime_crud_tables
                CROSS JOIN (
                    VALUES ('SELECT'), ('INSERT'), ('UPDATE'), ('DELETE')
                ) AS privilege(privilege_type)
                UNION ALL
                SELECT 'litblogs_runtime', 'alembic_version', 'SELECT', FALSE
            ),
            actual_table_acl(
                role_name,
                table_name,
                privilege_type,
                is_grantable
            ) AS (
                SELECT
                    COALESCE(grantee.rolname, 'PUBLIC'),
                    relation.relname,
                    acl.privilege_type,
                    acl.is_grantable
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                CROSS JOIN LATERAL pg_catalog.aclexplode(
                    COALESCE(
                        relation.relacl,
                        pg_catalog.acldefault('r', relation.relowner)
                    )
                ) AS acl
                LEFT JOIN pg_catalog.pg_roles AS grantee
                  ON grantee.oid = acl.grantee
                WHERE namespace.nspname = 'public'
                  AND relation.relkind IN ('r', 'p', 'v', 'm', 'f')
                  AND (
                      acl.grantee = 0
                      OR grantee.rolname = 'litblogs_runtime'
                  )
            ),
            expected_column_acl(
                role_name,
                table_name,
                column_name,
                privilege_type,
                is_grantable
            ) AS (
                VALUES
                    ('litblogs_runtime', 'teacher_invitations', 'id', 'SELECT', FALSE),
                    ('litblogs_runtime', 'teacher_invitations', 'token_digest', 'SELECT', FALSE),
                    ('litblogs_runtime', 'teacher_invitations', 'email_digest', 'SELECT', FALSE),
                    ('litblogs_runtime', 'teacher_invitations', 'expires_at', 'SELECT', FALSE),
                    ('litblogs_runtime', 'teacher_invitations', 'consumed_at', 'SELECT', FALSE),
                    ('litblogs_runtime', 'teacher_invitations', 'revoked_at', 'SELECT', FALSE),
                    ('litblogs_runtime', 'teacher_invitations', 'consumed_at', 'UPDATE', FALSE),
                    ('litblogs_runtime', 'teacher_invitations', 'revoked_at', 'UPDATE', FALSE),
                    ('litblogs_runtime', 'operator_audit_events', 'actor_identifier', 'INSERT', FALSE),
                    ('litblogs_runtime', 'operator_audit_events', 'action', 'INSERT', FALSE),
                    ('litblogs_runtime', 'operator_audit_events', 'outcome', 'INSERT', FALSE),
                    ('litblogs_runtime', 'operator_audit_events', 'resource_digest', 'INSERT', FALSE)
            ),
            actual_column_acl(
                role_name,
                table_name,
                column_name,
                privilege_type,
                is_grantable
            ) AS (
                SELECT
                    COALESCE(grantee.rolname, 'PUBLIC'),
                    relation.relname,
                    attribute.attname,
                    acl.privilege_type,
                    acl.is_grantable
                FROM pg_catalog.pg_attribute AS attribute
                JOIN pg_catalog.pg_class AS relation
                  ON relation.oid = attribute.attrelid
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                CROSS JOIN LATERAL pg_catalog.aclexplode(attribute.attacl) AS acl
                LEFT JOIN pg_catalog.pg_roles AS grantee
                  ON grantee.oid = acl.grantee
                WHERE namespace.nspname = 'public'
                  AND attribute.attnum > 0
                  AND NOT attribute.attisdropped
                  AND (
                      acl.grantee = 0
                      OR grantee.rolname = 'litblogs_runtime'
                  )
            ),
            expected_sequence_acl(
                role_name,
                sequence_name,
                privilege_type,
                is_grantable
            ) AS (
                SELECT
                    'litblogs_runtime',
                    sequence_name,
                    privilege_type,
                    FALSE
                FROM runtime_sequences
                CROSS JOIN (VALUES ('USAGE'), ('SELECT'))
                    AS privilege(privilege_type)
            ),
            actual_sequence_acl(
                role_name,
                sequence_name,
                privilege_type,
                is_grantable
            ) AS (
                SELECT
                    COALESCE(grantee.rolname, 'PUBLIC'),
                    relation.relname,
                    acl.privilege_type,
                    acl.is_grantable
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                CROSS JOIN LATERAL pg_catalog.aclexplode(
                    COALESCE(
                        relation.relacl,
                        pg_catalog.acldefault('S', relation.relowner)
                    )
                ) AS acl
                LEFT JOIN pg_catalog.pg_roles AS grantee
                  ON grantee.oid = acl.grantee
                WHERE namespace.nspname = 'public'
                  AND relation.relkind = 'S'
                  AND (
                      acl.grantee = 0
                      OR grantee.rolname = 'litblogs_runtime'
                  )
            ),
            expected_function_acl(
                role_name,
                signature,
                privilege_type,
                is_grantable
            ) AS (
                SELECT
                    NULL::TEXT,
                    NULL::TEXT,
                    NULL::TEXT,
                    NULL::BOOLEAN
                WHERE FALSE
            ),
            actual_function_acl(
                role_name,
                signature,
                privilege_type,
                is_grantable
            ) AS (
                SELECT
                    COALESCE(grantee.rolname, 'PUBLIC'),
                    routine.proname || '(' ||
                        pg_catalog.oidvectortypes(routine.proargtypes) || ')',
                    acl.privilege_type,
                    acl.is_grantable
                FROM pg_catalog.pg_proc AS routine
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = routine.pronamespace
                CROSS JOIN LATERAL pg_catalog.aclexplode(
                    COALESCE(
                        routine.proacl,
                        pg_catalog.acldefault('f', routine.proowner)
                    )
                ) AS acl
                LEFT JOIN pg_catalog.pg_roles AS grantee
                  ON grantee.oid = acl.grantee
                WHERE namespace.nspname = 'public'
                  AND (
                      acl.grantee = 0
                      OR grantee.rolname = 'litblogs_runtime'
                  )
            )
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
                    AS has_exact_search_path,
                NOT EXISTS (
                    SELECT * FROM expected_schema_acl
                    EXCEPT
                    SELECT * FROM actual_schema_acl
                ) AND NOT EXISTS (
                    SELECT * FROM actual_schema_acl
                    EXCEPT
                    SELECT * FROM expected_schema_acl
                ) AS schema_acl_is_exact,
                NOT EXISTS (
                    SELECT * FROM expected_table_acl
                    EXCEPT
                    SELECT * FROM actual_table_acl
                ) AND NOT EXISTS (
                    SELECT * FROM actual_table_acl
                    EXCEPT
                    SELECT * FROM expected_table_acl
                ) AS table_acl_is_exact,
                NOT EXISTS (
                    SELECT * FROM expected_column_acl
                    EXCEPT
                    SELECT * FROM actual_column_acl
                ) AND NOT EXISTS (
                    SELECT * FROM actual_column_acl
                    EXCEPT
                    SELECT * FROM expected_column_acl
                ) AS column_acl_is_exact,
                NOT EXISTS (
                    SELECT * FROM expected_sequence_acl
                    EXCEPT
                    SELECT * FROM actual_sequence_acl
                ) AND NOT EXISTS (
                    SELECT * FROM actual_sequence_acl
                    EXCEPT
                    SELECT * FROM expected_sequence_acl
                ) AS sequence_acl_is_exact,
                NOT EXISTS (
                    SELECT * FROM expected_function_acl
                    EXCEPT
                    SELECT * FROM actual_function_acl
                ) AND NOT EXISTS (
                    SELECT * FROM actual_function_acl
                    EXCEPT
                    SELECT * FROM expected_function_acl
                ) AS function_acl_is_exact,
                NOT EXISTS (
                    SELECT 1
                    FROM pg_catalog.pg_database AS database_record
                    WHERE database_record.datdba = roles.oid
                ) AND NOT EXISTS (
                    SELECT 1
                    FROM pg_catalog.pg_namespace AS namespace
                    WHERE namespace.nspowner = roles.oid
                ) AND NOT EXISTS (
                    SELECT 1
                    FROM pg_catalog.pg_class AS relation
                    WHERE relation.relowner = roles.oid
                ) AND NOT EXISTS (
                    SELECT 1
                    FROM pg_catalog.pg_proc AS routine
                    WHERE routine.proowner = roles.oid
                ) AND NOT EXISTS (
                    SELECT 1
                    FROM pg_catalog.pg_type AS object_type
                    WHERE object_type.typowner = roles.oid
                ) AS runtime_owns_no_application_objects
            FROM pg_catalog.pg_roles AS roles
            WHERE roles.rolname = current_user
            """
        )
    ).one()
    if tuple(role_record) != EXPECTED_RUNTIME_DATABASE_BOUNDARY:
        raise RuntimeError("Database runtime privilege boundary mismatch")
