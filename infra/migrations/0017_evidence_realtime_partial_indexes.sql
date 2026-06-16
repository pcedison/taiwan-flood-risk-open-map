CREATE INDEX IF NOT EXISTS idx_evidence_nearby_non_realtime_geom
    ON evidence USING gist (geom)
    WHERE geom IS NOT NULL
        AND ingestion_status = 'accepted'
        AND privacy_level IN ('public', 'aggregated')
        AND NOT (
            source_type = 'official'
            AND event_type IN ('rainfall', 'water_level')
        );

CREATE INDEX IF NOT EXISTS idx_evidence_official_rainfall_geom
    ON evidence USING gist (geom)
    WHERE geom IS NOT NULL
        AND ingestion_status = 'accepted'
        AND privacy_level IN ('public', 'aggregated')
        AND source_type = 'official'
        AND event_type = 'rainfall';

CREATE INDEX IF NOT EXISTS idx_evidence_official_water_level_geom
    ON evidence USING gist (geom)
    WHERE geom IS NOT NULL
        AND ingestion_status = 'accepted'
        AND privacy_level IN ('public', 'aggregated')
        AND source_type = 'official'
        AND event_type = 'water_level';

CREATE INDEX IF NOT EXISTS idx_evidence_official_rainfall_observed_at
    ON evidence (observed_at DESC)
    WHERE geom IS NOT NULL
        AND ingestion_status = 'accepted'
        AND privacy_level IN ('public', 'aggregated')
        AND source_type = 'official'
        AND event_type = 'rainfall';

CREATE INDEX IF NOT EXISTS idx_evidence_official_water_level_observed_at
    ON evidence (observed_at DESC)
    WHERE geom IS NOT NULL
        AND ingestion_status = 'accepted'
        AND privacy_level IN ('public', 'aggregated')
        AND source_type = 'official'
        AND event_type = 'water_level';
