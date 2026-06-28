from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.adapters._helpers import optional_float, optional_str, parse_datetime
from app.adapters._helpers import parse_observed_at_utc, stable_evidence_id
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

WRA_IOW_FLOOD_DEPTH_API_URL = (
    "https://opendata.wra.gov.tw/api/v2/1b991bbb-ad85-4e7a-b931-06ce8749d3ed"
    "?format=JSON&sort=_importdate%20asc&limit=5000"
)
WRA_IOW_FLOOD_SENSOR_METADATA_API_URL = (
    "https://opendata.wra.gov.tw/api/v2/21c50be1-7c4a-4fdf-a386-790625e984e7"
    "?format=JSON&sort=_importdate%20asc&limit=5000"
)
WRA_IOW_FLOOD_DEPTH_DATA_GOV_URL = "https://data.gov.tw/dataset/142980"
WRA_IOW_FLOOD_SENSOR_METADATA_DATA_GOV_URL = "https://data.gov.tw/dataset/142979"
WRA_IOW_FLOOD_DEPTH_ATTRIBUTION = "Water Resources Agency / IoW flood depth"
WRA_IOW_FLOOD_DEPTH_USER_AGENT = "FloodRiskTaiwan/0.1 worker-wra-iow-flood-depth"
DEFAULT_WRA_IOW_FLOOD_DEPTH_TIMEOUT_SECONDS = 8

WRA_IOW_FLOOD_DEPTH_METADATA = AdapterMetadata(
    key="official.wra_iow.flood_depth",
    family=SourceFamily.OFFICIAL,
    enabled_by_default=False,
    display_name="WRA IoW flood depth adapter",
    data_gov_dataset_id="142980",
    data_gov_url=WRA_IOW_FLOOD_DEPTH_DATA_GOV_URL,
    resource_url=WRA_IOW_FLOOD_DEPTH_API_URL,
    update_frequency=(
        "WRA IoW latest flood-depth observations refresh from sensor telemetry; "
        "freshness must be checked from each timestamp."
    ),
    license="Government Open Data License, version 1.0",
    limitations=(
        "Latest values are raw IoW telemetry and may be affected by sensor or "
        "transmission faults.",
        "Station coordinates are joined from the paired WRA IoW basic metadata "
        "dataset; rows without coordinates are rejected from normalization.",
    ),
)


class WraIowFloodDepthAdapterError(RuntimeError):
    """Base error for WRA IoW flood depth adapter failures."""


class WraIowFloodDepthFetchError(WraIowFloodDepthAdapterError):
    """Raised when fetching WRA IoW payloads fails."""


class WraIowFloodDepthPayloadError(WraIowFloodDepthAdapterError):
    """Raised when WRA IoW payloads cannot be parsed."""


class WraIowFloodDepthApiAdapter:
    metadata = WRA_IOW_FLOOD_DEPTH_METADATA

    def __init__(
        self,
        *,
        api_url: str | None = None,
        metadata_api_url: str | None = None,
        timeout_seconds: int = DEFAULT_WRA_IOW_FLOOD_DEPTH_TIMEOUT_SECONDS,
        fetched_at: datetime | None = None,
        fetch_json: FetchJson | None = None,
        raw_snapshot_key: str | None = None,
    ) -> None:
        self._api_url = (api_url or WRA_IOW_FLOOD_DEPTH_API_URL).strip()
        self._metadata_api_url = (
            metadata_api_url or WRA_IOW_FLOOD_SENSOR_METADATA_API_URL
        ).strip()
        self._timeout_seconds = max(1, timeout_seconds)
        self._fetched_at = fetched_at
        self._fetch_json = fetch_json or fetch_wra_iow_json
        self._raw_snapshot_key = raw_snapshot_key

    def fetch(self) -> tuple[RawSourceItem, ...]:
        try:
            metadata_payload = self._fetch_json(self._metadata_api_url, self._timeout_seconds)
            latest_payload = self._fetch_json(self._api_url, self._timeout_seconds)
        except WraIowFloodDepthAdapterError:
            raise
        except Exception as exc:
            raise WraIowFloodDepthFetchError(
                f"WRA IoW flood depth fetcher failed: {exc}"
            ) from exc

        station_metadata = parse_wra_iow_flood_sensor_metadata_payload(metadata_payload)
        records = parse_wra_iow_flood_depth_latest_payload(
            latest_payload,
            source_url=WRA_IOW_FLOOD_DEPTH_DATA_GOV_URL,
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
        return _normalize_wra_iow_flood_depth_record(self.metadata, raw_item)

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


def fetch_wra_iow_json(url: str, timeout_seconds: int) -> Any:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": WRA_IOW_FLOOD_DEPTH_USER_AGENT,
        },
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8-sig"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise WraIowFloodDepthFetchError(f"Failed to fetch WRA IoW API {url}: {exc}") from exc


def parse_wra_iow_flood_sensor_metadata_payload(
    payload: object,
) -> dict[str, Mapping[str, Any]]:
    records: dict[str, Mapping[str, Any]] = {}
    for item in _payload_items(payload, label="WRA IoW flood sensor metadata"):
        if not isinstance(item, Mapping):
            continue
        record = _parse_metadata_record(item)
        if record is None:
            continue
        records[_station_lookup_key(record["station_id"])] = record
    return records


def parse_wra_iow_flood_depth_latest_payload(
    payload: object,
    *,
    source_url: str,
    resource_url: str | None = None,
    station_metadata: Mapping[str, Mapping[str, Any]] | None = None,
    station_metadata_url: str | None = None,
) -> tuple[Mapping[str, Any], ...]:
    parsed: list[Mapping[str, Any]] = []
    metadata_by_station = station_metadata or {}
    for item in _payload_items(payload, label="WRA IoW flood depth latest"):
        if not isinstance(item, Mapping):
            continue
        record = _parse_latest_record(
            item,
            source_url=source_url,
            resource_url=resource_url,
            station_metadata=metadata_by_station,
            station_metadata_url=station_metadata_url,
        )
        if record is not None:
            parsed.append(record)
    return tuple(parsed)


def _parse_metadata_record(item: Mapping[str, Any]) -> Mapping[str, Any] | None:
    station_id = _first_text(item, "sensorid", "SensorID", "station_id")
    if station_id is None:
        return None

    record: dict[str, Any] = {"station_id": station_id}
    _assign_text(
        record,
        "station_name",
        _first_text(item, "stationname", "observatoryname", "sensorfullname", "sensorname"),
    )
    _assign_text(record, "authority", _first_text(item, "orgname", "authority"))
    _assign_text(record, "county", _first_text(item, "countyname", "county"))
    _assign_text(record, "town", _first_text(item, "townname", "town"))
    _assign_text(record, "county_code", _first_text(item, "countycode"))
    _assign_text(record, "area_code", _first_text(item, "areacode"))
    _assign_text(record, "category", _first_text(item, "category"))
    _assign_text(record, "unit", _first_text(item, "unit"))

    enabled = _optional_bool(_first_value(item, "isenable", "isEnable", "enabled"))
    if enabled is not None:
        record["sensor_enabled"] = enabled

    coordinate = _coordinate(item)
    if coordinate is not None:
        longitude, latitude = coordinate
        record["longitude"] = longitude
        record["latitude"] = latitude
        record["geometry"] = {"type": "Point", "coordinates": [longitude, latitude]}

    return record


def _parse_latest_record(
    item: Mapping[str, Any],
    *,
    source_url: str,
    resource_url: str | None,
    station_metadata: Mapping[str, Mapping[str, Any]],
    station_metadata_url: str | None,
) -> Mapping[str, Any] | None:
    station_id = _first_text(item, "sensorid", "SensorID", "station_id")
    observed_at = parse_observed_at_utc(_first_value(item, "timestamp", "observed_at"))
    flood_depth_cm = optional_float(_first_value(item, "latestvalue", "flood_depth_cm"))
    if station_id is None or observed_at is None or flood_depth_cm is None:
        return None
    if flood_depth_cm < 0:
        return None

    metadata = station_metadata.get(_station_lookup_key(station_id))
    sensor_enabled = _metadata_bool(metadata, "sensor_enabled")
    quality_flags = {
        "station_metadata_missing": metadata is None,
        "missing_station_coordinates": "geometry" not in (metadata or {}),
        "sensor_disabled": sensor_enabled is False,
    }

    station_name = _metadata_text(metadata, "station_name") or station_id
    county = _metadata_text(metadata, "county")
    town = _metadata_text(metadata, "town")
    location_text = " ".join(part for part in (county, town, station_name) if part)
    record: dict[str, Any] = {
        "station_id": station_id,
        "station_name": station_name,
        "observed_at": observed_at.isoformat(),
        "flood_depth_cm": flood_depth_cm,
        "source_url": source_url,
        "location_text": location_text or station_name,
        "authority": _metadata_text(metadata, "authority") or WRA_IOW_FLOOD_DEPTH_ATTRIBUTION,
        "attribution": WRA_IOW_FLOOD_DEPTH_ATTRIBUTION,
        "confidence": _confidence(quality_flags),
        "quality_flags": quality_flags,
    }
    if resource_url is not None:
        record["resource_url"] = resource_url
    if station_metadata_url is not None:
        record["station_metadata_url"] = station_metadata_url
    _assign_text(record, "county_code", _first_text(item, "countycode") or _metadata_text(metadata, "county_code"))
    _assign_text(record, "area_code", _first_text(item, "areacode") or _metadata_text(metadata, "area_code"))

    if metadata is not None:
        for key in (
            "county",
            "town",
            "category",
            "unit",
            "longitude",
            "latitude",
            "geometry",
            "sensor_enabled",
        ):
            if key in metadata:
                record[key] = metadata[key]

    return record


def _normalize_wra_iow_flood_depth_record(
    metadata: AdapterMetadata,
    raw_item: RawSourceItem,
) -> NormalizedEvidence | None:
    payload = raw_item.payload
    quality_flags = payload.get("quality_flags")
    if isinstance(quality_flags, Mapping) and (
        quality_flags.get("missing_station_coordinates") is True
        or quality_flags.get("sensor_disabled") is True
    ):
        return None

    station_name = optional_str(payload.get("station_name"))
    observed_at = parse_datetime(payload.get("observed_at"))
    flood_depth_cm = optional_float(payload.get("flood_depth_cm"))
    if station_name is None or observed_at is None or flood_depth_cm is None:
        return None

    if flood_depth_cm == 0:
        summary = f"WRA IoW 淹水深度：無觀測到淹水（0 公分）（{station_name}）"
        depth_tags = ["dry", "no_flooding_observed"]
    elif flood_depth_cm < 3:
        summary = (
            f"WRA IoW 淹水深度：低水深觀測 {_format_depth_cm(flood_depth_cm)} "
            f"公分（{station_name}）"
        )
        depth_tags = ["below_flood_threshold", "low_depth_observation"]
    else:
        summary = (
            f"WRA IoW 淹水深度：水深 {_format_depth_cm(flood_depth_cm)} "
            f"公分（{station_name}）"
        )
        depth_tags = []

    tags = [
        "official",
        "wra_iow",
        "flood_sensor",
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
        source_title=f"WRA IoW 淹水深度觀測：{station_name}",
        source_timestamp=observed_at,
        fetched_at=raw_item.fetched_at,
        summary=summary,
        location_text=optional_str(payload.get("location_text")) or station_name,
        confidence=float(payload.get("confidence", 0.86)),
        status=IngestionStatus.NORMALIZED,
        attribution=optional_str(payload.get("attribution")) or WRA_IOW_FLOOD_DEPTH_ATTRIBUTION,
        tags=tuple(dict.fromkeys(tags)),
    )


def _payload_items(payload: object, *, label: str) -> Iterable[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, Mapping):
        for key in ("records", "Record", "data", "Data", "value"):
            items = payload.get(key)
            if isinstance(items, list):
                return items
    raise WraIowFloodDepthPayloadError(f"{label} payload is missing a records list")


def _coordinate(item: Mapping[str, Any]) -> tuple[float, float] | None:
    longitude = optional_float(_first_value(item, "longitude", "Longitude", "lng", "x"))
    latitude = optional_float(_first_value(item, "latitude", "Latitude", "lat", "y"))
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


def _metadata_bool(metadata: Mapping[str, Any] | None, key: str) -> bool | None:
    if metadata is None:
        return None
    value = metadata.get(key)
    return value if isinstance(value, bool) else None


def _assign_text(record: dict[str, Any], key: str, value: str | None) -> None:
    if value is not None:
        record[key] = value


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
    confidence = 0.86
    if quality_flags.get("missing_station_coordinates"):
        confidence -= 0.14
    if quality_flags.get("station_metadata_missing"):
        confidence -= 0.08
    if quality_flags.get("sensor_disabled"):
        confidence -= 0.3
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
