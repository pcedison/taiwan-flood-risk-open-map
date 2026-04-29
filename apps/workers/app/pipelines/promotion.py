from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
import json
from typing import Any, Protocol


ConnectionFactory = Callable[[], Any]


@dataclass(frozen=True)
class PromotionCandidate:
    staging_evidence_id: str
    raw_snapshot_id: str | None
    raw_ref: str | None
    data_source_id: str | None
    source_id: str
    source_type: str
    event_type: str
    title: str
    summary: str
    url: str | None
    occurred_at: datetime | None
    observed_at: datetime | None
    confidence: float
    validation_status: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvidencePromotionPayload:
    data_source_id: str | None
    adapter_key: str | None
    source_id: str
    source_type: str
    event_type: str
    title: str
    summary: str
    url: str | None
    occurred_at: datetime | None
    observed_at: datetime | None
    confidence: float
    raw_ref: str | None
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PromotionResult:
    promoted: int
    evidence_ids: tuple[str, ...]


class EvidencePromotionWriter(Protocol):
    def fetch_accepted_staging(self, *, limit: int | None = None) -> tuple[PromotionCandidate, ...]:
        """Load staging rows that are ready to become evidence records."""

    def write_evidence(self, payload: EvidencePromotionPayload) -> str:
        """Persist one promoted evidence record and return its evidence id."""


def build_evidence_promotion_payload(candidate: PromotionCandidate) -> EvidencePromotionPayload:
    if candidate.validation_status != "accepted":
        raise ValueError("only accepted staging evidence can be promoted")

    return EvidencePromotionPayload(
        data_source_id=candidate.data_source_id,
        adapter_key=_payload_adapter_key(candidate.payload),
        source_id=candidate.source_id,
        source_type=candidate.source_type,
        event_type=candidate.event_type,
        title=candidate.title,
        summary=candidate.summary,
        url=candidate.url,
        occurred_at=candidate.occurred_at,
        observed_at=candidate.observed_at,
        confidence=candidate.confidence,
        raw_ref=candidate.raw_ref,
        properties={
            **candidate.payload,
            "staging_evidence_id": candidate.staging_evidence_id,
            "raw_snapshot_id": candidate.raw_snapshot_id,
        },
    )


def promote_accepted_staging(
    writer: EvidencePromotionWriter,
    *,
    limit: int | None = None,
) -> PromotionResult:
    evidence_ids = tuple(
        writer.write_evidence(build_evidence_promotion_payload(candidate))
        for candidate in writer.fetch_accepted_staging(limit=limit)
    )
    return PromotionResult(promoted=len(evidence_ids), evidence_ids=evidence_ids)


class PostgresEvidencePromotionWriter:
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

    def fetch_accepted_staging(self, *, limit: int | None = None) -> tuple[PromotionCandidate, ...]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(_accepted_staging_sql(limit=limit), _accepted_staging_params(limit=limit))
                return tuple(_candidate_from_row(row) for row in cursor.fetchall())

    def write_evidence(self, payload: EvidencePromotionPayload) -> str:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO evidence (
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
                        raw_ref,
                        ingestion_status,
                        properties
                    )
                    VALUES (
                        COALESCE(%s, (SELECT id FROM data_sources WHERE adapter_key = %s)),
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
                        'accepted',
                        %s::jsonb
                    )
                    RETURNING id
                    """,
                    (
                        payload.data_source_id,
                        payload.adapter_key,
                        payload.source_id,
                        payload.source_type,
                        payload.event_type,
                        payload.title,
                        payload.summary,
                        payload.url,
                        payload.occurred_at,
                        payload.observed_at,
                        payload.confidence,
                        payload.raw_ref,
                        _json(payload.properties),
                    ),
                )
                row = cursor.fetchone()
                if row is None:
                    raise RuntimeError("evidence insert did not return an id")
            connection.commit()

        return str(row[0])

    def _connect(self) -> Any:
        if self._connection_factory is not None:
            return self._connection_factory()

        import psycopg

        assert self._database_url is not None
        return psycopg.connect(self._database_url)


def _accepted_staging_sql(*, limit: int | None) -> str:
    limit_clause = "LIMIT %s" if limit is not None else ""
    return f"""
        SELECT
            se.id,
            se.raw_snapshot_id,
            rs.raw_ref,
            COALESCE(se.data_source_id, rs.data_source_id, ds.id) AS data_source_id,
            se.source_id,
            se.source_type,
            se.event_type,
            se.title,
            se.summary,
            se.url,
            se.occurred_at,
            se.observed_at,
            se.confidence,
            se.validation_status,
            se.payload
        FROM staging_evidence se
        LEFT JOIN raw_snapshots rs ON rs.id = se.raw_snapshot_id
        LEFT JOIN data_sources ds ON ds.adapter_key = COALESCE(se.payload ->> 'adapter_key', rs.adapter_key)
        WHERE se.validation_status = 'accepted'
            AND NOT EXISTS (
                SELECT 1
                FROM evidence e
                WHERE e.source_id = se.source_id
                    AND e.raw_ref IS NOT DISTINCT FROM rs.raw_ref
            )
        ORDER BY se.created_at ASC, se.id ASC
        {limit_clause}
    """


def _accepted_staging_params(*, limit: int | None) -> tuple[object, ...]:
    if limit is None:
        return ()
    if limit < 1:
        raise ValueError("limit must be greater than 0")
    return (limit,)


def _candidate_from_row(row: tuple[Any, ...]) -> PromotionCandidate:
    payload = row[14]
    if isinstance(payload, str):
        payload = json.loads(payload)
    if payload is None:
        payload = {}

    return PromotionCandidate(
        staging_evidence_id=str(row[0]),
        raw_snapshot_id=str(row[1]) if row[1] is not None else None,
        raw_ref=str(row[2]) if row[2] is not None else None,
        data_source_id=str(row[3]) if row[3] is not None else None,
        source_id=str(row[4]),
        source_type=str(row[5]),
        event_type=str(row[6]),
        title=str(row[7]),
        summary=str(row[8]),
        url=str(row[9]) if row[9] is not None else None,
        occurred_at=row[10],
        observed_at=row[11],
        confidence=float(row[12]),
        validation_status=str(row[13]),
        payload=dict(payload),
    )


def _payload_adapter_key(payload: dict[str, Any]) -> str | None:
    adapter_key = payload.get("adapter_key")
    return str(adapter_key) if adapter_key else None


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))
