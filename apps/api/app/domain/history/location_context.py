from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import gzip
import json
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
from typing import Any


_APP_ROOT = Path(__file__).resolve().parents[2]
_GEOCODER_DATA_DIR = _APP_ROOT / "data" / "geocoder"
_VILLAGE_DATA_PATH = _GEOCODER_DATA_DIR / "villages.normalized.jsonl.gz"


@dataclass(frozen=True)
class PublicNewsLocationContext:
    name: str
    distance_m: float
    source_key: str
    precision: str


def nearest_public_news_location_text(
    *,
    lat: float,
    lng: float,
    radius_m: int,
    preferred_text: str | None = None,
) -> str | None:
    """Return user text or a nearby village/admin term for public-news lookup."""

    if preferred_text and preferred_text.strip():
        return preferred_text.strip()

    context = nearest_public_news_location_context(
        lat=lat,
        lng=lng,
        radius_m=radius_m,
    )
    return context.name if context is not None else None


def nearest_public_news_location_context(
    *,
    lat: float,
    lng: float,
    radius_m: int,
) -> PublicNewsLocationContext | None:
    max_distance_m = max(1500.0, min(max(float(radius_m) * 4.0, 3000.0), 8000.0))
    best: PublicNewsLocationContext | None = None
    for location in _village_locations():
        distance_m = _haversine_m(lat, lng, location["lat"], location["lng"])
        if distance_m > max_distance_m:
            continue
        if best is None or distance_m < best.distance_m:
            best = PublicNewsLocationContext(
                name=location["name"],
                distance_m=distance_m,
                source_key=location["source_key"],
                precision=location["precision"],
            )
    return best


@lru_cache(maxsize=1)
def _village_locations() -> tuple[dict[str, Any], ...]:
    if not _VILLAGE_DATA_PATH.is_file():
        return ()

    locations: list[dict[str, Any]] = []
    with gzip.open(_VILLAGE_DATA_PATH, "rt", encoding="utf-8") as rows:
        for line in rows:
            payload = json.loads(line)
            name = str(payload.get("name") or "").strip()
            source_key = str(payload.get("source_key") or "").strip()
            precision = str(payload.get("precision") or "").strip()
            lat = _float(payload.get("lat"))
            lng = _float(payload.get("lng"))
            if not name or lat is None or lng is None:
                continue
            locations.append(
                {
                    "name": name,
                    "lat": lat,
                    "lng": lng,
                    "source_key": source_key,
                    "precision": precision,
                }
            )
    return tuple(locations)


def _float(value: object) -> float | None:
    if not isinstance(value, (float, int, str)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    earth_radius_m = 6_371_000.0
    d_lat = radians(lat2 - lat1)
    d_lng = radians(lng2 - lng1)
    a = sin(d_lat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lng / 2) ** 2
    return 2 * earth_radius_m * asin(sqrt(a))
