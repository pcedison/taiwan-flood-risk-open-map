"""External geocoding candidate lookups for the public geocode endpoint.

These helpers perform outbound Nominatim/Wikimedia requests. They are wired
into the route layer through module globals in ``app.api.routes.public`` so
tests can monkeypatch the lookups without network access.
"""

from __future__ import annotations

import json
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.api.schemas import LatLng, PlaceCandidate
from app.api.services import public_geocode_cache
from app.domain.geocoding import (
    candidate_type_for_precision,
    geocode_limitations,
    nominatim_precision,
    requires_geocode_confirmation,
    stable_uuid,
    within_taiwan_bounds,
)

NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
WIKIMEDIA_API_URL = "https://zh.wikipedia.org/w/api.php"
NOMINATIM_USER_AGENT = "FloodRiskTaiwan/0.1 local-development"
TAIWAN_VIEWBOX = "119.2,25.5,122.3,21.7"


def cached_nominatim_candidates(
    query: str,
    input_type: Literal["address", "landmark", "parcel"],
    limit: int,
    *,
    ttl_seconds: int = 86400,
    backend: str = "memory",
    redis_url: str | None = None,
) -> tuple[PlaceCandidate, ...]:
    cache_key = f"nominatim:{input_type}:{limit}:{query}"
    cached = public_geocode_cache.cached_candidates(
        cache_key, backend=backend, redis_url=redis_url
    )
    if cached is not None:
        return cached
    candidates = fetch_nominatim_candidates(query, input_type, limit)
    public_geocode_cache.store_candidates(
        cache_key,
        candidates,
        ttl_seconds=ttl_seconds,
        backend=backend,
        redis_url=redis_url,
    )
    return candidates


def fetch_nominatim_candidates(
    query: str,
    input_type: Literal["address", "landmark", "parcel"],
    limit: int,
) -> tuple[PlaceCandidate, ...]:
    params = urlencode(
        {
            "q": query,
            "format": "jsonv2",
            "limit": limit,
            "countrycodes": "tw",
            "viewbox": TAIWAN_VIEWBOX,
            "bounded": 1,
            "accept-language": "zh-TW,zh,en",
        }
    )
    http_request = Request(
        f"{NOMINATIM_SEARCH_URL}?{params}",
        headers={
            "Accept": "application/json",
            "User-Agent": NOMINATIM_USER_AGENT,
        },
        method="GET",
    )
    try:
        with urlopen(http_request, timeout=2.5) as response:
            payload: Any = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return ()

    if not isinstance(payload, list):
        return ()

    candidates: list[PlaceCandidate] = []
    for index, item in enumerate(payload[:limit]):
        if not isinstance(item, dict):
            continue
        lat = float_from_payload(item.get("lat"))
        lng = float_from_payload(item.get("lon"))
        if lat is None or lng is None:
            continue
        display_name = item.get("display_name")
        precision = nominatim_precision(item, input_type)
        confidence = max(0.5, 0.9 - (index * 0.08))
        candidates.append(
            PlaceCandidate(
                place_id=stable_uuid("nominatim", item.get("osm_type"), item.get("osm_id"), index),
                name=str(item.get("name") or query or display_name),
                type=candidate_type_for_precision(input_type, precision),
                point=LatLng(lat=lat, lng=lng),
                admin_code=None,
                source="openstreetmap-nominatim",
                confidence=confidence,
                precision=precision,
                matched_query=query,
                requires_confirmation=requires_geocode_confirmation(precision, confidence),
                limitations=geocode_limitations(precision),
            )
        )
    return tuple(candidates)


def cached_wikimedia_candidates(
    query: str,
    limit: int,
    *,
    ttl_seconds: int = 86400,
    backend: str = "memory",
    redis_url: str | None = None,
) -> tuple[PlaceCandidate, ...]:
    cache_key = f"wikimedia:{limit}:{query}"
    cached = public_geocode_cache.cached_candidates(
        cache_key, backend=backend, redis_url=redis_url
    )
    if cached is not None:
        return cached
    candidates = fetch_wikimedia_candidates(query, limit)
    public_geocode_cache.store_candidates(
        cache_key,
        candidates,
        ttl_seconds=ttl_seconds,
        backend=backend,
        redis_url=redis_url,
    )
    return candidates


def fetch_wikimedia_candidates(query: str, limit: int) -> tuple[PlaceCandidate, ...]:
    search_params = urlencode(
        {
            "action": "query",
            "format": "json",
            "list": "search",
            "srsearch": query,
            "srlimit": min(max(limit, 1), 5),
            "utf8": 1,
            "origin": "*",
        }
    )
    search_payload = fetch_json(f"{WIKIMEDIA_API_URL}?{search_params}")
    search_results = search_payload.get("query", {}).get("search", [])
    if not isinstance(search_results, list) or not search_results:
        return ()

    page_ids = [
        str(item.get("pageid"))
        for item in search_results
        if isinstance(item, dict) and item.get("pageid") is not None
    ][:5]
    if not page_ids:
        return ()

    coord_params = urlencode(
        {
            "action": "query",
            "format": "json",
            "pageids": "|".join(page_ids),
            "prop": "coordinates",
            "colimit": "max",
            "origin": "*",
        }
    )
    coord_payload = fetch_json(f"{WIKIMEDIA_API_URL}?{coord_params}")
    pages = coord_payload.get("query", {}).get("pages", {})
    if not isinstance(pages, dict):
        return ()

    candidates: list[PlaceCandidate] = []
    for index, page_id in enumerate(page_ids):
        page = pages.get(page_id)
        if not isinstance(page, dict):
            continue
        coordinates = page.get("coordinates")
        if not isinstance(coordinates, list) or not coordinates:
            continue
        coordinate = coordinates[0]
        if not isinstance(coordinate, dict):
            continue
        lat = float_from_payload(coordinate.get("lat"))
        lng = float_from_payload(coordinate.get("lon"))
        if lat is None or lng is None or not within_taiwan_bounds(lat, lng):
            continue
        title = str(page.get("title") or query)
        candidates.append(
            PlaceCandidate(
                place_id=stable_uuid("wikimedia", page_id, index),
                name=title,
                type="landmark",
                point=LatLng(lat=lat, lng=lng),
                admin_code=None,
                source="wikimedia-coordinates",
                confidence=max(0.66, 0.84 - (index * 0.06)),
                precision="poi",
                matched_query=query,
                requires_confirmation=False,
                limitations=geocode_limitations("poi"),
            )
        )
        if len(candidates) >= limit:
            break
    return tuple(candidates)


def fetch_json(url: str) -> dict[str, Any]:
    http_request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": NOMINATIM_USER_AGENT,
        },
        method="GET",
    )
    try:
        with urlopen(http_request, timeout=3.5) as response:
            payload: Any = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def float_from_payload(value: object) -> float | None:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None
