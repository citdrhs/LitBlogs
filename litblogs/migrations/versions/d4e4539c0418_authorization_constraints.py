"""add authorization and reset-outbox constraints

Revision ID: d4e4539c0418
Revises: b7c41f0e2d19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.sqlite_contract import (
    has_any_named_schema_object,
    table_contract_matches,
)

revision: str = "d4e4539c0418"
down_revision: str | Sequence[str] | None = "b7c41f0e2d19"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def _sqlite_schema_already_current() -> bool:
    if not _is_sqlite():
        return False
    inspector = sa.inspect(op.get_bind())
    has_marker = any(
        (
            has_any_named_schema_object(
                inspector,
                "class_enrollments",
                columns=("notes",),
                unique_constraints=("unique_class_enrollment",),
            ),
            has_any_named_schema_object(
                inspector,
                "assignment_submissions",
                unique_constraints=("unique_assignment_submission",),
            ),
            has_any_named_schema_object(
                inspector,
                "password_resets",
                columns=("delivery_status", "delivery_attempted_at"),
                indexes=(
                    "ix_password_resets_user_id",
                    "ix_password_resets_delivery_status",
                ),
                check_constraints=("ck_password_reset_delivery_status",),
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
                "class_enrollments",
                columns={"notes": ("TEXT", True, None, False)},
                unique_constraints=(
                    ("unique_class_enrollment", ("student_id", "class_id")),
                ),
                exact_unique_constraints=True,
            ),
            table_contract_matches(
                inspector,
                "assignment_submissions",
                columns={},
                unique_constraints=(
                    (
                        "unique_assignment_submission",
                        ("assignment_id", "student_id"),
                    ),
                ),
                exact_unique_constraints=True,
            ),
            table_contract_matches(
                inspector,
                "password_resets",
                columns={
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
                    "ck_password_reset_delivery_status": (
                        "delivery_status IN ('PENDING', 'PROCESSING', "
                        "'DELIVERED', 'FAILED')"
                    )
                },
                exact_indexes=True,
                exact_check_constraints=False,
            ),
            reset_foreign_key_is_current,
        )
    )
    if not is_current:
        raise RuntimeError(
            "partial SQLite schema for d4e4539c0418; repair it before retrying"
        )
    return True


def _assert_upgrade_data_is_compatible() -> None:
    bind = op.get_bind()
    checks = (
        "SELECT 1 FROM class_enrollments "
        "GROUP BY student_id, class_id HAVING count(*) > 1 LIMIT 1",
        "SELECT 1 FROM assignment_submissions "
        "GROUP BY assignment_id, student_id HAVING count(*) > 1 LIMIT 1",
        "SELECT 1 FROM password_resets "
        "GROUP BY user_id HAVING count(*) > 1 LIMIT 1",
        "SELECT 1 FROM password_resets WHERE created_at IS NULL LIMIT 1",
    )
    if any(bind.execute(sa.text(statement)).first() is not None for statement in checks):
        raise RuntimeError(
            "authorization constraint preflight failed; reconcile legacy rows before retrying"
        )


def upgrade() -> None:
    if _sqlite_schema_already_current():
        return
    _assert_upgrade_data_is_compatible()
    op.add_column("class_enrollments", sa.Column("notes", sa.Text(), nullable=True))
    op.add_column(
        "password_resets",
        sa.Column("delivery_status", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "password_resets",
        sa.Column("delivery_attempted_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.execute(sa.text("UPDATE password_resets SET delivery_status = 'DELIVERED' WHERE delivery_status IS NULL"))
    op.execute(sa.text("UPDATE password_resets SET used = FALSE WHERE used IS NULL"))

    if _is_sqlite():
        with op.batch_alter_table("class_enrollments", recreate="always") as batch_op:
            batch_op.create_unique_constraint("unique_class_enrollment", ["student_id", "class_id"])
        with op.batch_alter_table("assignment_submissions", recreate="always") as batch_op:
            batch_op.create_unique_constraint("unique_assignment_submission", ["assignment_id", "student_id"])
        with op.batch_alter_table(
            "password_resets",
            recreate="always",
            naming_convention={"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"},
        ) as batch_op:
            batch_op.alter_column("token", existing_type=sa.String(length=64), nullable=True)
            batch_op.alter_column("created_at", existing_type=sa.DateTime(timezone=True), nullable=False)
            batch_op.alter_column("expires_at", existing_type=sa.DateTime(timezone=True), nullable=True)
            batch_op.alter_column("used", existing_type=sa.Boolean(), nullable=False)
            batch_op.alter_column(
                "delivery_status",
                existing_type=sa.String(length=16),
                nullable=False,
            )
            batch_op.drop_constraint("fk_password_resets_user_id_users", type_="foreignkey")
            batch_op.create_foreign_key(
                "fk_password_resets_user_id_users",
                "users",
                ["user_id"],
                ["id"],
                ondelete="CASCADE",
            )
            batch_op.create_check_constraint(
                "ck_password_reset_delivery_status",
                "delivery_status IN ('PENDING', 'PROCESSING', 'DELIVERED', 'FAILED')",
            )
            batch_op.create_index("ix_password_resets_user_id", ["user_id"], unique=True)
            batch_op.create_index(
                "ix_password_resets_delivery_status",
                ["delivery_status"],
                unique=False,
            )
    else:
        op.create_unique_constraint(
            "unique_class_enrollment",
            "class_enrollments",
            ["student_id", "class_id"],
        )
        op.create_unique_constraint(
            "unique_assignment_submission",
            "assignment_submissions",
            ["assignment_id", "student_id"],
        )
        op.alter_column(
            "password_resets",
            "token",
            existing_type=sa.String(length=64),
            nullable=True,
        )
        op.alter_column(
            "password_resets",
            "created_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
        )
        op.alter_column(
            "password_resets",
            "expires_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=True,
        )
        op.alter_column(
            "password_resets",
            "used",
            existing_type=sa.Boolean(),
            nullable=False,
        )
        op.drop_constraint(
            "password_resets_user_id_fkey",
            "password_resets",
            type_="foreignkey",
        )
        op.create_foreign_key(
            None,
            "password_resets",
            "users",
            ["user_id"],
            ["id"],
            ondelete="CASCADE",
        )
        op.create_check_constraint(
            "ck_password_reset_delivery_status",
            "password_resets",
            "delivery_status IN ('PENDING', 'PROCESSING', 'DELIVERED', 'FAILED')",
        )
        op.create_index(
            "ix_password_resets_user_id",
            "password_resets",
            ["user_id"],
            unique=True,
        )
        op.create_index(
            "ix_password_resets_delivery_status",
            "password_resets",
            ["delivery_status"],
            unique=False,
        )
        op.alter_column(
            "password_resets",
            "delivery_status",
            existing_type=sa.String(length=16),
            nullable=False,
        )


def downgrade() -> None:
    if _is_sqlite():
        with op.batch_alter_table("class_enrollments", recreate="always") as batch_op:
            batch_op.drop_constraint("unique_class_enrollment", type_="unique")
        with op.batch_alter_table("assignment_submissions", recreate="always") as batch_op:
            batch_op.drop_constraint("unique_assignment_submission", type_="unique")
        with op.batch_alter_table(
            "password_resets",
            recreate="always",
            naming_convention={"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"},
        ) as batch_op:
            batch_op.drop_index("ix_password_resets_delivery_status")
            batch_op.drop_index("ix_password_resets_user_id")
            batch_op.drop_constraint("ck_password_reset_delivery_status", type_="check")
            batch_op.drop_constraint("fk_password_resets_user_id_users", type_="foreignkey")
            batch_op.create_foreign_key(
                "fk_password_resets_user_id_users",
                "users",
                ["user_id"],
                ["id"],
            )
            batch_op.alter_column("used", existing_type=sa.Boolean(), nullable=True)
            batch_op.alter_column("expires_at", existing_type=sa.DateTime(timezone=True), nullable=False)
            batch_op.alter_column("created_at", existing_type=sa.DateTime(timezone=True), nullable=True)
            batch_op.alter_column("token", existing_type=sa.String(length=64), nullable=False)
    else:
        op.drop_index("ix_password_resets_delivery_status", table_name="password_resets")
        op.drop_index("ix_password_resets_user_id", table_name="password_resets")
        op.drop_constraint(
            "ck_password_reset_delivery_status",
            "password_resets",
            type_="check",
        )
        op.drop_constraint(
            "password_resets_user_id_fkey",
            "password_resets",
            type_="foreignkey",
        )
        op.create_foreign_key(None, "password_resets", "users", ["user_id"], ["id"])
        op.alter_column(
            "password_resets",
            "used",
            existing_type=sa.Boolean(),
            nullable=True,
        )
        op.alter_column(
            "password_resets",
            "expires_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
        )
        op.alter_column(
            "password_resets",
            "created_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=True,
        )
        op.alter_column(
            "password_resets",
            "token",
            existing_type=sa.String(length=64),
            nullable=False,
        )
        op.drop_constraint(
            "unique_assignment_submission",
            "assignment_submissions",
            type_="unique",
        )
        op.drop_constraint("unique_class_enrollment", "class_enrollments", type_="unique")

    op.drop_column("password_resets", "delivery_attempted_at")
    op.drop_column("password_resets", "delivery_status")
    op.drop_column("class_enrollments", "notes")
