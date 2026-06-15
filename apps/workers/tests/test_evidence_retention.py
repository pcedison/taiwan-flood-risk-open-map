from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.config import load_worker_settings
from app.jobs.evidence_retention import (
    DEFAULT_EVIDENCE_REALTIME_RETENTION_HOURS,
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
    assert summary.event_types == ("rainfall", "water_level")
    assert summary.cutoff == now - timedelta(hours=48)
    assert connection.commits == 1

    sql, params = connection.cursor_instance.executions[0]
    assert "DELETE FROM evidence" in sql
    assert "source_type = 'official'" in sql
    assert "event_type = ANY(%s::text[])" in sql
    assert params == (["rainfall", "water_level"], now - timedelta(hours=48), 50_000)


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
