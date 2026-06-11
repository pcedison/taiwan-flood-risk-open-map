from datetime import UTC, datetime, timedelta

import pytest
import redis

import app.api.services.public_response_cache as response_cache
from app.api.schemas import (
    ConfidenceBlock,
    Explanation,
    LatLng,
    QueryHeat,
    RiskAssessmentResponse,
    RiskLevelBlock,
)


NOW = datetime(2026, 6, 11, 8, 0, tzinfo=UTC)


class _FakeRedis:
    def __init__(self, *, fail: bool = False) -> None:
        self.store: dict[str, str] = {}
        self.fail = fail
        self.get_calls = 0
        self.setex_calls: list[tuple[str, int]] = []

    def get(self, key: str) -> str | None:
        self.get_calls += 1
        if self.fail:
            raise redis.RedisError("redis down")
        return self.store.get(key)

    def setex(self, key: str, ttl: int, value: str) -> None:
        if self.fail:
            raise redis.RedisError("redis down")
        self.setex_calls.append((key, ttl))
        self.store[key] = value


@pytest.fixture(autouse=True)
def isolated_cache_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(response_cache, "_MEMORY_CACHE", {})
    monkeypatch.setattr(response_cache, "_redis_client", None)
    monkeypatch.setattr(response_cache, "_redis_client_url", None)
    monkeypatch.setattr(response_cache, "_redis_retry_at", 0.0)


def _response(assessment_id: str = "assessment-1") -> RiskAssessmentResponse:
    return RiskAssessmentResponse(
        assessment_id=assessment_id,
        location=LatLng(lat=25.033, lng=121.5654),
        radius_m=500,
        score_version="risk-v0.1.0",
        created_at=NOW,
        expires_at=NOW + timedelta(hours=6),
        realtime=RiskLevelBlock(level="低"),
        historical=RiskLevelBlock(level="中"),
        confidence=ConfidenceBlock(level="中"),
        explanation=Explanation(summary="測試用評估摘要"),
        evidence=[],
        data_freshness=[],
        query_heat=QueryHeat(period="weekly", attention_level="低", updated_at=NOW),
    )


def test_memory_backend_roundtrip_and_ttl_expiry() -> None:
    response_cache.store_response("key-a", _response(), now=NOW, ttl_seconds=120)

    cached = response_cache.cached_response("key-a", now=NOW + timedelta(seconds=60), ttl_seconds=120)
    assert cached is not None
    assert cached.assessment_id == "assessment-1"

    expired = response_cache.cached_response("key-a", now=NOW + timedelta(seconds=120), ttl_seconds=120)
    assert expired is None


def test_zero_ttl_disables_cache() -> None:
    response_cache.store_response("key-a", _response(), now=NOW, ttl_seconds=0)

    assert response_cache.cached_response("key-a", now=NOW, ttl_seconds=0) is None
    assert response_cache._MEMORY_CACHE == {}


def test_redis_backend_stores_and_reads_serialized_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_redis = _FakeRedis()
    monkeypatch.setattr(
        "app.api.services.public_response_cache.redis.Redis.from_url",
        lambda *_, **__: fake_redis,
    )

    response_cache.store_response(
        "key-a",
        _response(),
        now=NOW,
        ttl_seconds=120,
        backend="redis",
        redis_url="redis://example.test:6379/0",
    )

    assert len(fake_redis.setex_calls) == 1
    stored_key, stored_ttl = fake_redis.setex_calls[0]
    assert stored_key.startswith("flood-risk:risk-response:")
    assert stored_ttl == 120

    monkeypatch.setattr(response_cache, "_MEMORY_CACHE", {})
    cached = response_cache.cached_response(
        "key-a",
        now=NOW + timedelta(seconds=60),
        ttl_seconds=120,
        backend="redis",
        redis_url="redis://example.test:6379/0",
    )
    assert cached is not None
    assert cached.assessment_id == "assessment-1"


def test_redis_failure_fails_open_to_memory_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_redis = _FakeRedis(fail=True)
    monkeypatch.setattr(
        "app.api.services.public_response_cache.redis.Redis.from_url",
        lambda *_, **__: fake_redis,
    )

    response_cache.store_response(
        "key-a",
        _response(),
        now=NOW,
        ttl_seconds=120,
        backend="redis",
        redis_url="redis://example.test:6379/0",
    )
    cached = response_cache.cached_response(
        "key-a",
        now=NOW + timedelta(seconds=60),
        ttl_seconds=120,
        backend="redis",
        redis_url="redis://example.test:6379/0",
    )

    assert cached is not None
    assert cached.assessment_id == "assessment-1"


def test_redis_failure_pauses_redis_attempts_for_cooldown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_redis = _FakeRedis(fail=True)
    monkeypatch.setattr(
        "app.api.services.public_response_cache.redis.Redis.from_url",
        lambda *_, **__: fake_redis,
    )

    response_cache.store_response(
        "key-a",
        _response(),
        now=NOW,
        ttl_seconds=120,
        backend="redis",
        redis_url="redis://example.test:6379/0",
    )
    assert response_cache._redis_retry_at > 0.0

    response_cache.cached_response(
        "key-a",
        now=NOW,
        ttl_seconds=120,
        backend="redis",
        redis_url="redis://example.test:6379/0",
    )
    assert fake_redis.get_calls == 0
