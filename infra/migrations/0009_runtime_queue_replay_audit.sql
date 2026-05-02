CREATE TABLE IF NOT EXISTS worker_runtime_queue_replay_audit (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id uuid NOT NULL REFERENCES worker_runtime_jobs(id) ON DELETE RESTRICT,
    action text NOT NULL CHECK (
        action IN ('replay', 'poison_quarantine', 'poison_release')
    ),
    requested_by text NOT NULL,
    reason text,
    status text NOT NULL CHECK (status IN ('requested', 'completed', 'failed')),
    attempts_before integer CHECK (attempts_before IS NULL OR attempts_before >= 0),
    attempts_after integer CHECK (attempts_after IS NULL OR attempts_after >= 0),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    requested_at timestamptz,
    completed_at timestamptz,
    failed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (
        (
            status = 'requested'
            AND requested_at IS NOT NULL
            AND completed_at IS NULL
            AND failed_at IS NULL
        )
        OR (
            status = 'completed'
            AND requested_at IS NULL
            AND completed_at IS NOT NULL
            AND failed_at IS NULL
        )
        OR (
            status = 'failed'
            AND requested_at IS NULL
            AND completed_at IS NULL
            AND failed_at IS NOT NULL
        )
    )
);

COMMENT ON TABLE worker_runtime_queue_replay_audit IS
    'Append-only audit primitive for runtime queue replay intent and outcomes; it does not implement automatic replay policy or mutate worker_runtime_jobs.';

COMMENT ON COLUMN worker_runtime_queue_replay_audit.metadata IS
    'Operator/runtime context for audit review; helpers serialize this as JSON and do not use it to drive replay behavior.';

CREATE INDEX IF NOT EXISTS idx_worker_runtime_queue_replay_audit_job
    ON worker_runtime_queue_replay_audit (job_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_worker_runtime_queue_replay_audit_status
    ON worker_runtime_queue_replay_audit (status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_worker_runtime_queue_replay_audit_action_status
    ON worker_runtime_queue_replay_audit (action, status, created_at DESC);

CREATE TABLE IF NOT EXISTS worker_runtime_queue_poison_quarantine (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id uuid NOT NULL REFERENCES worker_runtime_jobs(id) ON DELETE RESTRICT,
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'released')),
    quarantined_by text NOT NULL,
    reason text NOT NULL,
    attempts_at_quarantine integer CHECK (
        attempts_at_quarantine IS NULL OR attempts_at_quarantine >= 0
    ),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    quarantined_at timestamptz NOT NULL DEFAULT now(),
    released_by text,
    released_reason text,
    released_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (
        (status = 'active' AND released_at IS NULL)
        OR (status = 'released' AND released_at IS NOT NULL)
    )
);

COMMENT ON TABLE worker_runtime_queue_poison_quarantine IS
    'Conservative poison-job boundary primitive; records quarantine state only and does not cancel, replay, or otherwise mutate worker_runtime_jobs.';

CREATE UNIQUE INDEX IF NOT EXISTS idx_worker_runtime_queue_poison_quarantine_active_job
    ON worker_runtime_queue_poison_quarantine (job_id)
    WHERE status = 'active'
        AND released_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_worker_runtime_queue_poison_quarantine_status
    ON worker_runtime_queue_poison_quarantine (status, quarantined_at DESC);
