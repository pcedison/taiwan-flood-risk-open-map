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
        'CWA rainfall observations',
        'official.cwa.rainfall',
        'official',
        'Government Open Data License',
        'near_realtime',
        'unknown',
        'L1',
        true,
        '{"operator":"Central Weather Administration","phase":"2"}'::jsonb
    ),
    (
        'WRA water level observations',
        'official.wra.water_level',
        'official',
        'Government Open Data License',
        'near_realtime',
        'unknown',
        'L1',
        true,
        '{"operator":"Water Resources Agency","phase":"2"}'::jsonb
    ),
    (
        'Flood potential GeoJSON',
        'official.flood_potential.geojson',
        'official',
        'Government Open Data License',
        'periodic',
        'unknown',
        'L1',
        true,
        '{"operator":"Official flood potential dataset","phase":"2"}'::jsonb
    ),
    (
        'Sample public web fixture',
        'news.public_web.sample',
        'news',
        'Citation only; no full-text redistribution',
        'fixture_only',
        'unknown',
        'L2',
        false,
        '{"allowlist_key":"sample-public-web","citation_required":true,"full_text_redistribution":false,"phase":"2","status":"fixture_only"}'::jsonb
    ),
    (
        'Production L2 news source template',
        'news.public_web.production-template',
        'news',
        'Citation only; no full-text redistribution',
        'pending_review',
        'unknown',
        'L2',
        false,
        '{"allowlist_key":"production-news-template","citation_required":true,"full_text_redistribution":false,"phase":"2","status":"candidate"}'::jsonb
    ),
    (
        'GDELT DOC public-news backfill candidate',
        'news.public_web.gdelt_backfill',
        'news',
        'Citation only; no full-text redistribution',
        'backfill_then_daily',
        'unknown',
        'L2',
        false,
        '{"allowlist_key":"gdelt-backfill-candidate","citation_required":true,"full_text_redistribution":false,"phase":"2","status":"candidate"}'::jsonb
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
