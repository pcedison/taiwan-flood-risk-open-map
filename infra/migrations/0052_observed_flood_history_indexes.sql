-- Retained positive flood-depth observations are historical evidence after
-- their realtime window ends. Keep the spatial/time lookup bounded as sensor
-- history grows; these indexes do not change or relabel stored evidence rows.

BEGIN;

CREATE INDEX IF NOT EXISTS idx_evidence_observed_flood_history_geom
    ON evidence USING gist (geom)
    WHERE geom IS NOT NULL
        AND ingestion_status = 'accepted'
        AND privacy_level IN ('public', 'aggregated')
        AND source_type = 'official'
        AND event_type = 'flood_report'
        AND properties->>'evidence_scope' = 'current'
        AND observed_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_evidence_observed_flood_history_time
    ON evidence (observed_at DESC)
    WHERE geom IS NOT NULL
        AND ingestion_status = 'accepted'
        AND privacy_level IN ('public', 'aggregated')
        AND source_type = 'official'
        AND event_type = 'flood_report'
        AND properties->>'evidence_scope' = 'current'
        AND observed_at IS NOT NULL;

COMMIT;
