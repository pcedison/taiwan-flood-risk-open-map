"""Shared fail-open Redis client management for cache backends.

Each cache module owns one ``FailOpenRedisClients`` instance so its failure
cooldown does not leak into other caches. Callers treat ``None`` as "skip
Redis for now" and fall back to their in-process cache.
"""

from __future__ import annotations

from threading import Lock
from time import monotonic

import redis

_FAILURE_COOLDOWN_SECONDS = 30.0


class FailOpenRedisClients:
    """URL-keyed shared Redis client with a failure cooldown.

    After any Redis error the next attempts pause for a cooldown window so a
    dead Redis does not add per-request connection stalls.
    """

    def __init__(self, *, cooldown_seconds: float = _FAILURE_COOLDOWN_SECONDS) -> None:
        self._client: redis.Redis | None = None
        self._client_url: str | None = None
        self._retry_at: float = 0.0
        self._cooldown_seconds = cooldown_seconds
        self._lock = Lock()

    @property
    def retry_at(self) -> float:
        return self._retry_at

    def client(self, redis_url: str) -> redis.Redis | None:
        with self._lock:
            if monotonic() < self._retry_at:
                return None
            if self._client is None or self._client_url != redis_url:
                try:
                    self._client = redis.Redis.from_url(
                        redis_url,
                        socket_connect_timeout=2,
                        socket_timeout=2,
                    )
                except redis.RedisError:
                    self._mark_unavailable_locked()
                    return None
                self._client_url = redis_url
            return self._client

    def mark_unavailable(self) -> None:
        with self._lock:
            self._mark_unavailable_locked()

    def _mark_unavailable_locked(self) -> None:
        self._retry_at = monotonic() + self._cooldown_seconds
