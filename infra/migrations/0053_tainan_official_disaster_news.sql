-- Register the reviewed citation-only Tainan City disaster-news source used to
-- recover recent official flood incidents when the spatial history near a
-- query point has not been updated for more than one year.

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
VALUES (
    'Tainan City official disaster news',
    'official.tainan.disaster_news',
    'official',
    'Government Open Data License, version 1.0',
    'on_demand_10_minute_cache',
    'unknown',
    'L1',
    true,
    jsonb_build_object(
        'label_zh', '臺南市政府近期積淹水事件',
        'owner_authority', 'Tainan City Government',
        'source_url', 'https://www.tainan.gov.tw/News.aspx?PageSize=200&n=13370&page=1&sms=9748',
        'rss_url', 'https://www.tainan.gov.tw/OpenData.aspx?SN=24474215983F6554',
        'license_name', 'Government Open Data License, version 1.0',
        'license_url', 'https://data.tainan.gov.tw/About?id=7fdb85c9-bf02-4d5a-813a-1988b9724873',
        'citation_required', true,
        'full_text_stored', false,
        'stored_fields', jsonb_build_array('title', 'publication_date', 'url', 'location_match'),
        'evidence_scope', 'historical',
        'scoring_use', 'historical_context',
        'location_precision', 'admin_area_or_road',
        'review_status', 'ready',
        'limitation_zh', '市府新聞可確認近期積淹水事件；行政區命中不代表查詢門牌有實測淹水深度。',
        'kill_switch', 'OFFICIAL_TAINAN_HISTORY_NEWS_ENABLED=false',
        'phase', 'recent_official_history_recovery'
    )
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
