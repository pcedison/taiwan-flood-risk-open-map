CREATE TABLE IF NOT EXISTS worker_scheduler_leases (
    lease_key text PRIMARY KEY,
    holder_id text NOT NULL,
    lease_expires_at timestamptz NOT NULL,
    acquired_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS worker_runtime_jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    queue_name text NOT NULL DEFAULT 'runtime-adapters',
    job_key text NOT NULL,
    adapter_key text,
    status text NOT NULL DEFAULT 'queued' CHECK (
        status IN ('queued', 'running', 'succeeded', 'failed', 'skipped', 'cancelled')
    ),
    priority integer NOT NULL DEFAULT 0,
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    max_attempts integer NOT NULL DEFAULT 3 CHECK (max_attempts > 0),
    run_after timestamptz NOT NULL DEFAULT now(),
    leased_by text,
    lease_expires_at timestamptz,
    started_at timestamptz,
    finished_at timestamptz,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    last_error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at)
);

CREATE INDEX IF NOT EXISTS idx_worker_scheduler_leases_expires_at
    ON worker_scheduler_leases (lease_expires_at);

CREATE INDEX IF NOT EXISTS idx_worker_runtime_jobs_dequeue
    ON worker_runtime_jobs (queue_name, status, run_after, priority DESC, created_at);

CREATE INDEX IF NOT EXISTS idx_worker_runtime_jobs_adapter_key
    ON worker_runtime_jobs (adapter_key);

CREATE INDEX IF NOT EXISTS idx_worker_runtime_jobs_lease_expires_at
    ON worker_runtime_jobs (lease_expires_at)
    WHERE status = 'running';
