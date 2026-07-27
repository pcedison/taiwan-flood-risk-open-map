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
        'Yilan mobile pump status observations',
        'local.yilan.mobile_pump_status',
        'official',
        'Government Open Data License',
        'near_realtime',
        'unknown',
        'L3',
        false,
        jsonb_build_object(
            'label_zh', '宜蘭縣移動式抽水機狀態',
            'owner_authority', 'Yilan County Government',
            'license_name', 'Government Open Data License',
            'tier', 'L3',
            'source_url', 'https://wra.e-land.gov.tw/IlanHsdsMap/',
            'resource_url', 'https://wragis.e-land.gov.tw/arcgis/rest/services/HDST/%E9%98%B2%E6%B1%9B%E5%84%80%E8%A1%A8%E6%9D%BF/MapServer/1/query?where=1%3D1&outFields=*&f=json&returnGeometry=true&outSR=4326',
            'notes', 'Disabled by default; reads ArcGIS layer 1 status-only mobile-pump rows. LogDate is corrected from Taiwan wall-clock epoch encoding before normalization.',
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

INSERT INTO realtime_source_jurisdictions (
    adapter_key,
    signal_type,
    coverage_scope,
    jurisdiction_code,
    requirement_role,
    mapping_revision
)
VALUES
    (
        'local.yilan.mobile_pump_status',
        'pump_or_gate_status',
        'local',
        '10002000',
        'required',
        '2026-07-22-v1'
    )
ON CONFLICT (adapter_key, signal_type, jurisdiction_code) DO UPDATE SET
    coverage_scope = EXCLUDED.coverage_scope,
    requirement_role = EXCLUDED.requirement_role,
    mapping_revision = EXCLUDED.mapping_revision;
