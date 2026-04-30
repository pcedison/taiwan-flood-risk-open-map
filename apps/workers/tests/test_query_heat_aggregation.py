from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.jobs.query_heat import (
    QUERY_HEAT_PERIOD_ORIGIN,
    PostgresQueryHeatAggregationJob,
    QueryHeatAggregationUnavailable,
)


WINDOW_START = datetime(2026, 4, 23, 0, 0, tzinfo=UTC)
WINDOW_END = datetime(2026, 4, 30, 0, 0, tzinfo=UTC)


def test_query_heat_aggregation_upserts_p7d_and_p1d_buckets() -> None:
    connection = _FakeConnection(fetch_rows=[(3,), (9,)])
    job = PostgresQueryHeatAggregationJob(connection_factory=lambda: connection)

    summaries = job.aggregate(
        periods=("P7D", "P1D"),
        created_at_start=WINDOW_START,
        created_at_end=WINDOW_END,
    )

    assert connection.commits == 1
    assert [(summary.period, summary.buckets_upserted) for summary in summaries] == [
        ("P7D", 3),
        ("P1D", 9),
    ]
    p7d_sql, p7d_params = connection.cursor_instance.executions[0]
    p1d_sql, p1d_params = connection.cursor_instance.executions[1]
    assert "FROM location_queries lq" in p7d_sql
    assert "INSERT INTO query_heat_buckets" in p7d_sql
    assert "date_bin(%s::interval, nq.created_at, %s::timestamptz)" in p7d_sql
    assert "COUNT(*)::integer AS query_count" in p7d_sql
    assert "COUNT(" in p7d_sql
    assert "DISTINCT COALESCE" in p7d_sql
    assert "ON CONFLICT (h3_index, period, period_started_at) DO UPDATE SET" in p7d_sql
    assert "query_count = EXCLUDED.query_count" in p7d_sql
    assert "unique_approx_count = EXCLUDED.unique_approx_count" in p7d_sql
    assert "updated_at = now()" in p7d_sql
    assert p7d_params == (
        WINDOW_START,
        WINDOW_END,
        "P7D",
        "7 days",
        QUERY_HEAT_PERIOD_ORIGIN,
    )
    assert p1d_params == (
        WINDOW_START,
        WINDOW_END,
        "P1D",
        "1 day",
        QUERY_HEAT_PERIOD_ORIGIN,
    )


def test_query_heat_aggregation_validates_period_before_connecting() -> None:
    connected = False

    def connect() -> _FakeConnection:
        nonlocal connected
        connected = True
        return _FakeConnection(fetch_rows=[(0,)])

    job = PostgresQueryHeatAggregationJob(connection_factory=connect)

    try:
        job.aggregate(periods=("PT1H",))
    except ValueError as exc:
        assert "unsupported query heat period 'PT1H'" in str(exc)
    else:
        raise AssertionError("expected ValueError")

    assert connected is False


def test_query_heat_aggregation_wraps_database_errors() -> None:
    job = PostgresQueryHeatAggregationJob(connection_factory=lambda: _BrokenConnection())

    try:
        job.aggregate(periods=("P7D",))
    except QueryHeatAggregationUnavailable as exc:
        assert "database unavailable" in str(exc)
    else:
        raise AssertionError("expected QueryHeatAggregationUnavailable")


def test_query_heat_aggregation_requires_database_url_or_connection_factory() -> None:
    try:
        PostgresQueryHeatAggregationJob()
    except ValueError as exc:
        assert str(exc) == "database_url or connection_factory is required"
    else:
        raise AssertionError("expected ValueError")


class _FakeConnection:
    def __init__(self, *, fetch_rows: list[tuple[Any, ...] | None]) -> None:
        self.cursor_instance = _FakeCursor(fetch_rows=fetch_rows)
        self.commits = 0

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def cursor(self) -> _FakeCursor:
        return self.cursor_instance

    def commit(self) -> None:
        self.commits += 1


class _FakeCursor:
    def __init__(self, *, fetch_rows: list[tuple[Any, ...] | None]) -> None:
        self._fetch_rows = fetch_rows
        self.executions: list[tuple[str, tuple[object, ...]]] = []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        self.executions.append((sql, params))

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._fetch_rows.pop(0)


class _BrokenConnection:
    def __enter__(self) -> _BrokenConnection:
        raise RuntimeError("database unavailable")

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None
