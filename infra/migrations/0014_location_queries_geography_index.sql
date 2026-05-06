CREATE INDEX IF NOT EXISTS idx_location_queries_geom_geography
    ON location_queries USING gist ((geom::geography))
    WHERE geom IS NOT NULL;
