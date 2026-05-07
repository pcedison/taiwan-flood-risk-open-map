from __future__ import annotations

import gzip
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Literal


TaiwanQueryScope = Literal["county", "town", "village", "road"]

TAIWAN_COUNTY_TERMS = (
    "台北市",
    "新北市",
    "桃園市",
    "台中市",
    "台南市",
    "高雄市",
    "基隆市",
    "新竹市",
    "新竹縣",
    "苗栗縣",
    "彰化縣",
    "南投縣",
    "雲林縣",
    "嘉義市",
    "嘉義縣",
    "屏東縣",
    "宜蘭縣",
    "花蓮縣",
    "台東縣",
    "澎湖縣",
    "金門縣",
    "連江縣",
)
TAIWAN_FLOOD_NEWS_TERMS = (
    "淹水",
    "積淹水",
    "積水",
    "豪雨",
    "暴雨",
    "水災",
    "道路淹水",
    "地下道淹水",
    "排水不及",
)
DEFAULT_TERMS_PER_QUERY = 8


def build_taiwan_flood_news_queries(
    place_terms: Iterable[str],
    *,
    terms_per_query: int = DEFAULT_TERMS_PER_QUERY,
) -> tuple[str, ...]:
    terms = _dedupe(term.strip() for term in place_terms if term.strip())
    if not terms:
        return ()

    queries: list[str] = []
    for chunk in _chunks(terms, size=max(1, terms_per_query)):
        place_clause = " OR ".join(_quote_term(term) for term in chunk)
        flood_clause = " OR ".join(TAIWAN_FLOOD_NEWS_TERMS)
        queries.append(f"({place_clause}) ({flood_clause}) sourcecountry:TW")
    return tuple(queries)


def load_taiwan_geocoder_terms(
    paths: Iterable[str | Path],
    *,
    scopes: Iterable[TaiwanQueryScope] = ("village",),
    limit: int | None = None,
) -> tuple[str, ...]:
    selected_scopes = set(scopes)
    terms: list[str] = []
    for path in paths:
        for payload in _iter_jsonl(path):
            term = _term_from_geocoder_payload(payload, scopes=selected_scopes)
            if not term:
                continue
            terms.append(term)
            if limit is not None and len(_dedupe(terms)) >= limit:
                return _dedupe(terms)[:limit]
    return _dedupe(terms)


def _term_from_geocoder_payload(
    payload: dict[str, Any],
    *,
    scopes: set[TaiwanQueryScope],
) -> str | None:
    name = str(payload.get("name") or "").strip()
    if not name:
        return None
    precision = str(payload.get("precision") or "").strip()
    place_type = str(payload.get("place_type") or "").strip()
    raw = payload.get("metadata", {}).get("raw", {})
    if not isinstance(raw, dict):
        raw = {}

    if "road" in scopes and precision == "road_or_lane":
        return name
    if place_type != "admin_area":
        return None
    if "village" in scopes and raw.get("source") == "nlsc-village-boundary-centroid":
        return name
    if "town" in scopes:
        return _county_town(name)
    if "county" in scopes:
        return _county(name)
    return None


def _iter_jsonl(path: str | Path) -> Iterable[dict[str, Any]]:
    resolved = Path(path)
    opener = gzip.open if resolved.suffix == ".gz" else open
    with opener(resolved, "rt", encoding="utf-8") as rows:
        for line in rows:
            payload = json.loads(line)
            if isinstance(payload, dict):
                yield payload


def _county_town(name: str) -> str | None:
    for town_marker in ("區", "鄉", "鎮", "市"):
        marker_index = name.find(town_marker, 2)
        if marker_index > 0:
            return name[: marker_index + 1]
    return None


def _county(name: str) -> str | None:
    for marker in ("縣", "市"):
        marker_index = name.find(marker)
        if marker_index > 0:
            return name[: marker_index + 1]
    return None


def _quote_term(term: str) -> str:
    return f'"{term}"' if len(term) > 2 else term


def _chunks(values: tuple[str, ...], *, size: int) -> Iterable[tuple[str, ...]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    deduped: list[str] = []
    for value in values:
        normalized = value.strip()
        if normalized and normalized not in deduped:
            deduped.append(normalized)
    return tuple(deduped)


DEFAULT_TAIWAN_FLOOD_NEWS_QUERIES = (
    *build_taiwan_flood_news_queries(TAIWAN_COUNTY_TERMS),
    '(道路淹水 OR 地下道淹水 OR 排水不及 OR 側溝排水不及) sourcecountry:TW',
)
