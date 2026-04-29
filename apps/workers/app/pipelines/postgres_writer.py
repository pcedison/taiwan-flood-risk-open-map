from __future__ import annotations

from collections.abc import Callable
import json
from typing import Any

from app.pipelines.staging import AdapterStagingBatch, StagingEvidenceUpsert


ConnectionFactory = Callable[[], Any]


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
                for item in (*batch.accepted, *batch.rejected):
                    _insert_staging_evidence(cursor, raw_snapshot_id, item)
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


def _insert_staging_evidence(
    cursor: Any,
    raw_snapshot_id: str,
    item: StagingEvidenceUpsert,
) -> None:
    cursor.execute(
        """
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
            payload
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
            %s::jsonb
        )
        """,
        (
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
        ),
    )


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))
