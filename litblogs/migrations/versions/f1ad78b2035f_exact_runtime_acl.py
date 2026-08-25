"""establish the exact PostgreSQL runtime and operator ACL

Revision ID: f1ad78b2035f
Revises: b983b7aebe7b
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f1ad78b2035f"
down_revision: str | Sequence[str] | None = "b983b7aebe7b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RUNTIME_ROLE = "litblogs_runtime"
IDENTITY_OWNER_ROLE = "litblog_identity_owner"
ACCOUNT_OPERATOR_ROLE = "litblog_account_operator"
INVITATION_OPERATOR_ROLE = "litblog_invitation_operator"
MIGRATOR_ROLE = "litblogs_migrator"

# Deployment creates these roles before Alembic. The migration deliberately does
# not require CREATEROLE, and the release gate compares the catalog to this exact
# contract before accepting the conditional grants below.
REQUIRED_ROLE_ATTRIBUTES = {
    RUNTIME_ROLE: ("LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"),
    IDENTITY_OWNER_ROLE: ("NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"),
    ACCOUNT_OPERATOR_ROLE: ("LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"),
    INVITATION_OPERATOR_ROLE: ("LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"),
}
# Exact temporary direction and options:
# GRANT litblog_identity_owner TO litblogs_migrator
# WITH ADMIN FALSE, INHERIT TRUE, SET TRUE.
# It exists only across a reviewed upgrade or downgrade ownership handoff and is
# revoked immediately after that one migration command.
TEMPORARY_IDENTITY_OWNER_MEMBERSHIP = (
    MIGRATOR_ROLE,
    IDENTITY_OWNER_ROLE,
)

RUNTIME_CRUD_TABLES = (
    "assignment_drafts",
    "assignment_reminder_notifications",
    "assignment_submission_replies",
    "assignment_submissions",
    "assignments",
    "blogs",
    "browser_sessions",
    "class_enrollments",
    "classes",
    "comment_likes",
    "comments",
    "federated_identities",
    "password_resets",
    "post_likes",
    "push_subscriptions",
    "saved_posts",
    "teachers",
    "upload_assets",
    "user_settings",
    "users",
)
RUNTIME_SEQUENCE_TABLES = (
    "assignment_drafts",
    "assignment_reminder_notifications",
    "assignment_submission_replies",
    "assignment_submissions",
    "assignments",
    "blogs",
    "browser_sessions",
    "class_enrollments",
    "classes",
    "comment_likes",
    "comments",
    "federated_identities",
    "operator_audit_events",
    "password_resets",
    "post_likes",
    "push_subscriptions",
    "saved_posts",
    "teachers",
    "upload_assets",
    "user_settings",
    "users",
)

ACCOUNT_FUNCTION = "public.operator_set_account_status(VARCHAR, BOOLEAN, VARCHAR, VARCHAR)"
INVITATION_FUNCTIONS = (
    "public.operator_create_teacher_invitation(VARCHAR, VARCHAR, TIMESTAMPTZ, VARCHAR, VARCHAR)",
    "public.operator_revoke_teacher_invitation(VARCHAR, VARCHAR, VARCHAR)",
)
REVIEWED_FUNCTIONS = (ACCOUNT_FUNCTION, *INVITATION_FUNCTIONS)


def _role_exists(role_name: str) -> bool:
    return bool(
        op.get_bind()
        .execute(
            sa.text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :name)"),
            {"name": role_name},
        )
        .scalar_one()
    )


def _revoke_direct_object_access(role_name: str) -> None:
    op.execute(sa.text(f"REVOKE ALL PRIVILEGES ON SCHEMA public FROM {role_name}"))
    op.execute(sa.text(f"REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM {role_name}"))
    op.execute(sa.text(f"REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM {role_name}"))
    op.execute(sa.text(f"REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public FROM {role_name}"))


def _grant_runtime_acl() -> None:
    _revoke_direct_object_access(RUNTIME_ROLE)
    op.execute(sa.text(f"GRANT USAGE ON SCHEMA public TO {RUNTIME_ROLE}"))
    for table_name in RUNTIME_CRUD_TABLES:
        op.execute(sa.text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.{table_name} TO {RUNTIME_ROLE}"))
    op.execute(
        sa.text(
            "GRANT SELECT (id, token_digest, email_digest, expires_at, "
            "consumed_at, revoked_at), UPDATE (consumed_at, revoked_at) "
            f"ON TABLE public.teacher_invitations TO {RUNTIME_ROLE}"
        )
    )
    op.execute(
        sa.text(
            "GRANT INSERT (actor_identifier, action, outcome, resource_digest) "
            f"ON TABLE public.operator_audit_events TO {RUNTIME_ROLE}"
        )
    )
    op.execute(sa.text(f"GRANT SELECT ON TABLE public.alembic_version TO {RUNTIME_ROLE}"))
    for table_name in RUNTIME_SEQUENCE_TABLES:
        op.execute(sa.text(f"GRANT USAGE, SELECT ON SEQUENCE public.{table_name}_id_seq TO {RUNTIME_ROLE}"))


def _grant_identity_acl() -> None:
    _revoke_direct_object_access(IDENTITY_OWNER_ROLE)
    op.execute(sa.text(f"GRANT USAGE ON SCHEMA public TO {IDENTITY_OWNER_ROLE}"))
    op.execute(
        sa.text(f"GRANT SELECT (id, email), UPDATE (disabled_at) ON TABLE public.users TO {IDENTITY_OWNER_ROLE}")
    )
    op.execute(
        sa.text(
            "GRANT SELECT (user_id, revoked_at, expires_at), UPDATE (revoked_at) "
            f"ON TABLE public.browser_sessions TO {IDENTITY_OWNER_ROLE}"
        )
    )
    op.execute(
        sa.text(
            "GRANT SELECT (user_id), UPDATE (token, expires_at, used, "
            "delivery_status, delivery_attempted_at, delivery_claim_digest) "
            f"ON TABLE public.password_resets TO {IDENTITY_OWNER_ROLE}"
        )
    )
    op.execute(
        sa.text(
            "GRANT SELECT (email_digest, consumed_at, revoked_at, expires_at), "
            "INSERT (token_digest, email_digest, expires_at, created_by), "
            "UPDATE (revoked_at) ON TABLE public.teacher_invitations "
            f"TO {IDENTITY_OWNER_ROLE}"
        )
    )
    op.execute(
        sa.text(
            "GRANT INSERT (actor_identifier, action, outcome, resource_digest) "
            f"ON TABLE public.operator_audit_events TO {IDENTITY_OWNER_ROLE}"
        )
    )
    op.execute(
        sa.text(
            "GRANT USAGE ON SEQUENCE public.teacher_invitations_id_seq, "
            "public.operator_audit_events_id_seq "
            f"TO {IDENTITY_OWNER_ROLE}"
        )
    )


def _grant_operator_acl() -> None:
    account_exists = _role_exists(ACCOUNT_OPERATOR_ROLE)
    invitation_exists = _role_exists(INVITATION_OPERATOR_ROLE)
    if account_exists:
        _revoke_direct_object_access(ACCOUNT_OPERATOR_ROLE)
        op.execute(sa.text(f"GRANT USAGE ON SCHEMA public TO {ACCOUNT_OPERATOR_ROLE}"))
        op.execute(sa.text(f"GRANT EXECUTE ON FUNCTION {ACCOUNT_FUNCTION} TO {ACCOUNT_OPERATOR_ROLE}"))
    if invitation_exists:
        _revoke_direct_object_access(INVITATION_OPERATOR_ROLE)
        op.execute(sa.text(f"GRANT USAGE ON SCHEMA public TO {INVITATION_OPERATOR_ROLE}"))
        for function_signature in INVITATION_FUNCTIONS:
            op.execute(sa.text(f"GRANT EXECUTE ON FUNCTION {function_signature} TO {INVITATION_OPERATOR_ROLE}"))


def _transfer_function_ownership() -> None:
    op.execute(sa.text(f"GRANT CREATE ON SCHEMA public TO {IDENTITY_OWNER_ROLE}"))
    for function_signature in REVIEWED_FUNCTIONS:
        op.execute(sa.text(f"ALTER FUNCTION {function_signature} OWNER TO {IDENTITY_OWNER_ROLE}"))
    op.execute(sa.text(f"REVOKE CREATE ON SCHEMA public FROM {IDENTITY_OWNER_ROLE}"))


def _assert_password_reset_downgrade_is_safe() -> None:
    invalidated = op.get_bind().execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM password_resets "
            "WHERE token IS NULL OR expires_at IS NULL)"
        )
    ).scalar_one()
    if invalidated:
        raise RuntimeError(
            "password reset secrets were irreversibly invalidated; retire those rows before a reviewed downgrade"
        )


def _owned_object_dependencies(bind, role_name: str) -> set[tuple[int, int, int, int]]:
    return {
        tuple(int(value) for value in row)
        for row in bind.execute(
            sa.text(
                "SELECT dependency.dbid, dependency.classid, "
                "dependency.objid, dependency.objsubid "
                "FROM pg_catalog.pg_shdepend AS dependency "
                "JOIN pg_catalog.pg_roles AS owner "
                "ON owner.oid = dependency.refobjid "
                "WHERE dependency.refclassid = "
                "'pg_catalog.pg_authid'::pg_catalog.regclass "
                "AND dependency.deptype = 'o' "
                "AND owner.rolname = :role_name"
            ),
            {"role_name": role_name},
        )
    }


def _expected_identity_function_dependencies(bind) -> set[tuple[int, int, int, int]]:
    database_oid = int(
        bind.execute(
            sa.text(
                "SELECT oid FROM pg_catalog.pg_database "
                "WHERE datname = pg_catalog.current_database()"
            )
        ).scalar_one()
    )
    procedure_class_oid = int(
        bind.execute(
            sa.text(
                "SELECT 'pg_catalog.pg_proc'::pg_catalog.regclass::pg_catalog.oid"
            )
        ).scalar_one()
    )
    expected: set[tuple[int, int, int, int]] = set()
    for function_signature in REVIEWED_FUNCTIONS:
        routine_oid = bind.execute(
            sa.text(
                "SELECT pg_catalog.to_regprocedure(:signature)::pg_catalog.oid"
            ),
            {"signature": function_signature},
        ).scalar_one()
        if routine_oid is None:
            raise RuntimeError("ACL downgrade ownership boundary mismatch")
        expected.add((database_oid, procedure_class_oid, int(routine_oid), 0))
    return expected


def _assert_acl_downgrade_ownership() -> set[int]:
    bind = op.get_bind()
    expected_dependencies = _expected_identity_function_dependencies(bind)
    if _owned_object_dependencies(bind, IDENTITY_OWNER_ROLE) != expected_dependencies:
        raise RuntimeError("ACL downgrade ownership boundary mismatch")
    return {dependency[2] for dependency in expected_dependencies}


def _assert_acl_downgrade_membership() -> None:
    membership_options = op.get_bind().execute(
        sa.text(
            "SELECT membership.admin_option, membership.inherit_option, "
            "membership.set_option "
            "FROM pg_catalog.pg_auth_members AS membership "
            "JOIN pg_catalog.pg_roles AS granted_role "
            "ON granted_role.oid = membership.roleid "
            "JOIN pg_catalog.pg_roles AS member_role "
            "ON member_role.oid = membership.member "
            "WHERE granted_role.rolname = :owner_role "
            "AND member_role.rolname = :migrator_role "
            "AND member_role.rolname = CURRENT_USER"
        ),
        {
            "owner_role": IDENTITY_OWNER_ROLE,
            "migrator_role": MIGRATOR_ROLE,
        },
    ).one_or_none()
    if membership_options is None or tuple(membership_options) != (False, True, True):
        raise RuntimeError(
            "ACL downgrade requires exact temporary membership: "
            "GRANT litblog_identity_owner TO litblogs_migrator "
            "WITH ADMIN FALSE, INHERIT TRUE, SET TRUE"
        )


def _assert_acl_downgrade_ownership_transferred(routine_oids: set[int]) -> None:
    bind = op.get_bind()
    if _owned_object_dependencies(bind, IDENTITY_OWNER_ROLE):
        raise RuntimeError("ACL downgrade ownership transfer failed")
    for routine_oid in routine_oids:
        owner_name = bind.execute(
            sa.text(
                "SELECT owner.rolname FROM pg_catalog.pg_proc AS routine "
                "JOIN pg_catalog.pg_roles AS owner ON owner.oid = routine.proowner "
                "WHERE routine.oid = :routine_oid"
            ),
            {"routine_oid": routine_oid},
        ).scalar_one_or_none()
        if owner_name != MIGRATOR_ROLE:
            raise RuntimeError("ACL downgrade ownership transfer failed")


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    if not _role_exists(MIGRATOR_ROLE):
        raise RuntimeError(
            "litblogs_migrator must exist before applying the exact default function ACL"
        )

    op.execute(sa.text("REVOKE ALL ON SCHEMA public FROM PUBLIC"))
    op.execute(sa.text("REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM PUBLIC"))
    op.execute(sa.text("REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC"))
    op.execute(sa.text("REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC"))
    op.execute(
        sa.text(
            "ALTER DEFAULT PRIVILEGES FOR ROLE litblogs_migrator "
            "REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC"
        )
    )

    if _role_exists(RUNTIME_ROLE):
        _grant_runtime_acl()
    if _role_exists(IDENTITY_OWNER_ROLE):
        _grant_identity_acl()
    _grant_operator_acl()
    if _role_exists(IDENTITY_OWNER_ROLE):
        _transfer_function_ownership()


def downgrade() -> None:
    _assert_password_reset_downgrade_is_safe()
    if op.get_bind().dialect.name != "postgresql":
        return

    if _role_exists(IDENTITY_OWNER_ROLE):
        routine_oids = _assert_acl_downgrade_ownership()
        _assert_acl_downgrade_membership()
        for function_signature in REVIEWED_FUNCTIONS:
            op.execute(sa.text(f"ALTER FUNCTION {function_signature} OWNER TO CURRENT_USER"))
        _assert_acl_downgrade_ownership_transferred(routine_oids)
        _revoke_direct_object_access(IDENTITY_OWNER_ROLE)
    for role_name in (
        ACCOUNT_OPERATOR_ROLE,
        INVITATION_OPERATOR_ROLE,
        RUNTIME_ROLE,
    ):
        if _role_exists(role_name):
            _revoke_direct_object_access(role_name)
