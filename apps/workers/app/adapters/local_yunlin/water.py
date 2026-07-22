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

DEFAULT_YUNLIN_WATER_TIMEOUT_SECONDS = 8
YUNLIN_MAX_FUTURE_SKEW_MINUTES = 15
YUNLIN_STALE_AFTER_MINUTES = 180
YUNLIN_ATTRIBUTION = "雲林縣政府 / 雲林水情災情監控系統"
YUNLIN_USER_AGENT = "FloodRiskTaiwan/0.1 worker-local-yunlin-water"
YUNLIN_DATA_URL = "https://yliflood.yunlin.gov.tw/ifloodboard/"
YUNLIN_STATIONS_API_URL = (
    "https://yliflood.yunlin.gov.tw/api/v1/IfloodStation/StationTypes/Areas/Stations"
    "?context=5"
)

YUNLIN_WATER_LEVEL_METADATA = AdapterMetadata(
    key="local.yunlin.water_level",
    family=SourceFamily.OFFICIAL,
    enabled_by_default=False,
    display_name="Yunlin local water-level adapter",
    data_gov_url=YUNLIN_DATA_URL,
    resource_url=YUNLIN_STATIONS_API_URL,
    update_frequency="Yunlin iflood API carries per-station latestUpdateTime timestamps",
    license="Government Open Data License, version 1.0",
    limitations=(
        "Supplemental local-government water-level source for Yunlin County.",
        "The same station API includes flood sensors, but the verified public list "
        "does not expose flood depth; this adapter only normalizes water-level rows "
        "with levelHeight.",
    ),
)


class YunlinWaterAdapterError(RuntimeError):
    """Base error for Yunlin local water adapters."""


class YunlinWaterFetchError(YunlinWaterAdapterError):
    """Raised when fetching Yunlin JSON fails."""


class YunlinWaterPayloadError(YunlinWaterAdapterError):
    """Raised when Yunlin JSON cannot be parsed."""


class YunlinWaterLevelApiAdapter:
    metadata = YUNLIN_WATER_LEVEL_METADATA

    def __init__(
        self,
        *,
        api_url: str | None = None,
        timeout_seconds: int = DEFAULT_YUNLIN_WATER_TIMEOUT_SECONDS,
        fetched_at: datetime | None = None,
        fetch_json: FetchJson | None = None,
        raw_snapshot_key: str | None = None,
    ) -> None:
        self._api_url = (api_url or YUNLIN_STATIONS_API_URL).strip()
        self._timeout_seconds = max(1, timeout_seconds)
        self._fetched_at = fetched_at
        self._fetch_json = fetch_yunlin_json if fetch_json is None else fetch_json
        self._raw_snapshot_key = raw_snapshot_key

    def fetch(self) -> tuple[RawSourceItem, ...]:
        try:
            payload = self._fetch_json(self._api_url, self._timeout_seconds)
        except YunlinWaterAdapterError:
            raise
        except Exception as exc:
            raise YunlinWaterFetchError(
                f"{self.metadata.display_name} fetcher failed: {exc}"
            ) from exc
        fetched_at = self._fetched_at or datetime.now(UTC)
        records = parse_yunlin_water_level_payload(
            payload,
            source_url=YUNLIN_DATA_URL,
            resource_url=self._api_url,
            fetched_at=fetched_at,
        )
        return _raw_items(records, fetched_at=fetched_at, raw_snapshot_key=self._raw_snapshot_key)

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        return _normalize_water_level_record(self.metadata, raw_item)

    def run(self) -> AdapterRunResult:
        return _run(self)


def fetch_yunlin_json(url: str, timeout_seconds: int) -> Any:
    request = Request(
        url,
        headers={"Accept": "application/json", "User-Agent": YUNLIN_USER_AGENT},
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8-sig"))
    except (HTTPError, URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise YunlinWaterFetchError(f"Failed to fetch Yunlin JSON {url}: {exc}") from exc


def parse_yunlin_water_level_payload(
    payload: object,
    *,
    source_url: str,
    resource_url: str | None = None,
    fetched_at: datetime | None = None,
) -> tuple[Mapping[str, Any], ...]:
    records: list[Mapping[str, Any]] = []
    for item in _station_items(payload):
        if not isinstance(item, Mapping):
            continue
        station_type = _first_text(item, "stationType")
        if station_type not in {"水位", "淹水感測"}:
            continue
        station_id = _first_text(item, "id", "stationId", "stationNo")
        station_name = _first_text(item, "stationName", "displayName")
        observed_at = _parse_observed_at(_first_value(item, "latestUpdateTime"))
        coordinate = _coordinate(_first_value(item, "longitude"), _first_value(item, "latitude"))
        if (
            station_id is None
            or station_name is None
            or observed_at is None
            or coordinate is None
        ):
            continue
        longitude, latitude = coordinate
        properties = _json_property(item.get("jsonProperty"))
        record: dict[str, Any] = {
            "station_id": station_id,
            "station_name": station_name,
            "observed_at": observed_at.isoformat(),
            "station_type": station_type,
            "source_url": source_url,
            "resource_url": resource_url,
            "location_text": _location_text(item, station_name),
            "town": _first_text(item, "administrativeArea"),
            "display_name": _first_text(item, "displayName"),
            "alarm_state": _first_text(item, "alarmState"),
            "authority": _first_text(item, "owner") or "雲林縣政府",
            "longitude": longitude,
            "latitude": latitude,
            "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
            "attribution": YUNLIN_ATTRIBUTION,
            "confidence": 0.84,
            "quality_flags": _quality_flags(observed_at, fetched_at=fetched_at),
        }
        if station_type == "淹水感測":
            record["status_only"] = True
            record["confidence"] = 0.32
            record["source_weight"] = 0.05
            records.append(record)
            continue

        water_level_m = optional_float(_first_value(item, "levelHeight"))
        if water_level_m is None:
            continue
        record["water_level_m"] = water_level_m
        thresholds = item.get("alertThreshold")
        if isinstance(thresholds, Mapping):
            _assign_float(record, "warning_level_m", thresholds.get("level2"))
            _assign_float(record, "red_alert_level_m", thresholds.get("level1"))
            _assign_float(record, "low_alert_level_m", thresholds.get("level3"))
        _assign_float(record, "elevation_m", _first_value(item, "elevation"))
        _assign_float(record, "elevation_m", properties.get("elevation"))
        observation_frequency = optional_str(properties.get("observationFrequency"))
        drainage = optional_str(properties.get("drainage"))
        observation_principle = optional_str(properties.get("observationPrinciple"))
        if observation_frequency is not None:
            record["observation_frequency"] = observation_frequency
        if drainage is not None:
            record["drainage"] = drainage
        if observation_principle is not None:
            record["observation_principle"] = observation_principle
        records.append(record)
    return tuple(records)


def _normalize_water_level_record(
    metadata: AdapterMetadata,
    raw_item: RawSourceItem,
) -> NormalizedEvidence | None:
    payload = raw_item.payload
    if payload.get("status_only") is True:
        return _normalize_status_only_record(metadata, raw_item)

    station_name = optional_str(payload.get("station_name"))
    observed_at = parse_datetime(payload.get("observed_at"))
    water_level_m = optional_float(payload.get("water_level_m"))
    if station_name is None or observed_at is None or water_level_m is None:
        return None
    if _has_blocking_quality_flag(payload):
        return None
    summary = f"雲林地方水位觀測：{water_level_m:.2f} 公尺（{station_name}）"
    tags = ["official", "local_yunlin", "water_level"]
    warning_level_m = optional_float(payload.get("warning_level_m"))
    if warning_level_m is not None:
        gap = warning_level_m - water_level_m
        summary = f"{summary}；距警戒 {gap:.2f} 公尺"
        if gap <= 0:
            tags.append("warning_threshold_reached")
    alarm_state = optional_str(payload.get("alarm_state"))
    if alarm_state and alarm_state != "正常":
        tags.append("local_alarm_state")
    return _evidence(
        metadata,
        raw_item,
        event_type=EventType.WATER_LEVEL,
        station_name=station_name,
        observed_at=observed_at,
        summary=summary,
        tags=tuple(tags),
    )


def _normalize_status_only_record(
    metadata: AdapterMetadata,
    raw_item: RawSourceItem,
) -> NormalizedEvidence | None:
    payload = raw_item.payload
    station_name = optional_str(payload.get("station_name"))
    observed_at = parse_datetime(payload.get("observed_at"))
    alarm_state = optional_str(payload.get("alarm_state"))
    if station_name is None or observed_at is None or alarm_state is None:
        return None
    if _has_blocking_quality_flag(payload):
        return None

    tags = ["official", "local_yunlin", "status_only", "flood_sensor_status", "not_flood_depth"]
    if alarm_state != "正常":
        tags.append("local_alarm_state")
    summary = f"雲林 iflood 淹水感測狀態：{alarm_state}（{station_name}）"
    return _evidence(
        metadata,
        raw_item,
        event_type=EventType.STATUS_ONLY,
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
        attribution=optional_str(payload.get("attribution")) or YUNLIN_ATTRIBUTION,
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


def _station_items(payload: object) -> tuple[object, ...]:
    if isinstance(payload, list):
        return tuple(payload)
    if not isinstance(payload, Mapping):
        return ()
    result = payload.get("result")
    if isinstance(result, Mapping) and isinstance(result.get("items"), list):
        return tuple(result["items"])
    if isinstance(payload.get("items"), list):
        return tuple(payload["items"])
    return ()


def _parse_observed_at(value: object) -> datetime | None:
    parsed = parse_datetime(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _json_property(value: object) -> Mapping[str, Any]:
    text = optional_str(value)
    if text is None:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, Mapping) else {}


def _quality_flags(
    observed_at: datetime,
    *,
    fetched_at: datetime | None,
) -> dict[str, bool]:
    if fetched_at is None:
        return {"future_observation": False, "stale_observation": False}
    return {
        "future_observation": observed_at
        > fetched_at + timedelta(minutes=YUNLIN_MAX_FUTURE_SKEW_MINUTES),
        "stale_observation": observed_at
        < fetched_at - timedelta(minutes=YUNLIN_STALE_AFTER_MINUTES),
    }


def _has_blocking_quality_flag(payload: Mapping[str, Any]) -> bool:
    quality_flags = payload.get("quality_flags")
    if not isinstance(quality_flags, Mapping):
        return False
    return (
        quality_flags.get("future_observation") is True
        or quality_flags.get("stale_observation") is True
    )


def _coordinate(lon: object, lat: object) -> tuple[float, float] | None:
    longitude = optional_float(lon)
    latitude = optional_float(lat)
    if longitude is None or latitude is None:
        return None
    if not (118.0 <= longitude <= 123.5 and 21.0 <= latitude <= 26.5):
        return None
    return longitude, latitude


def _location_text(row: Mapping[str, Any], station_name: str) -> str:
    return " ".join(
        part for part in (_first_text(row, "administrativeArea"), station_name) if part
    )


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
