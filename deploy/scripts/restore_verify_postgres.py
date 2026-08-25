#!/usr/bin/env python3
"""Restore a backup only into a synthetic verification database."""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import hmac
import io
import json
import os
import re
import stat
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from postgres_common import (
    PostgresConnection,
    PostgresOperatorError,
    build_pg_environment,
    parse_postgres_url,
    postgres_executable,
    validate_postgres_client_installation,
    validate_postgres_tls_custody,
    validate_private_operator_directory,
    validate_restore_database_name,
)
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.pool import NullPool
from upload_snapshot_common import (
    AssetRecord,
    CoupledRecoverySet,
    UploadSnapshotError,
    coupled_recovery_artifact_paths,
    extract_upload_archive,
    load_coupled_recovery_set,
    registry_inventory,
    validate_existing_synthetic_upload_root,
    validate_synthetic_upload_restore_root,
    verify_upload_tree,
)

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]
DriftChecker = Callable[[PostgresConnection, str], None]
MANIFEST_FORMAT = "litblogs-postgresql-custom-v1"
MANIFEST_KEYS = frozenset({"archive", "created_at", "format", "sha256", "size_bytes"})
SHA256 = re.compile(r"^[0-9a-f]{64}$")
UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
IDENTITY_RESULT = re.compile(r"^ok:([0-9]+)$")
PSQL_VARIABLE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
MAX_MANIFEST_BYTES = 16 * 1024
EXPECTED_ALEMBIC_HEAD = "f1ad78b2035f"
BACKEND_ROOT = Path(__file__).resolve().parents[2] / "litblogs"
OPERATOR_ROUTINE_MIGRATION = (
    BACKEND_ROOT / "migrations/versions/c5136f36e302_identity_controls.py"
)
EXPECTED_OPERATOR_ROUTINE_SIGNATURES = {
    "operator_set_account_status": (
        (
            "\n    p_email VARCHAR(100),\n"
            "    p_disabled BOOLEAN,\n"
            "    p_actor_identifier VARCHAR(100),\n"
            "    p_resource_digest VARCHAR(64)\n"
        ),
        (
            "operator_set_account_status(character varying, boolean, "
            "character varying, character varying)"
        ),
    ),
    "operator_create_teacher_invitation": (
        (
            "\n    p_token_digest VARCHAR(64),\n"
            "    p_email_digest VARCHAR(64),\n"
            "    p_expires_at TIMESTAMPTZ,\n"
            "    p_actor_identifier VARCHAR(100),\n"
            "    p_resource_digest VARCHAR(64)\n"
        ),
        (
            "operator_create_teacher_invitation(character varying, character "
            "varying, timestamp with time zone, character varying, character varying)"
        ),
    ),
    "operator_revoke_teacher_invitation": (
        (
            "\n    p_email_digest VARCHAR(64),\n"
            "    p_actor_identifier VARCHAR(100),\n"
            "    p_resource_digest VARCHAR(64)\n"
        ),
        (
            "operator_revoke_teacher_invitation(character varying, character "
            "varying, character varying)"
        ),
    ),
}
OPERATOR_ROUTINE_SOURCE = re.compile(
    r"CREATE OR REPLACE FUNCTION public\."
    r"(?P<name>operator_[a-z_]+)\((?P<arguments>.*?)\)\n"
    r"RETURNS (?P<return_type>[^\n]+)\n"
    r"LANGUAGE (?P<language>[a-z0-9_]+)\n"
    r"SECURITY DEFINER\n"
    r"SET search_path = pg_catalog, pg_temp\n"
    r"AS \$(?P<tag>[a-z_]+)\$(?P<body>.*?)\$(?P=tag)\$;",
    re.DOTALL,
)


def _load_expected_operator_routine_contract(
    backend_root: Path = BACKEND_ROOT,
) -> dict[str, dict[str, object]]:
    """Extract the reviewed byte-exact routine bodies from the creating migration."""

    migration_path = (
        backend_root / "migrations/versions/c5136f36e302_identity_controls.py"
    )
    try:
        migration_source = migration_path.read_text(encoding="utf-8")
        migration_module = ast.parse(migration_source, filename=str(migration_path))
    except (OSError, SyntaxError, UnicodeError):
        raise PostgresOperatorError(
            "The reviewed operator routine source contract is invalid"
        ) from None

    operator_sql_values: list[str] = []
    for statement in migration_module.body:
        if not isinstance(statement, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name)
            and target.id == "OPERATOR_FUNCTIONS_SQL"
            for target in statement.targets
        ):
            continue
        if not isinstance(statement.value, ast.Constant) or not isinstance(
            statement.value.value, str
        ):
            raise PostgresOperatorError(
                "The reviewed operator routine source contract is invalid"
            )
        operator_sql_values.append(statement.value.value)
    if len(operator_sql_values) != 1:
        raise PostgresOperatorError(
            "The reviewed operator routine source contract is invalid"
        )
    operator_sql = operator_sql_values[0]
    matches = list(OPERATOR_ROUTINE_SOURCE.finditer(operator_sql))
    if (
        operator_sql.count("CREATE OR REPLACE FUNCTION public.") != 3
        or len(matches) != 3
    ):
        raise PostgresOperatorError(
            "The reviewed operator routine source contract is invalid"
        )

    contract: dict[str, dict[str, object]] = {}
    for match in matches:
        name = match.group("name")
        expected_signature = EXPECTED_OPERATOR_ROUTINE_SIGNATURES.get(name)
        if (
            expected_signature is None
            or match.group("arguments") != expected_signature[0]
            or match.group("return_type") != "VARCHAR(16)"
            or match.group("language") != "plpgsql"
            or match.group("tag") != name
            or expected_signature[1] in contract
        ):
            raise PostgresOperatorError(
                "The reviewed operator routine source contract is invalid"
            )
        contract[expected_signature[1]] = {
            "source": match.group("body"),
            "language": "plpgsql",
            "return_type": "character varying",
            "volatility": "v",
            "parallel_safety": "u",
            "strict": False,
            "leakproof": False,
            "kind": "f",
            "security_definer": True,
            "configuration": ["search_path=pg_catalog, pg_temp"],
            "argument_defaults": 0,
            "owner": "litblog_identity_owner",
        }
    if set(contract) != {
        signature for _arguments, signature in EXPECTED_OPERATOR_ROUTINE_SIGNATURES.values()
    }:
        raise PostgresOperatorError(
            "The reviewed operator routine source contract is invalid"
        )
    return contract


EXPECTED_OPERATOR_ROUTINE_CONTRACT = _load_expected_operator_routine_contract()
OPERATOR_ROUTINE_CATALOG_SQL = """
SELECT COALESCE(
    pg_catalog.jsonb_agg(
        pg_catalog.jsonb_build_object(
            'signature', routine.proname || '(' ||
                pg_catalog.oidvectortypes(routine.proargtypes) || ')',
            'source_hex', pg_catalog.encode(
                pg_catalog.convert_to(routine.prosrc, 'UTF8'), 'hex'
            ),
            'language', language.lanname,
            'return_type', pg_catalog.format_type(routine.prorettype, NULL),
            'volatility', routine.provolatile,
            'parallel_safety', routine.proparallel,
            'strict', routine.proisstrict,
            'leakproof', routine.proleakproof,
            'kind', routine.prokind,
            'security_definer', routine.prosecdef,
            'configuration', routine.proconfig,
            'argument_defaults', routine.pronargdefaults,
            'owner', owner.rolname
        ) ORDER BY routine.proname,
            pg_catalog.oidvectortypes(routine.proargtypes)
    ),
    '[]'::pg_catalog.jsonb
)::text
FROM pg_catalog.pg_proc AS routine
JOIN pg_catalog.pg_namespace AS namespace
  ON namespace.oid = routine.pronamespace
JOIN pg_catalog.pg_language AS language ON language.oid = routine.prolang
JOIN pg_catalog.pg_roles AS owner ON owner.oid = routine.proowner
WHERE namespace.nspname = 'public';
""".strip()
SYNTHETIC_TARGET_STATE_SQL = """
WITH required_roles(role_name) AS (
    VALUES
        ('litblogs_migrator'),
        ('litblogs_runtime'),
        ('litblog_identity_owner'),
        ('litblog_account_operator'),
        ('litblog_invitation_operator')
),
role_state AS (
    SELECT
        COUNT(*) = 5
        AND BOOL_AND(
            NOT role.rolcanlogin
            AND NOT role.rolinherit
            AND NOT role.rolsuper
            AND NOT role.rolcreatedb
            AND NOT role.rolcreaterole
            AND NOT role.rolreplication
            AND NOT role.rolbypassrls
        )
        AND NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_auth_members AS membership
            JOIN pg_catalog.pg_roles AS granted_role
              ON granted_role.oid = membership.roleid
            JOIN pg_catalog.pg_roles AS member_role
              ON member_role.oid = membership.member
            WHERE granted_role.rolname IN (
                SELECT role_name FROM required_roles
            ) OR member_role.rolname IN (
                SELECT role_name FROM required_roles
            )
        ) AS valid
    FROM pg_catalog.pg_roles AS role
    JOIN required_roles ON required_roles.role_name = role.rolname
),
restore_role AS (
    SELECT
        role.rolsuper
        AND pg_catalog.current_schemas(FALSE) = ARRAY['public'::name] AS valid
    FROM pg_catalog.pg_roles AS role
    WHERE role.rolname = CURRENT_USER
)
SELECT CASE
    WHEN NOT COALESCE((SELECT valid FROM restore_role), FALSE)
        THEN 'restore-dba-invalid'
    WHEN NOT COALESCE((SELECT valid FROM role_state), FALSE)
        THEN 'isolated-roles-invalid'
    WHEN EXISTS (
        SELECT 1 FROM pg_database WHERE datname = :'target_database'
    ) THEN 'exists'
    ELSE 'absent'
END;
""".strip()
UPLOAD_REGISTRY_INVENTORY_SQL = """
COPY (
    SELECT
        id AS asset_id,
        storage_key,
        state,
        size_bytes,
        pg_catalog.rtrim(sha256_digest) AS sha256_digest
    FROM public.upload_assets
    ORDER BY storage_key
) TO STDOUT WITH (FORMAT CSV, HEADER TRUE);
""".strip()

SCHEMA_INTEGRITY_SQL = """
WITH required_tables(name) AS (
    VALUES
        ('users'),
        ('password_resets'),
        ('push_subscriptions'),
        ('teachers'),
        ('user_settings'),
        ('classes'),
        ('assignments'),
        ('blogs'),
        ('class_enrollments'),
        ('assignment_drafts'),
        ('assignment_reminder_notifications'),
        ('assignment_submissions'),
        ('comments'),
        ('post_likes'),
        ('saved_posts'),
        ('assignment_submission_replies'),
        ('comment_likes'),
        ('upload_assets')
),
expected_foreign_keys(
    table_name,
    column_name,
    foreign_table_name,
    foreign_column_name
) AS (
    VALUES
        ('password_resets', 'user_id', 'users', 'id'),
        ('push_subscriptions', 'user_id', 'users', 'id'),
        ('teachers', 'user_id', 'users', 'id'),
        ('user_settings', 'user_id', 'users', 'id'),
        ('classes', 'teacher_id', 'teachers', 'id'),
        ('assignments', 'class_id', 'classes', 'id'),
        ('assignments', 'created_by', 'users', 'id'),
        ('blogs', 'class_id', 'classes', 'id'),
        ('blogs', 'owner_id', 'users', 'id'),
        ('class_enrollments', 'class_id', 'classes', 'id'),
        ('class_enrollments', 'student_id', 'users', 'id'),
        ('assignment_drafts', 'assignment_id', 'assignments', 'id'),
        ('assignment_drafts', 'student_id', 'users', 'id'),
        ('assignment_reminder_notifications', 'assignment_id', 'assignments', 'id'),
        ('assignment_reminder_notifications', 'user_id', 'users', 'id'),
        ('assignment_submissions', 'assignment_id', 'assignments', 'id'),
        ('assignment_submissions', 'student_id', 'users', 'id'),
        ('comments', 'blog_id', 'blogs', 'id'),
        ('comments', 'parent_id', 'comments', 'id'),
        ('comments', 'user_id', 'users', 'id'),
        ('post_likes', 'post_id', 'blogs', 'id'),
        ('post_likes', 'user_id', 'users', 'id'),
        ('saved_posts', 'post_id', 'blogs', 'id'),
        ('saved_posts', 'user_id', 'users', 'id'),
        ('assignment_submission_replies', 'submission_id', 'assignment_submissions', 'id'),
        ('assignment_submission_replies', 'user_id', 'users', 'id'),
        ('comment_likes', 'comment_id', 'comments', 'id'),
        ('comment_likes', 'user_id', 'users', 'id'),
        ('upload_assets', 'owner_user_id', 'users', 'id'),
        ('upload_assets', 'blog_id', 'blogs', 'id')
),
actual_foreign_keys AS (
    SELECT
        constraint_table.table_name,
        key_column.column_name,
        foreign_column.table_name AS foreign_table_name,
        foreign_column.column_name AS foreign_column_name
    FROM information_schema.table_constraints AS constraint_table
    JOIN information_schema.key_column_usage AS key_column
      ON key_column.constraint_schema = constraint_table.constraint_schema
     AND key_column.constraint_name = constraint_table.constraint_name
    JOIN information_schema.constraint_column_usage AS foreign_column
      ON foreign_column.constraint_schema = constraint_table.constraint_schema
     AND foreign_column.constraint_name = constraint_table.constraint_name
    WHERE constraint_table.constraint_type = 'FOREIGN KEY'
      AND constraint_table.table_schema = 'public'
      AND foreign_column.table_schema = 'public'
)
SELECT CASE WHEN COUNT(to_regclass('public.' || name)) = COUNT(*)
                 AND BOOL_AND(to_regclass('public.' || name) IS NOT NULL)
                 AND NOT EXISTS (
                     SELECT 1
                     FROM expected_foreign_keys AS expected
                     WHERE NOT EXISTS (
                         SELECT 1
                         FROM actual_foreign_keys AS actual
                         WHERE actual.table_name = expected.table_name
                           AND actual.column_name = expected.column_name
                           AND actual.foreign_table_name = expected.foreign_table_name
                           AND actual.foreign_column_name = expected.foreign_column_name
                     )
                 )
                 AND (
                     to_regclass('public.federated_identities') IS NULL
                     OR (
                         EXISTS (
                             SELECT 1
                             FROM actual_foreign_keys AS identity_foreign_key
                             WHERE identity_foreign_key.table_name = 'federated_identities'
                               AND identity_foreign_key.column_name = 'user_id'
                               AND identity_foreign_key.foreign_table_name = 'users'
                               AND identity_foreign_key.foreign_column_name = 'id'
                         )
                         AND EXISTS (
                             SELECT 1
                             FROM pg_constraint AS identity_constraint
                             WHERE identity_constraint.conrelid =
                                   to_regclass('public.federated_identities')
                               AND identity_constraint.contype = 'p'
                         )
                         AND EXISTS (
                             SELECT 1
                             FROM pg_constraint AS identity_constraint
                             WHERE identity_constraint.conrelid =
                                   to_regclass('public.federated_identities')
                               AND identity_constraint.conname =
                                   'ck_federated_identity_provider'
                               AND identity_constraint.contype = 'c'
                         )
                         AND EXISTS (
                             SELECT 1
                             FROM pg_constraint AS identity_constraint
                             WHERE identity_constraint.conrelid =
                                   to_regclass('public.federated_identities')
                               AND identity_constraint.conname =
                                   'uq_federated_identity_subject'
                               AND identity_constraint.contype = 'u'
                         )
                         AND EXISTS (
                             SELECT 1
                             FROM pg_constraint AS identity_constraint
                             WHERE identity_constraint.conrelid =
                                   to_regclass('public.federated_identities')
                               AND identity_constraint.conname =
                                   'uq_federated_identity_provider_user'
                               AND identity_constraint.contype = 'u'
                         )
                         AND to_regclass(
                             'public.ix_federated_identities_user_id'
                         ) IS NOT NULL
                     )
                 )
                 AND NOT EXISTS (
                     SELECT 1
                     FROM pg_constraint AS constraint_record
                     JOIN pg_class AS constrained_table
                       ON constrained_table.oid = constraint_record.conrelid
                     JOIN pg_namespace AS constrained_schema
                       ON constrained_schema.oid = constrained_table.relnamespace
                     WHERE constrained_schema.nspname = 'public'
                       AND constraint_record.contype IN ('c', 'f')
                       AND NOT constraint_record.convalidated
                 )
            THEN 'ok' ELSE 'failed' END
FROM required_tables;
""".strip()

MIGRATION_STATE_SQL = """
SELECT CASE
    WHEN to_regclass('public.alembic_version') IS NULL
     AND to_regclass('public.federated_identities') IS NULL
        THEN 'pre_alembic'
    WHEN to_regclass('public.alembic_version') IS NOT NULL
     AND to_regclass('public.federated_identities') IS NOT NULL
        THEN 'versioned'
    ELSE 'mixed'
END;
""".strip()

CORE_DATA_INTEGRITY_SQL = """
SELECT CASE WHEN
    (SELECT COUNT(*) FROM public.users) >= 0
    AND (SELECT COUNT(*) FROM public.password_resets) >= 0
    AND (SELECT COUNT(*) FROM public.push_subscriptions) >= 0
    AND (SELECT COUNT(*) FROM public.teachers) >= 0
    AND (SELECT COUNT(*) FROM public.user_settings) >= 0
    AND (SELECT COUNT(*) FROM public.classes) >= 0
    AND (SELECT COUNT(*) FROM public.assignments) >= 0
    AND (SELECT COUNT(*) FROM public.blogs) >= 0
    AND (SELECT COUNT(*) FROM public.class_enrollments) >= 0
    AND (SELECT COUNT(*) FROM public.assignment_drafts) >= 0
    AND (SELECT COUNT(*) FROM public.assignment_reminder_notifications) >= 0
    AND (SELECT COUNT(*) FROM public.assignment_submissions) >= 0
    AND (SELECT COUNT(*) FROM public.comments) >= 0
    AND (SELECT COUNT(*) FROM public.post_likes) >= 0
    AND (SELECT COUNT(*) FROM public.saved_posts) >= 0
    AND (SELECT COUNT(*) FROM public.assignment_submission_replies) >= 0
    AND (SELECT COUNT(*) FROM public.comment_likes) >= 0
    AND (SELECT COUNT(*) FROM public.upload_assets) >= 0
    AND NOT EXISTS (
        SELECT 1
        FROM public.blogs AS blog
        LEFT JOIN public.users AS owner ON owner.id = blog.owner_id
        LEFT JOIN public.classes AS class_record ON class_record.id = blog.class_id
        WHERE owner.id IS NULL OR class_record.id IS NULL
    )
    AND NOT EXISTS (
        SELECT 1
        FROM public.class_enrollments AS enrollment
        LEFT JOIN public.users AS student ON student.id = enrollment.student_id
        LEFT JOIN public.classes AS class_record ON class_record.id = enrollment.class_id
        WHERE student.id IS NULL OR class_record.id IS NULL
    )
THEN 'ok' ELSE 'failed' END;
""".strip()

IDENTITY_DATA_INTEGRITY_SQL = """
WITH application_roles(role_name) AS (
    VALUES
        ('litblogs_migrator'),
        ('litblogs_runtime'),
        ('litblog_identity_owner'),
        ('litblog_account_operator'),
        ('litblog_invitation_operator')
),
runtime_crud_tables(table_name) AS (
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
    VALUES
        ('litblogs_runtime', 'USAGE', FALSE),
        ('litblog_identity_owner', 'USAGE', FALSE),
        ('litblog_account_operator', 'USAGE', FALSE),
        ('litblog_invitation_operator', 'USAGE', FALSE)
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
    LEFT JOIN pg_catalog.pg_roles AS grantee ON grantee.oid = acl.grantee
    WHERE namespace.nspname = 'public'
      AND acl.grantee <> namespace.nspowner
),
expected_table_acl(role_name, table_name, privilege_type, is_grantable) AS (
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
actual_table_acl(role_name, table_name, privilege_type, is_grantable) AS (
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
    LEFT JOIN pg_catalog.pg_roles AS grantee ON grantee.oid = acl.grantee
    WHERE namespace.nspname = 'public'
      AND relation.relkind IN ('r', 'p', 'v', 'm', 'f')
      AND acl.grantee <> relation.relowner
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
        ('litblogs_runtime', 'operator_audit_events', 'resource_digest', 'INSERT', FALSE),
        ('litblog_identity_owner', 'users', 'id', 'SELECT', FALSE),
        ('litblog_identity_owner', 'users', 'email', 'SELECT', FALSE),
        ('litblog_identity_owner', 'users', 'disabled_at', 'UPDATE', FALSE),
        ('litblog_identity_owner', 'browser_sessions', 'user_id', 'SELECT', FALSE),
        ('litblog_identity_owner', 'browser_sessions', 'revoked_at', 'SELECT', FALSE),
        ('litblog_identity_owner', 'browser_sessions', 'expires_at', 'SELECT', FALSE),
        ('litblog_identity_owner', 'browser_sessions', 'revoked_at', 'UPDATE', FALSE),
        ('litblog_identity_owner', 'password_resets', 'user_id', 'SELECT', FALSE),
        ('litblog_identity_owner', 'password_resets', 'token', 'UPDATE', FALSE),
        ('litblog_identity_owner', 'password_resets', 'expires_at', 'UPDATE', FALSE),
        ('litblog_identity_owner', 'password_resets', 'used', 'UPDATE', FALSE),
        ('litblog_identity_owner', 'password_resets', 'delivery_status', 'UPDATE', FALSE),
        ('litblog_identity_owner', 'password_resets', 'delivery_attempted_at', 'UPDATE', FALSE),
        ('litblog_identity_owner', 'password_resets', 'delivery_claim_digest', 'UPDATE', FALSE),
        ('litblog_identity_owner', 'teacher_invitations', 'email_digest', 'SELECT', FALSE),
        ('litblog_identity_owner', 'teacher_invitations', 'consumed_at', 'SELECT', FALSE),
        ('litblog_identity_owner', 'teacher_invitations', 'revoked_at', 'SELECT', FALSE),
        ('litblog_identity_owner', 'teacher_invitations', 'expires_at', 'SELECT', FALSE),
        ('litblog_identity_owner', 'teacher_invitations', 'token_digest', 'INSERT', FALSE),
        ('litblog_identity_owner', 'teacher_invitations', 'email_digest', 'INSERT', FALSE),
        ('litblog_identity_owner', 'teacher_invitations', 'expires_at', 'INSERT', FALSE),
        ('litblog_identity_owner', 'teacher_invitations', 'created_by', 'INSERT', FALSE),
        ('litblog_identity_owner', 'teacher_invitations', 'revoked_at', 'UPDATE', FALSE),
        ('litblog_identity_owner', 'operator_audit_events', 'actor_identifier', 'INSERT', FALSE),
        ('litblog_identity_owner', 'operator_audit_events', 'action', 'INSERT', FALSE),
        ('litblog_identity_owner', 'operator_audit_events', 'outcome', 'INSERT', FALSE),
        ('litblog_identity_owner', 'operator_audit_events', 'resource_digest', 'INSERT', FALSE)
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
    JOIN pg_catalog.pg_class AS relation ON relation.oid = attribute.attrelid
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = relation.relnamespace
    CROSS JOIN LATERAL pg_catalog.aclexplode(attribute.attacl) AS acl
    LEFT JOIN pg_catalog.pg_roles AS grantee ON grantee.oid = acl.grantee
    WHERE namespace.nspname = 'public'
      AND attribute.attnum > 0
      AND NOT attribute.attisdropped
),
expected_sequence_acl(role_name, sequence_name, privilege_type, is_grantable) AS (
    SELECT
        'litblogs_runtime',
        sequence_name,
        privilege_type,
        FALSE
    FROM runtime_sequences
    CROSS JOIN (VALUES ('USAGE'), ('SELECT')) AS privilege(privilege_type)
    UNION ALL
    SELECT
        'litblog_identity_owner',
        sequence_name,
        'USAGE',
        FALSE
    FROM (
        VALUES
            ('teacher_invitations_id_seq'),
            ('operator_audit_events_id_seq')
    ) AS identity_sequence(sequence_name)
),
actual_sequence_acl(role_name, sequence_name, privilege_type, is_grantable) AS (
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
    LEFT JOIN pg_catalog.pg_roles AS grantee ON grantee.oid = acl.grantee
    WHERE namespace.nspname = 'public'
      AND relation.relkind = 'S'
      AND acl.grantee <> relation.relowner
),
expected_routines(signature) AS (
    VALUES
        ('operator_set_account_status(character varying, boolean, character varying, character varying)'),
        ('operator_create_teacher_invitation(character varying, character varying, timestamp with time zone, character varying, character varying)'),
        ('operator_revoke_teacher_invitation(character varying, character varying, character varying)')
),
actual_routines(function_oid, signature, owner_name, prosecdef, proconfig) AS (
    SELECT
        routine.oid,
        routine.proname || '(' ||
            pg_catalog.oidvectortypes(routine.proargtypes) || ')',
        owner.rolname,
        routine.prosecdef,
        routine.proconfig
    FROM pg_catalog.pg_proc AS routine
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = routine.pronamespace
    JOIN pg_catalog.pg_roles AS owner ON owner.oid = routine.proowner
    WHERE namespace.nspname = 'public'
),
expected_function_acl(role_name, signature, privilege_type, is_grantable) AS (
    VALUES
        ('litblog_account_operator', 'operator_set_account_status(character varying, boolean, character varying, character varying)', 'EXECUTE', FALSE),
        ('litblog_invitation_operator', 'operator_create_teacher_invitation(character varying, character varying, timestamp with time zone, character varying, character varying)', 'EXECUTE', FALSE),
        ('litblog_invitation_operator', 'operator_revoke_teacher_invitation(character varying, character varying, character varying)', 'EXECUTE', FALSE)
),
actual_function_acl(role_name, signature, privilege_type, is_grantable) AS (
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
    LEFT JOIN pg_catalog.pg_roles AS grantee ON grantee.oid = acl.grantee
    WHERE namespace.nspname = 'public'
      AND acl.grantee <> routine.proowner
),
expected_default_function_acl(
    owner_name,
    namespace_name,
    object_type,
    grantor_name,
    grantee_name,
    privilege_type,
    is_grantable
) AS (
    VALUES
        (
            'litblogs_migrator',
            'GLOBAL',
            'f'::"char",
            'litblogs_migrator',
            'litblogs_migrator',
            'EXECUTE',
            FALSE
        )
),
actual_default_function_acl(
    owner_name,
    namespace_name,
    object_type,
    grantor_name,
    grantee_name,
    privilege_type,
    is_grantable
) AS (
    SELECT
        owner.rolname,
        COALESCE(namespace.nspname, 'GLOBAL'),
        default_acl.defaclobjtype,
        grantor.rolname,
        COALESCE(grantee.rolname, 'PUBLIC'),
        acl.privilege_type,
        acl.is_grantable
    FROM pg_catalog.pg_default_acl AS default_acl
    JOIN pg_catalog.pg_roles AS owner
      ON owner.oid = default_acl.defaclrole
    JOIN application_roles ON application_roles.role_name = owner.rolname
    LEFT JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = default_acl.defaclnamespace
    CROSS JOIN LATERAL pg_catalog.aclexplode(default_acl.defaclacl) AS acl
    JOIN pg_catalog.pg_roles AS grantor ON grantor.oid = acl.grantor
    LEFT JOIN pg_catalog.pg_roles AS grantee ON grantee.oid = acl.grantee
),
expected_user_schemas(schema_name) AS (
    VALUES ('public')
),
actual_user_schemas(schema_name) AS (
    SELECT namespace.nspname
    FROM pg_catalog.pg_namespace AS namespace
    WHERE namespace.nspname <> 'information_schema'
      AND namespace.nspname !~ '^pg_'
),
role_contract_valid AS (
    SELECT COUNT(*) = 5 AND BOOL_AND(
        NOT role.rolcanlogin
        AND NOT role.rolinherit
        AND NOT role.rolsuper
        AND NOT role.rolcreatedb
        AND NOT role.rolcreaterole
        AND NOT role.rolreplication
        AND NOT role.rolbypassrls
    ) AS valid
    FROM pg_catalog.pg_roles AS role
    JOIN application_roles ON application_roles.role_name = role.rolname
),
routine_contract_valid AS (
    SELECT
        COUNT(*) = 3
        AND BOOL_AND(owner_name = 'litblog_identity_owner')
        AND BOOL_AND(prosecdef)
        AND BOOL_AND(
            proconfig = ARRAY['search_path=pg_catalog, pg_temp']::text[]
        ) AS valid
    FROM actual_routines
),
default_function_acl_scope_valid AS (
    SELECT
        COUNT(*) = 1
        AND COUNT(*) FILTER (
            WHERE owner.rolname = 'litblogs_migrator'
              AND default_acl.defaclnamespace = 0
              AND default_acl.defaclobjtype = 'f'
        ) = 1
        AND COUNT(*) FILTER (WHERE default_acl.defaclnamespace <> 0) = 0 AS valid
    FROM pg_catalog.pg_default_acl AS default_acl
    JOIN pg_catalog.pg_roles AS owner
      ON owner.oid = default_acl.defaclrole
    JOIN application_roles ON application_roles.role_name = owner.rolname
),
database_acl_valid AS (
    SELECT
        owner.rolname = CURRENT_USER
        AND database_record.datallowconn
        AND NOT EXISTS (
            SELECT 1
            FROM pg_catalog.aclexplode(
                COALESCE(
                    database_record.datacl,
                    pg_catalog.acldefault('d', database_record.datdba)
                )
            ) AS acl
            WHERE acl.grantee <> database_record.datdba
        ) AS valid
    FROM pg_catalog.pg_database AS database_record
    JOIN pg_catalog.pg_roles AS owner ON owner.oid = database_record.datdba
    WHERE database_record.datname = pg_catalog.current_database()
)
SELECT CASE WHEN
    (SELECT COUNT(*) FROM public.federated_identities) >= 0
    AND NOT EXISTS (
        SELECT 1
        FROM public.federated_identities AS identity
        LEFT JOIN public.users AS identity_user ON identity_user.id = identity.user_id
        WHERE identity_user.id IS NULL
           OR identity.provider IS NULL
           OR identity.provider NOT IN ('google', 'microsoft')
           OR identity.issuer IS NULL
           OR pg_catalog.btrim(identity.issuer) = ''
           OR identity.subject IS NULL
           OR pg_catalog.btrim(identity.subject) = ''
    )
    AND NOT EXISTS (
        SELECT 1
        FROM public.federated_identities
        GROUP BY provider, issuer, subject
        HAVING COUNT(*) > 1
    )
    AND NOT EXISTS (
        SELECT 1
        FROM public.federated_identities
        GROUP BY provider, user_id
        HAVING COUNT(*) > 1
    )
    AND (SELECT valid FROM role_contract_valid)
    AND (SELECT valid FROM routine_contract_valid)
    AND (SELECT valid FROM default_function_acl_scope_valid)
    AND (SELECT valid FROM database_acl_valid)
    AND NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_auth_members AS membership
        JOIN pg_catalog.pg_roles AS granted_role
          ON granted_role.oid = membership.roleid
        JOIN pg_catalog.pg_roles AS member_role
          ON member_role.oid = membership.member
        WHERE granted_role.rolname IN (SELECT role_name FROM application_roles)
           OR member_role.rolname IN (SELECT role_name FROM application_roles)
    )
    AND (
        SELECT owner.rolname = 'litblogs_migrator'
        FROM pg_catalog.pg_namespace AS namespace
        JOIN pg_catalog.pg_roles AS owner ON owner.oid = namespace.nspowner
        WHERE namespace.nspname = 'public'
    )
    AND NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        JOIN pg_catalog.pg_roles AS owner ON owner.oid = relation.relowner
        WHERE namespace.nspname = 'public'
          AND owner.rolname <> 'litblogs_migrator'
    )
    AND NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_type AS object_type
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = object_type.typnamespace
        JOIN pg_catalog.pg_roles AS owner ON owner.oid = object_type.typowner
        WHERE namespace.nspname = 'public'
          AND owner.rolname <> 'litblogs_migrator'
    )
    AND NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_proc AS routine
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = routine.pronamespace
        JOIN pg_catalog.pg_roles AS owner ON owner.oid = routine.proowner
        WHERE namespace.nspname = 'public'
          AND owner.rolname <> 'litblog_identity_owner'
    )
    AND NOT EXISTS (
        SELECT signature FROM expected_routines
        EXCEPT
        SELECT signature FROM actual_routines
    )
    AND NOT EXISTS (
        SELECT signature FROM actual_routines
        EXCEPT
        SELECT signature FROM expected_routines
    )
    AND NOT EXISTS (
        SELECT * FROM expected_schema_acl
        EXCEPT
        SELECT * FROM actual_schema_acl
    )
    AND NOT EXISTS (
        SELECT * FROM actual_schema_acl
        EXCEPT
        SELECT * FROM expected_schema_acl
    )
    AND NOT EXISTS (
        SELECT * FROM expected_table_acl
        EXCEPT
        SELECT * FROM actual_table_acl
    )
    AND NOT EXISTS (
        SELECT * FROM actual_table_acl
        EXCEPT
        SELECT * FROM expected_table_acl
    )
    AND NOT EXISTS (
        SELECT * FROM expected_column_acl
        EXCEPT
        SELECT * FROM actual_column_acl
    )
    AND NOT EXISTS (
        SELECT * FROM actual_column_acl
        EXCEPT
        SELECT * FROM expected_column_acl
    )
    AND NOT EXISTS (
        SELECT * FROM expected_sequence_acl
        EXCEPT
        SELECT * FROM actual_sequence_acl
    )
    AND NOT EXISTS (
        SELECT * FROM actual_sequence_acl
        EXCEPT
        SELECT * FROM expected_sequence_acl
    )
    AND NOT EXISTS (
        SELECT * FROM expected_function_acl
        EXCEPT
        SELECT * FROM actual_function_acl
    )
    AND NOT EXISTS (
        SELECT * FROM actual_function_acl
        EXCEPT
        SELECT * FROM expected_function_acl
    )
    AND NOT EXISTS (
        SELECT * FROM expected_default_function_acl
        EXCEPT
        SELECT * FROM actual_default_function_acl
    )
    AND NOT EXISTS (
        SELECT * FROM actual_default_function_acl
        EXCEPT
        SELECT * FROM expected_default_function_acl
    )
    AND NOT EXISTS (
        SELECT * FROM expected_user_schemas
        EXCEPT
        SELECT * FROM actual_user_schemas
    )
    AND NOT EXISTS (
        SELECT * FROM actual_user_schemas
        EXCEPT
        SELECT * FROM expected_user_schemas
    )
THEN 'ok:' || (SELECT COUNT(*) FROM public.federated_identities)::text
ELSE 'failed' END;
""".strip()


@dataclass(frozen=True)
class RestoreVerificationResult:
    target_database: str
    migration_state: str
    alembic_revision: str | None
    federated_identity_count: int | None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as backup_file:
        for chunk in iter(lambda: backup_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    manifest_object: dict[str, object] = {}
    for key, value in pairs:
        if key in manifest_object:
            raise ValueError("duplicate manifest key")
        manifest_object[key] = value
    return manifest_object


def _valid_utc_timestamp(value: object) -> bool:
    if not isinstance(value, str) or not UTC_TIMESTAMP.fullmatch(value):
        return False
    try:
        parsed = datetime.fromisoformat(f"{value[:-1]}+00:00")
    except ValueError:
        return False
    return parsed.tzinfo == UTC


def _require_private_custody(path: Path) -> None:
    """Require restore inputs to be owned and accessible only by this operator."""

    if os.name != "posix":
        return
    try:
        if not path.is_absolute() or path.resolve(strict=True) != path:
            raise ValueError
        metadata = path.stat(follow_symlinks=False)
    except (OSError, ValueError) as exc:
        raise PostgresOperatorError(
            "Backup input custody could not be verified"
        ) from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_mode & 0o077
    ):
        raise PostgresOperatorError(
            "Backup archive and manifest custody must be owner-only"
        )


def _load_and_verify_manifest(archive: Path, manifest: Path) -> None:
    if archive.parent != manifest.parent:
        raise PostgresOperatorError(
            "Backup archive and manifest must share one private staging directory"
        )
    validate_private_operator_directory(
        archive.parent, purpose="restore staging directory"
    )
    _require_private_custody(archive)
    _require_private_custody(manifest)
    try:
        coupled = _load_coupled_with_custody(manifest)
    except PostgresOperatorError:
        coupled = None
    if coupled is not None:
        if coupled.database_archive != archive:
            raise PostgresOperatorError(
                "The coupled recovery manifest does not bind this database archive"
            )
        return

    if archive.is_symlink() or not archive.is_file():
        raise PostgresOperatorError("The backup archive must be a regular file")
    if manifest.is_symlink() or not manifest.is_file():
        raise PostgresOperatorError("The backup manifest must be a regular file")
    if manifest.stat().st_size > MAX_MANIFEST_BYTES:
        raise PostgresOperatorError("The backup manifest is malformed")
    try:
        payload = json.loads(
            manifest.read_text(encoding="utf-8"),
            object_pairs_hook=_manifest_object,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PostgresOperatorError("The backup manifest is malformed") from exc
    if not isinstance(payload, dict) or set(payload) != MANIFEST_KEYS:
        raise PostgresOperatorError("The backup manifest is malformed")

    archive_name = payload.get("archive")
    created_at = payload.get("created_at")
    manifest_format = payload.get("format")
    checksum = payload.get("sha256")
    size_bytes = payload.get("size_bytes")
    if (
        not isinstance(archive_name, str)
        or Path(archive_name).name != archive_name
        or archive_name != archive.name
        or not _valid_utc_timestamp(created_at)
        or manifest_format != MANIFEST_FORMAT
        or not isinstance(checksum, str)
        or not SHA256.fullmatch(checksum)
        or type(size_bytes) is not int
        or size_bytes < 5
    ):
        raise PostgresOperatorError("The backup manifest is malformed")
    try:
        actual_size = archive.stat().st_size
        with archive.open("rb") as backup_file:
            magic = backup_file.read(5)
        actual_checksum = _sha256(archive)
    except OSError as exc:
        raise PostgresOperatorError("The backup archive could not be verified") from exc
    if magic != b"PGDMP":
        raise PostgresOperatorError("The backup archive is not custom-format")
    if actual_size != size_bytes or not hmac.compare_digest(actual_checksum, checksum):
        raise PostgresOperatorError("The backup checksum does not match its manifest")


def _run(
    command: list[str],
    *,
    environment: dict[str, str],
    runner: CommandRunner,
    capture_stdout: bool = False,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        kwargs = {
            "env": environment,
            "check": False,
            "shell": False,
            "stdout": subprocess.PIPE if capture_stdout else subprocess.DEVNULL,
            "stderr": subprocess.PIPE,
            "text": True,
        }
        if input_text is not None:
            kwargs["input"] = input_text
        return runner(command, **kwargs)
    except OSError as exc:
        raise PostgresOperatorError(
            "A required PostgreSQL operator command could not start"
        ) from exc


def _load_coupled_with_custody(manifest_path: str | Path) -> CoupledRecoverySet:
    manifest = Path(manifest_path)
    validate_private_operator_directory(
        manifest.parent,
        purpose="restore staging directory",
    )
    try:
        database, uploads, assets = coupled_recovery_artifact_paths(manifest)
    except UploadSnapshotError as exc:
        raise PostgresOperatorError("The coupled recovery manifest is invalid") from exc
    artifacts = (database, uploads, assets, manifest)
    before: list[os.stat_result] = []
    for artifact in artifacts:
        _require_private_custody(artifact)
        try:
            before.append(artifact.stat(follow_symlinks=False))
        except OSError as exc:
            raise PostgresOperatorError(
                "Backup input custody could not be verified"
            ) from exc
    try:
        recovery_set = load_coupled_recovery_set(manifest)
    except UploadSnapshotError as exc:
        raise PostgresOperatorError("The coupled recovery manifest is invalid") from exc
    if (
        recovery_set.database_archive,
        recovery_set.upload_archive,
        recovery_set.asset_inventory,
        recovery_set.manifest,
    ) != artifacts:
        raise PostgresOperatorError("The coupled recovery manifest is invalid")
    try:
        after = [artifact.stat(follow_symlinks=False) for artifact in artifacts]
    except OSError as exc:
        raise PostgresOperatorError("Backup input custody could not be verified") from exc
    if any(
        not os.path.samestat(before_fact, after_fact)
        for before_fact, after_fact in zip(before, after, strict=True)
    ):
        raise PostgresOperatorError("Backup input custody could not be verified")
    return recovery_set


def _read_restored_upload_registry(
    connection: PostgresConnection,
    target_database: str,
    *,
    runner: CommandRunner,
) -> tuple[AssetRecord, ...]:
    result = _run(
        _psql_command(UPLOAD_REGISTRY_INVENTORY_SQL),
        environment=build_pg_environment(connection, database=target_database),
        runner=runner,
        capture_stdout=True,
    )
    _require_success(result, "The restored upload asset registry could not be read")
    try:
        reader = csv.DictReader(io.StringIO(result.stdout or ""))
        if reader.fieldnames != [
            "asset_id",
            "storage_key",
            "state",
            "size_bytes",
            "sha256_digest",
        ]:
            raise ValueError
        rows = [
            {
                "asset_id": int(row["asset_id"]),
                "storage_key": row["storage_key"],
                "state": row["state"],
                "size_bytes": int(row["size_bytes"]),
                "sha256_digest": row["sha256_digest"],
            }
            for row in reader
        ]
        return registry_inventory(rows)
    except (KeyError, TypeError, ValueError, csv.Error, UploadSnapshotError) as exc:
        raise PostgresOperatorError(
            "The restored upload asset registry is invalid"
        ) from exc


def _psql_base_command() -> list[str]:
    return [
        postgres_executable("psql"),
        "--no-psqlrc",
        "--no-password",
        "--tuples-only",
        "--no-align",
        "--set=ON_ERROR_STOP=1",
    ]


def _psql_command(sql: str) -> list[str]:
    return [*_psql_base_command(), "--command", sql]


def _run_psql(
    sql: str,
    *,
    variables: Mapping[str, str],
    environment: dict[str, str],
    runner: CommandRunner,
    capture_stdout: bool = False,
) -> subprocess.CompletedProcess[str]:
    command = _psql_base_command()
    for name, value in sorted((variables or {}).items()):
        if not PSQL_VARIABLE_NAME.fullmatch(name):
            raise PostgresOperatorError("The psql variable name is invalid")
        command.append(f"--set={name}={value}")
    command.append("--file=-")
    return _run(
        command,
        environment=environment,
        runner=runner,
        capture_stdout=capture_stdout,
        input_text=sql,
    )


def _require_success(
    result: subprocess.CompletedProcess[str],
    operator_message: str,
) -> None:
    if result.returncode != 0:
        raise PostgresOperatorError(operator_message)


def _verify_operator_routine_contract(
    target_environment: Mapping[str, str],
    *,
    runner: CommandRunner,
) -> None:
    result = _run(
        _psql_command(OPERATOR_ROUTINE_CATALOG_SQL),
        environment=target_environment,
        runner=runner,
        capture_stdout=True,
    )
    _require_success(
        result,
        "Post-restore operator routine integrity checks failed",
    )
    serialized = (result.stdout or "").strip()
    if len(serialized.encode("utf-8")) > 64 * 1024:
        raise PostgresOperatorError(
            "Post-restore operator routine integrity checks failed"
        )
    try:
        records = json.loads(serialized)
        if not isinstance(records, list) or len(records) != 3:
            raise ValueError
        actual: dict[str, dict[str, object]] = {}
        expected_keys = {
            "signature",
            "source_hex",
            "language",
            "return_type",
            "volatility",
            "parallel_safety",
            "strict",
            "leakproof",
            "kind",
            "security_definer",
            "configuration",
            "argument_defaults",
            "owner",
        }
        for record in records:
            if not isinstance(record, dict) or set(record) != expected_keys:
                raise ValueError
            signature = record.pop("signature")
            source_hex = record.pop("source_hex")
            if (
                not isinstance(signature, str)
                or signature in actual
                or not isinstance(source_hex, str)
                or len(source_hex) % 2
                or re.fullmatch(r"[0-9a-f]*", source_hex) is None
            ):
                raise ValueError
            record["source"] = bytes.fromhex(source_hex).decode("utf-8")
            actual[signature] = record
    except (TypeError, ValueError, UnicodeError, json.JSONDecodeError):
        raise PostgresOperatorError(
            "Post-restore operator routine integrity checks failed"
        ) from None
    if actual != EXPECTED_OPERATOR_ROUTINE_CONTRACT:
        raise PostgresOperatorError(
            "Post-restore operator routine integrity checks failed"
        )


def check_alembic_schema_drift(
    connection: PostgresConnection,
    target_database: str,
) -> None:
    """Compare the target schema to model metadata without exposing DB details."""

    from alembic import command
    from alembic.config import Config

    backend_root = Path(__file__).resolve().parents[2] / "litblogs"
    query = {
        "connect_timeout": "10",
        "sslmode": connection.sslmode,
    }
    if connection.sslrootcert is not None:
        query["sslrootcert"] = connection.sslrootcert
    if connection.sslcert is not None:
        query["sslcert"] = connection.sslcert
    if connection.sslkey is not None:
        query["sslkey"] = connection.sslkey
    database_url = URL.create(
        "postgresql+psycopg2",
        username=connection.user,
        password=connection.password,
        host=connection.host,
        port=connection.port,
        database=target_database,
        query=query,
    )
    engine = create_engine(database_url, poolclass=NullPool)
    migration_output = io.StringIO()
    config = Config(stdout=migration_output, output_buffer=migration_output)
    config.set_main_option("script_location", str(backend_root / "migrations"))
    config.set_main_option("prepend_sys_path", str(backend_root))
    config.set_main_option("path_separator", "os")
    try:
        with engine.connect() as database_connection:
            config.attributes["connection"] = database_connection
            with redirect_stdout(migration_output), redirect_stderr(migration_output):
                command.check(config)
    except Exception:  # noqa: BLE001 - redact all Alembic/driver failures
        raise PostgresOperatorError(
            "The restored database failed the Alembic schema drift check"
        ) from None
    finally:
        engine.dispose()


def _verify_database_integrity(
    target: str,
    connection: PostgresConnection,
    *,
    runner: CommandRunner,
    require_current_head: bool,
    drift_checker: DriftChecker,
    expected_federated_identities: int | None = None,
) -> RestoreVerificationResult:
    target_environment = build_pg_environment(connection, database=target)
    schema_check = _run(
        _psql_command(SCHEMA_INTEGRITY_SQL),
        environment=target_environment,
        runner=runner,
        capture_stdout=True,
    )
    _require_success(schema_check, "Post-restore schema integrity checks failed")
    if (schema_check.stdout or "").strip() != "ok":
        raise PostgresOperatorError("Post-restore schema integrity checks failed")

    state_check = _run(
        _psql_command(MIGRATION_STATE_SQL),
        environment=target_environment,
        runner=runner,
        capture_stdout=True,
    )
    _require_success(state_check, "Post-restore migration state check failed")
    database_state = (state_check.stdout or "").strip()
    if database_state == "mixed":
        raise PostgresOperatorError(
            "Post-restore migration state is mixed or partially applied"
        )
    if database_state not in {"pre_alembic", "versioned"}:
        raise PostgresOperatorError(
            "Post-restore migration state could not be classified"
        )
    if database_state == "pre_alembic" and require_current_head:
        raise PostgresOperatorError(
            "The verification database is not at the current head"
        )

    revision: str | None = None
    if database_state == "versioned":
        revision_check = _run(
            _psql_command("SELECT version_num FROM alembic_version;"),
            environment=target_environment,
            runner=runner,
            capture_stdout=True,
        )
        _require_success(
            revision_check,
            "Post-restore migration ledger check failed",
        )
        revision = (revision_check.stdout or "").strip()
        if revision != EXPECTED_ALEMBIC_HEAD:
            raise PostgresOperatorError(
                "The verification database is not at the current head"
            )

    data_check = _run(
        _psql_command(CORE_DATA_INTEGRITY_SQL),
        environment=target_environment,
        runner=runner,
        capture_stdout=True,
    )
    _require_success(data_check, "Post-restore data integrity checks failed")
    if (data_check.stdout or "").strip() != "ok":
        raise PostgresOperatorError("Post-restore data integrity checks failed")

    identity_count: int | None = None
    if database_state == "versioned":
        identity_check = _run(
            _psql_command(IDENTITY_DATA_INTEGRITY_SQL),
            environment=target_environment,
            runner=runner,
            capture_stdout=True,
        )
        _require_success(
            identity_check,
            "Post-restore identity, ownership and ACL integrity checks failed",
        )
        identity_result = IDENTITY_RESULT.fullmatch(
            (identity_check.stdout or "").strip()
        )
        if identity_result is None:
            raise PostgresOperatorError(
                "Post-restore identity, ownership and ACL integrity checks failed"
            )
        identity_count = int(identity_result.group(1))
        if (
            expected_federated_identities is not None
            and identity_count != expected_federated_identities
        ):
            raise PostgresOperatorError(
                "Federated identity mappings do not match the approved inventory"
            )
        _verify_operator_routine_contract(
            target_environment,
            runner=runner,
        )
        try:
            drift_checker(connection, target)
        except Exception:  # noqa: BLE001 - redact injected/driver failures
            raise PostgresOperatorError(
                "The restored database failed the Alembic schema drift check"
            ) from None

    return RestoreVerificationResult(
        target_database=target,
        migration_state=(
            "pre_alembic" if database_state == "pre_alembic" else "current_head"
        ),
        alembic_revision=revision,
        federated_identity_count=identity_count,
    )


def restore_and_verify(
    archive_path: str | Path,
    manifest_path: str | Path,
    target_database: str,
    *,
    confirmation: str,
    database_url: str,
    runner: CommandRunner = subprocess.run,
    drift_checker: DriftChecker = check_alembic_schema_drift,
    tls_custody_validator=None,
) -> RestoreVerificationResult:
    """Restore to a newly created synthetic database and verify core integrity."""

    target = validate_restore_database_name(target_database)
    if not hmac.compare_digest(confirmation, target):
        raise PostgresOperatorError(
            "The restore confirmation must exactly match the target"
        )
    archive = Path(archive_path)
    manifest = Path(manifest_path)
    _load_and_verify_manifest(archive, manifest)
    connection = parse_postgres_url(database_url)
    (tls_custody_validator or validate_postgres_tls_custody)(connection)

    source_environment = build_pg_environment(connection)
    tool_environment = {
        key: value
        for key, value in source_environment.items()
        if not key.startswith("PG")
    }
    archive_check = _run(
        [postgres_executable("pg_restore"), "--list", str(archive)],
        environment=tool_environment,
        runner=runner,
    )
    _require_success(archive_check, "The backup archive failed structural validation")

    maintenance_environment = build_pg_environment(connection, database="postgres")
    existence = _run_psql(
        SYNTHETIC_TARGET_STATE_SQL,
        variables={"target_database": target},
        environment=maintenance_environment,
        runner=runner,
        capture_stdout=True,
    )
    _require_success(existence, "The verification database existence check failed")
    if (existence.stdout or "").strip() != "absent":
        target_state = (existence.stdout or "").strip()
        if target_state == "exists":
            raise PostgresOperatorError(
                "The verification database already exists; refusing restore"
            )
        if target_state == "restore-dba-invalid":
            raise PostgresOperatorError(
                "The isolated restore credential is not the approved privileged DBA"
            )
        if target_state == "isolated-roles-invalid":
            raise PostgresOperatorError(
                "The five isolated NOLOGIN application and migrator roles are not pre-provisioned"
            )
        raise PostgresOperatorError(
            "The verification database existence check was inconclusive"
        )

    creation = _run(
        [
            postgres_executable("createdb"),
            "--maintenance-db=postgres",
            "--no-password",
            "--encoding=UTF8",
            "--template=template0",
            target,
        ],
        environment=maintenance_environment,
        runner=runner,
    )
    _require_success(
        creation,
        "The verification database could not be created; no database was dropped",
    )

    access_lockdown = _run_psql(
        'REVOKE CONNECT, TEMPORARY ON DATABASE :"target_database" FROM PUBLIC;',
        variables={"target_database": target},
        environment=maintenance_environment,
        runner=runner,
    )
    _require_success(
        access_lockdown,
        "The verification database could not be isolated; it was retained and was not dropped",
    )

    # Recheck owner-only custody, manifest binding, and the full archive hash
    # immediately before pg_restore. The mode-0700 staging directory prevents
    # another identity from swapping a verified pathname between checks.
    _load_and_verify_manifest(archive, manifest)
    target_environment = build_pg_environment(connection, database=target)
    restoration = _run(
        [
            postgres_executable("pg_restore"),
            "--exit-on-error",
            "--single-transaction",
            "--no-password",
            "--dbname",
            target,
            str(archive),
        ],
        environment=target_environment,
        runner=runner,
    )
    _require_success(
        restoration,
        "Restore failed; the verification database was retained and was not dropped",
    )

    return _verify_database_integrity(
        target,
        connection,
        runner=runner,
        require_current_head=False,
        drift_checker=drift_checker,
    )


def restore_coupled_and_verify(
    manifest_path: str | Path,
    target_database: str,
    *,
    upload_target: str | Path,
    confirmation: str,
    database_url: str,
    runner: CommandRunner = subprocess.run,
    drift_checker: DriftChecker = check_alembic_schema_drift,
    tls_custody_validator=None,
) -> RestoreVerificationResult:
    """Restore a complete recovery set and compare DB/files to its inventory."""

    recovery_set = _load_coupled_with_custody(manifest_path)
    try:
        validated_upload_target = validate_synthetic_upload_restore_root(upload_target)
    except UploadSnapshotError as exc:
        raise PostgresOperatorError(str(exc)) from exc
    result = restore_and_verify(
        recovery_set.database_archive,
        recovery_set.manifest,
        target_database,
        confirmation=confirmation,
        database_url=database_url,
        runner=runner,
        drift_checker=drift_checker,
        tls_custody_validator=tls_custody_validator,
    )
    if result.migration_state != "current_head":
        raise PostgresOperatorError(
            "A coupled recovery set must contain the current registry schema"
        )
    try:
        extract_upload_archive(
            recovery_set.upload_archive,
            validated_upload_target,
            recovery_set.inventory,
        )
    except UploadSnapshotError as exc:
        raise PostgresOperatorError(str(exc)) from exc
    connection = parse_postgres_url(database_url)
    restored_inventory = _read_restored_upload_registry(
        connection,
        result.target_database,
        runner=runner,
    )
    if restored_inventory != recovery_set.inventory:
        raise PostgresOperatorError(
            "The restored upload asset registry does not match the recovery inventory"
        )
    try:
        verify_upload_tree(validated_upload_target, restored_inventory)
    except UploadSnapshotError as exc:
        raise PostgresOperatorError(str(exc)) from exc
    return result


def verify_existing_database(
    target_database: str,
    *,
    confirmation: str,
    expected_federated_identities: int,
    database_url: str,
    runner: CommandRunner = subprocess.run,
    drift_checker: DriftChecker = check_alembic_schema_drift,
    tls_custody_validator=None,
) -> RestoreVerificationResult:
    """Read only checks for a migrated synthetic verification database."""

    target = validate_restore_database_name(target_database)
    if not hmac.compare_digest(confirmation, target):
        raise PostgresOperatorError(
            "The verification confirmation must exactly match the target"
        )
    if (
        type(expected_federated_identities) is not int
        or expected_federated_identities < 0
    ):
        raise PostgresOperatorError(
            "The approved federated identity inventory count is invalid"
        )

    connection = parse_postgres_url(database_url)
    (tls_custody_validator or validate_postgres_tls_custody)(connection)
    maintenance_environment = build_pg_environment(connection, database="postgres")
    existence_sql = (
        "SELECT CASE WHEN EXISTS (SELECT 1 FROM pg_database WHERE datname = "
        ":'target_database') THEN 'exists' ELSE 'absent' END;"
    )
    existence = _run_psql(
        existence_sql,
        variables={"target_database": target},
        environment=maintenance_environment,
        runner=runner,
        capture_stdout=True,
    )
    _require_success(existence, "The verification database existence check failed")
    existence_status = (existence.stdout or "").strip()
    if existence_status != "exists":
        if existence_status == "absent":
            raise PostgresOperatorError(
                "The synthetic verification database does not exist"
            )
        raise PostgresOperatorError(
            "The verification database existence check was inconclusive"
        )

    return _verify_database_integrity(
        target,
        connection,
        runner=runner,
        require_current_head=True,
        drift_checker=drift_checker,
        expected_federated_identities=expected_federated_identities,
    )


def verify_existing_coupled_database(
    manifest_path: str | Path,
    target_database: str,
    *,
    upload_target: str | Path,
    confirmation: str,
    expected_federated_identities: int,
    database_url: str,
    runner: CommandRunner = subprocess.run,
    drift_checker: DriftChecker = check_alembic_schema_drift,
    tls_custody_validator=None,
) -> RestoreVerificationResult:
    """Reverify a migrated synthetic database and its restored upload tree."""

    recovery_set = _load_coupled_with_custody(manifest_path)
    try:
        restored_upload_root = validate_existing_synthetic_upload_root(upload_target)
        verify_upload_tree(restored_upload_root, recovery_set.inventory)
    except UploadSnapshotError as exc:
        raise PostgresOperatorError(str(exc)) from exc
    result = verify_existing_database(
        target_database,
        confirmation=confirmation,
        expected_federated_identities=expected_federated_identities,
        database_url=database_url,
        runner=runner,
        drift_checker=drift_checker,
        tls_custody_validator=tls_custody_validator,
    )
    connection = parse_postgres_url(database_url)
    restored_inventory = _read_restored_upload_registry(
        connection,
        result.target_database,
        runner=runner,
    )
    if restored_inventory != recovery_set.inventory:
        raise PostgresOperatorError(
            "The restored upload asset registry does not match the recovery inventory"
        )
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Restore one coupled LitBlogs recovery set into synthetic targets."
    )
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--upload-target", required=True)
    parser.add_argument("--target-database", required=True)
    parser.add_argument(
        "--confirm-target",
        required=True,
        help="Repeat the exact synthetic target database name.",
    )
    parser.add_argument(
        "--verify-existing",
        action="store_true",
        help="Run read-only post-migration checks against an existing synthetic database.",
    )
    parser.add_argument(
        "--expected-federated-identities",
        type=int,
        help="Approved inventory count; required only with --verify-existing.",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    runner: CommandRunner = subprocess.run,
    client_validator=None,
    drift_checker: DriftChecker = check_alembic_schema_drift,
    tls_custody_validator=None,
) -> int:
    args = _parser().parse_args(argv)
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print(
            "ERROR: DATABASE_URL is required in the operator environment",
            file=sys.stderr,
        )
        return 2
    if args.verify_existing:
        if args.expected_federated_identities is None:
            print(
                "ERROR: verify-existing requires the approved identity count",
                file=sys.stderr,
            )
            return 2
    elif args.expected_federated_identities is not None:
        print(
            "ERROR: expected identity count is only valid with verify-existing",
            file=sys.stderr,
        )
        return 2
    try:
        (client_validator or validate_postgres_client_installation)()
        if args.verify_existing:
            result = verify_existing_coupled_database(
                args.manifest,
                args.target_database,
                upload_target=args.upload_target,
                confirmation=args.confirm_target,
                expected_federated_identities=args.expected_federated_identities,
                database_url=database_url,
                runner=runner,
                drift_checker=drift_checker,
                tls_custody_validator=tls_custody_validator,
            )
        else:
            result = restore_coupled_and_verify(
                args.manifest,
                args.target_database,
                upload_target=args.upload_target,
                confirmation=args.confirm_target,
                database_url=database_url,
                runner=runner,
                drift_checker=drift_checker,
                tls_custody_validator=tls_custody_validator,
            )
    except PostgresOperatorError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if args.verify_existing:
        print("Existing synthetic database verification: current_head")
    else:
        print(f"Verified restore database: {result.target_database}")
        print(f"Migration state: {result.migration_state}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
