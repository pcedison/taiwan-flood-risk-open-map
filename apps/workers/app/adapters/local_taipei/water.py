from __future__ import annotations

import csv
import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
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


FetchJson = Callable[[str, int], Any]
FetchText = Callable[[str, int], str]

TAIPEI_LOCAL_TZ = timezone(timedelta(hours=8))
DEFAULT_TAIPEI_WATER_TIMEOUT_SECONDS = 8
DEFAULT_TAIPEI_MAX_OBSERVATION_AGE_MINUTES = 180
TAIPEI_ATTRIBUTION = "臺北市政府工務局水利工程處 / 臺北市資料大平臺"
TAIPEI_USER_AGENT = "FloodRiskTaiwan/0.1 worker-local-taipei-water"

TAIPEI_SEWER_WATER_LEVEL_API_URL = (
    "https://wic.gov.taipei/OpenData/API/Sewer/Get?stationNo=&loginId=sewer01"
    "&dataKey=BD3E513A"
)
TAIPEI_SEWER_WATER_LEVEL_METADATA_CSV_URL = (
    "https://data.taipei/api/dataset/b3648c5d-15c8-416a-a603-fda7a9ac1b0d/"
    "resource/586e5233-aa60-4680-8ac1-cbb9ef7f7fde/download"
)
TAIPEI_SEWER_WATER_LEVEL_DATA_URL = (
    "https://data.taipei/dataset/detail?id=cd444840-bbfb-4b0a-bdfa-2a36d49b3794"
)

TAIPEI_RIVER_WATER_LEVEL_API_URL = (
    "https://wic.gov.taipei/OpenData/API/Water/Get?stationNo=&loginId=river"
    "&dataKey=9E2648AA"
)
TAIPEI_RIVER_WATER_LEVEL_METADATA_CSV_URL = (
    "https://data.taipei/api/dataset/0016a730-aef1-43c5-baaf-0f08e270c0f6/"
    "resource/98fce0a1-66f9-4b10-b384-1e80a7999e27/download"
)
TAIPEI_RIVER_WATER_LEVEL_DATA_URL = (
    "https://data.taipei/dataset/detail?id=5b4b8ae1-9505-4a1a-8808-feea14e78130"
)

TAIPEI_PUMP_STATION_API_URL = "https://heopublic.gov.taipei/taipei-heo-api/openapi/pumb/latest"
TAIPEI_PUMP_STATION_DATA_URL = (
    "https://data.taipei/dataset/detail?id=2bbfb30e-de58-43bd-9cc9-b56e9a6b5369"
)


class TaipeiWaterAdapterError(RuntimeError):
    """Base error for Taipei local water adapters."""


class TaipeiWaterFetchError(TaipeiWaterAdapterError):
    """Raised when fetching Taipei local water payloads fails."""


class TaipeiWaterPayloadError(TaipeiWaterAdapterError):
    """Raised when Taipei local water payloads cannot be parsed."""


@dataclass(frozen=True)
class TaipeiWaterLevelSource:
    metadata: AdapterMetadata
    api_url: str
    metadata_csv_url: str
    source_url: str
    source_tag: str
    metadata_station_id_keys: tuple[str, ...]
    metadata_station_name_keys: tuple[str, ...]
    metadata_district_keys: tuple[str, ...]
    metadata_longitude_keys: tuple[str, ...]
    metadata_latitude_keys: tuple[str, ...]
    metadata_extra_keys: tuple[tuple[str, tuple[str, ...]], ...] = ()
    stale_after_minutes: int = DEFAULT_TAIPEI_MAX_OBSERVATION_AGE_MINUTES


TAIPEI_SEWER_WATER_LEVEL = TaipeiWaterLevelSource(
    metadata=AdapterMetadata(
        key="local.taipei.sewer_water_level",
        family=SourceFamily.OFFICIAL,
        enabled_by_default=False,
        display_name="Taipei storm sewer water level adapter",
        data_gov_dataset_id="121643",
        data_gov_url=TAIPEI_SEWER_WATER_LEVEL_DATA_URL,
        resource_url=TAIPEI_SEWER_WATER_LEVEL_API_URL,
        update_frequency="Taipei open-data catalog: realtime, 10 minutes / 1 minute",
        license="Government Open Data License, version 1.0",
        limitations=(
            "Sewer water-level sensors may be affected by sewer environment faults "
            "or unstable transmission.",
            "Coordinates are joined from Taipei dataset 121643; rows without "
            "coordinates are rejected from normalization.",
        ),
    ),
    api_url=TAIPEI_SEWER_WATER_LEVEL_API_URL,
    metadata_csv_url=TAIPEI_SEWER_WATER_LEVEL_METADATA_CSV_URL,
    source_url=TAIPEI_SEWER_WATER_LEVEL_DATA_URL,
    source_tag="sewer_water_level",
    metadata_station_id_keys=("設施編號",),
    metadata_station_name_keys=("站名",),
    metadata_district_keys=("行政區",),
    metadata_longitude_keys=("經度",),
    metadata_latitude_keys=("緯度",),
)

TAIPEI_RIVER_WATER_LEVEL = TaipeiWaterLevelSource(
    metadata=AdapterMetadata(
        key="local.taipei.river_water_level",
        family=SourceFamily.OFFICIAL,
        enabled_by_default=False,
        display_name="Taipei river water level adapter",
        data_gov_dataset_id="138171",
        data_gov_url=TAIPEI_RIVER_WATER_LEVEL_DATA_URL,
        resource_url=TAIPEI_RIVER_WATER_LEVEL_API_URL,
        update_frequency="Taipei open-data catalog: realtime, every 10 minutes",
        license="Government Open Data License, version 1.0",
        limitations=(
            "River water-level telemetry can be affected by instrument or "
            "communication faults.",
            "Coordinates are joined from Taipei dataset 138171; rows without "
            "coordinates or stale observations are rejected from normalization.",
        ),
    ),
    api_url=TAIPEI_RIVER_WATER_LEVEL_API_URL,
    metadata_csv_url=TAIPEI_RIVER_WATER_LEVEL_METADATA_CSV_URL,
    source_url=TAIPEI_RIVER_WATER_LEVEL_DATA_URL,
    source_tag="river_water_level",
    metadata_station_id_keys=("站碼",),
    metadata_station_name_keys=("站名",),
    metadata_district_keys=("行政區",),
    metadata_longitude_keys=("X座標",),
    metadata_latitude_keys=("Y座標",),
    metadata_extra_keys=(("basin", ("流域",)),),
)

TAIPEI_PUMP_STATION = AdapterMetadata(
    key="local.taipei.pump_station",
    family=SourceFamily.OFFICIAL,
    enabled_by_default=False,
    display_name="Taipei pump station status adapter",
    data_gov_url=TAIPEI_PUMP_STATION_DATA_URL,
    resource_url=TAIPEI_PUMP_STATION_API_URL,
    update_frequency="Taipei open-data catalog: realtime, 1 hour / event",
    license="Government Open Data License, version 1.0",
    limitations=(
        "Pump-station telemetry is operational data and may have communication "
        "or facility outages.",
        "The adapter uses outer water level as the flood-relevant water-level "
        "metric and keeps inner water level as an auxiliary metric.",
    ),
)


class TaipeiWaterLevelApiAdapter:
    def __init__(
        self,
        source: TaipeiWaterLevelSource,
        *,
        api_url: str | None = None,
        metadata_csv_url: str | None = None,
        timeout_seconds: int = DEFAULT_TAIPEI_WATER_TIMEOUT_SECONDS,
        fetched_at: datetime | None = None,
        fetch_json: FetchJson | None = None,
        fetch_text: FetchText | None = None,
        raw_snapshot_key: str | None = None,
    ) -> None:
        self._source = source
        self.metadata = source.metadata
        self._api_url = (api_url or source.api_url).strip()
        self._metadata_csv_url = (metadata_csv_url or source.metadata_csv_url).strip()
        self._timeout_seconds = max(1, timeout_seconds)
        self._fetched_at = fetched_at
        self._fetch_json = fetch_json or fetch_taipei_json
        self._fetch_text = fetch_text or fetch_taipei_text
        self._raw_snapshot_key = raw_snapshot_key

    def fetch(self) -> tuple[RawSourceItem, ...]:
        try:
            metadata_text = self._fetch_text(self._metadata_csv_url, self._timeout_seconds)
            payload = self._fetch_json(self._api_url, self._timeout_seconds)
        except TaipeiWaterAdapterError:
            raise
        except Exception as exc:
            raise TaipeiWaterFetchError(
                f"{self.metadata.display_name} fetcher failed: {exc}"
            ) from exc

        fetched_at = self._fetched_at or datetime.now(UTC)
        station_metadata = parse_taipei_station_metadata_csv(metadata_text, source=self._source)
        records = parse_taipei_water_level_payload(
            payload,
            source=self._source,
            station_metadata=station_metadata,
            fetched_at=fetched_at,
            resource_url=self._api_url,
            station_metadata_url=self._metadata_csv_url,
        )
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
        return _normalize_taipei_water_level_record(self._source, raw_item)

    def run(self) -> AdapterRunResult:
        return _run(self)


class TaipeiPumpStationApiAdapter:
    metadata = TAIPEI_PUMP_STATION

    def __init__(
        self,
        *,
        api_url: str | None = None,
        timeout_seconds: int = DEFAULT_TAIPEI_WATER_TIMEOUT_SECONDS,
        fetched_at: datetime | None = None,
        fetch_json: FetchJson | None = None,
        raw_snapshot_key: str | None = None,
        stale_after_minutes: int = DEFAULT_TAIPEI_MAX_OBSERVATION_AGE_MINUTES,
    ) -> None:
        self._api_url = (api_url or TAIPEI_PUMP_STATION_API_URL).strip()
        self._timeout_seconds = max(1, timeout_seconds)
        self._fetched_at = fetched_at
        self._fetch_json = fetch_json or fetch_taipei_json
        self._raw_snapshot_key = raw_snapshot_key
        self._stale_after_minutes = stale_after_minutes

    def fetch(self) -> tuple[RawSourceItem, ...]:
        try:
            payload = self._fetch_json(self._api_url, self._timeout_seconds)
        except TaipeiWaterAdapterError:
            raise
        except Exception as exc:
            raise TaipeiWaterFetchError(
                f"{self.metadata.display_name} fetcher failed: {exc}"
            ) from exc

        fetched_at = self._fetched_at or datetime.now(UTC)
        records = parse_taipei_pump_station_payload(
            payload,
            source_url=TAIPEI_PUMP_STATION_DATA_URL,
            resource_url=self._api_url,
            fetched_at=fetched_at,
            stale_after_minutes=self._stale_after_minutes,
        )
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
        return _normalize_taipei_pump_station_record(self.metadata, raw_item)

    def run(self) -> AdapterRunResult:
        return _run(self)


def fetch_taipei_json(url: str, timeout_seconds: int) -> Any:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": TAIPEI_USER_AGENT})
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8-sig"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise TaipeiWaterFetchError(f"Failed to fetch Taipei JSON API {url}: {exc}") from exc


def fetch_taipei_text(url: str, timeout_seconds: int) -> str:
    request = Request(url, headers={"Accept": "text/csv,*/*", "User-Agent": TAIPEI_USER_AGENT})
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return response.read().decode("utf-8-sig")
    except (HTTPError, URLError, TimeoutError, UnicodeDecodeError) as exc:
        raise TaipeiWaterFetchError(f"Failed to fetch Taipei text API {url}: {exc}") from exc


def parse_taipei_station_metadata_csv(
    text: str,
    *,
    source: TaipeiWaterLevelSource,
) -> dict[str, Mapping[str, Any]]:
    records: dict[str, Mapping[str, Any]] = {}
    reader = csv.DictReader(StringIO(text.lstrip("\ufeff")))
    for row in reader:
        station_id = _first_text(row, *source.metadata_station_id_keys)
        if station_id is None:
            continue
        record: dict[str, Any] = {"station_id": station_id}
        _assign_text(record, "station_name", _first_text(row, *source.metadata_station_name_keys))
        _assign_text(record, "district", _first_text(row, *source.metadata_district_keys))
        for target_key, source_keys in source.metadata_extra_keys:
            _assign_text(record, target_key, _first_text(row, *source_keys))

        longitude = optional_float(_first_value(row, *source.metadata_longitude_keys))
        latitude = optional_float(_first_value(row, *source.metadata_latitude_keys))
        if longitude is not None and latitude is not None and _valid_taiwan_point(
            longitude,
            latitude,
        ):
            record["longitude"] = longitude
            record["latitude"] = latitude
            record["geometry"] = {"type": "Point", "coordinates": [longitude, latitude]}
        records[_station_lookup_key(station_id)] = record
    return records


def parse_taipei_water_level_payload(
    payload: object,
    *,
    source: TaipeiWaterLevelSource,
    station_metadata: Mapping[str, Mapping[str, Any]],
    fetched_at: datetime,
    resource_url: str | None = None,
    station_metadata_url: str | None = None,
) -> tuple[Mapping[str, Any], ...]:
    parsed: list[Mapping[str, Any]] = []
    for item in _payload_items(payload, label=source.metadata.display_name):
        if not isinstance(item, Mapping):
            continue
        record = _parse_water_level_record(
            item,
            source=source,
            station_metadata=station_metadata,
            fetched_at=fetched_at,
            resource_url=resource_url,
            station_metadata_url=station_metadata_url,
        )
        if record is not None:
            parsed.append(record)
    return tuple(parsed)


def parse_taipei_pump_station_payload(
    payload: object,
    *,
    source_url: str,
    fetched_at: datetime,
    resource_url: str | None = None,
    stale_after_minutes: int = DEFAULT_TAIPEI_MAX_OBSERVATION_AGE_MINUTES,
) -> tuple[Mapping[str, Any], ...]:
    parsed: list[Mapping[str, Any]] = []
    for item in _payload_items(payload, label="Taipei pump station"):
        if not isinstance(item, Mapping):
            continue
        record = _parse_pump_station_record(
            item,
            source_url=source_url,
            fetched_at=fetched_at,
            resource_url=resource_url,
            stale_after_minutes=stale_after_minutes,
        )
        if record is not None:
            parsed.append(record)
    return tuple(parsed)


def _parse_water_level_record(
    item: Mapping[str, Any],
    *,
    source: TaipeiWaterLevelSource,
    station_metadata: Mapping[str, Mapping[str, Any]],
    fetched_at: datetime,
    resource_url: str | None,
    station_metadata_url: str | None,
) -> Mapping[str, Any] | None:
    station_id = _first_text(item, "stationNo", "station_no", "id")
    observed_at = _parse_taipei_compact_time(_first_value(item, "recTime", "observed_at"))
    water_level_m = optional_float(_first_value(item, "levelOut", "water_level_m"))
    if station_id is None or observed_at is None or water_level_m is None:
        return None

    metadata = station_metadata.get(_station_lookup_key(station_id))
    station_name = _metadata_text(metadata, "station_name") or _first_text(
        item,
        "stationName",
        "station_name",
    ) or station_id
    quality_flags = _quality_flags(
        metadata=metadata,
        observed_at=observed_at,
        fetched_at=fetched_at,
        stale_after_minutes=source.stale_after_minutes,
    )

    record: dict[str, Any] = {
        "station_id": station_id,
        "station_name": station_name,
        "observed_at": observed_at.isoformat(),
        "water_level_m": water_level_m,
        "source_url": source.source_url,
        "location_text": _location_text(metadata, station_name),
        "authority": "臺北市政府工務局水利工程處",
        "attribution": TAIPEI_ATTRIBUTION,
        "confidence": _confidence(quality_flags),
        "quality_flags": quality_flags,
    }
    if resource_url is not None:
        record["resource_url"] = resource_url
    if station_metadata_url is not None:
        record["station_metadata_url"] = station_metadata_url
    _assign_float(record, "ground_far_m", _first_value(item, "groundFar", "ground_far_m"))
    _assign_float(record, "voltage", _first_value(item, "voltage"))
    if metadata is not None:
        for key in ("district", "basin", "longitude", "latitude", "geometry"):
            if key in metadata:
                record[key] = metadata[key]
    return record


def _parse_pump_station_record(
    item: Mapping[str, Any],
    *,
    source_url: str,
    fetched_at: datetime,
    resource_url: str | None,
    stale_after_minutes: int,
) -> Mapping[str, Any] | None:
    station_id = _first_text(item, "stn_id", "station_id")
    station_name = _first_text(item, "stn_name", "station_name")
    observed_at = _parse_taipei_spaced_time(_first_value(item, "obs_time", "observed_at"))
    outer_level_m = optional_float(_first_value(item, "outer_value", "water_level_m"))
    if station_id is None or station_name is None or observed_at is None or outer_level_m is None:
        return None

    longitude = optional_float(_first_value(item, "lon", "longitude"))
    latitude = optional_float(_first_value(item, "lat", "latitude"))
    has_coordinates = (
        longitude is not None
        and latitude is not None
        and _valid_taiwan_point(longitude, latitude)
    )
    quality_flags = {
        "station_metadata_missing": False,
        "missing_station_coordinates": not has_coordinates,
        "stale_observation": _is_stale(
            observed_at,
            fetched_at=fetched_at,
            stale_after_minutes=stale_after_minutes,
        ),
    }
    record: dict[str, Any] = {
        "station_id": station_id,
        "station_name": station_name,
        "observed_at": observed_at.isoformat(),
        "water_level_m": outer_level_m,
        "source_url": source_url,
        "location_text": station_name,
        "authority": "臺北市政府工務局水利工程處",
        "attribution": TAIPEI_ATTRIBUTION,
        "confidence": _confidence(quality_flags),
        "quality_flags": quality_flags,
    }
    if resource_url is not None:
        record["resource_url"] = resource_url
    _assign_float(record, "inner_water_level_m", _first_value(item, "inner_value"))
    _assign_float(
        record,
        "max_allowable_water_level_m",
        _first_value(item, "max_allowable_water_level"),
    )
    _assign_text(record, "pump_status", _first_text(item, "pumb_status"))
    _assign_text(record, "door_status", _first_text(item, "door_status"))
    _assign_int(record, "pump_count", _first_value(item, "pumb_num"))
    _assign_int(record, "door_count", _first_value(item, "door_num"))
    if has_coordinates:
        record["longitude"] = longitude
        record["latitude"] = latitude
        record["geometry"] = {"type": "Point", "coordinates": [longitude, latitude]}
    return record


def _normalize_taipei_water_level_record(
    source: TaipeiWaterLevelSource,
    raw_item: RawSourceItem,
) -> NormalizedEvidence | None:
    payload = raw_item.payload
    if _has_blocking_quality_flags(payload.get("quality_flags")):
        return None

    station_name = optional_str(payload.get("station_name"))
    observed_at = parse_datetime(payload.get("observed_at"))
    water_level_m = optional_float(payload.get("water_level_m"))
    if station_name is None or observed_at is None or water_level_m is None:
        return None

    summary = (
        f"{source.metadata.display_name} 觀測：{water_level_m:.2f} "
        f"公尺（{station_name}）"
    )
    tags = [
        "official",
        "local_taipei",
        source.source_tag,
        *_quality_flag_tags(payload.get("quality_flags")),
    ]
    return NormalizedEvidence(
        evidence_id=stable_evidence_id(source.metadata.key, raw_item.source_id),
        adapter_key=source.metadata.key,
        source_family=source.metadata.family,
        event_type=EventType.WATER_LEVEL,
        source_id=raw_item.source_id,
        source_url=raw_item.source_url,
        source_title=f"{source.metadata.display_name}：{station_name}",
        source_timestamp=observed_at,
        fetched_at=raw_item.fetched_at,
        summary=summary,
        location_text=optional_str(payload.get("location_text")) or station_name,
        confidence=float(payload.get("confidence", 0.84)),
        status=IngestionStatus.NORMALIZED,
        attribution=optional_str(payload.get("attribution")) or TAIPEI_ATTRIBUTION,
        tags=tuple(dict.fromkeys(tags)),
    )


def _normalize_taipei_pump_station_record(
    metadata: AdapterMetadata,
    raw_item: RawSourceItem,
) -> NormalizedEvidence | None:
    payload = raw_item.payload
    if _has_blocking_quality_flags(payload.get("quality_flags")):
        return None

    station_name = optional_str(payload.get("station_name"))
    observed_at = parse_datetime(payload.get("observed_at"))
    water_level_m = optional_float(payload.get("water_level_m"))
    if station_name is None or observed_at is None or water_level_m is None:
        return None

    max_level_m = optional_float(payload.get("max_allowable_water_level_m"))
    summary = f"{metadata.display_name} 外水位：{water_level_m:.2f} 公尺（{station_name}）"
    tags = [
        "official",
        "local_taipei",
        "pump_station",
        "outer_water_level",
        *_quality_flag_tags(payload.get("quality_flags")),
    ]
    if max_level_m is not None:
        gap = max_level_m - water_level_m
        summary = f"{summary}；距允許水位 {gap:.2f} 公尺"
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
        attribution=optional_str(payload.get("attribution")) or TAIPEI_ATTRIBUTION,
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


def _payload_items(payload: object, *, label: str) -> Iterable[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, Mapping):
        for key in ("data", "Data", "records", "value"):
            items = payload.get(key)
            if isinstance(items, list):
                return items
    raise TaipeiWaterPayloadError(f"{label} payload is missing a data list")


def _parse_taipei_compact_time(value: object) -> datetime | None:
    text = optional_str(value)
    if text is None:
        return None
    try:
        parsed = datetime.strptime(text, "%Y%m%d%H%M")
    except ValueError:
        return None
    return parsed.replace(tzinfo=TAIPEI_LOCAL_TZ).astimezone(UTC)


def _parse_taipei_spaced_time(value: object) -> datetime | None:
    text = optional_str(value)
    if text is None:
        return None
    parsed = parse_datetime(text)
    if parsed is None:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=TAIPEI_LOCAL_TZ)
    return parsed.astimezone(UTC)


def _quality_flags(
    *,
    metadata: Mapping[str, Any] | None,
    observed_at: datetime,
    fetched_at: datetime,
    stale_after_minutes: int,
) -> dict[str, bool]:
    return {
        "station_metadata_missing": metadata is None,
        "missing_station_coordinates": "geometry" not in (metadata or {}),
        "stale_observation": _is_stale(
            observed_at,
            fetched_at=fetched_at,
            stale_after_minutes=stale_after_minutes,
        ),
    }


def _is_stale(
    observed_at: datetime,
    *,
    fetched_at: datetime,
    stale_after_minutes: int,
) -> bool:
    return observed_at < fetched_at - timedelta(minutes=stale_after_minutes)


def _has_blocking_quality_flags(value: object) -> bool:
    return isinstance(value, Mapping) and (
        value.get("missing_station_coordinates") is True
        or value.get("stale_observation") is True
    )


def _location_text(metadata: Mapping[str, Any] | None, station_name: str) -> str:
    if metadata is None:
        return station_name
    district = optional_str(metadata.get("district"))
    basin = optional_str(metadata.get("basin"))
    return " ".join(part for part in (basin, district, station_name) if part)


def _source_id(record: Mapping[str, Any]) -> str:
    return f"{record['station_id']}:{record['observed_at']}"


def _station_lookup_key(value: object) -> str:
    text = str(value).strip().casefold()
    if text.isdigit():
        return str(int(text))
    return text


def _valid_taiwan_point(longitude: float, latitude: float) -> bool:
    return 118.0 <= longitude <= 123.5 and 21.0 <= latitude <= 26.5


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


def _metadata_text(metadata: Mapping[str, Any] | None, key: str) -> str | None:
    if metadata is None:
        return None
    return optional_str(metadata.get(key))


def _assign_text(record: dict[str, Any], key: str, value: str | None) -> None:
    if value is not None:
        record[key] = value


def _assign_float(record: dict[str, Any], key: str, value: object) -> None:
    parsed = optional_float(value)
    if parsed is not None:
        record[key] = parsed


def _assign_int(record: dict[str, Any], key: str, value: object) -> None:
    parsed = optional_float(value)
    if parsed is not None:
        record[key] = int(parsed)


def _confidence(quality_flags: Mapping[str, bool]) -> float:
    confidence = 0.84
    if quality_flags.get("missing_station_coordinates"):
        confidence -= 0.14
    if quality_flags.get("station_metadata_missing"):
        confidence -= 0.08
    if quality_flags.get("stale_observation"):
        confidence -= 0.25
    return max(0.4, round(confidence, 2))


def _quality_flag_tags(value: object) -> tuple[str, ...]:
    if not isinstance(value, Mapping):
        return ()
    return tuple(str(key) for key, enabled in value.items() if enabled is True)


def _format_decimal(value: float) -> str:
    formatted = format(Decimal(str(value)).normalize(), "f")
    return formatted.rstrip("0").rstrip(".")
