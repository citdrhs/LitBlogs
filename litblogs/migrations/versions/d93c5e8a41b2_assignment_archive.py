"""Allow teachers to hide assignments while preserving student work.

Revision ID: d93c5e8a41b2
Revises: c8f21d9a6b70
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

from migrations.sqlite_contract import table_contract_matches

revision: str = "d93c5e8a41b2"
down_revision: str | Sequence[str] | None = "c8f21d9a6b70"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        inspector = sa.inspect(op.get_bind())
        if "archived_at" in {
            column["name"] for column in inspector.get_columns("assignments")
        }:
            if not table_contract_matches(
                inspector,
                "assignments",
                columns={
                    "id": ("INTEGER", False, None, True),
                    "class_id": ("INTEGER", False, None, False),
                    "title": ("VARCHAR(200)", False, None, False),
                    "description": ("TEXT", True, None, False),
                    "due_date": ("DATETIME", False, None, False),
                    "created_at": ("DATETIME", True, "CURRENT_TIMESTAMP", False),
                    "created_by": ("INTEGER", False, None, False),
                    "allow_late": ("BOOLEAN", True, None, False),
                    "visibility": ("VARCHAR", True, None, False),
                    "archived_at": ("DATETIME", True, None, False),
                },
                indexes={"ix_assignments_id": (("id",), False, None)},
                unique_constraints=(),
                check_constraints={},
                foreign_keys=(
                    (None, ("class_id",), "classes", ("id",), None),
                    (None, ("created_by",), "users", ("id",), None),
                ),
                exact_columns=True,
                exact_indexes=True,
                exact_unique_constraints=True,
                exact_check_constraints=True,
                exact_foreign_keys=True,
            ):
                raise RuntimeError(
                    "partial SQLite schema for d93c5e8a41b2; repair it before retrying"
                )
            return
    op.add_column("assignments", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    archived = op.get_bind().execute(
        text("SELECT EXISTS (SELECT 1 FROM assignments WHERE archived_at IS NOT NULL)")
    ).scalar_one()
    if archived:
        raise RuntimeError("Cannot downgrade while archived assignments exist")
    op.drop_column("assignments", "archived_at")
