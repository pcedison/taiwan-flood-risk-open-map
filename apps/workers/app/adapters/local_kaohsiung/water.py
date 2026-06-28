from __future__ import annotations

import json
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

KAOHSIUNG_LOCAL_TZ = timezone(timedelta(hours=8))
DEFAULT_KAOHSIUNG_WATER_TIMEOUT_SECONDS = 8
KAOHSIUNG_MAX_FUTURE_SKEW_MINUTES = 15
KAOHSIUNG_ATTRIBUTION = "高雄市政府水利局 / 高雄市智慧水利監測密網平台"
KAOHSIUNG_USER_AGENT = "FloodRiskTaiwan/0.1 worker-local-kaohsiung-water"
KAOHSIUNG_SEWER_WATER_LEVEL_API_URL = "https://wrbswi.kcg.gov.tw/SFC/api/sewer/rt"
KAOHSIUNG_FLOOD_SENSOR_API_URL = (
    "https://wrbswi.kcg.gov.tw/SFC/api/khfloodinfo/sta_info/lastest/wrs_flooding_sensor"
)
KAOHSIUNG_DATA_URL = "https://wrb.kcg.gov.tw/WRInfo/"

KAOHSIUNG_SEWER_WATER_LEVEL_METADATA = AdapterMetadata(
    key="local.kaohsiung.sewer_water_level",
    family=SourceFamily.OFFICIAL,
    enabled_by_default=False,
    display_name="Kaohsiung sewer water-level adapter",
    data_gov_url=KAOHSIUNG_DATA_URL,
    resource_url=KAOHSIUNG_SEWER_WATER_LEVEL_API_URL,
    update_frequency="Kaohsiung sewer API carries per-station time timestamps",
    license="Government Open Data License, version 1.0",
    limitations=(
        "Supplemental local-government sewer water-level source for Kaohsiung.",
        "The API also exposes obs_time with a GMT suffix; the local time field is "
        "used and interpreted as Asia/Taipei.",
    ),
)

KAOHSIUNG_FLOOD_SENSOR_METADATA = AdapterMetadata(
    key="local.kaohsiung.flood_sensor",
    family=SourceFamily.OFFICIAL,
    enabled_by_default=False,
    display_name="Kaohsiung flood sensor adapter",
    data_gov_url=KAOHSIUNG_DATA_URL,
    resource_url=KAOHSIUNG_FLOOD_SENSOR_API_URL,
    update_frequency="Kaohsiung flood-sensor API carries per-station time timestamps",
    license="Government Open Data License, version 1.0",
    limitations=(
        "Supplemental local flood-depth source exposed through Kaohsiung SFC.",
        "Rows without station id, observation time, depth, or WGS84 point are rejected.",
    ),
)


class KaohsiungWaterAdapterError(RuntimeError):
    """Base error for Kaohsiung local water adapters."""


class KaohsiungWaterFetchError(KaohsiungWaterAdapterError):
    """Raised when fetching Kaohsiung JSON fails."""


class KaohsiungWaterPayloadError(KaohsiungWaterAdapterError):
    """Raised when Kaohsiung JSON cannot be parsed."""


class KaohsiungSewerWaterLevelApiAdapter:
    metadata = KAOHSIUNG_SEWER_WATER_LEVEL_METADATA

    def __init__(
        self,
        *,
        api_url: str | None = None,
        timeout_seconds: int = DEFAULT_KAOHSIUNG_WATER_TIMEOUT_SECONDS,
        fetched_at: datetime | None = None,
        fetch_json: FetchJson | None = None,
        raw_snapshot_key: str | None = None,
    ) -> None:
        self._api_url = (api_url or KAOHSIUNG_SEWER_WATER_LEVEL_API_URL).strip()
        self._timeout_seconds = max(1, timeout_seconds)
        self._fetched_at = fetched_at
        self._fetch_json = fetch_json or fetch_kaohsiung_json
        self._raw_snapshot_key = raw_snapshot_key

    def fetch(self) -> tuple[RawSourceItem, ...]:
        try:
            payload = self._fetch_json(self._api_url, self._timeout_seconds)
        except KaohsiungWaterAdapterError:
            raise
        except Exception as exc:
            raise KaohsiungWaterFetchError(
                f"{self.metadata.display_name} fetcher failed: {exc}"
            ) from exc
        fetched_at = self._fetched_at or datetime.now(UTC)
        records = parse_kaohsiung_sewer_water_level_payload(
            payload,
            source_url=KAOHSIUNG_DATA_URL,
            resource_url=self._api_url,
            fetched_at=fetched_at,
        )
        return _raw_items(records, fetched_at=fetched_at, raw_snapshot_key=self._raw_snapshot_key)

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        return _normalize_water_level_record(self.metadata, raw_item)

    def run(self) -> AdapterRunResult:
        return _run(self)


class KaohsiungFloodSensorApiAdapter:
    metadata = KAOHSIUNG_FLOOD_SENSOR_METADATA

    def __init__(
        self,
        *,
        api_url: str | None = None,
        timeout_seconds: int = DEFAULT_KAOHSIUNG_WATER_TIMEOUT_SECONDS,
        fetched_at: datetime | None = None,
        fetch_json: FetchJson | None = None,
        raw_snapshot_key: str | None = None,
    ) -> None:
        self._api_url = (api_url or KAOHSIUNG_FLOOD_SENSOR_API_URL).strip()
        self._timeout_seconds = max(1, timeout_seconds)
        self._fetched_at = fetched_at
        self._fetch_json = fetch_json or fetch_kaohsiung_json
        self._raw_snapshot_key = raw_snapshot_key

    def fetch(self) -> tuple[RawSourceItem, ...]:
        try:
            payload = self._fetch_json(self._api_url, self._timeout_seconds)
        except KaohsiungWaterAdapterError:
            raise
        except Exception as exc:
            raise KaohsiungWaterFetchError(
                f"{self.metadata.display_name} fetcher failed: {exc}"
            ) from exc
        fetched_at = self._fetched_at or datetime.now(UTC)
        records = parse_kaohsiung_flood_sensor_payload(
            payload,
            source_url=KAOHSIUNG_DATA_URL,
            resource_url=self._api_url,
            fetched_at=fetched_at,
        )
        return _raw_items(records, fetched_at=fetched_at, raw_snapshot_key=self._raw_snapshot_key)

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        return _normalize_flood_sensor_record(self.metadata, raw_item)

    def run(self) -> AdapterRunResult:
        return _run(self)


def fetch_kaohsiung_json(url: str, timeout_seconds: int) -> Any:
    request = Request(
        url,
        headers={"Accept": "application/json", "User-Agent": KAOHSIUNG_USER_AGENT},
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8-sig"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise KaohsiungWaterFetchError(f"Failed to fetch Kaohsiung JSON {url}: {exc}") from exc


def parse_kaohsiung_sewer_water_level_payload(
    payload: object,
    *,
    source_url: str,
    resource_url: str | None = None,
    fetched_at: datetime | None = None,
) -> tuple[Mapping[str, Any], ...]:
    records: list[Mapping[str, Any]] = []
    for item in _payload_items(payload):
        if not isinstance(item, Mapping):
            continue
        station_id = _first_text(item, "stn_no", "st_no", "station_id")
        station_name = _first_text(item, "stn_name", "station_name")
        observed_at = _parse_local_time(_first_value(item, "time", "DATE"))
        water_level_m = optional_float(_first_value(item, "stage", "water_level_m"))
        coordinate = _coordinate(_first_value(item, "lon"), _first_value(item, "lat"))
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
            "location_text": " ".join(
                part for part in (_first_text(item, "basin"), station_name) if part
            ),
            "basin": _first_text(item, "basin"),
            "authority": _first_text(item, "source") or "高雄市政府水利局",
            "longitude": longitude,
            "latitude": latitude,
            "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
            "attribution": KAOHSIUNG_ATTRIBUTION,
            "confidence": 0.84,
            "quality_flags": _quality_flags(observed_at, fetched_at=fetched_at),
        }
        _assign_float(record, "warning_level_m", _first_value(item, "warn_level2"))
        _assign_float(record, "red_alert_level_m", _first_value(item, "warn_Level1"))
        _assign_float(record, "battery_voltage", _first_value(item, "voltage"))
        records.append(record)
    return tuple(records)


def parse_kaohsiung_flood_sensor_payload(
    payload: object,
    *,
    source_url: str,
    resource_url: str | None = None,
    fetched_at: datetime | None = None,
) -> tuple[Mapping[str, Any], ...]:
    records: list[Mapping[str, Any]] = []
    for item in _payload_items(payload):
        if not isinstance(item, Mapping):
            continue
        station_id = _first_text(item, "stn_id", "stn_no", "station_id")
        station_name = _first_text(item, "stn_name", "station_name")
        observed_at = _parse_local_time(_first_value(item, "time"))
        flood_depth_cm = optional_float(_first_value(item, "obs_value", "depth"))
        coordinate = _coordinate(_first_value(item, "lon"), _first_value(item, "lat"))
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
        records.append(
            {
                "station_id": station_id,
                "station_name": station_name,
                "observed_at": observed_at.isoformat(),
                "flood_depth_cm": flood_depth_cm,
                "source_url": source_url,
                "resource_url": resource_url,
                "location_text": " ".join(
                    part for part in (_first_text(item, "town"), station_name) if part
                ),
                "town": _first_text(item, "town"),
                "authority": _first_text(item, "source") or "高雄市政府水利局",
                "longitude": longitude,
                "latitude": latitude,
                "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
                "attribution": KAOHSIUNG_ATTRIBUTION,
                "confidence": 0.84,
                "quality_flags": _quality_flags(observed_at, fetched_at=fetched_at),
            }
        )
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
    if _has_quality_flag(payload, "future_observation"):
        return None
    summary = f"高雄地方下水道水位觀測：{water_level_m:.2f} 公尺（{station_name}）"
    tags = ["official", "local_kaohsiung", "sewer_water_level"]
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
    if _has_quality_flag(payload, "future_observation"):
        return None
    if flood_depth_cm == 0:
        summary = f"高雄地方淹水感測：無觀測到淹水（0 公分）（{station_name}）"
        depth_tags = ["dry", "no_flooding_observed"]
    elif flood_depth_cm < 3:
        summary = f"高雄地方淹水感測：低水深觀測 {_format_depth_cm(flood_depth_cm)} 公分（{station_name}）"
        depth_tags = ["below_flood_threshold", "low_depth_observation"]
    else:
        summary = f"高雄地方淹水感測：水深 {_format_depth_cm(flood_depth_cm)} 公分（{station_name}）"
        depth_tags = []
    return _evidence(
        metadata,
        raw_item,
        event_type=EventType.FLOOD_REPORT,
        station_name=station_name,
        observed_at=observed_at,
        summary=summary,
        tags=("official", "local_kaohsiung", "flood_sensor", *depth_tags),
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
        attribution=optional_str(payload.get("attribution")) or KAOHSIUNG_ATTRIBUTION,
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
        items: list[object] = []
        for value in payload.values():
            if isinstance(value, list):
                items.extend(value)
        return tuple(items)
    return ()


def _parse_local_time(value: object) -> datetime | None:
    text = optional_str(value)
    if text is None:
        return None
    parsed = parse_datetime(text)
    if parsed is None:
        try:
            parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=KAOHSIUNG_LOCAL_TZ)
    return parsed.astimezone(UTC)


def _quality_flags(
    observed_at: datetime,
    *,
    fetched_at: datetime | None,
) -> dict[str, bool]:
    if fetched_at is None:
        return {"future_observation": False}
    return {
        "future_observation": observed_at
        > fetched_at + timedelta(minutes=KAOHSIUNG_MAX_FUTURE_SKEW_MINUTES)
    }


def _has_quality_flag(payload: Mapping[str, Any], flag: str) -> bool:
    quality_flags = payload.get("quality_flags")
    return isinstance(quality_flags, Mapping) and quality_flags.get(flag) is True


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
