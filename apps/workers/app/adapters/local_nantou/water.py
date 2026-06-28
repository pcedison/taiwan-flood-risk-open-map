from __future__ import annotations

import html
import json
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
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


FetchText = Callable[[str, int], str]

NANTOU_LOCAL_TZ = timezone(timedelta(hours=8))
DEFAULT_NANTOU_WATER_TIMEOUT_SECONDS = 8
NANTOU_ATTRIBUTION = "南投縣政府 / 南投雨水下水道即時水情監測系統"
NANTOU_USER_AGENT = "FloodRiskTaiwan/0.1 worker-local-nantou-water"
NANTOU_SEWER_WATER_LEVEL_KML_URL = "https://dpinfo.nantou.gov.tw/Api/Proxy/GetKML"
NANTOU_SEWER_WATER_LEVEL_DATA_URL = "https://dpinfo.nantou.gov.tw/"

NANTOU_SEWER_WATER_LEVEL_METADATA = AdapterMetadata(
    key="local.nantou.sewer_water_level",
    family=SourceFamily.OFFICIAL,
    enabled_by_default=False,
    display_name="Nantou sewer water-level KML adapter",
    data_gov_url=NANTOU_SEWER_WATER_LEVEL_DATA_URL,
    resource_url=NANTOU_SEWER_WATER_LEVEL_KML_URL,
    update_frequency="Nantou KML feed carries per-station 更新時間 fields",
    license="Government Open Data License, version 1.0",
    limitations=(
        "Supplemental local-government sewer water-level source for Nantou County.",
        "Realtime metrics are embedded as JSON inside KML Placemark descriptions.",
        "Hourly rainfall is preserved as contextual raw metric and the normalized "
        "event remains sewer water level.",
    ),
)


class NantouWaterAdapterError(RuntimeError):
    """Base error for Nantou local water adapter failures."""


class NantouWaterFetchError(NantouWaterAdapterError):
    """Raised when fetching Nantou KML fails."""


class NantouWaterPayloadError(NantouWaterAdapterError):
    """Raised when Nantou KML cannot be parsed."""


class NantouSewerWaterLevelKmlAdapter:
    metadata = NANTOU_SEWER_WATER_LEVEL_METADATA

    def __init__(
        self,
        *,
        kml_url: str | None = None,
        timeout_seconds: int = DEFAULT_NANTOU_WATER_TIMEOUT_SECONDS,
        fetched_at: datetime | None = None,
        fetch_text: FetchText | None = None,
        raw_snapshot_key: str | None = None,
    ) -> None:
        self._kml_url = (kml_url or NANTOU_SEWER_WATER_LEVEL_KML_URL).strip()
        self._timeout_seconds = max(1, timeout_seconds)
        self._fetched_at = fetched_at
        self._fetch_text = fetch_text or fetch_nantou_text
        self._raw_snapshot_key = raw_snapshot_key

    def fetch(self) -> tuple[RawSourceItem, ...]:
        try:
            text = self._fetch_text(self._kml_url, self._timeout_seconds)
        except NantouWaterAdapterError:
            raise
        except Exception as exc:
            raise NantouWaterFetchError(
                f"{self.metadata.display_name} fetcher failed: {exc}"
            ) from exc

        records = parse_nantou_sewer_water_level_kml(
            text,
            source_url=NANTOU_SEWER_WATER_LEVEL_DATA_URL,
            resource_url=self._kml_url,
        )
        fetched_at = self._fetched_at or datetime.now(UTC)
        return _raw_items(records, fetched_at=fetched_at, raw_snapshot_key=self._raw_snapshot_key)

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        return _normalize_water_level_record(self.metadata, raw_item)

    def run(self) -> AdapterRunResult:
        return _run(self)


def fetch_nantou_text(url: str, timeout_seconds: int) -> str:
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.google-earth.kml+xml,application/xml,text/xml,*/*",
            "User-Agent": NANTOU_USER_AGENT,
        },
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return response.read().decode("utf-8-sig")
    except (HTTPError, URLError, TimeoutError, UnicodeDecodeError) as exc:
        raise NantouWaterFetchError(f"Failed to fetch Nantou KML {url}: {exc}") from exc


def parse_nantou_sewer_water_level_kml(
    text: str,
    *,
    source_url: str,
    resource_url: str | None = None,
) -> tuple[Mapping[str, Any], ...]:
    try:
        root = ET.fromstring(text.lstrip("\ufeff").strip())
    except ET.ParseError as exc:
        raise NantouWaterPayloadError(f"Nantou KML payload is not parseable: {exc}") from exc

    records: list[Mapping[str, Any]] = []
    for placemark in root.findall(".//{*}Placemark"):
        name = optional_str(_find_text(placemark, ".//{*}name"))
        description = optional_str(_find_text(placemark, ".//{*}description"))
        coordinate = _placemark_coordinate(placemark)
        if name is None or description is None or coordinate is None:
            continue
        parsed_description = _json_description(description)
        if parsed_description is None:
            continue
        data_by_title = _description_data_by_title(parsed_description)
        observed_at = _parse_local_time(data_by_title.get("更新時間"))
        water_level_m = optional_float(data_by_title.get("水位高度(m)"))
        if observed_at is None or water_level_m is None:
            continue
        chart_url = _description_iframe_url(parsed_description)
        station_id = _station_id_from_url(chart_url) or name
        longitude, latitude = coordinate
        record: dict[str, Any] = {
            "station_id": station_id,
            "station_name": name,
            "observed_at": observed_at.isoformat(),
            "water_level_m": water_level_m,
            "source_url": source_url,
            "resource_url": resource_url,
            "chart_url": chart_url,
            "location_text": name,
            "town": _town_from_name(name),
            "longitude": longitude,
            "latitude": latitude,
            "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
            "authority": "南投縣政府",
            "attribution": NANTOU_ATTRIBUTION,
            "confidence": 0.83,
        }
        _assign_float(record, "rainfall_mm_1h", data_by_title.get("時雨量(mm)"))
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
    summary = f"南投地方下水道水位觀測：{water_level_m:.2f} 公尺（{station_name}）"
    rainfall_mm_1h = optional_float(payload.get("rainfall_mm_1h"))
    if rainfall_mm_1h is not None:
        summary = f"{summary}；時雨量 {rainfall_mm_1h:.1f} mm"
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
        confidence=float(payload.get("confidence", 0.83)),
        status=IngestionStatus.NORMALIZED,
        attribution=optional_str(payload.get("attribution")) or NANTOU_ATTRIBUTION,
        tags=("official", "local_nantou", "sewer_water_level"),
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


def _find_text(element: ET.Element, path: str) -> str | None:
    found = element.find(path)
    if found is None:
        return None
    return found.text


def _placemark_coordinate(placemark: ET.Element) -> tuple[float, float] | None:
    coordinates = optional_str(_find_text(placemark, ".//{*}coordinates"))
    if coordinates is None:
        return None
    parts = [part.strip() for part in coordinates.split(",")]
    if len(parts) < 2:
        return None
    return _coordinate(parts[0], parts[1])


def _json_description(description: str) -> Mapping[str, Any] | None:
    normalized = html.unescape(description)
    match = re.search(
        r"<jsonDescription[^>]*>(.*?)</jsonDescription>",
        normalized,
        flags=re.IGNORECASE | re.DOTALL,
    )
    candidate = match.group(1) if match is not None else normalized
    json_match = re.search(r"\{.*\}", candidate, flags=re.DOTALL)
    if json_match is None:
        return None
    try:
        parsed = json.loads(json_match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, Mapping) else None


def _description_data_by_title(description: Mapping[str, Any]) -> dict[str, str]:
    datas = description.get("datas")
    if not isinstance(datas, list):
        return {}
    values: dict[str, str] = {}
    for item in datas:
        if not isinstance(item, Mapping):
            continue
        title = optional_str(item.get("title"))
        value = optional_str(item.get("value"))
        if title is not None and value is not None:
            values[title] = value
    return values


def _description_iframe_url(description: Mapping[str, Any]) -> str | None:
    datas = description.get("datas")
    if not isinstance(datas, list):
        return None
    for item in datas:
        if not isinstance(item, Mapping):
            continue
        url = optional_str(item.get("url"))
        if url is not None:
            return url
    return None


def _station_id_from_url(url: str | None) -> str | None:
    text = optional_str(url)
    if text is None:
        return None
    query = parse_qs(urlsplit(text).query)
    values = query.get("ID") or query.get("id")
    if not values:
        return None
    return optional_str(values[0])


def _parse_local_time(value: object) -> datetime | None:
    text = optional_str(value)
    if text is None:
        return None
    parsed = parse_datetime(text)
    if parsed is None:
        try:
            parsed = datetime.strptime(text, "%Y/%m/%d %H:%M:%S")
        except ValueError:
            return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=NANTOU_LOCAL_TZ)
    return parsed.astimezone(UTC)


def _coordinate(lon: object, lat: object) -> tuple[float, float] | None:
    longitude = optional_float(lon)
    latitude = optional_float(lat)
    if longitude is None or latitude is None:
        return None
    if not (118.0 <= longitude <= 123.5 and 21.0 <= latitude <= 26.5):
        return None
    return longitude, latitude


def _town_from_name(name: str) -> str | None:
    if "-" not in name:
        return None
    return optional_str(name.split("-", 1)[0])


def _assign_float(record: dict[str, Any], key: str, value: object) -> None:
    parsed = optional_float(value)
    if parsed is not None:
        record[key] = parsed
