from __future__ import annotations

from datetime import UTC, datetime

import psycopg
import pytest

from app.domain.history import coverage


AS_OF = datetime(2026, 8, 31, 14, 0, tzinfo=UTC)


class FakeResult:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[dict[str, object]]:
        return self._rows


class FakeConnection:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.query: str | None = None
        self.params: tuple[object, ...] | None = None

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, query: str, params: tuple[object, ...]) -> FakeResult:
        self.query = query
        self.params = params
        return FakeResult(self.rows)


def _row(**overrides: object) -> dict[str, object]:
    now = datetime(2026, 8, 31, 14, 0, tzinfo=UTC)
    row: dict[str, object] = {
        "county_code": "67000000",
        "county": "臺南市",
        "year": 2026,
        "status": "complete",
        "persisted": True,
        "record_count": 3,
        "checked_source_count": 2,
        "successful_source_count": 2,
        "source_adapter_keys": [
            "official.wra.flood_incident",
            "official.gov_tw.flood_citation",
        ],
        "assessed_at": now,
        "last_attempted_at": now,
        "last_succeeded_at": now,
        "status_reason": "Two official sources completed.",
        "updated_at": now,
    }
    row.update(overrides)
    return row


def test_repository_reads_public_safe_coverage_records(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = FakeConnection([_row()])
    monkeypatch.setattr(coverage.psycopg, "connect", lambda *args, **kwargs: connection)

    records = coverage.list_historical_coverage(
        database_url="postgresql://example.invalid/flood",
        as_of=AS_OF,
        county_code="67000000",
        year=2026,
    )

    assert len(records) == 1
    assert records[0].county == "臺南市"
    assert records[0].resolved is True
    assert records[0].source_adapter_keys == (
        "official.wra.flood_incident",
        "official.gov_tw.flood_citation",
    )
    assert "CROSS JOIN selected_years" in str(connection.query)
    assert "LEFT JOIN historical_coverage_cells" in str(connection.query)
    assert "generate_series(%s::integer, %s::integer)" in str(connection.query)
    assert connection.params == ("67000000", "67000000", 2012, 2026, 2026, 2026)


def test_repository_preserves_unassessed_missing_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = FakeConnection(
        [
            _row(
                status="unassessed",
                persisted=False,
                record_count=0,
                checked_source_count=0,
                successful_source_count=0,
                source_adapter_keys=[],
                assessed_at=None,
                last_attempted_at=None,
                last_succeeded_at=None,
                status_reason="Coverage ledger row is missing; coverage remains unassessed.",
                updated_at=None,
            )
        ]
    )
    monkeypatch.setattr(coverage.psycopg, "connect", lambda *args, **kwargs: connection)

    record = coverage.list_historical_coverage(
        database_url="postgresql://example.invalid/flood",
        as_of=AS_OF,
        county_code="67000000",
        year=2026,
    )[0]

    assert record.status == "unassessed"
    assert record.persisted is False
    assert record.resolved is False


def test_repository_rejects_unknown_status(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = FakeConnection([_row(status="no_flood")])
    monkeypatch.setattr(coverage.psycopg, "connect", lambda *args, **kwargs: connection)

    with pytest.raises(
        coverage.HistoricalCoverageRepositoryUnavailable,
        match="unsupported historical coverage status",
    ):
        coverage.list_historical_coverage(
            database_url="postgresql://example.invalid/flood",
            as_of=AS_OF,
            county_code="67000000",
            year=2026,
        )


def test_repository_wraps_database_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable(*args: object, **kwargs: object) -> None:
        raise psycopg.OperationalError("database unavailable")

    monkeypatch.setattr(coverage.psycopg, "connect", unavailable)

    with pytest.raises(coverage.HistoricalCoverageRepositoryUnavailable):
        coverage.list_historical_coverage(
            database_url="postgresql://example.invalid/flood",
            as_of=AS_OF,
        )


def test_repository_rejects_year_outside_15_year_window() -> None:
    with pytest.raises(ValueError, match="year must be between 2012 and 2026"):
        coverage.list_historical_coverage(
            database_url="postgresql://example.invalid/flood",
            as_of=AS_OF,
            year=2027,
        )


def test_repository_uses_taiwan_calendar_year_at_rollover(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeConnection([])
    monkeypatch.setattr(coverage.psycopg, "connect", lambda *args, **kwargs: connection)

    coverage.list_historical_coverage(
        database_url="postgresql://example.invalid/flood",
        as_of=datetime(2026, 12, 31, 16, 1, tzinfo=UTC),
    )

    assert connection.params == (None, None, 2013, 2027, None, None)
