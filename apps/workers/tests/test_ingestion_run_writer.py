from __future__ import annotations

from datetime import UTC, datetime
import json

from app.adapters.civil_iot import FloodSensorStaApiAdapter
from app.jobs.ingestion import AdapterBatchRunSummary, run_adapter_batch
from app.pipelines.ingestion_runs import PostgresIngestionRunWriter
from tests.test_ingestion_job_runner import _EmptyAdapter, _MemoryWriter
from app.adapters.news import SamplePublicWebNewsAdapter


STARTED_AT = datetime(2026, 4, 29, 8, 0, tzinfo=UTC)
FINISHED_AT = datetime(2026, 4, 29, 8, 1, tzinfo=UTC)


def _civil_iot_inventory_payload(*, with_observation: bool = True) -> dict:
    observations = (
        [{"phenomenonTime": "2026-04-29T08:00:00Z", "result": 0.0}]
        if with_observation
        else []
    )
    return {
        "@iot.count": 1,
        "value": [
            {
                "@iot.id": 101,
                "name": "Inventory station",
                "properties": {"stationID": "FS-INVENTORY-1"},
                "Locations": [
                    {"location": {"type": "Point", "coordinates": [120.2, 23.0]}}
                ],
                "Datastreams": [
                    {
                        "name": "淹水深度",
                        "unitOfMeasurement": {"symbol": "cm"},
                        "Observations": observations,
                    }
                ],
            }
        ],
    }


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
    assert source_params[-2] == "news.public_web.sample"
    assert source_params[-1] == STARTED_AT


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


def test_postgres_ingestion_run_writer_persists_runtime_selection_snapshot() -> None:
    connection = _FakeConnection(job_id="unused")
    writer = PostgresIngestionRunWriter(connection_factory=lambda: connection)

    writer.write_runtime_selection(
        enabled_adapter_keys=("official.cwa.rainfall",),
        known_adapter_keys=("official.cwa.rainfall", "official.wra.water_level"),
        checked_at=FINISHED_AT,
    )

    assert connection.committed is True
    assert len(connection.cursor_instance.executions) == 1
    sql, params = connection.cursor_instance.executions[0]
    assert "runtime_enabled = (adapter_key = ANY" in sql
    assert params == (
        ["official.cwa.rainfall"],
        FINISHED_AT,
        ["official.cwa.rainfall", "official.wra.water_level"],
    )


def test_postgres_ingestion_run_writer_persists_final_pipeline_status() -> None:
    connection = _FakeConnection(job_id="unused")
    writer = PostgresIngestionRunWriter(connection_factory=lambda: connection)

    writer.write_pipeline_status(
        adapter_keys=("official.wra.water_level",),
        status="failed",
        complete=False,
        checked_at=FINISHED_AT,
        run_at=STARTED_AT,
    )

    assert connection.committed is True
    assert len(connection.cursor_instance.executions) == 1
    sql, params = connection.cursor_instance.executions[0]
    assert "runtime_pipeline_status = %s" in sql
    assert "runtime_pipeline_complete = %s" in sql
    assert "runtime_pipeline_run_at <= %s" in sql
    assert "COALESCE(jobs.started_at, jobs.created_at) > %s" in sql
    assert params == (
        "failed",
        FINISHED_AT,
        False,
        STARTED_AT,
        ["official.wra.water_level"],
        STARTED_AT,
        STARTED_AT,
    )


def test_pipeline_failure_without_ingestion_summary_gets_ordered_generation() -> None:
    connection = _FakeConnection(job_id="unused")
    writer = PostgresIngestionRunWriter(connection_factory=lambda: connection)

    writer.write_pipeline_status(
        adapter_keys=("official.wra.water_level",),
        status="failed",
        complete=False,
        checked_at=FINISHED_AT,
    )

    _, params = connection.cursor_instance.executions[0]
    assert params[3] == FINISHED_AT
    assert params[-2:] == (FINISHED_AT, FINISHED_AT)


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


def test_civil_iot_inventory_proof_flows_to_run_snapshot_and_safe_metrics() -> None:
    adapter = FloodSensorStaApiAdapter(
        fetched_at=STARTED_AT,
        fetch_json=lambda url, timeout: _civil_iot_inventory_payload(),
    )
    connection = _FakeConnection(job_id="job-id")
    run_writer = PostgresIngestionRunWriter(connection_factory=lambda: connection)

    summary = run_adapter_batch(
        adapter,
        writer=_MemoryWriter(),
        run_writer=run_writer,
        job_key="ingest.official.civil_iot.flood_sensor",
    )

    assert summary.status == "succeeded"
    proof = summary.station_inventory_proof
    assert proof is not None
    assert proof.inventory_complete is True
    snapshot_sql, snapshot_params = next(
        execution
        for execution in connection.cursor_instance.executions
        if "INSERT INTO station_inventory_snapshots" in execution[0]
    )
    assert "station_ids" in snapshot_sql
    assert snapshot_params[:10] == (
        "job-id",
        "official.civil_iot.flood_sensor",
        summary.finished_at,
        1,
        1,
        True,
        1,
        1,
        0,
        0,
    )
    assert snapshot_params[10] == proof.manifest_sha256
    assert json.loads(str(snapshot_params[11])) == ["FS-INVENTORY-1"]
    assert snapshot_params[12] is True

    run_sql, run_params = next(
        execution
        for execution in connection.cursor_instance.executions
        if "INSERT INTO adapter_runs" in execution[0]
    )
    assert "INSERT INTO adapter_runs" in run_sql
    metrics = json.loads(str(run_params[13]))
    assert metrics["station_inventory_proof"]["manifest_sha256"] == proof.manifest_sha256
    assert metrics["station_inventory_proof"]["manifest_version"] == "station-id-json-v1"
    assert "station_ids" not in metrics["station_inventory_proof"]


def test_empty_civil_iot_observations_stay_skipped_but_preserve_inventory_proof() -> None:
    adapter = FloodSensorStaApiAdapter(
        fetched_at=STARTED_AT,
        fetch_json=lambda url, timeout: _civil_iot_inventory_payload(
            with_observation=False
        ),
    )
    connection = _FakeConnection(job_id="job-id")
    run_writer = PostgresIngestionRunWriter(connection_factory=lambda: connection)

    summary = run_adapter_batch(
        adapter,
        run_writer=run_writer,
        job_key="ingest.official.civil_iot.flood_sensor",
    )

    assert summary.status == "skipped"
    assert summary.items_fetched == 0
    assert summary.station_inventory_proof is not None
    assert summary.station_inventory_proof.inventory_complete is True
    assert not any(
        "INSERT INTO adapter_runs" in sql
        for sql, _params in connection.cursor_instance.executions
    )
    snapshot_sql, snapshot_params = next(
        execution
        for execution in connection.cursor_instance.executions
        if "INSERT INTO station_inventory_snapshots" in execution[0]
    )
    assert "INSERT INTO station_inventory_snapshots" in snapshot_sql
    assert json.loads(str(snapshot_params[11])) == ["FS-INVENTORY-1"]
    assert snapshot_params[12] is True


def test_run_adapter_batch_surfaces_operational_summary_write_failure() -> None:
    summary = run_adapter_batch(_EmptyAdapter(), run_writer=_FailingRunWriter())

    assert summary.status == "failed"
    assert summary.items_fetched == 0
    assert summary.error_code == "RuntimeError"
    assert summary.error_message == "run summary write failed: run write failed"


def test_civil_iot_flood_sensor_upstream_failure_marks_failed_summary_and_source_health() -> None:
    adapter = FloodSensorStaApiAdapter(
        fetch_json=lambda url, timeout: (_ for _ in ()).throw(RuntimeError("upstream timeout"))
    )
    connection = _FakeConnection(job_id="job-id")
    run_writer = PostgresIngestionRunWriter(connection_factory=lambda: connection)

    summary = run_adapter_batch(
        adapter,
        writer=_MemoryWriter(),
        run_writer=run_writer,
        job_key="ingest.official.civil_iot.flood_sensor",
    )

    assert summary.adapter_key == "official.civil_iot.flood_sensor"
    assert summary.status == "failed"
    assert summary.items_fetched == 0
    assert summary.error_code == "CivilIotStaFetchError"
    assert summary.error_message == "Flood sensor fetcher failed: upstream timeout"
    source_sql, source_params = connection.cursor_instance.executions[-1]
    assert "UPDATE data_sources" in source_sql
    assert source_params[6] == "failed"
    assert source_params[-2] == "official.civil_iot.flood_sensor"
    assert source_params[-1] == summary.started_at


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
