"""add monotonic assignment draft revisions

Revision ID: f0684bf8ff2e
Revises: c5136f36e302
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.sqlite_contract import table_contract_matches

revision: str = "f0684bf8ff2e"
down_revision: str | Sequence[str] | None = "c5136f36e302"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "revision" in {
        column["name"] for column in inspector.get_columns("assignment_drafts")
    }:
        if op.get_bind().dialect.name == "sqlite" and not table_contract_matches(
            inspector,
            "assignment_drafts",
            columns={
                "id": ("INTEGER", False, None, True),
                "assignment_id": ("INTEGER", False, None, False),
                "student_id": ("INTEGER", False, None, False),
                "content": ("TEXT", True, None, False),
                "updated_at": (
                    "DATETIME",
                    False,
                    "CURRENT_TIMESTAMP",
                    False,
                ),
                "revision": ("INTEGER", False, "0", False),
            },
            indexes={
                "ix_assignment_drafts_id": (("id",), False, None),
            },
            unique_constraints=(
                (
                    "unique_assignment_draft",
                    ("assignment_id", "student_id"),
                ),
            ),
            check_constraints={
                "assignment_drafts_revision_range": (
                    "revision >= 0 AND revision <= 2147483647"
                )
            },
            foreign_keys=(
                (
                    None,
                    ("assignment_id",),
                    "assignments",
                    ("id",),
                    "CASCADE",
                ),
                (None, ("student_id",), "users", ("id",), "CASCADE"),
            ),
            exact_columns=True,
            exact_indexes=True,
            exact_unique_constraints=True,
            exact_check_constraints=True,
            exact_foreign_keys=True,
        ):
            raise RuntimeError(
                "partial SQLite schema for f0684bf8ff2e; repair it before retrying"
            )
        return
    op.add_column(
        "assignment_drafts",
        sa.Column(
            "revision",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("assignment_drafts", recreate="always") as batch_op:
            batch_op.create_check_constraint(
                "assignment_drafts_revision_range",
                "revision >= 0 AND revision <= 2147483647",
            )
    else:
        op.create_check_constraint(
            "assignment_drafts_revision_range",
            "assignment_drafts",
            "revision >= 0 AND revision <= 2147483647",
        )


def downgrade() -> None:
    _assert_password_reset_downgrade_is_safe()
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("assignment_drafts", recreate="always") as batch_op:
            batch_op.drop_constraint("assignment_drafts_revision_range", type_="check")
    else:
        op.drop_constraint(
            "assignment_drafts_revision_range",
            "assignment_drafts",
            type_="check",
        )
    op.drop_column("assignment_drafts", "revision")
