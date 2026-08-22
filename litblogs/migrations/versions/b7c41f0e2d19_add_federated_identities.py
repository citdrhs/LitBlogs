"""add federated identities

Revision ID: b7c41f0e2d19
Revises: 985a04df032a
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7c41f0e2d19"
down_revision: str | Sequence[str] | None = "985a04df032a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "federated_identities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("issuer", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "provider IN ('google', 'microsoft')",
            name="ck_federated_identity_provider",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider", "issuer", "subject", name="uq_federated_identity_subject"
        ),
        sa.UniqueConstraint(
            "provider", "user_id", name="uq_federated_identity_provider_user"
        ),
    )
    op.create_index(
        "ix_federated_identities_user_id",
        "federated_identities",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_federated_identities_user_id", table_name="federated_identities")
    op.drop_table("federated_identities")
