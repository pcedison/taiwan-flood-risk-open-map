from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import hashlib
import json
from typing import Any, Iterable, Mapping, Protocol


STATION_ID_MANIFEST_VERSION = "station-id-json-v1"


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
    STATUS_ONLY = "status_only"
    ROAD_CLOSURE = "road_closure"
    DISCUSSION = "discussion"


@dataclass(frozen=True)
class AdapterMetadata:
    key: str
    family: SourceFamily
    enabled_by_default: bool
    display_name: str
    terms_review_required: bool = False
    data_gov_dataset_id: str | None = None
    data_gov_url: str | None = None
    resource_url: str | None = None
    update_frequency: str | None = None
    license: str | None = None
    limitations: tuple[str, ...] = field(default_factory=tuple)


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
class StationInventoryProof:
    """Public-safe proof that a station inventory came from a full upstream walk.

    ``station_ids`` is the canonical, sorted, unique Thing/station manifest.  Its
    hash is derived here rather than accepted from adapters so an adapter cannot
    accidentally persist a checksum for a different ordering or payload.
    """

    upstream_total: int | None
    pages_fetched: int
    pagination_complete: bool
    source_items_seen: int
    missing_station_id_count: int
    duplicate_station_id_count: int
    station_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.upstream_total is not None and self.upstream_total < 0:
            raise ValueError("upstream_total must be non-negative")
        for name, value in (
            ("pages_fetched", self.pages_fetched),
            ("source_items_seen", self.source_items_seen),
            ("missing_station_id_count", self.missing_station_id_count),
            ("duplicate_station_id_count", self.duplicate_station_id_count),
        ):
            if value < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.pagination_complete and self.pages_fetched == 0:
            raise ValueError("complete pagination must include at least one fetched page")
        if any(not station_id or station_id != station_id.strip() for station_id in self.station_ids):
            raise ValueError("station_ids must contain non-empty trimmed values")
        if self.station_ids != tuple(sorted(set(self.station_ids))):
            raise ValueError("station_ids must be canonical sorted unique values")

    @property
    def station_ids_seen(self) -> int:
        return len(self.station_ids)

    @property
    def manifest_version(self) -> str:
        """Canonical checksum contract pinned by migration 0035."""

        return STATION_ID_MANIFEST_VERSION

    @property
    def manifest_sha256(self) -> str:
        return hashlib.sha256(self.canonical_manifest_json.encode("utf-8")).hexdigest()

    @property
    def canonical_manifest_json(self) -> str:
        """Serialize the ``station-id-json-v1`` manifest deterministically."""

        return json.dumps(
            list(self.station_ids),
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @property
    def inventory_complete(self) -> bool:
        return (
            self.upstream_total is not None
            and self.pagination_complete
            and self.pages_fetched > 0
            and self.missing_station_id_count == 0
            and self.duplicate_station_id_count == 0
            and self.source_items_seen == self.station_ids_seen
            and self.station_ids_seen == self.upstream_total
        )

    def public_summary(self) -> dict[str, int | str | bool | None]:
        """Return proof diagnostics without exposing the full station manifest."""

        return {
            "upstream_total": self.upstream_total,
            "pages_fetched": self.pages_fetched,
            "pagination_complete": self.pagination_complete,
            "source_items_seen": self.source_items_seen,
            "station_ids_seen": self.station_ids_seen,
            "missing_station_id_count": self.missing_station_id_count,
            "duplicate_station_id_count": self.duplicate_station_id_count,
            "manifest_version": self.manifest_version,
            "manifest_sha256": self.manifest_sha256,
            "inventory_complete": self.inventory_complete,
        }


@dataclass(frozen=True)
class AdapterRunResult:
    adapter_key: str
    fetched: tuple[RawSourceItem, ...]
    normalized: tuple[NormalizedEvidence, ...]
    rejected: tuple[str, ...] = field(default_factory=tuple)
    station_inventory_proof: StationInventoryProof | None = None


class DataSourceAdapter(Protocol):
    metadata: AdapterMetadata

    def fetch(self) -> Iterable[RawSourceItem]:
        """Fetch source-specific records without mutating pipeline state."""

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        """Convert one raw source record into normalized evidence or reject it."""

    def run(self) -> AdapterRunResult:
        """Fetch and normalize one adapter batch."""
