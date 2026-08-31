"""add email verification persistence and exact privileges

Revision ID: a82f8f2b1d7c
Revises: f1ad78b2035f
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.sqlite_contract import (
    has_any_named_schema_object,
    table_contract_matches,
)

revision: str = "a82f8f2b1d7c"
down_revision: str | Sequence[str] | None = "f1ad78b2035f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RUNTIME_ROLE = "litblogs_runtime"
IDENTITY_OWNER_ROLE = "litblog_identity_owner"
ACCOUNT_OPERATOR_ROLE = "litblog_account_operator"
INVITATION_OPERATOR_ROLE = "litblog_invitation_operator"
MIGRATOR_ROLE = "litblogs_migrator"
ACCOUNT_FUNCTION = (
    "public.operator_set_account_status(VARCHAR, BOOLEAN, VARCHAR, VARCHAR)"
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


PREVIOUS_OPERATOR_SET_ACCOUNT_STATUS_SQL = r"""
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


def _is_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _role_exists(role_name: str) -> bool:
    return bool(
        op.get_bind()
        .execute(
            sa.text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :name)"),
            {"name": role_name},
        )
        .scalar_one()
    )


def _postgresql_check(expression: str, name: str) -> sa.CheckConstraint | None:
    if not _is_postgresql():
        return None
    return sa.CheckConstraint(expression, name=name)


def _sqlite_schema_already_current() -> bool:
    if op.get_bind().dialect.name != "sqlite":
        return False
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    has_marker = "email_verifications" in tables or has_any_named_schema_object(
        inspector,
        "users",
        columns=("email_verified_at",),
    )
    if not has_marker:
        return False

    is_current = all(
        (
            table_contract_matches(
                inspector,
                "users",
                columns={
                    "email_verified_at": ("DATETIME", True, None, False),
                },
            ),
            table_contract_matches(
                inspector,
                "email_verifications",
                columns={
                    "id": ("INTEGER", False, None, True),
                    "user_id": ("INTEGER", False, None, False),
                    "token_digest": ("VARCHAR(64)", True, None, False),
                    "created_at": (
                        "DATETIME",
                        False,
                        "CURRENT_TIMESTAMP",
                        False,
                    ),
                    "expires_at": ("DATETIME", True, None, False),
                    "delivery_status": ("VARCHAR(16)", False, None, False),
                    "delivery_attempted_at": ("DATETIME", True, None, False),
                    "delivery_claim_digest": ("VARCHAR(64)", True, None, False),
                },
                indexes={
                    "ix_email_verifications_delivery_status": (
                        ("delivery_status",),
                        False,
                        None,
                    ),
                    "ix_email_verifications_id": (("id",), False, None),
                    "ix_email_verifications_token_digest": (
                        ("token_digest",),
                        True,
                        None,
                    ),
                    "ix_email_verifications_user_id": (
                        ("user_id",),
                        True,
                        None,
                    ),
                },
                unique_constraints=(),
                check_constraints={
                    "ck_email_verification_delivery_claim_digest": (
                        "delivery_claim_digest IS NULL OR "
                        "length(delivery_claim_digest) = 64"
                    ),
                    "ck_email_verification_delivery_status": (
                        "delivery_status IN ('PENDING', 'PROCESSING', "
                        "'DELIVERED', 'FAILED')"
                    ),
                },
                foreign_keys=(
                    (
                        "fk_email_verifications_user_id_users",
                        ("user_id",),
                        "users",
                        ("id",),
                        "CASCADE",
                    ),
                ),
                exact_columns=True,
                exact_indexes=True,
                exact_unique_constraints=True,
                exact_check_constraints=True,
                exact_foreign_keys=True,
            ),
        )
    )
    if not is_current:
        raise RuntimeError(
            "partial SQLite schema detected for email verification; repair before retrying"
        )
    return True


def _backfill_existing_users() -> None:
    op.execute(
        sa.text(
            "UPDATE users SET email_verified_at = CURRENT_TIMESTAMP "
            "WHERE email_verified_at IS NULL"
        )
    )


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


def _revoke_email_verification_object_access(role_name: str) -> None:
    op.execute(
        sa.text(
            "REVOKE ALL PRIVILEGES ON TABLE public.email_verifications "
            f"FROM {role_name}"
        )
    )
    op.execute(
        sa.text(
            "REVOKE ALL PRIVILEGES ON SEQUENCE public.email_verifications_id_seq "
            f"FROM {role_name}"
        )
    )


def _grant_runtime_acl() -> None:
    _revoke_email_verification_object_access(RUNTIME_ROLE)
    op.execute(
        sa.text(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.email_verifications TO litblogs_runtime"
        )
    )
    op.execute(
        sa.text(
            "GRANT USAGE, SELECT ON SEQUENCE public.email_verifications_id_seq TO litblogs_runtime"
        )
    )


def _grant_identity_acl() -> None:
    _revoke_email_verification_object_access(IDENTITY_OWNER_ROLE)
    op.execute(
        sa.text(
            "GRANT SELECT (user_id), UPDATE (token_digest, expires_at, delivery_status, delivery_attempted_at, delivery_claim_digest) ON TABLE public.email_verifications TO litblog_identity_owner"
        )
    )


def _grant_operator_acl() -> None:
    op.execute(
        sa.text(
            """REVOKE ALL ON FUNCTION public.operator_set_account_status(
            VARCHAR, BOOLEAN, VARCHAR, VARCHAR ) FROM PUBLIC"""
        )
    )
    for role_name in (
        RUNTIME_ROLE,
        ACCOUNT_OPERATOR_ROLE,
        INVITATION_OPERATOR_ROLE,
    ):
        if _role_exists(role_name):
            op.execute(
                sa.text(
                    f"REVOKE ALL PRIVILEGES ON FUNCTION {ACCOUNT_FUNCTION} "
                    f"FROM {role_name}"
                )
            )
    if _role_exists(ACCOUNT_OPERATOR_ROLE):
        op.execute(
            sa.text(
                """GRANT EXECUTE ON FUNCTION public.operator_set_account_status(
                VARCHAR, BOOLEAN, VARCHAR, VARCHAR ) TO litblog_account_operator"""
            )
        )


def _create_email_verification_table() -> None:
    constraints: list[sa.Constraint] = [
        sa.CheckConstraint(
            "delivery_status IN ('PENDING', 'PROCESSING', 'DELIVERED', 'FAILED')",
            name="ck_email_verification_delivery_status",
        ),
        sa.CheckConstraint(
            "delivery_claim_digest IS NULL OR length(delivery_claim_digest) = 64",
            name="ck_email_verification_delivery_claim_digest",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
            name="fk_email_verifications_user_id_users",
        ),
    ]
    for constraint in (
        _postgresql_check(
            "delivery_claim_digest IS NULL OR "
            "delivery_claim_digest ~ '^[0-9a-f]{64}$'",
            "ck_email_verification_delivery_claim_digest_lower_hex",
        ),
        _postgresql_check(
            "token_digest IS NULL OR token_digest ~ '^[0-9a-f]{64}$'",
            "ck_email_verification_token_digest_lower_hex",
        ),
    ):
        if constraint is not None:
            constraints.append(constraint)

    op.create_table(
        "email_verifications",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_digest", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivery_status", sa.String(length=16), nullable=False),
        sa.Column(
            "delivery_attempted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("delivery_claim_digest", sa.String(length=64), nullable=True),
        *constraints,
    )
    op.create_index(
        "ix_email_verifications_id",
        "email_verifications",
        ["id"],
        unique=False,
    )
    op.create_index(
        "ix_email_verifications_user_id",
        "email_verifications",
        ["user_id"],
        unique=True,
    )
    op.create_index(
        "ix_email_verifications_token_digest",
        "email_verifications",
        ["token_digest"],
        unique=True,
    )
    op.create_index(
        "ix_email_verifications_delivery_status",
        "email_verifications",
        ["delivery_status"],
        unique=False,
    )


def upgrade() -> None:
    if _sqlite_schema_already_current():
        _backfill_existing_users()
        return

    op.add_column(
        "users",
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    _backfill_existing_users()
    _create_email_verification_table()

    if not _is_postgresql():
        return

    op.execute(
        sa.text(
            "ALTER TABLE public.email_verifications OWNER TO litblogs_migrator"
        )
    )
    op.execute(
        sa.text(
            "ALTER SEQUENCE public.email_verifications_id_seq "
            "OWNER TO litblogs_migrator"
        )
    )
    _revoke_email_verification_object_access("PUBLIC")
    for role_name in (ACCOUNT_OPERATOR_ROLE, INVITATION_OPERATOR_ROLE):
        if _role_exists(role_name):
            _revoke_email_verification_object_access(role_name)
    if _role_exists(RUNTIME_ROLE):
        _grant_runtime_acl()
    if _role_exists(IDENTITY_OWNER_ROLE):
        _grant_identity_acl()

    op.execute(sa.text(OPERATOR_FUNCTIONS_SQL))
    _grant_operator_acl()


def downgrade() -> None:
    _assert_password_reset_downgrade_is_safe()
    if _is_postgresql():
        op.execute(sa.text(PREVIOUS_OPERATOR_SET_ACCOUNT_STATUS_SQL))
        _grant_operator_acl()

    op.drop_index(
        "ix_email_verifications_delivery_status",
        table_name="email_verifications",
    )
    op.drop_index(
        "ix_email_verifications_token_digest",
        table_name="email_verifications",
    )
    op.drop_index(
        "ix_email_verifications_user_id",
        table_name="email_verifications",
    )
    op.drop_index("ix_email_verifications_id", table_name="email_verifications")
    op.drop_table("email_verifications")
    op.drop_column("users", "email_verified_at")
