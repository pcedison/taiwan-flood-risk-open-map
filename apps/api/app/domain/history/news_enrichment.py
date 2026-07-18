from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from hashlib import sha256
from html import unescape
import json
import re
from time import monotonic
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from uuid import NAMESPACE_URL, uuid5
from xml.etree.ElementTree import Element

from defusedxml import ElementTree

from app.domain.evidence import EvidenceUpsert
from app.domain.geocoding import extract_taiwan_search_location


FetchJson = Callable[[str, float], Mapping[str, Any]]
FetchText = Callable[[str, float], str]

GDELT_DOC_ENDPOINT = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_ON_DEMAND_ADAPTER_KEY = "news.public_web.gdelt_backfill"
PUBLIC_NEWS_ON_DEMAND_ADAPTER_KEY = "news.public_web.on_demand_search"
PUBLIC_WIKI_ON_DEMAND_ADAPTER_KEY = "news.public_web.wiki_search"
GOOGLE_NEWS_RSS_ENDPOINT = "https://news.google.com/rss/search"
BING_NEWS_RSS_ENDPOINT = "https://www.bing.com/news/search"
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
    text_client = fetch_text if fetch_text is not None else (_fetch_text if fetch_json is None else None)
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
    if timed_out or query_errors or (rss_attempted and rss_errors) or (wiki_attempted and wiki_errors):
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
    queries.append(f"{quoted_location} {_or_clause(('災情', '道路積水', '地下道', '封閉'))} sourcecountry:TW")
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
            "Accept": "application/rss+xml, application/xml, text/xml",
            "User-Agent": "FloodRiskTaiwan/0.1 on-demand-public-news-rss",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=max(0.5, timeout_seconds)) as response:
            return response.read().decode("utf-8", errors="replace")
    except (HTTPError, URLError, TimeoutError, UnicodeDecodeError):
        return ""


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
            f"{BING_NEWS_RSS_ENDPOINT}?"
            f"{urlencode({'q': query, 'format': 'rss', 'mkt': 'zh-TW'})}"
        )
    return _dedupe(urls, limit=16)


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


def _rss_articles(payload: str, *, feed_url: str) -> tuple[Mapping[str, Any], ...]:
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError:
        return ()
    articles: list[Mapping[str, Any]] = []
    for item in root.findall(".//item"):
        title = _xml_child_text(item, "title")
        link = _xml_child_text(item, "link")
        if not title or not link:
            continue
        description = _xml_child_text(item, "description")
        pub_date = _xml_child_text(item, "pubDate") or _xml_child_text(item, "published")
        articles.append(
            {
                "title": title,
                "url": link,
                "description": description,
                "published_at": pub_date,
                "domain": _domain_from_url(link),
                "feed_url": feed_url,
            }
        )
    return tuple(articles)


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
) -> EvidenceUpsert | None:
    title = str(article.get("title", "")).strip()
    url = str(article.get("url", "")).strip()
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

    published_at = _parse_public_news_datetime(article.get("seendate") or article.get("published_at"))
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
    return EvidenceUpsert(
        id=str(uuid5(NAMESPACE_URL, source_id)),
        adapter_key=adapter_key,
        source_id=source_id,
        source_type="news",
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
            "query_url": query_url,
            "search_window": search_window_label,
            "citation_only": True,
            "full_text_stored": False,
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
    return _location_match(text, location, relaxed_location_terms=relaxed_location_terms) is not None


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
        return (_SearchWindow(
            datetime(year, 1, 1, tzinfo=UTC),
            datetime(year, 12, 31, 23, 59, 59, tzinfo=UTC),
            str(year),
        ),)

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


def _domain_from_url(url: str) -> str:
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
