"""add revocable sessions, invitation controls, and mediated operator routines

Revision ID: c5136f36e302
Revises: d4e4539c0418
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.sqlite_contract import (
    has_any_named_schema_object,
    table_contract_matches,
)

revision: str = "c5136f36e302"
down_revision: str | Sequence[str] | None = "d4e4539c0418"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


EMAIL_PREFLIGHT_SQL = r"""
DO $identity_preflight$
BEGIN
    IF EXISTS (
        SELECT 1 FROM public.users
        WHERE octet_length(email) <> char_length(email)
           OR email ~ '[[:cntrl:]]'
           OR btrim(email) = ''
           OR btrim(email) ~ '[[:space:]]'
    ) THEN
        RAISE EXCEPTION 'users.email requires reviewed reconciliation';
    END IF;
    IF EXISTS (
        SELECT 1 FROM public.users
        GROUP BY translate(
            btrim(email),
            'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
            'abcdefghijklmnopqrstuvwxyz'
        ) COLLATE "C"
        HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION 'users.email contains canonical duplicates';
    END IF;
    IF EXISTS (
        SELECT 1 FROM public.teachers
        WHERE email IS NULL
           OR octet_length(email) <> char_length(email)
           OR email ~ '[[:cntrl:]]'
           OR char_length(btrim(email)) > 100
           OR btrim(email) = ''
           OR btrim(email) ~ '[[:space:]]'
    ) THEN
        RAISE EXCEPTION 'teachers.email requires reviewed reconciliation';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM public.teachers AS teacher
        LEFT JOIN public.users AS account ON account.id = teacher.user_id
        WHERE teacher.user_id IS NOT NULL
          AND (
              account.id IS NULL
              OR account.role::text <> 'TEACHER'
              OR translate(
                    btrim(teacher.email),
                    'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
                    'abcdefghijklmnopqrstuvwxyz'
                 ) COLLATE "C" <> translate(
                    btrim(account.email),
                    'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
                    'abcdefghijklmnopqrstuvwxyz'
                 ) COLLATE "C"
          )
    ) THEN
        RAISE EXCEPTION 'teachers.user_id association requires reviewed reconciliation';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM public.teachers AS teacher
        WHERE teacher.user_id IS NULL
          AND (
              SELECT count(*)
              FROM public.users AS account
              WHERE account.role::text = 'TEACHER'
                AND translate(
                        btrim(account.email),
                        'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
                        'abcdefghijklmnopqrstuvwxyz'
                    ) COLLATE "C" = translate(
                        btrim(teacher.email),
                        'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
                        'abcdefghijklmnopqrstuvwxyz'
                    ) COLLATE "C"
          ) <> 1
    ) THEN
        RAISE EXCEPTION 'teacher row does not map to exactly one teacher account';
    END IF;
    IF EXISTS (
        WITH resolved_teachers AS (
            SELECT
                teacher.id,
                COALESCE(
                    teacher.user_id,
                    (
                        SELECT min(account.id)
                        FROM public.users AS account
                        WHERE account.role::text = 'TEACHER'
                          AND translate(
                                btrim(account.email),
                                'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
                                'abcdefghijklmnopqrstuvwxyz'
                              ) COLLATE "C" = translate(
                                btrim(teacher.email),
                                'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
                                'abcdefghijklmnopqrstuvwxyz'
                              ) COLLATE "C"
                    )
                ) AS resolved_user_id
            FROM public.teachers AS teacher
        )
        SELECT 1 FROM resolved_teachers
        GROUP BY resolved_user_id
        HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION 'multiple teacher rows map to one user';
    END IF;
END
$identity_preflight$;
"""


OPERATOR_FUNCTIONS_SQL = r"""
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC;

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

CREATE OR REPLACE FUNCTION public.operator_create_teacher_invitation(
    p_token_digest VARCHAR(64),
    p_email_digest VARCHAR(64),
    p_expires_at TIMESTAMPTZ,
    p_actor_identifier VARCHAR(100),
    p_resource_digest VARCHAR(64)
)
RETURNS VARCHAR(16)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $operator_create_teacher_invitation$
DECLARE
    v_now TIMESTAMPTZ := transaction_timestamp();
BEGIN
    IF p_token_digest IS NULL
       OR p_token_digest !~ '^[0-9a-f]{64}$'
       OR p_email_digest IS NULL
       OR p_email_digest !~ '^[0-9a-f]{64}$'
       OR p_actor_identifier IS NULL
       OR p_actor_identifier !~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,99}$'
       OR p_resource_digest IS NULL
       OR p_resource_digest !~ '^[0-9a-f]{64}$'
       OR p_expires_at IS NULL
       OR p_expires_at <= v_now
       OR p_expires_at > v_now + INTERVAL '720 hours'
    THEN
        RAISE EXCEPTION 'invalid invitation create command' USING ERRCODE = '22023';
    END IF;

    UPDATE public.teacher_invitations
    SET revoked_at = v_now
    WHERE email_digest = p_email_digest
      AND consumed_at IS NULL
      AND revoked_at IS NULL
      AND expires_at <= v_now;

    BEGIN
        INSERT INTO public.teacher_invitations (
            token_digest, email_digest, expires_at, created_by
        ) VALUES (
            p_token_digest, p_email_digest, p_expires_at, p_actor_identifier
        );
    EXCEPTION WHEN unique_violation THEN
        INSERT INTO public.operator_audit_events (
            actor_identifier, action, outcome, resource_digest
        ) VALUES (
            p_actor_identifier,
            'TEACHER_INVITATION_CREATED',
            'CONFLICT',
            p_resource_digest
        );
        RETURN 'CONFLICT';
    END;

    INSERT INTO public.operator_audit_events (
        actor_identifier, action, outcome, resource_digest
    ) VALUES (
        p_actor_identifier,
        'TEACHER_INVITATION_CREATED',
        'SUCCEEDED',
        p_resource_digest
    );
    RETURN 'SUCCEEDED';
END
$operator_create_teacher_invitation$;

CREATE OR REPLACE FUNCTION public.operator_revoke_teacher_invitation(
    p_email_digest VARCHAR(64),
    p_actor_identifier VARCHAR(100),
    p_resource_digest VARCHAR(64)
)
RETURNS VARCHAR(16)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $operator_revoke_teacher_invitation$
DECLARE
    v_now TIMESTAMPTZ := transaction_timestamp();
    v_updated INTEGER;
    v_outcome VARCHAR(16);
BEGIN
    IF p_email_digest IS NULL
       OR p_email_digest !~ '^[0-9a-f]{64}$'
       OR p_actor_identifier IS NULL
       OR p_actor_identifier !~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,99}$'
       OR p_resource_digest IS NULL
       OR p_resource_digest !~ '^[0-9a-f]{64}$'
    THEN
        RAISE EXCEPTION 'invalid invitation revoke command' USING ERRCODE = '22023';
    END IF;

    UPDATE public.teacher_invitations
    SET revoked_at = v_now
    WHERE email_digest = p_email_digest
      AND consumed_at IS NULL
      AND revoked_at IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_outcome := CASE WHEN v_updated = 1 THEN 'SUCCEEDED' ELSE 'NOT_FOUND' END;

    INSERT INTO public.operator_audit_events (
        actor_identifier, action, outcome, resource_digest
    ) VALUES (
        p_actor_identifier,
        'TEACHER_INVITATION_REVOKED',
        v_outcome,
        p_resource_digest
    );
    RETURN v_outcome;
END
$operator_revoke_teacher_invitation$;

REVOKE ALL ON FUNCTION public.operator_set_account_status(
    VARCHAR, BOOLEAN, VARCHAR, VARCHAR
) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.operator_create_teacher_invitation(
    VARCHAR, VARCHAR, TIMESTAMPTZ, VARCHAR, VARCHAR
) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.operator_revoke_teacher_invitation(
    VARCHAR, VARCHAR, VARCHAR
) FROM PUBLIC;
"""


def _is_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _postgresql_check(expression: str, name: str) -> sa.CheckConstraint | None:
    if not _is_postgresql():
        return None
    return sa.CheckConstraint(expression, name=name)


def _sqlite_schema_already_current() -> bool:
    if op.get_bind().dialect.name != "sqlite":
        return False
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    identity_tables = {
        "browser_sessions",
        "teacher_invitations",
        "operator_audit_events",
    }
    has_marker = bool(identity_tables & tables) or any(
        (
            has_any_named_schema_object(
                inspector,
                "users",
                columns=("disabled_at",),
                indexes=("ix_users_disabled_at",),
            ),
            has_any_named_schema_object(
                inspector,
                "teachers",
                unique_constraints=("uq_teachers_user_id",),
            ),
            has_any_named_schema_object(
                inspector,
                "password_resets",
                columns=("delivery_claim_digest",),
                check_constraints=(
                    "ck_password_reset_delivery_claim_digest",
                ),
            ),
        )
    )
    if not has_marker:
        return False

    reset_foreign_keys = inspector.get_foreign_keys("password_resets")
    reset_foreign_key_is_current = len(reset_foreign_keys) == 1 and (
        tuple(reset_foreign_keys[0]["constrained_columns"]) == ("user_id",)
        and reset_foreign_keys[0]["referred_table"] == "users"
        and tuple(reset_foreign_keys[0]["referred_columns"]) == ("id",)
        and reset_foreign_keys[0].get("options", {}).get("ondelete") == "CASCADE"
        and reset_foreign_keys[0]["name"]
        in {None, "fk_password_resets_user_id_users"}
    )
    is_current = all(
        (
            table_contract_matches(
                inspector,
                "users",
                columns={"disabled_at": ("DATETIME", True, None, False)},
                indexes={
                    "ix_users_disabled_at": (("disabled_at",), False, None),
                    "ix_users_email": (("email",), True, None),
                    "ix_users_id": (("id",), False, None),
                    "ix_users_username": (("username",), True, None),
                },
                exact_indexes=True,
            ),
            table_contract_matches(
                inspector,
                "teachers",
                columns={
                    "id": ("INTEGER", False, None, True),
                    "name": ("VARCHAR", True, None, False),
                    "email": ("VARCHAR(100)", False, None, False),
                    "hashed_password": ("VARCHAR", True, None, False),
                    "user_id": ("INTEGER", False, None, False),
                },
                indexes={
                    "ix_teachers_email": (("email",), True, None),
                    "ix_teachers_id": (("id",), False, None),
                },
                unique_constraints=(("uq_teachers_user_id", ("user_id",)),),
                foreign_keys=((None, ("user_id",), "users", ("id",), None),),
                exact_columns=True,
                exact_indexes=True,
                exact_unique_constraints=True,
                exact_foreign_keys=True,
            ),
            table_contract_matches(
                inspector,
                "password_resets",
                columns={
                    "id": ("INTEGER", False, None, True),
                    "user_id": ("INTEGER", False, None, False),
                    "token": ("VARCHAR(64)", True, None, False),
                    "created_at": (
                        "DATETIME",
                        False,
                        "CURRENT_TIMESTAMP",
                        False,
                    ),
                    "expires_at": ("DATETIME", True, None, False),
                    "used": ("BOOLEAN", False, None, False),
                    "delivery_status": ("VARCHAR(16)", False, None, False),
                    "delivery_attempted_at": ("DATETIME", True, None, False),
                    "delivery_claim_digest": ("VARCHAR(64)", True, None, False),
                },
                indexes={
                    "ix_password_resets_delivery_status": (
                        ("delivery_status",),
                        False,
                        None,
                    ),
                    "ix_password_resets_id": (("id",), False, None),
                    "ix_password_resets_token": (("token",), True, None),
                    "ix_password_resets_user_id": (("user_id",), True, None),
                },
                check_constraints={
                    "ck_password_reset_delivery_claim_digest": (
                        "delivery_claim_digest IS NULL OR "
                        "length(delivery_claim_digest) = 64"
                    ),
                    "ck_password_reset_delivery_status": (
                        "delivery_status IN ('PENDING', 'PROCESSING', "
                        "'DELIVERED', 'FAILED')"
                    ),
                },
                exact_columns=True,
                exact_indexes=True,
                exact_check_constraints=True,
            ),
            reset_foreign_key_is_current,
            table_contract_matches(
                inspector,
                "browser_sessions",
                columns={
                    "id": ("INTEGER", False, None, True),
                    "jti_digest": ("VARCHAR(64)", False, None, False),
                    "user_id": ("INTEGER", False, None, False),
                    "created_at": (
                        "DATETIME",
                        False,
                        "CURRENT_TIMESTAMP",
                        False,
                    ),
                    "expires_at": ("DATETIME", False, None, False),
                    "revoked_at": ("DATETIME", True, None, False),
                },
                indexes={
                    "ix_browser_sessions_expires_at": (
                        ("expires_at",),
                        False,
                        None,
                    ),
                    "ix_browser_sessions_user_id": (("user_id",), False, None),
                    "ix_browser_sessions_user_recency": (
                        ("user_id", "created_at", "id"),
                        False,
                        None,
                    ),
                },
                unique_constraints=(
                    ("uq_browser_session_jti_digest", ("jti_digest",)),
                ),
                check_constraints={
                    "ck_browser_session_jti_digest": "length(jti_digest) = 64"
                },
                foreign_keys=(
                    (
                        "fk_browser_session_user",
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
            table_contract_matches(
                inspector,
                "teacher_invitations",
                columns={
                    "id": ("INTEGER", False, None, True),
                    "token_digest": ("VARCHAR(64)", False, None, False),
                    "email_digest": ("VARCHAR(64)", False, None, False),
                    "created_at": (
                        "DATETIME",
                        False,
                        "CURRENT_TIMESTAMP",
                        False,
                    ),
                    "expires_at": ("DATETIME", False, None, False),
                    "consumed_at": ("DATETIME", True, None, False),
                    "revoked_at": ("DATETIME", True, None, False),
                    "created_by": ("VARCHAR(100)", False, None, False),
                },
                indexes={
                    "ix_teacher_invitations_email_digest": (
                        ("email_digest",),
                        False,
                        None,
                    ),
                    "ix_teacher_invitations_expires_at": (
                        ("expires_at",),
                        False,
                        None,
                    ),
                    "uq_teacher_invitation_active_email": (
                        ("email_digest",),
                        True,
                        "consumed_at IS NULL AND revoked_at IS NULL",
                    ),
                },
                unique_constraints=(
                    ("uq_teacher_invitation_token_digest", ("token_digest",)),
                ),
                check_constraints={
                    "ck_teacher_invitation_created_by": (
                        "length(created_by) BETWEEN 1 AND 100"
                    ),
                    "ck_teacher_invitation_email_digest": (
                        "length(email_digest) = 64"
                    ),
                    "ck_teacher_invitation_token_digest": (
                        "length(token_digest) = 64"
                    ),
                },
                foreign_keys=(),
                exact_columns=True,
                exact_indexes=True,
                exact_unique_constraints=True,
                exact_check_constraints=True,
                exact_foreign_keys=True,
            ),
            table_contract_matches(
                inspector,
                "operator_audit_events",
                columns={
                    "id": ("INTEGER", False, None, True),
                    "actor_identifier": ("VARCHAR(100)", False, None, False),
                    "action": ("VARCHAR(64)", False, None, False),
                    "outcome": ("VARCHAR(16)", False, None, False),
                    "resource_digest": ("VARCHAR(64)", False, None, False),
                    "created_at": (
                        "DATETIME",
                        False,
                        "CURRENT_TIMESTAMP",
                        False,
                    ),
                },
                indexes={
                    "ix_operator_audit_events_action": (
                        ("action",),
                        False,
                        None,
                    ),
                    "ix_operator_audit_events_actor_identifier": (
                        ("actor_identifier",),
                        False,
                        None,
                    ),
                    "ix_operator_audit_events_created_at": (
                        ("created_at",),
                        False,
                        None,
                    ),
                    "ix_operator_audit_events_resource_digest": (
                        ("resource_digest",),
                        False,
                        None,
                    ),
                },
                unique_constraints=(),
                check_constraints={
                    "ck_operator_audit_action": (
                        "action IN ('TEACHER_INVITATION_CREATED', "
                        "'TEACHER_INVITATION_REVOKED', "
                        "'ACCOUNT_DISABLED', 'ACCOUNT_ENABLED')"
                    ),
                    "ck_operator_audit_actor_identifier": (
                        "length(actor_identifier) BETWEEN 1 AND 100"
                    ),
                    "ck_operator_audit_outcome": (
                        "outcome IN ('SUCCEEDED', 'NOT_FOUND', 'CONFLICT')"
                    ),
                    "ck_operator_audit_resource_digest": (
                        "length(resource_digest) = 64"
                    ),
                },
                foreign_keys=(),
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
            "partial SQLite schema for c5136f36e302; repair it before retrying"
        )
    return True


def _canonical_email(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        value.encode("ascii")
    except UnicodeEncodeError:
        return None
    normalized = value.strip(" ").lower()
    if not normalized or any(
        character.isspace() or ord(character) < 32 or ord(character) == 127
        for character in normalized
    ):
        return None
    return normalized


def _sqlite_preflight_and_reconcile_identity_rows() -> None:
    bind = op.get_bind()
    users = [
        dict(row)
        for row in bind.execute(
            sa.text("SELECT id, email, role FROM users ORDER BY id")
        ).mappings()
    ]
    teachers = [
        dict(row)
        for row in bind.execute(
            sa.text("SELECT id, email, user_id FROM teachers ORDER BY id")
        ).mappings()
    ]
    user_by_id: dict[int, dict[str, object]] = {}
    teacher_users_by_email: dict[str, list[dict[str, object]]] = {}
    canonical_user_emails: set[str] = set()
    failed = False

    for account in users:
        canonical = _canonical_email(account["email"])
        if canonical is None or canonical in canonical_user_emails:
            failed = True
            continue
        canonical_user_emails.add(canonical)
        account["canonical_email"] = canonical
        user_by_id[int(account["id"])] = account
        if str(account["role"]) == "TEACHER":
            teacher_users_by_email.setdefault(canonical, []).append(account)

    resolved_teachers: list[tuple[int, int, str]] = []
    resolved_user_ids: set[int] = set()
    for teacher in teachers:
        canonical = _canonical_email(teacher["email"])
        if canonical is None or len(canonical) > 100:
            failed = True
            continue
        user_id = teacher["user_id"]
        if user_id is None:
            matches = teacher_users_by_email.get(canonical, [])
            if len(matches) != 1:
                failed = True
                continue
            account = matches[0]
        else:
            account = user_by_id.get(int(user_id))
            if (
                account is None
                or str(account["role"]) != "TEACHER"
                or account.get("canonical_email") != canonical
            ):
                failed = True
                continue
        resolved_user_id = int(account["id"])
        if resolved_user_id in resolved_user_ids:
            failed = True
            continue
        resolved_user_ids.add(resolved_user_id)
        resolved_teachers.append(
            (int(teacher["id"]), resolved_user_id, str(account["canonical_email"]))
        )

    if failed:
        raise RuntimeError(
            "identity control preflight failed; reconcile legacy users and teachers before retrying"
        )

    if users:
        bind.execute(
            sa.text("UPDATE users SET email = :email WHERE id = :id"),
            [
                {"id": int(account["id"]), "email": account["canonical_email"]}
                for account in users
            ],
        )
    if resolved_teachers:
        bind.execute(
            sa.text(
                "UPDATE teachers SET user_id = :user_id, email = :email WHERE id = :id"
            ),
            [
                {"id": teacher_id, "user_id": user_id, "email": email}
                for teacher_id, user_id, email in resolved_teachers
            ],
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


def _invalidate_legacy_password_resets() -> None:
    op.execute(
        sa.text(
            "UPDATE password_resets SET token = NULL, expires_at = NULL, "
            "used = TRUE, delivery_status = 'FAILED', "
            "delivery_attempted_at = CURRENT_TIMESTAMP, "
            "delivery_claim_digest = NULL"
        )
    )


def upgrade() -> None:
    sqlite_schema_is_current = _sqlite_schema_already_current()
    if sqlite_schema_is_current:
        _sqlite_preflight_and_reconcile_identity_rows()
        _invalidate_legacy_password_resets()
        return
    postgresql = _is_postgresql()
    if postgresql:
        op.execute(sa.text(EMAIL_PREFLIGHT_SQL))
    else:
        _sqlite_preflight_and_reconcile_identity_rows()

    op.add_column(
        "users",
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_users_disabled_at", "users", ["disabled_at"], unique=False)

    if postgresql:
        op.execute(
            sa.text(
                "UPDATE public.teachers AS teacher SET user_id = account.id "
                "FROM public.users AS account "
                "WHERE teacher.user_id IS NULL "
                "AND account.role::text = 'TEACHER' "
                "AND translate(btrim(account.email), "
                "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz') COLLATE \"C\" "
                "= translate(btrim(teacher.email), "
                "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz') COLLATE \"C\""
            )
        )
        op.execute(
            sa.text(
                "UPDATE public.users SET email = translate(btrim(email), "
                "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz') "
                'WHERE email COLLATE "C" IS DISTINCT FROM '
                "translate(btrim(email), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
                "'abcdefghijklmnopqrstuvwxyz') COLLATE \"C\""
            )
        )
        op.execute(
            sa.text(
                "UPDATE public.teachers AS teacher SET email = account.email "
                "FROM public.users AS account WHERE teacher.user_id = account.id "
                'AND teacher.email COLLATE "C" '
                'IS DISTINCT FROM account.email COLLATE "C"'
            )
        )
        op.create_check_constraint(
            "ck_users_email_ascii",
            "users",
            "octet_length(email) = char_length(email)",
        )
        op.create_check_constraint(
            "ck_users_email_canonical",
            "users",
            'email COLLATE "C" = translate(btrim(email), '
            "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz') COLLATE \"C\"",
        )
        op.create_check_constraint("ck_users_email_no_whitespace", "users", "email !~ '[[:space:]]'")
        op.create_check_constraint("ck_users_email_no_controls", "users", "email !~ '[[:cntrl:]]'")
        op.create_index(
            "uq_users_email_normalized",
            "users",
            ["email"],
            unique=True,
            postgresql_ops={"email": "varchar_pattern_ops"},
        )
        op.alter_column(
            "teachers",
            "email",
            existing_type=sa.String(),
            type_=sa.String(length=100),
            nullable=False,
        )
        op.alter_column(
            "teachers",
            "user_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
        op.create_unique_constraint("uq_teachers_user_id", "teachers", ["user_id"])
        op.create_check_constraint(
            "ck_teachers_email_ascii",
            "teachers",
            "octet_length(email) = char_length(email)",
        )
        op.create_check_constraint(
            "ck_teachers_email_canonical",
            "teachers",
            'email COLLATE "C" = translate(btrim(email), '
            "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz') COLLATE \"C\"",
        )
        op.create_check_constraint(
            "ck_teachers_email_no_whitespace",
            "teachers",
            "email !~ '[[:space:]]'",
        )
        op.create_check_constraint(
            "ck_teachers_email_no_controls",
            "teachers",
            "email !~ '[[:cntrl:]]'",
        )
    else:
        with op.batch_alter_table("teachers", recreate="always") as batch_op:
            batch_op.alter_column(
                "email",
                existing_type=sa.String(),
                type_=sa.String(length=100),
                nullable=False,
            )
            batch_op.alter_column("user_id", existing_type=sa.Integer(), nullable=False)
            batch_op.create_unique_constraint("uq_teachers_user_id", ["user_id"])

    op.add_column(
        "password_resets",
        sa.Column("delivery_claim_digest", sa.String(length=64), nullable=True),
    )
    _invalidate_legacy_password_resets()
    if postgresql:
        op.create_check_constraint(
            "ck_password_reset_delivery_claim_digest",
            "password_resets",
            "delivery_claim_digest IS NULL OR length(delivery_claim_digest) = 64",
        )
        op.create_check_constraint(
            "ck_password_reset_delivery_claim_digest_lower_hex",
            "password_resets",
            "delivery_claim_digest IS NULL OR delivery_claim_digest ~ '^[0-9a-f]{64}$'",
        )
        op.create_check_constraint(
            "ck_password_reset_token_lower_hex",
            "password_resets",
            "token IS NULL OR token ~ '^[0-9a-f]{64}$'",
        )
    else:
        with op.batch_alter_table("password_resets", recreate="always") as batch_op:
            batch_op.create_check_constraint(
                "ck_password_reset_delivery_claim_digest",
                "delivery_claim_digest IS NULL OR length(delivery_claim_digest) = 64",
            )

    browser_constraints: list[sa.Constraint] = [
        sa.UniqueConstraint("jti_digest", name="uq_browser_session_jti_digest"),
        sa.CheckConstraint("length(jti_digest) = 64", name="ck_browser_session_jti_digest"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
            name="fk_browser_session_user",
        ),
    ]
    browser_hex = _postgresql_check(
        "jti_digest ~ '^[0-9a-f]{64}$'",
        "ck_browser_session_jti_digest_lower_hex",
    )
    if browser_hex is not None:
        browser_constraints.append(browser_hex)
    op.create_table(
        "browser_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("jti_digest", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        *browser_constraints,
    )
    op.create_index("ix_browser_sessions_user_id", "browser_sessions", ["user_id"], unique=False)
    op.create_index(
        "ix_browser_sessions_expires_at",
        "browser_sessions",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_browser_sessions_user_recency",
        "browser_sessions",
        ["user_id", "created_at", "id"],
        unique=False,
    )

    invitation_constraints: list[sa.Constraint] = [
        sa.UniqueConstraint("token_digest", name="uq_teacher_invitation_token_digest"),
        sa.CheckConstraint(
            "length(token_digest) = 64",
            name="ck_teacher_invitation_token_digest",
        ),
        sa.CheckConstraint(
            "length(email_digest) = 64",
            name="ck_teacher_invitation_email_digest",
        ),
        sa.CheckConstraint(
            "length(created_by) BETWEEN 1 AND 100",
            name="ck_teacher_invitation_created_by",
        ),
    ]
    for constraint in (
        _postgresql_check(
            "token_digest ~ '^[0-9a-f]{64}$'",
            "ck_teacher_invitation_token_digest_lower_hex",
        ),
        _postgresql_check(
            "email_digest ~ '^[0-9a-f]{64}$'",
            "ck_teacher_invitation_email_digest_lower_hex",
        ),
        _postgresql_check(
            "created_by ~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,99}$'",
            "ck_teacher_invitation_created_by_format",
        ),
    ):
        if constraint is not None:
            invitation_constraints.append(constraint)
    op.create_table(
        "teacher_invitations",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column("email_digest", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=100), nullable=False),
        *invitation_constraints,
    )
    op.create_index(
        "ix_teacher_invitations_email_digest",
        "teacher_invitations",
        ["email_digest"],
        unique=False,
    )
    op.create_index(
        "ix_teacher_invitations_expires_at",
        "teacher_invitations",
        ["expires_at"],
        unique=False,
    )
    active_invitation = sa.text("consumed_at IS NULL AND revoked_at IS NULL")
    op.create_index(
        "uq_teacher_invitation_active_email",
        "teacher_invitations",
        ["email_digest"],
        unique=True,
        sqlite_where=active_invitation,
        postgresql_where=active_invitation,
    )

    audit_constraints: list[sa.Constraint] = [
        sa.CheckConstraint(
            "length(actor_identifier) BETWEEN 1 AND 100",
            name="ck_operator_audit_actor_identifier",
        ),
        sa.CheckConstraint(
            "action IN ('TEACHER_INVITATION_CREATED', "
            "'TEACHER_INVITATION_REVOKED', 'ACCOUNT_DISABLED', 'ACCOUNT_ENABLED')",
            name="ck_operator_audit_action",
        ),
        sa.CheckConstraint(
            "outcome IN ('SUCCEEDED', 'NOT_FOUND', 'CONFLICT')",
            name="ck_operator_audit_outcome",
        ),
        sa.CheckConstraint(
            "length(resource_digest) = 64",
            name="ck_operator_audit_resource_digest",
        ),
    ]
    for constraint in (
        _postgresql_check(
            "actor_identifier ~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,99}$'",
            "ck_operator_audit_actor_identifier_format",
        ),
        _postgresql_check(
            "resource_digest ~ '^[0-9a-f]{64}$'",
            "ck_operator_audit_resource_digest_lower_hex",
        ),
    ):
        if constraint is not None:
            audit_constraints.append(constraint)
    op.create_table(
        "operator_audit_events",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("actor_identifier", sa.String(length=100), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("resource_digest", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        *audit_constraints,
    )
    for column in ("actor_identifier", "action", "resource_digest", "created_at"):
        op.create_index(
            f"ix_operator_audit_events_{column}",
            "operator_audit_events",
            [column],
            unique=False,
        )

    if postgresql:
        op.execute(sa.text(OPERATOR_FUNCTIONS_SQL))


def downgrade() -> None:
    _assert_password_reset_downgrade_is_safe()
    postgresql = _is_postgresql()
    if postgresql:
        op.execute(
            sa.text(
                "DROP FUNCTION IF EXISTS public.operator_set_account_status("
                "VARCHAR, BOOLEAN, VARCHAR, VARCHAR); "
                "DROP FUNCTION IF EXISTS public.operator_create_teacher_invitation("
                "VARCHAR, VARCHAR, TIMESTAMPTZ, VARCHAR, VARCHAR); "
                "DROP FUNCTION IF EXISTS public.operator_revoke_teacher_invitation("
                "VARCHAR, VARCHAR, VARCHAR)"
            )
        )

    for column in ("created_at", "resource_digest", "action", "actor_identifier"):
        op.drop_index(
            f"ix_operator_audit_events_{column}",
            table_name="operator_audit_events",
        )
    op.drop_table("operator_audit_events")
    op.drop_index("uq_teacher_invitation_active_email", table_name="teacher_invitations")
    op.drop_index("ix_teacher_invitations_expires_at", table_name="teacher_invitations")
    op.drop_index("ix_teacher_invitations_email_digest", table_name="teacher_invitations")
    op.drop_table("teacher_invitations")
    op.drop_index("ix_browser_sessions_user_recency", table_name="browser_sessions")
    op.drop_index("ix_browser_sessions_expires_at", table_name="browser_sessions")
    op.drop_index("ix_browser_sessions_user_id", table_name="browser_sessions")
    op.drop_table("browser_sessions")

    if postgresql:
        op.drop_constraint(
            "ck_password_reset_token_lower_hex",
            "password_resets",
            type_="check",
        )
        op.drop_constraint(
            "ck_password_reset_delivery_claim_digest_lower_hex",
            "password_resets",
            type_="check",
        )
        op.drop_constraint(
            "ck_password_reset_delivery_claim_digest",
            "password_resets",
            type_="check",
        )
    else:
        with op.batch_alter_table("password_resets", recreate="always") as batch_op:
            batch_op.drop_constraint("ck_password_reset_delivery_claim_digest", type_="check")
    op.drop_column("password_resets", "delivery_claim_digest")

    if postgresql:
        for name in (
            "ck_teachers_email_no_controls",
            "ck_teachers_email_no_whitespace",
            "ck_teachers_email_canonical",
            "ck_teachers_email_ascii",
        ):
            op.drop_constraint(name, "teachers", type_="check")
        op.drop_constraint("uq_teachers_user_id", "teachers", type_="unique")
        op.alter_column("teachers", "user_id", existing_type=sa.Integer(), nullable=True)
        op.alter_column(
            "teachers",
            "email",
            existing_type=sa.String(length=100),
            type_=sa.String(),
            nullable=True,
        )
        op.drop_index("uq_users_email_normalized", table_name="users")
        for name in (
            "ck_users_email_no_controls",
            "ck_users_email_no_whitespace",
            "ck_users_email_canonical",
            "ck_users_email_ascii",
        ):
            op.drop_constraint(name, "users", type_="check")
    else:
        with op.batch_alter_table("teachers", recreate="always") as batch_op:
            batch_op.drop_constraint("uq_teachers_user_id", type_="unique")
            batch_op.alter_column("user_id", existing_type=sa.Integer(), nullable=True)
            batch_op.alter_column(
                "email",
                existing_type=sa.String(length=100),
                type_=sa.String(),
                nullable=True,
            )

    op.drop_index("ix_users_disabled_at", table_name="users")
    op.drop_column("users", "disabled_at")
