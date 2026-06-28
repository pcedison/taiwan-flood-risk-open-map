from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.adapters._helpers import optional_float, optional_str, parse_datetime
from app.adapters._helpers import stable_evidence_id
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

TAICHUNG_LOCAL_TZ = timezone(timedelta(hours=8))
DEFAULT_TAICHUNG_WATER_TIMEOUT_SECONDS = 8
DEFAULT_TAICHUNG_MAX_OBSERVATION_AGE_MINUTES = 180
TAICHUNG_ATTRIBUTION = "臺中市政府水利局 / 臺中市資料開放平臺"
TAICHUNG_USER_AGENT = "FloodRiskTaiwan/0.1 worker-local-taichung-water"
TAICHUNG_WATER_LEVEL_API_URL = (
    "https://wrbeocin.taichung.gov.tw/TCSAFE/UploadFile/WATERLEVEL/WATERLEVEL_NEW.JSON"
)
TAICHUNG_WATER_LEVEL_DATA_URL = "https://opendata.taichung.gov.tw/"

TAICHUNG_WATER_LEVEL_METADATA = AdapterMetadata(
    key="local.taichung.water_level",
    family=SourceFamily.OFFICIAL,
    enabled_by_default=False,
    display_name="Taichung local water level adapter",
    data_gov_url=TAICHUNG_WATER_LEVEL_DATA_URL,
    resource_url=TAICHUNG_WATER_LEVEL_API_URL,
    update_frequency="Taichung water-level JSON carries per-station 日期時間 timestamps",
    license="Government Open Data License, version 1.0",
    limitations=(
        "Supplemental local-government water-level source for Taichung.",
        "Station identifiers are not provided in the live JSON; station name is "
        "used as the stable station id until an official id field is available.",
    ),
)


class TaichungWaterAdapterError(RuntimeError):
    """Base error for Taichung water adapter failures."""


class TaichungWaterFetchError(TaichungWaterAdapterError):
    """Raised when fetching Taichung JSON fails."""


class TaichungWaterPayloadError(TaichungWaterAdapterError):
    """Raised when Taichung JSON cannot be parsed."""


class TaichungWaterLevelApiAdapter:
    metadata = TAICHUNG_WATER_LEVEL_METADATA

    def __init__(
        self,
        *,
        api_url: str | None = None,
        timeout_seconds: int = DEFAULT_TAICHUNG_WATER_TIMEOUT_SECONDS,
        fetched_at: datetime | None = None,
        fetch_json: FetchJson | None = None,
        raw_snapshot_key: str | None = None,
        stale_after_minutes: int = DEFAULT_TAICHUNG_MAX_OBSERVATION_AGE_MINUTES,
    ) -> None:
        self._api_url = (api_url or TAICHUNG_WATER_LEVEL_API_URL).strip()
        self._timeout_seconds = max(1, timeout_seconds)
        self._fetched_at = fetched_at
        self._fetch_json = fetch_json or fetch_taichung_json
        self._raw_snapshot_key = raw_snapshot_key
        self._stale_after_minutes = stale_after_minutes

    def fetch(self) -> tuple[RawSourceItem, ...]:
        try:
            payload = self._fetch_json(self._api_url, self._timeout_seconds)
        except TaichungWaterAdapterError:
            raise
        except Exception as exc:
            raise TaichungWaterFetchError(
                f"{self.metadata.display_name} fetcher failed: {exc}"
            ) from exc
        fetched_at = self._fetched_at or datetime.now(UTC)
        records = parse_taichung_water_level_payload(
            payload,
            source_url=TAICHUNG_WATER_LEVEL_DATA_URL,
            resource_url=self._api_url,
            fetched_at=fetched_at,
            stale_after_minutes=self._stale_after_minutes,
        )
        return _raw_items(records, fetched_at=fetched_at, raw_snapshot_key=self._raw_snapshot_key)

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        return _normalize_water_level_record(self.metadata, raw_item)

    def run(self) -> AdapterRunResult:
        return _run(self)


def fetch_taichung_json(url: str, timeout_seconds: int) -> Any:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": TAICHUNG_USER_AGENT})
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8-sig"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise TaichungWaterFetchError(f"Failed to fetch Taichung JSON {url}: {exc}") from exc


def parse_taichung_water_level_payload(
    payload: object,
    *,
    source_url: str,
    fetched_at: datetime,
    resource_url: str | None = None,
    stale_after_minutes: int = DEFAULT_TAICHUNG_MAX_OBSERVATION_AGE_MINUTES,
) -> tuple[Mapping[str, Any], ...]:
    records: list[Mapping[str, Any]] = []
    for item in _payload_items(payload):
        if not isinstance(item, Mapping):
            continue
        record = _parse_record(
            item,
            source_url=source_url,
            resource_url=resource_url,
            fetched_at=fetched_at,
            stale_after_minutes=stale_after_minutes,
        )
        if record is not None:
            records.append(record)
    return tuple(records)


def _parse_record(
    item: Mapping[str, Any],
    *,
    source_url: str,
    resource_url: str | None,
    fetched_at: datetime,
    stale_after_minutes: int,
) -> Mapping[str, Any] | None:
    station_name = _first_text(item, "水位站名稱", "站名")
    observed_at = _parse_taichung_time(_first_value(item, "日期時間", "資料時間"))
    water_level_m = optional_float(_first_value(item, "水位高m"))
    coordinate = _coordinate(_first_value(item, "經度"), _first_value(item, "緯度"))
    if station_name is None or observed_at is None or water_level_m is None or coordinate is None:
        return None
    longitude, latitude = coordinate
    yellow_alert_level_m = optional_float(_first_value(item, "黃色警戒值m"))
    red_alert_level_m = optional_float(_first_value(item, "紅色警戒值m"))
    quality_flags = {
        "stale_observation": observed_at < fetched_at - timedelta(minutes=stale_after_minutes)
    }
    record: dict[str, Any] = {
        "station_id": station_name,
        "station_name": station_name,
        "observed_at": observed_at.isoformat(),
        "water_level_m": water_level_m,
        "source_url": source_url,
        "resource_url": resource_url,
        "location_text": " ".join(
            part for part in (_first_text(item, "行政區"), station_name) if part
        ),
        "district": _first_text(item, "行政區"),
        "status_text": _first_text(item, "狀態"),
        "longitude": longitude,
        "latitude": latitude,
        "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
        "authority": "臺中市政府水利局",
        "attribution": TAICHUNG_ATTRIBUTION,
        "confidence": 0.84 if not quality_flags["stale_observation"] else 0.55,
        "quality_flags": quality_flags,
    }
    if yellow_alert_level_m is not None:
        record["yellow_alert_level_m"] = yellow_alert_level_m
        record["warning_level_m"] = yellow_alert_level_m
    if red_alert_level_m is not None:
        record["red_alert_level_m"] = red_alert_level_m
    _assign_float(record, "revetment_height_m", _first_value(item, "護岸高m"))
    _assign_text(record, "image_url", _first_text(item, "影像網址"))
    return record


def _normalize_water_level_record(
    metadata: AdapterMetadata,
    raw_item: RawSourceItem,
) -> NormalizedEvidence | None:
    payload = raw_item.payload
    quality_flags = payload.get("quality_flags")
    if isinstance(quality_flags, Mapping) and quality_flags.get("stale_observation") is True:
        return None
    station_name = optional_str(payload.get("station_name"))
    observed_at = parse_datetime(payload.get("observed_at"))
    water_level_m = optional_float(payload.get("water_level_m"))
    if station_name is None or observed_at is None or water_level_m is None:
        return None
    summary = f"臺中地方水位觀測：{water_level_m:.2f} 公尺（{station_name}）"
    tags = ["official", "local_taichung", "water_level"]
    warning_level_m = optional_float(payload.get("warning_level_m"))
    if warning_level_m is not None:
        gap = warning_level_m - water_level_m
        summary = f"{summary}；距黃色警戒 {gap:.2f} 公尺"
        if gap <= 0:
            tags.append("warning_threshold_reached")
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
        location_text=optional_str(payload.get("location_text")) or station_name,
        confidence=float(payload.get("confidence", 0.84)),
        status=IngestionStatus.NORMALIZED,
        attribution=optional_str(payload.get("attribution")) or TAICHUNG_ATTRIBUTION,
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


def _payload_items(payload: object) -> Iterable[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, Mapping):
        root = payload.get("ROOT") or payload.get("root")
        if isinstance(root, Mapping):
            data = root.get("DATA") or root.get("data")
            if isinstance(data, list):
                return data
        for key in ("DATA", "data", "records", "value"):
            items = payload.get(key)
            if isinstance(items, list):
                return items
    raise TaichungWaterPayloadError("Taichung water-level payload is missing DATA list")


def _parse_taichung_time(value: object) -> datetime | None:
    text = optional_str(value)
    if text is None:
        return None
    parsed = _parse_chinese_ampm(text) or parse_datetime(text)
    if parsed is None:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=TAICHUNG_LOCAL_TZ)
    return parsed.astimezone(UTC)


def _parse_chinese_ampm(text: str) -> datetime | None:
    for marker, is_pm in (("上午", False), ("下午", True)):
        if marker not in text:
            continue
        date_part, time_part = (part.strip() for part in text.split(marker, 1))
        try:
            year, month, day = (int(part) for part in date_part.split("/"))
            hour, minute, second = (int(part) for part in time_part.split(":"))
        except ValueError:
            return None
        if is_pm and hour != 12:
            hour += 12
        if not is_pm and hour == 12:
            hour = 0
        return datetime(year, month, day, hour, minute, second)
    return None


def _coordinate(lon: object, lat: object) -> tuple[float, float] | None:
    longitude = optional_float(lon)
    latitude = optional_float(lat)
    if longitude is None or latitude is None:
        return None
    if not (118.0 <= longitude <= 123.5 and 21.0 <= latitude <= 26.5):
        return None
    return longitude, latitude


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


def _assign_float(record: dict[str, Any], key: str, value: object) -> None:
    parsed = optional_float(value)
    if parsed is not None:
        record[key] = parsed


def _assign_text(record: dict[str, Any], key: str, value: str | None) -> None:
    if value is not None:
        record[key] = value
