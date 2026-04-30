ALTER TABLE location_queries
    ADD COLUMN IF NOT EXISTS lat numeric(9,6),
    ADD COLUMN IF NOT EXISTS lng numeric(9,6),
    ADD COLUMN IF NOT EXISTS metadata jsonb NOT NULL DEFAULT '{}'::jsonb;

UPDATE location_queries
SET
    lat = COALESCE(lat, ST_Y(geom::geometry)),
    lng = COALESCE(lng, ST_X(geom::geometry))
WHERE geom IS NOT NULL
    AND (lat IS NULL OR lng IS NULL);

ALTER TABLE risk_assessments
    ADD COLUMN IF NOT EXISTS risk_level text NOT NULL DEFAULT 'unknown',
    ADD COLUMN IF NOT EXISTS result_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS metadata jsonb NOT NULL DEFAULT '{}'::jsonb;

UPDATE risk_assessments
SET risk_level = CASE
    WHEN risk_level_realtime = 'severe' OR risk_level_historical = 'severe' THEN 'severe'
    WHEN risk_level_realtime = 'high' OR risk_level_historical = 'high' THEN 'high'
    WHEN risk_level_realtime = 'medium' OR risk_level_historical = 'medium' THEN 'medium'
    WHEN risk_level_realtime = 'low' OR risk_level_historical = 'low' THEN 'low'
    ELSE 'unknown'
END
WHERE risk_level = 'unknown';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'risk_assessments_risk_level_check'
            AND conrelid = 'risk_assessments'::regclass
    ) THEN
        ALTER TABLE risk_assessments
            ADD CONSTRAINT risk_assessments_risk_level_check
            CHECK (risk_level IN ('low', 'medium', 'high', 'severe', 'unknown'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_location_queries_created_at
    ON location_queries (created_at);

CREATE INDEX IF NOT EXISTS idx_location_queries_lat_lng
    ON location_queries (lat, lng);

CREATE INDEX IF NOT EXISTS idx_risk_assessments_risk_level
    ON risk_assessments (risk_level);

CREATE INDEX IF NOT EXISTS idx_risk_assessments_created_at
    ON risk_assessments (created_at);

CREATE INDEX IF NOT EXISTS idx_risk_assessments_query_created_at
    ON risk_assessments (query_id, created_at);
