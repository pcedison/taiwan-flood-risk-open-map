ALTER TABLE user_reports
    ADD COLUMN IF NOT EXISTS redacted_at timestamptz;

ALTER TABLE user_reports
    ADD COLUMN IF NOT EXISTS redaction_reason text;

ALTER TABLE user_reports
    DROP CONSTRAINT IF EXISTS user_reports_status_check;

ALTER TABLE user_reports
    ADD CONSTRAINT user_reports_status_check CHECK (
        status IN ('pending', 'approved', 'rejected', 'spam', 'deleted')
    );

ALTER TABLE user_reports
    DROP CONSTRAINT IF EXISTS user_reports_redaction_reason_check;

ALTER TABLE user_reports
    ADD CONSTRAINT user_reports_redaction_reason_check CHECK (
        redaction_reason IS NULL
        OR redaction_reason IN (
            'reporter_request',
            'affected_person_request',
            'private_data_exposure',
            'retention_expiry',
            'operator_error'
        )
    );

CREATE INDEX IF NOT EXISTS idx_user_reports_redacted_at
    ON user_reports (redacted_at);
