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
        'Penghu local water level observations',
        'local.penghu.water_level',
        'official',
        'Official public endpoint',
        'near_realtime',
        'unknown',
        'L3',
        false,
        jsonb_build_object(
            'label_zh', '澎湖縣智慧水位計',
            'owner_authority', 'Penghu County Government',
            'license_name', 'Official public endpoint',
            'tier', 'L3',
            'source_url', 'https://ph3dgis.penghu.gov.tw/',
            'resource_url', 'https://ph3dgis.penghu.gov.tw/server/rest/services/SewerNew/PHSewer_Basemap/MapServer/6/query?where=1%3D1&outFields=*&f=json&returnGeometry=true&outSR=4326',
            'notes', 'Disabled by default; reads Penghu ArcGIS REST layer 6 water-level rows. water_level is millimeters and measure_time/upload_time are corrected from Taiwan wall-clock epoch encoding before freshness checks.',
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
