-- Semantic PostgreSQL reference for the upload registry. This file documents
-- the intended DDL and must be converted into an ordered, reviewed Alembic
-- migration before production execution.

CREATE TABLE upload_assets (
    id BIGSERIAL PRIMARY KEY,
    storage_key VARCHAR(255) NOT NULL UNIQUE,
    owner_user_id INTEGER NULL,
    blog_id INTEGER NULL,
    purpose VARCHAR(20) NOT NULL,
    state VARCHAR(20) NOT NULL,
    original_filename VARCHAR(255) NULL,
    media_type VARCHAR(127) NOT NULL,
    size_bytes BIGINT NOT NULL,
    sha256_digest CHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMPTZ NULL,
    bound_at TIMESTAMPTZ NULL,
    delete_after TIMESTAMPTZ NULL,
    deleted_at TIMESTAMPTZ NULL,
    scan_completed_at TIMESTAMPTZ NULL,
    CONSTRAINT fk_upload_assets_owner_user
        FOREIGN KEY (owner_user_id) REFERENCES users(id) ON DELETE SET NULL,
    CONSTRAINT fk_upload_assets_blog
        FOREIGN KEY (blog_id) REFERENCES blogs(id) ON DELETE SET NULL,
    CONSTRAINT ck_upload_assets_purpose
        CHECK (purpose IN ('POST', 'PROFILE_IMAGE', 'COVER_IMAGE')),
    CONSTRAINT ck_upload_assets_state
        CHECK (state IN ('PENDING', 'ACTIVE', 'DELETE_PENDING', 'DELETED')),
    CONSTRAINT ck_upload_assets_positive_size
        CHECK (size_bytes > 0),
    CONSTRAINT ck_upload_assets_sha256_length
        CHECK (length(sha256_digest) = 64),
    CONSTRAINT ck_upload_assets_sha256_lower_hex
        CHECK (sha256_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_upload_assets_storage_key_prefix CHECK (
        substring(storage_key FROM 1 FOR 8) = 'objects/'
        AND substring(storage_key FROM 9 FOR 2)
            = substring(storage_key FROM 12 FOR 2)
    ),
    CONSTRAINT ck_upload_assets_storage_key_format CHECK (
        storage_key ~ '^objects/[0-9a-f]{2}/[0-9a-f]{32}\.[a-z0-9]{1,10}$'
    ),
    CONSTRAINT ck_upload_assets_state_shape CHECK (
        (
            state = 'PENDING'
            AND purpose = 'POST'
            AND owner_user_id IS NOT NULL
            AND blog_id IS NULL
            AND expires_at IS NOT NULL
            AND bound_at IS NULL
            AND delete_after IS NULL
            AND deleted_at IS NULL
            AND scan_completed_at IS NOT NULL
        )
        OR
        (
            state = 'ACTIVE'
            AND owner_user_id IS NOT NULL
            AND expires_at IS NULL
            AND bound_at IS NOT NULL
            AND delete_after IS NULL
            AND deleted_at IS NULL
            AND scan_completed_at IS NOT NULL
            AND (
                (purpose = 'POST' AND blog_id IS NOT NULL)
                OR
                (
                    purpose IN ('PROFILE_IMAGE', 'COVER_IMAGE')
                    AND blog_id IS NULL
                )
            )
        )
        OR
        (
            state = 'DELETE_PENDING'
            AND blog_id IS NULL
            AND expires_at IS NULL
            AND delete_after IS NOT NULL
            AND deleted_at IS NULL
            AND scan_completed_at IS NOT NULL
        )
        OR
        (
            state = 'DELETED'
            AND blog_id IS NULL
            AND expires_at IS NULL
            AND delete_after IS NULL
            AND deleted_at IS NOT NULL
            AND original_filename IS NULL
            AND scan_completed_at IS NOT NULL
        )
    )
);

CREATE INDEX ix_upload_assets_owner_state_created
    ON upload_assets (owner_user_id, state, created_at);

CREATE INDEX ix_upload_assets_blog_id
    ON upload_assets (blog_id);

CREATE INDEX ix_upload_assets_expires_at
    ON upload_assets (expires_at);

CREATE INDEX ix_upload_assets_state_delete_after
    ON upload_assets (state, delete_after);

CREATE UNIQUE INDEX uq_upload_assets_active_profile_purpose
    ON upload_assets (owner_user_id, purpose)
    WHERE state = 'ACTIVE'
      AND purpose IN ('PROFILE_IMAGE', 'COVER_IMAGE');
