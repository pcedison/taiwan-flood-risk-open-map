"""Generic Civil IoT SensorThings water-level adapters.

Agricultural pond levels (``iow12``), storm-sewer levels (國土署 雨水下水道), and
pump-station external water levels (``pump_taipei``) all share the same OGC
SensorThings water-level shape. This module provides one configurable adapter
pair (live + fixture-backed) plus the per-source metadata, so the three networks
do not each duplicate the river adapter.

All three are official ``water_level`` evidence, disabled by default, and gated by
their own ``SOURCE_*`` flags.
"""

from __future__ import annotations

from dataclasses import dataclass
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

# Sentinel returned by some stations when an instrument is offline.
WATER_LEVEL_INVALID_BELOW = -90.0


@dataclass(frozen=True)
class StaWaterLevelSource:
    """Static configuration for one Civil IoT water-level network."""

    metadata: AdapterMetadata
    sta_url: str
    source_url: str
    attribution: str
    datastream_name_contains: str | None = None


def _build_sta_url(*, filter_expr: str, top: int = 2000) -> str:
    return (
        f"{STA_WATER_RESOURCE_BASE}Things"
        "?$expand=Locations,Datastreams($expand=Observations("
        "$orderby=phenomenonTime desc;$top=1))"
        f"&$filter={filter_expr}"
        f"&$top={top}"
    )


POND_WATER_LEVEL = StaWaterLevelSource(
    metadata=AdapterMetadata(
        key="official.civil_iot.pond_water_level",
        family=SourceFamily.OFFICIAL,
        enabled_by_default=False,
        display_name="Agricultural pond water level adapter (Civil IoT)",
        resource_url=_build_sta_url(filter_expr="substringof('埤塘',Datastreams/name)"),
        data_gov_url="https://ci.taiwan.gov.tw/dsp/dataset_iow12.aspx",
        update_frequency="Civil IoT SensorThings observations refresh roughly every 10 minutes",
        license="Government Open Data License, version 1.0",
        limitations=(
            "Agricultural pond levels reflect irrigation operations and are an "
            "indirect flood signal; treat as context, not a flood warning.",
            "Raw IoT telemetry can be distorted by sensor or transmission faults.",
        ),
    ),
    sta_url=_build_sta_url(filter_expr="substringof('埤塘',Datastreams/name)"),
    source_url="https://ci.taiwan.gov.tw/dsp/dataset_iow12.aspx",
    attribution="Agency of Rural Development and Soil and Water Conservation / Civil IoT Taiwan",
)

SEWER_WATER_LEVEL = StaWaterLevelSource(
    metadata=AdapterMetadata(
        key="official.civil_iot.sewer_water_level",
        family=SourceFamily.OFFICIAL,
        enabled_by_default=False,
        display_name="Storm sewer water level adapter (Civil IoT)",
        resource_url=_build_sta_url(filter_expr="substringof('下水道',Datastreams/name)"),
        data_gov_url="https://ci.taiwan.gov.tw/dsp/dataset_weather.aspx",
        update_frequency="Civil IoT SensorThings observations refresh roughly every 10 minutes",
        license="Government Open Data License, version 1.0",
        limitations=(
            "Storm-sewer levels indicate drainage loading; a rising level is an "
            "early urban-flood signal but is not an official flood warning.",
            "Raw IoT telemetry can be distorted by sensor or transmission faults.",
        ),
    ),
    sta_url=_build_sta_url(filter_expr="substringof('下水道',Datastreams/name)"),
    source_url="https://ci.taiwan.gov.tw/dsp/dataset_weather.aspx",
    attribution="National Land Management Agency / Civil IoT Taiwan",
)

PUMP_WATER_LEVEL = StaWaterLevelSource(
    metadata=AdapterMetadata(
        key="official.civil_iot.pump_water_level",
        family=SourceFamily.OFFICIAL,
        enabled_by_default=False,
        display_name="Pump station external water level adapter (Civil IoT)",
        resource_url=_build_sta_url(filter_expr="substringof('外水位',Datastreams/name)"),
        data_gov_url="https://ci.taiwan.gov.tw/dsp/dataset_pump_taipei.aspx",
        update_frequency="Civil IoT SensorThings observations refresh roughly every 10 minutes",
        license="Government Open Data License, version 1.0",
        limitations=(
            "Pump stations expose internal/external water levels; this adapter "
            "reads the external (外水位) level as the flood-relevant signal.",
            "Operational data; confirm the external-level datastream name against "
            "the live dataset before enabling.",
        ),
    ),
    sta_url=_build_sta_url(filter_expr="substringof('外水位',Datastreams/name)"),
    source_url="https://ci.taiwan.gov.tw/dsp/dataset_pump_taipei.aspx",
    attribution="Taipei City Government / Civil IoT Taiwan",
    # Pump things carry several datastreams; read the external water level.
    datastream_name_contains="外水位",
)


class StaWaterLevelApiAdapter:
    """Live adapter fetching a Civil IoT water-level network from the STA."""

    def __init__(
        self,
        source: StaWaterLevelSource,
        *,
        sta_url: str | None = None,
        timeout_seconds: int = DEFAULT_STA_TIMEOUT_SECONDS,
        fetched_at: datetime | None = None,
        fetch_json: StaFetchJson | None = None,
        raw_snapshot_key: str | None = None,
    ) -> None:
        self._source = source
        self.metadata = source.metadata
        self._sta_url = (sta_url or source.sta_url).strip()
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
            raise CivilIotStaFetchError(
                f"{self.metadata.display_name} fetcher failed: {exc}"
            ) from exc

        records = parse_sta_things_payload(
            payload,
            source_url=self._source.source_url,
            datastream_name_contains=self._source.datastream_name_contains,
        )
        fetched_at = self._fetched_at or datetime.now(UTC)
        return tuple(
            RawSourceItem(
                source_id=_source_id(record),
                source_url=str(record["source_url"]),
                fetched_at=fetched_at,
                payload=_raw_payload_with_water_level_metric(record),
                raw_snapshot_key=self._raw_snapshot_key,
            )
            for record in records
        )

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        return _normalize(self._source, raw_item)

    def run(self) -> AdapterRunResult:
        return _run(self)


class StaWaterLevelAdapter:
    """Fixture-backed adapter running on pre-fetched synthetic records."""

    def __init__(
        self,
        source: StaWaterLevelSource,
        records: Iterable[Mapping[str, Any]],
        *,
        fetched_at: datetime,
        raw_snapshot_key: str | None = None,
    ) -> None:
        self._source = source
        self.metadata = source.metadata
        self._records = tuple(records)
        self._fetched_at = fetched_at
        self._raw_snapshot_key = raw_snapshot_key

    def fetch(self) -> tuple[RawSourceItem, ...]:
        return tuple(
            RawSourceItem(
                source_id=_source_id(record),
                source_url=str(record.get("source_url", self._source.source_url)),
                fetched_at=self._fetched_at,
                payload=_raw_payload_with_water_level_metric(record),
                raw_snapshot_key=self._raw_snapshot_key,
            )
            for record in self._records
        )

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        return _normalize(self._source, raw_item)

    def run(self) -> AdapterRunResult:
        return _run(self)


def _normalize(
    source: StaWaterLevelSource,
    raw_item: RawSourceItem,
) -> NormalizedEvidence | None:
    payload = raw_item.payload
    station_name = optional_str(payload.get("station_name"))
    observed_at = parse_datetime(payload.get("observed_at"))
    water_level_m = optional_float(payload.get("water_level_m"))
    if water_level_m is None:
        water_level_m = optional_float(payload.get("value"))
    if station_name is None or observed_at is None or water_level_m is None:
        return None
    if water_level_m <= WATER_LEVEL_INVALID_BELOW:
        return None

    metadata = source.metadata
    location_text = optional_str(payload.get("location_text")) or station_name
    summary = f"{metadata.display_name} 觀測：{water_level_m:.2f} 公尺（{station_name}）"

    return NormalizedEvidence(
        evidence_id=stable_evidence_id(metadata.key, raw_item.source_id),
        adapter_key=metadata.key,
        source_family=metadata.family,
        event_type=EventType.WATER_LEVEL,
        source_id=raw_item.source_id,
        source_url=raw_item.source_url,
        source_title=f"{metadata.display_name}：{station_name}",
        source_timestamp=observed_at,
        fetched_at=raw_item.fetched_at,
        summary=summary,
        location_text=location_text,
        confidence=float(payload.get("confidence", 0.9)),
        status=IngestionStatus.NORMALIZED,
        attribution=optional_str(payload.get("attribution")) or source.attribution,
        tags=("official", "civil_iot", "water_level"),
    )


def _raw_payload_with_water_level_metric(record: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = dict(record)
    water_level_m = optional_float(payload.get("water_level_m"))
    if water_level_m is None:
        water_level_m = optional_float(payload.get("value"))
    if water_level_m is not None:
        payload["water_level_m"] = water_level_m

    warning_level_m = optional_float(payload.get("warning_level_m"))
    if warning_level_m is not None:
        payload["warning_level_m"] = warning_level_m
    return payload


def _source_id(record: Mapping[str, Any]) -> str:
    station_id = str(record["station_id"])
    observed_at = str(record["observed_at"])
    return f"{station_id}:{observed_at}"


def _run(adapter: StaWaterLevelApiAdapter | StaWaterLevelAdapter) -> AdapterRunResult:
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
