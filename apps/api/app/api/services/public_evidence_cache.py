"""Assessment evidence cache with memory and Redis backends.

The memory backend keeps the in-process FIFO cache that lived in the public
evidence module. The Redis backend shares cached evidence across replicas so
the evidence endpoint still works when a follow-up request lands on another
replica while the evidence repository is disabled. Redis always fails open:
any error falls back to the memory cache, and after a failure Redis attempts
pause for a cooldown window.
"""

from __future__ import annotations

from threading import Lock

import redis
from pydantic import TypeAdapter, ValidationError

from app.api.schemas import Evidence
from app.api.services.redis_support import FailOpenRedisClients

_REDIS_KEY_PREFIX = "flood-risk:assessment-evidence:"
_MEMORY_CACHE_MAX_ENTRIES = 256

_MEMORY_CACHE: dict[str, list[Evidence]] = {}
_MEMORY_CACHE_LOCK = Lock()

_REDIS_CLIENTS = FailOpenRedisClients()
_EVIDENCE_LIST_ADAPTER: TypeAdapter[list[Evidence]] = TypeAdapter(list[Evidence])


def cached_evidence(
    assessment_id: str,
    *,
    backend: str = "memory",
    redis_url: str | None = None,
) -> list[Evidence] | None:
    with _MEMORY_CACHE_LOCK:
        cached_items = _MEMORY_CACHE.get(assessment_id)
    if cached_items is not None:
        return cached_items
    if backend == "redis" and redis_url:
        return _redis_cached_evidence(assessment_id, redis_url=redis_url)
    return None


def store_evidence(
    assessment_id: str,
    evidence_items: list[Evidence],
    *,
    ttl_seconds: int = 0,
    backend: str = "memory",
    redis_url: str | None = None,
) -> None:
    with _MEMORY_CACHE_LOCK:
        _MEMORY_CACHE[assessment_id] = evidence_items
        while len(_MEMORY_CACHE) > _MEMORY_CACHE_MAX_ENTRIES:
            oldest_key = next(iter(_MEMORY_CACHE))
            del _MEMORY_CACHE[oldest_key]
    if backend == "redis" and redis_url and ttl_seconds > 0:
        _redis_store_evidence(
            assessment_id,
            evidence_items,
            ttl_seconds=ttl_seconds,
            redis_url=redis_url,
        )


def _redis_cached_evidence(assessment_id: str, *, redis_url: str) -> list[Evidence] | None:
    client = _REDIS_CLIENTS.client(redis_url)
    if client is None:
        return None
    try:
        payload = client.get(_REDIS_KEY_PREFIX + assessment_id)
    except redis.RedisError:
        _REDIS_CLIENTS.mark_unavailable()
        return None
    if not isinstance(payload, str | bytes | bytearray):
        return None
    try:
        return _EVIDENCE_LIST_ADAPTER.validate_json(payload)
    except ValidationError:
        return None


def _redis_store_evidence(
    assessment_id: str,
    evidence_items: list[Evidence],
    *,
    ttl_seconds: int,
    redis_url: str,
) -> None:
    client = _REDIS_CLIENTS.client(redis_url)
    if client is None:
        return
    try:
        client.setex(
            _REDIS_KEY_PREFIX + assessment_id,
            ttl_seconds,
            _EVIDENCE_LIST_ADAPTER.dump_json(evidence_items),
        )
    except redis.RedisError:
        _REDIS_CLIENTS.mark_unavailable()
