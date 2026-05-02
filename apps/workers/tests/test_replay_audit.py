from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.jobs.queue import RuntimeQueueUnavailable
from app.jobs.replay_audit import PostgresRuntimeQueueReplayAudit


REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATION = REPO_ROOT / "infra" / "migrations" / "0009_runtime_queue_replay_audit.sql"


def test_replay_audit_migration_uses_idempotent_runtime_queue_names() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert MIGRATION.name == "0009_runtime_queue_replay_audit.sql"
    assert "CREATE TABLE IF NOT EXISTS worker_runtime_queue_replay_audit" in sql
    assert "CREATE TABLE IF NOT EXISTS worker_runtime_queue_poison_quarantine" in sql
    assert "CREATE INDEX IF NOT EXISTS idx_worker_runtime_queue_replay_audit_job" in sql
    assert (
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_worker_runtime_queue_poison_quarantine_active_job"
    ) in sql
    assert "does not implement automatic replay policy" in sql
    assert "does not cancel, replay, or otherwise mutate worker_runtime_jobs" in sql
    assert "ALTER TABLE worker_runtime_jobs" not in sql


def test_record_requested_inserts_audit_row_with_json_metadata_without_requeue() -> None:
    connection = _FakeConnection(fetch_rows=[("audit-1", "job-1", "replay", "requested", 3, None)])
    audit = PostgresRuntimeQueueReplayAudit(connection_factory=lambda: connection)

    record = audit.record_requested(
        job_id="job-1",
        requested_by="operator@example.test",
        reason="operator retry",
        attempts_before=3,
        metadata={"ticket": "INC-1", "retry": True},
    )

    assert record.id == "audit-1"
    assert record.job_id == "job-1"
    assert record.action == "replay"
    assert record.status == "requested"
    assert record.attempts_before == 3
    assert record.attempts_after is None
    assert connection.commits == 1
    sql, params = connection.cursor_instance.executions[0]
    assert "INSERT INTO worker_runtime_queue_replay_audit" in sql
    assert "UPDATE worker_runtime_jobs" not in sql
    assert "CASE WHEN %s = 'requested' THEN now()" in sql
    assert "CASE WHEN %s = 'completed' THEN now()" in sql
    assert "CASE WHEN %s = 'failed' THEN now()" in sql
    assert params[:7] == (
        "job-1",
        "replay",
        "operator@example.test",
        "operator retry",
        "requested",
        3,
        None,
    )
    assert isinstance(params[7], str)
    assert json.loads(params[7]) == {"retry": True, "ticket": "INC-1"}
    assert params[8:] == ("requested", "requested", "requested")


def test_record_completed_and_failed_capture_attempt_boundaries() -> None:
    connection = _FakeConnection(
        fetch_rows=[
            ("audit-2", "job-1", "replay", "completed", 3, 0),
            ("audit-3", "job-1", "replay", "failed", 3, 3),
        ]
    )
    audit = PostgresRuntimeQueueReplayAudit(connection_factory=lambda: connection)

    completed = audit.record_completed(
        job_id="job-1",
        requested_by="operator@example.test",
        reason="manual replay completed",
        attempts_before=3,
        attempts_after=0,
        metadata={"duration_ms": 1200},
    )
    failed = audit.record_failed(
        job_id="job-1",
        requested_by="operator@example.test",
        reason="manual replay failed",
        attempts_before=3,
        attempts_after=3,
        metadata={"error": "source timeout"},
    )

    assert completed.status == "completed"
    assert completed.attempts_after == 0
    assert failed.status == "failed"
    assert failed.attempts_after == 3
    assert connection.commits == 2
    _, completed_params = connection.cursor_instance.executions[0]
    _, failed_params = connection.cursor_instance.executions[1]
    assert completed_params[4] == "completed"
    assert completed_params[5:8] == (3, 0, '{"duration_ms":1200}')
    assert completed_params[8:] == ("completed", "completed", "completed")
    assert failed_params[3:8] == (
        "manual replay failed",
        "failed",
        3,
        3,
        '{"error":"source timeout"}',
    )
    assert failed_params[8:] == ("failed", "failed", "failed")


def test_quarantine_poison_job_uses_boundary_table_without_touching_queue() -> None:
    connection = _FakeConnection(
        fetch_rows=[("quarantine-1", "job-1", "active", "operator@example.test", "bad", 5)]
    )
    audit = PostgresRuntimeQueueReplayAudit(connection_factory=lambda: connection)

    record = audit.quarantine_poison_job(
        job_id="job-1",
        quarantined_by="operator@example.test",
        reason="bad payload shape",
        attempts_at_quarantine=5,
        metadata={"payload_hash": "abc123"},
    )

    assert record.id == "quarantine-1"
    assert record.status == "active"
    assert record.quarantined_by == "operator@example.test"
    assert record.attempts_at_quarantine == 5
    sql, params = connection.cursor_instance.executions[0]
    assert "INSERT INTO worker_runtime_queue_poison_quarantine" in sql
    assert "ON CONFLICT (job_id)" in sql
    assert "WHERE status = 'active'" in sql
    assert "UPDATE worker_runtime_jobs" not in sql
    assert params[:4] == (
        "job-1",
        "operator@example.test",
        "bad payload shape",
        5,
    )
    assert isinstance(params[4], str)
    assert json.loads(params[4]) == {"payload_hash": "abc123"}


def test_release_poison_quarantine_marks_boundary_released_without_requeue() -> None:
    connection = _FakeConnection(fetch_rows=[("quarantine-1",)])
    audit = PostgresRuntimeQueueReplayAudit(connection_factory=lambda: connection)

    released = audit.release_poison_quarantine(
        job_id="job-1",
        released_by="operator@example.test",
        reason="payload fixed",
        metadata={"ticket": "INC-2"},
    )

    assert released is True
    assert connection.commits == 1
    sql, params = connection.cursor_instance.executions[0]
    assert "UPDATE worker_runtime_queue_poison_quarantine" in sql
    assert "released_at = now()" in sql
    assert "worker_runtime_jobs" not in sql
    assert params[:2] == ("operator@example.test", "payload fixed")
    assert isinstance(params[2], str)
    assert json.loads(params[2]) == {"ticket": "INC-2"}
    assert params[3] == "job-1"


def test_release_poison_quarantine_reports_missing_active_boundary() -> None:
    connection = _FakeConnection(fetch_rows=[None])
    audit = PostgresRuntimeQueueReplayAudit(connection_factory=lambda: connection)

    released = audit.release_poison_quarantine(
        job_id="job-1",
        released_by="operator@example.test",
    )

    assert released is False
    assert connection.commits == 1


def test_has_active_poison_quarantine_checks_active_boundary() -> None:
    connection = _FakeConnection(fetch_rows=[(1,), None])
    audit = PostgresRuntimeQueueReplayAudit(connection_factory=lambda: connection)

    assert audit.has_active_poison_quarantine(job_id="job-1") is True
    assert audit.has_active_poison_quarantine(job_id="job-2") is False
    assert connection.commits == 2
    first_sql, first_params = connection.cursor_instance.executions[0]
    assert "FROM worker_runtime_queue_poison_quarantine" in first_sql
    assert "status = 'active'" in first_sql
    assert "released_at IS NULL" in first_sql
    assert first_params == ("job-1",)


def test_requeue_failed_job_with_audit_commits_job_update_and_audit_together() -> None:
    connection = _FakeConnection(
        fetch_rows=[
            ("job-1", "failed", 3),
            ("audit-requested", "job-1", "replay", "requested", 3, None),
            None,
            ("job-1", 0),
            ("audit-completed", "job-1", "replay", "completed", 3, 0),
        ]
    )
    audit = PostgresRuntimeQueueReplayAudit(connection_factory=lambda: connection)

    result = audit.requeue_failed_job_with_audit(
        job_id="job-1",
        requested_by="operator@example.test",
        reason="manual retry",
    )

    assert result.requeued is True
    assert result.requested_audit_id == "audit-requested"
    assert result.outcome_audit_id == "audit-completed"
    assert result.attempts_before == 3
    assert result.attempts_after == 0
    assert connection.commits == 1
    executions = connection.cursor_instance.executions
    assert "FOR UPDATE" in executions[0][0]
    assert "INSERT INTO worker_runtime_queue_replay_audit" in executions[1][0]
    assert executions[1][1][:7] == (
        "job-1",
        "replay",
        "operator@example.test",
        "manual retry",
        "requested",
        3,
        None,
    )
    assert "FOR UPDATE" in executions[2][0]
    assert "worker_runtime_queue_poison_quarantine" in executions[2][0]
    assert "UPDATE worker_runtime_jobs" in executions[3][0]
    assert executions[3][1] == (True, "job-1")
    assert "INSERT INTO worker_runtime_queue_replay_audit" in executions[4][0]
    assert executions[4][1][:7] == (
        "job-1",
        "replay",
        "operator@example.test",
        "manual retry",
        "completed",
        3,
        0,
    )


def test_requeue_failed_job_with_audit_refuses_active_poison_quarantine() -> None:
    connection = _FakeConnection(
        fetch_rows=[
            ("job-1", "failed", 5),
            ("audit-requested", "job-1", "replay", "requested", 5, None),
            ("quarantine-1",),
            ("audit-failed", "job-1", "replay", "failed", 5, 5),
        ]
    )
    audit = PostgresRuntimeQueueReplayAudit(connection_factory=lambda: connection)

    result = audit.requeue_failed_job_with_audit(
        job_id="job-1",
        requested_by="operator@example.test",
        reason="manual retry",
    )

    assert result.requeued is False
    assert result.reason == "poison_quarantine_active"
    assert result.requested_audit_id == "audit-requested"
    assert result.outcome_audit_id == "audit-failed"
    assert result.attempts_before == 5
    assert result.attempts_after == 5
    assert connection.commits == 1
    assert all("UPDATE worker_runtime_jobs" not in sql for sql, _ in connection.cursor_instance.executions)
    failed_sql, failed_params = connection.cursor_instance.executions[3]
    assert "INSERT INTO worker_runtime_queue_replay_audit" in failed_sql
    assert failed_params[:7] == (
        "job-1",
        "replay",
        "operator@example.test",
        "poison_quarantine_active",
        "failed",
        5,
        5,
    )


def test_replay_audit_database_errors_raise_runtime_queue_unavailable() -> None:
    audit = PostgresRuntimeQueueReplayAudit(connection_factory=lambda: _BrokenConnection())

    with pytest.raises(RuntimeQueueUnavailable, match="database unavailable"):
        audit.record_requested(
            job_id="job-1",
            requested_by="operator@example.test",
            reason="operator retry",
            attempts_before=1,
        )


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
