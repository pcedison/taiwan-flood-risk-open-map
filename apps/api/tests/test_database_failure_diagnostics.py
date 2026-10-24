from __future__ import annotations

import json
import socket
from contextlib import nullcontext
from typing import Any

import psycopg
import pytest

from app.api.routes import health
from app.core import database_failures
from app.domain.ingestion import readiness


SECRET = "postgresql://private-user:private-password@private-host/private-db"


@pytest.fixture
def events(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(
        database_failures, "log_event", lambda event, **fields: captured.append(
            {"event": event, **fields}
        )
    )
    return captured


class Connection:
    def __init__(self, fail_at: str | None, error: Exception) -> None:
        self.fail_at = fail_at
        self.error = error
        self.calls = 0

    def __enter__(self) -> Connection:
        if self.fail_at == "connect":
            raise self.error
        return self

    def __exit__(self, *args: object) -> None:
        if self.fail_at == "transaction_exit":
            raise self.error

    def cursor(self) -> nullcontext[Connection]:
        return nullcontext(self)

    def execute(self, sql: str, *args: object) -> Connection:
        self.calls += 1
        if self.fail_at in {"probe", "scheduler"} and self.calls == 1:
            raise self.error
        if self.fail_at in {"schema", "sources"} and self.calls == 2:
            raise self.error
        if self.fail_at == "jurisdictions" and self.calls == 3:
            raise self.error
        return self

    def fetchone(self) -> tuple[bool, ...] | None:
        return (True,) * 13 if self.calls == 2 else None

    def fetchall(self) -> list[object]:
        return []


@pytest.mark.parametrize("stage", ["connect", "probe", "schema", "transaction_exit"])
def test_database_readiness_failure_keeps_failure_and_logs_safe_stage(
    monkeypatch: pytest.MonkeyPatch, events: list[dict[str, Any]], stage: str
) -> None:
    error = psycopg.errors.TooManyConnections(f"connection refused: {SECRET}")
    monkeypatch.setattr(psycopg, "connect", lambda *a, **kw: Connection(stage, error))

    result = health._check_database(SECRET)

    assert result.status == "failed"
    assert result.message == health.DATABASE_READINESS_FAILURE_MESSAGE
    assert len(events) == 1
    assert events[0]["operation"] == "readiness"
    assert events[0]["stage"] == stage
    assert events[0]["sqlstate"] == "53300"
    assert events[0]["error_type"] == "TooManyConnections"
    assert events[0]["elapsed_ms"] >= 0
    assert "private-" not in json.dumps(events) + result.model_dump_json()


@pytest.mark.parametrize(
    "stage", ["connect", "scheduler", "sources", "jurisdictions", "transaction_exit"]
)
def test_ingestion_failure_keeps_unavailable_and_logs_safe_stage(
    monkeypatch: pytest.MonkeyPatch, events: list[dict[str, Any]], stage: str
) -> None:
    error = psycopg.errors.QueryCanceled(f"query failed: {SECRET}")
    monkeypatch.setattr(psycopg, "connect", lambda *a, **kw: Connection(stage, error))

    with pytest.raises(readiness.IngestionReadinessRepositoryUnavailable) as caught:
        readiness.fetch_ingestion_readiness(database_url=SECRET)

    assert caught.value.__cause__ is error
    assert len(events) == 1
    assert events[0]["operation"] == "ingestion_readiness"
    assert events[0]["stage"] == stage
    assert events[0]["sqlstate"] == "57014"
    assert events[0]["error_type"] == "QueryCanceled"
    assert "private-" not in json.dumps(events) + str(caught.value)


@pytest.mark.parametrize("sqlstate", [None, "private-password", "53300\nsecret", 53300])
def test_diagnostics_drop_non_sqlstate_values(
    events: list[dict[str, Any]], sqlstate: object
) -> None:
    error = RuntimeError(SECRET)
    error.sqlstate = sqlstate  # type: ignore[attr-defined]
    database_failures.log_database_failure(
        operation="readiness", stage="connect", started_at=0, error=error
    )
    assert events[0]["sqlstate"] is None
    assert "private-" not in json.dumps(events)


def test_successful_readiness_does_not_log_failures(
    monkeypatch: pytest.MonkeyPatch, events: list[dict[str, Any]]
) -> None:
    monkeypatch.setattr(
        psycopg, "connect", lambda *a, **kw: Connection(None, RuntimeError(SECRET))
    )
    assert health._check_database(SECRET).status == "healthy"
    readiness.fetch_ingestion_readiness(database_url=SECRET)
    assert events == []


def test_real_local_unavailable_connection_preserves_both_failure_contracts(
    events: list[dict[str, Any]],
) -> None:
    # Reserve an unlistened loopback port: no server, production URL or SQL.
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
        local_dsn = f"postgresql://private-user:private-password@127.0.0.1:{port}/private-db"
        assert health._check_database(local_dsn).status == "failed"
        with pytest.raises(readiness.IngestionReadinessRepositoryUnavailable):
            readiness.fetch_ingestion_readiness(database_url=local_dsn)

    assert [event["operation"] for event in events] == ["readiness", "ingestion_readiness"]
    assert all(event["stage"] == "connect" for event in events)
    # Windows may time out instead of immediately refusing an unlistened port.
    assert all(event["error_type"] in {"OperationalError", "ConnectionTimeout"} for event in events)
    assert all(event["sqlstate"] is None for event in events)
    assert "private-" not in json.dumps(events)
    assert "127.0.0.1" not in json.dumps(events)
