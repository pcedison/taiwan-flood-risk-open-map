"""Bounded WRA warning KML ingestion as non-scoring official context.

The module deliberately keeps its own URL policy, transport bounds, and parser
limits.  It never reuses or widens the historical-flood adapter's policy.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from http.client import HTTPMessage
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import (
    HTTPRedirectHandler,
    HTTPSHandler,
    Request,
    build_opener,
)
from xml.etree.ElementTree import Element

from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException

from app.adapters._helpers import optional_str, stable_evidence_id
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

WraFloodWarningFetchJson = Callable[[str, int], object]
WraFloodWarningFetchText = Callable[[str, int], str]

WRA_FLOOD_WARNING_KML_URLS = (
    "https://fhy.wra.gov.tw/pub_web_2011/kml/KmlShare/NewstFloodWarm.kml",
    "https://fhy.wra.gov.tw/pub_web_2011/kml/KmlShare/NewstWaterWarm.kml",
    "https://fhy.wra.gov.tw/pub_web_2011/kml/KmlShare/NewstReservoirWarm.kml",
    "https://fhy.wra.gov.tw/pub_web_2011/kml/KmlShare/AnnounceFlood.kml",
)
WRA_FLOOD_WARNING_INDEX_URL = (
    "https://opendata.wra.gov.tw/api/v2/"
    "301c0b62-8736-4e03-95ef-55309c1a5e74"
)
_APPROVED_URLS = (*WRA_FLOOD_WARNING_KML_URLS, WRA_FLOOD_WARNING_INDEX_URL)

WRA_FLOOD_WARNING_DATA_GOV_DATASET_ID = "5982"
WRA_FLOOD_WARNING_DATA_GOV_DATASET_IDS = ("5982", "5983", "5984")
WRA_FLOOD_WARNING_DATA_GOV_URL = "https://data.gov.tw/dataset/5982"
WRA_FLOOD_WARNING_ATTRIBUTION = "Water Resources Agency flood warning KML"
WRA_FLOOD_WARNING_USER_AGENT = "FloodRiskTaiwan/0.1 worker-wra-flood-warning"

DEFAULT_WRA_FLOOD_WARNING_TIMEOUT_SECONDS = 8
MAX_WRA_FLOOD_WARNING_METADATA_BYTES = 256 * 1024
MAX_WRA_FLOOD_WARNING_KML_BYTES = 2 * 1024 * 1024
MAX_WRA_FLOOD_WARNING_XML_DEPTH = 32
MAX_WRA_FLOOD_WARNING_XML_ELEMENTS = 20_000
MAX_WRA_FLOOD_WARNING_PLACEMARKS = 2_000
MAX_WRA_FLOOD_WARNING_TOTAL_COORDINATES = 100_000
MAX_WRA_FLOOD_WARNING_NETWORK_LINKS = 4
MAX_WRA_FLOOD_WARNING_GEOMETRY_PARTS = 64
MAX_WRA_FLOOD_WARNING_RETRY_AFTER_SECONDS = 3_600
MAX_WRA_FLOOD_WARNING_AUDITED_REJECTIONS = 256

WRA_FLOOD_WARNING_LOCAL_TZ = timezone(timedelta(hours=8))
_TAIWAN_LONGITUDE_BOUNDS = (117.0, 123.5)
_TAIWAN_LATITUDE_BOUNDS = (20.0, 27.5)

_WARNING_KINDS = {
    "NewstFloodWarm.kml": "flood_warning",
    "NewstWaterWarm.kml": "water_level_warning",
    "NewstReservoirWarm.kml": "reservoir_warning",
    "AnnounceFlood.kml": "announced_flood",
}
_RESOLVED_KEYWORDS = ("解除", "已解除", "解除警戒")

WRA_FLOOD_WARNING_LIMITATIONS = (
    "官方警戒範圍為情境背景，尚未經淹水感測器逐點確認。",
    "警戒發布與解除可能延遲；解除後仍保留為稽核脈絡。",
    "active_fixture_reviewed=false: no reviewed live active-warning capture exists yet.",
)

WRA_FLOOD_WARNING_METADATA = AdapterMetadata(
    key="official.wra.flood_warning",
    family=SourceFamily.OFFICIAL,
    enabled_by_default=False,
    display_name="WRA warning KML context adapter",
    data_gov_dataset_id=WRA_FLOOD_WARNING_DATA_GOV_DATASET_ID,
    data_gov_url=WRA_FLOOD_WARNING_DATA_GOV_URL,
    resource_url=WRA_FLOOD_WARNING_INDEX_URL,
    update_frequency="irregular warning publication; polled per ingestion cycle",
    license="Government Open Data License, version 1.0",
    limitations=WRA_FLOOD_WARNING_LIMITATIONS,
)

_KML_NS = "http://www.opengis.net/kml/2.2"
_KML_ROOT = f"{{{_KML_NS}}}kml"
_KML_DOCUMENT = f"{{{_KML_NS}}}Document"
_KML_FOLDER = f"{{{_KML_NS}}}Folder"
_KML_PLACEMARK = f"{{{_KML_NS}}}Placemark"
_KML_NAME = f"{{{_KML_NS}}}name"
_KML_DESCRIPTION = f"{{{_KML_NS}}}description"
_KML_POINT = f"{{{_KML_NS}}}Point"
_KML_POLYGON = f"{{{_KML_NS}}}Polygon"
_KML_MULTI_GEOMETRY = f"{{{_KML_NS}}}MultiGeometry"
_KML_OUTER_BOUNDARY = f"{{{_KML_NS}}}outerBoundaryIs"
_KML_INNER_BOUNDARY = f"{{{_KML_NS}}}innerBoundaryIs"
_KML_LINEAR_RING = f"{{{_KML_NS}}}LinearRing"
_KML_COORDINATES = f"{{{_KML_NS}}}coordinates"
_KML_TIMESTAMP = f"{{{_KML_NS}}}TimeStamp"
_KML_TIMESPAN = f"{{{_KML_NS}}}TimeSpan"
_KML_WHEN = f"{{{_KML_NS}}}when"
_KML_BEGIN = f"{{{_KML_NS}}}begin"
_KML_END = f"{{{_KML_NS}}}end"
_KML_NETWORK_LINK = f"{{{_KML_NS}}}NetworkLink"
_KML_LINK = f"{{{_KML_NS}}}Link"
_KML_URL = f"{{{_KML_NS}}}Url"
_KML_HREF = f"{{{_KML_NS}}}href"
_KML_CONTAINER_TAGS = {_KML_DOCUMENT, _KML_FOLDER}
_KML_SUPPORTED_GEOMETRY_TAGS = {_KML_POINT, _KML_POLYGON, _KML_MULTI_GEOMETRY}
_UNSUPPORTED_GEOMETRY_LOCAL_NAMES = {
    "LineString",
    "Model",
    "MultiTrack",
    "Track",
}

_FETCH_ERROR_MESSAGE = "WRA flood warning request failed: [REDACTED]"
_PAYLOAD_ERROR_MESSAGE = "WRA flood warning payload was rejected: [REDACTED]"


class WraFloodWarningAdapterError(RuntimeError):
    """Base error for the WRA warning-context adapter."""


class WraFloodWarningFetchError(WraFloodWarningAdapterError):
    """Raised when the bounded index or KML transport fails."""


class WraFloodWarningPayloadError(WraFloodWarningAdapterError):
    """Raised when metadata, a URL, or a KML document violates the contract."""


class WraFloodWarningRateLimitError(WraFloodWarningFetchError):
    def __init__(self, message: str, *, retry_after_seconds: int | None) -> None:
        super().__init__(message)
        self.retry_after_seconds = _bounded_retry_after(retry_after_seconds)


def approved_wra_flood_warning_url(
    value: object,
    *,
    allow_http_upgrade: bool = False,
) -> str:
    """Return one of the exact approved HTTPS constants or fail closed."""

    text = value.strip() if isinstance(value, str) else None
    if not text:
        raise WraFloodWarningPayloadError(_PAYLOAD_ERROR_MESSAGE)
    try:
        parts = urlsplit(text)
        port = parts.port
        username = parts.username
        password = parts.password
        host = (parts.hostname or "").lower()
    except ValueError:
        raise WraFloodWarningPayloadError(_PAYLOAD_ERROR_MESSAGE) from None

    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"}:
        raise WraFloodWarningPayloadError(_PAYLOAD_ERROR_MESSAGE)
    if scheme == "http" and not allow_http_upgrade:
        raise WraFloodWarningPayloadError(_PAYLOAD_ERROR_MESSAGE)
    if username is not None or password is not None:
        raise WraFloodWarningPayloadError(_PAYLOAD_ERROR_MESSAGE)
    if parts.query or parts.fragment or not host:
        raise WraFloodWarningPayloadError(_PAYLOAD_ERROR_MESSAGE)
    if port not in {None, 443 if scheme == "https" else 80}:
        raise WraFloodWarningPayloadError(_PAYLOAD_ERROR_MESSAGE)

    for approved in _APPROVED_URLS:
        approved_parts = urlsplit(approved)
        if host == approved_parts.hostname and parts.path == approved_parts.path:
            return approved
    raise WraFloodWarningPayloadError(_PAYLOAD_ERROR_MESSAGE)


class _WraFloodWarningRedirectHandler(HTTPRedirectHandler):
    """Validate every redirect target before urllib is allowed to follow it."""

    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> Request | None:
        approved_url = approved_wra_flood_warning_url(urljoin(req.full_url, newurl))
        return super().redirect_request(req, fp, code, msg, headers, approved_url)


class WraFloodWarningAdapter:
    metadata = WRA_FLOOD_WARNING_METADATA

    def __init__(
        self,
        *,
        index_url: str | None = None,
        timeout_seconds: int = DEFAULT_WRA_FLOOD_WARNING_TIMEOUT_SECONDS,
        fetched_at: datetime | None = None,
        fetch_json: WraFloodWarningFetchJson | None = None,
        fetch_text: WraFloodWarningFetchText | None = None,
        raw_snapshot_key: str | None = None,
    ) -> None:
        self._index_url = approved_wra_flood_warning_url(
            index_url or WRA_FLOOD_WARNING_INDEX_URL
        )
        self._timeout_seconds = max(1, timeout_seconds)
        self._fetched_at = fetched_at
        self._fetch_json = fetch_json or fetch_wra_flood_warning_json
        self._fetch_text = fetch_text or fetch_wra_flood_warning_text
        self._raw_snapshot_key = raw_snapshot_key

    def fetch(self) -> tuple[RawSourceItem, ...]:
        return self.run().fetched

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        payload = raw_item.payload
        source_timestamp = _parse_aware_utc(payload.get("source_timestamp"))
        if source_timestamp is None:
            return None
        if payload.get("evidence_scope") != "context":
            return None
        if payload.get("location_precision") not in {"point", "polygon"}:
            return None
        warning_kind = optional_str(payload.get("warning_kind"))
        state = optional_str(payload.get("incident_state"))
        if warning_kind is None or state is None:
            return None
        title = optional_str(payload.get("placemark_name"))
        summary = f"水利署警戒圖層（{warning_kind}／{state}）"
        if title:
            summary = f"{summary}：{title}"
        return NormalizedEvidence(
            evidence_id=stable_evidence_id(self.metadata.key, raw_item.source_id),
            adapter_key=self.metadata.key,
            source_family=SourceFamily.OFFICIAL,
            event_type=EventType.STATUS_ONLY,
            source_id=raw_item.source_id,
            source_url=raw_item.source_url,
            source_title=self.metadata.display_name,
            source_timestamp=source_timestamp,
            fetched_at=raw_item.fetched_at,
            summary=summary,
            location_text=title,
            confidence=0.7,
            status=IngestionStatus.NORMALIZED,
            attribution=WRA_FLOOD_WARNING_ATTRIBUTION,
            tags=(
                "official",
                "wra",
                "warning_context",
                "official_reported",
                "status_only",
                warning_kind,
                state,
            ),
        )

    def run(self) -> AdapterRunResult:
        fetched_at = self._resolved_fetched_at()
        index_payload = self._load_index()
        selected_urls = _selected_kml_urls(index_payload)

        fetched: list[RawSourceItem] = []
        rejected: list[str] = []
        rejection_candidates: list[SourceRejection] = []
        seen_urls: set[str] = set()
        seen_source_ids: set[str] = set()
        failures: list[WraFloodWarningAdapterError] = []
        failed_selected_urls: list[str] = []

        for url in selected_urls:
            before = len(failures)
            self._collect_document(
                url,
                network_link_source_url=None,
                fetched_at=fetched_at,
                seen_urls=seen_urls,
                seen_source_ids=seen_source_ids,
                fetched=fetched,
                rejected=rejected,
                rejection_candidates=rejection_candidates,
                failures=failures,
            )
            # A selected resource counts as failed when its own document or any
            # of its one-level NetworkLink targets could not be read safely.
            if len(failures) > before:
                failed_selected_urls.append(url)

        if failed_selected_urls and len(failed_selected_urls) == len(selected_urls):
            raise _aggregate_failure(failures)

        normalized: list[NormalizedEvidence] = []
        for raw in fetched:
            evidence = self.normalize(raw)
            if evidence is None:  # pragma: no cover - defensive
                rejected.append(raw.source_id)
                continue
            normalized.append(evidence)

        source_rejections = tuple(
            sorted(rejection_candidates, key=lambda item: item.source_id)[
                :MAX_WRA_FLOOD_WARNING_AUDITED_REJECTIONS
            ]
        )
        return AdapterRunResult(
            adapter_key=self.metadata.key,
            fetched=tuple(fetched),
            normalized=tuple(normalized),
            rejected=tuple(rejected),
            source_rejections=source_rejections,
            no_active_event=not fetched and not rejected and not failures,
        )

    # ------------------------------------------------------------- internals

    def _resolved_fetched_at(self) -> datetime:
        fetched_at = self._fetched_at or datetime.now(UTC)
        if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
            raise WraFloodWarningPayloadError(_PAYLOAD_ERROR_MESSAGE)
        return fetched_at.astimezone(UTC)

    def _load_index(self) -> object:
        failure: WraFloodWarningAdapterError | None = None
        payload: object = None
        try:
            payload = self._fetch_json(self._index_url, self._timeout_seconds)
        except WraFloodWarningAdapterError as exc:
            failure = exc
        except Exception:  # noqa: BLE001 - sanitize the injected transport boundary
            failure = WraFloodWarningFetchError(_FETCH_ERROR_MESSAGE)
        if failure is not None:
            raise failure
        return payload

    def _read_document(self, url: str) -> str:
        failure: WraFloodWarningAdapterError | None = None
        text: str | None = None
        try:
            text = self._fetch_text(url, self._timeout_seconds)
        except WraFloodWarningAdapterError as exc:
            failure = exc
        except Exception:  # noqa: BLE001 - sanitize the injected transport boundary
            failure = WraFloodWarningFetchError(_FETCH_ERROR_MESSAGE)
        if failure is not None:
            raise failure
        if not isinstance(text, str):
            raise WraFloodWarningPayloadError(_PAYLOAD_ERROR_MESSAGE)
        return text

    def _collect_document(
        self,
        url: str,
        *,
        network_link_source_url: str | None,
        fetched_at: datetime,
        seen_urls: set[str],
        seen_source_ids: set[str],
        fetched: list[RawSourceItem],
        rejected: list[str],
        rejection_candidates: list[SourceRejection],
        failures: list[WraFloodWarningAdapterError],
    ) -> None:
        if url in seen_urls:
            return
        seen_urls.add(url)
        try:
            text = self._read_document(url)
            root = _parse_kml_document(text)
            network_link_urls = _network_link_urls(
                root,
                allow_network_link=network_link_source_url is None,
            )
            records = _placemark_records(
                root,
                source_url=url,
                fetched_at=fetched_at,
            )
        except WraFloodWarningAdapterError as exc:
            failures.append(exc)
            source_id = f"kml:{_source_filename(url)}"
            if source_id not in seen_source_ids:
                seen_source_ids.add(source_id)
                rejected.append(source_id)
                rejection_candidates.append(
                    SourceRejection(source_id, "wra_flood_warning_child_read_failed")
                )
            return

        for record in records:
            source_id = str(record["source_id"])
            if source_id in seen_source_ids:
                continue
            seen_source_ids.add(source_id)
            reason_code = record.get("rejection_reason_code")
            if isinstance(reason_code, str):
                rejected.append(source_id)
                rejection_candidates.append(SourceRejection(source_id, reason_code))
                continue
            payload = dict(record["payload"])
            payload["network_link_source_url"] = network_link_source_url
            payload["metadata_url"] = self._index_url
            fetched.append(
                RawSourceItem(
                    source_id=source_id,
                    source_url=url,
                    fetched_at=fetched_at,
                    payload=payload,
                    raw_snapshot_key=self._raw_snapshot_key,
                )
            )

        for child_url in network_link_urls:
            self._collect_document(
                child_url,
                network_link_source_url=url,
                fetched_at=fetched_at,
                seen_urls=seen_urls,
                seen_source_ids=seen_source_ids,
                fetched=fetched,
                rejected=rejected,
                rejection_candidates=rejection_candidates,
                failures=failures,
            )


# ------------------------------------------------------------ index handling


def _selected_kml_urls(payload: object) -> tuple[str, ...]:
    resolved: set[str] = set()
    for record in _index_records(payload):
        candidate = record.get("sourceurl")
        try:
            approved = approved_wra_flood_warning_url(
                candidate,
                allow_http_upgrade=True,
            )
        except WraFloodWarningPayloadError:
            continue
        if approved in WRA_FLOOD_WARNING_KML_URLS:
            resolved.add(approved)
    selected = tuple(url for url in WRA_FLOOD_WARNING_KML_URLS if url in resolved)
    if not selected:
        raise WraFloodWarningPayloadError(_PAYLOAD_ERROR_MESSAGE)
    return selected


def _index_records(payload: object) -> Iterable[Mapping[str, Any]]:
    if isinstance(payload, list):
        return tuple(item for item in payload if isinstance(item, Mapping))
    if not isinstance(payload, Mapping):
        return ()
    for key in ("responseData", "data", "records", "Data"):
        items = payload.get(key)
        if isinstance(items, list):
            return tuple(item for item in items if isinstance(item, Mapping))
    if "sourceurl" in payload:
        return (payload,)
    return ()


# ----------------------------------------------------------------- KML parse


def parse_wra_flood_warning_kml(text: str) -> Element:
    """Parse and bound-check one WRA warning KML document."""

    return _parse_kml_document(text)


def _parse_kml_document(text: str) -> Element:
    if len(text.encode("utf-8")) > MAX_WRA_FLOOD_WARNING_KML_BYTES:
        raise WraFloodWarningPayloadError(_PAYLOAD_ERROR_MESSAGE)
    try:
        root = ET.fromstring(text.lstrip("﻿").strip())
    except (ET.ParseError, DefusedXmlException):
        raise WraFloodWarningPayloadError(_PAYLOAD_ERROR_MESSAGE) from None
    except Exception:  # noqa: BLE001 - contain hostile parser state
        raise WraFloodWarningPayloadError(_PAYLOAD_ERROR_MESSAGE) from None
    if root.tag != _KML_ROOT:
        raise WraFloodWarningPayloadError(_PAYLOAD_ERROR_MESSAGE)
    _validate_kml_bounds(root)
    return root


def _validate_kml_bounds(root: Element) -> None:
    element_count = 0
    placemark_count = 0
    coordinate_count = 0
    stack: list[tuple[Element, int]] = [(root, 1)]
    while stack:
        element, depth = stack.pop()
        element_count += 1
        if element_count > MAX_WRA_FLOOD_WARNING_XML_ELEMENTS:
            raise WraFloodWarningPayloadError(_PAYLOAD_ERROR_MESSAGE)
        if depth > MAX_WRA_FLOOD_WARNING_XML_DEPTH:
            raise WraFloodWarningPayloadError(_PAYLOAD_ERROR_MESSAGE)
        if element.tag == _KML_PLACEMARK:
            placemark_count += 1
            if placemark_count > MAX_WRA_FLOOD_WARNING_PLACEMARKS:
                raise WraFloodWarningPayloadError(_PAYLOAD_ERROR_MESSAGE)
        if element.tag == _KML_COORDINATES:
            coordinate_count += len((element.text or "").split())
            if coordinate_count > MAX_WRA_FLOOD_WARNING_TOTAL_COORDINATES:
                raise WraFloodWarningPayloadError(_PAYLOAD_ERROR_MESSAGE)
        stack.extend((child, depth + 1) for child in element)


def _network_link_urls(root: Element, *, allow_network_link: bool) -> tuple[str, ...]:
    links = [element for element in root.iter() if element.tag == _KML_NETWORK_LINK]
    if not links:
        return ()
    if not allow_network_link:
        raise WraFloodWarningPayloadError(_PAYLOAD_ERROR_MESSAGE)
    if len(links) > MAX_WRA_FLOOD_WARNING_NETWORK_LINKS:
        raise WraFloodWarningPayloadError(_PAYLOAD_ERROR_MESSAGE)
    resolved: list[str] = []
    for link in links:
        hrefs = [
            element.text
            for element in link.iter()
            if element.tag == _KML_HREF
        ]
        containers = [child for child in link if child.tag in {_KML_LINK, _KML_URL}]
        if len(hrefs) != 1 or len(containers) != 1:
            raise WraFloodWarningPayloadError(_PAYLOAD_ERROR_MESSAGE)
        approved = approved_wra_flood_warning_url(hrefs[0], allow_http_upgrade=True)
        if approved not in WRA_FLOOD_WARNING_KML_URLS:
            raise WraFloodWarningPayloadError(_PAYLOAD_ERROR_MESSAGE)
        if approved not in resolved:
            resolved.append(approved)
    return tuple(resolved)


def _placemark_records(
    root: Element,
    *,
    source_url: str,
    fetched_at: datetime,
) -> tuple[Mapping[str, Any], ...]:
    filename = _source_filename(source_url)
    warning_kind = _WARNING_KINDS.get(filename)
    if warning_kind is None:  # pragma: no cover - defensive
        raise WraFloodWarningPayloadError(_PAYLOAD_ERROR_MESSAGE)

    records: list[Mapping[str, Any]] = []
    for index, placemark in enumerate(_reachable_placemarks(root)):
        identity = optional_str(placemark.attrib.get("id"))
        name = _direct_child_text(placemark, _KML_NAME)
        source_id = f"{filename}:{identity or _synthetic_identity(placemark, index)}"

        geometry = _placemark_geometry(placemark)
        if geometry is None:
            records.append(
                {
                    "source_id": source_id,
                    "rejection_reason_code": "wra_flood_warning_invalid_geometry",
                }
            )
            continue

        source_timestamp, active_from, active_until = _placemark_times(placemark)
        if source_timestamp is None:
            records.append(
                {
                    "source_id": source_id,
                    "rejection_reason_code": "wra_flood_warning_missing_source_time",
                }
            )
            continue

        records.append(
            {
                "source_id": source_id,
                "payload": {
                    "placemark_id": identity or "",
                    "placemark_name": name,
                    "warning_kind": warning_kind,
                    "source_filename": filename,
                    "resource_url": source_url,
                    "source_timestamp": source_timestamp.isoformat(),
                    "active_from": (
                        active_from.isoformat() if active_from is not None else None
                    ),
                    "active_until": (
                        active_until.isoformat() if active_until is not None else None
                    ),
                    "incident_state": _incident_state(
                        placemark,
                        active_until=active_until,
                        fetched_at=fetched_at,
                    ),
                    "geometry": geometry,
                    "location_precision": (
                        "point" if geometry["type"] == "Point" else "polygon"
                    ),
                    "evidence_scope": "context",
                    "context_kind": "official_wra_warning_context",
                    "verification_status": "official_reported",
                    "limitations": list(WRA_FLOOD_WARNING_LIMITATIONS),
                    "attribution": WRA_FLOOD_WARNING_ATTRIBUTION,
                },
            }
        )
    return tuple(records)


def _reachable_placemarks(root: Element) -> tuple[Element, ...]:
    placemarks: list[Element] = []
    stack: list[Element] = [root]
    while stack:
        element = stack.pop()
        if element.tag == _KML_PLACEMARK:
            placemarks.append(element)
            continue
        stack.extend(
            child
            for child in reversed(element)
            if child.tag in {*_KML_CONTAINER_TAGS, _KML_PLACEMARK}
        )
    return tuple(placemarks)


def _synthetic_identity(placemark: Element, index: int) -> str:
    digest = hashlib.sha256(
        json.dumps(
            {
                "index": index,
                "name": _direct_child_text(placemark, _KML_NAME),
                "description": _direct_child_text(placemark, _KML_DESCRIPTION),
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return digest[:32]


def _incident_state(
    placemark: Element,
    *,
    active_until: datetime | None,
    fetched_at: datetime,
) -> str:
    if active_until is not None and active_until <= fetched_at:
        return "resolved"
    text = "\n".join(
        value
        for value in (
            _direct_child_text(placemark, _KML_NAME),
            _direct_child_text(placemark, _KML_DESCRIPTION),
        )
        if value
    )
    if any(keyword in text for keyword in _RESOLVED_KEYWORDS):
        return "resolved"
    return "active"


def _placemark_times(
    placemark: Element,
) -> tuple[datetime | None, datetime | None, datetime | None]:
    when: datetime | None = None
    active_from: datetime | None = None
    active_until: datetime | None = None
    for child in placemark:
        if child.tag == _KML_TIMESTAMP and when is None:
            when = _kml_timestamp(_direct_child_text(child, _KML_WHEN))
        elif child.tag == _KML_TIMESPAN:
            if active_from is None:
                active_from = _kml_timestamp(_direct_child_text(child, _KML_BEGIN))
            if active_until is None:
                active_until = _kml_timestamp(_direct_child_text(child, _KML_END))
    source_timestamp = when or active_from
    return source_timestamp, active_from, active_until


def _kml_timestamp(value: str | None) -> datetime | None:
    text = optional_str(value)
    if text is None:
        return None
    candidate = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=WRA_FLOOD_WARNING_LOCAL_TZ)
    return parsed.astimezone(UTC)


def _parse_aware_utc(value: object) -> datetime | None:
    text = optional_str(value)
    if text is None:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


# ------------------------------------------------------------------ geometry


def _placemark_geometry(placemark: Element) -> dict[str, Any] | None:
    if _contains_unsupported_geometry(placemark):
        return None
    direct = [child for child in placemark if child.tag in _KML_SUPPORTED_GEOMETRY_TAGS]
    if len(direct) != 1:
        return None
    geometry = direct[0]
    if geometry.tag == _KML_POINT:
        point = _point_coordinates(geometry)
        return None if point is None else {"type": "Point", "coordinates": point}
    if geometry.tag == _KML_POLYGON:
        polygon = _polygon_coordinates(geometry)
        return None if polygon is None else {"type": "Polygon", "coordinates": polygon}

    parts = [child for child in geometry if child.tag in {_KML_POINT, _KML_POLYGON}]
    if not parts or len(parts) > MAX_WRA_FLOOD_WARNING_GEOMETRY_PARTS:
        return None
    if len(parts) != len([child for child in geometry]):
        return None
    if all(part.tag == _KML_POINT for part in parts):
        if len(parts) != 1:
            return None
        point = _point_coordinates(parts[0])
        return None if point is None else {"type": "Point", "coordinates": point}
    if not all(part.tag == _KML_POLYGON for part in parts):
        return None
    polygons = [_polygon_coordinates(part) for part in parts]
    if any(polygon is None for polygon in polygons):
        return None
    valid = [polygon for polygon in polygons if polygon is not None]
    if len(valid) == 1:
        return {"type": "Polygon", "coordinates": valid[0]}
    return {"type": "MultiPolygon", "coordinates": valid}


def _contains_unsupported_geometry(placemark: Element) -> bool:
    for element in placemark.iter():
        local_name = element.tag.rsplit("}", 1)[-1]
        if local_name in _UNSUPPORTED_GEOMETRY_LOCAL_NAMES:
            return True
        if local_name in {"Point", "Polygon", "MultiGeometry"} and not element.tag.startswith(
            f"{{{_KML_NS}}}"
        ):
            return True
    return False


def _point_coordinates(point: Element) -> list[float] | None:
    coordinates = [child for child in point if child.tag == _KML_COORDINATES]
    if len(coordinates) != 1:
        return None
    parsed = _coordinate_sequence(coordinates[0].text)
    if parsed is None or len(parsed) != 1:
        return None
    return parsed[0]


def _polygon_coordinates(polygon: Element) -> list[list[list[float]]] | None:
    outer: list[list[float]] | None = None
    holes: list[list[list[float]]] = []
    for child in polygon:
        if child.tag not in {_KML_OUTER_BOUNDARY, _KML_INNER_BOUNDARY}:
            return None
        ring = _boundary_ring(child)
        if not _valid_linear_ring(ring):
            return None
        assert ring is not None
        if child.tag == _KML_OUTER_BOUNDARY:
            if outer is not None:
                return None
            outer = ring
        else:
            holes.append(ring)
    if outer is None:
        return None
    return [outer, *holes]


def _boundary_ring(boundary: Element) -> list[list[float]] | None:
    rings = [child for child in boundary if child.tag == _KML_LINEAR_RING]
    if len(rings) != 1 or len(list(boundary)) != 1:
        return None
    coordinates = [child for child in rings[0] if child.tag == _KML_COORDINATES]
    if len(coordinates) != 1 or len(list(rings[0])) != 1:
        return None
    return _coordinate_sequence(coordinates[0].text)


def _valid_linear_ring(ring: list[list[float]] | None) -> bool:
    return ring is not None and len(ring) >= 4 and ring[0] == ring[-1]


def _coordinate_sequence(value: str | None) -> list[list[float]] | None:
    text = optional_str(value)
    if text is None:
        return None
    coordinates: list[list[float]] = []
    for token in text.split():
        parts = token.split(",")
        if len(parts) < 2:
            return None
        try:
            longitude = float(parts[0])
            latitude = float(parts[1])
        except ValueError:
            return None
        if not _coordinate_in_taiwan(longitude, latitude):
            return None
        coordinates.append([longitude, latitude])
    return coordinates or None


def _coordinate_in_taiwan(longitude: float, latitude: float) -> bool:
    return (
        math.isfinite(longitude)
        and math.isfinite(latitude)
        and _TAIWAN_LONGITUDE_BOUNDS[0] <= longitude <= _TAIWAN_LONGITUDE_BOUNDS[1]
        and _TAIWAN_LATITUDE_BOUNDS[0] <= latitude <= _TAIWAN_LATITUDE_BOUNDS[1]
    )


# ----------------------------------------------------------------- transport


def fetch_wra_flood_warning_json(url: str, timeout_seconds: int) -> object:
    approved_url = approved_wra_flood_warning_url(url)
    payload = _read_bounded(
        approved_url,
        timeout_seconds,
        accept="application/json",
        limit=MAX_WRA_FLOOD_WARNING_METADATA_BYTES,
    )
    try:
        return json.loads(payload.decode("utf-8-sig"))
    except Exception:  # noqa: BLE001 - sanitize JSON parser state
        raise WraFloodWarningPayloadError(_PAYLOAD_ERROR_MESSAGE) from None


def fetch_wra_flood_warning_text(url: str, timeout_seconds: int) -> str:
    approved_url = approved_wra_flood_warning_url(url)
    payload = _read_bounded(
        approved_url,
        timeout_seconds,
        accept="application/vnd.google-earth.kml+xml,application/xml,text/xml",
        limit=MAX_WRA_FLOOD_WARNING_KML_BYTES,
    )
    try:
        return payload.decode("utf-8-sig")
    except Exception:  # noqa: BLE001 - contain response decode state
        raise WraFloodWarningPayloadError(_PAYLOAD_ERROR_MESSAGE) from None


def _read_bounded(
    approved_url: str,
    timeout_seconds: int,
    *,
    accept: str,
    limit: int,
) -> bytes:
    request = Request(
        approved_url,
        headers={"Accept": accept, "User-Agent": WRA_FLOOD_WARNING_USER_AGENT},
        method="GET",
    )
    opener = build_opener(
        HTTPSHandler(context=taiwan_gov_open_data_ssl_context()),
        _WraFloodWarningRedirectHandler(),
    )
    failure: WraFloodWarningAdapterError | None = None
    body: bytes | None = None
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            approved_wra_flood_warning_url(response.geturl())
            body = response.read(limit + 1)
    except HTTPError as exc:
        failure = _http_error_failure(exc)
    except WraFloodWarningAdapterError as exc:
        failure = exc
    except (URLError, TimeoutError):
        failure = WraFloodWarningFetchError(_FETCH_ERROR_MESSAGE)
    except Exception:  # noqa: BLE001 - complete untrusted transport boundary
        failure = WraFloodWarningFetchError(_FETCH_ERROR_MESSAGE)
    if failure is not None:
        raise failure
    if type(body) is not bytes or len(body) > limit:
        raise WraFloodWarningPayloadError(_PAYLOAD_ERROR_MESSAGE)
    return body


def _http_error_failure(exc: HTTPError) -> WraFloodWarningFetchError:
    try:
        if type(exc.code) is int and exc.code == 429:
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            return WraFloodWarningRateLimitError(
                "WRA flood warning returned HTTP 429: [REDACTED]",
                retry_after_seconds=_retry_after_seconds(retry_after),
            )
    except Exception:  # noqa: BLE001 - contain hostile HTTP error metadata
        return WraFloodWarningFetchError(_FETCH_ERROR_MESSAGE)
    return WraFloodWarningFetchError(_FETCH_ERROR_MESSAGE)


def _retry_after_seconds(value: str | None) -> int | None:
    if value is None:
        return None
    stripped = value.strip()
    try:
        seconds = int(stripped)
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(stripped)
        except (TypeError, ValueError, OverflowError):
            return None
        if retry_at.tzinfo is None or retry_at.utcoffset() is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        seconds = math.ceil((retry_at - datetime.now(UTC)).total_seconds())
    return _bounded_retry_after(seconds)


def _bounded_retry_after(value: int | None) -> int | None:
    if type(value) is not int:
        return None
    return min(MAX_WRA_FLOOD_WARNING_RETRY_AFTER_SECONDS, max(0, value))


def _aggregate_failure(
    failures: list[WraFloodWarningAdapterError],
) -> WraFloodWarningFetchError:
    cooldowns = [
        failure.retry_after_seconds
        for failure in failures
        if isinstance(failure, WraFloodWarningRateLimitError)
        and failure.retry_after_seconds is not None
    ]
    if cooldowns:
        return WraFloodWarningRateLimitError(
            "WRA flood warning returned HTTP 429: [REDACTED]",
            retry_after_seconds=max(cooldowns),
        )
    return WraFloodWarningFetchError(_FETCH_ERROR_MESSAGE)


def _source_filename(url: str) -> str:
    return urlsplit(url).path.rsplit("/", 1)[-1]


def _direct_child_text(element: Element, tag: str) -> str | None:
    for child in element:
        if child.tag == tag:
            return optional_str(child.text)
    return None
