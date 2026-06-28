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

NEW_TAIPEI_LOCAL_TZ = timezone(timedelta(hours=8))
DEFAULT_NEW_TAIPEI_WATER_TIMEOUT_SECONDS = 8
NEW_TAIPEI_MAX_FUTURE_SKEW_MINUTES = 15
NEW_TAIPEI_STALE_AFTER_MINUTES = 180
NEW_TAIPEI_ATTRIBUTION = "新北市政府 / 新北市智慧水情監測平台（WaveGIS）"
NEW_TAIPEI_USER_AGENT = "FloodRiskTaiwan/0.1 worker-local-new-taipei-water"
NEW_TAIPEI_DATA_URL = "https://newtaipei.wavegis.com.tw/"
NEW_TAIPEI_API_BASE_URL = "https://newtaipei.wavegis.com.tw/api/javaapi/water_extra_api"
NEW_TAIPEI_WATER_LEVEL_API_URL = (
    f"{NEW_TAIPEI_API_BASE_URL}/flood/getFloodListData?"
    "fields=ascent_rate&filter_ps=true&org_data=ALL&org_id=110&source=ALL&strata=0&"
    "type=radar%2Cwater%2CWT_RR_W%2CWG_RR_W&unit=1"
)
NEW_TAIPEI_FLOOD_SENSOR_API_URL = (
    f"{NEW_TAIPEI_API_BASE_URL}/flood/getFloodListData?"
    "fields=ascent_rate&filter_ps=true&org_data=ALL&org_id=110&source=ALL&strata=0&"
    "type=flood&unit=1"
)
NEW_TAIPEI_RAINFALL_API_URL = (
    f"{NEW_TAIPEI_API_BASE_URL}/rain/getRainFallBaseData?org_id=110&org_data=ALL"
)
NEW_TAIPEI_DRAINAGE_WATER_LEVEL_API_URL = (
    f"{NEW_TAIPEI_API_BASE_URL}/water/getDrainage?org_id=110&org_data=ALL"
)

NEW_TAIPEI_WATER_LEVEL_METADATA = AdapterMetadata(
    key="local.new_taipei.water_level",
    family=SourceFamily.OFFICIAL,
    enabled_by_default=False,
    display_name="New Taipei local water-level adapter",
    data_gov_url=NEW_TAIPEI_DATA_URL,
    resource_url=NEW_TAIPEI_WATER_LEVEL_API_URL,
    update_frequency="New Taipei WaveGIS JSON carries per-station datatime timestamps",
    license="Official public endpoint; explicit open-data license not separately located",
    limitations=(
        "Supplemental local-government water-level source for New Taipei City.",
        "Rows older than the freshness guard or newer than fetched_at are retained raw "
        "but rejected during normalization.",
    ),
)

NEW_TAIPEI_FLOOD_SENSOR_METADATA = AdapterMetadata(
    key="local.new_taipei.flood_sensor",
    family=SourceFamily.OFFICIAL,
    enabled_by_default=False,
    display_name="New Taipei local flood-sensor adapter",
    data_gov_url=NEW_TAIPEI_DATA_URL,
    resource_url=NEW_TAIPEI_FLOOD_SENSOR_API_URL,
    update_frequency="New Taipei WaveGIS JSON carries per-station datatime timestamps",
    license="Official public endpoint; explicit open-data license not separately located",
    limitations=(
        "Supplemental local-government flood-depth source for New Taipei City.",
        "type=flood rows expose water_inner with unit=1; this adapter preserves the raw "
        "row and interprets the value as centimeters, matching the WaveGIS flood source.",
    ),
)

NEW_TAIPEI_RAINFALL_METADATA = AdapterMetadata(
    key="local.new_taipei.rainfall",
    family=SourceFamily.OFFICIAL,
    enabled_by_default=False,
    display_name="New Taipei local rainfall adapter",
    data_gov_url=NEW_TAIPEI_DATA_URL,
    resource_url=NEW_TAIPEI_RAINFALL_API_URL,
    update_frequency="New Taipei rainfall JSON carries per-station datatime timestamps",
    license="Official public endpoint; explicit open-data license not separately located",
    limitations=(
        "Supplemental local-government rainfall source for New Taipei City.",
        "rain is preserved as rainfall_mm and the API window fields are preserved "
        "under their explicit minute/hour durations.",
    ),
)

NEW_TAIPEI_DRAINAGE_WATER_LEVEL_METADATA = AdapterMetadata(
    key="local.new_taipei.drainage_water_level",
    family=SourceFamily.OFFICIAL,
    enabled_by_default=False,
    display_name="New Taipei local drainage water-level adapter",
    data_gov_url=NEW_TAIPEI_DATA_URL,
    resource_url=NEW_TAIPEI_DRAINAGE_WATER_LEVEL_API_URL,
    update_frequency="New Taipei drainage JSON carries per-station datatime timestamps",
    license="Official public endpoint; explicit open-data license not separately located",
    limitations=(
        "Supplemental local-government drainage and sewer water-level source for New Taipei City.",
        "This source provides infrastructure context and should not be treated as a "
        "standalone flood warning.",
    ),
)


class NewTaipeiWaterAdapterError(RuntimeError):
    """Base error for New Taipei local water adapters."""


class NewTaipeiWaterFetchError(NewTaipeiWaterAdapterError):
    """Raised when fetching New Taipei JSON fails."""


class NewTaipeiWaterPayloadError(NewTaipeiWaterAdapterError):
    """Raised when New Taipei JSON cannot be parsed."""


class NewTaipeiWaterLevelApiAdapter:
    metadata = NEW_TAIPEI_WATER_LEVEL_METADATA

    def __init__(
        self,
        *,
        api_url: str | None = None,
        timeout_seconds: int = DEFAULT_NEW_TAIPEI_WATER_TIMEOUT_SECONDS,
        fetched_at: datetime | None = None,
        fetch_json: FetchJson | None = None,
        raw_snapshot_key: str | None = None,
    ) -> None:
        self._api_url = (api_url or NEW_TAIPEI_WATER_LEVEL_API_URL).strip()
        self._timeout_seconds = max(1, timeout_seconds)
        self._fetched_at = fetched_at
        self._fetch_json = fetch_new_taipei_json if fetch_json is None else fetch_json
        self._raw_snapshot_key = raw_snapshot_key

    def fetch(self) -> tuple[RawSourceItem, ...]:
        payload = _fetch_payload(self, self.metadata)
        fetched_at = self._fetched_at or datetime.now(UTC)
        records = parse_new_taipei_water_level_payload(
            payload,
            source_url=NEW_TAIPEI_DATA_URL,
            resource_url=self._api_url,
            fetched_at=fetched_at,
        )
        return _raw_items(records, fetched_at=fetched_at, raw_snapshot_key=self._raw_snapshot_key)

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        return _normalize_water_level_record(self.metadata, raw_item)

    def run(self) -> AdapterRunResult:
        return _run(self)


class NewTaipeiFloodSensorApiAdapter:
    metadata = NEW_TAIPEI_FLOOD_SENSOR_METADATA

    def __init__(
        self,
        *,
        api_url: str | None = None,
        timeout_seconds: int = DEFAULT_NEW_TAIPEI_WATER_TIMEOUT_SECONDS,
        fetched_at: datetime | None = None,
        fetch_json: FetchJson | None = None,
        raw_snapshot_key: str | None = None,
    ) -> None:
        self._api_url = (api_url or NEW_TAIPEI_FLOOD_SENSOR_API_URL).strip()
        self._timeout_seconds = max(1, timeout_seconds)
        self._fetched_at = fetched_at
        self._fetch_json = fetch_new_taipei_json if fetch_json is None else fetch_json
        self._raw_snapshot_key = raw_snapshot_key

    def fetch(self) -> tuple[RawSourceItem, ...]:
        payload = _fetch_payload(self, self.metadata)
        fetched_at = self._fetched_at or datetime.now(UTC)
        records = parse_new_taipei_flood_sensor_payload(
            payload,
            source_url=NEW_TAIPEI_DATA_URL,
            resource_url=self._api_url,
            fetched_at=fetched_at,
        )
        return _raw_items(records, fetched_at=fetched_at, raw_snapshot_key=self._raw_snapshot_key)

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        return _normalize_flood_sensor_record(self.metadata, raw_item)

    def run(self) -> AdapterRunResult:
        return _run(self)


class NewTaipeiRainfallApiAdapter:
    metadata = NEW_TAIPEI_RAINFALL_METADATA

    def __init__(
        self,
        *,
        api_url: str | None = None,
        timeout_seconds: int = DEFAULT_NEW_TAIPEI_WATER_TIMEOUT_SECONDS,
        fetched_at: datetime | None = None,
        fetch_json: FetchJson | None = None,
        raw_snapshot_key: str | None = None,
    ) -> None:
        self._api_url = (api_url or NEW_TAIPEI_RAINFALL_API_URL).strip()
        self._timeout_seconds = max(1, timeout_seconds)
        self._fetched_at = fetched_at
        self._fetch_json = fetch_new_taipei_json if fetch_json is None else fetch_json
        self._raw_snapshot_key = raw_snapshot_key

    def fetch(self) -> tuple[RawSourceItem, ...]:
        payload = _fetch_payload(self, self.metadata)
        fetched_at = self._fetched_at or datetime.now(UTC)
        records = parse_new_taipei_rainfall_payload(
            payload,
            source_url=NEW_TAIPEI_DATA_URL,
            resource_url=self._api_url,
            fetched_at=fetched_at,
        )
        return _raw_items(records, fetched_at=fetched_at, raw_snapshot_key=self._raw_snapshot_key)

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        return _normalize_rainfall_record(self.metadata, raw_item)

    def run(self) -> AdapterRunResult:
        return _run(self)


class NewTaipeiDrainageWaterLevelApiAdapter:
    metadata = NEW_TAIPEI_DRAINAGE_WATER_LEVEL_METADATA

    def __init__(
        self,
        *,
        api_url: str | None = None,
        timeout_seconds: int = DEFAULT_NEW_TAIPEI_WATER_TIMEOUT_SECONDS,
        fetched_at: datetime | None = None,
        fetch_json: FetchJson | None = None,
        raw_snapshot_key: str | None = None,
    ) -> None:
        self._api_url = (api_url or NEW_TAIPEI_DRAINAGE_WATER_LEVEL_API_URL).strip()
        self._timeout_seconds = max(1, timeout_seconds)
        self._fetched_at = fetched_at
        self._fetch_json = fetch_new_taipei_json if fetch_json is None else fetch_json
        self._raw_snapshot_key = raw_snapshot_key

    def fetch(self) -> tuple[RawSourceItem, ...]:
        payload = _fetch_payload(self, self.metadata)
        fetched_at = self._fetched_at or datetime.now(UTC)
        records = parse_new_taipei_drainage_water_level_payload(
            payload,
            source_url=NEW_TAIPEI_DATA_URL,
            resource_url=self._api_url,
            fetched_at=fetched_at,
        )
        return _raw_items(records, fetched_at=fetched_at, raw_snapshot_key=self._raw_snapshot_key)

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        return _normalize_water_level_record(self.metadata, raw_item)

    def run(self) -> AdapterRunResult:
        return _run(self)


def fetch_new_taipei_json(url: str, timeout_seconds: int) -> Any:
    request = Request(
        url,
        headers={"Accept": "application/json", "User-Agent": NEW_TAIPEI_USER_AGENT},
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8-sig"))
    except (HTTPError, URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NewTaipeiWaterFetchError(f"Failed to fetch New Taipei JSON {url}: {exc}") from exc


def parse_new_taipei_water_level_payload(
    payload: object,
    *,
    source_url: str,
    resource_url: str | None = None,
    fetched_at: datetime | None = None,
) -> tuple[Mapping[str, Any], ...]:
    return _parse_water_level_payload(
        payload,
        source_url=source_url,
        resource_url=resource_url,
        fetched_at=fetched_at,
        authority_default="新北市政府",
        signal="water_level",
    )


def parse_new_taipei_drainage_water_level_payload(
    payload: object,
    *,
    source_url: str,
    resource_url: str | None = None,
    fetched_at: datetime | None = None,
) -> tuple[Mapping[str, Any], ...]:
    return _parse_water_level_payload(
        payload,
        source_url=source_url,
        resource_url=resource_url,
        fetched_at=fetched_at,
        authority_default="新北市政府",
        signal="drainage_water_level",
    )


def parse_new_taipei_flood_sensor_payload(
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
        station_id = _first_text(item, "st_no", "station_id")
        station_name = _first_text(item, "st_name", "station_name")
        observed_at = _parse_local_time(_first_value(item, "datatime", "time"))
        flood_depth_cm = optional_float(_first_value(item, "water_inner", "flood_depth_cm"))
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
        record: dict[str, Any] = {
            "station_id": station_id,
            "station_name": station_name,
            "observed_at": observed_at.isoformat(),
            "flood_depth_cm": flood_depth_cm,
            "source_url": source_url,
            "resource_url": resource_url,
            "location_text": _location_text(item, station_name),
            "city": _first_text(item, "city"),
            "town": _first_text(item, "town"),
            "village": _first_text(item, "village"),
            "status_text": _first_text(item, "status"),
            "authority": _first_text(item, "source") or "新北市政府",
            "longitude": longitude,
            "latitude": latitude,
            "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
            "attribution": NEW_TAIPEI_ATTRIBUTION,
            "confidence": 0.82,
            "quality_flags": _quality_flags(observed_at, fetched_at=fetched_at),
        }
        _assign_float(record, "warning_level_cm", _first_value(item, "warn_lv2"))
        _assign_float(record, "red_alert_level_cm", _first_value(item, "warn_lv1"))
        _assign_float(record, "battery_voltage", _first_value(item, "batteryvol"))
        records.append(record)
    return tuple(records)


def parse_new_taipei_rainfall_payload(
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
        station_id = _first_text(item, "st_no", "station_id")
        station_name = _first_text(item, "st_name", "station_name")
        observed_at = _parse_local_time(_first_value(item, "datatime", "time"))
        rainfall_mm = optional_float(_first_value(item, "rain", "rainfall_mm"))
        coordinate = _coordinate(_first_value(item, "lon"), _first_value(item, "lat"))
        if (
            station_id is None
            or station_name is None
            or observed_at is None
            or rainfall_mm is None
            or coordinate is None
        ):
            continue
        if rainfall_mm < 0:
            continue
        longitude, latitude = coordinate
        record: dict[str, Any] = {
            "station_id": station_id,
            "station_name": station_name,
            "observed_at": observed_at.isoformat(),
            "rainfall_mm": rainfall_mm,
            "source_url": source_url,
            "resource_url": resource_url,
            "location_text": _location_text(item, station_name),
            "city": _first_text(item, "city"),
            "town": _first_text(item, "town"),
            "river": _first_text(item, "river"),
            "status_text": _first_text(item, "status"),
            "authority": _first_text(item, "source") or "新北市政府",
            "longitude": longitude,
            "latitude": latitude,
            "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
            "attribution": NEW_TAIPEI_ATTRIBUTION,
            "confidence": 0.82,
            "quality_flags": _quality_flags(observed_at, fetched_at=fetched_at),
        }
        _assign_float(record, "rainfall_mm_10m", _first_value(item, "min_10"))
        _assign_float(record, "rainfall_mm_30m", _first_value(item, "min_30"))
        _assign_float(record, "rainfall_mm_3h", _first_value(item, "hour_3"))
        _assign_float(record, "rainfall_mm_6h", _first_value(item, "hour_6"))
        _assign_float(record, "rainfall_mm_12h", _first_value(item, "hour_12"))
        _assign_float(record, "rainfall_mm_24h", _first_value(item, "hour_24"))
        records.append(record)
    return tuple(records)


def _parse_water_level_payload(
    payload: object,
    *,
    source_url: str,
    resource_url: str | None,
    fetched_at: datetime | None,
    authority_default: str,
    signal: str,
) -> tuple[Mapping[str, Any], ...]:
    records: list[Mapping[str, Any]] = []
    for item in _payload_items(payload):
        if not isinstance(item, Mapping):
            continue
        station_id = _first_text(item, "st_no", "station_id")
        station_name = _first_text(item, "st_name", "station_name")
        observed_at = _parse_local_time(_first_value(item, "datatime", "time"))
        water_level_m = optional_float(_first_value(item, "water_inner", "water_level_m"))
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
            "location_text": _location_text(item, station_name),
            "city": _first_text(item, "city"),
            "town": _first_text(item, "town"),
            "village": _first_text(item, "village"),
            "river": _first_text(item, "river"),
            "basin": _first_text(item, "basin"),
            "status_text": _first_text(item, "status"),
            "authority": _first_text(item, "source") or authority_default,
            "longitude": longitude,
            "latitude": latitude,
            "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
            "attribution": NEW_TAIPEI_ATTRIBUTION,
            "confidence": 0.82,
            "quality_flags": _quality_flags(observed_at, fetched_at=fetched_at),
            "signal": signal,
        }
        _assign_float(record, "warning_level_m", _first_value(item, "warn_lv2"))
        _assign_float(record, "red_alert_level_m", _first_value(item, "warn_lv1"))
        _assign_float(record, "yellow_alert_level_m", _first_value(item, "warn_lv3"))
        _assign_float(record, "battery_voltage", _first_value(item, "batteryvol"))
        _assign_float(record, "ascent_rate_m_per_minute", _first_value(item, "ascent_rate"))
        cctv_url = _first_text(item, "cctv_url", "cctv")
        if cctv_url:
            record["cctv_url"] = cctv_url
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
    if metadata.key == "local.new_taipei.drainage_water_level":
        summary = f"新北地方排水水位觀測：{water_level_m:.2f} 公尺（{station_name}）"
        tags = ["official", "local_new_taipei", "drainage_water_level"]
    else:
        summary = f"新北地方水位觀測：{water_level_m:.2f} 公尺（{station_name}）"
        tags = ["official", "local_new_taipei", "water_level"]
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
    if _has_blocking_quality_flag(payload):
        return None
    if flood_depth_cm == 0:
        summary = f"新北地方淹水感測：無觀測到淹水（0 公分）（{station_name}）"
        depth_tags = ["dry", "no_flooding_observed"]
    elif flood_depth_cm < 3:
        summary = f"新北地方淹水感測：低水深觀測 {_format_depth_cm(flood_depth_cm)} 公分（{station_name}）"
        depth_tags = ["below_flood_threshold", "low_depth_observation"]
    else:
        summary = f"新北地方淹水感測：水深 {_format_depth_cm(flood_depth_cm)} 公分（{station_name}）"
        depth_tags = []
    return _evidence(
        metadata,
        raw_item,
        event_type=EventType.FLOOD_REPORT,
        station_name=station_name,
        observed_at=observed_at,
        summary=summary,
        tags=("official", "local_new_taipei", "flood_sensor", *depth_tags),
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
    if _has_blocking_quality_flag(payload):
        return None
    summary = f"新北地方雨量觀測：{rainfall_mm:.1f} mm（{station_name}）"
    rainfall_24h = optional_float(payload.get("rainfall_mm_24h"))
    if rainfall_24h is not None:
        summary = f"{summary}；24 小時 {rainfall_24h:.1f} mm"
    return _evidence(
        metadata,
        raw_item,
        event_type=EventType.RAINFALL,
        station_name=station_name,
        observed_at=observed_at,
        summary=summary,
        tags=("official", "local_new_taipei", "rainfall"),
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
        attribution=optional_str(payload.get("attribution")) or NEW_TAIPEI_ATTRIBUTION,
        tags=tuple(dict.fromkeys(tags)),
    )


def _fetch_payload(adapter: Any, metadata: AdapterMetadata) -> Any:
    try:
        return adapter._fetch_json(adapter._api_url, adapter._timeout_seconds)
    except NewTaipeiWaterAdapterError:
        raise
    except Exception as exc:
        raise NewTaipeiWaterFetchError(f"{metadata.display_name} fetcher failed: {exc}") from exc


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
        if isinstance(payload.get("data"), list):
            return tuple(payload["data"])
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
        parsed = parsed.replace(tzinfo=NEW_TAIPEI_LOCAL_TZ)
    return parsed.astimezone(UTC)


def _quality_flags(
    observed_at: datetime,
    *,
    fetched_at: datetime | None,
) -> dict[str, bool]:
    if fetched_at is None:
        return {"future_observation": False, "stale_observation": False}
    return {
        "future_observation": observed_at
        > fetched_at + timedelta(minutes=NEW_TAIPEI_MAX_FUTURE_SKEW_MINUTES),
        "stale_observation": observed_at
        < fetched_at - timedelta(minutes=NEW_TAIPEI_STALE_AFTER_MINUTES),
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
        part
        for part in (
            _first_text(row, "city"),
            _first_text(row, "town"),
            _first_text(row, "village"),
            station_name,
        )
        if part
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


def _format_depth_cm(value: float) -> str:
    return f"{value:.0f}" if value.is_integer() else f"{value:.1f}"
