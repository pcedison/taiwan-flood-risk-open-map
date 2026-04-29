from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Iterable, Mapping, Protocol


class SourceFamily(str, Enum):
    OFFICIAL = "official"
    NEWS = "news"
    FORUM = "forum"
    SOCIAL = "social"
    USER_REPORT = "user_report"
    DERIVED = "derived"


class IngestionStatus(str, Enum):
    FETCHED = "fetched"
    NORMALIZED = "normalized"
    REJECTED = "rejected"


class EventType(str, Enum):
    RAINFALL = "rainfall"
    WATER_LEVEL = "water_level"
    FLOOD_WARNING = "flood_warning"
    FLOOD_POTENTIAL = "flood_potential"
    FLOOD_REPORT = "flood_report"
    ROAD_CLOSURE = "road_closure"
    DISCUSSION = "discussion"


@dataclass(frozen=True)
class AdapterMetadata:
    key: str
    family: SourceFamily
    enabled_by_default: bool
    display_name: str
    terms_review_required: bool = False


@dataclass(frozen=True)
class RawSourceItem:
    source_id: str
    source_url: str
    fetched_at: datetime
    payload: Mapping[str, Any]
    raw_snapshot_key: str | None = None


@dataclass(frozen=True)
class NormalizedEvidence:
    evidence_id: str
    adapter_key: str
    source_family: SourceFamily
    event_type: EventType
    source_id: str
    source_url: str
    source_title: str
    source_timestamp: datetime
    fetched_at: datetime
    summary: str
    location_text: str | None
    confidence: float
    status: IngestionStatus = IngestionStatus.NORMALIZED
    attribution: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class AdapterRunResult:
    adapter_key: str
    fetched: tuple[RawSourceItem, ...]
    normalized: tuple[NormalizedEvidence, ...]
    rejected: tuple[str, ...] = field(default_factory=tuple)


class DataSourceAdapter(Protocol):
    metadata: AdapterMetadata

    def fetch(self) -> Iterable[RawSourceItem]:
        """Fetch source-specific records without mutating pipeline state."""

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        """Convert one raw source record into normalized evidence or reject it."""

    def run(self) -> AdapterRunResult:
        """Fetch and normalize one adapter batch."""
