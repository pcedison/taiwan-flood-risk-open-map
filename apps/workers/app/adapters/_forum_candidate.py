from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from app.adapters._helpers import optional_str, parse_datetime, stable_evidence_id
from app.adapters.contracts import (
    AdapterMetadata,
    AdapterRunResult,
    EventType,
    IngestionStatus,
    NormalizedEvidence,
    RawSourceItem,
)


class ForumCandidateFixtureAdapter:
    """No-network candidate adapter for synthetic forum fixture records."""

    metadata: AdapterMetadata

    def __init__(
        self,
        records: Iterable[Mapping[str, Any]],
        *,
        metadata: AdapterMetadata,
        platform: str,
        source_approval_status: str,
        disabled_reason: str,
        required_acceptance_fields: tuple[str, ...],
        fetched_at: datetime | None = None,
        raw_snapshot_key: str | None = None,
    ) -> None:
        self.metadata = metadata
        self._records = tuple(records)
        self._fetched_at = fetched_at or datetime.now(UTC)
        self._raw_snapshot_key = raw_snapshot_key
        self._governance_metadata = {
            "platform": platform,
            "source_approval_status": source_approval_status,
            "disabled_reason": disabled_reason,
            "required_acceptance_fields": list(required_acceptance_fields),
            "candidate_contract": {
                "runtime_mode": "local_fixture_only",
                "fixture_records": "synthetic_only",
                "network_access": "disabled",
                "real_source_records": False,
                "http_fetch": False,
                "crawl": False,
                "scrape": False,
                "login_bypass": False,
                "anti_bot_circumvention": False,
                "raw_content_storage": False,
                "identity_storage": False,
            },
        }

    @property
    def governance_metadata(self) -> Mapping[str, Any]:
        return dict(self._governance_metadata)

    def fetch(self) -> tuple[RawSourceItem, ...]:
        return tuple(
            RawSourceItem(
                source_id=str(record["id"]),
                source_url=str(record["url"]),
                fetched_at=self._fetched_at,
                payload=self._fixture_payload(record),
                raw_snapshot_key=self._raw_snapshot_key,
            )
            for record in self._records
        )

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        payload = raw_item.payload
        if payload.get("fixture_kind") != "synthetic_forum_candidate":
            return None

        title = str(payload.get("title", "")).strip()
        summary = str(payload.get("summary", "")).strip()
        published_at = parse_datetime(payload.get("published_at"))
        if not title or not summary or published_at is None:
            return None

        return NormalizedEvidence(
            evidence_id=stable_evidence_id(self.metadata.key, raw_item.source_id),
            adapter_key=self.metadata.key,
            source_family=self.metadata.family,
            event_type=EventType.DISCUSSION,
            source_id=raw_item.source_id,
            source_url=raw_item.source_url,
            source_title=title,
            source_timestamp=published_at,
            fetched_at=raw_item.fetched_at,
            summary=summary,
            location_text=optional_str(payload.get("location_text")),
            confidence=_safe_confidence(payload.get("confidence")),
            status=IngestionStatus.NORMALIZED,
            attribution=optional_str(payload.get("attribution")),
            tags=_fixture_tags(payload.get("tags")),
        )

    def run(self) -> AdapterRunResult:
        fetched = self.fetch()
        normalized: list[NormalizedEvidence] = []
        rejected: list[str] = []

        for raw_item in fetched:
            evidence = self.normalize(raw_item)
            if evidence is None:
                rejected.append(raw_item.source_id)
            else:
                normalized.append(evidence)

        return AdapterRunResult(
            adapter_key=self.metadata.key,
            fetched=fetched,
            normalized=tuple(normalized),
            rejected=tuple(rejected),
        )

    def _fixture_payload(self, record: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "fixture_kind": "synthetic_forum_candidate",
            "id": str(record["id"]),
            "url": str(record["url"]),
            "title": str(record.get("title", "")).strip(),
            "summary": str(record.get("summary", "")).strip(),
            "published_at": str(record.get("published_at", "")).strip(),
            "location_text": optional_str(record.get("location_text")),
            "confidence": _safe_confidence(record.get("confidence")),
            "attribution": optional_str(record.get("attribution")),
            "tags": list(_fixture_tags(record.get("tags"))),
            "governance": dict(self._governance_metadata),
        }


def _fixture_tags(value: object) -> tuple[str, ...]:
    tags: tuple[str, ...]
    if isinstance(value, str):
        tags = (value,)
    elif isinstance(value, Iterable):
        tags = tuple(str(item) for item in value)
    else:
        tags = ()
    return tuple(
        dict.fromkeys(
            (
                *[tag.strip() for tag in tags if tag.strip()],
                "forum-candidate-fixture",
                "synthetic",
            )
        )
    )


def _safe_confidence(value: object) -> float:
    try:
        confidence = float(value if isinstance(value, int | float) else str(value))
    except (TypeError, ValueError):
        return 0.5
    return max(0.0, min(confidence, 1.0))
