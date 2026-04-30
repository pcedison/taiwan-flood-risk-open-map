INSERT INTO map_layers (
    layer_id,
    name,
    description,
    category,
    status,
    minzoom,
    maxzoom,
    attribution,
    tilejson_url,
    updated_at,
    metadata
)
VALUES
    (
        'flood-potential',
        'Flood potential',
        'Official flood potential layer placeholder. Tile generation is not enabled locally yet.',
        'flood_potential',
        'disabled',
        8,
        18,
        'Government open data',
        '/v1/layers/flood-potential/tilejson',
        now(),
        '{
            "tilejson": "3.0.0",
            "version": "placeholder-2026-04-30",
            "scheme": "xyz",
            "tiles": [
                "https://tiles.placeholder.flood-risk.local/flood-potential/{z}/{x}/{y}.pbf"
            ],
            "bounds": [119.3, 21.8, 122.1, 25.4],
            "vector_layers": [
                {
                    "id": "flood_potential",
                    "fields": {
                        "source_id": "String",
                        "category": "String"
                    }
                }
            ]
        }'::jsonb
    ),
    (
        'query-heat',
        'Query heat',
        'Privacy-preserving query heat placeholder. Tile generation is not enabled locally yet.',
        'query_heat',
        'disabled',
        8,
        14,
        'Flood Risk aggregated analytics',
        '/v1/layers/query-heat/tilejson',
        now(),
        '{
            "tilejson": "3.0.0",
            "version": "placeholder-2026-04-30",
            "scheme": "xyz",
            "tiles": [
                "https://tiles.placeholder.flood-risk.local/query-heat/{z}/{x}/{y}.pbf"
            ],
            "bounds": [119.3, 21.8, 122.1, 25.4],
            "vector_layers": [
                {
                    "id": "query_heat",
                    "fields": {
                        "query_count_bucket": "String",
                        "period": "String"
                    }
                }
            ]
        }'::jsonb
    )
ON CONFLICT (layer_id) DO UPDATE SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    category = EXCLUDED.category,
    status = EXCLUDED.status,
    minzoom = EXCLUDED.minzoom,
    maxzoom = EXCLUDED.maxzoom,
    attribution = EXCLUDED.attribution,
    tilejson_url = EXCLUDED.tilejson_url,
    updated_at = now(),
    metadata = EXCLUDED.metadata;
