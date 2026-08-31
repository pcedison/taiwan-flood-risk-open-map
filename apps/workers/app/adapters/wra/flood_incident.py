from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from app.adapters._helpers import optional_float, optional_str, parse_datetime, stable_evidence_id
from app.adapters._taiwan_gov_tls import taiwan_gov_open_data_ssl_context
from app.adapters.contracts import (
    AdapterMetadata,
    AdapterRunResult,
    EventType,
    IngestionStatus,
    NormalizedEvidence,
    RawSourceItem,
    SourceFamily,
    SourceRejection,
)

WraFloodIncidentFetchJson = Callable[[str, Mapping[str, str], int], object]

WRA_FLOOD_INCIDENT_API_URL = (
    "https://fhy.wra.gov.tw/OpenApiv3/v2/Disaster/Flooding?$top=100"
)
WRA_FLOOD_INCIDENT_DOCS_URL = "https://fhy.wra.gov.tw/openapiv3"
WRA_FLOOD_INCIDENT_ATTRIBUTION = "Water Resources Agency"
WRA_FLOOD_INCIDENT_USER_AGENT = "FloodRiskTaiwan/0.1 worker-wra-flood-incident"
DEFAULT_WRA_FLOOD_INCIDENT_TIMEOUT_SECONDS = 12
MAX_WRA_FLOOD_INCIDENT_ROWS = 5000
WRA_LOCAL_TZ = timezone(timedelta(hours=8))

WRA_FLOOD_INCIDENT_METADATA = AdapterMetadata(
    key="official.wra.flood_incident",
    family=SourceFamily.OFFICIAL,
    enabled_by_default=False,
    display_name="WRA nationwide reported flood incident adapter",
    resource_url=WRA_FLOOD_INCIDENT_API_URL,
    update_frequency="polled every hosted worker cycle; upstream returns the latest disaster event",
    license="official API contract review required before production activation",
    limitations=(
        "The endpoint returns only the latest disaster event; durable multi-year coverage starts only after scheduled polling is enabled.",
        "Some rows originate from partner agencies, media, or public reports and retain their upstream source codes.",
        "Reported depth has no unit in the published API schema and is never converted or presented as a measured centimetre value.",
    ),
)


class WraFloodIncidentAdapterError(RuntimeError):
    """Base error for WRA nationwide reported flood incidents."""


class WraFloodIncidentConfigurationError(WraFloodIncidentAdapterError):
    """Raised when the protected official endpoint is not safely configured."""


class WraFloodIncidentFetchError(WraFloodIncidentAdapterError):
    """Raised when the official API request fails."""


class WraFloodIncidentPayloadError(WraFloodIncidentAdapterError):
    """Raised when the official API response does not match its documented shape."""


class WraFloodIncidentApiAdapter:
    metadata = WRA_FLOOD_INCIDENT_METADATA

    def __init__(
        self,
        *,
        api_key: str | None,
        api_url: str | None = None,
        timeout_seconds: int = DEFAULT_WRA_FLOOD_INCIDENT_TIMEOUT_SECONDS,
        fetched_at: datetime | None = None,
        fetch_json: WraFloodIncidentFetchJson | None = None,
        raw_snapshot_key: str | None = None,
    ) -> None:
        key = optional_str(api_key)
        if key is None:
            raise WraFloodIncidentConfigurationError(
                "WRA flood incident API key is required; credential value is [REDACTED]"
            )
        self._api_url = _approved_api_url(api_url or WRA_FLOOD_INCIDENT_API_URL)
        self._api_key = key
        self._timeout_seconds = max(1, timeout_seconds)
        self._fetched_at = fetched_at
        self._fetch_json = fetch_json or _fetch_json
        self._raw_snapshot_key = raw_snapshot_key

    def fetch(self) -> tuple[RawSourceItem, ...]:
        headers = {
            "Accept": "application/json",
            "apikey": self._api_key,
            "x-date": datetime.now(UTC).strftime("%a, %d %b %Y %H:%M:%S GMT"),
            "User-Agent": WRA_FLOOD_INCIDENT_USER_AGENT,
        }
        try:
            payload = self._fetch_json(self._api_url, headers, self._timeout_seconds)
        except WraFloodIncidentAdapterError:
            raise
        except Exception as exc:
            raise WraFloodIncidentFetchError(
                "WRA flood incident fetcher failed: [REDACTED]"
            ) from exc

        fetched_at = self._fetched_at or datetime.now(UTC)
        records = parse_wra_flood_incident_payload(payload)
        return tuple(
            RawSourceItem(
                source_id=str(record["incident_id"]),
                source_url=WRA_FLOOD_INCIDENT_DOCS_URL,
                fetched_at=fetched_at,
                payload=record,
                raw_snapshot_key=self._raw_snapshot_key,
            )
            for record in records
        )

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        return _normalize_flood_incident(raw_item)

    def run(self) -> AdapterRunResult:
        fetched = self.fetch()
        normalized: list[NormalizedEvidence] = []
        rejected: list[str] = []
        rejection_details: list[SourceRejection] = []
        for raw_item in fetched:
            evidence = self.normalize(raw_item)
            if evidence is None:
                rejected.append(raw_item.source_id)
                if len(rejection_details) < 256:
                    rejection_details.append(
                        SourceRejection(
                            source_id=raw_item.source_id,
                            reason_code="invalid_incident_fields",
                        )
                    )
            else:
                normalized.append(evidence)
        return AdapterRunResult(
            adapter_key=self.metadata.key,
            fetched=fetched,
            normalized=tuple(normalized),
            rejected=tuple(rejected),
            source_rejections=tuple(rejection_details),
            # This is a historical evidence source, not an active-warning
            # lifecycle. An empty latest-event response must not retire rows.
            no_active_event=False,
        )


def parse_wra_flood_incident_payload(payload: object) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(payload, Mapping):
        raise WraFloodIncidentPayloadError("WRA flood incident payload is not an object")
    city_rows = payload.get("Data")
    if not isinstance(city_rows, list):
        raise WraFloodIncidentPayloadError("WRA flood incident payload is missing Data")

    parsed: list[Mapping[str, Any]] = []
    for city_row in city_rows:
        if not isinstance(city_row, Mapping):
            continue
        city_code = optional_str(city_row.get("CityCode"))
        incidents = city_row.get("DisasterFlooding")
        if incidents is None:
            continue
        if not isinstance(incidents, list):
            raise WraFloodIncidentPayloadError(
                "WRA flood incident city row has a non-list DisasterFlooding field"
            )
        for incident in incidents:
            if not isinstance(incident, Mapping):
                continue
            record = _parse_incident(incident, city_code=city_code)
            if record is not None:
                parsed.append(record)
            if len(parsed) > MAX_WRA_FLOOD_INCIDENT_ROWS:
                raise WraFloodIncidentPayloadError(
                    f"WRA flood incident payload exceeds {MAX_WRA_FLOOD_INCIDENT_ROWS} rows"
                )
    return tuple(parsed)


def _parse_incident(
    incident: Mapping[str, Any],
    *,
    city_code: str | None,
) -> Mapping[str, Any] | None:
    incident_id = optional_str(incident.get("DisasterFloodingID"))
    occurred_at = _parse_wra_datetime(incident.get("Time"))
    if incident_id is None or occurred_at is None:
        return None

    location = optional_str(incident.get("Location"))
    operator_name = optional_str(incident.get("OperatorName"))
    town_code = optional_str(incident.get("TownCode"))
    location_text = location or operator_name or town_code or city_code
    point = incident.get("Point")
    lat: float | None = None
    lng: float | None = None
    if isinstance(point, Mapping):
        lat = optional_float(point.get("Latitude"))
        lng = optional_float(point.get("Longitude"))
        if lat is not None and lng is not None and not (20.0 <= lat <= 27.0 and 118.0 <= lng <= 123.5):
            lat = None
            lng = None

    record: dict[str, Any] = {
        "incident_id": incident_id,
        "occurred_at": occurred_at.isoformat(),
        "location_text": location_text,
        "location": location,
        "operator_name": operator_name,
        "city_code": city_code,
        "town_code": town_code,
        "category_code": optional_str(incident.get("CategoryCode")),
        "source_code": optional_str(incident.get("SourceCode")),
        "case_no": optional_str(incident.get("CaseNo")),
        "incident_type": optional_str(incident.get("Type")),
        "is_receded": _optional_bool(incident.get("IsReceded")),
        "receded_at": (
            parsed.isoformat()
            if (parsed := _parse_wra_datetime(incident.get("RecededDate"))) is not None
            else None
        ),
        "reported_depth": optional_float(incident.get("Depth")),
        "reported_depth_unit": "upstream_schema_unspecified",
        "evidence_scope": "historical",
        "location_precision": "point" if lat is not None and lng is not None else "admin_area",
        "attribution": WRA_FLOOD_INCIDENT_ATTRIBUTION,
        "source_url": WRA_FLOOD_INCIDENT_DOCS_URL,
        "limitations": [
            "水利署 API 僅提供最後事件；本站自啟用排程後逐次保存，不能宣稱已完整回補所有年份。",
            "上游 API schema 未標示 Depth 單位，本站不把該值轉寫為公分或門牌實測深度。",
        ],
    }
    if lat is not None and lng is not None:
        record["latitude"] = lat
        record["longitude"] = lng
        record["geometry"] = {"type": "Point", "coordinates": [lng, lat]}
        record["location_payload"] = {
            "resolution": "official_point",
            "geometry": record["geometry"],
        }
    return record


def _normalize_flood_incident(raw_item: RawSourceItem) -> NormalizedEvidence | None:
    payload = raw_item.payload
    occurred_at = parse_datetime(payload.get("occurred_at"))
    location_text = optional_str(payload.get("location_text"))
    if occurred_at is None or location_text is None:
        return None

    depth = optional_float(payload.get("reported_depth"))
    is_receded = payload.get("is_receded")
    status_label = (
        "已退水"
        if is_receded is True
        else "未退水"
        if is_receded is False
        else "退水狀態未提供"
    )
    depth_label = ""
    if depth is not None:
        depth_label = f"；上游回報深度值 {depth:g}（API 未標示單位）"
    source_code = optional_str(payload.get("source_code"))
    category_code = optional_str(payload.get("category_code"))
    confidence = 0.94 if _is_direct_official_category(category_code) else 0.78
    if payload.get("location_precision") != "point":
        confidence = min(confidence, 0.72)

    tags = ["official", "wra", "flood_incident", "historical"]
    tags.append(
        "receded"
        if is_receded is True
        else "not_receded"
        if is_receded is False
        else "recession_unknown"
    )
    if source_code:
        tags.append(f"source_code:{source_code.split(':', 1)[0].strip()}")

    return NormalizedEvidence(
        evidence_id=stable_evidence_id(WRA_FLOOD_INCIDENT_METADATA.key, raw_item.source_id),
        adapter_key=WRA_FLOOD_INCIDENT_METADATA.key,
        source_family=SourceFamily.OFFICIAL,
        event_type=EventType.FLOOD_REPORT,
        source_id=raw_item.source_id,
        source_url=raw_item.source_url,
        source_title=f"水利署淹水災情：{location_text}",
        source_timestamp=occurred_at,
        fetched_at=raw_item.fetched_at,
        summary=f"水利署最後事件淹水災情；{status_label}{depth_label}",
        location_text=location_text,
        confidence=confidence,
        status=IngestionStatus.NORMALIZED,
        attribution=WRA_FLOOD_INCIDENT_ATTRIBUTION,
        tags=tuple(tags),
    )


def _parse_wra_datetime(value: object) -> datetime | None:
    parsed = parse_datetime(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=WRA_LOCAL_TZ)
    return parsed.astimezone(UTC)


def _is_direct_official_category(value: str | None) -> bool:
    if value is None:
        return False
    prefix = value.split(":", 1)[0].strip()
    return prefix not in {"3", "7"}


def _optional_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "1", "yes", "y"}:
            return True
        if normalized in {"false", "0", "no", "n"}:
            return False
    return None


def _approved_api_url(value: str) -> str:
    try:
        parsed = urlparse(value.strip())
        port = parsed.port
    except ValueError as exc:
        raise WraFloodIncidentConfigurationError(
            "WRA flood incident API URL must use the reviewed all-county HTTPS endpoint"
        ) from exc
    query = parse_qs(parsed.query, keep_blank_values=True)
    top_values = query.get("$top", [])
    try:
        top = int(top_values[0]) if len(top_values) == 1 else None
    except ValueError:
        top = None
    if (
        parsed.scheme != "https"
        or parsed.hostname != "fhy.wra.gov.tw"
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or parsed.path.rstrip("/") != "/OpenApiv3/v2/Disaster/Flooding"
        or parsed.fragment
        or set(query) != {"$top"}
        or top is None
        or not 22 <= top <= 5000
    ):
        raise WraFloodIncidentConfigurationError(
            "WRA flood incident API URL must use the reviewed all-county HTTPS endpoint"
        )
    return value.strip()


def _fetch_json(url: str, headers: Mapping[str, str], timeout_seconds: int) -> object:
    request = Request(url, headers=dict(headers), method="GET")
    try:
        with urlopen(
            request,
            timeout=timeout_seconds,
            context=taiwan_gov_open_data_ssl_context(),
        ) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise WraFloodIncidentFetchError(
            f"WRA flood incident API returned HTTP {exc.code}"
        ) from exc
    except (URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WraFloodIncidentFetchError("WRA flood incident API request failed") from exc
