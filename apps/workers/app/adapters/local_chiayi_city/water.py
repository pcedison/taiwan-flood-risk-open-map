from __future__ import annotations

import csv
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime, timedelta, timezone
from io import StringIO
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


FetchText = Callable[[str, int], str]

CHIAYI_CITY_LOCAL_TZ = timezone(timedelta(hours=8))
DEFAULT_CHIAYI_CITY_WATER_TIMEOUT_SECONDS = 8
CHIAYI_CITY_ATTRIBUTION = "嘉義市政府 / 嘉義市政府資料開放平台"
CHIAYI_CITY_USER_AGENT = "FloodRiskTaiwan/0.1 worker-local-chiayi-city-water"
CHIAYI_CITY_WATER_LEVEL_API_URL = (
    "https://data.chiayi.gov.tw/opendata/api/getResource?"
    "oid=df063695-0076-4dd6-9237-39c5f8ae6b4a&rid=d4c7da5c-b08f-4fd1-97c0-913c949c4613"
)
CHIAYI_CITY_WATER_LEVEL_DATA_URL = "https://data.gov.tw/dataset/52584"
CHIAYI_CITY_RAINFALL_API_URL = (
    "https://data.chiayi.gov.tw/opendata/api/getResource?"
    "oid=0c766c28-c16e-4eaa-8520-f7ffeee3776b&rid=5ad1cdc5-6a8a-48d4-b6b4-7edb9b384e1a"
)
CHIAYI_CITY_RAINFALL_DATA_URL = "https://data.gov.tw/dataset/52585"

CHIAYI_CITY_WATER_LEVEL_METADATA = AdapterMetadata(
    key="local.chiayi_city.water_level",
    family=SourceFamily.OFFICIAL,
    enabled_by_default=False,
    display_name="Chiayi City local water level adapter",
    data_gov_dataset_id="52584",
    data_gov_url=CHIAYI_CITY_WATER_LEVEL_DATA_URL,
    resource_url=CHIAYI_CITY_WATER_LEVEL_API_URL,
    update_frequency="Chiayi City CSV feed carries per-station 資料時間 timestamps",
    license="Government Open Data License, version 1.0",
    limitations=(
        "Supplemental local-government water-level source for Chiayi City.",
        "Warning level uses 二級警戒 as the realtime warning threshold and keeps "
        "一級警戒 as the red alert threshold.",
    ),
)

CHIAYI_CITY_RAINFALL_METADATA = AdapterMetadata(
    key="local.chiayi_city.rainfall",
    family=SourceFamily.OFFICIAL,
    enabled_by_default=False,
    display_name="Chiayi City local rainfall adapter",
    data_gov_dataset_id="52585",
    data_gov_url=CHIAYI_CITY_RAINFALL_DATA_URL,
    resource_url=CHIAYI_CITY_RAINFALL_API_URL,
    update_frequency="Chiayi City CSV feed carries per-station 資料時間 timestamps",
    license="Government Open Data License, version 1.0",
    limitations=(
        "Supplemental local-government rainfall source for Chiayi City.",
        "The live CSV can publish duplicate 12-hour header names; the second duplicate "
        "is preserved as 24-hour rainfall when an explicit 24-hour column is absent.",
    ),
)


class ChiayiCityWaterAdapterError(RuntimeError):
    """Base error for Chiayi City water adapter failures."""


class ChiayiCityWaterFetchError(ChiayiCityWaterAdapterError):
    """Raised when fetching Chiayi City CSV fails."""


class ChiayiCityWaterPayloadError(ChiayiCityWaterAdapterError):
    """Raised when Chiayi City CSV cannot be parsed."""


class ChiayiCityWaterLevelApiAdapter:
    metadata = CHIAYI_CITY_WATER_LEVEL_METADATA

    def __init__(
        self,
        *,
        api_url: str | None = None,
        timeout_seconds: int = DEFAULT_CHIAYI_CITY_WATER_TIMEOUT_SECONDS,
        fetched_at: datetime | None = None,
        fetch_text: FetchText | None = None,
        raw_snapshot_key: str | None = None,
    ) -> None:
        self._api_url = (api_url or CHIAYI_CITY_WATER_LEVEL_API_URL).strip()
        self._timeout_seconds = max(1, timeout_seconds)
        self._fetched_at = fetched_at
        self._fetch_text = fetch_text or fetch_chiayi_city_text
        self._raw_snapshot_key = raw_snapshot_key

    def fetch(self) -> tuple[RawSourceItem, ...]:
        try:
            text = self._fetch_text(self._api_url, self._timeout_seconds)
        except ChiayiCityWaterAdapterError:
            raise
        except Exception as exc:
            raise ChiayiCityWaterFetchError(
                f"{self.metadata.display_name} fetcher failed: {exc}"
            ) from exc
        records = parse_chiayi_city_water_level_csv(
            text,
            source_url=CHIAYI_CITY_WATER_LEVEL_DATA_URL,
            resource_url=self._api_url,
        )
        fetched_at = self._fetched_at or datetime.now(UTC)
        return _raw_items(records, fetched_at=fetched_at, raw_snapshot_key=self._raw_snapshot_key)

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        return _normalize_water_level_record(self.metadata, raw_item)

    def run(self) -> AdapterRunResult:
        return _run(self)


class ChiayiCityRainfallApiAdapter:
    metadata = CHIAYI_CITY_RAINFALL_METADATA

    def __init__(
        self,
        *,
        api_url: str | None = None,
        timeout_seconds: int = DEFAULT_CHIAYI_CITY_WATER_TIMEOUT_SECONDS,
        fetched_at: datetime | None = None,
        fetch_text: FetchText | None = None,
        raw_snapshot_key: str | None = None,
    ) -> None:
        self._api_url = (api_url or CHIAYI_CITY_RAINFALL_API_URL).strip()
        self._timeout_seconds = max(1, timeout_seconds)
        self._fetched_at = fetched_at
        self._fetch_text = fetch_text or fetch_chiayi_city_text
        self._raw_snapshot_key = raw_snapshot_key

    def fetch(self) -> tuple[RawSourceItem, ...]:
        try:
            text = self._fetch_text(self._api_url, self._timeout_seconds)
        except ChiayiCityWaterAdapterError:
            raise
        except Exception as exc:
            raise ChiayiCityWaterFetchError(
                f"{self.metadata.display_name} fetcher failed: {exc}"
            ) from exc
        records = parse_chiayi_city_rainfall_csv(
            text,
            source_url=CHIAYI_CITY_RAINFALL_DATA_URL,
            resource_url=self._api_url,
        )
        fetched_at = self._fetched_at or datetime.now(UTC)
        return _raw_items(records, fetched_at=fetched_at, raw_snapshot_key=self._raw_snapshot_key)

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        return _normalize_rainfall_record(self.metadata, raw_item)

    def run(self) -> AdapterRunResult:
        return _run(self)


def fetch_chiayi_city_text(url: str, timeout_seconds: int) -> str:
    request = Request(url, headers={"Accept": "text/csv,*/*", "User-Agent": CHIAYI_CITY_USER_AGENT})
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return response.read().decode("utf-8-sig")
    except (HTTPError, URLError, TimeoutError, UnicodeDecodeError) as exc:
        raise ChiayiCityWaterFetchError(f"Failed to fetch Chiayi City CSV {url}: {exc}") from exc


def parse_chiayi_city_water_level_csv(
    text: str,
    *,
    source_url: str,
    resource_url: str | None = None,
) -> tuple[Mapping[str, Any], ...]:
    records: list[Mapping[str, Any]] = []
    reader = csv.DictReader(StringIO(text.lstrip("\ufeff")))
    for row in reader:
        station_id = _first_text(row, "代號")
        station_name = _first_text(row, "站名")
        observed_at = _parse_local_time(_first_text(row, "資料時間"))
        water_level_m = optional_float(_first_value(row, "水位-m"))
        coordinate = _coordinate(_first_value(row, "經度"), _first_value(row, "緯度"))
        if (
            station_id is None
            or station_name is None
            or observed_at is None
            or water_level_m is None
            or coordinate is None
        ):
            continue
        longitude, latitude = coordinate
        red_alert_level_m = optional_float(_first_value(row, "一級警戒"))
        yellow_alert_level_m = optional_float(_first_value(row, "二級警戒"))
        record: dict[str, Any] = {
            "station_id": station_id,
            "station_name": station_name,
            "observed_at": observed_at.isoformat(),
            "water_level_m": water_level_m,
            "source_url": source_url,
            "resource_url": resource_url,
            "location_text": station_name,
            "longitude": longitude,
            "latitude": latitude,
            "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
            "authority": "嘉義市政府",
            "attribution": CHIAYI_CITY_ATTRIBUTION,
            "confidence": 0.84,
        }
        if yellow_alert_level_m is not None:
            record["yellow_alert_level_m"] = yellow_alert_level_m
            record["warning_level_m"] = yellow_alert_level_m
        if red_alert_level_m is not None:
            record["red_alert_level_m"] = red_alert_level_m
        _assign_float(record, "battery_voltage", _first_value(row, "電池電壓"))
        records.append(record)
    return tuple(records)


def parse_chiayi_city_rainfall_csv(
    text: str,
    *,
    source_url: str,
    resource_url: str | None = None,
) -> tuple[Mapping[str, Any], ...]:
    records: list[Mapping[str, Any]] = []
    reader = csv.reader(StringIO(text.lstrip("\ufeff")))
    try:
        headers = next(reader)
    except StopIteration:
        return ()
    for values in reader:
        row = _row_mapping(headers, values)
        station_id = _first_text(row, "代號")
        station_name = _first_text(row, "站名")
        observed_at = _parse_local_time(_first_text(row, "資料時間"))
        coordinate = _coordinate(_first_value(row, "經度"), _first_value(row, "緯度"))
        rainfall = {
            "rainfall_mm_10m": _positive_or_zero(_first_value(row, "10分鐘雨量-mm")),
            "rainfall_mm_1h": _positive_or_zero(_first_value(row, "1小時雨量-mm")),
            "rainfall_mm_3h": _positive_or_zero(_first_value(row, "3小時雨量-mm")),
            "rainfall_mm_6h": _positive_or_zero(_first_value(row, "6小時雨量-mm")),
            "rainfall_mm_12h": _positive_or_zero(_first_value(row, "12小時雨量-mm")),
            "rainfall_mm_24h": _positive_or_zero(_first_value(row, "24小時雨量-mm")),
        }
        if station_id is None or station_name is None or observed_at is None or coordinate is None:
            continue
        if all(value is None for value in rainfall.values()):
            continue
        longitude, latitude = coordinate
        record: dict[str, Any] = {
            "station_id": station_id,
            "station_name": station_name,
            "observed_at": observed_at.isoformat(),
            "source_url": source_url,
            "resource_url": resource_url,
            "location_text": f"嘉義市 {station_name}",
            "county": "嘉義市",
            "longitude": longitude,
            "latitude": latitude,
            "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
            "authority": "嘉義市政府",
            "attribution": CHIAYI_CITY_ATTRIBUTION,
            "confidence": 0.84,
        }
        for key, value in rainfall.items():
            if value is not None:
                record[key] = value
        status_text = _first_text(row, "狀態")
        if status_text is not None:
            record["status_text"] = status_text
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
    summary = f"嘉義市地方水位觀測：{water_level_m:.2f} 公尺（{station_name}）"
    tags = ["official", "local_chiayi_city", "water_level"]
    warning_level_m = optional_float(payload.get("warning_level_m"))
    if warning_level_m is not None:
        gap = warning_level_m - water_level_m
        summary = f"{summary}；距二級警戒 {gap:.2f} 公尺"
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
        attribution=optional_str(payload.get("attribution")) or CHIAYI_CITY_ATTRIBUTION,
        tags=tuple(dict.fromkeys(tags)),
    )


def _normalize_rainfall_record(
    metadata: AdapterMetadata,
    raw_item: RawSourceItem,
) -> NormalizedEvidence | None:
    payload = raw_item.payload
    station_name = optional_str(payload.get("station_name"))
    observed_at = parse_datetime(payload.get("observed_at"))
    if station_name is None or observed_at is None:
        return None
    rainfall_1h = optional_float(payload.get("rainfall_mm_1h"))
    rainfall_10m = optional_float(payload.get("rainfall_mm_10m"))
    rainfall_24h = optional_float(payload.get("rainfall_mm_24h"))
    if rainfall_1h is not None:
        summary = f"嘉義市地方雨量觀測：{rainfall_1h:.1f} mm in 1 hour（{station_name}）"
    elif rainfall_10m is not None:
        summary = f"嘉義市地方雨量觀測：{rainfall_10m:.1f} mm in 10 minutes（{station_name}）"
    else:
        summary = f"嘉義市地方雨量觀測站上線（{station_name}）"
    if rainfall_24h is not None:
        summary = f"{summary}；{rainfall_24h:.1f} mm in 24 hours"
    return NormalizedEvidence(
        evidence_id=stable_evidence_id(metadata.key, raw_item.source_id),
        adapter_key=metadata.key,
        source_family=metadata.family,
        event_type=EventType.RAINFALL,
        source_id=raw_item.source_id,
        source_url=raw_item.source_url,
        source_title=f"{metadata.display_name}：{station_name}",
        source_timestamp=observed_at,
        fetched_at=raw_item.fetched_at,
        summary=summary,
        location_text=optional_str(payload.get("location_text")) or station_name,
        confidence=float(payload.get("confidence", 0.84)),
        status=IngestionStatus.NORMALIZED,
        attribution=optional_str(payload.get("attribution")) or CHIAYI_CITY_ATTRIBUTION,
        tags=("official", "local_chiayi_city", "rainfall"),
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


def _parse_local_time(value: object) -> datetime | None:
    parsed = parse_datetime(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=CHIAYI_CITY_LOCAL_TZ)
    return parsed.astimezone(UTC)


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


def _positive_or_zero(value: object) -> float | None:
    parsed = optional_float(value)
    if parsed is None or parsed < 0:
        return None
    return parsed


def _row_mapping(headers: list[str], values: list[str]) -> dict[str, str]:
    row: dict[str, str] = {}
    for index, header in enumerate(headers):
        value = values[index] if index < len(values) else ""
        if header == "12小時雨量-mm" and header in row and "24小時雨量-mm" not in row:
            row["24小時雨量-mm"] = value
            continue
        if header not in row:
            row[header] = value
    return row
