"""Risk assessment response cache with memory and Redis backends.

The memory backend is the in-process cache that existed in the public route
module. The Redis backend shares cached responses across replicas and always
fails open: any Redis error falls back to the memory cache so risk assessment
never depends on cache availability. After a failure, Redis attempts pause for
a cooldown window so a dead Redis does not add per-request connection stalls.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha256
from threading import Lock
from time import monotonic

import redis
from pydantic import ValidationError

from app.api.schemas import RiskAssessmentResponse

_REDIS_KEY_PREFIX = "flood-risk:risk-response:"
_REDIS_FAILURE_COOLDOWN_SECONDS = 30.0
_MEMORY_CACHE_MAX_ENTRIES = 128

_MEMORY_CACHE: dict[str, tuple[datetime, RiskAssessmentResponse]] = {}
_MEMORY_CACHE_LOCK = Lock()

_redis_client: redis.Redis | None = None
_redis_client_url: str | None = None
_redis_retry_at: float = 0.0
_REDIS_CLIENT_LOCK = Lock()


def cached_response(
    cache_key: str,
    *,
    now: datetime,
    ttl_seconds: int,
    backend: str = "memory",
    redis_url: str | None = None,
) -> RiskAssessmentResponse | None:
    if ttl_seconds <= 0:
        return None
    if backend == "redis" and redis_url:
        response = _redis_cached_response(cache_key, redis_url=redis_url)
        if response is not None:
            return response
    return _memory_cached_response(cache_key, now=now, ttl_seconds=ttl_seconds)


def store_response(
    cache_key: str,
    response: RiskAssessmentResponse,
    *,
    now: datetime,
    ttl_seconds: int,
    backend: str = "memory",
    redis_url: str | None = None,
) -> None:
    if ttl_seconds <= 0:
        return
    _memory_store_response(cache_key, response, now=now)
    if backend == "redis" and redis_url:
        _redis_store_response(cache_key, response, ttl_seconds=ttl_seconds, redis_url=redis_url)


def _memory_cached_response(
    cache_key: str,
    *,
    now: datetime,
    ttl_seconds: int,
) -> RiskAssessmentResponse | None:
    with _MEMORY_CACHE_LOCK:
        cached = _MEMORY_CACHE.get(cache_key)
        if cached is None:
            return None
        cached_at, response = cached
        if now - cached_at >= timedelta(seconds=ttl_seconds):
            _MEMORY_CACHE.pop(cache_key, None)
            return None
        return response


def _memory_store_response(
    cache_key: str,
    response: RiskAssessmentResponse,
    *,
    now: datetime,
) -> None:
    with _MEMORY_CACHE_LOCK:
        _MEMORY_CACHE[cache_key] = (now, response)
        while len(_MEMORY_CACHE) > _MEMORY_CACHE_MAX_ENTRIES:
            oldest_key = next(iter(_MEMORY_CACHE))
            del _MEMORY_CACHE[oldest_key]


def _redis_cached_response(cache_key: str, *, redis_url: str) -> RiskAssessmentResponse | None:
    client = _shared_redis_client(redis_url)
    if client is None:
        return None
    try:
        payload = client.get(_redis_key(cache_key))
    except redis.RedisError:
        _mark_redis_unavailable()
        return None
    if not isinstance(payload, str | bytes | bytearray):
        return None
    try:
        return RiskAssessmentResponse.model_validate_json(payload)
    except ValidationError:
        return None


def _redis_store_response(
    cache_key: str,
    response: RiskAssessmentResponse,
    *,
    ttl_seconds: int,
    redis_url: str,
) -> None:
    client = _shared_redis_client(redis_url)
    if client is None:
        return
    try:
        client.setex(_redis_key(cache_key), ttl_seconds, response.model_dump_json())
    except redis.RedisError:
        _mark_redis_unavailable()


def _redis_key(cache_key: str) -> str:
    return _REDIS_KEY_PREFIX + sha256(cache_key.encode("utf-8")).hexdigest()


def _shared_redis_client(redis_url: str) -> redis.Redis | None:
    global _redis_client, _redis_client_url, _redis_retry_at
    with _REDIS_CLIENT_LOCK:
        if monotonic() < _redis_retry_at:
            return None
        if _redis_client is None or _redis_client_url != redis_url:
            try:
                _redis_client = redis.Redis.from_url(
                    redis_url,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                )
            except redis.RedisError:
                _mark_redis_unavailable()
                return None
            _redis_client_url = redis_url
        return _redis_client


def _mark_redis_unavailable() -> None:
    global _redis_retry_at
    _redis_retry_at = monotonic() + _REDIS_FAILURE_COOLDOWN_SECONDS
