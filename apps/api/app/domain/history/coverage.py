from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, cast

import psycopg
from psycopg.rows import dict_row


HISTORICAL_COVERAGE_START_YEAR = 2018
HISTORICAL_COVERAGE_END_YEAR = 2026
HISTORICAL_COVERAGE_JURISDICTION_COUNT = 22
HISTORICAL_COVERAGE_EXPECTED_CELL_COUNT = (
    HISTORICAL_COVERAGE_END_YEAR - HISTORICAL_COVERAGE_START_YEAR + 1
) * HISTORICAL_COVERAGE_JURISDICTION_COUNT

HistoricalCoverageStatus = Literal[
    "unassessed",
    "complete",
    "partial",
    "official_checked_empty",
    "not_published",
    "stale",
    "failed",
]
HISTORICAL_COVERAGE_STATUSES = frozenset(
    {
        "unassessed",
        "complete",
        "partial",
        "official_checked_empty",
        "not_published",
        "stale",
        "failed",
    }
)
RESOLVED_HISTORICAL_COVERAGE_STATUSES = frozenset(
    {"complete", "official_checked_empty", "not_published"}
)


class HistoricalCoverageRepositoryUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class HistoricalCoverageRecord:
    county_code: str
    county: str
    year: int
    status: HistoricalCoverageStatus
    persisted: bool
    record_count: int
    checked_source_count: int
    successful_source_count: int
    source_adapter_keys: tuple[str, ...]
    assessed_at: datetime | None
    last_attempted_at: datetime | None
    last_succeeded_at: datetime | None
    status_reason: str
    updated_at: datetime | None

    @property
    def resolved(self) -> bool:
        return self.status in RESOLVED_HISTORICAL_COVERAGE_STATUSES


def list_historical_coverage(
    *,
    database_url: str,
    county_code: str | None = None,
    year: int | None = None,
) -> tuple[HistoricalCoverageRecord, ...]:
    if year is not None and not (
        HISTORICAL_COVERAGE_START_YEAR <= year <= HISTORICAL_COVERAGE_END_YEAR
    ):
        raise ValueError(
            "year must be between "
            f"{HISTORICAL_COVERAGE_START_YEAR} and {HISTORICAL_COVERAGE_END_YEAR}"
        )

    query = """
        WITH selected_jurisdictions AS (
            SELECT jurisdiction_code, jurisdiction_name
            FROM realtime_jurisdictions
            WHERE (%s::text IS NULL OR jurisdiction_code = %s::text)
        ),
        selected_years AS (
            SELECT coverage_year
            FROM generate_series(%s::integer, %s::integer) AS years(coverage_year)
            WHERE (%s::integer IS NULL OR coverage_year = %s::integer)
        )
        SELECT
            jurisdiction.jurisdiction_code AS county_code,
            jurisdiction.jurisdiction_name AS county,
            year_window.coverage_year AS year,
            COALESCE(coverage.status, 'unassessed') AS status,
            (coverage.jurisdiction_code IS NOT NULL) AS persisted,
            COALESCE(coverage.record_count, 0)::integer AS record_count,
            COALESCE(coverage.checked_source_count, 0)::integer AS checked_source_count,
            COALESCE(coverage.successful_source_count, 0)::integer
                AS successful_source_count,
            COALESCE(coverage.source_adapter_keys, ARRAY[]::text[])
                AS source_adapter_keys,
            coverage.assessed_at,
            coverage.last_attempted_at,
            coverage.last_succeeded_at,
            COALESCE(
                coverage.status_reason,
                'Coverage ledger row is missing; coverage remains unassessed.'
            ) AS status_reason,
            coverage.updated_at
        FROM selected_jurisdictions AS jurisdiction
        CROSS JOIN selected_years AS year_window
        LEFT JOIN historical_coverage_cells AS coverage
            ON coverage.jurisdiction_code = jurisdiction.jurisdiction_code
           AND coverage.coverage_year = year_window.coverage_year
        ORDER BY jurisdiction.jurisdiction_name, year_window.coverage_year
    """
    params = (
        county_code,
        county_code,
        HISTORICAL_COVERAGE_START_YEAR,
        HISTORICAL_COVERAGE_END_YEAR,
        year,
        year,
    )
    try:
        with psycopg.connect(
            database_url,
            connect_timeout=2,
            row_factory=dict_row,
        ) as connection:
            rows = connection.execute(query, params).fetchall()
    except (OSError, psycopg.Error) as exc:
        raise HistoricalCoverageRepositoryUnavailable(str(exc)) from exc

    return tuple(_record_from_row(row) for row in rows)


def _record_from_row(row: dict[str, object]) -> HistoricalCoverageRecord:
    status_text = str(row["status"])
    if status_text not in HISTORICAL_COVERAGE_STATUSES:
        raise HistoricalCoverageRepositoryUnavailable(
            f"unsupported historical coverage status: {status_text}"
        )
    source_adapter_keys = row.get("source_adapter_keys") or ()
    return HistoricalCoverageRecord(
        county_code=str(row["county_code"]),
        county=str(row["county"]),
        year=int(cast(int, row["year"])),
        status=cast(HistoricalCoverageStatus, status_text),
        persisted=bool(row["persisted"]),
        record_count=int(cast(int, row["record_count"])),
        checked_source_count=int(cast(int, row["checked_source_count"])),
        successful_source_count=int(cast(int, row["successful_source_count"])),
        source_adapter_keys=tuple(str(key) for key in cast(list[object], source_adapter_keys)),
        assessed_at=cast(datetime | None, row.get("assessed_at")),
        last_attempted_at=cast(datetime | None, row.get("last_attempted_at")),
        last_succeeded_at=cast(datetime | None, row.get("last_succeeded_at")),
        status_reason=str(row["status_reason"]),
        updated_at=cast(datetime | None, row.get("updated_at")),
    )
