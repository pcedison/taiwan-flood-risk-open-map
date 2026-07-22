INSERT INTO data_sources (
    name,
    adapter_key,
    source_type,
    license,
    update_frequency,
    health_status,
    legal_basis,
    is_enabled,
    metadata
)
VALUES
    (
        'CWA tide level observations',
        'official.cwa.tide_level',
        'official',
        'Government Open Data License',
        'near_realtime',
        'unknown',
        'L1',
        true,
        '{
            "operator":"Central Weather Administration",
            "phase":"2",
            "resource_id":"O-B0075-001",
            "station_metadata_resource_id":"O-B0076-001",
            "source_context":"coastal_tide_level",
            "limitations":[
                "coastal tide level is not inland drainage depth",
                "offshore station datum may use local mean sea level"
            ]
        }'::jsonb
    )
ON CONFLICT (adapter_key) DO UPDATE SET
    name = EXCLUDED.name,
    source_type = EXCLUDED.source_type,
    license = EXCLUDED.license,
    update_frequency = EXCLUDED.update_frequency,
    legal_basis = EXCLUDED.legal_basis,
    is_enabled = EXCLUDED.is_enabled,
    metadata = data_sources.metadata || EXCLUDED.metadata,
    updated_at = now();

