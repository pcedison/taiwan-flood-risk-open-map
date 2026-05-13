from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
import re
from time import monotonic
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import NAMESPACE_URL, uuid5

from app.domain.evidence import EvidenceUpsert
from app.domain.geocoding import extract_taiwan_search_location


FetchJson = Callable[[str, float], Mapping[str, Any]]

GDELT_DOC_ENDPOINT = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_ON_DEMAND_ADAPTER_KEY = "news.public_web.gdelt_backfill"
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
class _SearchWindow:
    start: datetime
    end: datetime
    label: str


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
    search_windows = _search_windows(location_text or "", now)
    accepted: list[EvidenceUpsert] = []
    seen_urls: set[str] = set()
    query_errors = 0
    timed_out = False
    deadline = monotonic() + max(0.5, timeout_seconds)
    per_query_max_records = _per_query_max_records(max_records)
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
            message=f"已從公開新聞索引補查並整理 {len(accepted)} 筆候選淹水事件。",
            records=tuple(accepted),
            health_status="healthy",
        )
    if timed_out or query_errors:
        message = "公開新聞索引暫時無法回應；保留既有資料，不阻塞風險查詢。"
        health_status: Literal["healthy", "degraded", "failed", "disabled", "unknown"] = "degraded"
    else:
        message = "公開新聞索引未找到可通過地點與淹水關鍵字比對的候選事件。"
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


def _fetch_json(url: str, timeout_seconds: float) -> Mapping[str, Any]:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "FloodRiskTaiwan/0.1 on-demand-public-news",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=max(0.5, timeout_seconds)) as response:
            payload: Any = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _articles(payload: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    articles = payload.get("articles", ())
    if not isinstance(articles, list):
        return ()
    return tuple(article for article in articles if isinstance(article, Mapping))


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
) -> EvidenceUpsert | None:
    title = str(article.get("title", "")).strip()
    url = str(article.get("url", "")).strip()
    if not title or not url:
        return None
    match_text = _article_match_text(article)
    if not _text_matches(match_text, location):
        return None

    published_at = _parse_gdelt_datetime(article.get("seendate") or article.get("published_at"))
    domain = str(article.get("domain", "")).strip() or _domain_from_url(url)
    source_id = f"gdelt-on-demand:{sha256(url.encode('utf-8')).hexdigest()[:24]}"
    raw_ref = f"gdelt-doc:{sha256((url + title).encode('utf-8')).hexdigest()[:32]}"
    text_locations = _text_locations(match_text)
    confidence = _confidence(text=match_text, location=location, domain=domain, match_scope=match_scope)
    return EvidenceUpsert(
        id=str(uuid5(NAMESPACE_URL, source_id)),
        adapter_key=GDELT_ON_DEMAND_ADAPTER_KEY,
        source_id=source_id,
        source_type="news",
        event_type="flood_report",
        title=title,
        summary=_summary(title=title, location=location, domain=domain),
        url=url,
        occurred_at=published_at,
        observed_at=published_at,
        ingested_at=now,
        lat=lat,
        lng=lng,
        distance_to_query_m=_distance_to_query_for_match(match_scope),
        confidence=confidence,
        freshness_score=_freshness_score(published_at, now),
        source_weight=target_source_weight,
        privacy_level="public",
        raw_ref=raw_ref,
        properties={
            "adapter_key": GDELT_ON_DEMAND_ADAPTER_KEY,
            "ingestion_mode": "on_demand_public_news",
            "query_location": location,
            "location_match_scope": match_scope,
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


def _text_matches(text: str, location: str) -> bool:
    normalized_title = _normalize(text)
    normalized_location = _normalize(location)
    if not any(term in normalized_title for term in TAIWAN_NEWS_FLOOD_TERMS):
        return False
    if normalized_location and normalized_location in normalized_title:
        return True
    return any(_normalize(term) in normalized_title for term in _location_terms(location))


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


def _summary(*, title: str, location: str, domain: str) -> str:
    source = f"{domain} " if domain else ""
    return (
        f"{source}公開新聞索引 metadata 與「{location}」及淹水關鍵字相符；"
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
