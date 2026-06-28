from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
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


FetchJson = Callable[[str, int, Mapping[str, Any] | None], Any]

DEFAULT_FHY_FLOOD_SENSOR_TIMEOUT_SECONDS = 8
FHY_MAX_FUTURE_SKEW_MINUTES = 15
FHY_STALE_AFTER_MINUTES = 180
FHY_ATTRIBUTION = "經濟部水利署防災協作平台 FHY Broker / 地方政府淹水感測器"
FHY_USER_AGENT = "FloodRiskTaiwan/0.1 worker-local-fhy-flood-sensor"
FHY_DATA_URL = "https://www.dprcflood.org.tw/SGDS/"
FHY_FLOOD_SENSOR_STATION_API_URL = (
    "https://www.dprcflood.org.tw/SGDS/WS/FHYBrokerWS.asmx/"
    "GetFHYFloodSensorStationByCityCode"
)
FHY_FLOOD_SENSOR_REALTIME_API_URL = (
    "https://www.dprcflood.org.tw/SGDS/WS/FHYBrokerWS.asmx/GetFHYFloodSensorInfoRt"
)


@dataclass(frozen=True)
class FhyFloodSensorSource:
    county: str
    slug: str
    city_code: int
    supplier_tokens: tuple[str, ...]
    metadata: AdapterMetadata


def _metadata(key: str, display_name: str, county: str) -> AdapterMetadata:
    return AdapterMetadata(
        key=key,
        family=SourceFamily.OFFICIAL,
        enabled_by_default=False,
        display_name=display_name,
        data_gov_url=FHY_DATA_URL,
        resource_url=FHY_FLOOD_SENSOR_REALTIME_API_URL,
        update_frequency=(
            "FHY broker realtime payload carries per-sensor SourceTime timestamps "
            "as .NET epoch milliseconds"
        ),
        license="Government Open Data License, version 1.0",
        limitations=(
            f"Supplemental {county} local-government flood-depth source from the public FHY broker.",
            "Station metadata is fetched by CityCode and filtered to local-government "
            "Supplier values before joining realtime rows.",
            "Water Resources Agency branch-supplied stations are intentionally excluded "
            "from this local adapter to preserve central/local source boundaries.",
        ),
    )


HSINCHU_COUNTY_FHY_FLOOD_SENSOR = FhyFloodSensorSource(
    county="新竹縣",
    slug="hsinchu_county",
    city_code=10004,
    supplier_tokens=("新竹縣政府",),
    metadata=_metadata(
        "local.hsinchu_county.flood_sensor",
        "Hsinchu County local FHY flood-sensor adapter",
        "Hsinchu County",
    ),
)
MIAOLI_FHY_FLOOD_SENSOR = FhyFloodSensorSource(
    county="苗栗縣",
    slug="miaoli",
    city_code=10005,
    supplier_tokens=("苗栗縣政府",),
    metadata=_metadata(
        "local.miaoli.flood_sensor",
        "Miaoli local FHY flood-sensor adapter",
        "Miaoli County",
    ),
)
CHANGHUA_FHY_FLOOD_SENSOR = FhyFloodSensorSource(
    county="彰化縣",
    slug="changhua",
    city_code=10007,
    supplier_tokens=("彰化縣政府",),
    metadata=_metadata(
        "local.changhua.flood_sensor",
        "Changhua local FHY flood-sensor adapter",
        "Changhua County",
    ),
)
PINGTUNG_FHY_FLOOD_SENSOR = FhyFloodSensorSource(
    county="屏東縣",
    slug="pingtung",
    city_code=10013,
    supplier_tokens=("屏東縣政府",),
    metadata=_metadata(
        "local.pingtung.flood_sensor",
        "Pingtung local FHY flood-sensor adapter",
        "Pingtung County",
    ),
)
HUALIEN_FHY_FLOOD_SENSOR = FhyFloodSensorSource(
    county="花蓮縣",
    slug="hualien",
    city_code=10015,
    supplier_tokens=("花蓮縣政府",),
    metadata=_metadata(
        "local.hualien.flood_sensor",
        "Hualien local FHY flood-sensor adapter",
        "Hualien County",
    ),
)
TAITUNG_FHY_FLOOD_SENSOR = FhyFloodSensorSource(
    county="臺東縣",
    slug="taitung",
    city_code=10014,
    supplier_tokens=("臺東縣政府", "台東縣政府"),
    metadata=_metadata(
        "local.taitung.flood_sensor",
        "Taitung local FHY flood-sensor adapter",
        "Taitung County",
    ),
)
FHY_LOCAL_FLOOD_SENSOR_SOURCES = (
    HSINCHU_COUNTY_FHY_FLOOD_SENSOR,
    MIAOLI_FHY_FLOOD_SENSOR,
    CHANGHUA_FHY_FLOOD_SENSOR,
    PINGTUNG_FHY_FLOOD_SENSOR,
    HUALIEN_FHY_FLOOD_SENSOR,
    TAITUNG_FHY_FLOOD_SENSOR,
)


class FhyFloodSensorAdapterError(RuntimeError):
    """Base error for local FHY flood-sensor adapters."""


class FhyFloodSensorFetchError(FhyFloodSensorAdapterError):
    """Raised when fetching FHY payloads fails."""


class FhyFloodSensorPayloadError(FhyFloodSensorAdapterError):
    """Raised when FHY payloads cannot be parsed."""


class FhyFloodSensorApiAdapter:
    def __init__(
        self,
        source: FhyFloodSensorSource,
        *,
        station_api_url: str | None = None,
        realtime_api_url: str | None = None,
        timeout_seconds: int = DEFAULT_FHY_FLOOD_SENSOR_TIMEOUT_SECONDS,
        fetched_at: datetime | None = None,
        fetch_json: FetchJson | None = None,
        raw_snapshot_key: str | None = None,
    ) -> None:
        self.source = source
        self.metadata = source.metadata
        self._station_api_url = (station_api_url or FHY_FLOOD_SENSOR_STATION_API_URL).strip()
        self._realtime_api_url = (realtime_api_url or FHY_FLOOD_SENSOR_REALTIME_API_URL).strip()
        self._timeout_seconds = max(1, timeout_seconds)
        self._fetched_at = fetched_at
        self._fetch_json = fetch_fhy_json if fetch_json is None else fetch_json
        self._raw_snapshot_key = raw_snapshot_key

    def fetch(self) -> tuple[RawSourceItem, ...]:
        try:
            station_payload = self._fetch_json(
                self._station_api_url,
                self._timeout_seconds,
                {"cityCode": self.source.city_code},
            )
            realtime_payload = self._fetch_json(
                self._realtime_api_url,
                self._timeout_seconds,
                {},
            )
        except FhyFloodSensorAdapterError:
            raise
        except Exception as exc:
            raise FhyFloodSensorFetchError(
                f"{self.metadata.display_name} fetcher failed: {exc}"
            ) from exc
        fetched_at = self._fetched_at or datetime.now(UTC)
        station_metadata = parse_fhy_flood_sensor_station_payload(
            station_payload,
            source=self.source,
            station_metadata_url=self._station_api_url,
        )
        records = parse_fhy_flood_sensor_realtime_payload(
            realtime_payload,
            source=self.source,
            source_url=FHY_DATA_URL,
            resource_url=self._realtime_api_url,
            station_metadata=station_metadata,
            fetched_at=fetched_at,
        )
        return _raw_items(records, fetched_at=fetched_at, raw_snapshot_key=self._raw_snapshot_key)

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        return _normalize_flood_sensor_record(self.source, self.metadata, raw_item)

    def run(self) -> AdapterRunResult:
        return _run(self)


def fetch_fhy_json(
    url: str,
    timeout_seconds: int,
    body: Mapping[str, Any] | None = None,
) -> Any:
    payload = json.dumps(dict(body or {})).encode("utf-8")
    request = Request(
        url,
        data=payload,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
            "Origin": "https://www.dprcflood.org.tw",
            "Referer": "https://www.dprcflood.org.tw/SGDS/",
            "User-Agent": FHY_USER_AGENT,
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8-sig"))
    except (HTTPError, URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FhyFloodSensorFetchError(f"Failed to fetch FHY JSON {url}: {exc}") from exc


def parse_fhy_flood_sensor_station_payload(
    payload: object,
    *,
    source: FhyFloodSensorSource,
    station_metadata_url: str | None = None,
) -> dict[str, Mapping[str, Any]]:
    records: dict[str, Mapping[str, Any]] = {}
    for item in _payload_items(payload):
        if not isinstance(item, Mapping):
            continue
        if _first_text(item, "CityCode", "city_code") != str(source.city_code):
            continue
        supplier = _first_text(item, "Supplier", "supplier")
        if not _supplier_is_local(supplier, source.supplier_tokens):
            continue
        station_id = _first_text(item, "SensorUUID", "sensor_uuid")
        station_name = _first_text(item, "SensorName", "sensor_name")
        point = item.get("Point")
        if not isinstance(point, Mapping):
            continue
        coordinate = _coordinate(
            _first_value(point, "Longitude", "longitude"),
            _first_value(point, "Latitude", "latitude"),
        )
        if station_id is None or station_name is None or coordinate is None:
            continue
        longitude, latitude = coordinate
        records[station_id] = {
            "station_id": station_id,
            "station_name": station_name,
            "county": source.county,
            "address": _first_text(item, "Address", "address"),
            "location_text": _first_text(item, "Address", "address") or station_name,
            "sensor_type": _first_text(item, "SensorType", "sensor_type"),
            "authority": supplier or source.supplier_tokens[0],
            "longitude": longitude,
            "latitude": latitude,
            "station_metadata_url": station_metadata_url,
            "city_code": source.city_code,
        }
    return records


def parse_fhy_flood_sensor_realtime_payload(
    payload: object,
    *,
    source: FhyFloodSensorSource,
    source_url: str,
    resource_url: str | None = None,
    station_metadata: Mapping[str, Mapping[str, Any]] | None = None,
    fetched_at: datetime | None = None,
) -> tuple[Mapping[str, Any], ...]:
    metadata_by_station = station_metadata or {}
    records: list[Mapping[str, Any]] = []
    for item in _payload_items(payload):
        if not isinstance(item, Mapping):
            continue
        station_id = _first_text(item, "SensorUUID", "sensor_uuid")
        observed_at = _parse_dotnet_date(_first_value(item, "SourceTime", "source_time"))
        flood_depth_cm = optional_float(_first_value(item, "Depth", "depth"))
        if station_id is None or observed_at is None or flood_depth_cm is None:
            continue
        if flood_depth_cm < 0:
            continue
        metadata = metadata_by_station.get(station_id)
        if metadata is None:
            continue
        coordinate = _coordinate(metadata.get("longitude"), metadata.get("latitude"))
        if coordinate is None:
            continue
        longitude, latitude = coordinate
        record: dict[str, Any] = {
            **metadata,
            "station_id": station_id,
            "observed_at": observed_at.isoformat(),
            "flood_depth_cm": flood_depth_cm,
            "source_url": source_url,
            "resource_url": resource_url,
            "longitude": longitude,
            "latitude": latitude,
            "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
            "attribution": FHY_ATTRIBUTION,
            "confidence": 0.82,
            "quality_flags": _quality_flags(observed_at, fetched_at=fetched_at),
        }
        transfer_at = _parse_dotnet_date(_first_value(item, "TransferTime", "transfer_time"))
        if transfer_at is not None:
            record["transfer_at"] = transfer_at.isoformat()
        to_be_confirmed = _first_value(item, "ToBeConfirm", "to_be_confirm")
        if to_be_confirmed is not None:
            record["to_be_confirmed"] = bool(to_be_confirmed)
        records.append(record)
    return tuple(records)


def _normalize_flood_sensor_record(
    source: FhyFloodSensorSource,
    metadata: AdapterMetadata,
    raw_item: RawSourceItem,
) -> NormalizedEvidence | None:
    payload = raw_item.payload
    station_name = optional_str(payload.get("station_name"))
    observed_at = parse_datetime(payload.get("observed_at"))
    flood_depth_cm = optional_float(payload.get("flood_depth_cm"))
    if station_name is None or observed_at is None or flood_depth_cm is None:
        return None
    if _has_blocking_quality_flag(payload):
        return None
    if flood_depth_cm == 0:
        summary = f"{source.county}地方淹水感測：無觀測到淹水（0 公分）（{station_name}）"
        depth_tags = ["dry", "no_flooding_observed"]
    elif flood_depth_cm < 3:
        summary = f"{source.county}地方淹水感測：低水深觀測 {_format_depth_cm(flood_depth_cm)} 公分（{station_name}）"
        depth_tags = ["below_flood_threshold", "low_depth_observation"]
    else:
        summary = f"{source.county}地方淹水感測：水深 {_format_depth_cm(flood_depth_cm)} 公分（{station_name}）"
        depth_tags = []
    return _evidence(
        metadata,
        raw_item,
        event_type=EventType.FLOOD_REPORT,
        station_name=station_name,
        observed_at=observed_at,
        summary=summary,
        tags=("official", f"local_{source.slug}", "fhy_flood_sensor", "flood_sensor", *depth_tags),
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
        attribution=optional_str(payload.get("attribution")) or FHY_ATTRIBUTION,
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
        current: object = payload
        for key in ("d", "data", "Data", "Result", "result"):
            if isinstance(current, Mapping) and key in current:
                current = current[key]
        if isinstance(current, list):
            return tuple(current)
    return ()


def _parse_dotnet_date(value: object) -> datetime | None:
    text = optional_str(value)
    if text is None:
        return None
    match = re.search(r"/Date\((-?\d+)\)/", text)
    if match is None:
        return parse_datetime(text)
    try:
        return datetime.fromtimestamp(int(match.group(1)) / 1000, UTC)
    except (OSError, ValueError):
        return None


def _quality_flags(
    observed_at: datetime,
    *,
    fetched_at: datetime | None,
) -> dict[str, bool]:
    if fetched_at is None:
        return {"future_observation": False, "stale_observation": False}
    return {
        "future_observation": observed_at > fetched_at + timedelta(minutes=FHY_MAX_FUTURE_SKEW_MINUTES),
        "stale_observation": observed_at < fetched_at - timedelta(minutes=FHY_STALE_AFTER_MINUTES),
    }


def _has_blocking_quality_flag(payload: Mapping[str, Any]) -> bool:
    quality_flags = payload.get("quality_flags")
    if not isinstance(quality_flags, Mapping):
        return False
    return (
        quality_flags.get("future_observation") is True
        or quality_flags.get("stale_observation") is True
    )


def _supplier_is_local(supplier: str | None, supplier_tokens: tuple[str, ...]) -> bool:
    if supplier is None:
        return False
    return any(token in supplier for token in supplier_tokens)


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


def _format_depth_cm(value: float) -> str:
    return f"{value:.0f}" if value.is_integer() else f"{value:.1f}"
