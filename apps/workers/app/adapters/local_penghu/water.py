from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime, timedelta
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

DEFAULT_PENGHU_WATER_TIMEOUT_SECONDS = 8
PENGHU_MAX_FUTURE_SKEW_MINUTES = 15
PENGHU_STALE_AFTER_MINUTES = 180
PENGHU_ARCGIS_LOCAL_EPOCH_OFFSET_HOURS = 8
PENGHU_ATTRIBUTION = "澎湖縣政府 / 澎湖縣智慧水位計 ArcGIS REST"
PENGHU_USER_AGENT = "FloodRiskTaiwan/0.1 worker-local-penghu-water"
PENGHU_DATA_URL = "https://ph3dgis.penghu.gov.tw/"
PENGHU_WATER_LEVEL_LAYER_URL = (
    "https://ph3dgis.penghu.gov.tw/server/rest/services/SewerNew/"
    "PHSewer_Basemap/MapServer/6/query?"
    "where=1%3D1&outFields=*&f=json&returnGeometry=true&outSR=4326"
)

PENGHU_WATER_LEVEL_METADATA = AdapterMetadata(
    key="local.penghu.water_level",
    family=SourceFamily.OFFICIAL,
    enabled_by_default=False,
    display_name="Penghu local water-level ArcGIS adapter",
    data_gov_url=PENGHU_DATA_URL,
    resource_url=PENGHU_WATER_LEVEL_LAYER_URL,
    update_frequency=(
        "Penghu ArcGIS layer carries measure_time epoch-millisecond timestamps encoded "
        "as Taiwan local wall-clock time"
    ),
    license="Official public endpoint; explicit open-data license not separately located",
    limitations=(
        "Supplemental local-government drainage water-level source for Penghu County.",
        "water_level is exposed in millimeters and normalized to meters; raw millimeter "
        "value and water_level_percent are preserved.",
        "measure_time/upload_time are epoch-millisecond values whose decoded UTC time is "
        "8 hours ahead of the observed Taiwan wall-clock time; this adapter subtracts "
        "8 hours before freshness checks.",
    ),
)


class PenghuWaterAdapterError(RuntimeError):
    """Base error for Penghu local water adapters."""


class PenghuWaterFetchError(PenghuWaterAdapterError):
    """Raised when fetching Penghu ArcGIS JSON fails."""


class PenghuWaterPayloadError(PenghuWaterAdapterError):
    """Raised when Penghu ArcGIS JSON cannot be parsed."""


class PenghuWaterLevelArcgisAdapter:
    metadata = PENGHU_WATER_LEVEL_METADATA

    def __init__(
        self,
        *,
        api_url: str | None = None,
        timeout_seconds: int = DEFAULT_PENGHU_WATER_TIMEOUT_SECONDS,
        fetched_at: datetime | None = None,
        fetch_json: FetchJson | None = None,
        raw_snapshot_key: str | None = None,
    ) -> None:
        self._api_url = (api_url or PENGHU_WATER_LEVEL_LAYER_URL).strip()
        self._timeout_seconds = max(1, timeout_seconds)
        self._fetched_at = fetched_at
        self._fetch_json = fetch_penghu_json if fetch_json is None else fetch_json
        self._raw_snapshot_key = raw_snapshot_key

    def fetch(self) -> tuple[RawSourceItem, ...]:
        try:
            payload = self._fetch_json(self._api_url, self._timeout_seconds)
        except PenghuWaterAdapterError:
            raise
        except Exception as exc:
            raise PenghuWaterFetchError(
                f"{self.metadata.display_name} fetcher failed: {exc}"
            ) from exc
        fetched_at = self._fetched_at or datetime.now(UTC)
        records = parse_penghu_water_level_layer(
            payload,
            source_url=PENGHU_DATA_URL,
            resource_url=self._api_url,
            fetched_at=fetched_at,
        )
        return _raw_items(records, fetched_at=fetched_at, raw_snapshot_key=self._raw_snapshot_key)

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        return _normalize_water_level_record(self.metadata, raw_item)

    def run(self) -> AdapterRunResult:
        return _run(self)


def fetch_penghu_json(url: str, timeout_seconds: int) -> Any:
    request = Request(
        url,
        headers={"Accept": "application/json", "User-Agent": PENGHU_USER_AGENT},
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8-sig"))
    except (HTTPError, URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PenghuWaterFetchError(f"Failed to fetch Penghu ArcGIS JSON {url}: {exc}") from exc


def parse_penghu_water_level_layer(
    payload: object,
    *,
    source_url: str,
    resource_url: str | None = None,
    fetched_at: datetime | None = None,
) -> tuple[Mapping[str, Any], ...]:
    records: list[Mapping[str, Any]] = []
    for attributes, geometry in _features(payload):
        station_id = _first_text(attributes, "SttNo", "device_id")
        station_name = _first_text(attributes, "SttName", "Addr")
        observed_at = _parse_epoch_millis(_first_value(attributes, "measure_time"))
        water_level_mm = optional_float(_first_value(attributes, "water_level"))
        coordinate = _coordinate_from_geometry(geometry)
        if (
            station_id is None
            or station_name is None
            or observed_at is None
            or water_level_mm is None
            or coordinate is None
        ):
            continue
        if water_level_mm < 0:
            continue
        longitude, latitude = coordinate
        record: dict[str, Any] = {
            "station_id": station_id,
            "station_name": station_name,
            "observed_at": observed_at.isoformat(),
            "water_level_m": water_level_mm / 1000,
            "water_level_mm": water_level_mm,
            "source_url": source_url,
            "resource_url": resource_url,
            "location_text": _location_text(attributes, station_name),
            "town": _town_from_county_code(_first_text(attributes, "CountyCode")),
            "urban_plan": _first_text(attributes, "UrbanPlan"),
            "pipe_name": _first_text(attributes, "PipeNum"),
            "address": _first_text(attributes, "Addr"),
            "purpose": _first_text(attributes, "SttPurpose"),
            "status_text": _first_text(attributes, "water_level_status"),
            "authority": _first_text(attributes, "Manager") or "澎湖縣政府",
            "longitude": longitude,
            "latitude": latitude,
            "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
            "attribution": PENGHU_ATTRIBUTION,
            "confidence": 0.82,
            "quality_flags": _quality_flags(observed_at, fetched_at=fetched_at),
        }
        _assign_float(record, "water_level_percent", _first_value(attributes, "water_level_percent"))
        _assign_float(record, "warning_level_m", _first_value(attributes, "HalfHeight"))
        _assign_float(record, "red_alert_level_m", _first_value(attributes, "FullHeight"))
        _assign_float(record, "manhole_depth_m", _first_value(attributes, "ManholeDepth"))
        _assign_float(record, "battery_percent", _first_value(attributes, "battery"))
        _assign_float(record, "rssi", _first_value(attributes, "rssi"))
        upload_at = _parse_epoch_millis(_first_value(attributes, "upload_time"))
        if upload_at is not None:
            record["uploaded_at"] = upload_at.isoformat()
        records.append(record)
    return tuple(records)


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
    if _has_blocking_quality_flag(payload):
        return None
    summary = f"澎湖地方水位觀測：{water_level_m:.2f} 公尺（{station_name}）"
    tags = ["official", "local_penghu", "water_level"]
    warning_level_m = optional_float(payload.get("warning_level_m"))
    if warning_level_m is not None:
        gap = warning_level_m - water_level_m
        summary = f"{summary}；距警戒 {gap:.2f} 公尺"
        if gap <= 0:
            tags.append("warning_threshold_reached")
    percent = optional_float(payload.get("water_level_percent"))
    if percent is not None:
        summary = f"{summary}；滿水比例 {percent:.1f}%"
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
        confidence=float(payload.get("confidence", 0.82)),
        status=IngestionStatus.NORMALIZED,
        attribution=optional_str(payload.get("attribution")) or PENGHU_ATTRIBUTION,
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


def _features(payload: object) -> tuple[tuple[Mapping[str, Any], Mapping[str, Any]], ...]:
    if not isinstance(payload, Mapping):
        return ()
    features = payload.get("features")
    if not isinstance(features, list):
        return ()
    records: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    for feature in features:
        if not isinstance(feature, Mapping):
            continue
        attributes = feature.get("attributes")
        geometry = feature.get("geometry")
        if isinstance(attributes, Mapping) and isinstance(geometry, Mapping):
            records.append((attributes, geometry))
    return tuple(records)


def _parse_epoch_millis(value: object) -> datetime | None:
    millis = optional_float(value)
    if millis is None:
        return None
    try:
        encoded_local_time = datetime.fromtimestamp(millis / 1000, UTC)
    except (OSError, ValueError):
        return None
    return encoded_local_time - timedelta(hours=PENGHU_ARCGIS_LOCAL_EPOCH_OFFSET_HOURS)


def _quality_flags(
    observed_at: datetime,
    *,
    fetched_at: datetime | None,
) -> dict[str, bool]:
    if fetched_at is None:
        return {"future_observation": False, "stale_observation": False}
    return {
        "future_observation": observed_at
        > fetched_at + timedelta(minutes=PENGHU_MAX_FUTURE_SKEW_MINUTES),
        "stale_observation": observed_at < fetched_at - timedelta(minutes=PENGHU_STALE_AFTER_MINUTES),
    }


def _has_blocking_quality_flag(payload: Mapping[str, Any]) -> bool:
    quality_flags = payload.get("quality_flags")
    if not isinstance(quality_flags, Mapping):
        return False
    return (
        quality_flags.get("future_observation") is True
        or quality_flags.get("stale_observation") is True
    )


def _coordinate_from_geometry(geometry: Mapping[str, Any]) -> tuple[float, float] | None:
    longitude = optional_float(geometry.get("x"))
    latitude = optional_float(geometry.get("y"))
    if longitude is None or latitude is None:
        return None
    if not (118.0 <= longitude <= 123.5 and 21.0 <= latitude <= 26.5):
        return None
    return longitude, latitude


def _location_text(row: Mapping[str, Any], station_name: str) -> str:
    return " ".join(
        part
        for part in (
            "澎湖縣",
            _town_from_county_code(_first_text(row, "CountyCode")),
            _first_text(row, "Addr"),
            station_name,
        )
        if part
    )


def _town_from_county_code(county_code: str | None) -> str | None:
    towns_by_code = {
        "10016010": "馬公市",
        "10016020": "湖西鄉",
        "10016030": "白沙鄉",
        "10016040": "西嶼鄉",
        "10016050": "望安鄉",
        "10016060": "七美鄉",
    }
    if county_code is None:
        return None
    return towns_by_code.get(county_code)


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
