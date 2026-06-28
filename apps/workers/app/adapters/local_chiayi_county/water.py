from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.adapters._helpers import optional_float, optional_str, parse_datetime, stable_evidence_id
from app.adapters.contracts import (
    AdapterMetadata,
    AdapterRunResult,
    EventType,
    IngestionStatus,
    NormalizedEvidence,
    RawSourceItem,
    SourceFamily,
)


FetchJson = Callable[[str, int], Any]

DEFAULT_CHIAYI_COUNTY_WATER_TIMEOUT_SECONDS = 8
CHIAYI_COUNTY_ATTRIBUTION = "嘉義縣政府水利處 / 嘉義縣智慧防汛公開資料"
CHIAYI_COUNTY_USER_AGENT = "FloodRiskTaiwan/0.1 worker-local-chiayi-county-water"
CHIAYI_COUNTY_FLOOD_SENSOR_API_URL = "https://api.floodsolution.aiot.ing/api/public/devices/RFD"
CHIAYI_COUNTY_FLOOD_SENSOR_DATA_URL = "https://www.cyhg.gov.tw/News_Content.aspx?n=16&s=249470"

CHIAYI_COUNTY_FLOOD_SENSOR_METADATA = AdapterMetadata(
    key="local.chiayi_county.flood_sensor",
    family=SourceFamily.OFFICIAL,
    enabled_by_default=False,
    display_name="Chiayi County local flood sensor adapter",
    data_gov_url=CHIAYI_COUNTY_FLOOD_SENSOR_DATA_URL,
    resource_url=CHIAYI_COUNTY_FLOOD_SENSOR_API_URL,
    update_frequency="Chiayi County public RFD API carries per-device latest.time timestamps",
    license="Government Open Data License, version 1.0",
    limitations=(
        "Supplemental local-government flood-depth source for Chiayi County.",
        "Only the public RFD endpoint is used; authenticated /api/v1 device "
        "management endpoints remain out of scope until official credentials are granted.",
        "Rows without latest observation time, coordinates, or waterDepth are rejected.",
    ),
)


class ChiayiCountyWaterAdapterError(RuntimeError):
    """Base error for Chiayi County local water adapter failures."""


class ChiayiCountyWaterFetchError(ChiayiCountyWaterAdapterError):
    """Raised when fetching Chiayi County JSON fails."""


class ChiayiCountyWaterPayloadError(ChiayiCountyWaterAdapterError):
    """Raised when Chiayi County JSON cannot be parsed."""


class ChiayiCountyFloodSensorApiAdapter:
    metadata = CHIAYI_COUNTY_FLOOD_SENSOR_METADATA

    def __init__(
        self,
        *,
        api_url: str | None = None,
        timeout_seconds: int = DEFAULT_CHIAYI_COUNTY_WATER_TIMEOUT_SECONDS,
        fetched_at: datetime | None = None,
        fetch_json: FetchJson | None = None,
        raw_snapshot_key: str | None = None,
    ) -> None:
        self._api_url = (api_url or CHIAYI_COUNTY_FLOOD_SENSOR_API_URL).strip()
        self._timeout_seconds = max(1, timeout_seconds)
        self._fetched_at = fetched_at
        self._fetch_json = fetch_json or fetch_chiayi_county_json
        self._raw_snapshot_key = raw_snapshot_key

    def fetch(self) -> tuple[RawSourceItem, ...]:
        try:
            payload = self._fetch_json(self._api_url, self._timeout_seconds)
        except ChiayiCountyWaterAdapterError:
            raise
        except Exception as exc:
            raise ChiayiCountyWaterFetchError(
                f"{self.metadata.display_name} fetcher failed: {exc}"
            ) from exc
        records = parse_chiayi_county_flood_sensor_payload(
            payload,
            source_url=CHIAYI_COUNTY_FLOOD_SENSOR_DATA_URL,
            resource_url=self._api_url,
        )
        fetched_at = self._fetched_at or datetime.now(UTC)
        return _raw_items(records, fetched_at=fetched_at, raw_snapshot_key=self._raw_snapshot_key)

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        return _normalize_flood_sensor_record(self.metadata, raw_item)

    def run(self) -> AdapterRunResult:
        return _run(self)


def fetch_chiayi_county_json(url: str, timeout_seconds: int) -> Any:
    request = Request(
        url,
        headers={"Accept": "application/json", "User-Agent": CHIAYI_COUNTY_USER_AGENT},
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8-sig"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ChiayiCountyWaterFetchError(f"Failed to fetch Chiayi County JSON {url}: {exc}") from exc


def parse_chiayi_county_flood_sensor_payload(
    payload: object,
    *,
    source_url: str,
    resource_url: str | None = None,
) -> tuple[Mapping[str, Any], ...]:
    records: list[Mapping[str, Any]] = []
    for item in _payload_items(payload):
        if not isinstance(item, Mapping):
            continue
        latest = item.get("latest")
        if not isinstance(latest, Mapping):
            continue
        latest_data = latest.get("data")
        if not isinstance(latest_data, Mapping):
            continue
        station_id = _first_text(item, "_id", "id")
        station_name = _first_text(item, "name")
        observed_at = _parse_observed_at(latest.get("time"))
        flood_depth_cm = optional_float(_first_value(latest_data, "waterDepth", "water_depth"))
        coordinate = _coordinate(_first_value(item, "lon", "longitude"), _first_value(item, "lat", "latitude"))
        if (
            station_id is None
            or station_name is None
            or observed_at is None
            or flood_depth_cm is None
            or coordinate is None
        ):
            continue
        if flood_depth_cm < 0:
            continue
        longitude, latitude = coordinate
        record: dict[str, Any] = {
            "station_id": station_id,
            "station_name": station_name,
            "observed_at": observed_at.isoformat(),
            "flood_depth_cm": flood_depth_cm,
            "source_url": source_url,
            "resource_url": resource_url,
            "location_text": " ".join(
                part
                for part in (
                    _first_text(item, "county"),
                    _first_text(item, "town"),
                    _first_text(item, "village"),
                    station_name,
                )
                if part
            ),
            "county": _first_text(item, "county"),
            "town": _first_text(item, "town"),
            "village": _first_text(item, "village"),
            "status_text": _first_text(item, "status"),
            "authority": _first_text(item, "institution") or "嘉義縣政府",
            "department": _first_text(item, "department"),
            "longitude": longitude,
            "latitude": latitude,
            "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
            "attribution": CHIAYI_COUNTY_ATTRIBUTION,
            "confidence": 0.84,
        }
        _assign_float(record, "battery_voltage", _first_value(latest_data, "mbBatteryVolt"))
        records.append(record)
    return tuple(records)


def _normalize_flood_sensor_record(
    metadata: AdapterMetadata,
    raw_item: RawSourceItem,
) -> NormalizedEvidence | None:
    payload = raw_item.payload
    station_name = optional_str(payload.get("station_name"))
    observed_at = parse_datetime(payload.get("observed_at"))
    flood_depth_cm = optional_float(payload.get("flood_depth_cm"))
    if station_name is None or observed_at is None or flood_depth_cm is None:
        return None
    if flood_depth_cm == 0:
        summary = f"嘉義縣地方淹水感測：無觀測到淹水（0 公分）（{station_name}）"
        depth_tags = ["dry", "no_flooding_observed"]
    elif flood_depth_cm < 3:
        summary = f"嘉義縣地方淹水感測：低水深觀測 {_format_depth_cm(flood_depth_cm)} 公分（{station_name}）"
        depth_tags = ["below_flood_threshold", "low_depth_observation"]
    else:
        summary = f"嘉義縣地方淹水感測：水深 {_format_depth_cm(flood_depth_cm)} 公分（{station_name}）"
        depth_tags = []
    return NormalizedEvidence(
        evidence_id=stable_evidence_id(metadata.key, raw_item.source_id),
        adapter_key=metadata.key,
        source_family=metadata.family,
        event_type=EventType.FLOOD_REPORT,
        source_id=raw_item.source_id,
        source_url=raw_item.source_url,
        source_title=f"{metadata.display_name}：{station_name}",
        source_timestamp=observed_at,
        fetched_at=raw_item.fetched_at,
        summary=summary,
        location_text=optional_str(payload.get("location_text")) or station_name,
        confidence=float(payload.get("confidence", 0.84)),
        status=IngestionStatus.NORMALIZED,
        attribution=optional_str(payload.get("attribution")) or CHIAYI_COUNTY_ATTRIBUTION,
        tags=tuple(
            dict.fromkeys(("official", "local_chiayi_county", "flood_sensor", *depth_tags))
        ),
    )


def _run(adapter: Any) -> AdapterRunResult:
    fetched = tuple(adapter.fetch())
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


def _raw_items(
    records: Iterable[Mapping[str, Any]],
    *,
    fetched_at: datetime,
    raw_snapshot_key: str | None,
) -> tuple[RawSourceItem, ...]:
    return tuple(
        RawSourceItem(
            source_id=f"{record['station_id']}:{record['observed_at']}",
            source_url=str(record["source_url"]),
            fetched_at=fetched_at,
            payload=record,
            raw_snapshot_key=raw_snapshot_key,
        )
        for record in records
    )


def _payload_items(payload: object) -> tuple[object, ...]:
    if isinstance(payload, list):
        return tuple(payload)
    if isinstance(payload, Mapping):
        data = payload.get("data") or payload.get("Data") or payload.get("devices")
        if isinstance(data, list):
            return tuple(data)
    return ()


def _parse_observed_at(value: object) -> datetime | None:
    parsed = parse_datetime(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _coordinate(lon: object, lat: object) -> tuple[float, float] | None:
    longitude = optional_float(lon)
    latitude = optional_float(lat)
    if longitude is None or latitude is None:
        return None
    if not (118.0 <= longitude <= 123.5 and 21.0 <= latitude <= 26.5):
        return None
    return longitude, latitude


def _first_value(row: Mapping[str, Any], *keys: str) -> Any:
    lowered = {str(key).lower(): value for key, value in row.items()}
    for key in keys:
        if key in row:
            return row[key]
        lowered_value = lowered.get(key.lower())
        if lowered_value is not None:
            return lowered_value
    return None


def _first_text(row: Mapping[str, Any], *keys: str) -> str | None:
    return optional_str(_first_value(row, *keys))


def _assign_float(record: dict[str, Any], key: str, value: object) -> None:
    parsed = optional_float(value)
    if parsed is not None:
        record[key] = parsed


def _format_depth_cm(value: float) -> str:
    return f"{value:.0f}" if value.is_integer() else f"{value:.1f}"
