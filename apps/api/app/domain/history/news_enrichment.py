from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from functools import lru_cache
from hashlib import sha256
from html import unescape
from html.parser import HTMLParser
import json
import re
from time import monotonic
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, unquote, urlencode, urljoin, urlparse
from urllib.request import Request, urlopen
from uuid import NAMESPACE_URL, uuid5
from xml.etree.ElementTree import Element

from defusedxml import ElementTree

from app.domain.evidence import EvidenceUpsert
from app.domain.geocoding import extract_taiwan_search_location
from app.domain.history.location_context import nearest_public_news_location_context


FetchJson = Callable[[str, float], Mapping[str, Any]]
FetchText = Callable[[str, float], str]
ResolveUrl = Callable[[str, float], str | None]

GDELT_DOC_ENDPOINT = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_ON_DEMAND_ADAPTER_KEY = "news.public_web.gdelt_backfill"
PUBLIC_NEWS_ON_DEMAND_ADAPTER_KEY = "news.public_web.on_demand_search"
PUBLIC_WIKI_ON_DEMAND_ADAPTER_KEY = "news.public_web.wiki_search"
TAINAN_OFFICIAL_HISTORY_ADAPTER_KEY = "official.tainan.disaster_news"
TAIWAN_OFFICIAL_HISTORY_ADAPTER_KEY = "official.gov_tw.flood_citation"
GOOGLE_NEWS_RSS_ENDPOINT = "https://news.google.com/rss/search"
GOOGLE_NEWS_BATCH_EXECUTE_ENDPOINT = (
    "https://news.google.com/_/DotsSplashUi/data/batchexecute"
)
BING_NEWS_RSS_ENDPOINT = "https://www.bing.com/news/search"
BING_WEB_RSS_ENDPOINT = "https://www.bing.com/search"
TAINAN_CITY_NEWS_INDEX_URL = (
    "https://www.tainan.gov.tw/News.aspx?PageSize=200&n=13370&page=1&sms=9748"
)
ZH_WIKIPEDIA_API_ENDPOINT = "https://zh.wikipedia.org/w/api.php"
ZH_WIKIPEDIA_PAGE_ENDPOINT = "https://zh.wikipedia.org/wiki/"
ZH_WIKINEWS_API_ENDPOINT = "https://zh.wikinews.org/w/api.php"
ZH_WIKINEWS_PAGE_ENDPOINT = "https://zh.wikinews.org/wiki/"
WIKIMEDIA_REST_SEARCH_ENDPOINT = "https://api.wikimedia.org/core/v1/wikipedia/zh/search/page"
PRIMARY_FLOOD_TERMS = ("淹水", "積淹水", "積水", "水淹", "水災", "水患", "泡水")
CONTEXT_FLOOD_TERMS = (
    "豪雨",
    "暴雨",
    "颱風",
    "災情",
    "災損",
    "道路積水",
    "排水不及",
    "地下道",
    "封閉",
    "抽水",
    "低窪",
    "溢流",
    "一片汪洋",
)
TAIWAN_NEWS_FLOOD_TERMS = (*PRIMARY_FLOOD_TERMS, *CONTEXT_FLOOD_TERMS)
_TITLE_LOCATION_PATTERN = re.compile(
    r"[\u4e00-\u9fff]{1,18}(?:縣|市|區|鄉|鎮|里|村|路|街|大道|段|巷)"
)
_YEAR_MONTH_PATTERN = re.compile(
    r"(?P<year>20\d{2}|19\d{2})\s*(?:年|[-/])\s*(?P<month>1[0-2]|0?[1-9])"
)
_YEAR_PATTERN = re.compile(r"(20\d{2}|19\d{2})")
_GDELT_DATE_FORMATS = ("%Y%m%d%H%M%S", "%Y%m%dT%H%M%SZ", "%Y-%m-%dT%H:%M:%SZ")
_CITY_ALIASES = (
    "台北",
    "臺北",
    "新北",
    "桃園",
    "台中",
    "臺中",
    "台南",
    "臺南",
    "高雄",
    "基隆",
    "新竹",
    "苗栗",
    "彰化",
    "南投",
    "雲林",
    "嘉義",
    "屏東",
    "宜蘭",
    "花蓮",
    "台東",
    "臺東",
    "澎湖",
    "金門",
    "連江",
)
_ROAD_PATTERN = re.compile(
    r"[\u4e00-\u9fff]{1,18}(?:路|街|大道)"
    r"(?:[一二三四五六七八九十0-9]+段)?(?:\d+巷)?"
)


@dataclass(frozen=True)
class OnDemandNewsSearchResult:
    attempted: bool
    source_id: str
    message: str
    records: tuple[EvidenceUpsert, ...]
    health_status: Literal["healthy", "degraded", "failed", "disabled", "unknown"] = "unknown"


@dataclass(frozen=True)
class _SearchTarget:
    term: str
    scope: str
    source_weight: float


@dataclass(frozen=True)
class _WikiSource:
    api_url: str
    page_url: str
    domain: str
    api_kind: str


@dataclass(frozen=True)
class _LocationMatch:
    term: str
    basis: str


@dataclass(frozen=True)
class _SearchWindow:
    start: datetime
    end: datetime
    label: str


@dataclass(frozen=True)
class _TainanNewsRow:
    published_date: str
    title: str
    url: str


class _TainanNewsIndexParser(HTMLParser):
    """Parse only the three public metadata fields in the city-news table."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[_TainanNewsRow] = []
        self._row: dict[str, str] | None = None
        self._field: str | None = None
        self._field_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "tr":
            self._row = {}
            return
        if self._row is None:
            return
        if tag == "td":
            self._field = attributes.get("data-title")
            self._field_text = []
            return
        if tag == "a" and self._field == "標題":
            href = (attributes.get("href") or "").strip()
            if href:
                self._row["url"] = urljoin(TAINAN_CITY_NEWS_INDEX_URL, href)
            title = (attributes.get("title") or "").strip()
            if title:
                self._row["title"] = title

    def handle_data(self, data: str) -> None:
        if self._row is not None and self._field is not None:
            self._field_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self._row is not None and self._field is not None:
            text = " ".join("".join(self._field_text).split())
            if self._field == "刊登日期" and text:
                self._row["published_date"] = text
            elif self._field == "標題" and text and "title" not in self._row:
                self._row["title"] = text
            self._field = None
            self._field_text = []
            return
        if tag != "tr" or self._row is None:
            return
        if all(self._row.get(key) for key in ("published_date", "title", "url")):
            self.rows.append(
                _TainanNewsRow(
                    published_date=self._row["published_date"],
                    title=self._row["title"],
                    url=self._row["url"],
                )
            )
        self._row = None
        self._field = None
        self._field_text = []


class _GoogleNewsDecodeParser(HTMLParser):
    """Extract Google's signed redirect metadata without reading article bodies."""

    def __init__(self, article_id: str) -> None:
        super().__init__(convert_charrefs=True)
        self.article_id = article_id
        self.signature: str | None = None
        self.timestamp: str | None = None

    def handle_starttag(self, _tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if attributes.get("data-n-a-id") != self.article_id:
            return
        signature = (attributes.get("data-n-a-sg") or "").strip()
        timestamp = (attributes.get("data-n-a-ts") or "").strip()
        if signature and timestamp.isdigit():
            self.signature = signature
            self.timestamp = timestamp


_TAINAN_REVIEWED_INCIDENT_BOOTSTRAP = (
    _TainanNewsRow(
        published_date="115-08-24",
        title="黃偉哲視察安南、仁德淹水災情 盤點排水系統持續提升防洪韌性",
        url="https://www.tainan.gov.tw/News_Content.aspx?n=13370&s=8832256",
    ),
)

_OFFICIAL_TAIWAN_WEB_SUFFIXES = (".gov.tw", ".gov.taipei")
_OFFICIAL_HISTORY_LOOKBACK_YEARS = 7


_WIKI_SOURCES = (
    _WikiSource(
        WIKIMEDIA_REST_SEARCH_ENDPOINT,
        ZH_WIKIPEDIA_PAGE_ENDPOINT,
        "zh.wikipedia.org",
        "wikimedia_rest",
    ),
    _WikiSource(
        ZH_WIKIPEDIA_API_ENDPOINT,
        ZH_WIKIPEDIA_PAGE_ENDPOINT,
        "zh.wikipedia.org",
        "mediawiki_query",
    ),
    _WikiSource(
        ZH_WIKINEWS_API_ENDPOINT,
        ZH_WIKINEWS_PAGE_ENDPOINT,
        "zh.wikinews.org",
        "mediawiki_query",
    ),
)


def search_tainan_official_flood_news(
    *,
    location_text: str | None,
    lat: float,
    lng: float,
    radius_m: int,
    now: datetime,
    max_records: int = 3,
    timeout_seconds: float = 2.5,
    fetch_text: FetchText | None = None,
) -> OnDemandNewsSearchResult:
    """Find recent flood incidents in Tainan's official city-news index.

    Only the listing's title, publication date, and official URL are retained.
    A district-only match remains explicitly imprecise and is never labelled as
    a query-point observation.
    """

    context = nearest_public_news_location_context(
        lat=lat,
        lng=lng,
        radius_m=radius_m,
    )
    if context is None or "台南市" not in _normalize(context.name):
        return OnDemandNewsSearchResult(
            attempted=False,
            source_id="official-tainan-disaster-news",
            message="查詢點不在臺南市官方新聞補查範圍。",
            records=(),
            health_status="unknown",
        )

    query_location = extract_taiwan_search_location(location_text or "") or context.name
    relaxed_terms = _tainan_district_terms(context.name)
    if fetch_text is None:
        payload = _cached_tainan_news_index(
            int(monotonic() // 600),
            max(0.5, timeout_seconds),
        )
    else:
        payload = fetch_text(TAINAN_CITY_NEWS_INDEX_URL, max(0.5, timeout_seconds))
    live_rows = _tainan_news_rows(payload) if payload else ()
    rows_by_url: dict[str, _TainanNewsRow] = {}
    for row in (*live_rows, *_TAINAN_REVIEWED_INCIDENT_BOOTSTRAP):
        rows_by_url.setdefault(row.url, row)
    rows = tuple(rows_by_url.values())
    records: list[EvidenceUpsert] = []
    seen: set[tuple[str, str]] = set()
    oldest_allowed = now - timedelta(days=365 * 2)
    for row in rows:
        if not any(term in row.title for term in PRIMARY_FLOOD_TERMS):
            continue
        published_at = _parse_taiwan_roc_date(row.published_date)
        if published_at is None or published_at < oldest_allowed:
            continue
        if published_at > now + timedelta(days=1):
            continue
        record = _record_from_article(
            {
                "title": row.title,
                "url": row.url,
                "published_at": published_at,
                "domain": "www.tainan.gov.tw",
            },
            location=query_location,
            match_scope=_scope_for_term(query_location),
            target_source_weight=0.9,
            lat=lat,
            lng=lng,
            radius_m=radius_m,
            now=now,
            query_url=TAINAN_CITY_NEWS_INDEX_URL,
            search_window_label="official-tainan-city-news-latest-200",
            adapter_key=TAINAN_OFFICIAL_HISTORY_ADAPTER_KEY,
            source_prefix="tainan-official-news",
            raw_ref_prefix="tainan-official-news",
            ingestion_mode="on_demand_official_tainan_news",
            relaxed_location_terms=relaxed_terms,
            summary_source_label="臺南市政府新聞 metadata",
            source_type="official",
        )
        if record is None:
            continue
        match_scope = str(record.properties.get("location_match_scope") or "")
        match_term = str(record.properties.get("location_match_term") or context.name)
        dedupe_key = (record.url or "", match_term if match_scope == "admin_area" else "")
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        records.append(
            _official_tainan_record(
                record,
                context_lat=context.lat,
                context_lng=context.lng,
                match_scope=match_scope,
                match_term=match_term,
            )
        )
        if len(records) >= max(1, max_records):
            break

    if records:
        return OnDemandNewsSearchResult(
            attempted=True,
            source_id="official-tainan-disaster-news",
            message=(
                f"已補入 {len(records)} 筆臺南市政府近期積淹水事件 metadata。"
                if payload
                else (
                    f"臺南市政府新聞索引暫時無法回應；已使用隨版本審核的 {len(records)} 筆"
                    "官方 citation metadata。"
                )
            ),
            records=tuple(records),
            health_status="healthy" if payload else "degraded",
        )
    if not payload:
        return OnDemandNewsSearchResult(
            attempted=True,
            source_id="official-tainan-disaster-news",
            message="臺南市政府新聞索引暫時無法回應，且審核過的備援事件不符合查詢位置。",
            records=(),
            health_status="degraded",
        )
    return OnDemandNewsSearchResult(
        attempted=True,
        source_id="official-tainan-disaster-news",
        message="臺南市政府近期新聞未找到可通過行政區與淹水關鍵字比對的事件。",
        records=(),
        health_status="unknown",
    )


def search_taiwan_official_flood_citations(
    *,
    location_text: str | None,
    lat: float,
    lng: float,
    radius_m: int,
    now: datetime,
    max_records: int = 3,
    timeout_seconds: float = 3.0,
    fetch_text: FetchText | None = None,
    resolve_url: ResolveUrl | None = None,
    fetch_citation_text: FetchText | None = None,
) -> OnDemandNewsSearchResult:
    """Find recent Taiwan-wide flood citations on official government sites.

    This is a bounded miss-recovery lookup, not a claim of complete historical
    coverage. Every retained citation opens directly on an official Taiwan
    government host. Google News index links are retained only when their signed
    redirect metadata resolves to such a direct government page. When citation
    metadata omits the place name, a bounded direct-page read must verify the
    queried location. Article bodies are never stored.
    """

    context = nearest_public_news_location_context(
        lat=lat,
        lng=lng,
        radius_m=radius_m,
    )
    if context is None:
        return OnDemandNewsSearchResult(
            attempted=False,
            source_id="official-taiwan-government-citations",
            message="查詢點附近沒有可用的全臺行政區定位資料。",
            records=(),
            health_status="unknown",
        )

    query_location = extract_taiwan_search_location(location_text or "") or context.name
    targets = _official_history_search_targets(query_location, context.name)
    text_client = fetch_text or _fetch_text
    url_resolver = resolve_url or _resolve_google_news_url
    citation_text_client = fetch_citation_text or _fetch_official_citation_text
    deadline = monotonic() + max(0.5, timeout_seconds)
    coverage_start_year = now.year - _OFFICIAL_HISTORY_LOOKBACK_YEARS + 1
    oldest_allowed = datetime(coverage_start_year, 1, 1, tzinfo=now.tzinfo)
    relaxed_terms = _official_specific_admin_terms(context.name) or _rss_relaxed_location_terms(
        context.name
    )
    accepted: list[EvidenceUpsert] = []
    seen_urls: set[str] = set()
    errors = 0

    for target in targets:
        for feed_url in _official_history_rss_urls(
            target.term,
            now=now,
        ):
            remaining_seconds = deadline - monotonic()
            if remaining_seconds <= 0:
                errors += 1
                break
            payload = text_client(feed_url, min(1.5, max(0.45, remaining_seconds)))
            if not payload:
                errors += 1
                continue
            for article in _rss_articles(payload, feed_url=feed_url):
                article_url = str(article.get("url") or "")
                publisher_url = str(article.get("publisher_url") or "")
                match_text = _article_match_text(article)
                if not _official_history_text_qualifies(match_text):
                    continue
                published_at = _parse_public_news_datetime(article.get("published_at"))
                if published_at is None:
                    continue
                comparable = (
                    published_at
                    if published_at.tzinfo is not None
                    else published_at.replace(tzinfo=UTC)
                )
                if comparable < oldest_allowed or comparable > now + timedelta(days=1):
                    continue
                metadata_location_match = _location_match(
                    match_text,
                    target.term,
                    relaxed_location_terms=relaxed_terms,
                )
                needs_page_location_check = metadata_location_match is None

                citation_url = article_url
                if not _is_official_taiwan_web_url(citation_url):
                    # Publisher metadata is only a precondition for decoding a
                    # Google index item; it never authorizes the aggregator URL.
                    # Fail closed unless Google's signed metadata yields a direct
                    # Taiwan-government page that the user can open.
                    if not (
                        _is_google_news_article_url(article_url)
                        and _is_official_taiwan_web_url(publisher_url)
                    ):
                        continue
                    remaining_seconds = deadline - monotonic()
                    if remaining_seconds <= 0:
                        errors += 1
                        break
                    resolved_url = url_resolver(
                        article_url,
                        min(
                            1.4 if needs_page_location_check else 1.8,
                            max(
                                0.45,
                                remaining_seconds * 0.65
                                if needs_page_location_check
                                else remaining_seconds,
                            ),
                        ),
                    )
                    if not resolved_url or not _is_official_taiwan_web_url(resolved_url):
                        continue
                    citation_url = resolved_url

                location_verification = "citation_metadata"
                if needs_page_location_check:
                    remaining_seconds = deadline - monotonic()
                    if remaining_seconds <= 0:
                        errors += 1
                        break
                    citation_payload = citation_text_client(
                        citation_url,
                        min(0.9, max(0.35, remaining_seconds)),
                    )
                    if not citation_payload:
                        errors += 1
                        continue
                    if (
                        _location_match(
                            citation_payload,
                            target.term,
                            relaxed_location_terms=relaxed_terms,
                        )
                        is None
                    ):
                        continue
                    location_verification = "direct_official_page"

                official_article = {
                    **article,
                    "url": citation_url,
                    "context": target.term if needs_page_location_check else "",
                    "domain": _domain_from_url(citation_url),
                    "official_publisher_url": (
                        publisher_url
                        if _is_official_taiwan_web_url(publisher_url)
                        else citation_url
                    ),
                    "location_verification": location_verification,
                }
                record = _record_from_article(
                    official_article,
                    location=target.term,
                    match_scope=target.scope,
                    target_source_weight=0.9 if target.scope != "admin_area" else 0.74,
                    lat=lat,
                    lng=lng,
                    radius_m=radius_m,
                    now=now,
                    query_url=feed_url,
                    search_window_label=(
                        f"rolling-{_OFFICIAL_HISTORY_LOOKBACK_YEARS}-year-official-citations"
                    ),
                    adapter_key=TAIWAN_OFFICIAL_HISTORY_ADAPTER_KEY,
                    source_prefix="official-gov-tw-citation",
                    raw_ref_prefix="official-gov-tw-citation",
                    ingestion_mode="on_demand_official_government_citation",
                    relaxed_location_terms=relaxed_terms,
                    summary_source_label="臺灣政府機關公開頁面 citation metadata",
                    source_type="official",
                )
                if record is None or record.url is None or record.url in seen_urls:
                    continue
                seen_urls.add(record.url)
                accepted.append(
                    _official_government_record(
                        record,
                        context_lat=context.lat,
                        context_lng=context.lng,
                        now=now,
                    )
                )
            if len(accepted) >= max(1, max_records) and _has_recent_official_history(
                accepted,
                now=now,
            ):
                break
        if (
            len(accepted) >= max(1, max_records)
            and _has_recent_official_history(accepted, now=now)
        ) or deadline - monotonic() <= 0:
            break

    if accepted:
        selected = tuple(
            sorted(
                accepted,
                key=_official_history_record_time,
                reverse=True,
            )[: max(1, max_records)]
        )
        return OnDemandNewsSearchResult(
            attempted=True,
            source_id="official-taiwan-government-citations",
            message=(
                f"已補入 {len(selected)} 筆全臺政府機關近期積淹水 citation metadata；"
                "此查找不代表完整歷史覆蓋。"
            ),
            records=selected,
            health_status="healthy",
        )
    return OnDemandNewsSearchResult(
        attempted=True,
        source_id="official-taiwan-government-citations",
        message=(
            "政府機關公開頁面索引暫時無法完整回應。"
            if errors
            else "近七年政府機關公開頁面未找到可通過地點與淹水條件的事件。"
        ),
        records=(),
        health_status="degraded" if errors else "unknown",
    )


def search_public_flood_news(
    *,
    location_text: str | None,
    lat: float,
    lng: float,
    radius_m: int,
    now: datetime,
    max_records: int,
    timeout_seconds: float,
    fetch_json: FetchJson | None = None,
    fetch_text: FetchText | None = None,
    fetch_wiki_json: FetchJson | None = None,
) -> OnDemandNewsSearchResult:
    location = extract_taiwan_search_location(location_text or "")
    if not location:
        return OnDemandNewsSearchResult(
            attempted=False,
            source_id="on-demand-public-news",
            message="沒有可用地名，未啟動公開新聞補查。",
            records=(),
            health_status="unknown",
        )

    client = fetch_json or _fetch_json
    text_client = (
        fetch_text if fetch_text is not None else (_fetch_text if fetch_json is None else None)
    )
    wiki_client = (
        fetch_wiki_json
        if fetch_wiki_json is not None
        else (_fetch_json if fetch_json is None else None)
    )
    search_windows = _search_windows(location_text or "", now)
    accepted: list[EvidenceUpsert] = []
    seen_urls: set[str] = set()
    query_errors = 0
    timed_out = False
    deadline = monotonic() + max(0.5, timeout_seconds)
    rss_attempted = False
    rss_errors = 0
    wiki_attempted = False
    wiki_errors = 0
    if wiki_client is not None and max_records > 1:
        wiki_attempted = True
        wiki_records, wiki_errors = _search_public_wiki(
            location=location,
            location_text=location_text or "",
            lat=lat,
            lng=lng,
            radius_m=radius_m,
            now=now,
            max_records=1,
            deadline=min(deadline, monotonic() + _wiki_budget_seconds(timeout_seconds)),
            fetch_json=wiki_client,
            seen_urls=seen_urls,
        )
        accepted.extend(wiki_records)

    if text_client is not None:
        rss_max_records = max_records - len(accepted)
        rss_attempted = True
        if rss_max_records > 0:
            rss_records, rss_errors = _search_public_news_rss(
                location=location,
                location_text=location_text or "",
                lat=lat,
                lng=lng,
                radius_m=radius_m,
                now=now,
                max_records=rss_max_records,
                deadline=min(deadline, monotonic() + _rss_front_budget_seconds(timeout_seconds)),
                fetch_text=text_client,
                seen_urls=seen_urls,
            )
            accepted.extend(rss_records)

    if wiki_client is not None and not wiki_attempted and len(accepted) < max_records:
        wiki_attempted = True
        wiki_records, wiki_errors = _search_public_wiki(
            location=location,
            location_text=location_text or "",
            lat=lat,
            lng=lng,
            radius_m=radius_m,
            now=now,
            max_records=max_records - len(accepted),
            deadline=min(deadline, monotonic() + _wiki_budget_seconds(timeout_seconds)),
            fetch_json=wiki_client,
            seen_urls=seen_urls,
        )
        accepted.extend(wiki_records)

    per_query_max_records = _per_query_max_records(max_records)
    if not accepted:
        for target in _search_targets(location):
            for search_window in search_windows:
                for query in _gdelt_queries(target.term, scope=target.scope):
                    remaining_seconds = deadline - monotonic()
                    if remaining_seconds <= 0:
                        timed_out = True
                        break
                    url = _gdelt_url(
                        query=query,
                        start_datetime=search_window.start,
                        end_datetime=search_window.end,
                        max_records=per_query_max_records,
                    )
                    payload = client(url, min(timeout_seconds, max(0.5, remaining_seconds)))
                    if not payload:
                        query_errors += 1
                        continue
                    for article in _articles(payload):
                        record = _record_from_article(
                            article,
                            location=target.term,
                            match_scope=target.scope,
                            target_source_weight=target.source_weight,
                            lat=lat,
                            lng=lng,
                            radius_m=radius_m,
                            now=now,
                            query_url=url,
                            search_window_label=search_window.label,
                        )
                        if record is None or record.url is None or record.url in seen_urls:
                            continue
                        seen_urls.add(record.url)
                        accepted.append(record)
                        if len(accepted) >= max_records:
                            break
                    if len(accepted) >= max_records:
                        break
                if timed_out:
                    break
                if len(accepted) >= max_records:
                    break
            if timed_out:
                break
            if len(accepted) >= max_records:
                break

    if accepted:
        return OnDemandNewsSearchResult(
            attempted=True,
            source_id="on-demand-public-news",
            message=f"已從公開新聞/百科索引補查並整理 {len(accepted)} 筆候選淹水事件。",
            records=tuple(accepted),
            health_status="healthy",
        )
    if (
        timed_out
        or query_errors
        or (rss_attempted and rss_errors)
        or (wiki_attempted and wiki_errors)
    ):
        message = "公開新聞、RSS 或百科索引暫時無法完整回應；保留既有資料，不阻塞風險查詢。"
        health_status: Literal["healthy", "degraded", "failed", "disabled", "unknown"] = "degraded"
    else:
        message = "公開新聞、RSS 與百科索引未找到可通過地點與淹水關鍵字比對的候選事件。"
        health_status = "unknown"
    return OnDemandNewsSearchResult(
        attempted=True,
        source_id="on-demand-public-news",
        message=message,
        records=(),
        health_status=health_status,
    )


def _gdelt_queries(location: str, *, scope: str) -> tuple[str, ...]:
    quoted_location = f'"{location}"' if len(location) > 2 else location
    primary_clause = _or_clause(PRIMARY_FLOOD_TERMS)
    context_clause = _or_clause(CONTEXT_FLOOD_TERMS)
    queries = [
        f"{quoted_location} {primary_clause} sourcecountry:TW",
    ]
    if scope != "admin_area":
        queries.append(f"{quoted_location} {context_clause} sourcecountry:TW")
    queries.append(
        f"{quoted_location} {_or_clause(('災情', '道路積水', '地下道', '封閉'))} sourcecountry:TW"
    )
    return _dedupe(queries, limit=4)


def _search_targets(location: str) -> tuple[_SearchTarget, ...]:
    terms: list[_SearchTarget] = [_SearchTarget(location, "exact", 0.86)]
    for term in _admin_and_road_terms(location):
        scope = _scope_for_term(term)
        source_weight = 0.78 if scope == "road" else 0.68
        terms.append(_SearchTarget(term, scope, source_weight))
    deduped: list[_SearchTarget] = []
    seen: set[str] = set()
    for target in terms:
        normalized = _normalize(target.term)
        if len(normalized) < 2 or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(target)
        if len(deduped) >= 10:
            break
    return tuple(deduped)


def _admin_and_road_terms(location: str) -> tuple[str, ...]:
    normalized = _normalize(location)
    terms: list[str] = []
    for match in _ROAD_PATTERN.finditer(normalized):
        road = match.group(0)
        terms.append(road)
        trimmed_road = _trim_admin_prefix(road)
        if trimmed_road != road:
            terms.append(trimmed_road)
        for city in _CITY_ALIASES:
            if road.startswith(city) and len(road) > len(city) + 2:
                terms.append(road[len(city) :])
                terms.extend(_city_tail_district_terms(city, road[len(city) :]))
    for marker in ("區", "鄉", "鎮", "市", "縣"):
        if marker in normalized:
            prefix = normalized.split(marker, 1)[0] + marker
            terms.append(prefix)
    return _dedupe(terms, limit=14)


def _trim_admin_prefix(value: str) -> str:
    for marker in ("縣", "市", "區", "鄉", "鎮", "里", "村"):
        if marker in value:
            value = value.rsplit(marker, 1)[-1]
    return value


def _city_tail_district_terms(city: str, tail: str) -> tuple[str, ...]:
    terms: list[str] = []
    for district_length in (2, 3, 4):
        if len(tail) <= district_length + 1:
            continue
        district = tail[:district_length]
        road = tail[district_length:]
        if not _ROAD_PATTERN.fullmatch(road):
            continue
        terms.append(f"{district}{road}")
        terms.append(f"{district}區{road}")
        terms.append(f"{city}{district}區{road}")
        terms.append(f"{city}{district}")
        terms.append(f"{district}區")
        terms.append(f"{city}{district}區")
    return _dedupe(terms, limit=8)


def _scope_for_term(term: str) -> str:
    if term.endswith(("區", "鄉", "鎮", "市", "縣")):
        return "admin_area"
    if any(marker in term for marker in ("路", "街", "大道")):
        return "road"
    return "admin_area"


def _gdelt_url(
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
            "maxrecords": max(1, min(max_records, 50)),
            "startdatetime": start_datetime.strftime("%Y%m%d%H%M%S"),
            "enddatetime": end_datetime.strftime("%Y%m%d%H%M%S"),
        }
    )
    return f"{GDELT_DOC_ENDPOINT}?{params}"


def _per_query_max_records(max_records: int) -> int:
    return max(max_records, min(max_records * 4, 20))


def _rss_front_budget_seconds(timeout_seconds: float) -> float:
    return min(3.0, max(1.5, timeout_seconds * 0.65))


def _wiki_budget_seconds(timeout_seconds: float) -> float:
    return min(1.8, max(0.8, timeout_seconds * 0.35))


def _fetch_json(url: str, timeout_seconds: float) -> Mapping[str, Any]:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "FloodRiskTaiwan/0.1 (https://floodrisk.cc; public citation metadata)",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=max(0.5, timeout_seconds)) as response:
            payload: Any = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _fetch_text(url: str, timeout_seconds: float) -> str:
    request = Request(
        url,
        headers={
            "Accept": "application/rss+xml, application/xml, text/xml, text/html",
            "User-Agent": "FloodRiskTaiwan/0.1 on-demand-public-news-rss",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=max(0.5, timeout_seconds)) as response:
            return response.read().decode("utf-8", errors="replace")
    except (HTTPError, URLError, TimeoutError, UnicodeDecodeError):
        return ""


def _fetch_official_citation_text(url: str, timeout_seconds: float) -> str:
    if not _is_official_taiwan_web_url(url):
        return ""
    request = Request(
        url,
        headers={
            "Accept": "text/html, application/xhtml+xml",
            "User-Agent": "FloodRiskTaiwan/0.1 official-citation-location-verifier",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=max(0.3, timeout_seconds)) as response:
            payload = response.read(1_048_577)
        if len(payload) > 1_048_576:
            return ""
        return payload.decode("utf-8", errors="replace")
    except (HTTPError, URLError, TimeoutError, UnicodeDecodeError):
        return ""


@lru_cache(maxsize=4)
def _cached_tainan_news_index(_ten_minute_bucket: int, timeout_seconds: float) -> str:
    return _fetch_text(TAINAN_CITY_NEWS_INDEX_URL, timeout_seconds)


def _articles(payload: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    articles = payload.get("articles", ())
    if not isinstance(articles, list):
        return ()
    return tuple(article for article in articles if isinstance(article, Mapping))


def _search_public_news_rss(
    *,
    location: str,
    location_text: str,
    lat: float,
    lng: float,
    radius_m: int,
    now: datetime,
    max_records: int,
    deadline: float,
    fetch_text: FetchText,
    seen_urls: set[str],
) -> tuple[list[EvidenceUpsert], int]:
    accepted: list[EvidenceUpsert] = []
    errors = 0
    for target in _rss_search_targets(location):
        for feed_url in _public_news_rss_urls(target.term, location_text=location_text, now=now):
            remaining_seconds = deadline - monotonic()
            if remaining_seconds <= 0:
                errors += 1
                return accepted, errors
            payload = fetch_text(feed_url, min(1.2, max(0.45, remaining_seconds)))
            if not payload:
                errors += 1
                continue
            for article in _rss_articles(payload, feed_url=feed_url):
                record = _record_from_article(
                    article,
                    location=target.term,
                    match_scope=target.scope,
                    target_source_weight=_rss_source_weight(target.scope),
                    lat=lat,
                    lng=lng,
                    radius_m=radius_m,
                    now=now,
                    query_url=feed_url,
                    search_window_label="public-news-rss",
                    adapter_key=PUBLIC_NEWS_ON_DEMAND_ADAPTER_KEY,
                    source_prefix="public-news-rss",
                    raw_ref_prefix="public-news-rss",
                    ingestion_mode="on_demand_public_news_rss",
                    relaxed_location_terms=_rss_relaxed_location_terms(location_text or location),
                )
                if record is None or record.url is None or record.url in seen_urls:
                    continue
                seen_urls.add(record.url)
                accepted.append(record)
                if len(accepted) >= max_records:
                    return accepted, errors
        if accepted:
            return accepted, errors
    return accepted, errors


def _search_public_wiki(
    *,
    location: str,
    location_text: str,
    lat: float,
    lng: float,
    radius_m: int,
    now: datetime,
    max_records: int,
    deadline: float,
    fetch_json: FetchJson,
    seen_urls: set[str],
) -> tuple[list[EvidenceUpsert], int]:
    accepted: list[EvidenceUpsert] = []
    errors = 0
    seen_titles: set[str] = set()
    relaxed_location_terms = _rss_relaxed_location_terms(location_text or location)
    for target in _wiki_search_targets(location):
        for query in _public_wiki_queries(target.term, location_text=location_text, now=now):
            for source in _WIKI_SOURCES:
                remaining_seconds = deadline - monotonic()
                if remaining_seconds <= 0:
                    errors += 1
                    return accepted, errors
                payload = fetch_json(
                    _wiki_search_url(source, query),
                    min(1.2, max(0.45, remaining_seconds)),
                )
                if not payload:
                    errors += 1
                    continue
                for article in _wiki_articles(payload, source=source, query=query):
                    normalized_title = _normalize(str(article.get("title", "")))
                    if normalized_title in seen_titles:
                        continue
                    record = _record_from_article(
                        article,
                        location=target.term,
                        match_scope=target.scope,
                        target_source_weight=_wiki_source_weight(target.scope),
                        lat=lat,
                        lng=lng,
                        radius_m=radius_m,
                        now=now,
                        query_url=str(article.get("query_url", "")),
                        search_window_label="public-wiki-search",
                        adapter_key=PUBLIC_WIKI_ON_DEMAND_ADAPTER_KEY,
                        source_prefix="public-wiki",
                        raw_ref_prefix="public-wiki",
                        ingestion_mode="on_demand_public_wiki",
                        relaxed_location_terms=relaxed_location_terms,
                        summary_source_label="公開 wiki/百科 metadata",
                    )
                    if record is None or record.url is None or record.url in seen_urls:
                        continue
                    seen_titles.add(normalized_title)
                    seen_urls.add(record.url)
                    accepted.append(record)
                    if len(accepted) >= max_records:
                        return accepted, errors
        if accepted:
            return accepted, errors
    return accepted, errors


def _public_news_rss_urls(
    location: str,
    *,
    location_text: str,
    now: datetime,
) -> tuple[str, ...]:
    queries = _public_news_rss_queries(location, location_text=location_text, now=now)
    urls: list[str] = []
    for query in queries:
        urls.append(
            f"{GOOGLE_NEWS_RSS_ENDPOINT}?"
            f"{urlencode({'q': query, 'hl': 'zh-TW', 'gl': 'TW', 'ceid': 'TW:zh-Hant'})}"
        )
        urls.append(
            f"{BING_NEWS_RSS_ENDPOINT}?{urlencode({'q': query, 'format': 'rss', 'mkt': 'zh-TW'})}"
        )
    return _dedupe(urls, limit=16)


def _official_history_rss_urls(
    location: str,
    *,
    now: datetime,
) -> tuple[str, ...]:
    coverage_start_year = now.year - _OFFICIAL_HISTORY_LOOKBACK_YEARS + 1
    rolling_years = tuple(range(now.year, coverage_start_year - 1, -1))
    year_clause = " OR ".join(str(year) for year in rolling_years)
    queries = _dedupe(
        (
            f"{location} 積淹水 ({year_clause}) site:gov.tw",
            f"{location} 淹水 site:gov.tw",
            f"{location} 淹水 政府 ({year_clause})",
        ),
        limit=3,
    )
    google_urls = [
        (
            f"{GOOGLE_NEWS_RSS_ENDPOINT}?"
            f"{urlencode({'q': query, 'hl': 'zh-TW', 'gl': 'TW', 'ceid': 'TW:zh-Hant'})}"
        )
        for query in queries
    ]
    bing_urls = [
        (
            f"{BING_WEB_RSS_ENDPOINT}?"
            f"{urlencode({'q': query, 'format': 'rss', 'setlang': 'zh-hant', 'cc': 'tw'})}"
        )
        for query in queries
    ]
    # Google News exposes the publisher metadata used by the official-domain
    # gate.  Try every reviewed Google query before the noisier Bing web RSS
    # fallback so a slow/irrelevant Bing response cannot consume the deadline
    # before the explicit rolling-year query runs.
    return _dedupe([*google_urls, *bing_urls], limit=6)


def _official_history_record_time(record: EvidenceUpsert) -> datetime:
    value = record.observed_at or record.occurred_at
    if value is None:
        return datetime.min.replace(tzinfo=UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _official_history_text_qualifies(text: str) -> bool:
    normalized = _normalize(text)
    if not any(_normalize(term) in normalized for term in PRIMARY_FLOOD_TERMS):
        return False
    planning_phrases = (
        "淹水潛勢",
        "降低淹水",
        "改善淹水",
        "避免淹水",
        "預防淹水",
        "防止淹水",
        "防範淹水",
        "無淹水",
        "未淹水",
        "汛期水患",
        "防洪工程",
        "排水工程",
        "堤防工程",
        "治理工程",
    )
    incident_phrases = (
        "災情",
        "受災",
        "救助",
        "慰助",
        "災後",
        "封閉",
        "阻斷",
        "退水",
        "進水",
        "泡水",
        "水淹",
        "道路積水",
        "積淹水",
    )
    event_markers = (
        *incident_phrases,
        "豪雨",
        "暴雨",
        "大雨",
        "颱風",
        "發生",
        "造成",
        "多處",
        "勘災",
        "視察",
    )
    if any(phrase in normalized for phrase in planning_phrases) and not any(
        phrase in normalized for phrase in incident_phrases
    ):
        return False
    return any(marker in normalized for marker in event_markers)


def _has_recent_official_history(
    records: list[EvidenceUpsert],
    *,
    now: datetime,
) -> bool:
    cutoff = now - timedelta(days=30)
    future_limit = now + timedelta(days=1)
    return any(
        cutoff <= _official_history_record_time(record) <= future_limit
        for record in records
    )


def _official_history_search_targets(
    query_location: str,
    context_name: str,
) -> tuple[_SearchTarget, ...]:
    # A precise road query can produce many increasingly broad road aliases.
    # Searching those first used the entire on-demand deadline before the
    # district fallback ran, so the same district could show a recent event for
    # an administrative query but fall back to a decade-old point for an exact
    # address.  Lead with one canonical township/district target: this is the
    # minimum reliable nationwide recall layer, while road matches remain a
    # higher-precision follow-up.
    admin_area_term = _official_admin_area_term(context_name)
    admin_area_targets = (
        (_SearchTarget(admin_area_term, "admin_area", 0.68),)
        if admin_area_term
        else ()
    )
    query_is_admin_only = _ROAD_PATTERN.search(_normalize(query_location)) is None
    query_targets = tuple(
        _SearchTarget(
            target.term,
            "admin_area" if query_is_admin_only else target.scope,
            min(target.source_weight, 0.68) if query_is_admin_only else target.source_weight,
        )
        for target in _rss_search_targets(query_location)
    )
    context_targets = tuple(
        _SearchTarget(target.term, "admin_area", min(target.source_weight, 0.68))
        for target in _rss_search_targets(context_name)
    )
    candidates = [*admin_area_targets, *query_targets, *context_targets]
    required_admin_terms = _official_specific_admin_terms(context_name)
    deduped: list[_SearchTarget] = []
    seen: set[str] = set()
    for target in candidates:
        normalized = _normalize(target.term)
        if len(normalized) < 2 or normalized in seen:
            continue
        if (
            target.scope == "admin_area"
            and required_admin_terms
            and not any(_normalize(term) in normalized for term in required_admin_terms)
        ):
            continue
        seen.add(normalized)
        deduped.append(target)
        if len(deduped) >= 8:
            break
    return tuple(deduped)


def _official_admin_area_term(context_name: str) -> str:
    normalized = _normalize(context_name)
    endpoints = [normalized.rfind(suffix) for suffix in ("區", "鄉", "鎮", "市")]
    end = max(endpoints, default=-1)
    if end < 0:
        return normalized
    return normalized[: end + 1]


def _official_specific_admin_terms(context_name: str) -> tuple[str, ...]:
    normalized = _normalize(context_name)
    terms: list[str] = []
    for suffix in ("區", "鄉", "鎮"):
        end = normalized.rfind(suffix)
        if end < 0:
            continue
        value = normalized[: end + 1]
        for parent_suffix in ("縣", "市"):
            if parent_suffix in value:
                value = value.rsplit(parent_suffix, 1)[-1]
        if len(value) >= 2:
            terms.extend((value, value.removesuffix(suffix)))
    return tuple(term for term in _dedupe(terms, limit=6) if len(term) >= 2)


def _is_official_taiwan_web_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    if parsed.scheme != "https":
        return False
    host = (parsed.hostname or "").casefold().rstrip(".")
    return host == "gov.tw" or any(
        host.endswith(suffix) for suffix in _OFFICIAL_TAIWAN_WEB_SUFFIXES
    )


def _is_google_news_article_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    if parsed.scheme != "https" or (parsed.hostname or "").casefold() != "news.google.com":
        return False
    return parsed.path.startswith(("/articles/", "/read/", "/rss/articles/"))


def _google_news_article_id(value: str) -> str | None:
    if not _is_google_news_article_url(value):
        return None
    try:
        article_id = urlparse(value).path.rstrip("/").rsplit("/", 1)[-1]
    except ValueError:
        return None
    if not article_id or len(article_id) > 4096:
        return None
    return article_id if re.fullmatch(r"[A-Za-z0-9_-]+", article_id) else None


def _google_news_decode_params(
    payload: str,
    *,
    article_id: str,
) -> tuple[str, str] | None:
    parser = _GoogleNewsDecodeParser(article_id)
    try:
        parser.feed(payload)
        parser.close()
    except (ValueError, AssertionError):
        return None
    if parser.signature is None or parser.timestamp is None:
        return None
    return parser.signature, parser.timestamp


def _google_news_decoded_url(payload: str) -> str | None:
    for line in payload.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(")]}'") or stripped.isdigit():
            continue
        try:
            rows = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not (
                isinstance(row, list)
                and len(row) >= 3
                and row[0] == "wrb.fr"
                and row[1] == "Fbv4je"
                and isinstance(row[2], str)
            ):
                continue
            try:
                decoded = json.loads(row[2])
            except json.JSONDecodeError:
                continue
            if isinstance(decoded, list) and len(decoded) >= 2 and isinstance(decoded[1], str):
                return _canonical_public_news_url(decoded[1]) or None
    return None


def _resolve_google_news_url(value: str, timeout_seconds: float) -> str | None:
    """Resolve a Google News citation to its publisher URL using signed metadata."""

    article_id = _google_news_article_id(value)
    if article_id is None:
        return None
    deadline = monotonic() + max(0.4, timeout_seconds)
    shell_request = Request(
        value,
        headers={
            "Accept": "text/html",
            "User-Agent": "FloodRiskTaiwan/0.1 official-citation-link-resolver",
        },
        method="GET",
    )
    try:
        with urlopen(
            shell_request,
            timeout=max(0.2, min(timeout_seconds / 2, deadline - monotonic())),
        ) as response:
            shell_payload = response.read(2_097_153)
        if len(shell_payload) > 2_097_152:
            return None
        params = _google_news_decode_params(
            shell_payload.decode("utf-8", errors="replace"),
            article_id=article_id,
        )
        if params is None:
            return None
        signature, timestamp = params
        inner_request = [
            "garturlreq",
            [
                [
                    "X",
                    "X",
                    ["X", "X"],
                    None,
                    None,
                    1,
                    1,
                    "TW:zh-Hant",
                    None,
                    1,
                    None,
                    None,
                    None,
                    None,
                    None,
                    0,
                    1,
                ],
                "X",
                "X",
                1,
                [1, 1, 1],
                1,
                1,
                None,
                0,
                0,
                None,
                0,
            ],
            article_id,
            int(timestamp),
            signature,
        ]
        rpc = [
            "Fbv4je",
            json.dumps(inner_request, ensure_ascii=False, separators=(",", ":")),
            None,
            "generic",
        ]
        body = urlencode(
            {
                "f.req": json.dumps(
                    [[rpc]],
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            }
        ).encode("utf-8")
        remaining_seconds = deadline - monotonic()
        if remaining_seconds <= 0:
            return None
        batch_request = Request(
            GOOGLE_NEWS_BATCH_EXECUTE_ENDPOINT,
            data=body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                "User-Agent": "FloodRiskTaiwan/0.1 official-citation-link-resolver",
            },
            method="POST",
        )
        with urlopen(
            batch_request,
            timeout=max(0.2, remaining_seconds),
        ) as response:
            batch_payload = response.read(524_289)
        if len(batch_payload) > 524_288:
            return None
        return _google_news_decoded_url(
            batch_payload.decode("utf-8", errors="replace")
        )
    except (
        HTTPError,
        URLError,
        TimeoutError,
        UnicodeDecodeError,
        ValueError,
        OverflowError,
    ):
        return None


def _rss_search_targets(location: str) -> tuple[_SearchTarget, ...]:
    targets = _search_targets(location)
    return tuple(
        sorted(
            targets,
            key=lambda target: (
                0 if target.scope == "road" else 1 if target.scope == "exact" else 2,
                len(target.term),
            ),
        )
    )


def _public_news_rss_queries(
    location: str,
    *,
    location_text: str,
    now: datetime,
) -> tuple[str, ...]:
    # News RSS engines often broaden or break CJK quoted phrases; unquoted
    # road terms produce better metadata recall while local matching remains strict.
    quoted_location = location
    years = _query_years(location_text, now=now)
    queries = [
        f"{quoted_location} 淹水",
        f"{quoted_location} 積水",
    ]
    for year in years:
        queries.extend(
            (
                f"{quoted_location} {year} 淹水",
                f"{quoted_location} {year} 暴雨",
            )
        )
    return _dedupe(queries, limit=10)


def _wiki_search_targets(location: str) -> tuple[_SearchTarget, ...]:
    targets = list(_rss_search_targets(location))
    for term in _admin_context_terms(location, include_city=True):
        targets.append(_SearchTarget(term, "admin_area", 0.52))
    deduped: list[_SearchTarget] = []
    seen: set[str] = set()
    for target in targets:
        normalized = _normalize(target.term)
        if len(normalized) < 2 or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(target)
        if len(deduped) >= 12:
            break
    return tuple(deduped)


def _public_wiki_queries(
    location: str,
    *,
    location_text: str,
    now: datetime,
) -> tuple[str, ...]:
    years = _query_years(location_text, now=now)
    queries = [
        f"{location} 淹水 暴雨",
        f"{location} 水災 災情",
    ]
    for year in years:
        queries.extend(
            (
                f"{location} {year} 淹水",
                f"{location} {year} 暴雨",
            )
        )
    return _dedupe(queries, limit=12)


def _wiki_search_url(source: _WikiSource, query: str) -> str:
    if source.api_kind == "wikimedia_rest":
        return f"{source.api_url}?{urlencode({'q': query, 'limit': '5'})}"

    params = urlencode(
        {
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "list": "search",
            "srsearch": query,
            "srlimit": "5",
            "srprop": "snippet|timestamp",
            "utf8": "1",
        }
    )
    return f"{source.api_url}?{params}"


def _wiki_articles(
    payload: Mapping[str, Any],
    *,
    source: _WikiSource,
    query: str,
) -> tuple[Mapping[str, Any], ...]:
    query_url = _wiki_search_url(source, query)
    rest_items = payload.get("pages")
    if isinstance(rest_items, list):
        return _wikimedia_rest_articles(rest_items, source=source, query_url=query_url, query=query)

    query_payload = payload.get("query")
    if not isinstance(query_payload, Mapping):
        return ()
    items = query_payload.get("search")
    if not isinstance(items, list):
        return ()
    articles: list[Mapping[str, Any]] = []

    for item in items:
        if not isinstance(item, Mapping):
            continue
        title = str(item.get("title", "")).strip()
        if not title:
            continue
        snippet = _clean_wiki_snippet(str(item.get("snippet", "")))
        articles.append(
            {
                "title": title,
                "url": f"{source.page_url}{quote(title.replace(' ', '_'), safe='()')}",
                "description": snippet,
                "published_at": _wiki_event_datetime(title=title, snippet=snippet, query=query),
                "domain": source.domain,
                "query_url": query_url,
            }
        )
    return tuple(articles)


def _wikimedia_rest_articles(
    items: list[Any],
    *,
    source: _WikiSource,
    query_url: str,
    query: str,
) -> tuple[Mapping[str, Any], ...]:
    articles: list[Mapping[str, Any]] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        title = str(item.get("title", "")).strip()
        key = str(item.get("key", "")).strip()
        page_key = key or title
        if not title or not page_key:
            continue
        snippet = _clean_wiki_snippet(
            " ".join(
                str(value).strip()
                for value in (item.get("excerpt"), item.get("description"))
                if str(value or "").strip()
            )
        )
        articles.append(
            {
                "title": title,
                "url": f"{source.page_url}{quote(page_key.replace(' ', '_'), safe='()')}",
                "description": snippet,
                "published_at": _wiki_event_datetime(title=title, snippet=snippet, query=query),
                "domain": source.domain,
                "query_url": query_url,
            }
        )
    return tuple(articles)


def _clean_wiki_snippet(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", "", value)
    return re.sub(r"\s+", " ", unescape(without_tags)).strip()


def _wiki_event_datetime(*, title: str, snippet: str, query: str) -> str | None:
    text = f"{title} {snippet} {query}"
    month_match = _YEAR_MONTH_PATTERN.search(text)
    if month_match:
        return f"{int(month_match.group('year')):04d}-{int(month_match.group('month')):02d}-01T00:00:00Z"
    year_match = _YEAR_PATTERN.search(text)
    if year_match:
        return f"{int(year_match.group(1)):04d}-01-01T00:00:00Z"
    return None


def _rss_relaxed_location_terms(location_text: str) -> tuple[str, ...]:
    normalized = _normalize(location_text)
    terms: list[str] = list(_admin_context_terms(normalized, include_city=False))
    for marker in ("縣", "市", "區", "鄉", "鎮"):
        for match in re.finditer(rf"[\u4e00-\u9fff]{{2,8}}{marker}", normalized):
            value = match.group(0)
            terms.append(value)
            terms.append(value.removesuffix(marker))
    for city in _CITY_ALIASES:
        city_norm = _normalize(city)
        if not normalized.startswith(city_norm):
            continue
        tail = normalized[len(city_norm) :]
        road_tail = _short_road_tail(tail)
        if road_tail:
            admin = tail[: -len(road_tail)]
            if admin:
                terms.append(admin)
                terms.append(admin.rstrip("區鄉鎮市縣"))
    return tuple(term for term in _dedupe(terms, limit=8) if len(term) >= 2)


def _short_road_tail(value: str) -> str:
    normalized = _normalize(value)
    trimmed = _trim_admin_prefix(normalized)
    if trimmed != normalized and _ROAD_PATTERN.fullmatch(trimmed):
        return trimmed
    for district_length in (2, 3, 4):
        if len(normalized) <= district_length + 1:
            continue
        road = normalized[district_length:]
        if _ROAD_PATTERN.fullmatch(road):
            return road
    match = re.search(
        r"[\u4e00-\u9fff]{2,4}(?:路|街|大道)(?:[一二三四五六七八九十0-9]+段)?(?:\d+巷)?$",
        normalized,
    )
    return match.group(0) if match is not None else ""


def _road_tail(location: str) -> str:
    normalized = _normalize(location)
    if not normalized:
        return ""
    trimmed = _trim_admin_prefix(normalized)
    if trimmed != normalized and _ROAD_PATTERN.fullmatch(trimmed):
        return trimmed
    for city in _CITY_ALIASES:
        city_norm = _normalize(city)
        if not normalized.startswith(city_norm):
            continue
        tail = normalized[len(city_norm) :]
        road = _short_road_tail(tail)
        if road:
            return road
    matches = list(_ROAD_PATTERN.finditer(normalized))
    if not matches:
        return ""
    road = matches[-1].group(0)
    trimmed_road = _trim_admin_prefix(road)
    return trimmed_road if _ROAD_PATTERN.fullmatch(trimmed_road) else road


def _admin_context_terms(location: str, *, include_city: bool) -> tuple[str, ...]:
    normalized = _normalize(location)
    road = _road_tail(normalized)
    prefix = normalized[: -len(road)] if road and normalized.endswith(road) else normalized
    terms: list[str] = []

    for marker in ("縣", "市", "區", "鄉", "鎮"):
        for match in re.finditer(rf"[\u4e00-\u9fff]{{2,8}}{marker}", prefix):
            value = match.group(0)
            terms.append(value)
            terms.append(value.removesuffix(marker))

    for city in _CITY_ALIASES:
        city_norm = _normalize(city)
        if not normalized.startswith(city_norm):
            continue
        tail = normalized[len(city_norm) :]
        road_tail = _short_road_tail(tail)
        district = tail[: -len(road_tail)] if road_tail else tail
        district = district.rstrip("區鄉鎮市縣")
        if include_city:
            terms.append(city_norm)
        if district:
            terms.append(district)
            terms.append(f"{city_norm}{district}")
            for suffix in ("區", "鄉", "鎮", "市"):
                terms.append(f"{district}{suffix}")
                terms.append(f"{city_norm}{district}{suffix}")
        break

    return tuple(
        term
        for term in _dedupe(terms, limit=12)
        if len(term) >= 2 and not any(marker in term for marker in ("路", "街", "大道"))
    )


def _query_years(location_text: str, *, now: datetime) -> tuple[int, ...]:
    explicit_years = [int(match.group(1)) for match in _YEAR_PATTERN.finditer(location_text)]
    if explicit_years:
        return tuple(dict.fromkeys(explicit_years))
    return tuple(range(now.year - 1, now.year - 7, -1))


def _rss_source_weight(match_scope: str) -> float:
    if match_scope == "exact":
        return 0.78
    if match_scope == "road":
        return 0.72
    return 0.58


def _wiki_source_weight(match_scope: str) -> float:
    if match_scope == "exact":
        return 0.68
    if match_scope == "road":
        return 0.62
    return 0.52


def _tainan_news_rows(payload: str) -> tuple[_TainanNewsRow, ...]:
    parser = _TainanNewsIndexParser()
    try:
        parser.feed(payload)
        parser.close()
    except (TypeError, ValueError):
        return ()
    return tuple(parser.rows)


def _tainan_district_terms(context_name: str) -> tuple[str, ...]:
    match = re.search(r"台南市(?P<district>[\u4e00-\u9fff]{1,4}區)", _normalize(context_name))
    if match is None:
        return ()
    district = match.group("district")
    return (district, district.removesuffix("區"))


def _parse_taiwan_roc_date(value: str) -> datetime | None:
    match = re.fullmatch(r"\s*(\d{2,3})[-/](\d{1,2})[-/](\d{1,2})\s*", value)
    if match is None:
        return None
    try:
        return datetime(
            int(match.group(1)) + 1911,
            int(match.group(2)),
            int(match.group(3)),
            tzinfo=timezone(timedelta(hours=8)),
        )
    except ValueError:
        return None


def _official_tainan_record(
    record: EvidenceUpsert,
    *,
    context_lat: float,
    context_lng: float,
    match_scope: str,
    match_term: str,
) -> EvidenceUpsert:
    admin_match = match_scope == "admin_area"
    limitation = (
        "臺南市政府新聞僅確認行政區近期積淹水事件；未提供查詢門牌的實測淹水深度。"
        if admin_match
        else "臺南市政府新聞確認道路事件背景；未提供查詢門牌的實測淹水深度。"
    )
    precision = "admin_area" if admin_match else "road_or_lane"
    record_lat = context_lat if admin_match else record.lat
    record_lng = context_lng if admin_match else record.lng
    identity = record.url or record.source_id
    if admin_match:
        identity = f"{identity}|{_normalize(match_term)}"
    source_id = f"tainan-official-news:{sha256(identity.encode('utf-8')).hexdigest()[:24]}"
    raw_ref = f"tainan-official-news:{sha256(identity.encode('utf-8')).hexdigest()[:32]}"
    properties = {
        **record.properties,
        "evidence_scope": "historical",
        "location_precision": precision,
        "limitations": [limitation],
        "license_name": "政府資料開放授權條款第 1 版",
        "attribution": "臺南市政府",
        "location_payload": {
            "resolution": "admin_area_centroid" if admin_match else "query_point",
            "geometry": {
                "type": "Point",
                "coordinates": [record_lng, record_lat],
            },
            "matched_locations": record.properties.get("location_payload", {}).get(
                "matched_locations", []
            ),
        },
    }
    return replace(
        record,
        id=str(uuid5(NAMESPACE_URL, source_id)),
        source_id=source_id,
        summary=(
            "臺南市政府發布的近期積淹水事件；位置為行政區範圍，非門牌實測。"
            if admin_match
            else "臺南市政府發布的近期道路積淹水事件；未提供門牌實測深度。"
        ),
        lat=record_lat,
        lng=record_lng,
        distance_to_query_m=None if admin_match else record.distance_to_query_m,
        raw_ref=raw_ref,
        properties=properties,
    )


def _official_government_record(
    record: EvidenceUpsert,
    *,
    context_lat: float,
    context_lng: float,
    now: datetime,
) -> EvidenceUpsert:
    match_scope = str(record.properties.get("location_match_scope") or "admin_area")
    admin_match = match_scope == "admin_area"
    precision = "admin_area" if admin_match else "road_or_lane"
    record_lat = context_lat if admin_match else record.lat
    record_lng = context_lng if admin_match else record.lng
    domain = str(record.properties.get("source_domain") or _domain_from_url(record.url or ""))
    limitation = (
        "政府機關頁面僅確認行政區近期積淹水事件；不能據此判定查詢門牌曾經淹水。"
        if admin_match
        else "政府機關頁面確認道路積淹水事件；未提供查詢門牌的實測淹水深度。"
    )
    properties = {
        **record.properties,
        "evidence_scope": "historical",
        "location_precision": precision,
        "limitations": [limitation],
        "legal_basis": "L1 official public citation metadata",
        "attribution": domain,
        "coverage_start_year": now.year - _OFFICIAL_HISTORY_LOOKBACK_YEARS + 1,
        "coverage_end_year": now.year,
        "coverage_is_complete": False,
        "location_payload": {
            "resolution": "admin_area_centroid" if admin_match else "query_point",
            "geometry": {
                "type": "Point",
                "coordinates": [record_lng, record_lat],
            },
            "matched_locations": record.properties.get("location_payload", {}).get(
                "matched_locations", []
            ),
        },
    }
    return replace(
        record,
        summary=(
            "臺灣政府機關發布的近期積淹水事件；位置為行政區範圍，非門牌實測。"
            if admin_match
            else "臺灣政府機關發布的近期道路積淹水事件；未提供門牌實測深度。"
        ),
        lat=record_lat,
        lng=record_lng,
        distance_to_query_m=None,
        confidence=min(record.confidence, 0.68 if admin_match else 0.84),
        properties=properties,
    )


def _rss_articles(payload: str, *, feed_url: str) -> tuple[Mapping[str, Any], ...]:
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError:
        return ()
    articles: list[Mapping[str, Any]] = []
    for item in root.findall(".//item"):
        title = _xml_child_text(item, "title")
        link = _canonical_public_news_url(_xml_child_text(item, "link"))
        if not title or not link:
            continue
        description = _xml_child_text(item, "description")
        pub_date = _xml_child_text(item, "pubDate") or _xml_child_text(item, "published")
        source = item.find("source")
        publisher_url = ""
        publisher_name = ""
        if source is not None:
            publisher_url = str(source.attrib.get("url") or "").strip()
            publisher_name = str(source.text or "").strip()
        articles.append(
            {
                "title": title,
                "url": link,
                "description": description,
                "published_at": pub_date,
                "domain": _domain_from_url(link),
                "feed_url": feed_url,
                "publisher_url": publisher_url,
                "publisher_name": publisher_name,
            }
        )
    return tuple(sorted(articles, key=_rss_article_sort_time, reverse=True))


def _rss_article_sort_time(article: Mapping[str, Any]) -> datetime:
    published_at = _parse_public_news_datetime(article.get("published_at"))
    if published_at is None:
        return datetime.min.replace(tzinfo=UTC)
    return (
        published_at
        if published_at.tzinfo is not None
        else published_at.replace(tzinfo=UTC)
    )


def _xml_child_text(item: Element, child_name: str) -> str:
    child = item.find(child_name)
    if child is None or child.text is None:
        return ""
    return child.text.strip()


def _record_from_article(
    article: Mapping[str, Any],
    *,
    location: str,
    match_scope: str,
    target_source_weight: float,
    lat: float,
    lng: float,
    radius_m: int,
    now: datetime,
    query_url: str,
    search_window_label: str,
    adapter_key: str = GDELT_ON_DEMAND_ADAPTER_KEY,
    source_prefix: str = "gdelt-on-demand",
    raw_ref_prefix: str = "gdelt-doc",
    ingestion_mode: str = "on_demand_public_news",
    relaxed_location_terms: tuple[str, ...] = (),
    summary_source_label: str = "公開新聞索引 metadata",
    source_type: str = "news",
) -> EvidenceUpsert | None:
    title = str(article.get("title", "")).strip()
    url = _canonical_public_news_url(str(article.get("url", "")).strip())
    if not title or not url:
        return None
    match_text = _article_match_text(article)
    location_match = _location_match(
        match_text,
        location,
        relaxed_location_terms=relaxed_location_terms,
    )
    if location_match is None:
        return None

    published_at = _parse_public_news_datetime(
        article.get("seendate") or article.get("published_at")
    )
    domain = str(article.get("domain", "")).strip() or _domain_from_url(url)
    source_id = f"{source_prefix}:{sha256(url.encode('utf-8')).hexdigest()[:24]}"
    raw_ref = f"{raw_ref_prefix}:{sha256((url + title).encode('utf-8')).hexdigest()[:32]}"
    text_locations = _text_locations(match_text)
    effective_match_scope = _effective_match_scope(match_scope, location_match)
    confidence = _confidence(
        text=match_text,
        location=location,
        domain=domain,
        match_scope=effective_match_scope,
    )
    location_precision = "admin_area" if effective_match_scope == "admin_area" else "road_or_lane"
    limitation = (
        "公開來源僅確認行政區事件；不能據此判定查詢門牌曾經淹水。"
        if effective_match_scope == "admin_area"
        else "公開來源為道路事件線索；未提供查詢門牌的實測淹水深度。"
    )
    return EvidenceUpsert(
        id=str(uuid5(NAMESPACE_URL, source_id)),
        adapter_key=adapter_key,
        source_id=source_id,
        source_type=source_type,
        event_type="flood_report",
        title=title,
        summary=_summary(
            title=title,
            location=location,
            domain=domain,
            source_label=summary_source_label,
        ),
        url=url,
        occurred_at=published_at,
        observed_at=published_at,
        ingested_at=now,
        lat=lat,
        lng=lng,
        distance_to_query_m=_distance_to_query_for_match(effective_match_scope),
        confidence=confidence,
        freshness_score=_freshness_score(published_at, now),
        source_weight=_effective_source_weight(target_source_weight, effective_match_scope),
        privacy_level="public",
        raw_ref=raw_ref,
        properties={
            "adapter_key": adapter_key,
            "ingestion_mode": ingestion_mode,
            "query_location": location,
            "location_match_scope": effective_match_scope,
            "location_match_basis": location_match.basis,
            "location_match_term": location_match.term,
            "query_radius_m": radius_m,
            "location_payload": {
                "resolution": "query_point",
                "geometry": {"type": "Point", "coordinates": [lng, lat]},
                "matched_locations": text_locations,
            },
            "source_domain": domain,
            "official_publisher_url": str(article.get("official_publisher_url") or "") or None,
            "publisher_name": str(article.get("publisher_name") or "") or None,
            "location_verification": (
                str(article.get("location_verification") or "citation_metadata")
            ),
            "query_url": query_url,
            "search_window": search_window_label,
            "citation_only": True,
            "full_text_stored": False,
            "evidence_scope": "historical",
            "location_precision": location_precision,
            "limitations": [limitation],
        },
    )


def _title_matches(title: str, location: str) -> bool:
    return _text_matches(title, location)


def _text_matches(
    text: str,
    location: str,
    *,
    relaxed_location_terms: tuple[str, ...] = (),
) -> bool:
    return (
        _location_match(text, location, relaxed_location_terms=relaxed_location_terms) is not None
    )


def _location_match(
    text: str,
    location: str,
    *,
    relaxed_location_terms: tuple[str, ...] = (),
) -> _LocationMatch | None:
    normalized_text = _normalize(text)
    normalized_location = _normalize(location)
    if not any(term in normalized_text for term in TAIWAN_NEWS_FLOOD_TERMS):
        return None
    if normalized_location and normalized_location in normalized_text:
        return _LocationMatch(term=location, basis="exact")

    road_tail = _road_tail(location)
    normalized_road_tail = _normalize(road_tail)
    admin_terms = _admin_context_terms(location, include_city=True)
    if normalized_road_tail and normalized_road_tail in normalized_text:
        if not admin_terms or any(_normalize(term) in normalized_text for term in admin_terms):
            return _LocationMatch(term=road_tail, basis="road_with_admin_context")
        return None

    for term in _location_terms(location):
        normalized_term = _normalize(term)
        if not normalized_term:
            continue
        if admin_terms and normalized_road_tail and normalized_term == normalized_road_tail:
            continue
        if normalized_term in normalized_text:
            return _LocationMatch(term=term, basis="location_term")

    for term in relaxed_location_terms:
        normalized_term = _normalize(term)
        if normalized_term and normalized_term in normalized_text:
            return _LocationMatch(term=term, basis="relaxed_admin_context")
    return None


def _article_match_text(article: Mapping[str, Any]) -> str:
    values = (
        article.get("title"),
        article.get("description"),
        article.get("summary"),
        article.get("snippet"),
        article.get("context"),
    )
    return " ".join(str(value).strip() for value in values if str(value or "").strip())


def _location_terms(location: str) -> tuple[str, ...]:
    normalized = _normalize(location)
    terms = [normalized]
    for marker in ("縣", "市", "區", "鄉", "鎮"):
        if marker in normalized:
            tail = normalized.rsplit(marker, 1)[-1]
            if tail:
                terms.append(tail)
    for match in _TITLE_LOCATION_PATTERN.finditer(normalized):
        terms.append(match.group(0))
    return tuple(term for term in _dedupe(terms, limit=8) if len(term) >= 2)


def _text_locations(text: str) -> tuple[str, ...]:
    return _dedupe([match.group(0) for match in _TITLE_LOCATION_PATTERN.finditer(text)], limit=8)


def _summary(*, title: str, location: str, domain: str, source_label: str) -> str:
    source = f"{domain} " if domain else ""
    return (
        f"{source}{source_label} 與「{location}」及淹水關鍵字相符；"
        f"系統僅保存標題、URL、時間與地點判讀 metadata。標題：{title}"
    )


def _confidence(*, text: str, location: str, domain: str, match_scope: str) -> float:
    score = 0.56
    normalized_text = _normalize(text)
    if _normalize(location) in normalized_text:
        score += 0.2
    if any(keyword in text for keyword in ("淹水", "積淹水", "水淹", "水災", "水患")):
        score += 0.1
    if any(keyword in text for keyword in ("豪雨", "暴雨", "颱風", "道路積水", "地下道")):
        score += 0.06
    if domain:
        score += 0.04
    if match_scope == "admin_area":
        score -= 0.18
    elif match_scope == "road":
        score -= 0.06
    return min(max(score, 0.45), 0.9)


def _effective_match_scope(target_scope: str, location_match: _LocationMatch) -> str:
    if location_match.basis == "relaxed_admin_context":
        return "admin_area"
    return target_scope


def _effective_source_weight(target_source_weight: float, match_scope: str) -> float:
    if match_scope == "admin_area":
        return min(target_source_weight, 0.58)
    if match_scope == "road":
        return min(target_source_weight, 0.72)
    return target_source_weight


def _freshness_score(published_at: datetime | None, now: datetime) -> float:
    if published_at is None:
        return 0.7
    comparable = published_at if published_at.tzinfo else published_at.replace(tzinfo=UTC)
    age_days = max(0, (now - comparable).days)
    if age_days <= 365:
        return 0.95
    if age_days <= 365 * 3:
        return 0.88
    return 0.78


def _distance_to_query_for_match(match_scope: str) -> float | None:
    return 0.0 if match_scope in {"exact", "road"} else None


def _search_windows(location_text: str, now: datetime) -> tuple[_SearchWindow, ...]:
    month_match = _YEAR_MONTH_PATTERN.search(location_text)
    if month_match:
        year = int(month_match.group("year"))
        month = int(month_match.group("month"))
        start = datetime(year, month, 1, tzinfo=UTC)
        end = _month_end(year, month)
        return (_SearchWindow(start, end, f"{year}-{month:02d}"),)

    match = _YEAR_PATTERN.search(location_text)
    if match:
        year = int(match.group(1))
        return (
            _SearchWindow(
                datetime(year, 1, 1, tzinfo=UTC),
                datetime(year, 12, 31, 23, 59, 59, tzinfo=UTC),
                str(year),
            ),
        )

    windows = [
        _SearchWindow(now - timedelta(days=548), now, "recent-18-months"),
        _SearchWindow(
            datetime(now.year, 1, 1, tzinfo=UTC),
            now,
            str(now.year),
        ),
    ]
    for year in range(now.year - 1, now.year - 5, -1):
        windows.append(
            _SearchWindow(
                datetime(year, 1, 1, tzinfo=UTC),
                datetime(year, 12, 31, 23, 59, 59, tzinfo=UTC),
                str(year),
            )
        )
    windows.append(_SearchWindow(now - timedelta(days=3650), now, "last-10-years"))
    return _dedupe_windows(windows)


def _month_end(year: int, month: int) -> datetime:
    if month == 12:
        return datetime(year, 12, 31, 23, 59, 59, tzinfo=UTC)
    return datetime(year, month + 1, 1, tzinfo=UTC) - timedelta(seconds=1)


def _parse_gdelt_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    for fmt in _GDELT_DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _parse_public_news_datetime(value: object) -> datetime | None:
    parsed = _parse_gdelt_datetime(value)
    if parsed is not None:
        return parsed
    if value is None:
        return None
    try:
        rss_parsed = parsedate_to_datetime(str(value).strip())
    except (TypeError, ValueError, IndexError):
        return None
    return rss_parsed if rss_parsed.tzinfo else rss_parsed.replace(tzinfo=UTC)


def _canonical_public_news_url(url: str) -> str:
    """Unwrap Bing RSS redirect URLs so publisher citations deduplicate."""

    normalized = unescape(url).strip()
    try:
        parsed = urlparse(normalized)
    except ValueError:
        return normalized
    if parsed.hostname in {"bing.com", "www.bing.com"} and parsed.path.casefold().endswith(
        "/news/apiclick.aspx"
    ):
        target = parse_qs(parsed.query).get("url", [""])[0]
        target = unquote(target).strip()
        try:
            target_parsed = urlparse(target)
        except ValueError:
            target_parsed = None
        if target_parsed is not None and target_parsed.scheme in {"http", "https"}:
            return target
    return normalized


def _domain_from_url(url: str) -> str:
    try:
        return urlparse(url).netloc
    except ValueError:
        without_scheme = url.split("://", 1)[-1]
        return without_scheme.split("/", 1)[0]


def _normalize(value: str) -> str:
    return value.casefold().replace("臺", "台").replace(" ", "").strip()


def _or_clause(terms: tuple[str, ...]) -> str:
    return "(" + " OR ".join(f'"{term}"' for term in terms) + ")"


def _dedupe_windows(values: list[_SearchWindow]) -> tuple[_SearchWindow, ...]:
    deduped: list[_SearchWindow] = []
    seen: set[tuple[str, str]] = set()
    for value in values:
        key = (
            value.start.strftime("%Y%m%d%H%M%S"),
            value.end.strftime("%Y%m%d%H%M%S"),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return tuple(deduped)


def _dedupe(values: list[str] | tuple[str, ...], *, limit: int) -> tuple[str, ...]:
    deduped: list[str] = []
    for value in values:
        normalized = value.strip()
        if normalized and normalized not in deduped:
            deduped.append(normalized)
        if len(deduped) >= limit:
            break
    return tuple(deduped)
