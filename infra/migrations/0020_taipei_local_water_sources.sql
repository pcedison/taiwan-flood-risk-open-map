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
        'Taipei storm sewer water level observations',
        'local.taipei.sewer_water_level',
        'official',
        'Government Open Data License',
        'near_realtime',
        'unknown',
        'L3',
        false,
        jsonb_build_object(
            'label_zh', '臺北市雨水下水道水位即時資料',
            'owner_authority', 'Taipei City Hydraulic Engineering Office',
            'license_name', 'Government Open Data License',
            'tier', 'L3',
            'source_url', 'https://data.taipei/dataset/detail?id=cd444840-bbfb-4b0a-bdfa-2a36d49b3794',
            'metadata_source_url', 'https://data.gov.tw/dataset/121643',
            'notes', 'Disabled by default; joins realtime sewer water levels with station coordinates from Taipei dataset 121643.',
            'review_status', 'ready',
            'phase', 'local_realtime_sources'
        )
    ),
    (
        'Taipei river water level observations',
        'local.taipei.river_water_level',
        'official',
        'Government Open Data License',
        'near_realtime',
        'unknown',
        'L3',
        false,
        jsonb_build_object(
            'label_zh', '臺北市河川水位即時資料',
            'owner_authority', 'Taipei City Hydraulic Engineering Office',
            'license_name', 'Government Open Data License',
            'tier', 'L3',
            'source_url', 'https://data.taipei/dataset/detail?id=5b4b8ae1-9505-4a1a-8808-feea14e78130',
            'metadata_source_url', 'https://data.gov.tw/dataset/138171',
            'notes', 'Disabled by default; joins realtime river water levels with station coordinates from Taipei dataset 138171 and rejects stale station rows.',
            'review_status', 'ready',
            'phase', 'local_realtime_sources'
        )
    ),
    (
        'Taipei pump station status observations',
        'local.taipei.pump_station',
        'official',
        'Government Open Data License',
        'near_realtime',
        'unknown',
        'L3',
        false,
        jsonb_build_object(
            'label_zh', '臺北市抽水站運轉狀態',
            'owner_authority', 'Taipei City Hydraulic Engineering Office',
            'license_name', 'Government Open Data License',
            'tier', 'L3',
            'source_url', 'https://data.taipei/dataset/detail?id=2bbfb30e-de58-43bd-9cc9-b56e9a6b5369',
            'notes', 'Disabled by default; uses embedded WGS84 coordinates and outer water level as the flood-relevant metric.',
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
