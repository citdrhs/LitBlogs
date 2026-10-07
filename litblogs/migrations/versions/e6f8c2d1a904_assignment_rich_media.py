"""Keep rich assignment media private and bound to student work.

Revision ID: e6f8c2d1a904
Revises: d93c5e8a41b2
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.sqlite_contract import table_contract_matches

revision: str = "e6f8c2d1a904"
down_revision: str | Sequence[str] | None = "d93c5e8a41b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_PURPOSE = "purpose IN ('POST', 'PROFILE_IMAGE', 'COVER_IMAGE')"
NEW_PURPOSE = "purpose IN ('POST', 'PROFILE_IMAGE', 'COVER_IMAGE', 'ASSIGNMENT_MEDIA')"
OLD_SHAPE = (
    "(state = 'PENDING' AND purpose = 'POST' "
    "AND owner_user_id IS NOT NULL AND blog_id IS NULL "
    "AND expires_at IS NOT NULL AND bound_at IS NULL "
    "AND delete_after IS NULL AND deleted_at IS NULL "
    "AND scan_completed_at IS NOT NULL) OR "
    "(state = 'ACTIVE' AND owner_user_id IS NOT NULL "
    "AND expires_at IS NULL AND bound_at IS NOT NULL "
    "AND delete_after IS NULL AND deleted_at IS NULL "
    "AND scan_completed_at IS NOT NULL AND "
    "((purpose = 'POST' AND blog_id IS NOT NULL) OR "
    "(purpose IN ('PROFILE_IMAGE', 'COVER_IMAGE') AND blog_id IS NULL))) OR "
    "(state = 'DELETE_PENDING' AND delete_after IS NOT NULL "
    "AND blog_id IS NULL AND expires_at IS NULL "
    "AND deleted_at IS NULL AND scan_completed_at IS NOT NULL) OR "
    "(state = 'DELETED' AND blog_id IS NULL AND expires_at IS NULL "
    "AND delete_after IS NULL AND deleted_at IS NOT NULL "
    "AND original_filename IS NULL AND scan_completed_at IS NOT NULL)"
)
NEW_SHAPE = (
    "(state = 'PENDING' AND purpose IN ('POST', 'ASSIGNMENT_MEDIA') "
    "AND owner_user_id IS NOT NULL AND blog_id IS NULL "
    "AND ((purpose = 'POST' AND assignment_id IS NULL) OR "
    "(purpose = 'ASSIGNMENT_MEDIA' AND assignment_id IS NOT NULL)) "
    "AND expires_at IS NOT NULL AND bound_at IS NULL "
    "AND delete_after IS NULL AND deleted_at IS NULL "
    "AND scan_completed_at IS NOT NULL) OR "
    "(state = 'ACTIVE' AND owner_user_id IS NOT NULL "
    "AND expires_at IS NULL AND bound_at IS NOT NULL "
    "AND delete_after IS NULL AND deleted_at IS NULL "
    "AND scan_completed_at IS NOT NULL AND "
    "((purpose = 'POST' AND blog_id IS NOT NULL AND assignment_id IS NULL) OR "
    "(purpose IN ('PROFILE_IMAGE', 'COVER_IMAGE') "
    "AND blog_id IS NULL AND assignment_id IS NULL) OR "
    "(purpose = 'ASSIGNMENT_MEDIA' AND blog_id IS NULL "
    "AND assignment_id IS NOT NULL))) OR "
    "(state = 'DELETE_PENDING' AND delete_after IS NOT NULL "
    "AND blog_id IS NULL AND assignment_id IS NULL AND expires_at IS NULL "
    "AND deleted_at IS NULL AND scan_completed_at IS NOT NULL) OR "
    "(state = 'DELETED' AND blog_id IS NULL AND assignment_id IS NULL "
    "AND expires_at IS NULL "
    "AND delete_after IS NULL AND deleted_at IS NOT NULL "
    "AND original_filename IS NULL AND scan_completed_at IS NOT NULL)"
)


def _sqlite_already_complete_or_fail() -> bool:
    """Adopt a complete current-model SQLite schema, never a partial one."""
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if not {"assignment_drafts", "assignment_submissions", "upload_assets"} <= tables:
        raise RuntimeError("partial SQLite schema for e6f8c2d1a904; repair it before retrying")

    draft_columns = {column["name"] for column in inspector.get_columns("assignment_drafts")}
    submission_columns = {
        column["name"] for column in inspector.get_columns("assignment_submissions")
    }
    asset_columns = {column["name"] for column in inspector.get_columns("upload_assets")}
    asset_indexes = {index["name"] for index in inspector.get_indexes("upload_assets")}
    asset_foreign_keys = {
        key["name"] for key in inspector.get_foreign_keys("upload_assets")
    }
    old_checks = table_contract_matches(
        inspector,
        "upload_assets",
        columns={},
        check_constraints={
            "ck_upload_assets_purpose": OLD_PURPOSE,
            "ck_upload_assets_state_shape": OLD_SHAPE,
        },
    )
    new_markers = (
        "content_format" in draft_columns
        or "content_format" in submission_columns
        or "assignment_id" in asset_columns
        or "ix_upload_assets_assignment_id" in asset_indexes
        or "fk_upload_assets_assignment" in asset_foreign_keys
        or not old_checks
    )
    if not new_markers:
        return False

    complete = (
        table_contract_matches(
            inspector,
            "assignment_drafts",
            columns={"content_format": ("VARCHAR(8)", False, "plain", False)},
        )
        and table_contract_matches(
            inspector,
            "assignment_submissions",
            columns={"content_format": ("VARCHAR(8)", False, "plain", False)},
        )
        and table_contract_matches(
            inspector,
            "upload_assets",
            columns={"assignment_id": ("INTEGER", True, None, False)},
            indexes={
                "ix_upload_assets_assignment_id": (("assignment_id",), False, None),
            },
            check_constraints={
                "ck_upload_assets_purpose": NEW_PURPOSE,
                "ck_upload_assets_state_shape": NEW_SHAPE,
            },
            foreign_keys=(
                (
                    "fk_upload_assets_assignment",
                    ("assignment_id",),
                    "assignments",
                    ("id",),
                    "SET NULL",
                ),
            ),
        )
    )
    if not complete:
        raise RuntimeError("partial SQLite schema for e6f8c2d1a904; repair it before retrying")
    return True


def _replace_checks(purpose: str, shape: str) -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("upload_assets", recreate="always") as batch:
            batch.drop_constraint("ck_upload_assets_purpose", type_="check")
            batch.drop_constraint("ck_upload_assets_state_shape", type_="check")
            batch.create_check_constraint("ck_upload_assets_purpose", purpose)
            batch.create_check_constraint("ck_upload_assets_state_shape", shape)
        return
    op.drop_constraint("ck_upload_assets_purpose", "upload_assets", type_="check")
    op.drop_constraint("ck_upload_assets_state_shape", "upload_assets", type_="check")
    op.create_check_constraint("ck_upload_assets_purpose", "upload_assets", purpose)
    op.create_check_constraint("ck_upload_assets_state_shape", "upload_assets", shape)


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite" and _sqlite_already_complete_or_fail():
        return
    op.add_column("assignment_drafts", sa.Column(
        "content_format", sa.String(8), nullable=False, server_default="plain",
    ))
    op.add_column("assignment_submissions", sa.Column(
        "content_format", sa.String(8), nullable=False, server_default="plain",
    ))
    with op.batch_alter_table("upload_assets") as batch:
        batch.add_column(sa.Column("assignment_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_upload_assets_assignment", "assignments", ["assignment_id"], ["id"],
            ondelete="SET NULL",
        )
    op.create_index("ix_upload_assets_assignment_id", "upload_assets", ["assignment_id"])
    _replace_checks(NEW_PURPOSE, NEW_SHAPE)


def downgrade() -> None:
    invalidated_resets = op.get_bind().execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM password_resets "
        "WHERE token IS NULL OR expires_at IS NULL)"
    )).scalar_one()
    if invalidated_resets:
        raise RuntimeError(
            "password reset secrets were irreversibly invalidated; "
            "retire those rows before a reviewed downgrade"
        )
    active = op.get_bind().execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM upload_assets WHERE assignment_id IS NOT NULL "
        "OR purpose = 'ASSIGNMENT_MEDIA')"
    )).scalar_one()
    referenced = op.get_bind().execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM assignment_drafts WHERE content_format <> 'plain') "
        "OR EXISTS (SELECT 1 FROM assignment_submissions WHERE content_format <> 'plain')"
    )).scalar_one()
    if active or referenced:
        raise RuntimeError("Cannot downgrade while rich assignment media exist")
    _replace_checks(OLD_PURPOSE, OLD_SHAPE)
    op.drop_index("ix_upload_assets_assignment_id", table_name="upload_assets")
    with op.batch_alter_table("upload_assets") as batch:
        batch.drop_constraint("fk_upload_assets_assignment", type_="foreignkey")
        batch.drop_column("assignment_id")
    op.drop_column("assignment_submissions", "content_format")
    op.drop_column("assignment_drafts", "content_format")
