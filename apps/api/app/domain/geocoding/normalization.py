from __future__ import annotations

import re
import unicodedata


SEPARATOR_RE = re.compile(r"[\s\u3000,，、。．.·・/／\\|;；:：_＿\-－()（）\[\]【】「」『』]+")
SECTION_DIGITS = {
    "一": "1",
    "二": "2",
    "三": "3",
    "四": "4",
    "五": "5",
    "六": "6",
    "七": "7",
    "八": "8",
    "九": "9",
    "十": "10",
}
SECTION_NUMERALS = {value: key for key, value in SECTION_DIGITS.items()}


def normalize_taiwan_address_text(value: str) -> str:
    """Normalize common Taiwan address variants without guessing missing components."""
    text = unicodedata.normalize("NFKC", value or "")
    text = text.replace("\ufeff", "").strip().casefold()
    text = text.replace("臺", "台")
    return text


def compact_taiwan_query_key(value: str) -> str:
    normalized = normalize_taiwan_address_text(value)
    return SEPARATOR_RE.sub("", normalized)


def taiwan_address_aliases(*values: str, limit: int = 16) -> tuple[str, ...]:
    aliases: list[str] = []
    for value in values:
        for candidate in _address_variants(value):
            if candidate and candidate not in aliases:
                aliases.append(candidate)
                if len(aliases) >= limit:
                    return tuple(aliases)
    return tuple(aliases)


def normalized_aliases(*values: str, limit: int = 16) -> tuple[str, ...]:
    aliases: list[str] = []
    for value in values:
        for candidate in _address_variants(value):
            normalized = compact_taiwan_query_key(candidate)
            if normalized and normalized not in aliases:
                aliases.append(normalized)
                if len(aliases) >= limit:
                    return tuple(aliases)
    return tuple(aliases)


def _address_variants(value: str) -> tuple[str, ...]:
    text = unicodedata.normalize("NFKC", value or "").strip()
    if not text:
        return ()

    variants: list[str] = []
    queue = [text, compact_taiwan_query_key(text)]
    while queue:
        current = queue.pop(0)
        if not current or current in variants:
            continue
        variants.append(current)
        queue.extend(_tai_variants(current))
        queue.extend(_section_variants(current))
    return tuple(variants)


def _tai_variants(value: str) -> tuple[str, ...]:
    variants: list[str] = []
    if "臺" in value:
        variants.append(value.replace("臺", "台"))
    if "台" in value:
        variants.append(value.replace("台", "臺"))
    return tuple(variants)


def _section_variants(value: str) -> tuple[str, ...]:
    variants: list[str] = []
    for chinese, digit in SECTION_DIGITS.items():
        variants.append(value.replace(f"{chinese}段", f"{digit}段"))
    for digit, chinese in SECTION_NUMERALS.items():
        variants.append(value.replace(f"{digit}段", f"{chinese}段"))
    return tuple(variant for variant in variants if variant != value)
