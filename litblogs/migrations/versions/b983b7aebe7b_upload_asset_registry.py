"""add the canonical upload asset registry

Revision ID: b983b7aebe7b
Revises: f0684bf8ff2e
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.sqlite_contract import table_contract_matches

revision: str = "b983b7aebe7b"
down_revision: str | Sequence[str] | None = "f0684bf8ff2e"
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
    if "upload_assets" in inspector.get_table_names():
        if op.get_bind().dialect.name == "sqlite" and not table_contract_matches(
            inspector,
            "upload_assets",
            columns={
                "id": ("INTEGER", False, None, True),
                "storage_key": ("VARCHAR(255)", False, None, False),
                "owner_user_id": ("INTEGER", True, None, False),
                "blog_id": ("INTEGER", True, None, False),
                "purpose": ("VARCHAR(20)", False, None, False),
                "state": ("VARCHAR(20)", False, None, False),
                "original_filename": ("VARCHAR(255)", True, None, False),
                "media_type": ("VARCHAR(127)", False, None, False),
                "size_bytes": ("BIGINT", False, None, False),
                "sha256_digest": ("CHAR(64)", False, None, False),
                "created_at": (
                    "DATETIME",
                    False,
                    "CURRENT_TIMESTAMP",
                    False,
                ),
                "expires_at": ("DATETIME", True, None, False),
                "bound_at": ("DATETIME", True, None, False),
                "delete_after": ("DATETIME", True, None, False),
                "deleted_at": ("DATETIME", True, None, False),
                "scan_completed_at": ("DATETIME", True, None, False),
            },
            indexes={
                "ix_upload_assets_blog_id": (("blog_id",), False, None),
                "ix_upload_assets_expires_at": (("expires_at",), False, None),
                "ix_upload_assets_owner_state_created": (
                    ("owner_user_id", "state", "created_at"),
                    False,
                    None,
                ),
                "ix_upload_assets_state_delete_after": (
                    ("state", "delete_after"),
                    False,
                    None,
                ),
                "uq_upload_assets_active_profile_purpose": (
                    ("owner_user_id", "purpose"),
                    True,
                    "state = 'ACTIVE' AND purpose IN "
                    "('PROFILE_IMAGE', 'COVER_IMAGE')",
                ),
            },
            unique_constraints=((None, ("storage_key",)),),
            check_constraints={
                "ck_upload_assets_positive_size": "size_bytes > 0",
                "ck_upload_assets_purpose": (
                    "purpose IN ('POST', 'PROFILE_IMAGE', 'COVER_IMAGE')"
                ),
                "ck_upload_assets_sha256_length": (
                    "length(sha256_digest) = 64"
                ),
                "ck_upload_assets_state": (
                    "state IN ('PENDING', 'ACTIVE', 'DELETE_PENDING', 'DELETED')"
                ),
                "ck_upload_assets_state_shape": (
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
                    "(purpose IN ('PROFILE_IMAGE', 'COVER_IMAGE') "
                    "AND blog_id IS NULL))) OR "
                    "(state = 'DELETE_PENDING' AND delete_after IS NOT NULL "
                    "AND blog_id IS NULL AND expires_at IS NULL "
                    "AND deleted_at IS NULL AND scan_completed_at IS NOT NULL) OR "
                    "(state = 'DELETED' AND blog_id IS NULL "
                    "AND expires_at IS NULL AND delete_after IS NULL "
                    "AND deleted_at IS NOT NULL AND original_filename IS NULL "
                    "AND scan_completed_at IS NOT NULL)"
                ),
                "ck_upload_assets_storage_key_prefix": (
                    "substr(storage_key, 1, 8) = 'objects/' AND "
                    "substr(storage_key, 9, 2) = substr(storage_key, 12, 2)"
                ),
            },
            foreign_keys=(
                (
                    "fk_upload_assets_owner_user",
                    ("owner_user_id",),
                    "users",
                    ("id",),
                    "SET NULL",
                ),
                (
                    "fk_upload_assets_blog",
                    ("blog_id",),
                    "blogs",
                    ("id",),
                    "SET NULL",
                ),
            ),
            exact_columns=True,
            exact_indexes=True,
            exact_unique_constraints=True,
            exact_check_constraints=True,
            exact_foreign_keys=True,
        ):
            raise RuntimeError(
                "partial SQLite schema for b983b7aebe7b; repair it before retrying"
            )
        return
    constraints: list[sa.Constraint] = [
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            ondelete="SET NULL",
            name="fk_upload_assets_owner_user",
        ),
        sa.ForeignKeyConstraint(
            ["blog_id"],
            ["blogs.id"],
            ondelete="SET NULL",
            name="fk_upload_assets_blog",
        ),
        sa.CheckConstraint(
            "purpose IN ('POST', 'PROFILE_IMAGE', 'COVER_IMAGE')",
            name="ck_upload_assets_purpose",
        ),
        sa.CheckConstraint(
            "state IN ('PENDING', 'ACTIVE', 'DELETE_PENDING', 'DELETED')",
            name="ck_upload_assets_state",
        ),
        sa.CheckConstraint("size_bytes > 0", name="ck_upload_assets_positive_size"),
        sa.CheckConstraint(
            "length(sha256_digest) = 64",
            name="ck_upload_assets_sha256_length",
        ),
        sa.CheckConstraint(
            "substr(storage_key, 1, 8) = 'objects/' AND substr(storage_key, 9, 2) = substr(storage_key, 12, 2)",
            name="ck_upload_assets_storage_key_prefix",
        ),
        sa.CheckConstraint(
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
            "AND original_filename IS NULL AND scan_completed_at IS NOT NULL)",
            name="ck_upload_assets_state_shape",
        ),
    ]
    if op.get_bind().dialect.name == "postgresql":
        constraints.extend(
            (
                sa.CheckConstraint(
                    "sha256_digest ~ '^[0-9a-f]{64}$'",
                    name="ck_upload_assets_sha256_lower_hex",
                ),
                sa.CheckConstraint(
                    "storage_key ~ '^objects/[0-9a-f]{2}/[0-9a-f]{32}\\.[a-z0-9]{1,10}$'",
                    name="ck_upload_assets_storage_key_format",
                ),
            )
        )

    op.create_table(
        "upload_assets",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("storage_key", sa.String(length=255), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=True),
        sa.Column("blog_id", sa.Integer(), nullable=True),
        sa.Column("purpose", sa.String(length=20), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("media_type", sa.String(length=127), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256_digest", sa.CHAR(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("bound_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delete_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scan_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("storage_key"),
        *constraints,
    )
    op.create_index(
        "ix_upload_assets_owner_state_created",
        "upload_assets",
        ["owner_user_id", "state", "created_at"],
        unique=False,
    )
    op.create_index("ix_upload_assets_blog_id", "upload_assets", ["blog_id"], unique=False)
    op.create_index("ix_upload_assets_expires_at", "upload_assets", ["expires_at"], unique=False)
    op.create_index(
        "ix_upload_assets_state_delete_after",
        "upload_assets",
        ["state", "delete_after"],
        unique=False,
    )
    active_profile = sa.text("state = 'ACTIVE' AND purpose IN ('PROFILE_IMAGE', 'COVER_IMAGE')")
    op.create_index(
        "uq_upload_assets_active_profile_purpose",
        "upload_assets",
        ["owner_user_id", "purpose"],
        unique=True,
        sqlite_where=active_profile,
        postgresql_where=active_profile,
    )


def downgrade() -> None:
    _assert_password_reset_downgrade_is_safe()
    op.drop_index("uq_upload_assets_active_profile_purpose", table_name="upload_assets")
    op.drop_index("ix_upload_assets_state_delete_after", table_name="upload_assets")
    op.drop_index("ix_upload_assets_expires_at", table_name="upload_assets")
    op.drop_index("ix_upload_assets_blog_id", table_name="upload_assets")
    op.drop_index("ix_upload_assets_owner_state_created", table_name="upload_assets")
    op.drop_table("upload_assets")
