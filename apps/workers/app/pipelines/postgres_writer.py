from __future__ import annotations

from collections.abc import Callable
import json
from typing import Any
from zoneinfo import ZoneInfo

from app.pipelines.staging import AdapterStagingBatch, StagingEvidenceUpsert


ConnectionFactory = Callable[[], Any]
TAIWAN_TIMEZONE = ZoneInfo("Asia/Taipei")


class PostgresStagingBatchWriter:
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

    def write_batch(self, batch: AdapterStagingBatch) -> None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                raw_snapshot_id = _upsert_raw_snapshot(cursor, batch)
                items = (*batch.accepted, *batch.rejected)
                if items:
                    _insert_staging_evidence_batch(cursor, raw_snapshot_id, items)
            connection.commit()

    def _connect(self) -> Any:
        if self._connection_factory is not None:
            return self._connection_factory()

        import psycopg

        assert self._database_url is not None
        return psycopg.connect(self._database_url)


def _upsert_raw_snapshot(cursor: Any, batch: AdapterStagingBatch) -> str:
    raw = batch.raw_snapshot
    cursor.execute(
        """
        INSERT INTO raw_snapshots (
            data_source_id,
            adapter_key,
            raw_ref,
            content_hash,
            fetched_at,
            source_timestamp_min,
            source_timestamp_max,
            retention_expires_at,
            metadata
        )
        VALUES (
            (SELECT id FROM data_sources WHERE adapter_key = %s),
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s::jsonb
        )
        ON CONFLICT (raw_ref) DO UPDATE SET
            data_source_id = COALESCE(EXCLUDED.data_source_id, raw_snapshots.data_source_id),
            content_hash = EXCLUDED.content_hash,
            fetched_at = EXCLUDED.fetched_at,
            source_timestamp_min = EXCLUDED.source_timestamp_min,
            source_timestamp_max = EXCLUDED.source_timestamp_max,
            retention_expires_at = EXCLUDED.retention_expires_at,
            metadata = EXCLUDED.metadata
        RETURNING id
        """,
        (
            raw.adapter_key,
            raw.adapter_key,
            raw.raw_ref,
            raw.content_hash,
            raw.fetched_at,
            raw.source_timestamp_min,
            raw.source_timestamp_max,
            raw.retention_expires_at,
            _json(raw.metadata),
        ),
    )
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError("raw snapshot upsert did not return an id")
    return str(row[0])


_INSERT_STAGING_EVIDENCE_SQL = """
    INSERT INTO staging_evidence (
        raw_snapshot_id,
        data_source_id,
        source_id,
        source_type,
        event_type,
        title,
        summary,
        url,
        occurred_at,
        observed_at,
        confidence,
        validation_status,
        rejection_reason,
        payload,
        event_year,
        temporal_precision,
        event_start_at,
        event_end_at,
        source_record_key
    )
    VALUES (
        %s,
        (SELECT id FROM data_sources WHERE adapter_key = %s),
        %s,
        %s,
        %s,
        %s,
        %s,
        %s,
        %s,
        %s,
        %s,
        %s,
        %s,
        %s::jsonb,
        %s,
        %s,
        %s,
        %s,
        %s
    )
    """


def _insert_staging_evidence_batch(
    cursor: Any,
    raw_snapshot_id: str,
    items: tuple[StagingEvidenceUpsert, ...],
) -> None:
    params = [_staging_evidence_params(raw_snapshot_id, item) for item in items]
    cursor.executemany(_INSERT_STAGING_EVIDENCE_SQL, params)


def _staging_evidence_params(
    raw_snapshot_id: str,
    item: StagingEvidenceUpsert,
) -> tuple[Any, ...]:
    timestamp = item.occurred_at or item.observed_at
    raw_event_year = item.payload.get("event_year")
    event_year = (
        raw_event_year
        if isinstance(raw_event_year, int) and not isinstance(raw_event_year, bool)
        else timestamp.astimezone(TAIWAN_TIMEZONE).year if timestamp is not None else None
    )
    raw_precision = item.payload.get("temporal_precision")
    temporal_precision = (
        raw_precision
        if raw_precision in {"instant", "day", "month", "year", "unknown"}
        else "instant" if timestamp is not None else "unknown"
    )
    source_record_key = item.payload.get("source_record_key")
    if not isinstance(source_record_key, str) or not source_record_key.strip():
        source_record_key = item.source_id
    event_start_at = None if temporal_precision == "year" else timestamp
    event_end_at = (
        None
        if temporal_precision == "year"
        else item.observed_at or item.occurred_at
    )
    return (
        raw_snapshot_id,
        item.adapter_key,
        item.source_id,
        item.source_type,
        item.event_type,
        item.title,
        item.summary,
        item.url,
        item.occurred_at,
        item.observed_at,
        item.confidence,
        item.validation_status,
        item.rejection_reason,
        _json(
            {
                **item.payload,
                "evidence_id": item.evidence_id,
                "adapter_key": item.adapter_key,
                "raw_ref": item.raw_ref,
            }
        ),
        event_year,
        temporal_precision,
        event_start_at,
        event_end_at,
        source_record_key,
    )


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))
