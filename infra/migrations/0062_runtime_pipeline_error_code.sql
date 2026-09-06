-- The promotion stage records only runtime_pipeline_status='failed', so a
-- transient local database timeout (QueryCanceled, LockNotAvailable,
-- OperationalError) is indistinguishable from a broken publish step. The public
-- diagnosis then falls back to pipeline_unavailable and Hosted Monitoring pages
-- on a fault that clears itself on the next cycle. Persist the exception class
-- name alongside the pipeline status so the API can classify it the same way it
-- already classifies adapter batch failures (0060 / #360).
--
-- Idempotent, pure DDL, and instant: data_sources holds a few dozen rows and
-- adding a nullable text column rewrites nothing.

ALTER TABLE data_sources
    ADD COLUMN IF NOT EXISTS runtime_pipeline_error_code text;
