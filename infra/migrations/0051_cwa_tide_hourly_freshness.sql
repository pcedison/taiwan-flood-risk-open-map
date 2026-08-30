-- The CWA O-B0075-001 tide observations publish hourly. Public evidence
-- coverage reads this per-source threshold from metadata; without it the
-- repository falls back to ten minutes and hides valid observations between
-- scheduled publications.

BEGIN;

UPDATE data_sources
SET update_frequency = 'hourly',
    metadata = jsonb_set(
        COALESCE(metadata, '{}'::jsonb),
        '{freshness_threshold_seconds}',
        to_jsonb(5400),
        true
    ),
    updated_at = now()
WHERE adapter_key = 'official.cwa.tide_level';

COMMIT;
