CREATE TABLE IF NOT EXISTS geocoder_open_data_entries (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_key text NOT NULL,
    source_record_id text,
    name text NOT NULL,
    aliases text[] NOT NULL DEFAULT '{}'::text[],
    normalized_aliases text[] NOT NULL DEFAULT '{}'::text[],
    admin_code text,
    precision text NOT NULL CHECK (
        precision IN ('exact_address', 'road_or_lane', 'poi', 'admin_area', 'map_click', 'unknown')
    ),
    place_type text NOT NULL CHECK (
        place_type IN ('address', 'parcel', 'landmark', 'admin_area', 'poi')
    ),
    geom geometry(Geometry, 4326) NOT NULL,
    centroid geometry(Point, 4326) NOT NULL,
    confidence numeric(6,3) CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    source_url text,
    license text,
    attribution text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    imported_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (cardinality(normalized_aliases) > 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_geocoder_open_data_entries_source_record
    ON geocoder_open_data_entries (source_key, source_record_id)
    WHERE source_record_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_geocoder_open_data_entries_source_key
    ON geocoder_open_data_entries (source_key);

CREATE INDEX IF NOT EXISTS idx_geocoder_open_data_entries_admin_code
    ON geocoder_open_data_entries (admin_code)
    WHERE admin_code IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_geocoder_open_data_entries_precision
    ON geocoder_open_data_entries (precision, place_type);

CREATE INDEX IF NOT EXISTS idx_geocoder_open_data_entries_aliases_gin
    ON geocoder_open_data_entries USING gin (aliases);

CREATE INDEX IF NOT EXISTS idx_geocoder_open_data_entries_normalized_aliases_gin
    ON geocoder_open_data_entries USING gin (normalized_aliases);

CREATE INDEX IF NOT EXISTS idx_geocoder_open_data_entries_geom_gist
    ON geocoder_open_data_entries USING gist (geom);

CREATE INDEX IF NOT EXISTS idx_geocoder_open_data_entries_centroid_gist
    ON geocoder_open_data_entries USING gist (centroid);
