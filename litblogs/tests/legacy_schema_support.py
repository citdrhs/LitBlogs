"""Build the pre-recovery SQLite layout used by adoption tests."""

import sqlalchemy as sa

from base import Base


def create_pre_recovery_tables(engine, *, omit: frozenset[str] = frozenset()) -> None:
    """Model the existing schema before the additive admin-audit migration."""
    # Reuse the model tables so PostgreSQL-only ddl_if clauses remain attached.
    # The old action check is the single schema difference relevant here.
    audit = Base.metadata.tables["operator_audit_events"]
    action_check = next(
        constraint for constraint in audit.constraints
        if constraint.name == "ck_operator_audit_action"
    )
    original_sql = action_check.sqltext
    old_sql = (
        "action IN ('TEACHER_INVITATION_CREATED', "
        "'TEACHER_INVITATION_REVOKED', 'ACCOUNT_DISABLED', 'ACCOUNT_ENABLED')"
    )
    try:
        action_check.sqltext = sa.text(old_sql)
        Base.metadata.create_all(
            engine,
            tables=[table for name, table in Base.metadata.tables.items() if name not in omit],
        )
    finally:
        action_check.sqltext = original_sql
