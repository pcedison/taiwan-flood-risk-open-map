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
        'New Taipei local water level observations',
        'local.new_taipei.water_level',
        'official',
        'Official public endpoint',
        'near_realtime',
        'unknown',
        'L3',
        false,
        jsonb_build_object(
            'label_zh', '新北市水位站',
            'owner_authority', 'New Taipei City Government',
            'license_name', 'Official public endpoint',
            'tier', 'L3',
            'source_url', 'https://newtaipei.wavegis.com.tw/',
            'resource_url', 'https://newtaipei.wavegis.com.tw/api/javaapi/water_extra_api/flood/getFloodListData?fields=ascent_rate&filter_ps=true&org_data=ALL&org_id=110&source=ALL&strata=0&type=radar%2Cwater%2CWT_RR_W%2CWG_RR_W&unit=1',
            'notes', 'Disabled by default; reads New Taipei WaveGIS water-level rows and rejects stale or future observations.',
            'review_status', 'ready',
            'phase', 'local_realtime_sources'
        )
    ),
    (
        'New Taipei local flood sensor observations',
        'local.new_taipei.flood_sensor',
        'official',
        'Official public endpoint',
        'near_realtime',
        'unknown',
        'L3',
        false,
        jsonb_build_object(
            'label_zh', '新北市淹水感測器',
            'owner_authority', 'New Taipei City Government',
            'license_name', 'Official public endpoint',
            'tier', 'L3',
            'source_url', 'https://newtaipei.wavegis.com.tw/',
            'resource_url', 'https://newtaipei.wavegis.com.tw/api/javaapi/water_extra_api/flood/getFloodListData?fields=ascent_rate&filter_ps=true&org_data=ALL&org_id=110&source=ALL&strata=0&type=flood&unit=1',
            'notes', 'Disabled by default; interprets type=flood water_inner as flood depth in centimeters.',
            'review_status', 'ready',
            'phase', 'local_realtime_sources'
        )
    ),
    (
        'New Taipei local rainfall observations',
        'local.new_taipei.rainfall',
        'official',
        'Official public endpoint',
        'near_realtime',
        'unknown',
        'L3',
        false,
        jsonb_build_object(
            'label_zh', '新北市雨量站',
            'owner_authority', 'New Taipei City Government',
            'license_name', 'Official public endpoint',
            'tier', 'L3',
            'source_url', 'https://newtaipei.wavegis.com.tw/',
            'resource_url', 'https://newtaipei.wavegis.com.tw/api/javaapi/water_extra_api/rain/getRainFallBaseData?org_id=110&org_data=ALL',
            'notes', 'Disabled by default; preserves rain, min_10, min_30, hour_3, hour_6, hour_12, and hour_24 rainfall windows.',
            'review_status', 'ready',
            'phase', 'local_realtime_sources'
        )
    ),
    (
        'New Taipei local drainage water level observations',
        'local.new_taipei.drainage_water_level',
        'official',
        'Official public endpoint',
        'near_realtime',
        'unknown',
        'L3',
        false,
        jsonb_build_object(
            'label_zh', '新北市排水水位站',
            'owner_authority', 'New Taipei City Government',
            'license_name', 'Official public endpoint',
            'tier', 'L3',
            'source_url', 'https://newtaipei.wavegis.com.tw/',
            'resource_url', 'https://newtaipei.wavegis.com.tw/api/javaapi/water_extra_api/water/getDrainage?org_id=110&org_data=ALL',
            'notes', 'Disabled by default; drainage and sewer water-level observations provide infrastructure context and are not standalone flood warnings.',
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
