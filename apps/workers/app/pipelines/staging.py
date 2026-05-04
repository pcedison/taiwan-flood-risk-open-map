from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Any, Literal, Protocol

from app.adapters.contracts import AdapterRunResult, NormalizedEvidence, SourceFamily
from app.pipelines.validation import validate_evidence_for_promotion


ValidationStatus = Literal["accepted", "rejected"]


RETENTION_DAYS_BY_SOURCE_FAMILY: dict[SourceFamily, int] = {
    SourceFamily.OFFICIAL: 180,
    SourceFamily.NEWS: 60,
    SourceFamily.FORUM: 30,
    SourceFamily.SOCIAL: 30,
    SourceFamily.USER_REPORT: 90,
    SourceFamily.DERIVED: 180,
}


@dataclass(frozen=True)
class RawSnapshotUpsert:
    adapter_key: str
    raw_ref: str
    content_hash: str
    fetched_at: datetime
    source_timestamp_min: datetime | None
    source_timestamp_max: datetime | None
    retention_expires_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StagingEvidenceUpsert:
    raw_ref: str
    evidence_id: str
    adapter_key: str
    source_id: str
    source_type: str
    event_type: str
    title: str
    summary: str
    url: str
    occurred_at: datetime
    observed_at: datetime
    confidence: float
    validation_status: ValidationStatus
    rejection_reason: str | None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AdapterStagingBatch:
    adapter_key: str
    raw_snapshot: RawSnapshotUpsert
    accepted: tuple[StagingEvidenceUpsert, ...]
    rejected: tuple[StagingEvidenceUpsert, ...]
    rejected_raw_source_ids: tuple[str, ...] = field(default_factory=tuple)


class StagingBatchWriter(Protocol):
    def write_batch(self, batch: AdapterStagingBatch) -> None:
        """Persist a prepared raw snapshot and staging evidence batch."""


def build_staging_batch(result: AdapterRunResult, *, raw_ref: str | None = None) -> AdapterStagingBatch:
    if not result.fetched:
        raise ValueError("adapter run must include at least one fetched raw item before staging")

    validation = validate_evidence_for_promotion(result.normalized)
    raw_snapshot = build_raw_snapshot(result, raw_ref=raw_ref)
    raw_by_source_id = {item.source_id: item for item in result.fetched}
    accepted = tuple(
        _to_staging_upsert(
            evidence,
            raw_snapshot.raw_ref,
            "accepted",
            None,
            raw_by_source_id.get(evidence.source_id),
        )
        for evidence in validation.accepted
    )
    rejected = tuple(
        _to_staging_upsert(
            evidence,
            raw_snapshot.raw_ref,
            "rejected",
            "; ".join(errors),
            raw_by_source_id.get(evidence.source_id),
        )
        for evidence, errors in validation.rejected
    )

    return AdapterStagingBatch(
        adapter_key=result.adapter_key,
        raw_snapshot=raw_snapshot,
        accepted=accepted,
        rejected=rejected,
        rejected_raw_source_ids=result.rejected,
    )


def build_raw_snapshot(result: AdapterRunResult, *, raw_ref: str | None = None) -> RawSnapshotUpsert:
    if not result.fetched:
        raise ValueError("adapter run must include at least one fetched raw item before raw snapshot")

    content_hash = _content_hash(result)
    source_timestamps = tuple(evidence.source_timestamp for evidence in result.normalized)
    fetched_at = max(item.fetched_at for item in result.fetched)
    source_family = _source_family_for_retention(result)

    return RawSnapshotUpsert(
        adapter_key=result.adapter_key,
        raw_ref=raw_ref or _raw_ref(result, content_hash),
        content_hash=content_hash,
        fetched_at=fetched_at,
        source_timestamp_min=min(source_timestamps) if source_timestamps else None,
        source_timestamp_max=max(source_timestamps) if source_timestamps else None,
        retention_expires_at=fetched_at
        + timedelta(days=RETENTION_DAYS_BY_SOURCE_FAMILY[source_family]),
        metadata={
            "items_fetched": len(result.fetched),
            "items_normalized": len(result.normalized),
            "items_rejected": len(result.rejected),
            "retention_source_family": source_family.value,
        },
    )


def persist_staging_batch(batch: AdapterStagingBatch, writer: StagingBatchWriter) -> None:
    writer.write_batch(batch)


def _to_staging_upsert(
    evidence: NormalizedEvidence,
    raw_ref: str,
    validation_status: ValidationStatus,
    rejection_reason: str | None,
    raw_item: Any | None,
) -> StagingEvidenceUpsert:
    return StagingEvidenceUpsert(
        raw_ref=raw_ref,
        evidence_id=evidence.evidence_id,
        adapter_key=evidence.adapter_key,
        source_id=evidence.source_id,
        source_type=evidence.source_family.value,
        event_type=evidence.event_type.value,
        title=evidence.source_title,
        summary=evidence.summary,
        url=evidence.source_url,
        occurred_at=evidence.source_timestamp,
        observed_at=evidence.fetched_at,
        confidence=evidence.confidence,
        validation_status=validation_status,
        rejection_reason=rejection_reason,
        payload={
            "location_text": evidence.location_text,
            **_location_payload(raw_item),
            "attribution": evidence.attribution,
            "tags": list(evidence.tags),
        },
    )


def _location_payload(raw_item: Any | None) -> dict[str, Any]:
    if raw_item is None or not isinstance(raw_item.payload, Mapping):
        return {}

    geometry = raw_item.payload.get("geometry")
    if isinstance(geometry, Mapping):
        return {"location_payload": {"geometry": dict(geometry)}}
    return {}


def _content_hash(result: AdapterRunResult) -> str:
    payloads = [item.payload for item in result.fetched]
    raw_json = json.dumps(payloads, sort_keys=True, default=_json_default, separators=(",", ":"))
    return sha256(raw_json.encode("utf-8")).hexdigest()


def _raw_ref(result: AdapterRunResult, content_hash: str) -> str:
    raw_snapshot_keys = {item.raw_snapshot_key for item in result.fetched if item.raw_snapshot_key}
    if len(raw_snapshot_keys) == 1:
        return raw_snapshot_keys.pop()
    adapter_path = result.adapter_key.replace(".", "/")
    return f"raw/{adapter_path}/{content_hash[:16]}.json"


def _source_family_for_retention(result: AdapterRunResult) -> SourceFamily:
    families = {evidence.source_family for evidence in result.normalized}
    if len(families) == 1:
        return families.pop()
    if result.adapter_key.startswith("official."):
        return SourceFamily.OFFICIAL
    if result.adapter_key.startswith("news."):
        return SourceFamily.NEWS
    return SourceFamily.DERIVED


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)
