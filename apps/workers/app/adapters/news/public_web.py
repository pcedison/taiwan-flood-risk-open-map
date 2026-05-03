from __future__ import annotations

import json
from datetime import datetime
from hashlib import sha256
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urlencode
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
        fetch_json: FetchJson | None = None,
        raw_snapshot_key: str | None = None,
    ) -> None:
        self._queries = tuple(query for query in queries if query.strip())
        self._fetched_at = fetched_at
        self._start_datetime = start_datetime
        self._end_datetime = end_datetime
        self._max_records_per_query = _clamp_gdelt_max_records(max_records_per_query)
        self._fetch_json = fetch_json or _fetch_json
        self._raw_snapshot_key = raw_snapshot_key

    def fetch(self) -> tuple[RawSourceItem, ...]:
        raw_items: list[RawSourceItem] = []
        seen_urls: set[str] = set()
        for query in self._queries:
            url = _gdelt_url(
                self.endpoint,
                query=query,
                start_datetime=self._start_datetime,
                end_datetime=self._end_datetime,
                max_records=self._max_records_per_query,
            )
            payload = self._fetch_json(url)
            articles = payload.get("articles", ()) if isinstance(payload, Mapping) else ()
            for article in articles:
                if not isinstance(article, Mapping):
                    continue
                article_url = str(article.get("url", "")).strip()
                if not article_url or article_url in seen_urls:
                    continue
                seen_urls.add(article_url)
                article_payload = _metadata_only_article_payload(article)
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
        return tuple(raw_items)

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        payload = raw_item.payload
        title = str(payload.get("title", "")).strip()
        if not title:
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
            location_text=", ".join(location_terms) if location_terms else None,
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
    if payload.get("domain"):
        score += 0.06
    return min(score, 0.9)
