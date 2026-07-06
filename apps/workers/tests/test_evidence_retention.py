from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.config import load_worker_settings
from app.jobs.evidence_retention import (
    DEFAULT_EVIDENCE_REALTIME_RETENTION_HOURS,
    DEFAULT_LOCATION_QUERY_RETENTION_HOURS,
    EvidenceRetentionUnavailable,
    PostgresEvidenceRetentionJob,
)


class _FakeCursor:
    def __init__(self, fetch_result: object) -> None:
        self._fetch_result = fetch_result
        self.executions: list[tuple[str, tuple]] = []

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: tuple) -> None:
        self.executions.append((sql, params))

    def fetchone(self) -> object:
        return self._fetch_result


class _FakeConnection:
    def __init__(self, fetch_result: object) -> None:
        self.cursor_instance = _FakeCursor(fetch_result)
        self.commits = 0

    def __enter__(self) -> "_FakeConnection":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def cursor(self) -> _FakeCursor:
        return self.cursor_instance

    def commit(self) -> None:
        self.commits += 1


def test_prune_realtime_deletes_official_station_evidence_past_cutoff() -> None:
    connection = _FakeConnection((7,))
    now = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
    job = PostgresEvidenceRetentionJob(connection_factory=lambda: connection)

    summary = job.prune_realtime(retention_hours=48, now=now)

    assert summary.rows_deleted == 7
    assert summary.event_types == (
        "rainfall",
        "water_level",
        "flood_report",
        "flood_warning",
    )
    assert summary.cutoff == now - timedelta(hours=48)
    assert connection.commits == 1

    sql, params = connection.cursor_instance.executions[0]
    assert "DELETE FROM evidence" in sql
    assert "source_type = 'official'" in sql
    assert "event_type = ANY(%s::text[])" in sql
    assert params == (
        ["rainfall", "water_level", "flood_report", "flood_warning"],
        now - timedelta(hours=48),
        50_000,
    )


def test_prune_realtime_flood_report_and_warning_scoped_to_official_source() -> None:
    """flood_report/flood_warning are prunable, but only for source_type='official'.

    Historical flood_report evidence (e.g. news or public reports) shares the
    same event_type but uses a non-official source_type. The prune query must
    filter on ``source_type = 'official'`` as a hardcoded SQL literal (not a
    bind parameter), so those non-official rows can never be deleted no
    matter what event_types/params are passed in.
    """
    connection = _FakeConnection((3,))
    now = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
    job = PostgresEvidenceRetentionJob(connection_factory=lambda: connection)

    job.prune_realtime(
        retention_hours=48,
        event_types=("flood_report", "flood_warning"),
        now=now,
    )

    sql, params = connection.cursor_instance.executions[0]
    # 'official' is a literal baked into the SQL text, not a bind parameter --
    # there is no way for a caller to widen the query to non-official rows.
    assert "source_type = 'official'" in sql
    assert params == (["flood_report", "flood_warning"], now - timedelta(hours=48), 50_000)


def test_prune_realtime_skips_when_no_event_types() -> None:
    connection = _FakeConnection((0,))
    job = PostgresEvidenceRetentionJob(connection_factory=lambda: connection)

    summary = job.prune_realtime(retention_hours=24, event_types=())

    assert summary.rows_deleted == 0
    assert connection.commits == 0
    assert connection.cursor_instance.executions == []


def test_prune_realtime_rejects_non_positive_retention() -> None:
    job = PostgresEvidenceRetentionJob(connection_factory=lambda: _FakeConnection((0,)))

    with pytest.raises(ValueError):
        job.prune_realtime(retention_hours=0)


def test_prune_realtime_wraps_database_errors() -> None:
    def boom() -> object:
        raise RuntimeError("connection refused")

    job = PostgresEvidenceRetentionJob(connection_factory=boom)

    with pytest.raises(EvidenceRetentionUnavailable):
        job.prune_realtime(retention_hours=48)


def test_prune_location_queries_deletes_rows_past_cutoff() -> None:
    connection = _FakeConnection((11,))
    now = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)
    job = PostgresEvidenceRetentionJob(connection_factory=lambda: connection)

    summary = job.prune_location_queries(retention_hours=720, now=now)

    assert summary.rows_deleted == 11
    assert summary.retention_hours == 720
    assert summary.cutoff == now - timedelta(hours=720)
    assert connection.commits == 1

    sql, params = connection.cursor_instance.executions[0]
    assert "DELETE FROM location_queries" in sql
    assert "created_at < %s::timestamptz" in sql
    assert params == (now - timedelta(hours=720), 50_000)


def test_prune_location_queries_rejects_non_positive_retention() -> None:
    job = PostgresEvidenceRetentionJob(connection_factory=lambda: _FakeConnection((0,)))

    with pytest.raises(ValueError):
        job.prune_location_queries(retention_hours=0)


def test_prune_location_queries_wraps_database_errors() -> None:
    def boom() -> object:
        raise RuntimeError("connection refused")

    job = PostgresEvidenceRetentionJob(connection_factory=boom)

    with pytest.raises(EvidenceRetentionUnavailable):
        job.prune_location_queries(retention_hours=720)


def test_location_queries_retention_hours_config_default_and_env() -> None:
    assert load_worker_settings({}).location_queries_retention_hours == (
        DEFAULT_LOCATION_QUERY_RETENTION_HOURS
    )
    assert (
        load_worker_settings(
            {"LOCATION_QUERIES_RETENTION_HOURS": "240"}
        ).location_queries_retention_hours
        == 240
    )


def test_evidence_retention_hours_config_default_and_env() -> None:
    assert load_worker_settings({}).evidence_realtime_retention_hours == (
        DEFAULT_EVIDENCE_REALTIME_RETENTION_HOURS
    )
    assert (
        load_worker_settings(
            {"EVIDENCE_REALTIME_RETENTION_HOURS": "12"}
        ).evidence_realtime_retention_hours
        == 12
    )
