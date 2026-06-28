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

DEFAULT_YILAN_WATER_TIMEOUT_SECONDS = 8
YILAN_ATTRIBUTION = "宜蘭縣政府 / 宜蘭縣防汛儀表板 ArcGIS REST"
YILAN_USER_AGENT = "FloodRiskTaiwan/0.1 worker-local-yilan-water"
YILAN_ARCGIS_SERVICE_URL = (
    "https://wragis.e-land.gov.tw/arcgis/rest/services/HDST/"
    "%E9%98%B2%E6%B1%9B%E5%84%80%E8%A1%A8%E6%9D%BF/MapServer"
)
YILAN_FLOOD_SENSOR_LAYER_URL = (
    f"{YILAN_ARCGIS_SERVICE_URL}/0/query?where=1%3D1&outFields=*&f=json"
)
YILAN_WATER_LEVEL_LAYER_URL = (
    f"{YILAN_ARCGIS_SERVICE_URL}/2/query?where=1%3D1&outFields=*&f=json"
)
YILAN_DATA_URL = "https://wra.e-land.gov.tw/IlanHsdsMap/"

YILAN_FLOOD_SENSOR_METADATA = AdapterMetadata(
    key="local.yilan.flood_sensor",
    family=SourceFamily.OFFICIAL,
    enabled_by_default=False,
    display_name="Yilan flood sensor ArcGIS adapter",
    data_gov_url=YILAN_DATA_URL,
    resource_url=YILAN_FLOOD_SENSOR_LAYER_URL,
    update_frequency="Yilan ArcGIS layer carries write_date epoch-millisecond timestamps",
    license="Government Open Data License, version 1.0",
    limitations=(
        "Supplemental local-government flood-depth source for Yilan County.",
        "Layer 0 water_inner is interpreted as flood depth in centimeters.",
    ),
)

YILAN_WATER_LEVEL_METADATA = AdapterMetadata(
    key="local.yilan.water_level",
    family=SourceFamily.OFFICIAL,
    enabled_by_default=False,
    display_name="Yilan water-level ArcGIS adapter",
    data_gov_url=YILAN_DATA_URL,
    resource_url=YILAN_WATER_LEVEL_LAYER_URL,
    update_frequency="Yilan ArcGIS layer carries write_date epoch-millisecond timestamps",
    license="Government Open Data License, version 1.0",
    limitations=(
        "Supplemental local-government water-level source for Yilan County.",
        "Layer 2 water_inner is interpreted as water level in meters.",
    ),
)


class YilanWaterAdapterError(RuntimeError):
    """Base error for Yilan local water adapters."""


class YilanWaterFetchError(YilanWaterAdapterError):
    """Raised when fetching Yilan ArcGIS JSON fails."""


class YilanWaterPayloadError(YilanWaterAdapterError):
    """Raised when Yilan ArcGIS JSON cannot be parsed."""


class YilanFloodSensorArcgisAdapter:
    metadata = YILAN_FLOOD_SENSOR_METADATA

    def __init__(
        self,
        *,
        api_url: str | None = None,
        timeout_seconds: int = DEFAULT_YILAN_WATER_TIMEOUT_SECONDS,
        fetched_at: datetime | None = None,
        fetch_json: FetchJson | None = None,
        raw_snapshot_key: str | None = None,
    ) -> None:
        self._api_url = (api_url or YILAN_FLOOD_SENSOR_LAYER_URL).strip()
        self._timeout_seconds = max(1, timeout_seconds)
        self._fetched_at = fetched_at
        self._fetch_json = fetch_json or fetch_yilan_json
        self._raw_snapshot_key = raw_snapshot_key

    def fetch(self) -> tuple[RawSourceItem, ...]:
        try:
            payload = self._fetch_json(self._api_url, self._timeout_seconds)
        except YilanWaterAdapterError:
            raise
        except Exception as exc:
            raise YilanWaterFetchError(
                f"{self.metadata.display_name} fetcher failed: {exc}"
            ) from exc
        records = parse_yilan_flood_sensor_layer(
            payload,
            source_url=YILAN_DATA_URL,
            resource_url=self._api_url,
        )
        fetched_at = self._fetched_at or datetime.now(UTC)
        return _raw_items(records, fetched_at=fetched_at, raw_snapshot_key=self._raw_snapshot_key)

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        return _normalize_flood_sensor_record(self.metadata, raw_item)

    def run(self) -> AdapterRunResult:
        return _run(self)


class YilanWaterLevelArcgisAdapter:
    metadata = YILAN_WATER_LEVEL_METADATA

    def __init__(
        self,
        *,
        api_url: str | None = None,
        timeout_seconds: int = DEFAULT_YILAN_WATER_TIMEOUT_SECONDS,
        fetched_at: datetime | None = None,
        fetch_json: FetchJson | None = None,
        raw_snapshot_key: str | None = None,
    ) -> None:
        self._api_url = (api_url or YILAN_WATER_LEVEL_LAYER_URL).strip()
        self._timeout_seconds = max(1, timeout_seconds)
        self._fetched_at = fetched_at
        self._fetch_json = fetch_json or fetch_yilan_json
        self._raw_snapshot_key = raw_snapshot_key

    def fetch(self) -> tuple[RawSourceItem, ...]:
        try:
            payload = self._fetch_json(self._api_url, self._timeout_seconds)
        except YilanWaterAdapterError:
            raise
        except Exception as exc:
            raise YilanWaterFetchError(
                f"{self.metadata.display_name} fetcher failed: {exc}"
            ) from exc
        records = parse_yilan_water_level_layer(
            payload,
            source_url=YILAN_DATA_URL,
            resource_url=self._api_url,
        )
        fetched_at = self._fetched_at or datetime.now(UTC)
        return _raw_items(records, fetched_at=fetched_at, raw_snapshot_key=self._raw_snapshot_key)

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        return _normalize_water_level_record(self.metadata, raw_item)

    def run(self) -> AdapterRunResult:
        return _run(self)


def fetch_yilan_json(url: str, timeout_seconds: int) -> Any:
    request = Request(
        url,
        headers={"Accept": "application/json", "User-Agent": YILAN_USER_AGENT},
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8-sig"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise YilanWaterFetchError(f"Failed to fetch Yilan ArcGIS JSON {url}: {exc}") from exc


def parse_yilan_flood_sensor_layer(
    payload: object,
    *,
    source_url: str,
    resource_url: str | None = None,
) -> tuple[Mapping[str, Any], ...]:
    records: list[Mapping[str, Any]] = []
    for attributes in _feature_attributes(payload):
        station_id = _first_text(attributes, "st_no", "縣府編號")
        station_name = _first_text(attributes, "名稱", "name")
        observed_at = _parse_epoch_millis(_first_value(attributes, "write_date"))
        flood_depth_cm = optional_float(_first_value(attributes, "water_inner"))
        coordinate = _coordinate(_first_value(attributes, "E"), _first_value(attributes, "N"))
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
                part for part in (_first_text(attributes, "鄉鎮"), station_name) if part
            ),
            "town": _first_text(attributes, "鄉鎮"),
            "alert_text": _first_text(attributes, "警戒等級"),
            "authority": "宜蘭縣政府",
            "longitude": longitude,
            "latitude": latitude,
            "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
            "attribution": YILAN_ATTRIBUTION,
            "confidence": 0.84,
        }
        _assign_float(record, "warning_level_cm", _first_value(attributes, "warn_lv2"))
        _assign_float(record, "red_alert_level_cm", _first_value(attributes, "warn_lv1"))
        _assign_float(record, "low_alert_level_cm", _first_value(attributes, "warn_lv3"))
        records.append(record)
    return tuple(records)


def parse_yilan_water_level_layer(
    payload: object,
    *,
    source_url: str,
    resource_url: str | None = None,
) -> tuple[Mapping[str, Any], ...]:
    records: list[Mapping[str, Any]] = []
    for attributes in _feature_attributes(payload):
        station_id = _first_text(attributes, "st_no", "st_id")
        station_name = _first_text(attributes, "st_name", "name")
        observed_at = _parse_epoch_millis(_first_value(attributes, "write_date"))
        water_level_m = optional_float(_first_value(attributes, "water_inner"))
        coordinate = _coordinate(_first_value(attributes, "E"), _first_value(attributes, "N"))
        if (
            station_id is None
            or station_name is None
            or observed_at is None
            or water_level_m is None
            or coordinate is None
        ):
            continue
        longitude, latitude = coordinate
        record: dict[str, Any] = {
            "station_id": station_id,
            "station_name": station_name,
            "observed_at": observed_at.isoformat(),
            "water_level_m": water_level_m,
            "source_url": source_url,
            "resource_url": resource_url,
            "location_text": station_name,
            "alert_text": _first_text(attributes, "war"),
            "image_url": _first_text(attributes, "影像路徑"),
            "authority": "宜蘭縣政府",
            "longitude": longitude,
            "latitude": latitude,
            "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
            "attribution": YILAN_ATTRIBUTION,
            "confidence": 0.84,
        }
        _assign_float(record, "warning_level_m", _first_value(attributes, "war_ele"))
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
        summary = f"宜蘭地方淹水感測：無觀測到淹水（0 公分）（{station_name}）"
        depth_tags = ["dry", "no_flooding_observed"]
    elif flood_depth_cm < 3:
        summary = f"宜蘭地方淹水感測：低水深觀測 {_format_depth_cm(flood_depth_cm)} 公分（{station_name}）"
        depth_tags = ["below_flood_threshold", "low_depth_observation"]
    else:
        summary = f"宜蘭地方淹水感測：水深 {_format_depth_cm(flood_depth_cm)} 公分（{station_name}）"
        depth_tags = []
    return _evidence(
        metadata,
        raw_item,
        event_type=EventType.FLOOD_REPORT,
        station_name=station_name,
        observed_at=observed_at,
        summary=summary,
        tags=("official", "local_yilan", "flood_sensor", *depth_tags),
    )


def _normalize_water_level_record(
    metadata: AdapterMetadata,
    raw_item: RawSourceItem,
) -> NormalizedEvidence | None:
    payload = raw_item.payload
    station_name = optional_str(payload.get("station_name"))
    observed_at = parse_datetime(payload.get("observed_at"))
    water_level_m = optional_float(payload.get("water_level_m"))
    if station_name is None or observed_at is None or water_level_m is None:
        return None
    summary = f"宜蘭地方水位觀測：{water_level_m:.2f} 公尺（{station_name}）"
    tags = ["official", "local_yilan", "water_level"]
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
        attribution=optional_str(payload.get("attribution")) or YILAN_ATTRIBUTION,
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


def _feature_attributes(payload: object) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(payload, Mapping):
        return ()
    features = payload.get("features")
    if not isinstance(features, list):
        return ()
    records: list[Mapping[str, Any]] = []
    for feature in features:
        if not isinstance(feature, Mapping):
            continue
        attributes = feature.get("attributes")
        if isinstance(attributes, Mapping):
            records.append(attributes)
    return tuple(records)


def _parse_epoch_millis(value: object) -> datetime | None:
    millis = optional_float(value)
    if millis is None:
        return None
    try:
        return datetime.fromtimestamp(millis / 1000, UTC)
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


def _format_depth_cm(value: float) -> str:
    return f"{value:.0f}" if value.is_integer() else f"{value:.1f}"
