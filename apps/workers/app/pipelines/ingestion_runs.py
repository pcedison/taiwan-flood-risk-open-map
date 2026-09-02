from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Literal

from app.jobs.ingestion import (
    AdapterBatchRunSummary,
    is_successful_no_active_warning_summary,
)
from app.pipelines.promotion import warning_lifecycle_lock_key

ConnectionFactory = Callable[[], Any]
IngestionJobStatus = Literal["succeeded", "failed", "skipped"]
RuntimePipelineStatus = Literal["succeeded", "failed"]


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
    ) -> str:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                if is_successful_no_active_warning_summary(summary):
                    cursor.execute(
                        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                        (warning_lifecycle_lock_key(summary.adapter_key),),
                    )
                job_id = _insert_ingestion_job(
                    cursor,
                    summary,
                    job_key=job_key,
                    parameters=parameters or {},
                )
                _insert_adapter_run(cursor, summary, ingestion_job_id=job_id)
                _insert_station_inventory_snapshot(
                    cursor,
                    summary,
                    ingestion_job_id=job_id,
                )
                _update_data_source_health(cursor, summary)
            connection.commit()
        return job_id

    def begin_non_operational_summary(
        self,
        summary: AdapterBatchRunSummary,
        *,
        job_key: str,
        parameters: dict[str, Any] | None = None,
    ) -> str:
        """Create a pending audit that cannot become the latest live adapter run."""

        audit_parameters = {
            **(parameters or {}),
            "operational_run": False,
            "audit_state": "pending",
        }
        with self._connect() as connection:
            with connection.cursor() as cursor:
                job_id = _insert_pending_non_operational_job(
                    cursor,
                    summary,
                    job_key=job_key,
                    parameters=audit_parameters,
                )
                _insert_pending_non_operational_adapter_run(
                    cursor,
                    summary,
                    ingestion_job_id=job_id,
                )
            connection.commit()
        return job_id

    def finalize_non_operational_summary(
        self,
        ingestion_job_id: str,
        summary: AdapterBatchRunSummary,
        *,
        job_key: str,
        parameters: dict[str, Any] | None = None,
    ) -> None:
        """Atomically finalize a pending audit without mutating live source health."""

        audit_parameters = {
            **(parameters or {}),
            "operational_run": False,
            "audit_state": "terminal",
        }
        with self._connect() as connection:
            with connection.cursor() as cursor:
                _finalize_non_operational_job(
                    cursor,
                    ingestion_job_id,
                    summary,
                    job_key=job_key,
                    parameters=audit_parameters,
                )
                _finalize_non_operational_adapter_run(
                    cursor,
                    ingestion_job_id,
                    summary,
                )
            connection.commit()

    def write_runtime_selection(
        self,
        *,
        enabled_adapter_keys: tuple[str, ...],
        known_adapter_keys: tuple[str, ...],
        checked_at: datetime | None = None,
    ) -> None:
        if not known_adapter_keys:
            return
        resolved_checked_at = checked_at or datetime.now(UTC)
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE data_sources
                    SET
                        runtime_enabled = (adapter_key = ANY(%s::text[])),
                        runtime_enabled_checked_at = %s,
                        updated_at = now()
                    WHERE adapter_key = ANY(%s::text[])
                    """,
                    (
                        list(enabled_adapter_keys),
                        resolved_checked_at,
                        list(known_adapter_keys),
                    ),
                )
            connection.commit()

    def write_pipeline_status(
        self,
        *,
        adapter_keys: tuple[str, ...],
        status: RuntimePipelineStatus,
        complete: bool,
        checked_at: datetime | None = None,
        run_at: datetime | None = None,
        active_snapshot_raw_ref: str | None = None,
    ) -> None:
        if not adapter_keys:
            return
        if active_snapshot_raw_ref is not None:
            if (
                not active_snapshot_raw_ref
                or active_snapshot_raw_ref != active_snapshot_raw_ref.strip()
                or len(active_snapshot_raw_ref) > 256
            ):
                raise ValueError("active snapshot raw ref must be a trimmed 1..256 value")
            if status != "succeeded" or not complete:
                raise ValueError(
                    "active snapshot requires a succeeded complete pipeline status"
                )
        resolved_checked_at = checked_at or datetime.now(UTC)
        resolved_run_at = run_at or resolved_checked_at
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE data_sources
                    SET
                        runtime_pipeline_status = %s,
                        runtime_pipeline_checked_at = %s,
                        runtime_pipeline_complete = %s,
                        runtime_pipeline_run_at = %s,
                        metadata = CASE
                            WHEN %s::text IS NULL THEN metadata
                            ELSE jsonb_set(
                                COALESCE(metadata, '{}'::jsonb),
                                '{active_snapshot_raw_ref}',
                                to_jsonb(%s::text),
                                true
                            )
                        END,
                        updated_at = now()
                    WHERE adapter_key = ANY(%s::text[])
                        AND (
                            runtime_pipeline_run_at IS NULL
                            OR runtime_pipeline_run_at <= %s
                        )
                        AND NOT EXISTS (
                            SELECT 1
                            FROM ingestion_jobs jobs
                            WHERE jobs.adapter_key = data_sources.adapter_key
                                AND COALESCE(jobs.started_at, jobs.created_at) > %s
                            )
                    """,
                    (
                        status,
                        resolved_checked_at,
                        complete,
                        resolved_run_at,
                        active_snapshot_raw_ref,
                        active_snapshot_raw_ref,
                        list(adapter_keys),
                        resolved_run_at,
                        resolved_run_at,
                    ),
                )
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


def _insert_pending_non_operational_job(
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
            source_timestamp_min,
            source_timestamp_max,
            parameters
        )
        VALUES (%s, NULL, %s, NULL, 'running', %s, 0, %s, %s, %s, %s::jsonb)
        RETURNING id
        """,
        (
            job_key,
            summary.started_at,
            summary.items_fetched,
            summary.items_rejected,
            summary.source_timestamp_min,
            summary.source_timestamp_max,
            _json(dict(parameters)),
        ),
    )
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError("non-operational ingestion audit insert did not return an id")
    return str(row[0])


def _insert_pending_non_operational_adapter_run(
    cursor: Any,
    summary: AdapterBatchRunSummary,
    *,
    ingestion_job_id: str,
) -> None:
    cursor.execute(
        """
        INSERT INTO adapter_runs (
            ingestion_job_id,
            adapter_key,
            started_at,
            status,
            items_fetched,
            items_promoted,
            items_rejected,
            raw_ref,
            source_timestamp_min,
            source_timestamp_max,
            metrics
        )
        VALUES (%s, %s, %s, 'running', %s, 0, %s, %s, %s, %s, %s::jsonb)
        """,
        (
            ingestion_job_id,
            summary.adapter_key,
            summary.started_at,
            summary.items_fetched,
            summary.items_rejected,
            summary.raw_ref,
            summary.source_timestamp_min,
            summary.source_timestamp_max,
            _json(_adapter_run_metrics(summary)),
        ),
    )


def _finalize_non_operational_job(
    cursor: Any,
    ingestion_job_id: str,
    summary: AdapterBatchRunSummary,
    *,
    job_key: str,
    parameters: Mapping[str, Any],
) -> None:
    cursor.execute(
        """
        UPDATE ingestion_jobs
        SET
            finished_at = %s,
            status = %s,
            items_fetched = %s,
            items_promoted = %s,
            items_rejected = %s,
            error_code = %s,
            error_message = %s,
            source_timestamp_min = %s,
            source_timestamp_max = %s,
            parameters = %s::jsonb,
            updated_at = now()
        WHERE id = %s
            AND job_key = %s
            AND adapter_key IS NULL
            AND status = 'running'
        RETURNING id
        """,
        (
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
            ingestion_job_id,
            job_key,
        ),
    )
    if cursor.fetchone() is None:
        raise RuntimeError("pending non-operational ingestion audit was not finalized")


def _finalize_non_operational_adapter_run(
    cursor: Any,
    ingestion_job_id: str,
    summary: AdapterBatchRunSummary,
) -> None:
    cursor.execute(
        """
        UPDATE adapter_runs
        SET
            finished_at = %s,
            status = %s,
            items_fetched = %s,
            items_promoted = %s,
            items_rejected = %s,
            error_code = %s,
            error_message = %s,
            source_timestamp_min = %s,
            source_timestamp_max = %s,
            metrics = %s::jsonb
        WHERE ingestion_job_id = %s
            AND adapter_key = %s
            AND status = 'running'
        RETURNING id
        """,
        (
            summary.finished_at,
            _adapter_run_status(summary),
            summary.items_fetched,
            summary.items_promoted,
            summary.items_rejected,
            summary.error_code,
            summary.error_message,
            summary.source_timestamp_min,
            summary.source_timestamp_max,
            _json(_adapter_run_metrics(summary)),
            ingestion_job_id,
            summary.adapter_key,
        ),
    )
    if cursor.fetchone() is None:
        raise RuntimeError("pending non-operational adapter audit was not finalized")


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
            _json(_adapter_run_metrics(summary)),
        ),
    )


def _insert_station_inventory_snapshot(
    cursor: Any,
    summary: AdapterBatchRunSummary,
    *,
    ingestion_job_id: str,
) -> None:
    proof = summary.station_inventory_proof
    if proof is None:
        return

    cursor.execute(
        """
        INSERT INTO station_inventory_snapshots (
            ingestion_job_id,
            adapter_key,
            captured_at,
            upstream_total,
            pages_fetched,
            pagination_complete,
            source_items_seen,
            station_ids_seen,
            missing_station_id_count,
            duplicate_station_id_count,
            manifest_sha256,
            station_ids,
            inventory_complete
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
        """,
        (
            ingestion_job_id,
            summary.adapter_key,
            summary.finished_at,
            proof.upstream_total,
            proof.pages_fetched,
            proof.pagination_complete,
            proof.source_items_seen,
            proof.station_ids_seen,
            proof.missing_station_id_count,
            proof.duplicate_station_id_count,
            proof.manifest_sha256,
            _json(list(proof.station_ids)),
            proof.inventory_complete,
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
            runtime_pipeline_status = CASE
                WHEN %s = 'failed' THEN 'failed'
                ELSE runtime_pipeline_status
            END,
            runtime_pipeline_checked_at = CASE
                WHEN %s = 'failed' THEN %s
                ELSE runtime_pipeline_checked_at
            END,
            runtime_pipeline_complete = CASE
                WHEN %s = 'failed' THEN false
                ELSE runtime_pipeline_complete
            END,
            runtime_pipeline_run_at = CASE
                WHEN %s = 'failed' THEN %s
                ELSE runtime_pipeline_run_at
            END,
            source_timestamp_min = COALESCE(%s, source_timestamp_min),
            source_timestamp_max = COALESCE(%s, source_timestamp_max),
            updated_at = now()
        WHERE adapter_key = %s
            AND NOT EXISTS (
                SELECT 1
                FROM ingestion_jobs newer_job
                WHERE newer_job.adapter_key = data_sources.adapter_key
                    AND COALESCE(newer_job.started_at, newer_job.created_at) > %s
            )
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
            summary.status,
            summary.status,
            summary.finished_at,
            summary.status,
            summary.status,
            summary.started_at,
            summary.source_timestamp_min,
            summary.source_timestamp_max,
            summary.adapter_key,
            summary.started_at,
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


def _adapter_run_metrics(summary: AdapterBatchRunSummary) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    if summary.error_code == "no_active_event":
        metrics["no_active_event"] = True
    if summary.raw_ref:
        metrics["raw_ref"] = summary.raw_ref
    if summary.station_inventory_proof is not None:
        metrics["station_inventory_proof"] = (
            summary.station_inventory_proof.public_summary()
        )
    return metrics


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
