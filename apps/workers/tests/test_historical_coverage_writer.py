from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from app.jobs.historical_coverage import (
    HistoricalCoverageWriteError,
    PostgresHistoricalCoverageWriter,
)


class _FakeCursor:
    def __init__(self, row: tuple[object, ...]) -> None:
        self.row = row
        self.executions: list[tuple[str, tuple[object, ...]]] = []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        self.executions.append((sql, params))

    def fetchone(self) -> tuple[object, ...]:
        return self.row


class _FakeConnection:
    def __init__(self, row: tuple[object, ...]) -> None:
        self.cursor_instance = _FakeCursor(row)
        self.commit_count = 0

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def cursor(self) -> _FakeCursor:
        return self.cursor_instance

    def commit(self) -> None:
        self.commit_count += 1


def _writer(connection: _FakeConnection) -> PostgresHistoricalCoverageWriter:
    return PostgresHistoricalCoverageWriter(connection_factory=lambda: connection)


def _record_success(writer: PostgresHistoricalCoverageWriter) -> Any:
    return writer.record_success(
        adapter_key="official.nstc.flood_disaster_points",
        raw_ref="raw:test",
        assessed_at=datetime(2026, 9, 1, tzinfo=UTC),
    )


def test_record_success_attributes_and_upserts_in_one_database_statement() -> None:
    connection = _FakeConnection((6, 6, 6, [2018, 2019], 22, 1, 44))

    result = _record_success(_writer(connection))

    assert result.assessed_years == (2018, 2019)
    assert result.source_check_count == 44
    assert result.attributed_record_count == 6
    assert result.boundary_adjusted_record_count == 1
    assert connection.commit_count == 1
    assert len(connection.cursor_instance.executions) == 3
    ensure_sql, ensure_params = connection.cursor_instance.executions[0]
    assert "INSERT INTO historical_coverage_cells" in ensure_sql
    assert ensure_params == (2012, 2026)
    coverage_sql, coverage_params = connection.cursor_instance.executions[1]
    assert coverage_sql.count("target_snapshot AS") == 1
    assert "upserted_source_checks AS" in coverage_sql
    assert "DISTINCT ON (candidate.evidence_key)" in coverage_sql
    assert "ST_Subdivide(boundary.geom, 256)" in coverage_sql
    assert len(coverage_params) == 8
    _, refresh_params = connection.cursor_instance.executions[2]
    assert refresh_params == ([2018, 2019],)


def test_record_success_skips_refresh_when_snapshot_has_no_assessed_years() -> None:
    connection = _FakeConnection((0, 0, 0, [], 22, 0, 0))

    result = _record_success(_writer(connection))

    assert result.assessed_years == ()
    assert result.source_check_count == 0
    assert len(connection.cursor_instance.executions) == 2
    assert connection.commit_count == 1


def test_record_success_does_not_refresh_after_failed_preflight() -> None:
    connection = _FakeConnection((1, 0, 0, [2018], 22, 0, 0))

    with pytest.raises(
        HistoricalCoverageWriteError,
        match="accepted rows without valid geometry",
    ):
        _record_success(_writer(connection))

    assert len(connection.cursor_instance.executions) == 2
    assert connection.commit_count == 0


def test_record_success_rolls_window_forward_in_taiwan_calendar_time() -> None:
    connection = _FakeConnection((0, 0, 0, [], 22, 0, 0))
    writer = _writer(connection)

    writer.record_success(
        adapter_key="official.nstc.flood_disaster_points",
        raw_ref="raw:test-2027",
        assessed_at=datetime(2026, 12, 31, 16, 1, tzinfo=UTC),
    )

    _, ensure_params = connection.cursor_instance.executions[0]
    assert ensure_params == (2013, 2027)
    _, coverage_params = connection.cursor_instance.executions[1]
    assert coverage_params[2:4] == (2013, 2027)


def test_record_success_rejects_naive_assessment_time() -> None:
    connection = _FakeConnection((0, 0, 0, [], 22, 0, 0))

    with pytest.raises(ValueError, match="assessed_at must be timezone-aware"):
        _writer(connection).record_success(
            adapter_key="official.nstc.flood_disaster_points",
            raw_ref="raw:naive-time",
            assessed_at=datetime(2026, 9, 1),
        )

    assert connection.cursor_instance.executions == []
    assert connection.commit_count == 0
