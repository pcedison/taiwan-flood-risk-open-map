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
        'Taoyuan rainfall observations',
        'local.taoyuan.rainfall',
        'official',
        'Government Open Data License',
        'near_realtime',
        'unknown',
        'L3',
        false,
        jsonb_build_object(
            'label_zh', '桃園市水情雨量資料',
            'owner_authority', 'Taoyuan City Water Resources Bureau',
            'license_name', 'Government Open Data License',
            'tier', 'L3',
            'source_url', 'https://opendata.tycg.gov.tw/datalist/eabd93d1-d526-4de0-b378-b529aa61a4be',
            'resource_url', 'https://opendata.tycg.gov.tw/api/dataset/eabd93d1-d526-4de0-b378-b529aa61a4be/resource/6a555cf5-ccc9-4706-9cb6-62c25f23ec4e/download',
            'notes', 'Disabled by default; parses Taoyuan rainfall XML with one feed-level Time value, WGS84 station coordinates, and Rainfall values. The Rainfall accumulation window is not relabeled without official documentation.',
            'review_status', 'ready',
            'phase', 'local_realtime_sources'
        )
    ),
    (
        'Chiayi City rainfall observations',
        'local.chiayi_city.rainfall',
        'official',
        'Government Open Data License',
        'near_realtime',
        'unknown',
        'L3',
        false,
        jsonb_build_object(
            'label_zh', '嘉義市雨量即時資料',
            'owner_authority', 'Chiayi City Government',
            'license_name', 'Government Open Data License',
            'tier', 'L3',
            'source_url', 'https://data.gov.tw/dataset/52585',
            'resource_url', 'https://data.chiayi.gov.tw/opendata/api/getResource?oid=0c766c28-c16e-4eaa-8520-f7ffeee3776b&rid=5ad1cdc5-6a8a-48d4-b6b4-7edb9b384e1a',
            'notes', 'Disabled by default; parses Chiayi City rainfall CSV with 10-minute, 1/3/6/12-hour and inferred 24-hour rainfall windows when the live CSV publishes duplicate 12-hour headers.',
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
