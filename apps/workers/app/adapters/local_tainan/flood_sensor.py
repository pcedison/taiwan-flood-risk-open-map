from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
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

TAINAN_FLOOD_SENSOR_DATA_GOV_URL = (
    "https://data.tainan.gov.tw/DataSet/Detail/03dd4536-3fe7-46ec-9920-a120cb5c502c"
)
TAINAN_FLOOD_SENSOR_API_URL = (
    "https://soa.tainan.gov.tw/Api/Service/Get/21b31a27-3e61-48b8-8259-83c2001bec8c"
)
TAINAN_FLOOD_SENSOR_METADATA_API_URL = (
    "https://soa.tainan.gov.tw/Api/Service/Get/cdc1ead4-d56a-4092-8e1c-e1f2fa9ee864"
)
TAINAN_FLOOD_SENSOR_ATTRIBUTION = "臺南市政府水利局 / 臺南市政府資料開放平台"
DEFAULT_TAINAN_FLOOD_SENSOR_TIMEOUT_SECONDS = 8
TAINAN_LOCAL_TZ = timezone(timedelta(hours=8))

TAINAN_FLOOD_SENSOR_METADATA = AdapterMetadata(
    key="local.tainan.flood_sensor",
    family=SourceFamily.OFFICIAL,
    enabled_by_default=False,
    display_name="Tainan local open-data flood sensor fallback",
    data_gov_url=TAINAN_FLOOD_SENSOR_DATA_GOV_URL,
    resource_url=TAINAN_FLOOD_SENSOR_API_URL,
    update_frequency=(
        "Tainan open-data catalog metadata lists update frequency as 1 year; "
        "the realtime API carries per-station InfoTime timestamps and must be "
        "freshness-checked from observation time."
    ),
    license="Government Open Data License, version 1.0",
    limitations=(
        "Supplemental local-government source for Tainan only; it must not "
        "replace the Civil IoT L1 flood-sensor backbone.",
        "Only the documented Tainan open-data API resources are used; WMap or "
        "other undocumented map internals are not production sources.",
        "Station coordinates come from the paired station metadata resource. "
        "Records without a metadata point keep quality flags and are not "
        "eligible for latest point upsert.",
        "InfoTime values are timezone-naive in the API and are interpreted as "
        "Asia/Taipei local time before UTC normalization.",
    ),
)


class TainanFloodSensorAdapterError(RuntimeError):
    """Base error for Tainan flood sensor adapter failures."""


class TainanFloodSensorFetchError(TainanFloodSensorAdapterError):
    """Raised when fetching Tainan flood sensor API payloads fails."""


class TainanFloodSensorPayloadError(TainanFloodSensorAdapterError):
    """Raised when a Tainan flood sensor payload cannot be parsed."""


class TainanFloodSensorApiAdapter:
    metadata = TAINAN_FLOOD_SENSOR_METADATA

    def __init__(
        self,
        *,
        api_url: str | None = None,
        metadata_api_url: str | None = None,
        timeout_seconds: int = DEFAULT_TAINAN_FLOOD_SENSOR_TIMEOUT_SECONDS,
        fetched_at: datetime | None = None,
        fetch_json: FetchJson | None = None,
        raw_snapshot_key: str | None = None,
    ) -> None:
        self._api_url = (api_url or TAINAN_FLOOD_SENSOR_API_URL).strip()
        self._metadata_api_url = (
            metadata_api_url or TAINAN_FLOOD_SENSOR_METADATA_API_URL
        ).strip()
        self._timeout_seconds = max(1, timeout_seconds)
        self._fetched_at = fetched_at
        self._fetch_json = fetch_json or fetch_tainan_json
        self._raw_snapshot_key = raw_snapshot_key

    def fetch(self) -> tuple[RawSourceItem, ...]:
        try:
            metadata_payload = self._fetch_json(self._metadata_api_url, self._timeout_seconds)
            realtime_payload = self._fetch_json(self._api_url, self._timeout_seconds)
        except TainanFloodSensorAdapterError:
            raise
        except Exception as exc:
            raise TainanFloodSensorFetchError(
                f"Tainan flood sensor fetcher failed: {exc}"
            ) from exc

        station_metadata = parse_tainan_flood_sensor_metadata_payload(metadata_payload)
        records = parse_tainan_flood_sensor_realtime_payload(
            realtime_payload,
            source_url=TAINAN_FLOOD_SENSOR_DATA_GOV_URL,
            resource_url=self._api_url,
            station_metadata=station_metadata,
            station_metadata_url=self._metadata_api_url,
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
        return _normalize_tainan_flood_sensor_record(self.metadata, raw_item)

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


def fetch_tainan_json(url: str, timeout_seconds: int) -> Any:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "FloodRiskTaiwan/0.1 worker-local-tainan-flood-sensor",
        },
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8-sig"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise TainanFloodSensorFetchError(f"Failed to fetch Tainan API {url}: {exc}") from exc


def parse_tainan_flood_sensor_metadata_payload(
    payload: object,
) -> dict[str, Mapping[str, Any]]:
    records: dict[str, Mapping[str, Any]] = {}
    for item in _payload_items(payload, label="Tainan flood sensor metadata"):
        if not isinstance(item, Mapping):
            continue
        record = _parse_tainan_metadata_record(item)
        if record is None:
            continue
        records[_station_lookup_key(record["station_id"])] = record
    return records


def parse_tainan_flood_sensor_realtime_payload(
    payload: object,
    *,
    source_url: str,
    resource_url: str | None = None,
    station_metadata: Mapping[str, Mapping[str, Any]] | None = None,
    station_metadata_url: str | None = None,
) -> tuple[Mapping[str, Any], ...]:
    parsed: list[Mapping[str, Any]] = []
    metadata_by_station = station_metadata or {}
    for item in _payload_items(payload, label="Tainan flood sensor realtime"):
        if not isinstance(item, Mapping):
            continue
        record = _parse_tainan_realtime_record(
            item,
            source_url=source_url,
            resource_url=resource_url,
            station_metadata=metadata_by_station,
            station_metadata_url=station_metadata_url,
        )
        if record is not None:
            parsed.append(record)
    return tuple(parsed)


def _parse_tainan_metadata_record(item: Mapping[str, Any]) -> Mapping[str, Any] | None:
    station_id = _first_text(item, "StationID", "station_id", "stationId")
    if station_id is None:
        return None

    record: dict[str, Any] = {"station_id": station_id}
    _assign_text(record, "station_name", _first_text(item, "StationName", "station_name"))
    _assign_text(record, "authority", _first_text(item, "Owner", "owner", "authority"))
    _assign_text(record, "district_id", _first_text(item, "DistrictID", "district_id"))
    _assign_float(record, "land_level_m", _first_value(item, "LandLevel", "land_level_m"))
    _assign_float(record, "alert_level_cm", _first_value(item, "AlertLevel", "alert_level_cm"))
    enabled = _optional_bool(_first_value(item, "IsEnabled", "is_enabled"))
    if enabled is not None:
        record["metadata_station_enabled"] = enabled

    coordinate = _metadata_coordinate(item)
    if coordinate is not None:
        longitude, latitude = coordinate
        record["longitude"] = longitude
        record["latitude"] = latitude
        record["geometry"] = {"type": "Point", "coordinates": [longitude, latitude]}

    return record


def _parse_tainan_realtime_record(
    item: Mapping[str, Any],
    *,
    source_url: str,
    resource_url: str | None,
    station_metadata: Mapping[str, Mapping[str, Any]],
    station_metadata_url: str | None,
) -> Mapping[str, Any] | None:
    station_id = _first_text(item, "StationID", "station_id", "stationId")
    observed_at = _parse_tainan_observed_at(_first_value(item, "InfoTime", "info_time"))
    flood_depth_cm = optional_float(_first_value(item, "WaterDepth", "water_depth_cm"))
    if station_id is None or observed_at is None or flood_depth_cm is None:
        return None
    if flood_depth_cm < 0:
        return None

    metadata = station_metadata.get(_station_lookup_key(station_id))
    station_name = _metadata_text(metadata, "station_name") or station_id
    authority = _metadata_text(metadata, "authority") or TAINAN_FLOOD_SENSOR_ATTRIBUTION
    water_inner_doubt = _optional_bool(_first_value(item, "IsWaterInnerDoubt"))
    quality_flags = {
        "missing_station_coordinates": "geometry" not in (metadata or {}),
        "station_metadata_missing": metadata is None,
        "water_inner_doubt": water_inner_doubt is True,
    }

    record: dict[str, Any] = {
        "station_id": station_id,
        "station_name": station_name,
        "observed_at": observed_at.isoformat(),
        "flood_depth_cm": flood_depth_cm,
        "source_url": source_url,
        "location_text": station_name,
        "authority": authority,
        "attribution": TAINAN_FLOOD_SENSOR_ATTRIBUTION,
        "confidence": _confidence(quality_flags),
        "quality_flags": quality_flags,
    }
    if resource_url is not None:
        record["resource_url"] = resource_url
    if station_metadata_url is not None:
        record["station_metadata_url"] = station_metadata_url

    for target_key, source_key in (
        ("battery_voltage", "BatteryVoltage"),
        ("rssi", "RSSI"),
        ("snr", "SNR"),
    ):
        _assign_float(record, target_key, _first_value(item, source_key))

    realtime_enabled = _optional_bool(_first_value(item, "IsEnabled", "is_enabled"))
    if realtime_enabled is not None:
        record["realtime_station_enabled"] = realtime_enabled

    if metadata is not None:
        for key in (
            "district_id",
            "land_level_m",
            "alert_level_cm",
            "metadata_station_enabled",
            "latitude",
            "longitude",
            "geometry",
        ):
            if key in metadata:
                record[key] = metadata[key]
        if "geometry" in metadata:
            quality_flags["missing_station_coordinates"] = False

    return record


def _normalize_tainan_flood_sensor_record(
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
        summary = f"台南地方淹水感測：無觀測到淹水（0 公分）（{station_name}）"
        depth_tags = ["dry", "no_flooding_observed"]
    elif flood_depth_cm < 3:
        summary = (
            f"台南地方淹水感測：低水深觀測 {_format_depth_cm(flood_depth_cm)} "
            f"公分（{station_name}）"
        )
        depth_tags = ["below_flood_threshold", "low_depth_observation"]
    else:
        summary = (
            f"台南地方淹水感測：水深 {_format_depth_cm(flood_depth_cm)} "
            f"公分（{station_name}）"
        )
        depth_tags = []

    tags = [
        "official",
        "local_tainan",
        "flood_sensor",
        "supplemental_civil_iot",
        *depth_tags,
        *_quality_flag_tags(payload.get("quality_flags")),
    ]

    return NormalizedEvidence(
        evidence_id=stable_evidence_id(metadata.key, raw_item.source_id),
        adapter_key=metadata.key,
        source_family=metadata.family,
        event_type=EventType.FLOOD_REPORT,
        source_id=raw_item.source_id,
        source_url=raw_item.source_url,
        source_title=f"台南地方淹水感測器觀測：{station_name}",
        source_timestamp=observed_at,
        fetched_at=raw_item.fetched_at,
        summary=summary,
        location_text=optional_str(payload.get("location_text")) or station_name,
        confidence=float(payload.get("confidence", 0.82)),
        status=IngestionStatus.NORMALIZED,
        attribution=optional_str(payload.get("attribution")) or TAINAN_FLOOD_SENSOR_ATTRIBUTION,
        tags=tuple(dict.fromkeys(tags)),
    )


def _payload_items(payload: object, *, label: str) -> Iterable[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, Mapping):
        items = payload.get("data")
        if isinstance(items, list):
            return items
        for key in ("Data", "records", "value"):
            items = payload.get(key)
            if isinstance(items, list):
                return items
    raise TainanFloodSensorPayloadError(f"{label} payload is missing a data list")


def _parse_tainan_observed_at(value: object) -> datetime | None:
    parsed = parse_datetime(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=TAINAN_LOCAL_TZ)
    return parsed.astimezone(UTC)


def _metadata_coordinate(item: Mapping[str, Any]) -> tuple[float, float] | None:
    point = item.get("Point") or item.get("point")
    longitude = None
    latitude = None
    if isinstance(point, Mapping):
        longitude = optional_float(_first_value(point, "Longitude", "longitude", "lng", "x"))
        latitude = optional_float(_first_value(point, "Latitude", "latitude", "lat", "y"))
    if longitude is None:
        longitude = optional_float(_first_value(item, "Longitude", "longitude", "lng", "x"))
    if latitude is None:
        latitude = optional_float(_first_value(item, "Latitude", "latitude", "lat", "y"))
    if longitude is None or latitude is None:
        return None
    if not (118.0 <= longitude <= 123.5 and 21.0 <= latitude <= 26.5):
        return None
    return longitude, latitude


def _source_id(record: Mapping[str, Any]) -> str:
    return f"{record['station_id']}:{record['observed_at']}"


def _station_lookup_key(value: object) -> str:
    return str(value).strip().casefold()


def _first_value(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _first_text(mapping: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        text = optional_str(mapping.get(key))
        if text is not None:
            return text
    return None


def _metadata_text(metadata: Mapping[str, Any] | None, key: str) -> str | None:
    if metadata is None:
        return None
    return optional_str(metadata.get(key))


def _assign_text(record: dict[str, Any], key: str, value: str | None) -> None:
    if value is not None:
        record[key] = value


def _assign_float(record: dict[str, Any], key: str, value: object) -> None:
    parsed = optional_float(value)
    if parsed is not None:
        record[key] = parsed


def _optional_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    text = optional_str(value)
    if text is None:
        return None
    lowered = text.lower()
    if lowered in {"true", "1", "yes", "y", "on"}:
        return True
    if lowered in {"false", "0", "no", "n", "off"}:
        return False
    return None


def _confidence(quality_flags: Mapping[str, bool]) -> float:
    confidence = 0.82
    if quality_flags.get("missing_station_coordinates"):
        confidence -= 0.12
    if quality_flags.get("station_metadata_missing"):
        confidence -= 0.08
    if quality_flags.get("water_inner_doubt"):
        confidence -= 0.2
    return max(0.4, round(confidence, 2))


def _quality_flag_tags(value: object) -> tuple[str, ...]:
    if not isinstance(value, Mapping):
        return ()
    return tuple(str(key) for key, enabled in value.items() if enabled is True)


def _format_depth_cm(depth_cm: float) -> str:
    if depth_cm == 0:
        return "0"
    formatted = format(Decimal(str(depth_cm)).normalize(), "f")
    return formatted.rstrip("0").rstrip(".")
