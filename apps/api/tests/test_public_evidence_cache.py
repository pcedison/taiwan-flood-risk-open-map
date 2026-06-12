from datetime import UTC, datetime

import pytest
import redis

import app.api.services.public_evidence_cache as evidence_cache
from app.api.schemas import Evidence, LatLng
from app.api.services.redis_support import FailOpenRedisClients


NOW = datetime(2026, 6, 12, 8, 0, tzinfo=UTC)


class _FakeRedis:
    def __init__(self, *, fail: bool = False) -> None:
        self.store: dict[str, bytes] = {}
        self.fail = fail
        self.get_calls = 0
        self.setex_calls: list[tuple[str, int]] = []

    def get(self, key: str) -> bytes | None:
        self.get_calls += 1
        if self.fail:
            raise redis.RedisError("redis down")
        return self.store.get(key)

    def setex(self, key: str, ttl: int, value: bytes) -> None:
        if self.fail:
            raise redis.RedisError("redis down")
        self.setex_calls.append((key, ttl))
        self.store[key] = value


@pytest.fixture(autouse=True)
def isolated_cache_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(evidence_cache, "_MEMORY_CACHE", {})
    monkeypatch.setattr(evidence_cache, "_REDIS_CLIENTS", FailOpenRedisClients())


def _evidence(evidence_id: str = "evidence-1") -> Evidence:
    return Evidence(
        id=evidence_id,
        source_id="data-gov-9177:station-1",
        source_type="official",
        event_type="rainfall",
        title="測試用雨量站",
        summary="測試用觀測摘要",
        ingested_at=NOW,
        confidence=0.8,
        freshness_score=0.9,
        source_weight=1.0,
        privacy_level="public",
        point=LatLng(lat=25.033, lng=121.5654),
    )


def test_memory_backend_roundtrip_and_fifo_eviction() -> None:
    evidence_cache.store_evidence("assessment-1", [_evidence()])

    cached = evidence_cache.cached_evidence("assessment-1")
    assert cached is not None
    assert cached[0].id == "evidence-1"

    for index in range(evidence_cache._MEMORY_CACHE_MAX_ENTRIES):
        evidence_cache.store_evidence(f"assessment-extra-{index}", [_evidence()])

    assert evidence_cache.cached_evidence("assessment-1") is None


def test_redis_backend_stores_and_reads_serialized_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_redis = _FakeRedis()
    monkeypatch.setattr(
        "app.api.services.public_evidence_cache.redis.Redis.from_url",
        lambda *_, **__: fake_redis,
    )

    evidence_cache.store_evidence(
        "assessment-1",
        [_evidence()],
        ttl_seconds=3600,
        backend="redis",
        redis_url="redis://example.test:6379/0",
    )

    assert len(fake_redis.setex_calls) == 1
    stored_key, stored_ttl = fake_redis.setex_calls[0]
    assert stored_key == "flood-risk:assessment-evidence:assessment-1"
    assert stored_ttl == 3600

    monkeypatch.setattr(evidence_cache, "_MEMORY_CACHE", {})
    cached = evidence_cache.cached_evidence(
        "assessment-1",
        backend="redis",
        redis_url="redis://example.test:6379/0",
    )
    assert cached is not None
    assert cached[0].id == "evidence-1"
    assert cached[0].title == "測試用雨量站"


def test_memory_hit_skips_redis_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_redis = _FakeRedis()
    monkeypatch.setattr(
        "app.api.services.public_evidence_cache.redis.Redis.from_url",
        lambda *_, **__: fake_redis,
    )

    evidence_cache.store_evidence(
        "assessment-1",
        [_evidence()],
        ttl_seconds=3600,
        backend="redis",
        redis_url="redis://example.test:6379/0",
    )
    cached = evidence_cache.cached_evidence(
        "assessment-1",
        backend="redis",
        redis_url="redis://example.test:6379/0",
    )

    assert cached is not None
    assert fake_redis.get_calls == 0


def test_zero_ttl_skips_redis_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_redis = _FakeRedis()
    monkeypatch.setattr(
        "app.api.services.public_evidence_cache.redis.Redis.from_url",
        lambda *_, **__: fake_redis,
    )

    evidence_cache.store_evidence(
        "assessment-1",
        [_evidence()],
        ttl_seconds=0,
        backend="redis",
        redis_url="redis://example.test:6379/0",
    )

    assert fake_redis.setex_calls == []
    assert evidence_cache.cached_evidence("assessment-1") is not None


def test_redis_failure_fails_open_to_memory_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_redis = _FakeRedis(fail=True)
    monkeypatch.setattr(
        "app.api.services.public_evidence_cache.redis.Redis.from_url",
        lambda *_, **__: fake_redis,
    )

    evidence_cache.store_evidence(
        "assessment-1",
        [_evidence()],
        ttl_seconds=3600,
        backend="redis",
        redis_url="redis://example.test:6379/0",
    )
    cached = evidence_cache.cached_evidence(
        "assessment-1",
        backend="redis",
        redis_url="redis://example.test:6379/0",
    )

    assert cached is not None
    assert cached[0].id == "evidence-1"


def test_redis_failure_pauses_redis_attempts_for_cooldown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_redis = _FakeRedis(fail=True)
    monkeypatch.setattr(
        "app.api.services.public_evidence_cache.redis.Redis.from_url",
        lambda *_, **__: fake_redis,
    )

    evidence_cache.store_evidence(
        "assessment-1",
        [_evidence()],
        ttl_seconds=3600,
        backend="redis",
        redis_url="redis://example.test:6379/0",
    )
    assert evidence_cache._REDIS_CLIENTS.retry_at > 0.0

    evidence_cache.cached_evidence(
        "assessment-2",
        backend="redis",
        redis_url="redis://example.test:6379/0",
    )
    assert fake_redis.get_calls == 0
