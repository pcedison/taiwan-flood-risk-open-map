-- A missing historical row must never be interpreted as evidence that a county
-- had no flooding.  Seed one explicit, fail-closed coverage cell for every
-- canonical county/city and year in the first nationwide review window.
CREATE TABLE IF NOT EXISTS historical_coverage_cells (
    jurisdiction_code text NOT NULL
        REFERENCES realtime_jurisdictions(jurisdiction_code) ON DELETE RESTRICT,
    coverage_year integer NOT NULL,
    status text NOT NULL DEFAULT 'unassessed',
    record_count integer NOT NULL DEFAULT 0,
    checked_source_count integer NOT NULL DEFAULT 0,
    successful_source_count integer NOT NULL DEFAULT 0,
    source_adapter_keys text[] NOT NULL DEFAULT ARRAY[]::text[],
    assessed_at timestamptz,
    last_attempted_at timestamptz,
    last_succeeded_at timestamptz,
    review_ref text,
    status_reason text NOT NULL DEFAULT 'Coverage audit has not been run.',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (jurisdiction_code, coverage_year),
    CHECK (coverage_year BETWEEN 2018 AND 2100),
    CHECK (
        status IN (
            'unassessed',
            'complete',
            'partial',
            'official_checked_empty',
            'not_published',
            'stale',
            'failed'
        )
    ),
    CHECK (record_count >= 0),
    CHECK (checked_source_count >= 0),
    CHECK (successful_source_count >= 0),
    CHECK (successful_source_count <= checked_source_count),
    CHECK (btrim(status_reason) <> ''),
    CHECK (review_ref IS NULL OR btrim(review_ref) <> ''),
    CHECK (
        status = 'unassessed'
        OR status_reason <> 'Coverage audit has not been run.'
    ),
    CHECK (
        status <> 'unassessed'
        OR (
            record_count = 0
            AND checked_source_count = 0
            AND successful_source_count = 0
            AND cardinality(source_adapter_keys) = 0
            AND assessed_at IS NULL
            AND last_attempted_at IS NULL
            AND last_succeeded_at IS NULL
            AND review_ref IS NULL
        )
    ),
    CHECK (
        status NOT IN ('complete', 'official_checked_empty')
        OR (
            assessed_at IS NOT NULL
            AND last_attempted_at IS NOT NULL
            AND last_succeeded_at IS NOT NULL
            AND review_ref IS NOT NULL
            AND checked_source_count > 0
            AND successful_source_count > 0
            AND cardinality(source_adapter_keys) > 0
        )
    ),
    CHECK (status <> 'complete' OR record_count > 0),
    CHECK (status <> 'official_checked_empty' OR record_count = 0),
    CHECK (
        status <> 'not_published'
        OR (
            record_count = 0
            AND checked_source_count > 0
            AND successful_source_count = 0
            AND cardinality(source_adapter_keys) > 0
            AND assessed_at IS NOT NULL
            AND review_ref IS NOT NULL
        )
    ),
    CHECK (
        status NOT IN ('partial', 'stale', 'failed')
        OR (
            assessed_at IS NOT NULL
            AND last_attempted_at IS NOT NULL
            AND review_ref IS NOT NULL
        )
    ),
    CHECK (
        status <> 'partial'
        OR (
            checked_source_count > 0
            AND cardinality(source_adapter_keys) > 0
        )
    ),
    CHECK (
        status <> 'stale'
        OR (
            checked_source_count > 0
            AND successful_source_count > 0
            AND cardinality(source_adapter_keys) > 0
            AND last_succeeded_at IS NOT NULL
        )
    ),
    CHECK (
        status <> 'failed'
        OR (
            checked_source_count > 0
            AND cardinality(source_adapter_keys) > 0
        )
    ),
    CHECK (last_succeeded_at IS NULL OR last_attempted_at IS NOT NULL),
    CHECK (last_succeeded_at IS NULL OR last_succeeded_at <= updated_at),
    CHECK (last_attempted_at IS NULL OR last_attempted_at <= updated_at)
);

INSERT INTO historical_coverage_cells (
    jurisdiction_code,
    coverage_year
)
SELECT
    jurisdiction.jurisdiction_code,
    year_window.coverage_year
FROM realtime_jurisdictions AS jurisdiction
CROSS JOIN generate_series(2018, 2026) AS year_window(coverage_year)
ON CONFLICT (jurisdiction_code, coverage_year) DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_historical_coverage_cells_status_year
    ON historical_coverage_cells (status, coverage_year, jurisdiction_code);

CREATE INDEX IF NOT EXISTS idx_historical_coverage_cells_updated
    ON historical_coverage_cells (updated_at DESC, jurisdiction_code, coverage_year);

COMMENT ON TABLE historical_coverage_cells IS
    'Public-safe county/year ingestion coverage; a status never asserts that flooding did or did not occur.';
