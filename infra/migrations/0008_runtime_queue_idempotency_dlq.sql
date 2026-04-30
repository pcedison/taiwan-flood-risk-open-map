ALTER TABLE worker_runtime_jobs
    ADD COLUMN IF NOT EXISTS dedupe_key text;

ALTER TABLE worker_runtime_jobs
    ADD COLUMN IF NOT EXISTS final_failed_at timestamptz;

CREATE UNIQUE INDEX IF NOT EXISTS idx_worker_runtime_jobs_active_dedupe
    ON worker_runtime_jobs (
        queue_name,
        job_key,
        (COALESCE(adapter_key, ''::text)),
        dedupe_key
    )
    WHERE status IN ('queued', 'running')
        AND dedupe_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_worker_runtime_jobs_dead_letter
    ON worker_runtime_jobs (queue_name, final_failed_at DESC, updated_at DESC)
    WHERE status = 'failed'
        AND attempts >= max_attempts;
