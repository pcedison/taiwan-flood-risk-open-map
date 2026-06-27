"""WRA / local-government road flood sensor adapter (Civil IoT Taiwan).

The Water Resources Agency and county governments operate 2,000+ IoT road flood
sensors that report surface flood depth. They are published through the Civil
IoT Taiwan SensorThings API (dataset ``淹水感測器`` / ``water_12``).

Readings at or above :data:`FLOOD_SENSOR_MIN_DEPTH_CM` are treated as observed
flood events (``flood_report``). Exact ``0 cm`` readings are preserved as dry
telemetry, while nonzero subthreshold readings remain low-depth telemetry so the
latest model keeps the measured depth without overstating flood conditions.

Disabled by default. Live fetching requires ``SOURCE_FLOOD_SENSOR_ENABLED``,
``SOURCE_FLOOD_SENSOR_API_ENABLED``, and ``SOURCE_FLOOD_SENSOR_USE_LIVE``;
otherwise the fixture-backed adapter runs on synthetic records.
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
    fetch_paginated_sta_things_records,
    fetch_sta_json,
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

# Default Civil IoT SensorThings query for the flood-sensor dataset. The exact
# authority filter is configurable; this default selects flood-depth things with
# their location and latest observation expanded.
FLOOD_SENSOR_STA_URL = (
    f"{STA_WATER_RESOURCE_BASE}Things"
    "?$expand=Locations,Datastreams($expand=Observations($orderby=phenomenonTime desc;$top=1))"
    "&$filter=substringof('淹水',Datastreams/name)"
    "&$top=2000"
)
FLOOD_SENSOR_ATTRIBUTION = "Water Resources Agency / Civil IoT Taiwan"
FLOOD_SENSOR_CIVIL_IOT_DATASET = "water_12"
FLOOD_SENSOR_CIVIL_IOT_URL = (
    "https://ci.taiwan.gov.tw/dsp/Views/dataset/detail.aspx?id=water_12"
)
# Minimum surface flood depth (cm) that counts as an observed flood event.
FLOOD_SENSOR_MIN_DEPTH_CM = 3.0

FLOOD_SENSOR_METADATA = AdapterMetadata(
    key="official.civil_iot.flood_sensor",
    family=SourceFamily.OFFICIAL,
    enabled_by_default=False,
    display_name="Civil IoT official national flood sensor backbone",
    resource_url=FLOOD_SENSOR_STA_URL,
    data_gov_url=FLOOD_SENSOR_CIVIL_IOT_URL,
    update_frequency="Civil IoT SensorThings observations refresh roughly every 10 minutes",
    license="Government Open Data License, version 1.0",
    limitations=(
        "Road flood sensors report surface flood depth at fixed points; coverage "
        "concentrates on known flood-prone roads and is sparse elsewhere.",
        "Readings are raw IoT telemetry and can be distorted by sensor or "
        "transmission faults.",
        "This worker treats Civil IoT flood sensors as the official nationwide "
        "flood-sensor backbone for live ingestion, but the live gate remains "
        "disabled by default.",
        f"Readings below {FLOOD_SENSOR_MIN_DEPTH_CM:.0f} cm are retained as "
        "telemetry; only exact 0 cm readings are marked dry/no flooding observed.",
    ),
)


class FloodSensorAdapterError(RuntimeError):
    """Base error for flood sensor adapter failures."""


class FloodSensorStaApiAdapter:
    """Live adapter fetching flood-sensor readings from the Civil IoT STA."""

    metadata = FLOOD_SENSOR_METADATA

    def __init__(
        self,
        *,
        sta_url: str | None = None,
        timeout_seconds: int = DEFAULT_STA_TIMEOUT_SECONDS,
        fetched_at: datetime | None = None,
        fetch_json: StaFetchJson | None = None,
        raw_snapshot_key: str | None = None,
    ) -> None:
        self._sta_url = (sta_url or FLOOD_SENSOR_STA_URL).strip()
        self._timeout_seconds = max(1, timeout_seconds)
        self._fetched_at = fetched_at
        self._fetch_json = fetch_json or fetch_sta_json
        self._raw_snapshot_key = raw_snapshot_key

    def fetch(self) -> tuple[RawSourceItem, ...]:
        try:
            records = fetch_paginated_sta_things_records(
                self._sta_url,
                timeout_seconds=self._timeout_seconds,
                fetch_json=self._fetch_json,
                source_url=FLOOD_SENSOR_CIVIL_IOT_URL,
            )
        except CivilIotStaError:
            raise
        except Exception as exc:  # pragma: no cover - defensive
            raise CivilIotStaFetchError(f"Flood sensor fetcher failed: {exc}") from exc

        fetched_at = self._fetched_at or datetime.now(UTC)
        return tuple(
            RawSourceItem(
                source_id=_source_id(record),
                source_url=str(record["source_url"]),
                fetched_at=fetched_at,
                payload=_normalize_raw_payload(record, source_url=str(record["source_url"])),
                raw_snapshot_key=self._raw_snapshot_key,
            )
            for record in records
        )

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        return _normalize_flood_sensor_record(self.metadata, raw_item)

    def run(self) -> AdapterRunResult:
        return _run(self)


class FloodSensorAdapter:
    """Fixture-backed adapter running on pre-fetched synthetic records."""

    metadata = FLOOD_SENSOR_METADATA

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
                source_url=str(record.get("source_url", FLOOD_SENSOR_CIVIL_IOT_URL)),
                fetched_at=self._fetched_at,
                payload=_normalize_raw_payload(
                    record,
                    source_url=str(record.get("source_url", FLOOD_SENSOR_CIVIL_IOT_URL)),
                ),
                raw_snapshot_key=self._raw_snapshot_key,
            )
            for record in self._records
        )

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        return _normalize_flood_sensor_record(self.metadata, raw_item)

    def run(self) -> AdapterRunResult:
        return _run(self)


def _normalize_flood_sensor_record(
    metadata: AdapterMetadata,
    raw_item: RawSourceItem,
) -> NormalizedEvidence | None:
    payload = raw_item.payload
    station_name = optional_str(payload.get("station_name"))
    observed_at = parse_datetime(payload.get("observed_at"))
    depth_cm = optional_float(payload.get("value"))
    if station_name is None or observed_at is None or depth_cm is None:
        return None

    location_text = optional_str(payload.get("location_text")) or station_name
    tags = ["official", "wra", "flood_sensor", "civil_iot"]
    if depth_cm == 0:
        summary = f"路面淹水感測：無觀測到淹水（乾燥，{_format_depth_cm(depth_cm)} 公分）（{station_name}）"
        tags.extend(["dry", "no_flooding_observed"])
    elif depth_cm < FLOOD_SENSOR_MIN_DEPTH_CM:
        summary = f"路面淹水感測：低水深觀測 {_format_depth_cm(depth_cm)} 公分（{station_name}）"
        tags.extend(["below_flood_threshold", "low_depth_observation"])
    else:
        summary = f"路面淹水感測：水深 {_format_depth_cm(depth_cm)} 公分（{station_name}）"

    return NormalizedEvidence(
        evidence_id=stable_evidence_id(metadata.key, raw_item.source_id),
        adapter_key=metadata.key,
        source_family=metadata.family,
        event_type=EventType.FLOOD_REPORT,
        source_id=raw_item.source_id,
        source_url=raw_item.source_url,
        source_title=f"路面淹水感測器觀測：{station_name}",
        source_timestamp=observed_at,
        fetched_at=raw_item.fetched_at,
        summary=summary,
        location_text=location_text,
        confidence=float(payload.get("confidence", 0.9)),
        status=IngestionStatus.NORMALIZED,
        attribution=optional_str(payload.get("attribution")) or FLOOD_SENSOR_ATTRIBUTION,
        tags=tuple(tags),
    )


def _source_id(record: Mapping[str, Any]) -> str:
    station_id = str(record["station_id"])
    observed_at = str(record["observed_at"])
    return f"{station_id}:{observed_at}"


def _normalize_raw_payload(
    record: Mapping[str, Any],
    *,
    source_url: str,
) -> dict[str, Any]:
    payload = dict(record)
    payload["source_url"] = source_url
    value = optional_float(payload.get("value"))
    if value is not None:
        payload["flood_depth_cm"] = float(value)
    return payload


def _run(adapter: FloodSensorStaApiAdapter | FloodSensorAdapter) -> AdapterRunResult:
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


def _format_depth_cm(depth_cm: float) -> str:
    if depth_cm == 0:
        return "0"
    formatted = f"{depth_cm:.1f}"
    return formatted.rstrip("0").rstrip(".")
