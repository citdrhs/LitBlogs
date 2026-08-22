BEGIN;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS disabled_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS ix_users_disabled_at
    ON users (disabled_at);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM users
        WHERE octet_length(email) <> char_length(email)
           OR email ~ '[[:cntrl:]]'
           OR btrim(email) = ''
           OR btrim(email) ~ '[[:space:]]'
    ) THEN
        RAISE EXCEPTION 'users.email contains non-ASCII or unsupported whitespace; reviewed reconciliation is required';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM users
        GROUP BY translate(
            btrim(email),
            'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
            'abcdefghijklmnopqrstuvwxyz'
        ) COLLATE "C"
        HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION 'users.email contains canonical duplicates; reviewed reconciliation is required';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM teachers
        WHERE email IS NULL
           OR octet_length(email) <> char_length(email)
           OR email ~ '[[:cntrl:]]'
           OR char_length(btrim(email)) > 100
           OR btrim(email) = ''
           OR btrim(email) ~ '[[:space:]]'
    ) THEN
        RAISE EXCEPTION 'teachers.email contains null, non-ASCII, or unsupported whitespace; reviewed reconciliation is required';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM teachers AS teacher
        LEFT JOIN users AS account ON account.id = teacher.user_id
        WHERE teacher.user_id IS NOT NULL
          AND (
              account.id IS NULL
              OR account.role::text <> 'TEACHER'
              OR translate(
                    btrim(teacher.email),
                    'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
                    'abcdefghijklmnopqrstuvwxyz'
                 ) COLLATE "C" <> translate(
                    btrim(account.email),
                    'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
                    'abcdefghijklmnopqrstuvwxyz'
                 ) COLLATE "C"
          )
    ) THEN
        RAISE EXCEPTION 'teachers.user_id association is invalid or conflicts with its account email; reviewed reconciliation is required';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM teachers AS teacher
        WHERE teacher.user_id IS NULL
          AND (
              SELECT count(*)
              FROM users AS account
              WHERE account.role::text = 'TEACHER'
                AND translate(
                        btrim(account.email),
                        'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
                        'abcdefghijklmnopqrstuvwxyz'
                    ) COLLATE "C" = translate(
                        btrim(teacher.email),
                        'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
                        'abcdefghijklmnopqrstuvwxyz'
                    ) COLLATE "C"
          ) <> 1
    ) THEN
        RAISE EXCEPTION 'a teacher row cannot be mapped to exactly one teacher account; reviewed reconciliation is required';
    END IF;
    IF EXISTS (
        WITH resolved_teachers AS (
            SELECT
                teacher.id,
                COALESCE(
                    teacher.user_id,
                    (
                        SELECT min(account.id)
                        FROM users AS account
                        WHERE account.role::text = 'TEACHER'
                          AND translate(
                                btrim(account.email),
                                'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
                                'abcdefghijklmnopqrstuvwxyz'
                              ) COLLATE "C" = translate(
                                btrim(teacher.email),
                                'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
                                'abcdefghijklmnopqrstuvwxyz'
                              ) COLLATE "C"
                    )
                ) AS resolved_user_id
            FROM teachers AS teacher
        )
        SELECT 1
        FROM resolved_teachers
        GROUP BY resolved_user_id
        HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION 'multiple teacher rows map to one user; reviewed reconciliation is required';
    END IF;
END;
$$;

UPDATE teachers AS teacher
SET user_id = account.id
FROM users AS account
WHERE teacher.user_id IS NULL
  AND account.role::text = 'TEACHER'
  AND translate(
        btrim(account.email),
        'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
        'abcdefghijklmnopqrstuvwxyz'
      ) COLLATE "C" = translate(
        btrim(teacher.email),
        'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
        'abcdefghijklmnopqrstuvwxyz'
      ) COLLATE "C";

UPDATE users
SET email = translate(
    btrim(email),
    'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
    'abcdefghijklmnopqrstuvwxyz'
)
WHERE email COLLATE "C" IS DISTINCT FROM translate(
    btrim(email),
    'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
    'abcdefghijklmnopqrstuvwxyz'
) COLLATE "C";

UPDATE teachers AS teacher
SET email = account.email
FROM users AS account
WHERE teacher.user_id = account.id
  AND teacher.email COLLATE "C" IS DISTINCT FROM account.email COLLATE "C";

ALTER TABLE users
    ADD CONSTRAINT ck_users_email_ascii
        CHECK (octet_length(email) = char_length(email)),
    ADD CONSTRAINT ck_users_email_canonical
        CHECK (
            email COLLATE "C" = translate(
                btrim(email),
                'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
                'abcdefghijklmnopqrstuvwxyz'
            ) COLLATE "C"
        ),
    ADD CONSTRAINT ck_users_email_no_whitespace
        CHECK (email !~ '[[:space:]]'),
    ADD CONSTRAINT ck_users_email_no_controls
        CHECK (email !~ '[[:cntrl:]]');

CREATE UNIQUE INDEX uq_users_email_normalized
    ON users (email COLLATE "C");

ALTER TABLE teachers
    ALTER COLUMN email TYPE VARCHAR(100),
    ALTER COLUMN email SET NOT NULL,
    ALTER COLUMN user_id SET NOT NULL,
    ADD CONSTRAINT uq_teachers_user_id UNIQUE (user_id),
    ADD CONSTRAINT ck_teachers_email_ascii
        CHECK (octet_length(email) = char_length(email)),
    ADD CONSTRAINT ck_teachers_email_canonical
        CHECK (
            email COLLATE "C" = translate(
                btrim(email),
                'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
                'abcdefghijklmnopqrstuvwxyz'
            ) COLLATE "C"
        ),
    ADD CONSTRAINT ck_teachers_email_no_whitespace
        CHECK (email !~ '[[:space:]]'),
    ADD CONSTRAINT ck_teachers_email_no_controls
        CHECK (email !~ '[[:cntrl:]]');

ALTER TABLE password_resets
    ADD COLUMN IF NOT EXISTS delivery_claim_digest VARCHAR(64),
    ADD CONSTRAINT ck_password_reset_delivery_claim_digest
        CHECK (
            delivery_claim_digest IS NULL
            OR length(delivery_claim_digest) = 64
        ),
    ADD CONSTRAINT ck_password_reset_delivery_claim_digest_lower_hex
        CHECK (
            delivery_claim_digest IS NULL
            OR delivery_claim_digest ~ '^[0-9a-f]{64}$'
        );

-- Reset rows from older releases may contain raw bearer tokens. Invalidate every
-- outstanding link rather than attempting to distinguish plaintext from a digest.
UPDATE password_resets
SET token = NULL,
    expires_at = NULL,
    used = TRUE,
    delivery_status = 'FAILED',
    delivery_attempted_at = CURRENT_TIMESTAMP,
    delivery_claim_digest = NULL;

ALTER TABLE password_resets
    ADD CONSTRAINT ck_password_reset_token_lower_hex
        CHECK (token IS NULL OR token ~ '^[0-9a-f]{64}$');

CREATE TABLE browser_sessions (
    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    jti_digest VARCHAR(64) NOT NULL,
    user_id INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    CONSTRAINT ck_browser_session_jti_digest
        CHECK (length(jti_digest) = 64),
    CONSTRAINT ck_browser_session_jti_digest_lower_hex
        CHECK (jti_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT uq_browser_session_jti_digest
        UNIQUE (jti_digest),
    CONSTRAINT fk_browser_session_user
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX ix_browser_sessions_user_id
    ON browser_sessions (user_id);

CREATE INDEX ix_browser_sessions_user_recency
    ON browser_sessions (user_id, created_at, id);

CREATE INDEX ix_browser_sessions_expires_at
    ON browser_sessions (expires_at);

CREATE TABLE teacher_invitations (
    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    token_digest VARCHAR(64) NOT NULL,
    email_digest VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    created_by VARCHAR(100) NOT NULL,
    CONSTRAINT ck_teacher_invitation_token_digest
        CHECK (length(token_digest) = 64),
    CONSTRAINT ck_teacher_invitation_token_digest_lower_hex
        CHECK (token_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_teacher_invitation_email_digest
        CHECK (length(email_digest) = 64),
    CONSTRAINT ck_teacher_invitation_email_digest_lower_hex
        CHECK (email_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_teacher_invitation_created_by
        CHECK (length(created_by) BETWEEN 1 AND 100),
    CONSTRAINT ck_teacher_invitation_created_by_format
        CHECK (created_by ~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,99}$'),
    CONSTRAINT uq_teacher_invitation_token_digest
        UNIQUE (token_digest)
);

CREATE INDEX ix_teacher_invitations_email_digest
    ON teacher_invitations (email_digest);

CREATE INDEX ix_teacher_invitations_expires_at
    ON teacher_invitations (expires_at);

CREATE UNIQUE INDEX uq_teacher_invitation_active_email
    ON teacher_invitations (email_digest)
    WHERE consumed_at IS NULL AND revoked_at IS NULL;

CREATE TABLE operator_audit_events (
    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    actor_identifier VARCHAR(100) NOT NULL,
    action VARCHAR(64) NOT NULL,
    outcome VARCHAR(16) NOT NULL,
    resource_digest VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_operator_audit_actor_identifier
        CHECK (length(actor_identifier) BETWEEN 1 AND 100),
    CONSTRAINT ck_operator_audit_actor_identifier_format
        CHECK (actor_identifier ~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,99}$'),
    CONSTRAINT ck_operator_audit_action
        CHECK (action IN (
            'TEACHER_INVITATION_CREATED',
            'TEACHER_INVITATION_REVOKED',
            'ACCOUNT_DISABLED',
            'ACCOUNT_ENABLED'
        )),
    CONSTRAINT ck_operator_audit_outcome
        CHECK (outcome IN ('SUCCEEDED', 'NOT_FOUND', 'CONFLICT')),
    CONSTRAINT ck_operator_audit_resource_digest
        CHECK (length(resource_digest) = 64),
    CONSTRAINT ck_operator_audit_resource_digest_lower_hex
        CHECK (resource_digest ~ '^[0-9a-f]{64}$')
);

CREATE INDEX ix_operator_audit_events_actor_identifier
    ON operator_audit_events (actor_identifier);

CREATE INDEX ix_operator_audit_events_action
    ON operator_audit_events (action);

CREATE INDEX ix_operator_audit_events_resource_digest
    ON operator_audit_events (resource_digest);

CREATE INDEX ix_operator_audit_events_created_at
    ON operator_audit_events (created_at);

-- Operator roles receive EXECUTE only on these fixed-transition routines. The
-- migration/Alembic owner remains a separate non-login identity owner; operator
-- roles must never own the functions or receive direct table DML.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;

CREATE OR REPLACE FUNCTION public.operator_set_account_status(
    p_email VARCHAR(100),
    p_disabled BOOLEAN,
    p_actor_identifier VARCHAR(100),
    p_resource_digest VARCHAR(64)
)
RETURNS VARCHAR(16)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_user_id INTEGER;
    v_now TIMESTAMPTZ := transaction_timestamp();
    v_action VARCHAR(64);
BEGIN
    IF p_disabled IS NULL
       OR p_actor_identifier IS NULL
       OR p_actor_identifier !~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,99}$'
       OR p_resource_digest IS NULL
       OR p_resource_digest !~ '^[0-9a-f]{64}$'
       OR p_email IS NULL
       OR p_email = ''
       OR octet_length(p_email) <> char_length(p_email)
       OR p_email ~ '[[:cntrl:]]'
       OR p_email ~ '[[:space:]]'
       OR p_email COLLATE "C" <> translate(
            btrim(p_email),
            'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
            'abcdefghijklmnopqrstuvwxyz'
       ) COLLATE "C"
    THEN
        RAISE EXCEPTION 'invalid account status command' USING ERRCODE = '22023';
    END IF;

    SELECT users.id
    INTO v_user_id
    FROM public.users AS users
    WHERE users.email COLLATE "C" = p_email COLLATE "C"
    FOR UPDATE;

    v_action := CASE WHEN p_disabled THEN 'ACCOUNT_DISABLED' ELSE 'ACCOUNT_ENABLED' END;
    IF NOT FOUND THEN
        INSERT INTO public.operator_audit_events (
            actor_identifier,
            action,
            outcome,
            resource_digest
        ) VALUES (
            p_actor_identifier,
            v_action,
            'NOT_FOUND',
            p_resource_digest
        );
        RETURN 'NOT_FOUND';
    END IF;

    UPDATE public.users
    SET disabled_at = CASE WHEN p_disabled THEN v_now ELSE NULL END
    WHERE id = v_user_id;

    IF p_disabled THEN
        UPDATE public.browser_sessions
        SET revoked_at = v_now
        WHERE user_id = v_user_id
          AND revoked_at IS NULL
          AND expires_at > v_now;

        UPDATE public.password_resets
        SET token = NULL,
            expires_at = NULL,
            used = TRUE,
            delivery_status = 'FAILED',
            delivery_attempted_at = v_now,
            delivery_claim_digest = NULL
        WHERE user_id = v_user_id;
    END IF;

    INSERT INTO public.operator_audit_events (
        actor_identifier,
        action,
        outcome,
        resource_digest
    ) VALUES (
        p_actor_identifier,
        v_action,
        'SUCCEEDED',
        p_resource_digest
    );
    RETURN 'SUCCEEDED';
END;
$$;

CREATE OR REPLACE FUNCTION public.operator_create_teacher_invitation(
    p_token_digest VARCHAR(64),
    p_email_digest VARCHAR(64),
    p_expires_at TIMESTAMPTZ,
    p_actor_identifier VARCHAR(100),
    p_resource_digest VARCHAR(64)
)
RETURNS VARCHAR(16)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_now TIMESTAMPTZ := transaction_timestamp();
BEGIN
    IF p_token_digest IS NULL
       OR p_token_digest !~ '^[0-9a-f]{64}$'
       OR p_email_digest IS NULL
       OR p_email_digest !~ '^[0-9a-f]{64}$'
       OR p_actor_identifier IS NULL
       OR p_actor_identifier !~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,99}$'
       OR p_resource_digest IS NULL
       OR p_resource_digest !~ '^[0-9a-f]{64}$'
       OR p_expires_at IS NULL
       OR p_expires_at <= v_now
       OR p_expires_at > v_now + INTERVAL '720 hours'
    THEN
        RAISE EXCEPTION 'invalid invitation create command' USING ERRCODE = '22023';
    END IF;

    UPDATE public.teacher_invitations
    SET revoked_at = v_now
    WHERE email_digest = p_email_digest
      AND consumed_at IS NULL
      AND revoked_at IS NULL
      AND expires_at <= v_now;

    BEGIN
        INSERT INTO public.teacher_invitations (
            token_digest,
            email_digest,
            expires_at,
            created_by
        ) VALUES (
            p_token_digest,
            p_email_digest,
            p_expires_at,
            p_actor_identifier
        );
    EXCEPTION WHEN unique_violation THEN
        INSERT INTO public.operator_audit_events (
            actor_identifier,
            action,
            outcome,
            resource_digest
        ) VALUES (
            p_actor_identifier,
            'TEACHER_INVITATION_CREATED',
            'CONFLICT',
            p_resource_digest
        );
        RETURN 'CONFLICT';
    END;

    INSERT INTO public.operator_audit_events (
        actor_identifier,
        action,
        outcome,
        resource_digest
    ) VALUES (
        p_actor_identifier,
        'TEACHER_INVITATION_CREATED',
        'SUCCEEDED',
        p_resource_digest
    );
    RETURN 'SUCCEEDED';
END;
$$;

CREATE OR REPLACE FUNCTION public.operator_revoke_teacher_invitation(
    p_email_digest VARCHAR(64),
    p_actor_identifier VARCHAR(100),
    p_resource_digest VARCHAR(64)
)
RETURNS VARCHAR(16)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_now TIMESTAMPTZ := transaction_timestamp();
    v_updated INTEGER;
    v_outcome VARCHAR(16);
BEGIN
    IF p_email_digest IS NULL
       OR p_email_digest !~ '^[0-9a-f]{64}$'
       OR p_actor_identifier IS NULL
       OR p_actor_identifier !~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,99}$'
       OR p_resource_digest IS NULL
       OR p_resource_digest !~ '^[0-9a-f]{64}$'
    THEN
        RAISE EXCEPTION 'invalid invitation revoke command' USING ERRCODE = '22023';
    END IF;

    UPDATE public.teacher_invitations
    SET revoked_at = v_now
    WHERE email_digest = p_email_digest
      AND consumed_at IS NULL
      AND revoked_at IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_outcome := CASE WHEN v_updated = 1 THEN 'SUCCEEDED' ELSE 'NOT_FOUND' END;

    INSERT INTO public.operator_audit_events (
        actor_identifier,
        action,
        outcome,
        resource_digest
    ) VALUES (
        p_actor_identifier,
        'TEACHER_INVITATION_REVOKED',
        v_outcome,
        p_resource_digest
    );
    RETURN v_outcome;
END;
$$;

REVOKE ALL ON FUNCTION public.operator_set_account_status(
    VARCHAR,
    BOOLEAN,
    VARCHAR,
    VARCHAR
) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.operator_create_teacher_invitation(
    VARCHAR,
    VARCHAR,
    TIMESTAMPTZ,
    VARCHAR,
    VARCHAR
) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.operator_revoke_teacher_invitation(
    VARCHAR,
    VARCHAR,
    VARCHAR
) FROM PUBLIC;

-- Deliberately no session backfill: signed tokens issued by older application
-- versions are not browser sessions and must stop working after this deployment.

COMMIT;
