"""Add expiring, teacher-issued student verification codes without rewriting accounts.

Revision ID: f7a9d2c4e610
Revises: e6f8c2d1a904
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.sqlite_contract import table_contract_matches
from migrations.versions.a82f8f2b1d7c_email_verification import (
    OPERATOR_FUNCTIONS_SQL as PREVIOUS_OPERATOR_FUNCTIONS_SQL,
)
from migrations.versions.a82f8f2b1d7c_email_verification import _grant_operator_acl, _role_exists
from migrations.versions.f1ad78b2035f_exact_runtime_acl import _assert_acl_downgrade_membership

revision: str = "f7a9d2c4e610"
down_revision: str | Sequence[str] | None = "e6f8c2d1a904"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_ACTIONS = (
    "TEACHER_INVITATION_CREATED",
    "TEACHER_INVITATION_REVOKED",
    "ACCOUNT_DISABLED",
    "ACCOUNT_ENABLED",
    "ACCOUNT_DELETED",
    "ACCOUNT_RECOVERY_LINK_CREATED",
    "ACCOUNT_RECOVERY_EMAIL_QUEUED",
    "ACCOUNT_VERIFICATION_LINK_CREATED",
)
CODE_ACTIONS = (
    "STUDENT_VERIFICATION_CODE_CREATED",
    "STUDENT_VERIFICATION_CODE_CONSUMED",
)


OPERATOR_FUNCTIONS_SQL = r"""
CREATE OR REPLACE FUNCTION public.operator_set_account_status(
    p_email VARCHAR(100),
    p_disabled BOOLEAN,
    p_actor_identifier VARCHAR(100),
    p_resource_digest VARCHAR(64)
)
RETURNS VARCHAR(16)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $operator_set_account_status$
DECLARE
    v_user_id INTEGER;
    v_now TIMESTAMPTZ := transaction_timestamp();
    v_action VARCHAR(64);
BEGIN
    IF p_disabled IS NULL
       OR p_actor_identifier IS NULL
       OR p_actor_identifier !~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,99}$'
       OR p_resource_digest IS NULL
       OR p_resource_digest !~ '^[0-9a-f]{64}$'
       OR p_email IS NULL
       OR p_email = ''
       OR octet_length(p_email) <> char_length(p_email)
       OR p_email ~ '[[:cntrl:]]'
       OR p_email ~ '[[:space:]]'
       OR p_email COLLATE "C" <> translate(
            btrim(p_email),
            'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
            'abcdefghijklmnopqrstuvwxyz'
       ) COLLATE "C"
    THEN
        RAISE EXCEPTION 'invalid account status command' USING ERRCODE = '22023';
    END IF;

    SELECT users.id
    INTO v_user_id
    FROM public.users AS users
    WHERE users.email COLLATE "C" = p_email COLLATE "C"
    FOR UPDATE;

    v_action := CASE
        WHEN p_disabled THEN 'ACCOUNT_DISABLED'
        ELSE 'ACCOUNT_ENABLED'
    END;
    IF NOT FOUND THEN
        INSERT INTO public.operator_audit_events (
            actor_identifier, action, outcome, resource_digest
        ) VALUES (
            p_actor_identifier, v_action, 'NOT_FOUND', p_resource_digest
        );
        RETURN 'NOT_FOUND';
    END IF;

    UPDATE public.users
    SET disabled_at = CASE WHEN p_disabled THEN v_now ELSE NULL END
    WHERE id = v_user_id;

    IF p_disabled THEN
        UPDATE public.browser_sessions
        SET revoked_at = v_now
        WHERE user_id = v_user_id
          AND revoked_at IS NULL
          AND expires_at > v_now;

        UPDATE public.password_resets
        SET token = NULL,
            expires_at = NULL,
            used = TRUE,
            delivery_status = 'FAILED',
            delivery_attempted_at = v_now,
            delivery_claim_digest = NULL
        WHERE user_id = v_user_id;

        UPDATE public.email_verifications
        SET token_digest = NULL,
            expires_at = NULL,
            delivery_status = 'FAILED',
            delivery_attempted_at = v_now,
            delivery_claim_digest = NULL
        WHERE user_id = v_user_id;

        UPDATE public.student_verification_codes
        SET code_digest = NULL
        WHERE student_id = v_user_id OR issuer_id = v_user_id;
    END IF;

    INSERT INTO public.operator_audit_events (
        actor_identifier, action, outcome, resource_digest
    ) VALUES (
        p_actor_identifier, v_action, 'SUCCEEDED', p_resource_digest
    );
    RETURN 'SUCCEEDED';
END
$operator_set_account_status$;
"""

def _replace_audit_actions(actions: tuple[str, ...]) -> None:
    condition = "action IN (" + ", ".join(f"'{action}'" for action in actions) + ")"
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("operator_audit_events", recreate="always") as batch:
            batch.drop_constraint("ck_operator_audit_action", type_="check")
            batch.create_check_constraint("ck_operator_audit_action", condition)
        return
    op.drop_constraint(
        "ck_operator_audit_action", "operator_audit_events", schema="public", type_="check",
    )
    op.create_check_constraint(
        "ck_operator_audit_action", "operator_audit_events", condition, schema="public",
    )


def _sqlite_schema_already_current() -> bool:
    inspector = sa.inspect(op.get_bind())
    if "student_verification_codes" not in inspector.get_table_names():
        return False
    if not table_contract_matches(
        inspector,
        "student_verification_codes",
        columns={
            "id": ("INTEGER", False, None, True),
            "student_id": ("INTEGER", False, None, False),
            "issuer_id": ("INTEGER", True, None, False),
            "code_digest": ("VARCHAR(64)", True, None, False),
            "created_at": ("DATETIME", False, "CURRENT_TIMESTAMP", False),
            "expires_at": ("DATETIME", False, None, False),
            "attempts": ("INTEGER", False, "0", False),
            "consumed_at": ("DATETIME", True, None, False),
        },
        indexes={
            "ix_student_verification_codes_id": (("id",), False, None),
            "ix_student_verification_codes_student_id": (("student_id",), True, None),
        },
        unique_constraints=(),
        check_constraints={
            "ck_student_verification_code_attempts": "attempts >= 0 AND attempts <= 5",
            "ck_student_verification_code_digest_length": (
                "code_digest IS NULL OR length(code_digest) = 64"
            ),
        },
        foreign_keys=(
            ("fk_student_verification_code_student", ("student_id",), "users", ("id",), "CASCADE"),
            ("fk_student_verification_code_issuer", ("issuer_id",), "users", ("id",), "SET NULL"),
        ),
        exact_columns=True,
        exact_indexes=True,
        exact_unique_constraints=True,
        exact_check_constraints=True,
        exact_foreign_keys=True,
    ):
        raise RuntimeError("partial SQLite schema for f7a9d2c4e610; repair it before retrying")
    return True


def _create_table() -> None:
    constraints = [
        sa.CheckConstraint(
            "attempts >= 0 AND attempts <= 5", name="ck_student_verification_code_attempts",
        ),
        sa.CheckConstraint(
            "code_digest IS NULL OR length(code_digest) = 64",
            name="ck_student_verification_code_digest_length",
        ),
        sa.ForeignKeyConstraint(
            ["student_id"], ["users.id"], ondelete="CASCADE",
            name="fk_student_verification_code_student",
        ),
        sa.ForeignKeyConstraint(
            ["issuer_id"], ["users.id"], ondelete="SET NULL",
            name="fk_student_verification_code_issuer",
        ),
    ]
    if op.get_bind().dialect.name == "postgresql":
        constraints.append(sa.CheckConstraint(
            "code_digest IS NULL OR code_digest ~ '^[0-9a-f]{64}$'",
            name="ck_student_verification_code_digest_lower_hex",
        ))
    op.create_table(
        "student_verification_codes",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("issuer_id", sa.Integer(), nullable=True),
        sa.Column("code_digest", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        *constraints,
    )
    op.create_index("ix_student_verification_codes_id", "student_verification_codes", ["id"])
    op.create_index(
        "ix_student_verification_codes_student_id", "student_verification_codes", ["student_id"], unique=True,
    )


def _grant_runtime_acl() -> None:
    op.execute(sa.text(
        "ALTER TABLE public.student_verification_codes OWNER TO litblogs_migrator"
    ))
    op.execute(sa.text(
        "ALTER SEQUENCE public.student_verification_codes_id_seq OWNER TO litblogs_migrator"
    ))
    roles = op.get_bind().execute(sa.text(
        "SELECT rolname FROM pg_catalog.pg_roles WHERE rolname IN "
        "('litblogs_runtime', 'litblog_identity_owner', 'litblog_account_operator', "
        "'litblog_invitation_operator')"
    )).scalars().all()
    for role_name in ["PUBLIC", *roles]:
        op.execute(sa.text(
            "REVOKE ALL PRIVILEGES ON TABLE public.student_verification_codes "
            f"FROM {role_name}"
        ))
        op.execute(sa.text(
            "REVOKE ALL PRIVILEGES ON SEQUENCE public.student_verification_codes_id_seq "
            f"FROM {role_name}"
        ))
    if "litblogs_runtime" in roles:
        op.execute(sa.text(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.student_verification_codes TO litblogs_runtime"
        ))
        op.execute(sa.text(
            "GRANT USAGE, SELECT ON SEQUENCE public.student_verification_codes_id_seq TO litblogs_runtime"
        ))


def upgrade() -> None:
    if op.get_bind().dialect.name != "sqlite" or not _sqlite_schema_already_current():
        _create_table()
    _replace_audit_actions(OLD_ACTIONS + CODE_ACTIONS)
    if op.get_bind().dialect.name == "postgresql":
        _grant_runtime_acl()
        if _role_exists("litblog_identity_owner"):
            op.execute(sa.text(
                "GRANT SELECT (student_id, issuer_id), UPDATE (code_digest) "
                "ON TABLE public.student_verification_codes TO litblog_identity_owner"
            ))
        op.execute(sa.text(OPERATOR_FUNCTIONS_SQL))
        _grant_operator_acl()


def downgrade() -> None:
    present = op.get_bind().execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM student_verification_codes) OR EXISTS "
        "(SELECT 1 FROM operator_audit_events WHERE action IN "
        "('STUDENT_VERIFICATION_CODE_CREATED', 'STUDENT_VERIFICATION_CODE_CONSUMED'))"
    )).scalar_one()
    if present:
        raise RuntimeError("Cannot downgrade while student verification codes or their audit events exist")
    if op.get_bind().dialect.name == "postgresql":
        if _role_exists("litblog_identity_owner"):
            _assert_acl_downgrade_membership()
        op.execute(sa.text(PREVIOUS_OPERATOR_FUNCTIONS_SQL))
        _grant_operator_acl()
    _replace_audit_actions(OLD_ACTIONS)
    op.drop_table("student_verification_codes")
