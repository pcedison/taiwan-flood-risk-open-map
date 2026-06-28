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
        'Taoyuan flood sensor observations',
        'local.taoyuan.flood_sensor',
        'official',
        'Government Open Data License',
        'near_realtime',
        'unknown',
        'L3',
        false,
        jsonb_build_object(
            'label_zh', '桃園市路面淹水感測',
            'owner_authority', 'Taoyuan City Water Resources Bureau',
            'license_name', 'Government Open Data License',
            'tier', 'L3',
            'source_url', 'https://opendata.tycg.gov.tw/datalist/414be64a-c861-4c08-a94f-96fd7884fdbb',
            'resource_url', 'https://winfo.tycg.gov.tw/Transfer/UploadFile/WATERFLOOD.xml',
            'notes', 'Disabled by default; parses Taoyuan WATERFLOOD.xml with WGS84 coordinates and Chinese AM/PM timestamps.',
            'review_status', 'ready',
            'phase', 'local_realtime_sources'
        )
    ),
    (
        'Taoyuan water level observations',
        'local.taoyuan.water_level',
        'official',
        'Government Open Data License',
        'near_realtime',
        'unknown',
        'L3',
        false,
        jsonb_build_object(
            'label_zh', '桃園市水位站水情',
            'owner_authority', 'Taoyuan City Water Resources Bureau',
            'license_name', 'Government Open Data License',
            'tier', 'L3',
            'source_url', 'https://opendata.tycg.gov.tw/datalist/e3b34ba5-e8ff-4b21-b7a3-4b6f3bfed650',
            'resource_url', 'https://winfo.tycg.gov.tw/Transfer/UploadFile/WATERLEVEL.xml',
            'notes', 'Disabled by default; preserves water level plus yellow/red alert thresholds from Taoyuan WATERLEVEL.xml.',
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
