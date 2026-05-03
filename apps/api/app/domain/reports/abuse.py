from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from math import ceil
from threading import Lock
from time import monotonic, time
from typing import Literal

import redis


UserReportRateLimitBackend = Literal["redis", "memory"]
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
class UserReportRateLimitPolicy:
    max_requests: int
    window_seconds: int


class UserReportRateLimitExceeded(RuntimeError):
    def __init__(self, *, retry_after_seconds: int, policy: UserReportRateLimitPolicy) -> None:
        super().__init__("user report intake rate limit exceeded")
        self.retry_after_seconds = retry_after_seconds
        self.policy = policy


class UserReportRateLimitUnavailable(RuntimeError):
    """Raised when the configured shared abuse guard cannot be reached."""


class InMemoryUserReportRateLimiter:
    def __init__(self, *, clock: Callable[[], float] = monotonic) -> None:
        self._clock = clock
        self._requests_by_client: dict[str, deque[float]] = {}
        self._lock = Lock()

    def check(self, *, client_key: str, policy: UserReportRateLimitPolicy) -> None:
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
                raise UserReportRateLimitExceeded(
                    retry_after_seconds=retry_after,
                    policy=policy,
                )

            requests.append(now)


class RedisUserReportRateLimiter:
    def __init__(self, *, redis_url: str, clock: Callable[[], float] = time) -> None:
        self._redis_url = redis_url
        self._clock = clock

    def check(self, *, client_key: str, policy: UserReportRateLimitPolicy) -> None:
        if policy.max_requests < 1:
            raise ValueError("rate limit max_requests must be at least 1")
        if policy.window_seconds < 1:
            raise ValueError("rate limit window_seconds must be at least 1")

        client = redis.Redis.from_url(
            self._redis_url,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        try:
            result = client.eval(
                _REDIS_RATE_LIMIT_SCRIPT,
                2,
                f"flood-risk:user-report-rate:{client_key}",
                f"flood-risk:user-report-rate-seq:{client_key}",
                int(self._clock() * 1000),
                policy.window_seconds * 1000,
                policy.max_requests,
            )
        except redis.RedisError as exc:
            raise UserReportRateLimitUnavailable(str(exc)) from exc
        finally:
            client.close()

        allowed, retry_ms = _parse_redis_rate_limit_result(result)
        if not allowed:
            raise UserReportRateLimitExceeded(
                retry_after_seconds=max(1, ceil(retry_ms / 1000)),
                policy=policy,
            )


USER_REPORT_INTAKE_RATE_LIMITER = InMemoryUserReportRateLimiter()


def check_user_report_intake_rate_limit(
    *,
    client_key: str,
    max_requests: int,
    window_seconds: int,
    backend: UserReportRateLimitBackend = "redis",
    redis_url: str | None = None,
    limiter: InMemoryUserReportRateLimiter = USER_REPORT_INTAKE_RATE_LIMITER,
) -> None:
    policy = UserReportRateLimitPolicy(
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
        raise UserReportRateLimitUnavailable("unexpected Redis rate-limit script response")
    return bool(int(result[0])), int(result[1])
