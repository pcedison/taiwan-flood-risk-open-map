from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from math import ceil
from threading import Lock
from time import monotonic, time
from typing import Literal

import redis


RateLimitBackend = Literal["redis", "memory"]
UserReportRateLimitBackend = RateLimitBackend
_REDIS_RATE_LIMIT_SCRIPT = """
local bucket_key = KEYS[1]
local sequence_key = KEYS[2]
local now_ms = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2])
local max_requests = tonumber(ARGV[3])
local window_start = now_ms - window_ms

redis.call("ZREMRANGEBYSCORE", bucket_key, "-inf", window_start)
local current_count = redis.call("ZCARD", bucket_key)
if current_count >= max_requests then
  local oldest = redis.call("ZRANGE", bucket_key, 0, 0, "WITHSCORES")
  local retry_ms = window_ms
  if oldest[2] then
    retry_ms = math.max(1, window_ms - (now_ms - tonumber(oldest[2])))
  end
  return {0, retry_ms}
end

local sequence = redis.call("INCR", sequence_key)
local member = tostring(now_ms) .. ":" .. tostring(sequence)
redis.call("ZADD", bucket_key, now_ms, member)
redis.call("PEXPIRE", bucket_key, window_ms + 1000)
redis.call("PEXPIRE", sequence_key, window_ms + 1000)
return {1, 0}
"""


@dataclass(frozen=True)
class RateLimitPolicy:
    max_requests: int
    window_seconds: int


class RateLimitExceeded(RuntimeError):
    def __init__(
        self,
        *,
        retry_after_seconds: int,
        policy: RateLimitPolicy,
        message: str = "rate limit exceeded",
    ) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds
        self.policy = policy


class UserReportRateLimitExceeded(RateLimitExceeded):
    def __init__(self, *, retry_after_seconds: int, policy: RateLimitPolicy) -> None:
        super().__init__(
            retry_after_seconds=retry_after_seconds,
            policy=policy,
            message="user report intake rate limit exceeded",
        )


class RateLimitUnavailable(RuntimeError):
    """Raised when the configured shared abuse guard cannot be reached."""


class UserReportRateLimitUnavailable(RateLimitUnavailable):
    """Raised when user report abuse controls cannot be reached."""


class InMemoryRateLimiter:
    def __init__(self, *, clock: Callable[[], float] = monotonic) -> None:
        self._clock = clock
        self._requests_by_client: dict[str, deque[float]] = {}
        self._lock = Lock()

    def check(self, *, client_key: str, policy: RateLimitPolicy) -> None:
        self._check(
            client_key=client_key,
            policy=policy,
            exceeded_error=RateLimitExceeded,
        )

    def _check(
        self,
        *,
        client_key: str,
        policy: RateLimitPolicy,
        exceeded_error: type[RateLimitExceeded],
    ) -> None:
        if policy.max_requests < 1:
            raise ValueError("rate limit max_requests must be at least 1")
        if policy.window_seconds < 1:
            raise ValueError("rate limit window_seconds must be at least 1")

        now = self._clock()
        window_start = now - policy.window_seconds
        with self._lock:
            requests = self._requests_by_client.setdefault(client_key, deque())
            while requests and requests[0] <= window_start:
                requests.popleft()

            if len(requests) >= policy.max_requests:
                retry_after = max(1, ceil(policy.window_seconds - (now - requests[0])))
                raise exceeded_error(
                    retry_after_seconds=retry_after,
                    policy=policy,
                )

            requests.append(now)


class InMemoryUserReportRateLimiter(InMemoryRateLimiter):
    def check(self, *, client_key: str, policy: RateLimitPolicy) -> None:
        self._check(
            client_key=client_key,
            policy=policy,
            exceeded_error=UserReportRateLimitExceeded,
        )


_REDIS_CLIENT_CACHE: dict[str, redis.Redis] = {}
_REDIS_CLIENT_CACHE_LOCK = Lock()


def _shared_redis_client(redis_url: str) -> redis.Redis:
    """Return a process-wide client per URL so checks reuse one connection pool."""
    with _REDIS_CLIENT_CACHE_LOCK:
        client = _REDIS_CLIENT_CACHE.get(redis_url)
        if client is None:
            client = redis.Redis.from_url(
                redis_url,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
            _REDIS_CLIENT_CACHE[redis_url] = client
        return client


class RedisRateLimiter:
    def __init__(
        self,
        *,
        redis_url: str,
        namespace: str,
        clock: Callable[[], float] = time,
    ) -> None:
        self._redis_url = redis_url
        self._namespace = namespace
        self._clock = clock

    def check(self, *, client_key: str, policy: RateLimitPolicy) -> None:
        if policy.max_requests < 1:
            raise ValueError("rate limit max_requests must be at least 1")
        if policy.window_seconds < 1:
            raise ValueError("rate limit window_seconds must be at least 1")

        client = _shared_redis_client(self._redis_url)
        try:
            result = client.eval(
                _REDIS_RATE_LIMIT_SCRIPT,
                2,
                f"flood-risk:{self._namespace}:{client_key}",
                f"flood-risk:{self._namespace}-seq:{client_key}",
                int(self._clock() * 1000),
                policy.window_seconds * 1000,
                policy.max_requests,
            )
        except redis.RedisError as exc:
            raise RateLimitUnavailable(str(exc)) from exc

        allowed, retry_ms = _parse_redis_rate_limit_result(result)
        if not allowed:
            raise RateLimitExceeded(
                retry_after_seconds=max(1, ceil(retry_ms / 1000)),
                policy=policy,
            )


class RedisUserReportRateLimiter(RedisRateLimiter):
    def __init__(self, *, redis_url: str, clock: Callable[[], float] = time) -> None:
        super().__init__(
            redis_url=redis_url,
            namespace="user-report-rate",
            clock=clock,
        )

    def check(self, *, client_key: str, policy: RateLimitPolicy) -> None:
        try:
            super().check(client_key=client_key, policy=policy)
        except RateLimitExceeded as exc:
            raise UserReportRateLimitExceeded(
                retry_after_seconds=exc.retry_after_seconds,
                policy=exc.policy,
            ) from exc
        except RateLimitUnavailable as exc:
            raise UserReportRateLimitUnavailable(str(exc)) from exc


UserReportRateLimitPolicy = RateLimitPolicy
PUBLIC_ENDPOINT_RATE_LIMITER = InMemoryRateLimiter()
USER_REPORT_INTAKE_RATE_LIMITER = InMemoryUserReportRateLimiter()


def check_rate_limit(
    *,
    client_key: str,
    namespace: str,
    max_requests: int,
    window_seconds: int,
    backend: RateLimitBackend = "redis",
    redis_url: str | None = None,
    limiter: InMemoryRateLimiter = PUBLIC_ENDPOINT_RATE_LIMITER,
) -> None:
    policy = RateLimitPolicy(
        max_requests=max_requests,
        window_seconds=window_seconds,
    )
    if backend == "redis":
        if redis_url is None:
            raise RateLimitUnavailable("redis_url is required for redis rate limiting")
        RedisRateLimiter(redis_url=redis_url, namespace=namespace).check(
            client_key=client_key,
            policy=policy,
        )
        return

    limiter.check(
        client_key=f"{namespace}:{client_key}",
        policy=policy,
    )


def check_user_report_intake_rate_limit(
    *,
    client_key: str,
    max_requests: int,
    window_seconds: int,
    backend: UserReportRateLimitBackend = "redis",
    redis_url: str | None = None,
    limiter: InMemoryUserReportRateLimiter = USER_REPORT_INTAKE_RATE_LIMITER,
) -> None:
    policy = RateLimitPolicy(
        max_requests=max_requests,
        window_seconds=window_seconds,
    )
    if backend == "redis":
        if redis_url is None:
            raise UserReportRateLimitUnavailable("redis_url is required for redis rate limiting")
        RedisUserReportRateLimiter(redis_url=redis_url).check(
            client_key=client_key,
            policy=policy,
        )
        return

    limiter.check(
        client_key=client_key,
        policy=policy,
    )


def _parse_redis_rate_limit_result(result: object) -> tuple[bool, int]:
    if not isinstance(result, list | tuple) or len(result) != 2:
        raise RateLimitUnavailable("unexpected Redis rate-limit script response")
    return bool(int(result[0])), int(result[1])
