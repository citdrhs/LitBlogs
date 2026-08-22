BEGIN;

ALTER TABLE class_enrollments
    ADD COLUMN IF NOT EXISTS notes TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS uq_class_enrollments_student_class
    ON class_enrollments (student_id, class_id);

CREATE UNIQUE INDEX IF NOT EXISTS uq_assignment_submissions_assignment_student
    ON assignment_submissions (assignment_id, student_id);

ALTER TABLE password_resets
    ALTER COLUMN token DROP NOT NULL,
    ALTER COLUMN expires_at DROP NOT NULL;

ALTER TABLE password_resets
    ADD COLUMN IF NOT EXISTS delivery_status VARCHAR(16),
    ADD COLUMN IF NOT EXISTS delivery_attempted_at TIMESTAMPTZ;

UPDATE password_resets
SET delivery_status = 'DELIVERED'
WHERE delivery_status IS NULL;

UPDATE password_resets
SET used = FALSE
WHERE used IS NULL;

ALTER TABLE password_resets
    ALTER COLUMN delivery_status SET DEFAULT 'PENDING',
    ALTER COLUMN delivery_status SET NOT NULL,
    ALTER COLUMN used SET DEFAULT FALSE,
    ALTER COLUMN used SET NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_password_resets_user
    ON password_resets (user_id);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_password_reset_delivery_status'
    ) THEN
        ALTER TABLE password_resets
            ADD CONSTRAINT ck_password_reset_delivery_status
            CHECK (delivery_status IN ('PENDING', 'PROCESSING', 'DELIVERED', 'FAILED'));
    END IF;
END;
$$;

COMMIT;
