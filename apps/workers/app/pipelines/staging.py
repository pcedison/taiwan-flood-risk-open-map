from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
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


def build_staging_batch(
    result: AdapterRunResult,
    *,
    raw_ref: str | None = None,
    ingestion_generation_started_at: datetime | None = None,
) -> AdapterStagingBatch:
    if not result.fetched:
        raise ValueError("adapter run must include at least one fetched raw item before staging")
    if ingestion_generation_started_at is not None and (
        ingestion_generation_started_at.tzinfo is None
        or ingestion_generation_started_at.utcoffset() is None
    ):
        raise ValueError("ingestion generation must be timezone-aware")

    validation = validate_evidence_for_promotion(result.normalized)
    raw_snapshot = build_raw_snapshot(result, raw_ref=raw_ref)
    raw_by_source_id = {item.source_id: item for item in result.fetched}
    accepted_items: list[StagingEvidenceUpsert] = []
    metadata_rejected_items: list[StagingEvidenceUpsert] = []
    for evidence in validation.accepted:
        raw_item = raw_by_source_id.get(evidence.source_id)
        metadata_errors = _staging_metadata_errors(
            raw_item,
            event_type=evidence.event_type.value,
            ingestion_generation_started_at=ingestion_generation_started_at,
        )
        target = metadata_rejected_items if metadata_errors else accepted_items
        target.append(
            _to_staging_upsert(
                evidence,
                raw_snapshot.raw_ref,
                "rejected" if metadata_errors else "accepted",
                (
                    "invalid staging metadata: " + "; ".join(metadata_errors)
                    if metadata_errors
                    else None
                ),
                raw_item,
                (
                    ingestion_generation_started_at
                    if not metadata_errors
                    else None
                ),
            )
        )

    accepted = tuple(accepted_items)
    rejected = tuple(metadata_rejected_items) + tuple(
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


_EVIDENCE_SCOPES = frozenset({"current", "historical", "context"})
_LOCATION_PRECISIONS = frozenset(
    {
        "point",
        "road_or_lane",
        "poi",
        "admin_area",
        "polygon",
        "inferred",
        "map_click",
        "unknown",
    }
)


def _staging_metadata_errors(
    raw_item: Any | None,
    *,
    event_type: str,
    ingestion_generation_started_at: datetime | None,
) -> tuple[str, ...]:
    if raw_item is None or not isinstance(raw_item.payload, Mapping):
        return ()
    raw_payload = raw_item.payload
    errors: list[str] = []

    evidence_scope = raw_payload.get("evidence_scope")
    if evidence_scope is not None and evidence_scope not in _EVIDENCE_SCOPES:
        errors.append("evidence_scope is not reviewed")

    location_precision = raw_payload.get("location_precision")
    if location_precision is not None and location_precision not in _LOCATION_PRECISIONS:
        errors.append("location_precision is not public")

    admin_code = raw_payload.get("admin_code")
    if admin_code is not None and (
        not isinstance(admin_code, str)
        or re.fullmatch(r"\d{8}", admin_code) is None
    ):
        errors.append("admin_code must be a canonical 8-digit code")

    limitations = raw_payload.get("limitations")
    if limitations is not None:
        if not isinstance(limitations, (list, tuple)):
            errors.append("limitations must be a list")
        else:
            canonical_limitations: list[str] = []
            for value in limitations:
                if not isinstance(value, str) or not value.strip() or len(value.strip()) > 256:
                    errors.append("limitations must contain 1..256 character strings")
                    break
                if value.strip() not in canonical_limitations:
                    canonical_limitations.append(value.strip())
            if len(canonical_limitations) > 16:
                errors.append("limitations must contain at most 16 unique values")

    dataset_revision = raw_payload.get("dataset_revision")
    if dataset_revision is not None and (
        not isinstance(dataset_revision, str)
        or not dataset_revision.strip()
        or len(dataset_revision.strip()) > 256
    ):
        errors.append("dataset_revision must be a 1..256 character string")

    cap_keys = {
        "cap_sender",
        "cap_identifier",
        "cap_sent",
        "cap_references",
        "cap_status",
        "cap_message_type",
        "active_from",
        "active_until",
    }
    if event_type != "flood_warning":
        if any(key in raw_payload for key in cap_keys):
            errors.append("CAP lifecycle fields require flood_warning")
        return tuple(errors)

    if ingestion_generation_started_at is None:
        errors.append("CAP lifecycle requires an ingestion generation")
    sender = raw_payload.get("cap_sender")
    identifier = raw_payload.get("cap_identifier")
    for name, value in (("cap_sender", sender), ("cap_identifier", identifier)):
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > 512:
            errors.append(f"{name} must be a 1..512 character string")
    sent = _aware_rfc3339(raw_payload.get("cap_sent"))
    if sent is None:
        errors.append("cap_sent must be timezone-aware RFC3339")
    if raw_payload.get("cap_status") != "Actual":
        errors.append("cap_status must be Actual")
    message_type = raw_payload.get("cap_message_type")
    if message_type not in {"Alert", "Update", "Cancel"}:
        errors.append("cap_message_type is invalid")
    references = raw_payload.get("cap_references")
    if not isinstance(references, list):
        errors.append("cap_references must be a list")
        reference_count = 0
    else:
        canonical_references = _canonical_cap_references(references)
        if canonical_references is None:
            errors.append("cap_references must contain exact canonical triples")
            reference_count = 0
        else:
            reference_count = len(canonical_references)
            if reference_count > 64:
                errors.append("cap_references must contain at most 64 unique triples")
    if message_type in {"Update", "Cancel"} and reference_count == 0:
        errors.append("Update and Cancel require an earlier reference")
    if message_type in {"Alert", "Update"}:
        active_from = _aware_rfc3339(raw_payload.get("active_from"))
        active_until = _aware_rfc3339(raw_payload.get("active_until"))
        if active_from is None or active_until is None or active_from >= active_until:
            errors.append("Alert and Update require a valid active window")
    return tuple(errors)


def _aware_rfc3339(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _canonical_cap_references(value: list[object]) -> list[dict[str, str]] | None:
    canonical: dict[tuple[str, str, str], dict[str, str]] = {}
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {"sender", "identifier", "sent"}:
            return None
        sender = item.get("sender")
        identifier = item.get("identifier")
        sent = _aware_rfc3339(item.get("sent"))
        if (
            not isinstance(sender, str)
            or not sender.strip()
            or len(sender.strip()) > 512
            or not isinstance(identifier, str)
            or not identifier.strip()
            or len(identifier.strip()) > 512
            or sent is None
        ):
            return None
        sent_text = sent.astimezone(UTC).isoformat()
        key = (sender.strip(), identifier.strip(), sent_text)
        canonical[key] = {"sender": key[0], "identifier": key[1], "sent": key[2]}
    return [canonical[key] for key in sorted(canonical)]


def build_raw_snapshot(result: AdapterRunResult, *, raw_ref: str | None = None) -> RawSnapshotUpsert:
    if not result.fetched:
        raise ValueError("adapter run must include at least one fetched raw item before raw snapshot")

    content_hash = _content_hash(result)
    source_timestamps = tuple(evidence.source_timestamp for evidence in result.normalized)
    fetched_at = max(item.fetched_at for item in result.fetched)
    source_family = _source_family_for_retention(result)
    metadata: dict[str, Any] = {
        "items_fetched": len(result.fetched),
        "items_normalized": len(result.normalized),
        "items_rejected": len(result.rejected),
        "retention_source_family": source_family.value,
    }
    if result.station_inventory_proof is not None:
        # Counts and the manifest checksum are public-safe diagnostics.  The
        # full station-ID manifest belongs only in station_inventory_snapshots.
        metadata.update(result.station_inventory_proof.public_summary())

    return RawSnapshotUpsert(
        adapter_key=result.adapter_key,
        raw_ref=raw_ref or _raw_ref(result, content_hash),
        content_hash=content_hash,
        fetched_at=fetched_at,
        source_timestamp_min=min(source_timestamps) if source_timestamps else None,
        source_timestamp_max=max(source_timestamps) if source_timestamps else None,
        retention_expires_at=fetched_at
        + timedelta(days=RETENTION_DAYS_BY_SOURCE_FAMILY[source_family]),
        metadata=metadata,
    )


def persist_staging_batch(batch: AdapterStagingBatch, writer: StagingBatchWriter) -> None:
    writer.write_batch(batch)


def _to_staging_upsert(
    evidence: NormalizedEvidence,
    raw_ref: str,
    validation_status: ValidationStatus,
    rejection_reason: str | None,
    raw_item: Any | None,
    ingestion_generation_started_at: datetime | None = None,
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
        observed_at=evidence.source_timestamp,
        confidence=evidence.confidence,
        validation_status=validation_status,
        rejection_reason=rejection_reason,
        payload={
            "location_text": evidence.location_text,
            **_location_payload(raw_item),
            **_realtime_metrics_payload(raw_item),
            **_passthrough_payload(raw_item, event_type=evidence.event_type.value),
            **(
                {
                    "ingestion_generation_started_at": (
                        ingestion_generation_started_at.isoformat()
                    )
                }
                if ingestion_generation_started_at is not None
                else {}
            ),
            "attribution": evidence.attribution,
            "tags": list(evidence.tags),
        },
    )


# Realtime station intensity metrics carried into evidence.properties so the API
# can derive an intensity-aware risk factor (a dry rainfall station then scores
# low instead of inflating realtime risk by mere presence).
_REALTIME_METRIC_KEYS: tuple[str, ...] = (
    "rainfall_mm",
    "rainfall_mm_10m",
    "rainfall_mm_1h",
    "rainfall_mm_3h",
    "rainfall_mm_6h",
    "rainfall_mm_12h",
    "rainfall_mm_24h",
    "flood_depth_cm",
    "water_level_m",
    "warning_level_m",
)

_STAGING_PAYLOAD_PASSTHROUGH_KEYS: tuple[str, ...] = (
    "station_id",
    "station_name",
    "authority",
    "station_type",
    "station_attribute",
    "alarm_state",
    "status_only",
    "source_url",
    "resource_url",
    "station_metadata_url",
    "source_weight",
    "county",
    "town",
    "area",
    "tide_level_label",
    "county_code",
    "area_code",
    "areaDesc",
    "identifier",
    "effective",
    "expires",
    "expired",
    "severity",
    "certainty",
    "urgency",
    "evidence_scope",
    "location_precision",
    "limitations",
    "admin_code",
    "dataset_revision",
)


def _realtime_metrics_payload(raw_item: Any | None) -> dict[str, Any]:
    if raw_item is None or not isinstance(raw_item.payload, Mapping):
        return {}
    metrics: dict[str, Any] = {}
    for key in _REALTIME_METRIC_KEYS:
        value = raw_item.payload.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            metrics[key] = float(value)
    return metrics


def _passthrough_payload(raw_item: Any | None, *, event_type: str) -> dict[str, Any]:
    if raw_item is None or not isinstance(raw_item.payload, Mapping):
        return {}

    payload: dict[str, Any] = {}
    for key in _STAGING_PAYLOAD_PASSTHROUGH_KEYS:
        value = raw_item.payload.get(key)
        if value is not None:
            payload[key] = value

    limitations = raw_item.payload.get("limitations")
    if isinstance(limitations, (list, tuple)):
        retained: list[str] = []
        for value in limitations:
            text = str(value).strip()
            if text and text not in retained:
                retained.append(text)
        payload["limitations"] = retained

    dataset_revision = raw_item.payload.get("dataset_revision")
    if isinstance(dataset_revision, str) and dataset_revision.strip():
        payload["dataset_revision"] = dataset_revision.strip()

    if event_type == "flood_warning":
        for key in (
            "cap_sender",
            "cap_identifier",
            "cap_sent",
            "cap_status",
            "cap_message_type",
            "active_from",
            "active_until",
        ):
            value = raw_item.payload.get(key)
            if value is not None:
                payload[key] = value.strip() if isinstance(value, str) else value
        references = raw_item.payload.get("cap_references")
        if isinstance(references, list):
            canonical_references = _canonical_cap_references(references)
            if canonical_references is not None:
                payload["cap_references"] = canonical_references
        status = raw_item.payload.get("status")
        if status is not None:
            payload["cap_status"] = status

    return payload


def _location_payload(raw_item: Any | None) -> dict[str, Any]:
    if raw_item is None or not isinstance(raw_item.payload, Mapping):
        return {}

    payload: dict[str, Any] = {}
    geometry = raw_item.payload.get("geometry")
    if isinstance(geometry, Mapping):
        payload["location_payload"] = {"geometry": dict(geometry)}

    query_place = raw_item.payload.get("query_place")
    if isinstance(query_place, Mapping):
        location_payload = payload.setdefault("location_payload", {})
        location_payload["query_place"] = dict(query_place)
    return payload


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
