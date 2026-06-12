"""Geocode candidate cache with memory and Redis backends.

Replaces the per-process ``lru_cache`` on the external geocoding lookups so
replicas share results and entries expire instead of pinning stale (or
transiently failed) lookups forever. Empty results are cached with a short
TTL: they may be a legitimate "no match" worth shielding upstream rate
limits, or a transient outage that should retry soon. Redis always fails
open to the in-process cache.
"""

from __future__ import annotations

from threading import Lock
from time import time

import redis
from pydantic import TypeAdapter, ValidationError

from app.api.schemas import PlaceCandidate
from app.api.services.redis_support import FailOpenRedisClients

_REDIS_KEY_PREFIX = "flood-risk:geocode:"
_MEMORY_CACHE_MAX_ENTRIES = 512
_EMPTY_RESULT_TTL_SECONDS = 300

_MEMORY_CACHE: dict[str, tuple[float, tuple[PlaceCandidate, ...]]] = {}
_MEMORY_CACHE_LOCK = Lock()

_REDIS_CLIENTS = FailOpenRedisClients()
_CANDIDATES_ADAPTER: TypeAdapter[tuple[PlaceCandidate, ...]] = TypeAdapter(
    tuple[PlaceCandidate, ...]
)


def cached_candidates(
    cache_key: str,
    *,
    backend: str = "memory",
    redis_url: str | None = None,
) -> tuple[PlaceCandidate, ...] | None:
    with _MEMORY_CACHE_LOCK:
        cached = _MEMORY_CACHE.get(cache_key)
        if cached is not None:
            expires_at, candidates = cached
            if time() < expires_at:
                return candidates
            del _MEMORY_CACHE[cache_key]
    if backend == "redis" and redis_url:
        return _redis_cached_candidates(cache_key, redis_url=redis_url)
    return None


def store_candidates(
    cache_key: str,
    candidates: tuple[PlaceCandidate, ...],
    *,
    ttl_seconds: int,
    backend: str = "memory",
    redis_url: str | None = None,
) -> None:
    if not candidates:
        ttl_seconds = min(ttl_seconds, _EMPTY_RESULT_TTL_SECONDS)
    if ttl_seconds <= 0:
        return
    with _MEMORY_CACHE_LOCK:
        _MEMORY_CACHE[cache_key] = (time() + ttl_seconds, candidates)
        while len(_MEMORY_CACHE) > _MEMORY_CACHE_MAX_ENTRIES:
            oldest_key = next(iter(_MEMORY_CACHE))
            del _MEMORY_CACHE[oldest_key]
    if backend == "redis" and redis_url:
        _redis_store_candidates(
            cache_key,
            candidates,
            ttl_seconds=ttl_seconds,
            redis_url=redis_url,
        )


def _redis_cached_candidates(
    cache_key: str,
    *,
    redis_url: str,
) -> tuple[PlaceCandidate, ...] | None:
    client = _REDIS_CLIENTS.client(redis_url)
    if client is None:
        return None
    try:
        payload = client.get(_REDIS_KEY_PREFIX + cache_key)
    except redis.RedisError:
        _REDIS_CLIENTS.mark_unavailable()
        return None
    if not isinstance(payload, str | bytes | bytearray):
        return None
    try:
        return _CANDIDATES_ADAPTER.validate_json(payload)
    except ValidationError:
        return None


def _redis_store_candidates(
    cache_key: str,
    candidates: tuple[PlaceCandidate, ...],
    *,
    ttl_seconds: int,
    redis_url: str,
) -> None:
    client = _REDIS_CLIENTS.client(redis_url)
    if client is None:
        return
    try:
        client.setex(
            _REDIS_KEY_PREFIX + cache_key,
            ttl_seconds,
            _CANDIDATES_ADAPTER.dump_json(candidates),
        )
    except redis.RedisError:
        _REDIS_CLIENTS.mark_unavailable()
