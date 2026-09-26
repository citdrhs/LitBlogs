"""Audit administrator account recovery, verification and deletion actions.

Revision ID: c8f21d9a6b70
Revises: b64a9c2e7d31
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "c8f21d9a6b70"
down_revision: str | Sequence[str] | None = "b64a9c2e7d31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_ACTIONS = (
    "TEACHER_INVITATION_CREATED",
    "TEACHER_INVITATION_REVOKED",
    "ACCOUNT_DISABLED",
    "ACCOUNT_ENABLED",
)
NEW_ACTIONS = OLD_ACTIONS + (
    "ACCOUNT_DELETED",
    "ACCOUNT_RECOVERY_LINK_CREATED",
    "ACCOUNT_RECOVERY_EMAIL_QUEUED",
    "ACCOUNT_VERIFICATION_LINK_CREATED",
)


def _replace_action_constraint(actions: tuple[str, ...]) -> None:
    condition = "action IN (" + ", ".join(f"'{action}'" for action in actions) + ")"
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("operator_audit_events", recreate="always") as batch:
            batch.drop_constraint("ck_operator_audit_action", type_="check")
            batch.create_check_constraint("ck_operator_audit_action", condition)
        return
    op.drop_constraint(
        "ck_operator_audit_action", "operator_audit_events", schema="public", type_="check"
    )
    op.create_check_constraint(
        "ck_operator_audit_action", "operator_audit_events", condition, schema="public"
    )


def upgrade() -> None:
    _replace_action_constraint(NEW_ACTIONS)


def downgrade() -> None:
    present = op.get_bind().execute(
        text("SELECT EXISTS (SELECT 1 FROM operator_audit_events WHERE action IN "
             "('ACCOUNT_DELETED', 'ACCOUNT_RECOVERY_LINK_CREATED', "
             "'ACCOUNT_RECOVERY_EMAIL_QUEUED', 'ACCOUNT_VERIFICATION_LINK_CREATED'))")
    ).scalar_one()
    if present:
        raise RuntimeError("Cannot downgrade while new administrator audit events exist")
    _replace_action_constraint(OLD_ACTIONS)
