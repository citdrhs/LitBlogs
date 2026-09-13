"""Allow browser admins to issue invitations through the restricted runtime role.

Revision ID: b64a9c2e7d31
Revises: a82f8f2b1d7c
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "b64a9c2e7d31"
down_revision: str | Sequence[str] | None = "a82f8f2b1d7c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _runtime_role_exists() -> bool:
    connection = op.get_bind()
    return connection.dialect.name == "postgresql" and bool(connection.execute(
        text("SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'litblogs_runtime')")
    ).scalar_one())


def upgrade() -> None:
    if _runtime_role_exists():
        op.execute(
            "GRANT INSERT (token_digest, email_digest, expires_at, created_by) "
            "ON TABLE public.teacher_invitations TO litblogs_runtime"
        )
        op.execute("GRANT USAGE ON SEQUENCE public.teacher_invitations_id_seq TO litblogs_runtime")


def downgrade() -> None:
    if _runtime_role_exists():
        op.execute(
            "REVOKE INSERT (token_digest, email_digest, expires_at, created_by) "
            "ON TABLE public.teacher_invitations FROM litblogs_runtime"
        )
        op.execute("REVOKE USAGE ON SEQUENCE public.teacher_invitations_id_seq FROM litblogs_runtime")
