from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime, timedelta, timezone
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

HSINCHU_CITY_LOCAL_TZ = timezone(timedelta(hours=8))
DEFAULT_HSINCHU_CITY_WATER_TIMEOUT_SECONDS = 8
HSINCHU_CITY_ATTRIBUTION = "新竹市政府工務處 / 經濟部水利署防災協作平台"
HSINCHU_CITY_USER_AGENT = "FloodRiskTaiwan/0.1 worker-local-hsinchu-city-water"

HSINCHU_CITY_SEWER_BASE_API_URL = "https://swc.hccg.gov.tw/api/map/sewer/base"
HSINCHU_CITY_SEWER_REALTIME_API_URL = "https://swc.hccg.gov.tw/api/map/sewer/rt"
HSINCHU_CITY_SEWER_DATA_URL = "https://swc.hccg.gov.tw/"
HSINCHU_CITY_FLOOD_SENSOR_STATION_API_URL = (
    "https://www.dprcflood.org.tw/SGDS/WS/FHYBrokerWS.asmx/"
    "GetFHYFloodSensorStationByCityCode"
)
HSINCHU_CITY_FLOOD_SENSOR_REALTIME_API_URL = (
    "https://www.dprcflood.org.tw/SGDS/WS/FHYBrokerWS.asmx/GetFHYFloodSensorInfoRt"
)
HSINCHU_CITY_FLOOD_SENSOR_DATA_URL = "https://www.dprcflood.org.tw/SGDS/"

HSINCHU_CITY_SEWER_WATER_LEVEL_METADATA = AdapterMetadata(
    key="local.hsinchu_city.sewer_water_level",
    family=SourceFamily.OFFICIAL,
    enabled_by_default=False,
    display_name="Hsinchu City sewer water-level adapter",
    data_gov_url=HSINCHU_CITY_SEWER_DATA_URL,
    resource_url=HSINCHU_CITY_SEWER_REALTIME_API_URL,
    update_frequency="Hsinchu City sewer realtime API carries per-device Time timestamps",
    license="Government Open Data License, version 1.0",
    limitations=(
        "Supplemental local-government sewer water-level source for Hsinchu City.",
        "Realtime rows are joined to the public sewer base endpoint by Dev_UUID; "
        "rows without station coordinates are rejected.",
    ),
)

HSINCHU_CITY_FLOOD_SENSOR_METADATA = AdapterMetadata(
    key="local.hsinchu_city.flood_sensor",
    family=SourceFamily.OFFICIAL,
    enabled_by_default=False,
    display_name="Hsinchu City local flood sensor adapter",
    data_gov_url=HSINCHU_CITY_FLOOD_SENSOR_DATA_URL,
    resource_url=HSINCHU_CITY_FLOOD_SENSOR_REALTIME_API_URL,
    update_frequency=(
        "FHY broker realtime payload carries per-sensor SourceTime timestamps "
        "as .NET epoch milliseconds"
    ),
    license="Government Open Data License, version 1.0",
    limitations=(
        "Supplemental Hsinchu City flood-depth source from the public FHY broker.",
        "Station metadata is filtered to CityCode 10018 before joining realtime rows.",
    ),
)


class HsinchuCityWaterAdapterError(RuntimeError):
    """Base error for Hsinchu City local water adapters."""


class HsinchuCityWaterFetchError(HsinchuCityWaterAdapterError):
    """Raised when fetching a Hsinchu City water payload fails."""


class HsinchuCityWaterPayloadError(HsinchuCityWaterAdapterError):
    """Raised when a Hsinchu City water payload cannot be parsed."""


class HsinchuCitySewerWaterLevelApiAdapter:
    metadata = HSINCHU_CITY_SEWER_WATER_LEVEL_METADATA

    def __init__(
        self,
        *,
        base_api_url: str | None = None,
        realtime_api_url: str | None = None,
        timeout_seconds: int = DEFAULT_HSINCHU_CITY_WATER_TIMEOUT_SECONDS,
        fetched_at: datetime | None = None,
        fetch_json: FetchJson | None = None,
        raw_snapshot_key: str | None = None,
    ) -> None:
        self._base_api_url = (base_api_url or HSINCHU_CITY_SEWER_BASE_API_URL).strip()
        self._realtime_api_url = (realtime_api_url or HSINCHU_CITY_SEWER_REALTIME_API_URL).strip()
        self._timeout_seconds = max(1, timeout_seconds)
        self._fetched_at = fetched_at
        self._fetch_json = fetch_json or fetch_hsinchu_city_json
        self._raw_snapshot_key = raw_snapshot_key

    def fetch(self) -> tuple[RawSourceItem, ...]:
        try:
            base_payload = self._fetch_json(self._base_api_url, self._timeout_seconds)
            realtime_payload = self._fetch_json(self._realtime_api_url, self._timeout_seconds)
        except HsinchuCityWaterAdapterError:
            raise
        except Exception as exc:
            raise HsinchuCityWaterFetchError(
                f"{self.metadata.display_name} fetcher failed: {exc}"
            ) from exc

        records = parse_hsinchu_city_sewer_payload(
            base_payload,
            realtime_payload,
            source_url=HSINCHU_CITY_SEWER_DATA_URL,
            resource_url=self._realtime_api_url,
            metadata_url=self._base_api_url,
        )
        fetched_at = self._fetched_at or datetime.now(UTC)
        return _raw_items(records, fetched_at=fetched_at, raw_snapshot_key=self._raw_snapshot_key)

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        return _normalize_water_level_record(self.metadata, raw_item, tag="sewer_water_level")

    def run(self) -> AdapterRunResult:
        return _run(self)


class HsinchuCityFloodSensorApiAdapter:
    metadata = HSINCHU_CITY_FLOOD_SENSOR_METADATA

    def __init__(
        self,
        *,
        station_api_url: str | None = None,
        realtime_api_url: str | None = None,
        timeout_seconds: int = DEFAULT_HSINCHU_CITY_WATER_TIMEOUT_SECONDS,
        fetched_at: datetime | None = None,
        fetch_json: FetchJson | None = None,
        raw_snapshot_key: str | None = None,
    ) -> None:
        self._station_api_url = (
            station_api_url or HSINCHU_CITY_FLOOD_SENSOR_STATION_API_URL
        ).strip()
        self._realtime_api_url = (
            realtime_api_url or HSINCHU_CITY_FLOOD_SENSOR_REALTIME_API_URL
        ).strip()
        self._timeout_seconds = max(1, timeout_seconds)
        self._fetched_at = fetched_at
        self._fetch_json = fetch_json or fetch_hsinchu_city_json
        self._raw_snapshot_key = raw_snapshot_key

    def fetch(self) -> tuple[RawSourceItem, ...]:
        try:
            station_payload = self._fetch_json(self._station_api_url, self._timeout_seconds)
            realtime_payload = self._fetch_json(self._realtime_api_url, self._timeout_seconds)
        except HsinchuCityWaterAdapterError:
            raise
        except Exception as exc:
            raise HsinchuCityWaterFetchError(
                f"{self.metadata.display_name} fetcher failed: {exc}"
            ) from exc

        station_metadata = parse_hsinchu_city_flood_sensor_station_payload(station_payload)
        records = parse_hsinchu_city_flood_sensor_realtime_payload(
            realtime_payload,
            source_url=HSINCHU_CITY_FLOOD_SENSOR_DATA_URL,
            resource_url=self._realtime_api_url,
            station_metadata=station_metadata,
            station_metadata_url=self._station_api_url,
        )
        fetched_at = self._fetched_at or datetime.now(UTC)
        return _raw_items(records, fetched_at=fetched_at, raw_snapshot_key=self._raw_snapshot_key)

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        return _normalize_flood_sensor_record(self.metadata, raw_item)

    def run(self) -> AdapterRunResult:
        return _run(self)


def fetch_hsinchu_city_json(url: str, timeout_seconds: int) -> Any:
    headers = {
        "Accept": "application/json",
        "User-Agent": HSINCHU_CITY_USER_AGENT,
    }
    body: bytes | None = None
    method = "GET"
    if url == HSINCHU_CITY_FLOOD_SENSOR_STATION_API_URL:
        body = json.dumps({"cityCode": 10018}).encode("utf-8")
        method = "POST"
    elif url == HSINCHU_CITY_FLOOD_SENSOR_REALTIME_API_URL:
        body = b"{}"
        method = "POST"
    if method == "POST":
        headers.update(
            {
                "Content-Type": "application/json; charset=utf-8",
                "Origin": "https://www.dprcflood.org.tw",
                "Referer": "https://www.dprcflood.org.tw/SGDS/",
            }
        )
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8-sig"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise HsinchuCityWaterFetchError(f"Failed to fetch Hsinchu City JSON {url}: {exc}") from exc


def parse_hsinchu_city_sewer_payload(
    base_payload: object,
    realtime_payload: object,
    *,
    source_url: str,
    resource_url: str | None = None,
    metadata_url: str | None = None,
) -> tuple[Mapping[str, Any], ...]:
    metadata_by_device = _sewer_metadata_by_device(base_payload, metadata_url=metadata_url)
    records: list[Mapping[str, Any]] = []
    for item in _payload_items(realtime_payload):
        if not isinstance(item, Mapping):
            continue
        device_uuid = _first_text(item, "Dev_UUID", "dev_uuid")
        observed_at = _parse_local_time(_first_value(item, "Time", "time"))
        water_level_m = optional_float(_first_value(item, "WaterDepth", "water_depth_m"))
        if device_uuid is None or observed_at is None or water_level_m is None:
            continue
        metadata = metadata_by_device.get(device_uuid)
        if metadata is None:
            continue
        coordinate = _coordinate(metadata.get("longitude"), metadata.get("latitude"))
        if coordinate is None:
            continue
        longitude, latitude = coordinate
        record: dict[str, Any] = {
            **metadata,
            "station_id": device_uuid,
            "observed_at": observed_at.isoformat(),
            "water_level_m": water_level_m,
            "source_url": source_url,
            "resource_url": resource_url,
            "metadata_url": metadata_url,
            "longitude": longitude,
            "latitude": latitude,
            "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
            "attribution": HSINCHU_CITY_ATTRIBUTION,
            "confidence": 0.84,
        }
        _assign_float(record, "water_level_elevation_m", _first_value(item, "WaterLevelElevation"))
        _assign_float(record, "battery_voltage", _first_value(item, "Voltage"))
        _assign_float(record, "battery_level_percent", _first_value(item, "BatLevel"))
        _assign_text(record, "quality_text", _first_text(item, "FlagName", "WaterLevelElevationState"))
        records.append(record)
    return tuple(records)


def parse_hsinchu_city_flood_sensor_station_payload(
    payload: object,
) -> dict[str, Mapping[str, Any]]:
    records: dict[str, Mapping[str, Any]] = {}
    for item in _payload_items(payload):
        if not isinstance(item, Mapping):
            continue
        if _first_text(item, "CityCode", "city_code") != "10018":
            continue
        station_id = _first_text(item, "SensorUUID", "sensor_uuid")
        station_name = _first_text(item, "SensorName", "sensor_name")
        point = item.get("Point")
        if not isinstance(point, Mapping):
            continue
        coordinate = _coordinate(
            _first_value(point, "Longitude", "longitude"),
            _first_value(point, "Latitude", "latitude"),
        )
        if station_id is None or station_name is None or coordinate is None:
            continue
        longitude, latitude = coordinate
        records[station_id] = {
            "station_id": station_id,
            "station_name": station_name,
            "address": _first_text(item, "Address", "address"),
            "location_text": _first_text(item, "Address", "address") or station_name,
            "sensor_type": _first_text(item, "SensorType", "sensor_type"),
            "authority": _first_text(item, "Supplier", "supplier") or "新竹市政府",
            "longitude": longitude,
            "latitude": latitude,
        }
    return records


def parse_hsinchu_city_flood_sensor_realtime_payload(
    payload: object,
    *,
    source_url: str,
    resource_url: str | None = None,
    station_metadata: Mapping[str, Mapping[str, Any]] | None = None,
    station_metadata_url: str | None = None,
) -> tuple[Mapping[str, Any], ...]:
    metadata_by_station = station_metadata or {}
    records: list[Mapping[str, Any]] = []
    for item in _payload_items(payload):
        if not isinstance(item, Mapping):
            continue
        station_id = _first_text(item, "SensorUUID", "sensor_uuid")
        observed_at = _parse_dotnet_date(_first_value(item, "SourceTime", "source_time"))
        flood_depth_cm = optional_float(_first_value(item, "Depth", "depth"))
        if station_id is None or observed_at is None or flood_depth_cm is None:
            continue
        if flood_depth_cm < 0:
            continue
        metadata = metadata_by_station.get(station_id)
        if metadata is None:
            continue
        coordinate = _coordinate(metadata.get("longitude"), metadata.get("latitude"))
        if coordinate is None:
            continue
        longitude, latitude = coordinate
        record: dict[str, Any] = {
            **metadata,
            "station_id": station_id,
            "observed_at": observed_at.isoformat(),
            "flood_depth_cm": flood_depth_cm,
            "source_url": source_url,
            "resource_url": resource_url,
            "station_metadata_url": station_metadata_url,
            "longitude": longitude,
            "latitude": latitude,
            "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
            "attribution": HSINCHU_CITY_ATTRIBUTION,
            "confidence": 0.84,
            "to_be_confirmed": bool(_first_value(item, "ToBeConfirm", "to_be_confirm")),
        }
        transfer_at = _parse_dotnet_date(_first_value(item, "TransferTime", "transfer_time"))
        if transfer_at is not None:
            record["transfer_at"] = transfer_at.isoformat()
        records.append(record)
    return tuple(records)


def _sewer_metadata_by_device(
    payload: object,
    *,
    metadata_url: str | None,
) -> dict[str, Mapping[str, Any]]:
    records: dict[str, Mapping[str, Any]] = {}
    for item in _payload_items(payload):
        if not isinstance(item, Mapping):
            continue
        station_no = _first_text(item, "Stt_No", "station_no")
        station_name = _first_text(item, "Stt_Name", "station_name")
        coordinate = _coordinate(_first_value(item, "Lon", "longitude"), _first_value(item, "Lat", "latitude"))
        if station_no is None or station_name is None or coordinate is None:
            continue
        equipment_rows = item.get("EqInfos")
        if not isinstance(equipment_rows, list):
            continue
        longitude, latitude = coordinate
        for equipment in equipment_rows:
            if not isinstance(equipment, Mapping):
                continue
            device_uuid = _first_text(equipment, "Dev_UUID", "dev_uuid")
            if device_uuid is None:
                continue
            record: dict[str, Any] = {
                "station_no": station_no,
                "station_name": station_name,
                "location_text": _first_text(item, "Addr", "address") or station_name,
                "address": _first_text(item, "Addr", "address"),
                "authority": _first_text(item, "Manager", "manager") or "新竹市政府工務處",
                "longitude": longitude,
                "latitude": latitude,
                "metadata_url": metadata_url,
            }
            _assign_float(record, "warning_level_m", _first_value(equipment, "Half_Elev"))
            _assign_float(record, "yellow_alert_level_m", _first_value(equipment, "Half_Elev"))
            _assign_float(record, "red_alert_level_m", _first_value(equipment, "Full_Elev"))
            _assign_float(record, "abs_warning_level_m", _first_value(equipment, "Abs_Half_Elev"))
            _assign_float(record, "abs_red_alert_level_m", _first_value(equipment, "Abs_Full_Elev"))
            _assign_text(record, "measurement_name", _first_text(equipment, "Val_Name"))
            _assign_text(record, "measurement_unit", _first_text(equipment, "Val_Unit"))
            records[device_uuid] = record
    return records


def _normalize_water_level_record(
    metadata: AdapterMetadata,
    raw_item: RawSourceItem,
    *,
    tag: str,
) -> NormalizedEvidence | None:
    payload = raw_item.payload
    station_name = optional_str(payload.get("station_name"))
    observed_at = parse_datetime(payload.get("observed_at"))
    water_level_m = optional_float(payload.get("water_level_m"))
    if station_name is None or observed_at is None or water_level_m is None:
        return None
    summary = f"新竹市地方水位觀測：{water_level_m:.2f} 公尺（{station_name}）"
    tags = ["official", "local_hsinchu_city", tag]
    warning_level_m = optional_float(payload.get("warning_level_m"))
    if warning_level_m is not None:
        gap = warning_level_m - water_level_m
        summary = f"{summary}；距警戒 {gap:.2f} 公尺"
        if gap <= 0:
            tags.append("warning_threshold_reached")
    return _evidence(
        metadata,
        raw_item,
        event_type=EventType.WATER_LEVEL,
        station_name=station_name,
        observed_at=observed_at,
        summary=summary,
        tags=tuple(tags),
    )


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
        summary = f"新竹市地方淹水感測：無觀測到淹水（0 公分）（{station_name}）"
        depth_tags = ["dry", "no_flooding_observed"]
    elif flood_depth_cm < 3:
        summary = f"新竹市地方淹水感測：低水深觀測 {_format_depth_cm(flood_depth_cm)} 公分（{station_name}）"
        depth_tags = ["below_flood_threshold", "low_depth_observation"]
    else:
        summary = f"新竹市地方淹水感測：水深 {_format_depth_cm(flood_depth_cm)} 公分（{station_name}）"
        depth_tags = []
    return _evidence(
        metadata,
        raw_item,
        event_type=EventType.FLOOD_REPORT,
        station_name=station_name,
        observed_at=observed_at,
        summary=summary,
        tags=("official", "local_hsinchu_city", "flood_sensor", *depth_tags),
    )


def _evidence(
    metadata: AdapterMetadata,
    raw_item: RawSourceItem,
    *,
    event_type: EventType,
    station_name: str,
    observed_at: datetime,
    summary: str,
    tags: tuple[str, ...],
) -> NormalizedEvidence:
    payload = raw_item.payload
    return NormalizedEvidence(
        evidence_id=stable_evidence_id(metadata.key, raw_item.source_id),
        adapter_key=metadata.key,
        source_family=metadata.family,
        event_type=event_type,
        source_id=raw_item.source_id,
        source_url=raw_item.source_url,
        source_title=f"{metadata.display_name}：{station_name}",
        source_timestamp=observed_at,
        fetched_at=raw_item.fetched_at,
        summary=summary,
        location_text=optional_str(payload.get("location_text")) or station_name,
        confidence=float(payload.get("confidence", 0.84)),
        status=IngestionStatus.NORMALIZED,
        attribution=optional_str(payload.get("attribution")) or HSINCHU_CITY_ATTRIBUTION,
        tags=tuple(dict.fromkeys(tags)),
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
        current: object = payload
        for key in ("d", "data", "Data", "Result", "result"):
            if isinstance(current, Mapping) and key in current:
                current = current[key]
        if isinstance(current, list):
            return tuple(current)
    return ()


def _parse_local_time(value: object) -> datetime | None:
    text = optional_str(value)
    if text is None:
        return None
    parsed = parse_datetime(text)
    if parsed is None:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=HSINCHU_CITY_LOCAL_TZ)
    return parsed.astimezone(UTC)


def _parse_dotnet_date(value: object) -> datetime | None:
    text = optional_str(value)
    if text is None:
        return None
    match = re.search(r"/Date\((-?\d+)\)/", text)
    if match is None:
        return parse_datetime(text)
    try:
        return datetime.fromtimestamp(int(match.group(1)) / 1000, UTC)
    except (OSError, ValueError):
        return None


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


def _assign_text(record: dict[str, Any], key: str, value: object) -> None:
    parsed = optional_str(value)
    if parsed is not None:
        record[key] = parsed


def _format_depth_cm(value: float) -> str:
    return f"{value:.0f}" if value.is_integer() else f"{value:.1f}"
