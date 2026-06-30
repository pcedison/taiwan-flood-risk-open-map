from __future__ import annotations

import json
import math
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.adapters._helpers import (
    optional_float,
    optional_str,
    parse_datetime,
    parse_observed_at_utc,
    stable_evidence_id,
    url_with_query,
)
from app.adapters._taiwan_gov_tls import taiwan_gov_open_data_ssl_context
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

WRA_WATER_LEVEL_API_URL = (
    "https://opendata.wra.gov.tw/api/v2/73c4c3de-4045-4765-abeb-89f9f9cd5ff0"
    "?format=JSON&sort=_importdate+desc&limit=5000"
)
WRA_WATER_STATION_API_URL = (
    "https://opendata.wra.gov.tw/api/v2/c4acc691-7416-40ca-9464-292c0c00da92"
    "?format=JSON&limit=5000"
)
WRA_WATER_LEVEL_DATA_GOV_DATASET_ID = "25768"
WRA_WATER_LEVEL_DATA_GOV_URL = "https://data.gov.tw/dataset/25768"
WRA_WATER_LEVEL_ATTRIBUTION = "Water Resources Agency"
WRA_WATER_LEVEL_USER_AGENT = "FloodRiskTaiwan/0.1 worker-wra-water-level"
DEFAULT_WRA_WATER_LEVEL_TIMEOUT_SECONDS = 8

WRA_WATER_LEVEL_METADATA = AdapterMetadata(
    key="official.wra.water_level",
    family=SourceFamily.OFFICIAL,
    enabled_by_default=True,
    display_name="WRA water level observation adapter",
    data_gov_dataset_id=WRA_WATER_LEVEL_DATA_GOV_DATASET_ID,
    data_gov_url=WRA_WATER_LEVEL_DATA_GOV_URL,
    resource_url=WRA_WATER_LEVEL_API_URL,
    update_frequency="data.gov.tw metadata: every 1 hour; observations are recorded every 10 minutes",
    license="Government Open Data License, version 1.0",
    limitations=(
        "Realtime water-level observations are raw and not fully quality checked.",
        "Transmission interruption or instrument failure can stop or distort station data.",
    ),
)


class WraWaterLevelAdapterError(RuntimeError):
    """Base error for WRA water level adapter failures."""


class WraWaterLevelFetchError(WraWaterLevelAdapterError):
    """Raised when fetching WRA water level API payloads fails."""


class WraWaterLevelPayloadError(WraWaterLevelAdapterError):
    """Raised when the WRA water level API payload shape is not parseable."""


class WraWaterLevelApiAdapter:
    metadata = WRA_WATER_LEVEL_METADATA

    def __init__(
        self,
        *,
        api_url: str | None = None,
        station_api_url: str | None = None,
        api_token: str | None = None,
        timeout_seconds: int = DEFAULT_WRA_WATER_LEVEL_TIMEOUT_SECONDS,
        fetched_at: datetime | None = None,
        fetch_json: FetchJson | None = None,
        raw_snapshot_key: str | None = None,
    ) -> None:
        self._api_url = (api_url or WRA_WATER_LEVEL_API_URL).strip()
        self._station_api_url = (station_api_url or WRA_WATER_STATION_API_URL).strip()
        self._api_token = api_token
        self._timeout_seconds = max(1, timeout_seconds)
        self._fetched_at = fetched_at
        self._fetch_json = fetch_json or _fetch_json
        self._raw_snapshot_key = raw_snapshot_key

    def fetch(self) -> tuple[RawSourceItem, ...]:
        request_url = _wra_water_level_request_url(self._api_url, self._api_token)
        resource_url = _wra_water_level_source_url(self._api_url)
        station_request_url = _wra_water_level_request_url(self._station_api_url, self._api_token)
        station_resource_url = _wra_water_level_source_url(self._station_api_url)
        try:
            payload = self._fetch_json(request_url, self._timeout_seconds)
            station_payload = self._fetch_json(station_request_url, self._timeout_seconds)
        except WraWaterLevelAdapterError:
            raise
        except Exception as exc:
            raise WraWaterLevelFetchError(f"WRA water level fetcher failed: {exc}") from exc

        station_metadata = parse_wra_station_metadata_payload(station_payload)
        records = parse_wra_water_level_api_payload(
            payload,
            source_url=WRA_WATER_LEVEL_DATA_GOV_URL,
            resource_url=resource_url,
            station_metadata=station_metadata,
            station_metadata_url=station_resource_url,
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
        return _normalize_water_level_record(self.metadata, raw_item)

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


class WraWaterLevelAdapter:
    metadata = WRA_WATER_LEVEL_METADATA

    def __init__(
        self,
        records: Iterable[Mapping[str, Any]],
        *,
        fetched_at: datetime,
        raw_snapshot_key: str | None = None,
    ) -> None:
        self._records = tuple(records)
        self._fetched_at = fetched_at
        self._raw_snapshot_key = raw_snapshot_key

    def fetch(self) -> tuple[RawSourceItem, ...]:
        return tuple(
            RawSourceItem(
                source_id=_source_id(record),
                source_url=str(record["source_url"]),
                fetched_at=self._fetched_at,
                payload=record,
                raw_snapshot_key=self._raw_snapshot_key,
            )
            for record in self._records
        )

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        return _normalize_water_level_record(self.metadata, raw_item)

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


def parse_wra_water_level_api_payload(
    payload: object,
    *,
    source_url: str,
    resource_url: str | None = None,
    station_metadata: Mapping[str, Mapping[str, Any]] | None = None,
    station_metadata_url: str | None = None,
) -> tuple[Mapping[str, Any], ...]:
    items = _water_level_items(payload)
    parsed: list[Mapping[str, Any]] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        record = _parse_wra_station_record(
            item,
            source_url=source_url,
            resource_url=resource_url,
            station_metadata=station_metadata,
            station_metadata_url=station_metadata_url,
        )
        if record is not None:
            parsed.append(record)
    return tuple(parsed)


def parse_wra_station_metadata_payload(payload: object) -> dict[str, Mapping[str, Any]]:
    records: dict[str, Mapping[str, Any]] = {}
    for item in _station_metadata_items(payload):
        if not isinstance(item, Mapping):
            continue
        record = _parse_wra_station_metadata_record(item)
        if record is None:
            continue
        for key in _station_metadata_lookup_keys(record):
            records[key] = record
    return records


def _normalize_water_level_record(
    metadata: AdapterMetadata,
    raw_item: RawSourceItem,
) -> NormalizedEvidence | None:
    payload = raw_item.payload
    station_name = str(payload.get("station_name", "")).strip()
    observed_at = parse_datetime(payload.get("observed_at"))
    water_level_m = optional_float(payload.get("water_level_m"))
    warning_level_m = optional_float(payload.get("warning_level_m"))

    if not station_name or observed_at is None or water_level_m is None:
        return None

    river_name = optional_str(payload.get("river_name"))
    location_text = " ".join(part for part in (river_name, station_name) if part)
    summary = f"Observed water level: {water_level_m:.2f} m"
    tags = ["official", "wra", "water_level"]
    if warning_level_m is not None:
        gap = warning_level_m - water_level_m
        summary = f"{summary}; {gap:.2f} m below warning level"
        if gap <= 0:
            tags.append("warning_threshold_reached")

    return NormalizedEvidence(
        evidence_id=stable_evidence_id(metadata.key, raw_item.source_id),
        adapter_key=metadata.key,
        source_family=metadata.family,
        event_type=EventType.WATER_LEVEL,
        source_id=raw_item.source_id,
        source_url=raw_item.source_url,
        source_title=f"WRA water level observation: {station_name}",
        source_timestamp=observed_at,
        fetched_at=raw_item.fetched_at,
        summary=summary,
        location_text=location_text or station_name,
        confidence=float(payload.get("confidence", 0.9)),
        status=IngestionStatus.NORMALIZED,
        attribution=optional_str(payload.get("attribution")) or WRA_WATER_LEVEL_ATTRIBUTION,
        tags=tuple(tags),
    )


def _source_id(record: Mapping[str, Any]) -> str:
    station_id = str(record["station_id"])
    observed_at = str(record["observed_at"])
    return f"{station_id}:{observed_at}"


def _water_level_items(payload: object) -> Iterable[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, Mapping):
        raise WraWaterLevelPayloadError(
            "WRA water level payload is missing a water level record list"
        )

    for key in ("responseData", "data", "Data"):
        items = payload.get(key)
        if isinstance(items, list):
            return items

    records = payload.get("records")
    if isinstance(records, list):
        return records
    if isinstance(records, Mapping):
        for key in ("WaterLevel", "waterLevel", "Station", "records"):
            items = records.get(key)
            if isinstance(items, list):
                return items

    raise WraWaterLevelPayloadError(
        "WRA water level payload is missing a water level record list"
    )


def _parse_wra_station_record(
    item: Mapping[str, Any],
    *,
    source_url: str,
    resource_url: str | None,
    station_metadata: Mapping[str, Mapping[str, Any]] | None,
    station_metadata_url: str | None,
) -> Mapping[str, Any] | None:
    station_id = _first_text(
        item,
        "station_id",
        "StationId",
        "StationID",
        "StationNo",
        "ST_NO",
        "ObservatoryIdentifier",
        "stationid",
        "basinidentifier",
    )
    station_name = _first_text(
        item,
        "station_name",
        "StationName",
        "StationNameEng",
        "observatoryname",
    )
    observed_at = parse_observed_at_utc(
        _first_value(
            item,
            "observed_at",
            "Time",
            "DateTime",
            "RecordTime",
            "ObserveTime",
            "datetime",
        )
    )
    water_level_m = optional_float(
        _first_value(
            item,
            "water_level_m",
            "WaterLevel",
            "WaterLevelM",
            "Stage",
            "waterlevel",
        )
    )
    if station_id is None or observed_at is None or water_level_m is None:
        return None
    if water_level_m <= -90:
        return None
    metadata = station_metadata.get(station_id) if station_metadata is not None else None
    station_name = station_name or _metadata_text(metadata, "station_name") or station_id

    record: dict[str, Any] = {
        "station_id": station_id,
        "station_name": station_name,
        "observed_at": observed_at.isoformat(),
        "water_level_m": water_level_m,
        "source_url": source_url,
        "attribution": WRA_WATER_LEVEL_ATTRIBUTION,
        "confidence": 0.92,
    }
    if resource_url is not None:
        record["resource_url"] = resource_url
    if station_metadata_url is not None:
        record["station_metadata_url"] = station_metadata_url

    river_name = _first_text(item, "river_name", "RiverName", "rivername") or _metadata_text(
        metadata,
        "river_name",
    )
    warning_level_m = optional_float(
        _first_value(
            item,
            "warning_level_m",
            "WarningLevel",
            "WarningStage",
            "alertlevel2",
            "AlertLevel2",
            "alertlevel1",
            "AlertLevel1",
        )
    )
    if warning_level_m is None:
        warning_level_m = _metadata_float(metadata, "alert_level_2_m")
    if warning_level_m is None:
        warning_level_m = _metadata_float(metadata, "alert_level_1_m")
    if river_name is not None:
        record["river_name"] = river_name
    if warning_level_m is not None:
        record["warning_level_m"] = warning_level_m

    lat = optional_float(_first_value(item, "latitude", "Latitude", "Lat"))
    lng = optional_float(_first_value(item, "longitude", "Longitude", "Lon", "Lng"))
    if lat is None:
        lat = _metadata_float(metadata, "latitude")
    if lng is None:
        lng = _metadata_float(metadata, "longitude")
    if lat is not None and lng is not None:
        record["latitude"] = lat
        record["longitude"] = lng
        record["geometry"] = {"type": "Point", "coordinates": [lng, lat]}

    return record


def _parse_wra_station_metadata_record(item: Mapping[str, Any]) -> Mapping[str, Any] | None:
    status = _first_text(item, "observationstatus", "ObservationStatus")
    if status == "\u5df2\u5ee2":
        return None

    station_id = _first_text(
        item,
        "basinidentifier",
        "stationid",
        "StationId",
        "StationID",
        "StationNo",
        "ST_NO",
    )
    if station_id is None:
        return None

    coordinate = _wra_station_metadata_coordinate(item)
    if coordinate is None:
        return None
    lat, lng = coordinate
    record: dict[str, Any] = {
        "station_id": station_id,
        "latitude": lat,
        "longitude": lng,
    }

    observatory_identifier = _first_text(
        item,
        "observatoryidentifier",
        "ObservatoryIdentifier",
    )
    station_name = _first_text(item, "observatoryname", "StationName", "station_name")
    river_name = _first_text(item, "rivername", "RiverName", "river_name")
    alert_level_1_m = optional_float(_first_value(item, "alertlevel1", "AlertLevel1"))
    alert_level_2_m = optional_float(_first_value(item, "alertlevel2", "AlertLevel2"))

    if observatory_identifier is not None:
        record["observatory_identifier"] = observatory_identifier
    if station_name is not None:
        record["station_name"] = station_name
    if river_name is not None:
        record["river_name"] = river_name
    if alert_level_1_m is not None:
        record["alert_level_1_m"] = alert_level_1_m
    if alert_level_2_m is not None:
        record["alert_level_2_m"] = alert_level_2_m
    return record


def _station_metadata_lookup_keys(record: Mapping[str, Any]) -> tuple[str, ...]:
    keys = [
        value
        for value in (
            record.get("station_id"),
            record.get("observatory_identifier"),
        )
        if isinstance(value, str) and value
    ]
    return tuple(dict.fromkeys(keys))


def _wra_station_metadata_coordinate(item: Mapping[str, Any]) -> tuple[float, float] | None:
    lat = optional_float(_first_value(item, "latitude", "Latitude", "Lat"))
    lng = optional_float(_first_value(item, "longitude", "Longitude", "Lon", "Lng"))
    if lat is not None and lng is not None:
        return (lat, lng)
    return _twd97_xy_to_wgs84(
        _first_value(
            item,
            "locationbytwd97_xy",
            "LocationByTWD97_XY",
            "TWD97_XY",
        )
    )


def _metadata_text(metadata: Mapping[str, Any] | None, key: str) -> str | None:
    if metadata is None:
        return None
    return optional_str(metadata.get(key))


def _metadata_float(metadata: Mapping[str, Any] | None, key: str) -> float | None:
    if metadata is None:
        return None
    return optional_float(metadata.get(key))


def _fetch_json(url: str, timeout_seconds: int) -> Any:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": WRA_WATER_LEVEL_USER_AGENT,
        },
        method="GET",
    )
    try:
        with urlopen(
            request,
            timeout=timeout_seconds,
            context=taiwan_gov_open_data_ssl_context(),
        ) as response:
            payload: Any = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise WraWaterLevelFetchError(f"WRA water level API returned HTTP {exc.code}") from exc
    except (URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WraWaterLevelFetchError(f"WRA water level API request failed: {exc}") from exc

    if not isinstance(payload, (Mapping, list)):
        raise WraWaterLevelPayloadError(
            "WRA water level API returned a non-object/list JSON payload"
        )
    return payload


def _wra_water_level_request_url(api_url: str, api_token: str | None) -> str:
    params = {"format": "JSON"}
    token = optional_str(api_token)
    if token is not None:
        params["api_key"] = token
    return url_with_query(api_url, params, drop_keys=("api_key",))


def _wra_water_level_source_url(api_url: str) -> str:
    return url_with_query(api_url, {"format": "JSON"}, drop_keys=("api_key",))


def _station_metadata_items(payload: object) -> Iterable[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, Mapping):
        raise WraWaterLevelPayloadError(
            "WRA station metadata payload is missing a station metadata record list"
        )
    for key in ("responseData", "data", "Data", "records"):
        items = payload.get(key)
        if isinstance(items, list):
            return items
    raise WraWaterLevelPayloadError(
        "WRA station metadata payload is missing a station metadata record list"
    )


def _first_text(item: Mapping[str, Any], *keys: str) -> str | None:
    return optional_str(_first_value(item, *keys))


def _first_value(item: Mapping[str, Any], *keys: str) -> object:
    for key in keys:
        value = item.get(key)
        if value is not None:
            return value
    return None


def _twd97_xy_to_wgs84(value: object) -> tuple[float, float] | None:
    if not isinstance(value, str):
        return None
    parts = value.split()
    if len(parts) != 2:
        return None
    x = optional_float(parts[0])
    y = optional_float(parts[1])
    if x is None or y is None:
        return None

    a = 6378137.0
    b = 6356752.314245
    lng0 = math.radians(121)
    k0 = 0.9999
    dx = 250000.0
    dy = 0.0
    e = math.sqrt(1 - (b * b) / (a * a))

    x -= dx
    y -= dy
    m = y / k0
    mu = m / (a * (1 - e**2 / 4 - 3 * e**4 / 64 - 5 * e**6 / 256))
    e1 = (1 - math.sqrt(1 - e**2)) / (1 + math.sqrt(1 - e**2))

    fp = (
        mu
        + (3 * e1 / 2 - 27 * e1**3 / 32) * math.sin(2 * mu)
        + (21 * e1**2 / 16 - 55 * e1**4 / 32) * math.sin(4 * mu)
        + (151 * e1**3 / 96) * math.sin(6 * mu)
        + (1097 * e1**4 / 512) * math.sin(8 * mu)
    )

    e2 = e**2 / (1 - e**2)
    c1 = e2 * math.cos(fp) ** 2
    t1 = math.tan(fp) ** 2
    r1 = a * (1 - e**2) / ((1 - e**2 * math.sin(fp) ** 2) ** 1.5)
    n1 = a / math.sqrt(1 - e**2 * math.sin(fp) ** 2)
    d = x / (n1 * k0)

    lat = fp - (n1 * math.tan(fp) / r1) * (
        d**2 / 2
        - (5 + 3 * t1 + 10 * c1 - 4 * c1**2 - 9 * e2) * d**4 / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1**2 - 252 * e2 - 3 * c1**2) * d**6 / 720
    )
    lng = lng0 + (
        d
        - (1 + 2 * t1 + c1) * d**3 / 6
        + (5 - 2 * c1 + 28 * t1 - 3 * c1**2 + 8 * e2 + 24 * t1**2) * d**5 / 120
    ) / math.cos(fp)

    return (math.degrees(lat), math.degrees(lng))
