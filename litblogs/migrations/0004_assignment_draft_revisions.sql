BEGIN;

-- Existing content-bearing drafts become revision zero so an authenticated
-- client can adopt them through the normal compare-and-swap protocol.
ALTER TABLE assignment_drafts
    ALTER COLUMN content DROP NOT NULL;

ALTER TABLE assignment_drafts
    ADD COLUMN IF NOT EXISTS revision INTEGER;

UPDATE assignment_drafts
SET revision = 0
WHERE revision IS NULL;

ALTER TABLE assignment_drafts
    ALTER COLUMN revision SET DEFAULT 0,
    ALTER COLUMN revision SET NOT NULL;

ALTER TABLE assignment_drafts
    ADD CONSTRAINT assignment_drafts_revision_range
    CHECK (revision >= 0 AND revision <= 2147483647);

COMMIT;
