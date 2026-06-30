from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from app.adapters._helpers import optional_str, parse_observed_at_utc, stable_evidence_id
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


FetchJson = Callable[[str, int], object]
FetchText = Callable[[str, int], str]

NCDR_CAP_API_URL = "https://alerts.ncdr.nat.gov.tw/RssAtomFeed.ashx"
DEFAULT_NCDR_CAP_TIMEOUT_SECONDS = 8
NCDR_CAP_ATTRIBUTION = "National Science and Technology Center for Disaster Reduction"
NCDR_CAP_USER_AGENT = "FloodRiskTaiwan/0.1 worker-ncdr-cap"
NCDR_CAP_METADATA = AdapterMetadata(
    key="official.ncdr.cap",
    family=SourceFamily.OFFICIAL,
    enabled_by_default=False,
    display_name="NCDR CAP alert adapter",
    resource_url=NCDR_CAP_API_URL,
    update_frequency="NCDR Atom feed updates approximately every minute",
    license="Government Open Data License, version 1.0",
    limitations=(
        "CAP alerts can be area-level only and may include coarse areaDesc or geocode without a precise point.",
        "Fallback centroids are inferred and should not be treated as precise alert coordinates.",
    ),
)

_FLOOD_KEYWORDS = ("淹水", "水災", "豪雨", "大雨", "flood", "heavy rain")
_AREA_CENTROIDS = {
    "taiwan": (120.9605, 23.6978),
    "台灣": (120.9605, 23.6978),
    "臺灣": (120.9605, 23.6978),
    "tainan": (120.2270, 22.9999),
    "tainan city": (120.2270, 22.9999),
    "台南市": (120.2270, 22.9999),
    "臺南市": (120.2270, 22.9999),
    "kaohsiung": (120.3014, 22.6273),
    "kaohsiung city": (120.3014, 22.6273),
    "高雄市": (120.3014, 22.6273),
}


class NcdrCapAlertAdapterError(RuntimeError):
    """Base error for NCDR CAP adapter failures."""


class NcdrCapAlertFetchError(NcdrCapAlertAdapterError):
    """Raised when fetching NCDR CAP payloads fails."""


class NcdrCapAlertPayloadError(NcdrCapAlertAdapterError):
    """Raised when the NCDR CAP payload shape is not parseable."""


class NcdrCapAlertAdapter:
    metadata = NCDR_CAP_METADATA

    def __init__(
        self,
        *,
        api_url: str | None = None,
        timeout_seconds: int = DEFAULT_NCDR_CAP_TIMEOUT_SECONDS,
        fetched_at: datetime | None = None,
        payload: object | None = None,
        fetch_json: FetchJson | None = None,
        fetch_text: FetchText | None = None,
        raw_snapshot_key: str | None = None,
    ) -> None:
        self._api_url = (api_url or NCDR_CAP_API_URL).strip()
        self._timeout_seconds = max(1, timeout_seconds)
        self._fetched_at = fetched_at
        self._payload = payload
        self._fetch_json = fetch_json
        self._fetch_text = fetch_text or _fetch_text
        self._raw_snapshot_key = raw_snapshot_key

    def fetch(self) -> tuple[RawSourceItem, ...]:
        parsed_records = parse_ncdr_cap_payload(
            self._resolve_payload(),
            source_url=self._api_url,
        )
        fetched_at = self._fetched_at or datetime.now(UTC)
        prepared_records = tuple(_prepare_record(record, fetched_at=fetched_at) for record in parsed_records)
        return tuple(
            RawSourceItem(
                source_id=str(record["identifier"]),
                source_url=str(record["source_url"]),
                fetched_at=fetched_at,
                payload=record,
                raw_snapshot_key=self._raw_snapshot_key,
            )
            for record in prepared_records
        )

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        return _normalize_cap_alert(self.metadata, raw_item)

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

    def _resolve_payload(self) -> object:
        if self._payload is not None:
            return self._payload
        if self._fetch_json is not None:
            try:
                payload = self._fetch_json(self._api_url, self._timeout_seconds)
            except NcdrCapAlertAdapterError:
                raise
            except Exception as exc:
                raise NcdrCapAlertFetchError(f"NCDR CAP JSON fetcher failed: {exc}") from exc
            if isinstance(payload, (Mapping, list, str)):
                return payload
            raise NcdrCapAlertPayloadError("NCDR CAP JSON fetcher returned an unsupported payload")
        try:
            return self._fetch_text(self._api_url, self._timeout_seconds)
        except NcdrCapAlertAdapterError:
            raise
        except Exception as exc:
            raise NcdrCapAlertFetchError(f"NCDR CAP text fetcher failed: {exc}") from exc


def parse_ncdr_cap_payload(
    payload: object,
    *,
    source_url: str,
) -> tuple[Mapping[str, Any], ...]:
    if isinstance(payload, str):
        parsed_json = _parse_json_string_payload(payload)
        if parsed_json is not None:
            return parse_ncdr_cap_payload(parsed_json, source_url=source_url)
        return _parse_xml_payload(payload, source_url=source_url)
    if isinstance(payload, list):
        return tuple(
            record
            for item in payload
            if isinstance(item, Mapping)
            for record in (_parse_json_alert(item, source_url=source_url),)
            if record is not None
        )
    if not isinstance(payload, Mapping):
        raise NcdrCapAlertPayloadError("NCDR CAP payload must be XML text, list, or object")

    if _looks_like_alert(payload):
        record = _parse_json_alert(payload, source_url=source_url)
        return (record,) if record is not None else ()

    for key in ("alerts", "items", "entries", "feed", "records", "data"):
        items = payload.get(key)
        if isinstance(items, list):
            return tuple(
                record
                for item in items
                if isinstance(item, Mapping)
                for record in (_parse_json_alert(item, source_url=source_url),)
                if record is not None
            )

    raise NcdrCapAlertPayloadError("NCDR CAP object payload is missing an alert list")


def _parse_json_string_payload(payload: str) -> object | None:
    text = payload.lstrip()
    if not text or text[0] not in ("{", "["):
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _prepare_record(
    record: Mapping[str, Any],
    *,
    fetched_at: datetime,
) -> Mapping[str, Any]:
    prepared = dict(record)
    expires_at = parse_observed_at_utc(prepared.get("expires"))
    prepared["expired"] = expires_at is not None and expires_at < fetched_at
    station_id = _station_id(prepared)
    if station_id is not None:
        prepared["station_id"] = station_id

    geometry, location_inferred = _resolve_geometry(prepared)
    if geometry is not None:
        prepared["geometry"] = geometry
    prepared["quality_flags"] = {"location_inferred": location_inferred}
    return prepared


def _normalize_cap_alert(
    metadata: AdapterMetadata,
    raw_item: RawSourceItem,
) -> NormalizedEvidence | None:
    payload = raw_item.payload
    identifier = optional_str(payload.get("identifier"))
    sent_at = parse_observed_at_utc(payload.get("sent"))
    effective_at = parse_observed_at_utc(payload.get("effective"))
    expires_at = parse_observed_at_utc(payload.get("expires"))
    area_desc = optional_str(payload.get("areaDesc"))
    summary_text = " ".join(
        part
        for part in (
            optional_str(payload.get("event")),
            optional_str(payload.get("headline")),
            optional_str(payload.get("description")),
            area_desc,
        )
        if part
    )
    if (
        identifier is None
        or sent_at is None
        or effective_at is None
        or expires_at is None
        or area_desc is None
        or expires_at < raw_item.fetched_at
        or not _is_flood_related(summary_text)
    ):
        return None

    location_inferred = bool(_quality_flags(payload).get("location_inferred"))
    summary = f"NCDR CAP flood warning affecting {area_desc}"
    if location_inferred:
        summary = f"{summary}; location inferred from CAP area metadata"

    headline = optional_str(payload.get("headline")) or optional_str(payload.get("event")) or identifier
    tags = ["official", "ncdr", "cap", "flood_warning"]
    if location_inferred:
        tags.append("location_inferred")

    return NormalizedEvidence(
        evidence_id=stable_evidence_id(metadata.key, raw_item.source_id),
        adapter_key=metadata.key,
        source_family=metadata.family,
        event_type=EventType.FLOOD_WARNING,
        source_id=identifier,
        source_url=raw_item.source_url,
        source_title=f"NCDR CAP alert: {headline}",
        source_timestamp=effective_at,
        fetched_at=raw_item.fetched_at,
        summary=summary,
        location_text=area_desc,
        confidence=0.95,
        status=IngestionStatus.NORMALIZED,
        attribution=NCDR_CAP_ATTRIBUTION,
        tags=tuple(tags),
    )


def _parse_xml_payload(xml_text: str, *, source_url: str) -> tuple[Mapping[str, Any], ...]:
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as exc:
        raise NcdrCapAlertPayloadError(f"NCDR CAP XML could not be parsed: {exc}") from exc

    root_name = _local_name(root.tag)
    if root_name == "alert":
        record = _parse_xml_alert(root, source_url=source_url)
        return (record,) if record is not None else ()
    if root_name != "feed":
        raise NcdrCapAlertPayloadError("NCDR CAP XML root must be an Atom feed or CAP alert")

    parsed: list[Mapping[str, Any]] = []
    for entry in root.findall("{http://www.w3.org/2005/Atom}entry"):
        record = _parse_xml_entry(entry, source_url=source_url)
        if record is not None:
            parsed.append(record)
    return tuple(parsed)


def _parse_xml_entry(entry: ElementTree.Element, *, source_url: str) -> Mapping[str, Any] | None:
    embedded_alert = next(
        (element for element in entry.iter() if element is not entry and _local_name(element.tag) == "alert"),
        None,
    )
    if embedded_alert is not None:
        return _parse_xml_alert(embedded_alert, source_url=source_url)

    return _build_record(
        identifier=_first_xml_text(entry, "identifier") or _first_xml_text(entry, "id"),
        sender=_first_xml_text(entry, "sender"),
        sent=_first_xml_text(entry, "sent") or _first_xml_text(entry, "updated"),
        effective=_first_xml_text(entry, "effective"),
        expires=_first_xml_text(entry, "expires"),
        status=_first_xml_text(entry, "status"),
        msg_type=_first_xml_text(entry, "msgType"),
        scope=_first_xml_text(entry, "scope"),
        severity=_first_xml_text(entry, "severity"),
        certainty=_first_xml_text(entry, "certainty"),
        urgency=_first_xml_text(entry, "urgency"),
        event=_first_xml_text(entry, "event"),
        headline=_first_xml_text(entry, "headline") or _first_xml_text(entry, "title"),
        description=_first_xml_text(entry, "description") or _first_xml_text(entry, "summary"),
        area_desc=_first_xml_text(entry, "areaDesc"),
        polygon=_first_xml_text(entry, "polygon"),
        circle=_first_xml_text(entry, "circle"),
        geocode=_parse_xml_geocodes(entry),
        source_url=source_url,
    )


def _parse_xml_alert(alert: ElementTree.Element, *, source_url: str) -> Mapping[str, Any] | None:
    info = next((child for child in alert if _local_name(child.tag) == "info"), None)
    area = None
    if info is not None:
        area = next((child for child in info if _local_name(child.tag) == "area"), None)

    return _build_record(
        identifier=_first_xml_text(alert, "identifier"),
        sender=_first_xml_text(alert, "sender"),
        sent=_first_xml_text(alert, "sent"),
        effective=_first_xml_text(info, "effective"),
        expires=_first_xml_text(info, "expires"),
        status=_first_xml_text(alert, "status"),
        msg_type=_first_xml_text(alert, "msgType"),
        scope=_first_xml_text(alert, "scope"),
        severity=_first_xml_text(info, "severity"),
        certainty=_first_xml_text(info, "certainty"),
        urgency=_first_xml_text(info, "urgency"),
        event=_first_xml_text(info, "event"),
        headline=_first_xml_text(info, "headline"),
        description=_first_xml_text(info, "description"),
        area_desc=_first_xml_text(area, "areaDesc"),
        polygon=_first_xml_text(area, "polygon"),
        circle=_first_xml_text(area, "circle"),
        geocode=_parse_xml_geocodes(area),
        source_url=source_url,
    )


def _parse_json_alert(item: Mapping[str, Any], *, source_url: str) -> Mapping[str, Any] | None:
    info = _first_info(item)
    area = _first_area(info)
    if _looks_like_alert(info):
        area = _first_area(info)

    geocode = _parse_json_geocodes(area)
    return _build_record(
        identifier=_text(item, "identifier", "id"),
        sender=_text(item, "sender"),
        sent=_text(item, "sent", "updated"),
        effective=_text(info, "effective"),
        expires=_text(info, "expires"),
        status=_text(item, "status"),
        msg_type=_text(item, "msgType"),
        scope=_text(item, "scope"),
        severity=_text(info, "severity"),
        certainty=_text(info, "certainty"),
        urgency=_text(info, "urgency"),
        event=_text(info, "event"),
        headline=_text(info, "headline", "title"),
        description=_text(info, "description", "summary"),
        area_desc=_text(area, "areaDesc", "area_desc"),
        polygon=_text(area, "polygon"),
        circle=_text(area, "circle"),
        geocode=geocode,
        source_url=optional_str(_text(item, "source_url")) or source_url,
    )


def _build_record(
    *,
    identifier: str | None,
    sender: str | None,
    sent: str | None,
    effective: str | None,
    expires: str | None,
    status: str | None,
    msg_type: str | None,
    scope: str | None,
    severity: str | None,
    certainty: str | None,
    urgency: str | None,
    event: str | None,
    headline: str | None,
    description: str | None,
    area_desc: str | None,
    polygon: str | None,
    circle: str | None,
    geocode: tuple[Mapping[str, str], ...],
    source_url: str,
) -> Mapping[str, Any] | None:
    if identifier is None:
        return None
    return {
        "identifier": identifier,
        "sender": sender,
        "sent": sent,
        "effective": effective or sent,
        "expires": expires,
        "status": status,
        "msgType": msg_type,
        "scope": scope,
        "severity": severity,
        "certainty": certainty,
        "urgency": urgency,
        "event": event,
        "headline": headline,
        "description": description,
        "areaDesc": area_desc,
        "polygon": polygon,
        "circle": circle,
        "geocode": list(geocode),
        "source_url": source_url,
    }


def _resolve_geometry(record: Mapping[str, Any]) -> tuple[Mapping[str, Any] | None, bool]:
    polygon = optional_str(record.get("polygon"))
    if polygon:
        centroid = _polygon_centroid(polygon)
        if centroid is not None:
            return _point_geometry(*centroid), False

    circle = optional_str(record.get("circle"))
    if circle:
        center = _circle_center(circle)
        if center is not None:
            return _point_geometry(*center), False

    coordinate = _coordinate_center(record.get("coordinate"))
    if coordinate is not None:
        return _point_geometry(*coordinate), False

    area_desc = optional_str(record.get("areaDesc"))
    if area_desc is None:
        return None, True
    return _point_geometry(*_fallback_centroid(area_desc)), True


def _station_id(record: Mapping[str, Any]) -> str | None:
    geocode = record.get("geocode")
    if isinstance(geocode, list):
        for item in geocode:
            if not isinstance(item, Mapping):
                continue
            value = optional_str(item.get("value"))
            if value:
                return value
    return optional_str(record.get("identifier"))


def _quality_flags(record: Mapping[str, Any]) -> Mapping[str, Any]:
    quality_flags = record.get("quality_flags")
    if isinstance(quality_flags, Mapping):
        return quality_flags
    return {}


def _is_flood_related(text: str) -> bool:
    haystack = text.casefold()
    return any(keyword in haystack for keyword in _FLOOD_KEYWORDS)


def _fallback_centroid(area_desc: str) -> tuple[float, float]:
    normalized = area_desc.casefold()
    for key, centroid in _AREA_CENTROIDS.items():
        if key in normalized:
            return centroid
    return _AREA_CENTROIDS["taiwan"]


def _point_geometry(longitude: float, latitude: float) -> Mapping[str, Any]:
    return {"type": "Point", "coordinates": [round(longitude, 6), round(latitude, 6)]}


def _polygon_centroid(polygon: str) -> tuple[float, float] | None:
    coordinates: list[tuple[float, float]] = []
    for part in polygon.split():
        lat_lon = part.split(",")
        if len(lat_lon) != 2:
            continue
        try:
            lat = float(lat_lon[0])
            lon = float(lat_lon[1])
        except ValueError:
            continue
        coordinates.append((lon, lat))

    if len(coordinates) >= 2 and coordinates[0] == coordinates[-1]:
        coordinates.pop()
    if not coordinates:
        return None
    lon = sum(point[0] for point in coordinates) / len(coordinates)
    lat = sum(point[1] for point in coordinates) / len(coordinates)
    return lon, lat


def _circle_center(circle: str) -> tuple[float, float] | None:
    parts = circle.split()
    if not parts:
        return None
    lat_lon = parts[0].split(",")
    if len(lat_lon) != 2:
        return None
    try:
        lat = float(lat_lon[0])
        lon = float(lat_lon[1])
    except ValueError:
        return None
    return lon, lat


def _coordinate_center(value: object) -> tuple[float, float] | None:
    if isinstance(value, Mapping):
        longitude = _float(value.get("longitude")) or _float(value.get("lon")) or _float(value.get("x"))
        latitude = _float(value.get("latitude")) or _float(value.get("lat")) or _float(value.get("y"))
        if longitude is not None and latitude is not None:
            return longitude, latitude
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        longitude = _float(value[0])
        latitude = _float(value[1])
        if longitude is not None and latitude is not None:
            return longitude, latitude
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(",")]
        if len(parts) >= 2:
            longitude = _float(parts[0])
            latitude = _float(parts[1])
            if longitude is not None and latitude is not None:
                return longitude, latitude
    return None


def _float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _first_info(item: Mapping[str, Any]) -> Mapping[str, Any]:
    info = item.get("info")
    if isinstance(info, list):
        for entry in info:
            if isinstance(entry, Mapping):
                return entry
    if isinstance(info, Mapping):
        return info
    return item


def _first_area(item: Mapping[str, Any]) -> Mapping[str, Any]:
    area = item.get("area")
    if isinstance(area, list):
        for entry in area:
            if isinstance(entry, Mapping):
                return entry
    if isinstance(area, Mapping):
        return area
    return item


def _parse_json_geocodes(area: Mapping[str, Any]) -> tuple[Mapping[str, str], ...]:
    geocode = area.get("geocode")
    if not isinstance(geocode, list):
        return ()
    parsed: list[Mapping[str, str]] = []
    for item in geocode:
        if not isinstance(item, Mapping):
            continue
        value_name = optional_str(item.get("valueName")) or optional_str(item.get("name"))
        value = optional_str(item.get("value"))
        if value_name and value:
            parsed.append({"valueName": value_name, "value": value})
    return tuple(parsed)


def _parse_xml_geocodes(element: ElementTree.Element | None) -> tuple[Mapping[str, str], ...]:
    if element is None:
        return ()
    parsed: list[Mapping[str, str]] = []
    for geocode in element.iter():
        if _local_name(geocode.tag) != "geocode":
            continue
        value_name = _first_xml_text(geocode, "valueName")
        value = _first_xml_text(geocode, "value")
        if value_name and value:
            parsed.append({"valueName": value_name, "value": value})
    return tuple(parsed)


def _first_xml_text(element: ElementTree.Element | None, local_name: str) -> str | None:
    if element is None:
        return None
    for child in element.iter():
        if _local_name(child.tag) == local_name:
            return optional_str(child.text)
    return None


def _text(item: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = optional_str(item.get(key))
        if value is not None:
            return value
    return None


def _looks_like_alert(item: Mapping[str, Any]) -> bool:
    return any(key in item for key in ("identifier", "info", "msgType", "status"))


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _fetch_text(url: str, timeout_seconds: int) -> str:
    request = Request(
        url,
        headers={
            "Accept": "application/atom+xml, application/xml, text/xml, application/json",
            "User-Agent": NCDR_CAP_USER_AGENT,
        },
        method="GET",
    )
    try:
        with urlopen(
            request,
            timeout=timeout_seconds,
            context=taiwan_gov_open_data_ssl_context(),
        ) as response:
            body = response.read()
    except HTTPError as exc:
        raise NcdrCapAlertFetchError(f"NCDR CAP returned HTTP {exc.code}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise NcdrCapAlertFetchError(f"NCDR CAP request failed: {exc}") from exc

    content_type = response.headers.get("Content-Type", "")
    if "json" in content_type:
        try:
            payload: object = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise NcdrCapAlertPayloadError(f"NCDR CAP JSON could not be parsed: {exc}") from exc
        return json.dumps(payload)

    try:
        return body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise NcdrCapAlertPayloadError(f"NCDR CAP response could not be decoded: {exc}") from exc
