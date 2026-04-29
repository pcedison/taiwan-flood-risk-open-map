from __future__ import annotations

import re


_ROAD_PATTERN = re.compile(
    r"[\u4e00-\u9fff]{1,12}(?:路|街|大道)(?:[一二三四五六七八九十]+段)?(?:\d+巷)?"
)
_DISTRICT_PATTERN = re.compile(r"[\u4e00-\u9fff]{1,8}(?:區|鄉|鎮|市)")
_CITY_PATTERN = re.compile(r"[\u4e00-\u9fff]{1,8}(?:縣|市)")
_CITY_PREFIXES = (
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
    "嘉義",
)


def extract_taiwan_location_terms(text: str, *, limit: int = 8) -> tuple[str, ...]:
    """Extract coarse Taiwan place terms from public-news titles/snippets."""

    candidates: list[str] = []
    for pattern in (_ROAD_PATTERN, _DISTRICT_PATTERN, _CITY_PATTERN):
        for match in pattern.finditer(text):
            value = match.group(0).strip("，。、；：: ")
            if pattern is _ROAD_PATTERN:
                value = _trim_admin_prefix(value)
            elif pattern is _DISTRICT_PATTERN:
                value = _trim_city_prefix(value)
            if value and value not in candidates:
                candidates.append(value)
            if len(candidates) >= limit:
                return tuple(candidates)
    return tuple(candidates)


def _trim_admin_prefix(value: str) -> str:
    for marker in ("區", "鄉", "鎮", "市", "縣"):
        if marker in value:
            value = value.rsplit(marker, 1)[-1]
    return value


def _trim_city_prefix(value: str) -> str:
    for prefix in _CITY_PREFIXES:
        if value.startswith(prefix) and len(value) > len(prefix) + 1:
            return value[len(prefix) :]
    return value
