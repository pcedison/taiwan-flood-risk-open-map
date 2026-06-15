"""WRA river / drainage water level adapter (Civil IoT Taiwan SensorThings).

Water Resources Agency river and regional-drainage water-level stations are also
published through the Civil IoT Taiwan SensorThings API (dataset ``iow01``). This
adapter is an alternative STA-sourced path to the existing
``official.wra.water_level`` adapter (which reads ``opendata.wra.gov.tw``); it can
widen station coverage but overlaps with it, so operators should enable only one
of the two, or rely on station-id dedup, to avoid double-counting.

Disabled by default. Live fetching requires ``SOURCE_CIVIL_IOT_RIVER_ENABLED``
plus ``SOURCE_CIVIL_IOT_RIVER_API_ENABLED``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Iterable, Mapping

from app.adapters._helpers import (
    optional_float,
    optional_str,
    parse_datetime,
    stable_evidence_id,
)
from app.adapters.civil_iot.sta_client import (
    CivilIotStaError,
    CivilIotStaFetchError,
    DEFAULT_STA_TIMEOUT_SECONDS,
    STA_WATER_RESOURCE_BASE,
    StaFetchJson,
    fetch_sta_json,
    parse_sta_things_payload,
)
from app.adapters.contracts import (
    AdapterMetadata,
    AdapterRunResult,
    EventType,
    IngestionStatus,
    NormalizedEvidence,
    RawSourceItem,
    SourceFamily,
)

RIVER_WATER_LEVEL_STA_URL = (
    f"{STA_WATER_RESOURCE_BASE}Things"
    "?$expand=Locations,Datastreams($expand=Observations($orderby=phenomenonTime desc;$top=1))"
    "&$filter=substringof('水位',Datastreams/name)"
    "&$top=2000"
)
RIVER_WATER_LEVEL_ATTRIBUTION = "Water Resources Agency / Civil IoT Taiwan"
RIVER_WATER_LEVEL_CIVIL_IOT_DATASET = "iow01"
RIVER_WATER_LEVEL_CIVIL_IOT_URL = "https://ci.taiwan.gov.tw/dsp/dataset_iow01.aspx"
# Sentinel returned by some stations when an instrument is offline.
RIVER_WATER_LEVEL_INVALID_BELOW = -90.0

RIVER_WATER_LEVEL_METADATA = AdapterMetadata(
    key="official.civil_iot.river_water_level",
    family=SourceFamily.OFFICIAL,
    enabled_by_default=False,
    display_name="WRA river water level adapter (Civil IoT)",
    resource_url=RIVER_WATER_LEVEL_STA_URL,
    data_gov_url=RIVER_WATER_LEVEL_CIVIL_IOT_URL,
    update_frequency="Civil IoT SensorThings observations refresh roughly every 10 minutes",
    license="Government Open Data License, version 1.0",
    limitations=(
        "Overlaps with official.wra.water_level (opendata.wra.gov.tw); enable only "
        "one path or dedup by station to avoid double-counting.",
        "Realtime water levels are raw and not fully quality checked; instrument or "
        "transmission faults can stop or distort station data.",
    ),
)


class CivilIotRiverAdapterError(RuntimeError):
    """Base error for the Civil IoT river water level adapter."""


class CivilIotRiverApiAdapter:
    """Live adapter fetching river water levels from the Civil IoT STA."""

    metadata = RIVER_WATER_LEVEL_METADATA

    def __init__(
        self,
        *,
        sta_url: str | None = None,
        timeout_seconds: int = DEFAULT_STA_TIMEOUT_SECONDS,
        fetched_at: datetime | None = None,
        fetch_json: StaFetchJson | None = None,
        raw_snapshot_key: str | None = None,
    ) -> None:
        self._sta_url = (sta_url or RIVER_WATER_LEVEL_STA_URL).strip()
        self._timeout_seconds = max(1, timeout_seconds)
        self._fetched_at = fetched_at
        self._fetch_json = fetch_json or fetch_sta_json
        self._raw_snapshot_key = raw_snapshot_key

    def fetch(self) -> tuple[RawSourceItem, ...]:
        try:
            payload = self._fetch_json(self._sta_url, self._timeout_seconds)
        except CivilIotStaError:
            raise
        except Exception as exc:  # pragma: no cover - defensive
            raise CivilIotStaFetchError(f"River water level fetcher failed: {exc}") from exc

        records = parse_sta_things_payload(
            payload,
            source_url=RIVER_WATER_LEVEL_CIVIL_IOT_URL,
        )
        fetched_at = self._fetched_at or datetime.now(UTC)
        return tuple(
            RawSourceItem(
                source_id=_source_id(record),
                source_url=str(record["source_url"]),
                fetched_at=fetched_at,
                payload=record,
                raw_snapshot_key=self._raw_snapshot_key,
            )
            for record in records
        )

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        return _normalize_river_record(self.metadata, raw_item)

    def run(self) -> AdapterRunResult:
        return _run(self)


class CivilIotRiverAdapter:
    """Fixture-backed adapter running on pre-fetched synthetic records."""

    metadata = RIVER_WATER_LEVEL_METADATA

    def __init__(
        self,
        records: Iterable[Mapping[str, Any]],
        *,
        fetched_at: datetime,
        raw_snapshot_key: str | None = None,
    ) -> None:
        self._records = tuple(records)
        self._fetched_at = fetched_at
        self._raw_snapshot_key = raw_snapshot_key

    def fetch(self) -> tuple[RawSourceItem, ...]:
        return tuple(
            RawSourceItem(
                source_id=_source_id(record),
                source_url=str(record.get("source_url", RIVER_WATER_LEVEL_CIVIL_IOT_URL)),
                fetched_at=self._fetched_at,
                payload=record,
                raw_snapshot_key=self._raw_snapshot_key,
            )
            for record in self._records
        )

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        return _normalize_river_record(self.metadata, raw_item)

    def run(self) -> AdapterRunResult:
        return _run(self)


def _normalize_river_record(
    metadata: AdapterMetadata,
    raw_item: RawSourceItem,
) -> NormalizedEvidence | None:
    payload = raw_item.payload
    station_name = optional_str(payload.get("station_name"))
    observed_at = parse_datetime(payload.get("observed_at"))
    water_level_m = optional_float(payload.get("value"))
    if station_name is None or observed_at is None or water_level_m is None:
        return None
    if water_level_m <= RIVER_WATER_LEVEL_INVALID_BELOW:
        return None

    location_text = optional_str(payload.get("location_text")) or station_name
    summary = f"河川水位觀測：{water_level_m:.2f} 公尺（{station_name}）"
    tags = ["official", "wra", "water_level", "civil_iot"]

    return NormalizedEvidence(
        evidence_id=stable_evidence_id(metadata.key, raw_item.source_id),
        adapter_key=metadata.key,
        source_family=metadata.family,
        event_type=EventType.WATER_LEVEL,
        source_id=raw_item.source_id,
        source_url=raw_item.source_url,
        source_title=f"河川水位觀測：{station_name}",
        source_timestamp=observed_at,
        fetched_at=raw_item.fetched_at,
        summary=summary,
        location_text=location_text,
        confidence=float(payload.get("confidence", 0.9)),
        status=IngestionStatus.NORMALIZED,
        attribution=optional_str(payload.get("attribution")) or RIVER_WATER_LEVEL_ATTRIBUTION,
        tags=tuple(tags),
    )


def _source_id(record: Mapping[str, Any]) -> str:
    station_id = str(record["station_id"])
    observed_at = str(record["observed_at"])
    return f"{station_id}:{observed_at}"


def _run(adapter: CivilIotRiverApiAdapter | CivilIotRiverAdapter) -> AdapterRunResult:
    fetched = adapter.fetch()
    normalized: list[NormalizedEvidence] = []
    rejected: list[str] = []
    for raw_item in fetched:
        evidence = adapter.normalize(raw_item)
        if evidence is None:
            rejected.append(raw_item.source_id)
        else:
            normalized.append(evidence)
    return AdapterRunResult(
        adapter_key=adapter.metadata.key,
        fetched=fetched,
        normalized=tuple(normalized),
        rejected=tuple(rejected),
    )
