CREATE TABLE IF NOT EXISTS map_layer_features (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    layer_id text NOT NULL REFERENCES map_layers(layer_id) ON DELETE CASCADE,
    feature_key text,
    source_ref text,
    geom geometry(Geometry, 4326) NOT NULL,
    minzoom integer CHECK (minzoom IS NULL OR (minzoom >= 0 AND minzoom <= 24)),
    maxzoom integer CHECK (maxzoom IS NULL OR (maxzoom >= 0 AND maxzoom <= 24)),
    properties jsonb NOT NULL DEFAULT '{}'::jsonb,
    generated_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    CHECK (minzoom IS NULL OR maxzoom IS NULL OR minzoom <= maxzoom),
    CHECK (expires_at IS NULL OR expires_at > generated_at),
    UNIQUE (layer_id, feature_key)
);

CREATE TABLE IF NOT EXISTS tile_cache_entries (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    layer_id text NOT NULL REFERENCES map_layers(layer_id) ON DELETE CASCADE,
    z integer NOT NULL CHECK (z >= 0 AND z <= 24),
    x integer NOT NULL CHECK (x >= 0),
    y integer NOT NULL CHECK (y >= 0),
    tile_data bytea NOT NULL,
    content_hash text,
    generated_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    CHECK (expires_at IS NULL OR expires_at > generated_at),
    UNIQUE (layer_id, z, x, y)
);

CREATE INDEX IF NOT EXISTS idx_map_layer_features_layer_id
    ON map_layer_features (layer_id);

CREATE INDEX IF NOT EXISTS idx_map_layer_features_geom
    ON map_layer_features USING gist (geom);

CREATE INDEX IF NOT EXISTS idx_map_layer_features_layer_zoom
    ON map_layer_features (layer_id, minzoom, maxzoom);

CREATE INDEX IF NOT EXISTS idx_map_layer_features_expires_at
    ON map_layer_features (expires_at);

CREATE INDEX IF NOT EXISTS idx_tile_cache_entries_lookup
    ON tile_cache_entries (layer_id, z, x, y);

CREATE INDEX IF NOT EXISTS idx_tile_cache_entries_expires_at
    ON tile_cache_entries (expires_at);
