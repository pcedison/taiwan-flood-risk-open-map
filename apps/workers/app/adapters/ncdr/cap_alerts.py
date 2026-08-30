from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from xml.etree.ElementTree import Element

from defusedxml import ElementTree

from app.adapters._helpers import optional_str
from app.adapters._taiwan_gov_tls import taiwan_gov_open_data_ssl_context
from app.adapters.cap_identity import cap_message_digest, cap_source_id
from app.adapters.cap_xml import (
    MAX_CAP_BYTES,
    CapDocumentError,
    ParsedCapArea,
    ParsedCapMessage,
    parse_cap_document,
)
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

NcdrFetchJson = Callable[[str, Mapping[str, str], int], object]
NcdrFetchText = Callable[[str, Mapping[str, str], int], str]
FetchJson = NcdrFetchJson
FetchText = NcdrFetchText

NCDR_DATASTORE_API_URL = "https://alerts.ncdr.nat.gov.tw/api/datastore"
NCDR_DUMP_API_URL = "https://alerts.ncdr.nat.gov.tw/api/dump/datastore"
NCDR_ACTIVE_ATOM_FEED_URL = "https://alerts.ncdr.nat.gov.tw/RssAtomFeeds.ashx"
NCDR_PUBLIC_HOST = "alerts.ncdr.nat.gov.tw"
NCDR_FLOOD_CATEGORY = "淹水"
NCDR_GEOCODE_PROFILE = "Taiwan_Geocode_103"
NCDR_TOWNSHIP_GEOCODE_NAMES = frozenset({"towncode", "taiwan_geocode_103"})
# The public active-warning feed can legitimately exceed 50 flood entries during
# a widespread event (54 were observed on 2026-08-30). Keep the configured
# default aligned with the adapter's existing hard ceiling so valid official
# feeds are not reported as upstream failures exactly when warning volume rises.
DEFAULT_NCDR_MAX_CAP_IDS_PER_RUN = 200
DEFAULT_NCDR_CAP_TIMEOUT_SECONDS = 8
NCDR_CAP_USER_AGENT = "FloodRiskTaiwan/0.1 worker-ncdr-cap"
MAX_NCDR_AUDITED_ROWS = 256
NCDR_CAP_METADATA = AdapterMetadata(
    key="official.ncdr.cap",
    family=SourceFamily.OFFICIAL,
    enabled_by_default=False,
    display_name="NCDR active-warning Atom/CAP adapter",
    data_gov_dataset_id="NCDR-CAP",
    data_gov_url="https://alerts.ncdr.nat.gov.tw/",
    resource_url=NCDR_ACTIVE_ATOM_FEED_URL,
    update_frequency="active-warning Atom feed refreshed every minute by NCDR",
    license="Government Open Data License, version 1.0",
    snapshot_generation_mode="complete_replace",
    limitations=(
        "Uses the public active-warning Atom feed when no member API key is configured.",
        "Disabled by default; only exact Taiwan_Geocode_103 areas with an active reviewed boundary snapshot can be published.",
        "Polygon, Circle, ambiguous, and unreviewed CAP areas remain rejection-only audit rows.",
    ),
)


class NcdrCapAlertAdapterError(RuntimeError):
    """Base error for NCDR CAP adapter failures."""


class NcdrCapAlertFetchError(NcdrCapAlertAdapterError):
    """Raised when fetching NCDR CAP payloads fails."""

    def __init__(
        self,
        message: str,
        *,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(message)
        self.retry_after_seconds = _bounded_retry_after(retry_after_seconds)


class NcdrCapAlertPayloadError(NcdrCapAlertAdapterError):
    """Raised when the NCDR CAP payload shape is not parseable."""


class NcdrCapAlertConfigurationError(NcdrCapAlertAdapterError):
    """Raised when an enabled NCDR transport is configured unsafely."""


class NcdrCapAlertRateLimitError(NcdrCapAlertFetchError):
    def __init__(self, message: str, *, retry_after_seconds: int | None) -> None:
        super().__init__(message, retry_after_seconds=retry_after_seconds)


class NcdrCapAlertAdapter:
    metadata = NCDR_CAP_METADATA

    def __init__(
        self,
        *,
        api_key: str | None = None,
        datastore_url: str | None = None,
        dump_url: str | None = None,
        active_feed_url: str | None = None,
        max_cap_ids_per_run: int = DEFAULT_NCDR_MAX_CAP_IDS_PER_RUN,
        timeout_seconds: int = DEFAULT_NCDR_CAP_TIMEOUT_SECONDS,
        fetched_at: datetime | None = None,
        fetch_json: NcdrFetchJson | None = None,
        fetch_text: NcdrFetchText | None = None,
        raw_snapshot_key: str | None = None,
    ) -> None:
        self._api_key = api_key
        self._datastore_url = _configured_public_url(datastore_url or NCDR_DATASTORE_API_URL)
        self._dump_url = _configured_public_url(dump_url or NCDR_DUMP_API_URL)
        self._active_feed_url = _configured_active_feed_url(
            active_feed_url or NCDR_ACTIVE_ATOM_FEED_URL
        )
        self._max_cap_ids_per_run = min(200, max(1, max_cap_ids_per_run))
        self._timeout_seconds = max(1, timeout_seconds)
        self._fetched_at = fetched_at
        self._fetch_json_override = fetch_json
        self._fetch_text_override = fetch_text
        self._raw_snapshot_key = raw_snapshot_key

    def fetch(self) -> tuple[RawSourceItem, ...]:
        fetched, _normalized, _rejections, selected_count, successful_dump_count, retry_after = (
            self._fetch_audited_rows()
        )
        if selected_count > 0 and successful_dump_count == 0:
            raise NcdrCapAlertFetchError(
                "all selected NCDR CAP dumps failed",
                retry_after_seconds=retry_after,
            )
        return fetched

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        return _normalize_reviewed_raw(raw_item)

    def run(self) -> AdapterRunResult:
        (
            fetched,
            normalized,
            source_rejections,
            selected_count,
            successful_dump_count,
            retry_after,
        ) = (
            self._fetch_audited_rows()
        )
        if selected_count > 0 and successful_dump_count == 0:
            raise NcdrCapAlertFetchError(
                "all selected NCDR CAP dumps failed",
                retry_after_seconds=retry_after,
            )
        rejected = tuple(rejection.source_id for rejection in source_rejections)

        return AdapterRunResult(
            adapter_key=self.metadata.key,
            fetched=fetched,
            normalized=normalized,
            rejected=rejected,
            source_rejections=source_rejections,
            no_active_event=selected_count == 0 or (not fetched and successful_dump_count > 0),
        )

    def _fetch_audited_rows(
        self,
    ) -> tuple[
        tuple[RawSourceItem, ...],
        tuple[NormalizedEvidence, ...],
        tuple[SourceRejection, ...],
        int,
        int,
        int | None,
    ]:
        api_key = (self._api_key or "").strip()
        if api_key and (api_key in self._datastore_url or api_key in self._dump_url):
            raise NcdrCapAlertConfigurationError(
                "NCDR endpoint contained [REDACTED] credential material"
            )
        fetched_at = self._fetched_at or datetime.now(UTC)
        selected_documents: tuple[tuple[str, str, Mapping[str, str]], ...]
        if api_key:
            index_params = {
                "apikey": api_key,
                "format": "json",
                "limit": str(self._max_cap_ids_per_run),
            }
            index_payload = self._call_json_fetcher(
                self._datastore_url,
                index_params,
                fetched_at=fetched_at,
            )
            cap_ids = _parse_datastore_cap_ids(
                index_payload,
                api_key=api_key,
                limit=self._max_cap_ids_per_run,
            )
            selected_documents = tuple(
                (
                    cap_id,
                    self._dump_url,
                    {"apikey": api_key, "capid": cap_id, "format": "xml"},
                )
                for cap_id in cap_ids
            )
        else:
            feed_xml = self._call_text_fetcher(
                self._active_feed_url,
                {},
                fetched_at=fetched_at,
            )
            public_documents = _parse_public_active_feed(
                feed_xml,
                feed_url=self._active_feed_url,
                limit=self._max_cap_ids_per_run,
            )
            selected_documents = tuple(
                (cap_id, cap_url, {}) for cap_id, cap_url in public_documents
            )
        if not selected_documents:
            return (), (), (), 0, 0, None

        fetched: list[RawSourceItem] = []
        normalized: list[NormalizedEvidence] = []
        rejections: list[SourceRejection] = []
        seen_source_ids: set[str] = set()
        successful_dump_count = 0
        audited_row_count = 0
        max_retry_after_seconds: int | None = None
        for cap_id, cap_url, dump_params in selected_documents:
            dump_failed = False
            dump_retry_after_seconds: int | None = None
            xml_text = ""
            messages: tuple[ParsedCapMessage, ...] = ()
            try:
                xml_text = self._call_text_fetcher(
                    cap_url,
                    dump_params,
                    fetched_at=fetched_at,
                )
                if api_key and api_key in xml_text:
                    raise NcdrCapAlertPayloadError(
                        "NCDR CAP dump contained [REDACTED] credential material"
                    )
                messages = parse_cap_document(xml_text)
            except NcdrCapAlertRateLimitError as exc:
                dump_failed = True
                dump_retry_after_seconds = exc.retry_after_seconds
                if dump_retry_after_seconds is not None:
                    max_retry_after_seconds = max(
                        max_retry_after_seconds or 0,
                        dump_retry_after_seconds,
                    )
            except (NcdrCapAlertAdapterError, CapDocumentError):
                dump_failed = True
            finally:
                xml_text = ""

            row_count = sum(len(message.areas) or 1 for message in messages)
            if not dump_failed and audited_row_count + row_count > MAX_NCDR_AUDITED_ROWS:
                raise NcdrCapAlertPayloadError("NCDR CAP exceeds the 256 audited-row limit")
            prepared: list[tuple[RawSourceItem, str | None]] = []
            if not dump_failed:
                try:
                    prepared = [
                        _prepare_audit_row(
                            message,
                            area,
                            transport_capid=cap_id,
                            fetched_at=fetched_at,
                            source_url=cap_url,
                            raw_snapshot_key=self._raw_snapshot_key,
                        )
                        for message in messages
                        for area in (message.areas or (None,))
                    ]
                except CapDocumentError:
                    dump_failed = True
                    prepared = []

            if dump_failed:
                audited_row_count += 1
                if audited_row_count > MAX_NCDR_AUDITED_ROWS:
                    raise NcdrCapAlertPayloadError("NCDR CAP exceeds the 256 audited-row limit")
                transport_id = _transport_source_id(cap_id)
                failure_payload: dict[str, Any] = {
                    "transport_capid": cap_id,
                    "error": "NCDR CAP dump fetch failed",
                }
                if dump_retry_after_seconds is not None:
                    failure_payload["retry_after_seconds"] = dump_retry_after_seconds
                failure_raw = RawSourceItem(
                    source_id=transport_id,
                    source_url=cap_url,
                    fetched_at=fetched_at,
                    payload=failure_payload,
                    raw_snapshot_key=self._raw_snapshot_key,
                )
                if api_key:
                    _reject_secret_bearing_raw(failure_raw, secret=api_key)
                fetched.append(failure_raw)
                rejections.append(SourceRejection(transport_id, "ncdr_dump_fetch_failed"))
                continue

            for raw, _reason in prepared:
                if api_key:
                    _reject_secret_bearing_raw(raw, secret=api_key)
            successful_dump_count += 1
            audited_row_count += row_count
            for raw, reason in prepared:
                if raw.source_id in seen_source_ids:
                    continue
                seen_source_ids.add(raw.source_id)
                fetched.append(raw)
                if reason is None:
                    evidence = self.normalize(raw)
                    if evidence is None:
                        rejections.append(
                            SourceRejection(raw.source_id, "ncdr_normalization_failed")
                        )
                    else:
                        normalized.append(evidence)
                else:
                    rejections.append(SourceRejection(raw.source_id, reason))

        return (
            tuple(fetched),
            tuple(normalized),
            tuple(rejections),
            len(selected_documents),
            successful_dump_count,
            max_retry_after_seconds,
        )

    def _call_json_fetcher(
        self,
        url: str,
        params: Mapping[str, str],
        *,
        fetched_at: datetime,
    ) -> object:
        fetcher = self._fetch_json_override
        if fetcher is None:
            return _fetch_json(url, params, self._timeout_seconds, now=fetched_at)
        failure: NcdrCapAlertFetchError | None = None
        payload: object | None = None
        try:
            payload = fetcher(url, params, self._timeout_seconds)
        except Exception as exc:  # noqa: BLE001 - sanitize untrusted injected boundary
            if isinstance(exc, NcdrCapAlertRateLimitError):
                failure = NcdrCapAlertRateLimitError(
                    f"NCDR datastore fetcher failed at {url}: [REDACTED]",
                    retry_after_seconds=_bounded_retry_after(exc.retry_after_seconds),
                )
            else:
                failure = NcdrCapAlertFetchError(
                    f"NCDR datastore fetcher failed at {url}: [REDACTED]"
                )
        if failure is not None:
            raise failure
        return payload

    def _call_text_fetcher(
        self,
        url: str,
        params: Mapping[str, str],
        *,
        fetched_at: datetime,
    ) -> str:
        fetcher = self._fetch_text_override
        if fetcher is None:
            return _fetch_text(url, params, self._timeout_seconds, now=fetched_at)
        failure: NcdrCapAlertFetchError | None = None
        xml_text: str | None = None
        try:
            xml_text = fetcher(url, params, self._timeout_seconds)
        except Exception as exc:  # noqa: BLE001 - sanitize untrusted injected boundary
            if isinstance(exc, NcdrCapAlertRateLimitError):
                failure = NcdrCapAlertRateLimitError(
                    f"NCDR XML resource fetcher failed at {url}: [REDACTED]",
                    retry_after_seconds=_bounded_retry_after(exc.retry_after_seconds),
                )
            else:
                failure = NcdrCapAlertFetchError(
                    f"NCDR XML resource fetcher failed at {url}: [REDACTED]"
                )
        if failure is not None:
            raise failure
        if not isinstance(xml_text, str):
            raise NcdrCapAlertPayloadError("NCDR XML resource fetcher returned non-text data")
        return xml_text


def _parse_datastore_cap_ids(
    payload: object,
    *,
    api_key: str,
    limit: int,
) -> tuple[str, ...]:
    records: object
    if isinstance(payload, list):
        records = payload
    elif isinstance(payload, Mapping):
        records = payload.get("data")
        if isinstance(records, Mapping):
            if "records" in records:
                records = records["records"]
            elif "items" in records:
                records = records["items"]
            else:
                records = None
    else:
        raise NcdrCapAlertPayloadError("NCDR datastore payload must be a JSON object or list")
    if not isinstance(records, list):
        raise NcdrCapAlertPayloadError("NCDR datastore payload is missing a data list")

    cap_ids: set[str] = set()
    for record in records:
        if not isinstance(record, Mapping):
            raise NcdrCapAlertPayloadError("NCDR datastore data entries must be objects")
        raw_cap_id = record.get("capid")
        if raw_cap_id is None:
            continue
        if not isinstance(raw_cap_id, str):
            raise NcdrCapAlertPayloadError("NCDR datastore capid must be text")
        cap_id = raw_cap_id.strip()
        if not cap_id or len(cap_id) > 256:
            continue
        if api_key and api_key in cap_id:
            raise NcdrCapAlertPayloadError(
                "NCDR datastore capid contained [REDACTED] credential material"
            )
        cap_ids.add(cap_id)
    if records and not cap_ids:
        raise NcdrCapAlertPayloadError("NCDR datastore contained no usable capid values")
    return tuple(sorted(cap_ids)[:limit])


def _parse_public_active_feed(
    xml_text: str,
    *,
    feed_url: str,
    limit: int,
) -> tuple[tuple[str, str], ...]:
    """Return flood CAP documents from NCDR's public active-warning feed.

    The official feed contains every active warning category.  Only entries
    explicitly categorized as ``淹水`` belong to this adapter.  A malformed
    flood entry fails the poll instead of being mistaken for a healthy empty
    feed.
    """

    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as exc:
        raise NcdrCapAlertPayloadError("NCDR active-warning Atom feed could not be parsed") from exc
    if _local_name(root.tag) != "feed":
        raise NcdrCapAlertPayloadError("NCDR active-warning payload root must be an Atom feed")

    documents: list[tuple[str, str]] = []
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    for entry in root:
        if _local_name(entry.tag) != "entry":
            continue
        categories = {
            optional_str(element.attrib.get("term"))
            for element in entry
            if _local_name(element.tag) == "category"
        }
        if NCDR_FLOOD_CATEGORY not in categories:
            continue

        cap_id = _first_direct_xml_text(entry, "id")
        if cap_id is None or len(cap_id) > 256:
            raise NcdrCapAlertPayloadError("NCDR active-warning flood entry is missing a usable id")
        cap_url = _active_feed_cap_url(entry, feed_url=feed_url)
        if cap_id in seen_ids or cap_url in seen_urls:
            if (cap_id, cap_url) in documents:
                # The public feed occasionally repeats the exact same Atom entry.
                # Treat only an identical transport identity as idempotent.  An ID
                # reused for another URL (or a URL reused for another ID) remains
                # a fail-closed conflict below.
                continue
            raise NcdrCapAlertPayloadError(
                "NCDR active-warning feed contains conflicting flood entries"
            )
        seen_ids.add(cap_id)
        seen_urls.add(cap_url)
        documents.append((cap_id, cap_url))

    if len(documents) > limit:
        raise NcdrCapAlertPayloadError(
            "NCDR active-warning flood entry count exceeds the configured run limit"
        )
    return tuple(documents)


def _active_feed_cap_url(entry: Element, *, feed_url: str) -> str:
    href: str | None = None
    for element in entry:
        if _local_name(element.tag) != "link":
            continue
        rel = optional_str(element.attrib.get("rel"))
        candidate = optional_str(element.attrib.get("href"))
        if candidate is not None and rel in {None, "alternate"}:
            href = candidate
            break
    if href is None:
        raise NcdrCapAlertPayloadError("NCDR active-warning flood entry is missing a CAP link")

    feed_parts = urlsplit(feed_url)
    parts = urlsplit(href)
    try:
        port = parts.port
    except ValueError as exc:
        raise NcdrCapAlertPayloadError(
            "NCDR active-warning flood entry has an invalid CAP link"
        ) from exc
    if (
        parts.scheme != "https"
        or (parts.hostname or "").lower() != NCDR_PUBLIC_HOST
        or (feed_parts.hostname or "").lower() != NCDR_PUBLIC_HOST
        or parts.username is not None
        or parts.password is not None
        or port not in {None, 443}
        or not parts.path.startswith("/Capstorage/")
        or not parts.path.lower().endswith(".cap")
        or parts.query
        or parts.fragment
    ):
        raise NcdrCapAlertPayloadError("NCDR active-warning flood entry has an untrusted CAP link")
    return urlunsplit(("https", NCDR_PUBLIC_HOST, parts.path, "", ""))


def _first_direct_xml_text(element: Element, local_name: str) -> str | None:
    for child in element:
        if _local_name(child.tag) == local_name:
            return optional_str(child.text)
    return None


def _prepare_audit_row(
    message: ParsedCapMessage,
    area: ParsedCapArea | None,
    *,
    transport_capid: str,
    fetched_at: datetime,
    source_url: str,
    raw_snapshot_key: str | None,
) -> tuple[RawSourceItem, str | None]:
    if message.message_type not in {"Alert", "Update", "Cancel"}:
        raise CapDocumentError("NCDR CAP msgType must be Alert, Update, or Cancel")
    if message.message_type in {"Update", "Cancel"} and not message.references:
        raise CapDocumentError("NCDR CAP Update and Cancel messages require references")
    active_from = message.onset or message.effective
    if active_from is None or message.expires is None:
        raise CapDocumentError("NCDR CAP lifecycle requires effective or onset and expires")
    if message.expires <= active_from:
        raise CapDocumentError("NCDR CAP expires must be later than active_from")

    reviewed_geocode = _reviewed_township_geocode(area)
    admin_code = f"{reviewed_geocode[1]}0" if reviewed_geocode is not None else None
    if area is None:
        source_id = cap_source_id(
            sender=message.sender,
            identifier=message.identifier,
            sent=message.sent,
            admin_code=None,
            message_level=True,
        )
    elif admin_code is not None and area.polygon is None and area.circle is None:
        source_id = cap_source_id(
            sender=message.sender,
            identifier=message.identifier,
            sent=message.sent,
            admin_code=admin_code,
            message_level=False,
        )
    else:
        source_id = _unresolved_area_source_id(message, area)
    payload: dict[str, object] = {
        "evidence_scope": "current",
        "location_precision": "admin_area",
        "transport_capid": transport_capid,
        "cap_sender": message.sender,
        "cap_identifier": message.identifier,
        "cap_sent": message.sent.isoformat(),
        "cap_references": [
            {
                "sender": reference.sender,
                "identifier": reference.identifier,
                "sent": reference.sent.isoformat(),
            }
            for reference in message.references
        ],
        "cap_status": message.status,
        "cap_message_type": message.message_type,
        "cap_scope": message.scope,
        "cap_event": message.event,
        "headline": message.headline,
        "description": message.description,
        "active_from": active_from.isoformat(),
        "active_until": message.expires.isoformat(),
        "areaDesc": area.area_desc if area is not None else None,
        "source_geocodes": (
            [{"valueName": name, "value": value} for name, value in area.geocodes]
            if area is not None
            else []
        ),
    }
    if reviewed_geocode is not None:
        source_geocode_name, geocode_value = reviewed_geocode
        payload.update(
            {
                "admin_code": f"{geocode_value}0",
                "ncdr_geocode_profile": NCDR_GEOCODE_PROFILE,
                "ncdr_geocode_name": source_geocode_name,
                "ncdr_geocode": geocode_value,
            }
        )
    if area is not None and area.polygon is not None:
        payload["polygon"] = [
            {"latitude": latitude, "longitude": longitude} for latitude, longitude in area.polygon
        ]
    if area is not None and area.circle is not None:
        latitude, longitude, radius_km = area.circle
        payload["circle"] = {
            "latitude": latitude,
            "longitude": longitude,
            "radius_km": radius_km,
        }
    return (
        RawSourceItem(
            source_id=source_id,
            source_url=source_url,
            fetched_at=fetched_at,
            payload=payload,
            raw_snapshot_key=raw_snapshot_key,
        ),
        _audit_rejection_reason(
            message,
            area,
            active_from=active_from,
            fetched_at=fetched_at,
            reviewed_geocode=reviewed_geocode,
        ),
    )


def _reviewed_township_geocode(area: ParsedCapArea | None) -> tuple[str, str] | None:
    if area is None:
        return None
    matches = tuple(
        (name.strip(), value.strip())
        for name, value in area.geocodes
        if name.strip().lower() in NCDR_TOWNSHIP_GEOCODE_NAMES
    )
    values = {value for _name, value in matches}
    if len(values) != 1:
        return None
    value = next(iter(values))
    if re.fullmatch(r"[0-9]{7}", value) is None:
        return None
    source_name = min(name for name, _value in matches)
    return source_name, value


def _normalize_reviewed_raw(raw_item: RawSourceItem) -> NormalizedEvidence | None:
    payload = raw_item.payload
    message_type = optional_str(payload.get("cap_message_type"))
    status = optional_str(payload.get("cap_status"))
    if status != "Actual" or message_type not in {"Alert", "Update", "Cancel"}:
        return None
    if message_type in {"Alert", "Update"}:
        admin_code = optional_str(payload.get("admin_code"))
        geocode = optional_str(payload.get("ncdr_geocode"))
        if (
            re.fullmatch(r"[0-9]{8}", admin_code or "") is None
            or re.fullmatch(r"[0-9]{7}", geocode or "") is None
            or admin_code != f"{geocode}0"
            or payload.get("ncdr_geocode_profile") != NCDR_GEOCODE_PROFILE
        ):
            return None
    sent = _aware_datetime(payload.get("cap_sent"))
    if sent is None:
        return None
    headline = optional_str(payload.get("headline"))
    description = optional_str(payload.get("description"))
    area_desc = optional_str(payload.get("areaDesc"))
    title = headline or "NCDR 淹水警戒"
    summary = description or headline or "NCDR 發布淹水警戒 CAP 訊息。"
    return NormalizedEvidence(
        evidence_id=f"{NCDR_CAP_METADATA.key}:{raw_item.source_id}",
        adapter_key=NCDR_CAP_METADATA.key,
        source_family=SourceFamily.OFFICIAL,
        event_type=EventType.FLOOD_WARNING,
        source_id=raw_item.source_id,
        source_url=raw_item.source_url,
        source_title=title,
        source_timestamp=sent,
        fetched_at=raw_item.fetched_at,
        summary=summary,
        location_text=area_desc,
        confidence=0.95,
        status=IngestionStatus.NORMALIZED,
        attribution="國家災害防救科技中心（NCDR）",
        tags=("official", "ncdr", "cap", "flood_warning"),
    )


def _aware_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _unresolved_area_source_id(message: ParsedCapMessage, area: ParsedCapArea) -> str:
    message_id = cap_message_digest(
        sender=message.sender,
        identifier=message.identifier,
        sent=message.sent,
    )
    area_json = json.dumps(
        [area.area_desc, sorted(area.geocodes), area.polygon, area.circle],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    area_id = hashlib.sha256(area_json.encode("utf-8")).hexdigest()[:24]
    return f"cap:{message_id}:unresolved-area:{area_id}"


def _audit_rejection_reason(
    message: ParsedCapMessage,
    area: ParsedCapArea | None,
    *,
    active_from: datetime,
    fetched_at: datetime,
    reviewed_geocode: tuple[str, str] | None,
) -> str | None:
    if message.status != "Actual":
        return "ncdr_inactive_status"
    if message.scope != "Public":
        return "ncdr_inactive_scope"
    if message.message_type == "Cancel":
        if area is None or reviewed_geocode is not None:
            return None
        return "ncdr_unreviewed_admin_geometry"
    if active_from > fetched_at:
        return "ncdr_inactive_future"
    if message.expires is not None and message.expires <= fetched_at:
        return "ncdr_inactive_expired"
    if area is None:
        return "ncdr_unreviewed_message_geometry"
    if area.circle is not None:
        return "ncdr_circle_geometry_unreviewed"
    if area.polygon is not None:
        return "ncdr_polygon_geometry_unreviewed"
    if reviewed_geocode is None:
        return "ncdr_unreviewed_admin_geometry"
    return None


def _transport_source_id(cap_id: str) -> str:
    digest = hashlib.sha256(cap_id.encode("utf-8")).hexdigest()[:24]
    return f"ncdr-transport:{digest}"


def _reject_secret_bearing_raw(raw: RawSourceItem, *, secret: str) -> None:
    raw_fields = (
        raw.source_id,
        raw.source_url,
        raw.raw_snapshot_key,
        raw.payload,
    )
    if any(_contains_exact_secret(value, secret=secret) for value in raw_fields):
        raise NcdrCapAlertPayloadError(
            "NCDR CAP raw audit contained [REDACTED] credential material"
        )


def _contains_exact_secret(value: object, *, secret: str) -> bool:
    if isinstance(value, str):
        return secret in value
    if isinstance(value, Mapping):
        return any(
            _contains_exact_secret(key, secret=secret)
            or _contains_exact_secret(item, secret=secret)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_contains_exact_secret(item, secret=secret) for item in value)
    return False


def _public_url(url: str) -> str:
    parts = urlsplit(url.strip())
    if parts.username is not None or parts.password is not None:
        raise ValueError("NCDR endpoint URL must not contain userinfo")
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _configured_public_url(url: str) -> str:
    public_url: str | None = None
    failed = False
    try:
        public_url = _public_url(url)
    except Exception:  # noqa: BLE001 - sanitize configured URL parsing failures
        failed = True
    if failed or public_url is None:
        raise NcdrCapAlertConfigurationError("NCDR endpoint URL is invalid: [REDACTED]")
    return public_url


def _configured_active_feed_url(url: str) -> str:
    try:
        configured_parts = urlsplit(url.strip())
    except ValueError:
        raise NcdrCapAlertConfigurationError(
            "NCDR active-warning feed URL is invalid: [REDACTED]"
        ) from None
    if configured_parts.query or configured_parts.fragment:
        raise NcdrCapAlertConfigurationError("NCDR active-warning feed URL is invalid: [REDACTED]")
    public_url = _configured_public_url(url)
    parts = urlsplit(public_url)
    try:
        port = parts.port
    except ValueError:
        raise NcdrCapAlertConfigurationError(
            "NCDR active-warning feed URL is invalid: [REDACTED]"
        ) from None
    if (
        parts.scheme != "https"
        or (parts.hostname or "").lower() != NCDR_PUBLIC_HOST
        or port not in {None, 443}
        or parts.path != "/RssAtomFeeds.ashx"
    ):
        raise NcdrCapAlertConfigurationError("NCDR active-warning feed URL is invalid: [REDACTED]")
    return public_url


def _bounded_retry_after(value: int | None) -> int | None:
    if value is None:
        return None
    return min(3600, max(0, value))


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


def _parse_xml_entry(entry: Element, *, source_url: str) -> Mapping[str, Any] | None:
    embedded_alert = next(
        (
            element
            for element in entry.iter()
            if element is not entry and _local_name(element.tag) == "alert"
        ),
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


def _parse_xml_alert(alert: Element, *, source_url: str) -> Mapping[str, Any] | None:
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


def _parse_xml_geocodes(element: Element | None) -> tuple[Mapping[str, str], ...]:
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


def _first_xml_text(element: Element | None, local_name: str) -> str | None:
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


def _fetch_json(
    url: str,
    params: Mapping[str, str],
    timeout_seconds: int,
    *,
    now: datetime | None = None,
) -> object:
    body = _fetch_bytes(
        url,
        params,
        timeout_seconds,
        accept="application/json",
        now=now,
    )
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise NcdrCapAlertPayloadError(
            f"NCDR datastore JSON could not be parsed at {_public_url(url)}"
        ) from None


def _fetch_text(
    url: str,
    params: Mapping[str, str],
    timeout_seconds: int,
    *,
    now: datetime | None = None,
) -> str:
    body = _fetch_bytes(
        url,
        params,
        timeout_seconds,
        accept="application/xml, text/xml",
        now=now,
    )
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        raise NcdrCapAlertPayloadError(
            f"NCDR CAP dump could not be decoded at {_public_url(url)}"
        ) from None


def _fetch_bytes(
    url: str,
    params: Mapping[str, str],
    timeout_seconds: int,
    *,
    accept: str,
    now: datetime | None,
) -> bytes:
    public_url = "[invalid NCDR URL]"
    body: bytes | None = None
    failure: NcdrCapAlertFetchError | None = None
    try:
        public_url = _public_url(url)
        request_url = f"{public_url}?{urlencode(tuple(params.items()))}"
        request = Request(
            request_url,
            headers={
                "Accept": accept,
                "User-Agent": NCDR_CAP_USER_AGENT,
            },
            method="GET",
        )
        with urlopen(
            request,
            timeout=timeout_seconds,
            context=taiwan_gov_open_data_ssl_context(),
        ) as response:
            body = response.read(MAX_CAP_BYTES + 1)
    except HTTPError as exc:
        try:
            if exc.code == 429:
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                failure = NcdrCapAlertRateLimitError(
                    f"NCDR request returned HTTP 429 at {public_url}",
                    retry_after_seconds=_retry_after_seconds(
                        retry_after,
                        now=now or datetime.now(UTC),
                    ),
                )
            else:
                failure = NcdrCapAlertFetchError(
                    f"NCDR request returned HTTP {exc.code} at {public_url}"
                )
        except Exception:  # noqa: BLE001 - sanitize malformed HTTP error metadata
            failure = NcdrCapAlertFetchError(f"NCDR request failed at {public_url}")
    except Exception:  # noqa: BLE001 - complete untrusted transport boundary
        failure = NcdrCapAlertFetchError(f"NCDR request failed at {public_url}")
    if failure is not None:
        raise failure
    if type(body) is not bytes:
        raise NcdrCapAlertFetchError(f"NCDR request failed at {public_url}")
    if len(body) > MAX_CAP_BYTES:
        raise NcdrCapAlertFetchError(f"NCDR response exceeds the 2 MiB limit at {public_url}")
    return body


def _retry_after_seconds(value: str | None, *, now: datetime) -> int | None:
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
        seconds = math.ceil((retry_at.astimezone(UTC) - now.astimezone(UTC)).total_seconds())
    return min(3600, max(0, seconds))
