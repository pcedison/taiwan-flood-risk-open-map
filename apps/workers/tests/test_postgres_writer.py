from __future__ import annotations

from datetime import datetime, timezone
import json

from app.adapters.news import SamplePublicWebNewsAdapter
from app.pipelines.postgres_writer import PostgresStagingBatchWriter
from app.pipelines.staging import build_staging_batch


FETCHED_AT = datetime(2026, 4, 28, 10, 0, tzinfo=timezone.utc)


def test_postgres_writer_upserts_raw_snapshot_and_inserts_staging_rows() -> None:
    adapter = SamplePublicWebNewsAdapter(
        [
            {
                "id": "sample-news-001",
                "url": "https://example.test/news/flood-001",
                "title": "Heavy rain reported near riverside district",
                "summary": "Public report describes street flooding near the riverside district.",
                "published_at": "2026-04-28T08:30:00+00:00",
                "location_text": "Riverside District",
                "confidence": 0.72,
            }
        ],
        fetched_at=FETCHED_AT,
        raw_snapshot_key="raw/news-public-web/sample.json",
    )
    batch = build_staging_batch(adapter.run())
    connection = _FakeConnection(raw_snapshot_id="raw-snapshot-id")
    writer = PostgresStagingBatchWriter(connection_factory=lambda: connection)

    writer.write_batch(batch)

    assert connection.committed is True
    assert len(connection.cursor_instance.executions) == 2
    raw_sql, raw_params = connection.cursor_instance.executions[0]
    staging_sql, staging_params = connection.cursor_instance.executions[1]
    assert "INSERT INTO raw_snapshots" in raw_sql
    assert raw_params[1] == "raw/news-public-web/sample.json"
    assert "ON CONFLICT (raw_ref) DO UPDATE" in raw_sql
    assert "INSERT INTO staging_evidence" in staging_sql
    assert staging_params[0] == "raw-snapshot-id"
    assert staging_params[10] == "accepted"
    payload = json.loads(str(staging_params[12]))
    assert payload["evidence_id"].startswith("ev_")
    assert payload["adapter_key"] == "news.public_web.sample"


def test_postgres_writer_requires_database_url_or_connection_factory() -> None:
    try:
        PostgresStagingBatchWriter()
    except ValueError as exc:
        assert str(exc) == "database_url or connection_factory is required"
    else:
        raise AssertionError("expected ValueError")


class _FakeConnection:
    def __init__(self, *, raw_snapshot_id: str) -> None:
        self.cursor_instance = _FakeCursor(raw_snapshot_id=raw_snapshot_id)
        self.committed = False

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def cursor(self) -> _FakeCursor:
        return self.cursor_instance

    def commit(self) -> None:
        self.committed = True


class _FakeCursor:
    def __init__(self, *, raw_snapshot_id: str) -> None:
        self._raw_snapshot_id = raw_snapshot_id
        self.executions: list[tuple[str, tuple[object, ...]]] = []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        self.executions.append((sql, params))

    def fetchone(self) -> tuple[str]:
        return (self._raw_snapshot_id,)
