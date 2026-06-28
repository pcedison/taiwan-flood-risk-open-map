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
        'Hsinchu City sewer water level observations',
        'local.hsinchu_city.sewer_water_level',
        'official',
        'Government Open Data License',
        'near_realtime',
        'unknown',
        'L3',
        false,
        jsonb_build_object(
            'label_zh', '新竹市雨水下水道水位',
            'owner_authority', 'Hsinchu City Government',
            'license_name', 'Government Open Data License',
            'tier', 'L3',
            'source_url', 'https://swc.hccg.gov.tw/',
            'resource_url', 'https://swc.hccg.gov.tw/api/map/sewer/rt',
            'metadata_url', 'https://swc.hccg.gov.tw/api/map/sewer/base',
            'notes', 'Disabled by default; joins public sewer base station metadata to realtime Dev_UUID water-depth rows.',
            'review_status', 'ready',
            'phase', 'local_realtime_sources'
        )
    ),
    (
        'Hsinchu City flood sensor observations',
        'local.hsinchu_city.flood_sensor',
        'official',
        'Government Open Data License',
        'near_realtime',
        'unknown',
        'L3',
        false,
        jsonb_build_object(
            'label_zh', '新竹市淹水感測器',
            'owner_authority', 'Hsinchu City Government / FHY Broker',
            'license_name', 'Government Open Data License',
            'tier', 'L3',
            'source_url', 'https://www.dprcflood.org.tw/SGDS/',
            'resource_url', 'https://www.dprcflood.org.tw/SGDS/WS/FHYBrokerWS.asmx/GetFHYFloodSensorInfoRt',
            'metadata_url', 'https://www.dprcflood.org.tw/SGDS/WS/FHYBrokerWS.asmx/GetFHYFloodSensorStationByCityCode',
            'notes', 'Disabled by default; filters station metadata to CityCode 10018 before joining realtime flood-depth rows.',
            'review_status', 'ready',
            'phase', 'local_realtime_sources'
        )
    ),
    (
        'Nantou sewer water level observations',
        'local.nantou.sewer_water_level',
        'official',
        'Government Open Data License',
        'near_realtime',
        'unknown',
        'L3',
        false,
        jsonb_build_object(
            'label_zh', '南投縣雨水下水道水位',
            'owner_authority', 'Nantou County Government',
            'license_name', 'Government Open Data License',
            'tier', 'L3',
            'source_url', 'https://dpinfo.nantou.gov.tw/',
            'resource_url', 'https://dpinfo.nantou.gov.tw/Api/Proxy/GetKML',
            'notes', 'Disabled by default; parses KML Placemark descriptions containing embedded JSON water-level and hourly rainfall metrics.',
            'review_status', 'ready',
            'phase', 'local_realtime_sources'
        )
    ),
    (
        'Chiayi County flood sensor observations',
        'local.chiayi_county.flood_sensor',
        'official',
        'Government Open Data License',
        'near_realtime',
        'unknown',
        'L3',
        false,
        jsonb_build_object(
            'label_zh', '嘉義縣淹水感測器',
            'owner_authority', 'Chiayi County Government Water Resources Department',
            'license_name', 'Government Open Data License',
            'tier', 'L3',
            'source_url', 'https://www.cyhg.gov.tw/News_Content.aspx?n=16&s=249470',
            'resource_url', 'https://api.floodsolution.aiot.ing/api/public/devices/RFD',
            'notes', 'Disabled by default; reads the public RFD device endpoint and rejects rows without latest time, coordinates, or waterDepth.',
            'review_status', 'ready',
            'phase', 'local_realtime_sources'
        )
    ),
    (
        'Kaohsiung sewer water level observations',
        'local.kaohsiung.sewer_water_level',
        'official',
        'Government Open Data License',
        'near_realtime',
        'unknown',
        'L3',
        false,
        jsonb_build_object(
            'label_zh', '高雄市雨水下水道水位',
            'owner_authority', 'Kaohsiung City Water Resources Bureau',
            'license_name', 'Government Open Data License',
            'tier', 'L3',
            'source_url', 'https://wrb.kcg.gov.tw/WRInfo/',
            'resource_url', 'https://wrbswi.kcg.gov.tw/SFC/api/sewer/rt',
            'notes', 'Disabled by default; interprets the local time field as Asia/Taipei and preserves warning thresholds.',
            'review_status', 'ready',
            'phase', 'local_realtime_sources'
        )
    ),
    (
        'Kaohsiung flood sensor observations',
        'local.kaohsiung.flood_sensor',
        'official',
        'Government Open Data License',
        'near_realtime',
        'unknown',
        'L3',
        false,
        jsonb_build_object(
            'label_zh', '高雄市淹水感測器',
            'owner_authority', 'Kaohsiung City Water Resources Bureau',
            'license_name', 'Government Open Data License',
            'tier', 'L3',
            'source_url', 'https://wrb.kcg.gov.tw/WRInfo/',
            'resource_url', 'https://wrbswi.kcg.gov.tw/SFC/api/khfloodinfo/sta_info/lastest/wrs_flooding_sensor',
            'notes', 'Disabled by default; parses SFC flood sensor latest rows with WGS84 points and per-station local observation time.',
            'review_status', 'ready',
            'phase', 'local_realtime_sources'
        )
    ),
    (
        'Yilan flood sensor observations',
        'local.yilan.flood_sensor',
        'official',
        'Government Open Data License',
        'near_realtime',
        'unknown',
        'L3',
        false,
        jsonb_build_object(
            'label_zh', '宜蘭縣淹水感測器',
            'owner_authority', 'Yilan County Government',
            'license_name', 'Government Open Data License',
            'tier', 'L3',
            'source_url', 'https://wra.e-land.gov.tw/IlanHsdsMap/',
            'resource_url', 'https://wragis.e-land.gov.tw/arcgis/rest/services/HDST/%E9%98%B2%E6%B1%9B%E5%84%80%E8%A1%A8%E6%9D%BF/MapServer/0/query?where=1%3D1&outFields=*&f=json',
            'notes', 'Disabled by default; reads ArcGIS layer 0 and interprets water_inner as flood depth in centimeters.',
            'review_status', 'ready',
            'phase', 'local_realtime_sources'
        )
    ),
    (
        'Yilan water level observations',
        'local.yilan.water_level',
        'official',
        'Government Open Data License',
        'near_realtime',
        'unknown',
        'L3',
        false,
        jsonb_build_object(
            'label_zh', '宜蘭縣水位計',
            'owner_authority', 'Yilan County Government',
            'license_name', 'Government Open Data License',
            'tier', 'L3',
            'source_url', 'https://wra.e-land.gov.tw/IlanHsdsMap/',
            'resource_url', 'https://wragis.e-land.gov.tw/arcgis/rest/services/HDST/%E9%98%B2%E6%B1%9B%E5%84%80%E8%A1%A8%E6%9D%BF/MapServer/2/query?where=1%3D1&outFields=*&f=json',
            'notes', 'Disabled by default; reads ArcGIS layer 2 and interprets water_inner as water level in meters.',
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
