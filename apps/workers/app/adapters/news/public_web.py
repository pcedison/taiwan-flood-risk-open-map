from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app.adapters._helpers import optional_str, parse_datetime, stable_evidence_id
from app.adapters.contracts import (
    AdapterMetadata,
    AdapterRunResult,
    EventType,
    IngestionStatus,
    NormalizedEvidence,
    RawSourceItem,
    SourceFamily,
)
from app.classifiers.taiwan_locations import extract_taiwan_location_terms


FetchJson = Callable[[str], Mapping[str, Any]]
Sleep = Callable[[float], None]

GDELT_MAX_RECORDS_PER_QUERY = 250
_GDELT_METADATA_FIELDS = frozenset(
    {
        "url",
        "title",
        "seendate",
        "published_at",
        "domain",
        "sourcecountry",
        "language",
    }
)


@dataclass(frozen=True)
class GdeltQueryPlace:
    term: str
    lat: float
    lng: float
    scope: str
    canonical_name: str | None = None
    precision: str | None = None
    source_key: str | None = None
    source_record_id: str | None = None


class GdeltRateLimitError(RuntimeError):
    """Raised when GDELT asks this client to stop sending requests."""


class SamplePublicWebNewsAdapter:
    metadata = AdapterMetadata(
        key="news.public_web.sample",
        family=SourceFamily.NEWS,
        enabled_by_default=False,
        display_name="Sample news/public web adapter",
    )

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
                source_id=str(record["id"]),
                source_url=str(record["url"]),
                fetched_at=self._fetched_at,
                payload=record,
                raw_snapshot_key=self._raw_snapshot_key,
            )
            for record in self._records
        )

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        payload = raw_item.payload
        title = str(payload.get("title", "")).strip()
        summary = str(payload.get("summary", "")).strip()
        published_at = parse_datetime(payload.get("published_at"))

        if not title or not summary or published_at is None:
            return None

        evidence_id = stable_evidence_id(self.metadata.key, raw_item.source_id)
        return NormalizedEvidence(
            evidence_id=evidence_id,
            adapter_key=self.metadata.key,
            source_family=self.metadata.family,
            event_type=EventType.FLOOD_REPORT,
            source_id=raw_item.source_id,
            source_url=raw_item.source_url,
            source_title=title,
            source_timestamp=published_at,
            fetched_at=raw_item.fetched_at,
            summary=summary,
            location_text=optional_str(payload.get("location_text")),
            confidence=float(payload.get("confidence", 0.5)),
            status=IngestionStatus.NORMALIZED,
            attribution=optional_str(payload.get("attribution")),
            tags=tuple(str(tag) for tag in payload.get("tags", ())),
        )

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


class GdeltPublicNewsBackfillAdapter:
    metadata = AdapterMetadata(
        key="news.public_web.gdelt_backfill",
        family=SourceFamily.NEWS,
        enabled_by_default=False,
        display_name="GDELT public-news historical flood backfill adapter",
        terms_review_required=True,
    )

    endpoint = "https://api.gdeltproject.org/api/v2/doc/doc"

    def __init__(
        self,
        queries: Iterable[str],
        *,
        fetched_at: datetime,
        start_datetime: datetime,
        end_datetime: datetime,
        max_records_per_query: int = 250,
        request_cadence_seconds: int = 0,
        query_places: Iterable[GdeltQueryPlace] = (),
        require_query_place_match: bool = False,
        progress_log_interval: int = 0,
        fetch_json: FetchJson | None = None,
        sleep: Sleep | None = None,
        raw_snapshot_key: str | None = None,
    ) -> None:
        self._queries = tuple(query for query in queries if query.strip())
        self._fetched_at = fetched_at
        self._start_datetime = start_datetime
        self._end_datetime = end_datetime
        self._max_records_per_query = _clamp_gdelt_max_records(max_records_per_query)
        self._request_cadence_seconds = max(0, request_cadence_seconds)
        self._query_places = _dedupe_query_places(query_places)
        self._require_query_place_match = require_query_place_match
        self._progress_log_interval = max(0, progress_log_interval)
        self._fetch_json = fetch_json or _fetch_json
        self._sleep = sleep or time.sleep
        self._raw_snapshot_key = raw_snapshot_key

    def fetch(self) -> tuple[RawSourceItem, ...]:
        raw_items: list[RawSourceItem] = []
        seen_urls: set[str] = set()
        query_count = len(self._queries)
        for index, query in enumerate(self._queries):
            query_index = index + 1
            self._log_progress(
                query_index=query_index,
                query_count=query_count,
                fetched_count=len(raw_items),
                phase="started",
            )
            if index > 0 and self._request_cadence_seconds > 0:
                self._sleep(float(self._request_cadence_seconds))
            url = _gdelt_url(
                self.endpoint,
                query=query,
                start_datetime=self._start_datetime,
                end_datetime=self._end_datetime,
                max_records=self._max_records_per_query,
            )
            try:
                payload = self._fetch_json(url)
            except HTTPError as exc:
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                self._log_progress(
                    query_index=query_index,
                    query_count=query_count,
                    fetched_count=len(raw_items),
                    phase="failed",
                    error_type=exc.__class__.__name__,
                    error_status=exc.code,
                    retry_after=retry_after,
                )
                if exc.code == 429:
                    raise GdeltRateLimitError(
                        _rate_limit_message(retry_after=retry_after)
                    ) from exc
                continue
            except Exception as exc:
                self._log_progress(
                    query_index=query_index,
                    query_count=query_count,
                    fetched_count=len(raw_items),
                    phase="failed",
                    error_type=exc.__class__.__name__,
                )
                continue
            articles = payload.get("articles", ()) if isinstance(payload, Mapping) else ()
            for article in articles:
                if not isinstance(article, Mapping):
                    continue
                article_url = str(article.get("url", "")).strip()
                if not article_url or article_url in seen_urls:
                    continue
                seen_urls.add(article_url)
                article_payload = _metadata_only_article_payload(article)
                matched_place = _match_query_place(article_payload, self._query_places)
                if matched_place is not None:
                    article_payload = {
                        **article_payload,
                        **_query_place_payload(matched_place),
                    }
                raw_items.append(
                    RawSourceItem(
                        source_id=_source_id(article_url),
                        source_url=article_url,
                        fetched_at=self._fetched_at,
                        payload={
                            **article_payload,
                            "backfill_query": query,
                            "query_url": url,
                        },
                        raw_snapshot_key=self._raw_snapshot_key,
                    )
                )
            self._log_progress(
                query_index=query_index,
                query_count=query_count,
                fetched_count=len(raw_items),
                phase="completed",
            )
        return tuple(raw_items)

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        payload = raw_item.payload
        title = str(payload.get("title", "")).strip()
        if not title:
            return None

        has_query_place = isinstance(payload.get("geometry"), Mapping)
        if self._require_query_place_match and not has_query_place:
            return None

        published_at = parse_datetime(payload.get("seendate") or payload.get("published_at"))
        if published_at is None:
            return None

        location_terms = extract_taiwan_location_terms(
            _location_extraction_text(payload)
        )
        summary = _summary_from_article(payload, location_terms)
        if not summary:
            return None

        return NormalizedEvidence(
            evidence_id=stable_evidence_id(self.metadata.key, raw_item.source_id),
            adapter_key=self.metadata.key,
            source_family=self.metadata.family,
            event_type=EventType.FLOOD_REPORT,
            source_id=raw_item.source_id,
            source_url=raw_item.source_url,
            source_title=title,
            source_timestamp=published_at,
            fetched_at=raw_item.fetched_at,
            summary=summary,
            location_text=optional_str(payload.get("location_text"))
            or (", ".join(location_terms) if location_terms else None),
            confidence=_article_confidence(payload, location_terms),
            status=IngestionStatus.NORMALIZED,
            attribution=optional_str(payload.get("domain")),
            tags=("flood-history", "public-news", "backfill"),
        )

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

    def _log_progress(
        self,
        *,
        query_index: int,
        query_count: int,
        fetched_count: int,
        phase: str,
        error_type: str | None = None,
        error_status: int | None = None,
        retry_after: str | None = None,
    ) -> None:
        if self._progress_log_interval <= 0:
            return
        if not _should_log_progress(
            query_index=query_index,
            query_count=query_count,
            interval=self._progress_log_interval,
        ):
            return
        payload: dict[str, Any] = {
            "event": "gdelt_backfill.progress",
            "adapter_key": self.metadata.key,
            "phase": phase,
            "query_index": query_index,
            "query_count": query_count,
            "fetched_count": fetched_count,
            "metadata_only": True,
        }
        if error_type is not None:
            payload["error_type"] = error_type
        if error_status is not None:
            payload["error_status"] = error_status
        if retry_after:
            payload["retry_after"] = retry_after
        print(
            json.dumps(payload, sort_keys=True),
            flush=True,
        )


def _gdelt_url(
    endpoint: str,
    *,
    query: str,
    start_datetime: datetime,
    end_datetime: datetime,
    max_records: int,
) -> str:
    params = urlencode(
        {
            "query": query,
            "mode": "ArtList",
            "format": "json",
            "maxrecords": _clamp_gdelt_max_records(max_records),
            "startdatetime": start_datetime.strftime("%Y%m%d%H%M%S"),
            "enddatetime": end_datetime.strftime("%Y%m%d%H%M%S"),
        }
    )
    return f"{endpoint}?{params}"


def _fetch_json(url: str) -> Mapping[str, Any]:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "FloodRiskTaiwan/0.1 public-news-backfill",
        },
        method="GET",
    )
    with urlopen(request, timeout=20) as response:
        payload: Any = json.loads(response.read().decode("utf-8"))
    return payload if isinstance(payload, Mapping) else {}


def _source_id(url: str) -> str:
    return "gdelt_" + sha256(url.encode("utf-8")).hexdigest()[:24]


def _clamp_gdelt_max_records(max_records: int) -> int:
    return max(1, min(max_records, GDELT_MAX_RECORDS_PER_QUERY))


def _should_log_progress(*, query_index: int, query_count: int, interval: int) -> bool:
    if interval <= 0:
        return False
    return query_index == 1 or query_index == query_count or query_index % interval == 0


def _rate_limit_message(*, retry_after: str | None) -> str:
    if retry_after:
        return f"GDELT returned HTTP 429 Too Many Requests; retry after {retry_after}"
    return "GDELT returned HTTP 429 Too Many Requests"


def _metadata_only_article_payload(article: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: article[key]
        for key in _GDELT_METADATA_FIELDS
        if key in article and optional_str(article.get(key)) is not None
    }


def _location_extraction_text(payload: Mapping[str, Any]) -> str:
    country_hint = "台灣" if str(payload.get("sourcecountry", "")).upper() == "TW" else ""
    return " ".join(
        part
        for part in (
            str(payload.get("title", "")),
            str(payload.get("location_text", "")),
            str(payload.get("backfill_query", "")),
            str(payload.get("domain", "")),
            country_hint,
        )
        if part
    )


def _summary_from_article(
    payload: Mapping[str, Any],
    location_terms: tuple[str, ...],
) -> str:
    title = str(payload.get("title", "")).strip()
    if not title:
        return ""
    location_text = optional_str(payload.get("location_text"))
    if location_text:
        return (
            "Public news title mentions a flood-related event and matched a controlled "
            f"Taiwan geocoder term: {location_text}. Title: {title}"
        )
    if location_terms:
        return f"Public news title mentions a flood-related event. Extracted locations: {', '.join(location_terms)}. Title: {title}"
    return f"Public news title mentions a flood-related event, but needs location enrichment. Title: {title}"


def _article_confidence(payload: Mapping[str, Any], location_terms: tuple[str, ...]) -> float:
    title = str(payload.get("title", ""))
    has_flood_keyword = any(keyword in title for keyword in ("淹水", "積水", "積淹水", "豪雨"))
    score = 0.5
    if has_flood_keyword:
        score += 0.18
    if location_terms:
        score += 0.16
    if isinstance(payload.get("geometry"), Mapping):
        score += 0.08
    if payload.get("domain"):
        score += 0.06
    return min(score, 0.9)


def _dedupe_query_places(places: Iterable[GdeltQueryPlace]) -> tuple[GdeltQueryPlace, ...]:
    deduped: dict[str, GdeltQueryPlace] = {}
    for place in places:
        term = place.term.strip()
        if not term:
            continue
        deduped.setdefault(_normalize_term(term), place)
    return tuple(sorted(deduped.values(), key=lambda item: len(item.term), reverse=True))


def _match_query_place(
    payload: Mapping[str, Any],
    places: tuple[GdeltQueryPlace, ...],
) -> GdeltQueryPlace | None:
    if not places:
        return None
    title = str(payload.get("title", ""))
    normalized_title = _normalize_term(title)
    if not normalized_title:
        return None
    for place in places:
        normalized_term = _normalize_term(place.term)
        if normalized_term and normalized_term in normalized_title:
            return place
    return None


def _query_place_payload(place: GdeltQueryPlace) -> dict[str, Any]:
    return {
        "location_text": place.canonical_name or place.term,
        "geometry": {"type": "Point", "coordinates": [place.lng, place.lat]},
        "query_place": {
            "term": place.term,
            "canonical_name": place.canonical_name,
            "scope": place.scope,
            "precision": place.precision,
            "source_key": place.source_key,
            "source_record_id": place.source_record_id,
            "coordinate_policy": "taiwan_geocoder_query_place_title_match",
        },
    }


def _normalize_term(value: str) -> str:
    return value.casefold().replace("臺", "台").replace(" ", "").strip()
