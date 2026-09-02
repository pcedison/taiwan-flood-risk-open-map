-- Expand the public audit window to the requested 15 calendar years and keep
-- rolling NSTC snapshots as historical revisions. A new five-year source
-- snapshot must not make previously published years disappear.
ALTER TABLE historical_coverage_source_checks
    DROP CONSTRAINT IF EXISTS historical_coverage_source_checks_coverage_year_check;

ALTER TABLE historical_coverage_cells
    DROP CONSTRAINT IF EXISTS historical_coverage_cells_coverage_year_check;

ALTER TABLE historical_coverage_cells
    ADD CONSTRAINT historical_coverage_cells_coverage_year_check
    CHECK (coverage_year BETWEEN 2012 AND 2100);

ALTER TABLE historical_coverage_source_checks
    ADD CONSTRAINT historical_coverage_source_checks_coverage_year_check
    CHECK (coverage_year BETWEEN 2012 AND 2100);

INSERT INTO historical_coverage_cells (
    jurisdiction_code,
    coverage_year
)
SELECT
    jurisdiction.jurisdiction_code,
    year_window.coverage_year
FROM realtime_jurisdictions AS jurisdiction
CROSS JOIN generate_series(2012, 2026) AS year_window(coverage_year)
ON CONFLICT (jurisdiction_code, coverage_year) DO NOTHING;

UPDATE data_sources
SET
    update_frequency = 'irregular rolling recent-years snapshot; retained by revision; worker checks daily',
    metadata = (
        metadata
        - 'snapshot_generation_mode'
        - 'active_snapshot_raw_ref'
    ) || jsonb_build_object(
        'snapshot_retention_mode', 'append_historical_revisions',
        'public_history_window_years', 15,
        'coverage_is_complete', false,
        'limitation_zh',
            '來源本身僅發布滾動近期年份；系統按版本保留已見歷史點位，缺少點位仍不代表未曾淹水。'
    ),
    updated_at = now()
WHERE adapter_key = 'official.nstc.flood_disaster_points';

UPDATE data_sources
SET
    update_frequency = 'request-time rolling 15-year citation lookup',
    metadata = jsonb_set(
        metadata,
        '{rolling_lookback_years}',
        '15'::jsonb,
        true
    ),
    updated_at = now()
WHERE adapter_key = 'official.gov_tw.flood_citation';

COMMENT ON TABLE historical_coverage_cells IS
    'Public-safe 22-county by 15-year ingestion coverage; a status never asserts that flooding did or did not occur.';
