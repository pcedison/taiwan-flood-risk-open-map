from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from xml.etree.ElementTree import Element

from defusedxml import ElementTree as ET

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

TAOYUAN_LOCAL_TZ = timezone(timedelta(hours=8))
DEFAULT_TAOYUAN_WATER_TIMEOUT_SECONDS = 8
TAOYUAN_ATTRIBUTION = "桃園市政府水務局 / 桃園市政府資料開放平台"
TAOYUAN_USER_AGENT = "FloodRiskTaiwan/0.1 worker-local-taoyuan-water"

TAOYUAN_FLOOD_SENSOR_API_URL = "https://winfo.tycg.gov.tw/Transfer/UploadFile/WATERFLOOD.xml"
TAOYUAN_FLOOD_SENSOR_DATA_URL = (
    "https://opendata.tycg.gov.tw/datalist/414be64a-c861-4c08-a94f-96fd7884fdbb"
)
TAOYUAN_WATER_LEVEL_API_URL = "https://winfo.tycg.gov.tw/Transfer/UploadFile/WATERLEVEL.xml"
TAOYUAN_WATER_LEVEL_DATA_URL = (
    "https://opendata.tycg.gov.tw/datalist/e3b34ba5-e8ff-4b21-b7a3-4b6f3bfed650"
)
TAOYUAN_RAINFALL_API_URL = (
    "https://opendata.tycg.gov.tw/api/dataset/eabd93d1-d526-4de0-b378-b529aa61a4be/"
    "resource/6a555cf5-ccc9-4706-9cb6-62c25f23ec4e/download"
)
TAOYUAN_RAINFALL_DATA_URL = (
    "https://opendata.tycg.gov.tw/datalist/eabd93d1-d526-4de0-b378-b529aa61a4be"
)

TAOYUAN_FLOOD_SENSOR_METADATA = AdapterMetadata(
    key="local.taoyuan.flood_sensor",
    family=SourceFamily.OFFICIAL,
    enabled_by_default=False,
    display_name="Taoyuan local flood sensor adapter",
    data_gov_dataset_id="152941",
    data_gov_url=TAOYUAN_FLOOD_SENSOR_DATA_URL,
    resource_url=TAOYUAN_FLOOD_SENSOR_API_URL,
    update_frequency="Taoyuan XML feed carries per-station DATA_TIME timestamps",
    license="Government Open Data License, version 1.0",
    limitations=(
        "Supplemental local-government source for Taoyuan flood depth.",
        "Rows without WGS84 coordinates or valid observation time are rejected.",
    ),
)

TAOYUAN_WATER_LEVEL_METADATA = AdapterMetadata(
    key="local.taoyuan.water_level",
    family=SourceFamily.OFFICIAL,
    enabled_by_default=False,
    display_name="Taoyuan local water level adapter",
    data_gov_dataset_id="31299",
    data_gov_url=TAOYUAN_WATER_LEVEL_DATA_URL,
    resource_url=TAOYUAN_WATER_LEVEL_API_URL,
    update_frequency="Taoyuan XML feed carries per-station DATATIME timestamps",
    license="Government Open Data License, version 1.0",
    limitations=(
        "Supplemental local-government water-level source for Taoyuan.",
        "Yellow and red alert levels are preserved as raw metrics; warning_level_m "
        "uses the yellow threshold for realtime risk context.",
    ),
)

TAOYUAN_RAINFALL_METADATA = AdapterMetadata(
    key="local.taoyuan.rainfall",
    family=SourceFamily.OFFICIAL,
    enabled_by_default=False,
    display_name="Taoyuan local rainfall adapter",
    data_gov_dataset_id="46407",
    data_gov_url=TAOYUAN_RAINFALL_DATA_URL,
    resource_url=TAOYUAN_RAINFALL_API_URL,
    update_frequency="Taoyuan XML feed carries one root Time timestamp for station rainfall values",
    license="Government Open Data License, version 1.0",
    limitations=(
        "Supplemental local-government rainfall source for Taoyuan.",
        "The feed exposes a Rainfall value without a documented accumulation window; "
        "it is preserved as rainfall_mm instead of being relabeled as 10-minute or hourly rainfall.",
        "Rainfall sentinel -98 rows are treated as maintenance and rejected.",
    ),
)


class TaoyuanWaterAdapterError(RuntimeError):
    """Base error for Taoyuan local water adapters."""


class TaoyuanWaterFetchError(TaoyuanWaterAdapterError):
    """Raised when fetching Taoyuan XML fails."""


class TaoyuanWaterPayloadError(TaoyuanWaterAdapterError):
    """Raised when Taoyuan XML cannot be parsed."""


class TaoyuanFloodSensorApiAdapter:
    metadata = TAOYUAN_FLOOD_SENSOR_METADATA

    def __init__(
        self,
        *,
        api_url: str | None = None,
        timeout_seconds: int = DEFAULT_TAOYUAN_WATER_TIMEOUT_SECONDS,
        fetched_at: datetime | None = None,
        fetch_text: FetchText | None = None,
        raw_snapshot_key: str | None = None,
    ) -> None:
        self._api_url = (api_url or TAOYUAN_FLOOD_SENSOR_API_URL).strip()
        self._timeout_seconds = max(1, timeout_seconds)
        self._fetched_at = fetched_at
        self._fetch_text = fetch_text or fetch_taoyuan_text
        self._raw_snapshot_key = raw_snapshot_key

    def fetch(self) -> tuple[RawSourceItem, ...]:
        try:
            text = self._fetch_text(self._api_url, self._timeout_seconds)
        except TaoyuanWaterAdapterError:
            raise
        except Exception as exc:
            raise TaoyuanWaterFetchError(
                f"{self.metadata.display_name} fetcher failed: {exc}"
            ) from exc

        records = parse_taoyuan_flood_sensor_xml(
            text,
            source_url=TAOYUAN_FLOOD_SENSOR_DATA_URL,
            resource_url=self._api_url,
        )
        fetched_at = self._fetched_at or datetime.now(UTC)
        return _raw_items(records, fetched_at=fetched_at, raw_snapshot_key=self._raw_snapshot_key)

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        return _normalize_flood_sensor_record(self.metadata, raw_item)

    def run(self) -> AdapterRunResult:
        return _run(self)


class TaoyuanWaterLevelApiAdapter:
    metadata = TAOYUAN_WATER_LEVEL_METADATA

    def __init__(
        self,
        *,
        api_url: str | None = None,
        timeout_seconds: int = DEFAULT_TAOYUAN_WATER_TIMEOUT_SECONDS,
        fetched_at: datetime | None = None,
        fetch_text: FetchText | None = None,
        raw_snapshot_key: str | None = None,
    ) -> None:
        self._api_url = (api_url or TAOYUAN_WATER_LEVEL_API_URL).strip()
        self._timeout_seconds = max(1, timeout_seconds)
        self._fetched_at = fetched_at
        self._fetch_text = fetch_text or fetch_taoyuan_text
        self._raw_snapshot_key = raw_snapshot_key

    def fetch(self) -> tuple[RawSourceItem, ...]:
        try:
            text = self._fetch_text(self._api_url, self._timeout_seconds)
        except TaoyuanWaterAdapterError:
            raise
        except Exception as exc:
            raise TaoyuanWaterFetchError(
                f"{self.metadata.display_name} fetcher failed: {exc}"
            ) from exc

        records = parse_taoyuan_water_level_xml(
            text,
            source_url=TAOYUAN_WATER_LEVEL_DATA_URL,
            resource_url=self._api_url,
        )
        fetched_at = self._fetched_at or datetime.now(UTC)
        return _raw_items(records, fetched_at=fetched_at, raw_snapshot_key=self._raw_snapshot_key)

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        return _normalize_water_level_record(self.metadata, raw_item)

    def run(self) -> AdapterRunResult:
        return _run(self)


class TaoyuanRainfallApiAdapter:
    metadata = TAOYUAN_RAINFALL_METADATA

    def __init__(
        self,
        *,
        api_url: str | None = None,
        timeout_seconds: int = DEFAULT_TAOYUAN_WATER_TIMEOUT_SECONDS,
        fetched_at: datetime | None = None,
        fetch_text: FetchText | None = None,
        raw_snapshot_key: str | None = None,
    ) -> None:
        self._api_url = (api_url or TAOYUAN_RAINFALL_API_URL).strip()
        self._timeout_seconds = max(1, timeout_seconds)
        self._fetched_at = fetched_at
        self._fetch_text: FetchText = fetch_text or fetch_taoyuan_text
        self._raw_snapshot_key = raw_snapshot_key

    def fetch(self) -> tuple[RawSourceItem, ...]:
        try:
            text = self._fetch_text(self._api_url, self._timeout_seconds)
        except TaoyuanWaterAdapterError:
            raise
        except Exception as exc:
            raise TaoyuanWaterFetchError(
                f"{self.metadata.display_name} fetcher failed: {exc}"
            ) from exc

        records = parse_taoyuan_rainfall_xml(
            text,
            source_url=TAOYUAN_RAINFALL_DATA_URL,
            resource_url=self._api_url,
        )
        fetched_at = self._fetched_at or datetime.now(UTC)
        return _raw_items(records, fetched_at=fetched_at, raw_snapshot_key=self._raw_snapshot_key)

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        return _normalize_rainfall_record(self.metadata, raw_item)

    def run(self) -> AdapterRunResult:
        return _run(self)


def fetch_taoyuan_text(url: str, timeout_seconds: int) -> str:
    request = Request(url, headers={"Accept": "application/xml,text/xml,*/*", "User-Agent": TAOYUAN_USER_AGENT})
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return response.read().decode("utf-8-sig")
    except (HTTPError, URLError, TimeoutError, UnicodeDecodeError) as exc:
        raise TaoyuanWaterFetchError(f"Failed to fetch Taoyuan XML {url}: {exc}") from exc


def parse_taoyuan_flood_sensor_xml(
    text: str,
    *,
    source_url: str,
    resource_url: str | None = None,
) -> tuple[Mapping[str, Any], ...]:
    records: list[Mapping[str, Any]] = []
    for element in _xml_rows(text):
        station_id = _child_text(element, "ID")
        station_name = _child_text(element, "NAME")
        observed_at = _parse_taoyuan_datetime(_child_text(element, "DATA_TIME"))
        flood_depth_cm = optional_float(_child_text(element, "HEIGHT"))
        coordinate = _coordinate(_child_text(element, "LON"), _child_text(element, "LAT"))
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
            "location_text": _child_text(element, "ADDRESS") or station_name,
            "address": _child_text(element, "ADDRESS"),
            "longitude": longitude,
            "latitude": latitude,
            "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
            "authority": "桃園市政府水務局",
            "attribution": TAOYUAN_ATTRIBUTION,
            "confidence": 0.84,
        }
        records.append(record)
    return tuple(records)


def parse_taoyuan_water_level_xml(
    text: str,
    *,
    source_url: str,
    resource_url: str | None = None,
) -> tuple[Mapping[str, Any], ...]:
    records: list[Mapping[str, Any]] = []
    for element in _xml_rows(text):
        station_id = _child_text(element, "STATION_ID")
        station_name = _child_text(element, "STATION")
        observed_at = _parse_taoyuan_datetime(_child_text(element, "DATATIME"))
        water_level_m = optional_float(_child_text(element, "WATERHEIGHT_M"))
        coordinate = _coordinate(_child_text(element, "LON"), _child_text(element, "LAT"))
        if (
            station_id is None
            or station_name is None
            or observed_at is None
            or water_level_m is None
            or coordinate is None
        ):
            continue
        longitude, latitude = coordinate
        yellow_alert_level_m = optional_float(_child_text(element, "YellowAlertLevel"))
        red_alert_level_m = optional_float(_child_text(element, "RedAlertLevel"))
        record: dict[str, Any] = {
            "station_id": station_id,
            "station_name": station_name,
            "observed_at": observed_at.isoformat(),
            "water_level_m": water_level_m,
            "source_url": source_url,
            "resource_url": resource_url,
            "location_text": " ".join(
                part for part in (_child_text(element, "TOWN"), station_name) if part
            ),
            "town": _child_text(element, "TOWN"),
            "longitude": longitude,
            "latitude": latitude,
            "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
            "authority": "桃園市政府水務局",
            "attribution": TAOYUAN_ATTRIBUTION,
            "confidence": 0.84,
        }
        if yellow_alert_level_m is not None:
            record["yellow_alert_level_m"] = yellow_alert_level_m
            record["warning_level_m"] = yellow_alert_level_m
        if red_alert_level_m is not None:
            record["red_alert_level_m"] = red_alert_level_m
        records.append(record)
    return tuple(records)


def parse_taoyuan_rainfall_xml(
    text: str,
    *,
    source_url: str,
    resource_url: str | None = None,
) -> tuple[Mapping[str, Any], ...]:
    records: list[Mapping[str, Any]] = []
    try:
        root = ET.fromstring(text.lstrip("\ufeff").strip())
    except ET.ParseError as exc:
        raise TaoyuanWaterPayloadError(f"Taoyuan rainfall XML payload is not parseable: {exc}") from exc
    observed_at = _parse_taoyuan_datetime(_child_text(root, "Time"))
    if observed_at is None:
        return ()
    for element in root.iter():
        if element.tag.lower() != "station":
            continue
        station_id = _child_text(element, "ID")
        station_name = _child_text(element, "Name")
        rainfall_mm = optional_float(_child_text(element, "Rainfall"))
        coordinate = _coordinate(_child_text(element, "X"), _child_text(element, "Y"))
        if (
            station_id is None
            or station_name is None
            or rainfall_mm is None
            or coordinate is None
        ):
            continue
        if rainfall_mm < 0:
            continue
        district = _child_text(element, "Disrict") or _child_text(element, "District")
        county, town = _split_taoyuan_district(district)
        longitude, latitude = coordinate
        location_text = " ".join(part for part in (county, town, station_name) if part)
        records.append(
            {
                "station_id": station_id,
                "station_name": station_name,
                "observed_at": observed_at.isoformat(),
                "rainfall_mm": rainfall_mm,
                "source_url": source_url,
                "resource_url": resource_url,
                "location_text": location_text or station_name,
                "county": county,
                "town": town,
                "district": district,
                "longitude": longitude,
                "latitude": latitude,
                "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
                "authority": "桃園市政府水務局",
                "attribution": TAOYUAN_ATTRIBUTION,
                "confidence": 0.82,
            }
        )
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
        summary = f"桃園地方淹水感測：無觀測到淹水（0 公分）（{station_name}）"
        depth_tags = ["dry", "no_flooding_observed"]
    elif flood_depth_cm < 3:
        summary = (
            f"桃園地方淹水感測：低水深觀測 {_format_depth_cm(flood_depth_cm)} "
            f"公分（{station_name}）"
        )
        depth_tags = ["below_flood_threshold", "low_depth_observation"]
    else:
        summary = (
            f"桃園地方淹水感測：水深 {_format_depth_cm(flood_depth_cm)} "
            f"公分（{station_name}）"
        )
        depth_tags = []

    return _evidence(
        metadata,
        raw_item,
        event_type=EventType.FLOOD_REPORT,
        station_name=station_name,
        observed_at=observed_at,
        summary=summary,
        tags=("official", "local_taoyuan", "flood_sensor", *depth_tags),
    )


def _normalize_rainfall_record(
    metadata: AdapterMetadata,
    raw_item: RawSourceItem,
) -> NormalizedEvidence | None:
    payload = raw_item.payload
    station_name = optional_str(payload.get("station_name"))
    observed_at = parse_datetime(payload.get("observed_at"))
    rainfall_mm = optional_float(payload.get("rainfall_mm"))
    if station_name is None or observed_at is None or rainfall_mm is None:
        return None
    summary = f"桃園地方雨量觀測：{rainfall_mm:.1f} mm（{station_name}）"
    return _evidence(
        metadata,
        raw_item,
        event_type=EventType.RAINFALL,
        station_name=station_name,
        observed_at=observed_at,
        summary=summary,
        tags=("official", "local_taoyuan", "rainfall"),
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

    summary = f"桃園地方水位觀測：{water_level_m:.2f} 公尺（{station_name}）"
    warning_level_m = optional_float(payload.get("warning_level_m"))
    tags = ["official", "local_taoyuan", "water_level"]
    if warning_level_m is not None:
        gap = warning_level_m - water_level_m
        summary = f"{summary}；距黃色警戒 {gap:.2f} 公尺"
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
        attribution=optional_str(payload.get("attribution")) or TAOYUAN_ATTRIBUTION,
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
            source_id=_source_id(record),
            source_url=str(record["source_url"]),
            fetched_at=fetched_at,
            payload=record,
            raw_snapshot_key=raw_snapshot_key,
        )
        for record in records
    )


def _xml_rows(text: str) -> tuple[Element, ...]:
    try:
        root = ET.fromstring(text.lstrip("\ufeff").strip())
    except ET.ParseError as exc:
        raise TaoyuanWaterPayloadError(f"Taoyuan XML payload is not parseable: {exc}") from exc
    return tuple(element for element in root.iter() if element.tag.lower() == "data")


def _child_text(element: Element, name: str) -> str | None:
    for child in element:
        if child.tag.lower() == name.lower():
            return optional_str(child.text)
    return None


def _parse_taoyuan_datetime(value: object) -> datetime | None:
    text = optional_str(value)
    if text is None:
        return None
    parsed = _parse_chinese_ampm(text) or parse_datetime(text)
    if parsed is None:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=TAOYUAN_LOCAL_TZ)
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


def _source_id(record: Mapping[str, Any]) -> str:
    return f"{record['station_id']}:{record['observed_at']}"


def _split_taoyuan_district(value: str | None) -> tuple[str | None, str | None]:
    text = optional_str(value)
    if text is None:
        return None, None
    if text.startswith("桃園市") and len(text) > len("桃園市"):
        return "桃園市", text[len("桃園市") :]
    return None, text


def _format_depth_cm(depth_cm: float) -> str:
    if depth_cm == 0:
        return "0"
    formatted = format(Decimal(str(depth_cm)).normalize(), "f")
    return formatted.rstrip("0").rstrip(".")
