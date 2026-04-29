from __future__ import annotations

from datetime import UTC, datetime
import json

from app.jobs.ingestion import AdapterBatchRunSummary, run_adapter_batch
from app.pipelines.ingestion_runs import PostgresIngestionRunWriter
from tests.test_ingestion_job_runner import _EmptyAdapter, _MemoryWriter
from app.adapters.news import SamplePublicWebNewsAdapter


STARTED_AT = datetime(2026, 4, 29, 8, 0, tzinfo=UTC)
FINISHED_AT = datetime(2026, 4, 29, 8, 1, tzinfo=UTC)


def test_postgres_ingestion_run_writer_inserts_job_run_and_updates_source() -> None:
    summary = AdapterBatchRunSummary(
        adapter_key="news.public_web.sample",
        status="succeeded",
        started_at=STARTED_AT,
        finished_at=FINISHED_AT,
        items_fetched=2,
        items_promoted=2,
        items_rejected=0,
        raw_ref="raw/news/sample.json",
    )
    connection = _FakeConnection(job_id="job-id")
    writer = PostgresIngestionRunWriter(connection_factory=lambda: connection)

    writer.write_summary(summary, job_key="ingest.news", parameters={"radius_m": 500})

    assert connection.committed is True
    assert len(connection.cursor_instance.executions) == 3
    job_sql, job_params = connection.cursor_instance.executions[0]
    run_sql, run_params = connection.cursor_instance.executions[1]
    source_sql, source_params = connection.cursor_instance.executions[2]
    assert "INSERT INTO ingestion_jobs" in job_sql
    assert job_params[0] == "ingest.news"
    assert job_params[4] == "succeeded"
    assert json.loads(str(job_params[12])) == {"radius_m": 500}
    assert "INSERT INTO adapter_runs" in run_sql
    assert run_params[0] == "job-id"
    assert run_params[4] == "succeeded"
    assert json.loads(str(run_params[13])) == {"raw_ref": "raw/news/sample.json"}
    assert "UPDATE data_sources" in source_sql
    assert source_params[-1] == "news.public_web.sample"


def test_postgres_ingestion_run_writer_maps_partial_to_succeeded_job() -> None:
    summary = AdapterBatchRunSummary(
        adapter_key="news.public_web.sample",
        status="partial",
        started_at=STARTED_AT,
        finished_at=FINISHED_AT,
        items_fetched=2,
        items_promoted=1,
        items_rejected=1,
    )
    connection = _FakeConnection(job_id="job-id")

    PostgresIngestionRunWriter(connection_factory=lambda: connection).write_summary(
        summary,
        job_key="ingest.news",
    )

    assert connection.cursor_instance.executions[0][1][4] == "succeeded"
    assert connection.cursor_instance.executions[1][1][4] == "partial"


def test_postgres_ingestion_run_writer_does_not_insert_adapter_run_for_skipped_summary() -> None:
    summary = AdapterBatchRunSummary(
        adapter_key="test.empty",
        status="skipped",
        started_at=STARTED_AT,
        finished_at=FINISHED_AT,
        items_fetched=0,
        items_promoted=0,
        items_rejected=0,
        error_code="empty_fetch",
    )
    connection = _FakeConnection(job_id="job-id")

    PostgresIngestionRunWriter(connection_factory=lambda: connection).write_summary(
        summary,
        job_key="ingest.empty",
    )

    assert len(connection.cursor_instance.executions) == 2
    assert "INSERT INTO ingestion_jobs" in connection.cursor_instance.executions[0][0]
    assert "UPDATE data_sources" in connection.cursor_instance.executions[1][0]


def test_postgres_ingestion_run_writer_requires_database_url_or_connection_factory() -> None:
    try:
        PostgresIngestionRunWriter()
    except ValueError as exc:
        assert str(exc) == "database_url or connection_factory is required"
    else:
        raise AssertionError("expected ValueError")


def test_run_adapter_batch_can_write_operational_summary() -> None:
    adapter = SamplePublicWebNewsAdapter(
        [
            {
                "id": "sample-news-001",
                "url": "https://example.test/news/flood-001",
                "title": "Street flooding reported near riverside district",
                "summary": "Public report describes street flooding near the riverside district.",
                "published_at": "2026-04-28T08:30:00+00:00",
                "confidence": 0.72,
            }
        ],
        fetched_at=STARTED_AT,
    )
    run_writer = _MemoryRunWriter()

    summary = run_adapter_batch(
        adapter,
        writer=_MemoryWriter(),
        run_writer=run_writer,
        job_key="ingest.news",
        parameters={"source": "sample"},
    )

    assert summary.status == "succeeded"
    assert run_writer.calls == [(summary, "ingest.news", {"source": "sample"})]


def test_run_adapter_batch_surfaces_operational_summary_write_failure() -> None:
    summary = run_adapter_batch(_EmptyAdapter(), run_writer=_FailingRunWriter())

    assert summary.status == "failed"
    assert summary.items_fetched == 0
    assert summary.error_code == "RuntimeError"
    assert summary.error_message == "run summary write failed: run write failed"


class _MemoryRunWriter:
    def __init__(self) -> None:
        self.calls: list[tuple[AdapterBatchRunSummary, str, dict[str, object] | None]] = []

    def write_summary(
        self,
        summary: AdapterBatchRunSummary,
        *,
        job_key: str,
        parameters: dict[str, object] | None = None,
    ) -> None:
        self.calls.append((summary, job_key, parameters))


class _FailingRunWriter:
    def write_summary(
        self,
        summary: AdapterBatchRunSummary,
        *,
        job_key: str,
        parameters: dict[str, object] | None = None,
    ) -> None:
        raise RuntimeError("run write failed")


class _FakeConnection:
    def __init__(self, *, job_id: str) -> None:
        self.cursor_instance = _FakeCursor(job_id=job_id)
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
    def __init__(self, *, job_id: str) -> None:
        self._job_id = job_id
        self.executions: list[tuple[str, tuple[object, ...]]] = []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        self.executions.append((sql, params))

    def fetchone(self) -> tuple[str]:
        return (self._job_id,)
