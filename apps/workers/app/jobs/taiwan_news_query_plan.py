from __future__ import annotations

from dataclasses import dataclass
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
    "積淹水",
    "道路淹水",
    "地下道淹水",
    "住家淹水",
    "豪雨淹水",
    "暴雨淹水",
    "淹水災情",
    "積淹水災情",
    "排水不及",
    "側溝排水不及",
    "低窪地區淹水",
    "車道淹水",
)
DEFAULT_TERMS_PER_QUERY = 4
GDELT_MIN_QUERY_TERM_CHARS = 3


@dataclass(frozen=True)
class TaiwanGeocoderQueryPlace:
    term: str
    lat: float
    lng: float
    scope: TaiwanQueryScope
    canonical_name: str
    precision: str | None
    source_key: str | None
    source_record_id: str | None


def build_taiwan_flood_news_queries(
    place_terms: Iterable[str],
    *,
    terms_per_query: int = DEFAULT_TERMS_PER_QUERY,
) -> tuple[str, ...]:
    terms = _dedupe(
        term.strip() for term in place_terms if _is_gdelt_safe_query_term(term)
    )
    if not terms:
        return ()

    queries: list[str] = []
    flood_clause = " OR ".join(
        term for term in TAIWAN_FLOOD_NEWS_TERMS if _is_gdelt_safe_query_term(term)
    )
    for chunk in _chunks(terms, size=max(1, terms_per_query)):
        place_clause = " OR ".join(_quote_term(term) for term in chunk)
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


def load_taiwan_geocoder_query_places(
    paths: Iterable[str | Path],
    *,
    scopes: Iterable[TaiwanQueryScope] = ("village",),
    limit: int | None = None,
) -> tuple[TaiwanGeocoderQueryPlace, ...]:
    selected_scopes = set(scopes)
    candidates: list[tuple[str, TaiwanGeocoderQueryPlace]] = []
    term_record_keys: dict[str, set[str]] = {}
    for path in paths:
        for payload in _iter_jsonl(path):
            scope = _scope_from_geocoder_payload(payload, scopes=selected_scopes)
            if scope is None:
                continue
            lat = _float_or_none(payload.get("lat"))
            lng = _float_or_none(payload.get("lng"))
            if lat is None or lng is None:
                continue
            canonical_name = str(payload.get("name") or "").strip()
            precision = str(payload.get("precision") or "").strip() or None
            source_key = str(payload.get("source_key") or "").strip() or None
            source_record_id = str(payload.get("source_record_id") or "").strip() or None
            record_key = source_record_id or f"{canonical_name}:{lat:.6f},{lng:.6f}:{scope}"
            for term in _query_terms_from_geocoder_payload(payload, scope=scope):
                normalized = _normalize_term(term)
                if not normalized:
                    continue
                place = TaiwanGeocoderQueryPlace(
                    term=term,
                    lat=lat,
                    lng=lng,
                    scope=scope,
                    canonical_name=canonical_name or term,
                    precision=precision,
                    source_key=source_key,
                    source_record_id=source_record_id,
                )
                candidates.append((normalized, place))
                term_record_keys.setdefault(normalized, set()).add(record_key)

    places: list[TaiwanGeocoderQueryPlace] = []
    seen_terms: set[str] = set()
    for normalized, place in candidates:
        if normalized in seen_terms:
            continue
        if len(term_record_keys.get(normalized, ())) > 1:
            continue
        seen_terms.add(normalized)
        places.append(place)
        if limit is not None and len(places) >= limit:
            break
    return tuple(places)


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


def _scope_from_geocoder_payload(
    payload: dict[str, Any],
    *,
    scopes: set[TaiwanQueryScope],
) -> TaiwanQueryScope | None:
    precision = str(payload.get("precision") or "").strip()
    place_type = str(payload.get("place_type") or "").strip()
    raw = payload.get("metadata", {}).get("raw", {})
    if not isinstance(raw, dict):
        raw = {}

    if "road" in scopes and precision == "road_or_lane":
        return "road"
    if place_type != "admin_area":
        return None
    if "village" in scopes and raw.get("source") == "nlsc-village-boundary-centroid":
        return "village"
    if "town" in scopes:
        return "town"
    if "county" in scopes:
        return "county"
    return None


def _query_terms_from_geocoder_payload(
    payload: dict[str, Any],
    *,
    scope: TaiwanQueryScope,
) -> tuple[str, ...]:
    name = str(payload.get("name") or "").strip()
    aliases = _payload_aliases(payload)
    raw = payload.get("metadata", {}).get("raw", {})
    if not isinstance(raw, dict):
        raw = {}

    terms: list[str] = [name, *aliases]
    if scope == "road":
        road = str(raw.get("road") or "").strip()
        site_id = str(raw.get("site_id") or "").strip()
        town = _county_town(site_id) if site_id else None
        terms.extend(term for term in (road, f"{town}{road}" if town and road else "") if term)
        terms = [term for term in terms if _looks_like_road_term(term)]
    elif scope == "village":
        terms.append(_admin_tail(name, markers=("村", "里")))
    elif scope == "town":
        terms.append(_county_town(name) or "")
    elif scope == "county":
        terms.append(_county(name) or "")
    return tuple(term for term in _dedupe(terms) if len(term) >= 2)


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


def _payload_aliases(payload: dict[str, Any]) -> tuple[str, ...]:
    values: list[str] = []
    for key in ("normalized_aliases", "aliases"):
        raw_value = payload.get(key)
        if isinstance(raw_value, list):
            values.extend(str(value).strip() for value in raw_value)
        elif isinstance(raw_value, str):
            values.extend(part.strip() for part in raw_value.split("|"))
    raw_aliases = payload.get("metadata", {}).get("raw", {}).get("aliases")
    if isinstance(raw_aliases, str):
        values.extend(part.strip() for part in raw_aliases.split("|"))
    return _dedupe(values)


def _looks_like_road_term(term: str) -> bool:
    return any(marker in term for marker in ("路", "街", "大道", "段", "巷"))


def _admin_tail(name: str, *, markers: tuple[str, ...]) -> str:
    for index in range(len(name) - 1, -1, -1):
        if name[index] in markers:
            start = max(
                name.rfind(marker, 0, index)
                for marker in ("縣", "市", "區", "鄉", "鎮")
            )
            return name[start + 1 :] if start >= 0 else name
    return ""


def _county(name: str) -> str | None:
    for marker in ("縣", "市"):
        marker_index = name.find(marker)
        if marker_index > 0:
            return name[: marker_index + 1]
    return None


def _quote_term(term: str) -> str:
    return f'"{term}"' if any(char.isspace() for char in term) else term


def _is_gdelt_safe_query_term(term: str) -> bool:
    return len(_normalize_term(term)) >= GDELT_MIN_QUERY_TERM_CHARS


def _float_or_none(value: object) -> float | None:
    if not isinstance(value, (float, int, str)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_term(value: str) -> str:
    return value.casefold().replace("臺", "台").replace(" ", "").strip()


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
