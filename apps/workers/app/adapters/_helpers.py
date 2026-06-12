from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from hashlib import sha256
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def parse_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_observed_at_utc(value: object) -> datetime | None:
    parsed = parse_datetime(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def optional_float(value: object) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float, str)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def url_with_query(
    api_url: str,
    params: Mapping[str, str],
    *,
    drop_keys: Iterable[str] = (),
) -> str:
    parts = urlsplit(api_url)
    excluded_keys = {key.lower() for key in params} | {key.lower() for key in drop_keys}
    existing_params = tuple(
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in excluded_keys
    )
    query = urlencode((*existing_params, *params.items()))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def stable_evidence_id(adapter_key: str, source_id: str) -> str:
    digest = sha256(f"{adapter_key}:{source_id}".encode("utf-8")).hexdigest()[:16]
    return f"ev_{digest}"
