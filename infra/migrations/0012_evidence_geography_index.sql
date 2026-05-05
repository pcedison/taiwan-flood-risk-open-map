CREATE INDEX IF NOT EXISTS idx_evidence_geom_geography
    ON evidence USING gist ((geom::geography))
    WHERE geom IS NOT NULL;

