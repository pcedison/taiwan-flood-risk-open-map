import pytest
import redis

import app.api.services.public_geocode_cache as geocode_cache
from app.api.schemas import LatLng, PlaceCandidate
from app.api.services import public_geocoding
from app.api.services.redis_support import FailOpenRedisClients


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
    monkeypatch.setattr(geocode_cache, "_MEMORY_CACHE", {})
    monkeypatch.setattr(geocode_cache, "_REDIS_CLIENTS", FailOpenRedisClients())


def _candidate(place_id: str = "place-1") -> PlaceCandidate:
    return PlaceCandidate(
        place_id=place_id,
        name="測試地點",
        type="landmark",
        point=LatLng(lat=25.033, lng=121.5654),
        source="openstreetmap-nominatim",
        confidence=0.9,
        precision="poi",
        matched_query="測試地點",
    )


def test_memory_backend_roundtrip_and_ttl_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    current_time = 1_000.0
    monkeypatch.setattr(geocode_cache, "time", lambda: current_time)

    geocode_cache.store_candidates("key-a", (_candidate(),), ttl_seconds=600)
    cached = geocode_cache.cached_candidates("key-a")
    assert cached is not None
    assert cached[0].place_id == "place-1"

    current_time = 1_000.0 + 600.0
    assert geocode_cache.cached_candidates("key-a") is None


def test_empty_results_get_short_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_redis = _FakeRedis()
    monkeypatch.setattr(
        "app.api.services.public_geocode_cache.redis.Redis.from_url",
        lambda *_, **__: fake_redis,
    )

    geocode_cache.store_candidates(
        "key-a",
        (),
        ttl_seconds=86400,
        backend="redis",
        redis_url="redis://example.test:6379/0",
    )

    assert len(fake_redis.setex_calls) == 1
    _, stored_ttl = fake_redis.setex_calls[0]
    assert stored_ttl == 300

    cached = geocode_cache.cached_candidates("key-a")
    assert cached == ()


def test_zero_ttl_disables_cache() -> None:
    geocode_cache.store_candidates("key-a", (_candidate(),), ttl_seconds=0)

    assert geocode_cache.cached_candidates("key-a") is None
    assert geocode_cache._MEMORY_CACHE == {}


def test_redis_backend_stores_and_reads_serialized_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_redis = _FakeRedis()
    monkeypatch.setattr(
        "app.api.services.public_geocode_cache.redis.Redis.from_url",
        lambda *_, **__: fake_redis,
    )

    geocode_cache.store_candidates(
        "key-a",
        (_candidate(),),
        ttl_seconds=86400,
        backend="redis",
        redis_url="redis://example.test:6379/0",
    )

    stored_key, stored_ttl = fake_redis.setex_calls[0]
    assert stored_key == "flood-risk:geocode:key-a"
    assert stored_ttl == 86400

    monkeypatch.setattr(geocode_cache, "_MEMORY_CACHE", {})
    cached = geocode_cache.cached_candidates(
        "key-a",
        backend="redis",
        redis_url="redis://example.test:6379/0",
    )
    assert cached is not None
    assert cached[0].place_id == "place-1"
    assert cached[0].name == "測試地點"


def test_redis_failure_fails_open_to_memory_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_redis = _FakeRedis(fail=True)
    monkeypatch.setattr(
        "app.api.services.public_geocode_cache.redis.Redis.from_url",
        lambda *_, **__: fake_redis,
    )

    geocode_cache.store_candidates(
        "key-a",
        (_candidate(),),
        ttl_seconds=86400,
        backend="redis",
        redis_url="redis://example.test:6379/0",
    )
    cached = geocode_cache.cached_candidates(
        "key-a",
        backend="redis",
        redis_url="redis://example.test:6379/0",
    )

    assert cached is not None
    assert cached[0].place_id == "place-1"
    assert geocode_cache._REDIS_CLIENTS.retry_at > 0.0


def test_cached_nominatim_candidates_uses_cache_before_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetch_calls: list[str] = []

    def fake_fetch(query: str, input_type: str, limit: int) -> tuple[PlaceCandidate, ...]:
        fetch_calls.append(query)
        return (_candidate(),)

    monkeypatch.setattr(public_geocoding, "fetch_nominatim_candidates", fake_fetch)

    first = public_geocoding.cached_nominatim_candidates("台北車站", "landmark", 5)
    second = public_geocoding.cached_nominatim_candidates("台北車站", "landmark", 5)

    assert first == second
    assert fetch_calls == ["台北車站"]
