from __future__ import annotations

from collections.abc import Callable, Mapping
import json
from typing import Any, Literal

from app.jobs.ingestion import AdapterBatchRunSummary


ConnectionFactory = Callable[[], Any]
IngestionJobStatus = Literal["succeeded", "failed", "skipped"]


class PostgresIngestionRunWriter:
    def __init__(
        self,
        *,
        database_url: str | None = None,
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        if database_url is None and connection_factory is None:
            raise ValueError("database_url or connection_factory is required")
        self._database_url = database_url
        self._connection_factory = connection_factory

    def write_summary(
        self,
        summary: AdapterBatchRunSummary,
        *,
        job_key: str,
        parameters: dict[str, Any] | None = None,
    ) -> None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                job_id = _insert_ingestion_job(
                    cursor,
                    summary,
                    job_key=job_key,
                    parameters=parameters or {},
                )
                _insert_adapter_run(cursor, summary, ingestion_job_id=job_id)
                _update_data_source_health(cursor, summary)
            connection.commit()

    def _connect(self) -> Any:
        if self._connection_factory is not None:
            return self._connection_factory()

        import psycopg

        assert self._database_url is not None
        return psycopg.connect(self._database_url)


def _insert_ingestion_job(
    cursor: Any,
    summary: AdapterBatchRunSummary,
    *,
    job_key: str,
    parameters: Mapping[str, Any],
) -> str:
    cursor.execute(
        """
        INSERT INTO ingestion_jobs (
            job_key,
            adapter_key,
            started_at,
            finished_at,
            status,
            items_fetched,
            items_promoted,
            items_rejected,
            error_code,
            error_message,
            source_timestamp_min,
            source_timestamp_max,
            parameters
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        RETURNING id
        """,
        (
            job_key,
            summary.adapter_key,
            summary.started_at,
            summary.finished_at,
            _job_status(summary),
            summary.items_fetched,
            summary.items_promoted,
            summary.items_rejected,
            summary.error_code,
            summary.error_message,
            summary.source_timestamp_min,
            summary.source_timestamp_max,
            _json(dict(parameters)),
        ),
    )
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError("ingestion job insert did not return an id")
    return str(row[0])


def _insert_adapter_run(
    cursor: Any,
    summary: AdapterBatchRunSummary,
    *,
    ingestion_job_id: str,
) -> None:
    if summary.status == "skipped":
        return

    cursor.execute(
        """
        INSERT INTO adapter_runs (
            ingestion_job_id,
            adapter_key,
            started_at,
            finished_at,
            status,
            items_fetched,
            items_promoted,
            items_rejected,
            raw_ref,
            error_code,
            error_message,
            source_timestamp_min,
            source_timestamp_max,
            metrics
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        """,
        (
            ingestion_job_id,
            summary.adapter_key,
            summary.started_at,
            summary.finished_at,
            _adapter_run_status(summary),
            summary.items_fetched,
            summary.items_promoted,
            summary.items_rejected,
            summary.raw_ref,
            summary.error_code,
            summary.error_message,
            summary.source_timestamp_min,
            summary.source_timestamp_max,
            _json({"raw_ref": summary.raw_ref} if summary.raw_ref else {}),
        ),
    )


def _update_data_source_health(cursor: Any, summary: AdapterBatchRunSummary) -> None:
    cursor.execute(
        """
        UPDATE data_sources
        SET
            last_success_at = CASE
                WHEN %s IN ('succeeded', 'partial') THEN %s
                ELSE last_success_at
            END,
            last_failure_at = CASE
                WHEN %s = 'failed' THEN %s
                ELSE last_failure_at
            END,
            health_status = CASE
                WHEN %s = 'succeeded' THEN 'healthy'
                WHEN %s = 'partial' THEN 'degraded'
                WHEN %s = 'failed' THEN 'failed'
                WHEN %s = 'skipped' THEN 'unknown'
                ELSE health_status
            END,
            source_timestamp_min = COALESCE(%s, source_timestamp_min),
            source_timestamp_max = COALESCE(%s, source_timestamp_max),
            updated_at = now()
        WHERE adapter_key = %s
        """,
        (
            summary.status,
            summary.finished_at,
            summary.status,
            summary.finished_at,
            summary.status,
            summary.status,
            summary.status,
            summary.status,
            summary.source_timestamp_min,
            summary.source_timestamp_max,
            summary.adapter_key,
        ),
    )


def _job_status(summary: AdapterBatchRunSummary) -> IngestionJobStatus:
    if summary.status == "partial":
        return "succeeded"
    return summary.status


def _adapter_run_status(summary: AdapterBatchRunSummary) -> Literal["succeeded", "failed", "partial"]:
    if summary.status == "skipped":
        raise ValueError("skipped summaries do not create adapter_runs")
    return summary.status


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
