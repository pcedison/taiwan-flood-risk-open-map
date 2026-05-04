from __future__ import annotations

import re


_NOISE_TERMS = (
    "淹水",
    "積淹水",
    "積水",
    "豪雨",
    "暴雨",
    "颱風",
    "水災",
    "災情",
    "新聞",
    "報導",
    "事件",
    "風險",
    "警示",
    "嚴重",
    "歷史",
    "查詢",
)
_DATE_PATTERN = re.compile(
    r"(?:19|20)\d{2}(?:[/-]\d{1,2}(?:[/-]\d{1,2})?)?|"
    r"(?:19|20)\d{2}\s*年(?:\s*\d{1,2}\s*月(?:\s*\d{1,2}\s*日)?)?"
)
_ROAD_PATTERN = re.compile(
    r"[\u4e00-\u9fff]{1,18}(?:路|街|大道)"
    r"(?:[一二三四五六七八九十0-9]+段)?(?:\d+巷)?(?:\d+(?:之\d+)?號?)?"
)
_ADMIN_SUFFIX_PATTERN = re.compile(r"[\u4e00-\u9fff]{1,8}(?:縣|市|區|鄉|鎮)")
_CITY_ALIASES: dict[str, tuple[str, ...]] = {
    "台北": ("台北市",),
    "臺北": ("臺北市", "台北市"),
    "新北": ("新北市",),
    "桃園": ("桃園市",),
    "台中": ("台中市",),
    "臺中": ("臺中市", "台中市"),
    "台南": ("台南市",),
    "臺南": ("臺南市", "台南市"),
    "高雄": ("高雄市",),
    "基隆": ("基隆市",),
    "新竹": ("新竹市", "新竹縣"),
    "苗栗": ("苗栗縣",),
    "彰化": ("彰化縣",),
    "南投": ("南投縣",),
    "雲林": ("雲林縣",),
    "嘉義": ("嘉義市", "嘉義縣"),
    "屏東": ("屏東縣",),
    "宜蘭": ("宜蘭縣",),
    "花蓮": ("花蓮縣",),
    "台東": ("台東縣",),
    "臺東": ("臺東縣", "台東縣"),
    "澎湖": ("澎湖縣",),
    "金門": ("金門縣",),
    "連江": ("連江縣",),
}
_MUNICIPALITIES = ("台北市", "臺北市", "新北市", "桃園市", "台中市", "臺中市", "台南市", "臺南市", "高雄市")


def build_taiwan_geocode_queries(query: str, *, limit: int = 12) -> tuple[str, ...]:
    """Build Taiwan-focused geocoder queries from user text that may include news context."""

    normalized = _normalize_spaces(query)
    if not normalized:
        return ()

    extracted = extract_taiwan_search_location(normalized)
    candidates: list[str] = []
    noisy = _has_noise(normalized)
    if noisy and extracted:
        candidates.extend(_expand_admin_variants(extracted))
        candidates.append(extracted)

    candidates.append(normalized)

    if extracted and extracted != normalized:
        candidates.append(extracted)
        candidates.extend(_expand_admin_variants(extracted))

    cleaned = _clean_query_noise(normalized)
    if cleaned and cleaned not in (normalized, extracted):
        candidates.append(cleaned)
        candidates.extend(_expand_admin_variants(cleaned))

    for base in tuple(candidates):
        if base and not _contains_taiwan_context(base):
            candidates.append(f"{base} 台灣")
            candidates.append(f"臺灣 {base}")

    return _dedupe(candidates, limit=limit)


def extract_taiwan_search_location(query: str) -> str:
    """Extract the most likely Taiwan location phrase from a mixed event/news query."""

    cleaned = _clean_query_noise(query)
    road_matches = list(_ROAD_PATTERN.finditer(cleaned))
    if road_matches:
        return _trim_connectors(max((match.group(0) for match in road_matches), key=len))

    admin_matches = list(_ADMIN_SUFFIX_PATTERN.finditer(cleaned))
    if admin_matches:
        return _trim_connectors("".join(match.group(0) for match in admin_matches[-2:]))

    return cleaned


def _clean_query_noise(query: str) -> str:
    cleaned = _normalize_spaces(query).replace("臺", "台")
    cleaned = _DATE_PATTERN.sub(" ", cleaned)
    for term in _NOISE_TERMS:
        cleaned = cleaned.replace(term, " ")
    cleaned = re.sub(r"[，,。；;：:！!？?()\[\]{}「」『』\"']", " ", cleaned)
    cleaned = re.sub(r"\s+", "", cleaned)
    cleaned = cleaned.replace("的", "")
    return _trim_connectors(cleaned)


def _expand_admin_variants(location: str) -> tuple[str, ...]:
    variants: list[str] = []
    for city_alias, city_variants in _CITY_ALIASES.items():
        if not location.startswith(city_alias):
            continue
        tail = location[len(city_alias) :]
        for city in city_variants:
            variants.append(f"{city}{tail}")
            variants.extend(_city_tail_district_variants(city, tail))
            variants.extend(_insert_district_suffix(f"{city}{tail}", city))
    variants.extend(_insert_district_suffix(location, None))
    return _dedupe(variants, limit=8)


def _insert_district_suffix(location: str, city: str | None) -> tuple[str, ...]:
    road_match = _ROAD_PATTERN.search(location)
    if road_match is None:
        return ()

    road = road_match.group(0)
    prefix = location[: road_match.start()]
    if not prefix or prefix.endswith(("區", "鄉", "鎮", "市")):
        return ()

    last_city_index = max(prefix.rfind("市"), prefix.rfind("縣"))
    district = prefix[last_city_index + 1 :] if last_city_index >= 0 else prefix
    city_prefix = prefix[: last_city_index + 1] if last_city_index >= 0 else ""
    if not (1 <= len(district) <= 5) or district.endswith(("區", "鄉", "鎮", "市")):
        return ()

    suffixes = ("區",) if city in _MUNICIPALITIES else ("區", "鄉", "鎮", "市")
    return tuple(f"{city_prefix}{district}{suffix}{road}" for suffix in suffixes)


def _city_tail_district_variants(city: str, tail: str) -> tuple[str, ...]:
    if not tail or any(suffix in tail for suffix in ("區", "鄉", "鎮", "市")):
        return ()
    if _ROAD_PATTERN.search(tail) is None:
        return ()

    variants: list[str] = []
    suffixes = ("區",) if city in _MUNICIPALITIES else ("區", "鄉", "鎮", "市")
    for district_length in (2, 3, 4):
        if len(tail) <= district_length + 1:
            continue
        district = tail[:district_length]
        road = tail[district_length:]
        if _ROAD_PATTERN.fullmatch(road):
            variants.extend(f"{city}{district}{suffix}{road}" for suffix in suffixes)
    return _dedupe(variants, limit=8)


def _has_noise(query: str) -> bool:
    return bool(_DATE_PATTERN.search(query)) or any(term in query for term in _NOISE_TERMS)


def _contains_taiwan_context(query: str) -> bool:
    lower = query.casefold()
    return "台灣" in query or "臺灣" in query or "taiwan" in lower


def _normalize_spaces(query: str) -> str:
    return query.replace("\u3000", " ").strip()


def _trim_connectors(value: str) -> str:
    return value.strip(" -_/、，,。；;：:的")


def _dedupe(values: list[str] | tuple[str, ...], *, limit: int) -> tuple[str, ...]:
    deduped: list[str] = []
    for value in values:
        normalized = _normalize_spaces(value)
        if normalized and normalized not in deduped:
            deduped.append(normalized)
        if len(deduped) >= limit:
            break
    return tuple(deduped)
