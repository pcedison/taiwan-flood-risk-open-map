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
        'Chiayi City water level observations',
        'local.chiayi_city.water_level',
        'official',
        'Government Open Data License',
        'near_realtime',
        'unknown',
        'L3',
        false,
        jsonb_build_object(
            'label_zh', '嘉義市水位站水位',
            'owner_authority', 'Chiayi City Government',
            'license_name', 'Government Open Data License',
            'tier', 'L3',
            'source_url', 'https://data.gov.tw/dataset/52584',
            'resource_url', 'https://data.chiayi.gov.tw/opendata/api/getResource?oid=df063695-0076-4dd6-9237-39c5f8ae6b4a&rid=d4c7da5c-b08f-4fd1-97c0-913c949c4613',
            'notes', 'Disabled by default; parses Chiayi City water-level CSV and preserves first/second warning thresholds.',
            'review_status', 'ready',
            'phase', 'local_realtime_sources'
        )
    ),
    (
        'Taichung water level observations',
        'local.taichung.water_level',
        'official',
        'Government Open Data License',
        'near_realtime',
        'unknown',
        'L3',
        false,
        jsonb_build_object(
            'label_zh', '臺中市水位站水情',
            'owner_authority', 'Taichung City Water Resources Bureau',
            'license_name', 'Government Open Data License',
            'tier', 'L3',
            'source_url', 'https://opendata.taichung.gov.tw/',
            'resource_url', 'https://wrbeocin.taichung.gov.tw/TCSAFE/UploadFile/WATERLEVEL/WATERLEVEL_NEW.JSON',
            'notes', 'Disabled by default; uses the official live Water Resources Bureau JSON URL and rejects stale station rows.',
            'review_status', 'ready',
            'phase', 'local_realtime_sources'
        )
    )
ON CONFLICT (adapter_key) DO UPDATE SET
    name = EXCLUDED.name,
    source_type = EXCLUDED.source_type,
    license = EXCLUDED.license,
    update_frequency = EXCLUDED.update_frequency,
    health_status = EXCLUDED.health_status,
    legal_basis = EXCLUDED.legal_basis,
    is_enabled = EXCLUDED.is_enabled,
    metadata = data_sources.metadata || EXCLUDED.metadata,
    updated_at = now();
