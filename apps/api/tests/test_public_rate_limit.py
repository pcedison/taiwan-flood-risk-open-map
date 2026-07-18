from __future__ import annotations

from hashlib import sha256
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient
import pytest

from app.api.routes import public as public_routes
from app.domain.reports.abuse import (
    RateLimitExceeded,
    RateLimitPolicy,
    RateLimitUnavailable,
)
from app.main import create_app


client = TestClient(create_app())


def _settings(
    *,
    app_env: str = "test",
    enabled: bool = True,
    backend: str = "memory",
    redis_url: str | None = "redis://example.test:6379/0",
) -> SimpleNamespace:
    return SimpleNamespace(
        service_id="flood-risk-api",
        app_env=app_env,
        public_rate_limit_enabled=enabled,
        public_rate_limit_backend=backend,
        public_rate_limit_client_header="x-forwarded-for",
        public_rate_limit_trusted_proxy_cidrs=(),
        geocode_rate_limit_max_requests=60,
        risk_assessment_rate_limit_max_requests=30,
        public_rate_limit_window_seconds=60,
        abuse_hash_salt="test-salt",
        redis_url=redis_url,
    )


class _FakeGeocoder:
    def geocode(self, _request: object) -> list[object]:
        return []


def test_geocode_rate_limit_allows_request_with_hashed_client_signal(monkeypatch) -> None:
    monkeypatch.setattr(public_routes, "get_settings", lambda: _settings())
    monkeypatch.setattr(public_routes, "_build_geocoder", lambda: _FakeGeocoder())
    calls: list[dict[str, Any]] = []

    def check(**kwargs: Any) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(public_routes, "check_rate_limit", check)

    response = client.post(
        "/v1/geocode",
        json={"query": "Taipei 101", "input_type": "landmark", "limit": 1},
        headers={"x-forwarded-for": "203.0.113.10, 10.0.0.1"},
    )

    assert response.status_code == 200
    assert response.json() == {"candidates": []}
    assert calls == [
        {
            "client_key": sha256(
                "public-geocode-rate:test-salt:203.0.113.10".encode("utf-8")
            ).hexdigest(),
            "namespace": "public-geocode-rate",
            "backend": "memory",
            "redis_url": "redis://example.test:6379/0",
            "max_requests": 60,
            "window_seconds": 60,
        }
    ]


def _geocode_client_key_for_header(
    monkeypatch,
    header_value: str,
    *,
    trusted_proxy_cidrs: tuple[str, ...] = (),
) -> str:
    settings = _settings()
    settings.public_rate_limit_trusted_proxy_cidrs = trusted_proxy_cidrs
    monkeypatch.setattr(public_routes, "get_settings", lambda: settings)
    monkeypatch.setattr(public_routes, "_build_geocoder", lambda: _FakeGeocoder())
    calls: list[dict[str, Any]] = []

    def check(**kwargs: Any) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(public_routes, "check_rate_limit", check)
    response = client.post(
        "/v1/geocode",
        json={"query": "Taipei 101", "input_type": "landmark", "limit": 1},
        headers={"x-forwarded-for": header_value},
    )
    assert response.status_code == 200
    return str(calls[0]["client_key"])


def _expected_key(signal: str) -> str:
    return sha256(f"public-geocode-rate:test-salt:{signal}".encode("utf-8")).hexdigest()


def test_spoofed_left_forwarded_entries_cannot_rotate_the_rate_limit_bucket(
    monkeypatch,
) -> None:
    # Attacker-supplied values sit on the LEFT of the chain; the ingress
    # appends the real peer address to the right. The signal must come from
    # the right-most hop that is not one of our own proxies.
    key = _geocode_client_key_for_header(
        monkeypatch, "6.6.6.6, 203.0.113.10, 10.0.0.1"
    )
    assert key == _expected_key("203.0.113.10")

    rotated = _geocode_client_key_for_header(
        monkeypatch, "7.7.7.7, 203.0.113.10, 10.0.0.1"
    )
    assert rotated == key  # rotating the spoofed value must not change the bucket


def test_fully_private_forwarded_chain_uses_the_original_client_hop(
    monkeypatch,
) -> None:
    key = _geocode_client_key_for_header(monkeypatch, "192.168.1.50, 127.0.0.1")
    assert key == _expected_key("192.168.1.50")


def test_operator_trusted_proxy_cidrs_are_skipped_like_private_hops(
    monkeypatch,
) -> None:
    # A public-IP proxy layer (for example a CDN egress range) can be marked
    # trusted so the signal walks past it to the real client.
    key = _geocode_client_key_for_header(
        monkeypatch,
        "203.0.113.10, 198.51.100.7, 10.0.0.1",
        trusted_proxy_cidrs=("198.51.100.0/24",),
    )
    assert key == _expected_key("203.0.113.10")


@pytest.mark.parametrize(
    ("path", "payload", "namespace", "max_requests"),
    [
        (
            "/v1/geocode",
            {"query": "Taipei 101", "input_type": "landmark", "limit": 1},
            "public-geocode-rate",
            60,
        ),
        (
            "/v1/risk/assess",
            {
                "point": {"lat": 25.033, "lng": 121.5654},
                "radius_m": 500,
                "time_context": "now",
            },
            "public-risk-assess-rate",
            30,
        ),
    ],
)
def test_public_endpoint_rate_limited_returns_429(
    monkeypatch,
    path: str,
    payload: dict[str, object],
    namespace: str,
    max_requests: int,
) -> None:
    monkeypatch.setattr(public_routes, "get_settings", lambda: _settings())

    def rate_limited(**kwargs: Any) -> None:
        assert kwargs["namespace"] == namespace
        assert kwargs["max_requests"] == max_requests
        raise RateLimitExceeded(
            retry_after_seconds=17,
            policy=RateLimitPolicy(max_requests=max_requests, window_seconds=60),
        )

    monkeypatch.setattr(public_routes, "check_rate_limit", rate_limited)
    monkeypatch.setattr(
        public_routes,
        "fetch_official_realtime_bundle",
        lambda **_kwargs: pytest.fail("rate-limited risk request should stop before work"),
    )
    monkeypatch.setattr(
        public_routes,
        "_build_geocoder",
        lambda: pytest.fail("rate-limited geocode request should stop before work"),
    )

    response = client.post(path, json=payload)

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "17"
    payload = response.json()
    assert payload["error"]["code"] == "rate_limited"
    assert payload["error"]["details"] == {
        "retry_after_seconds": 17,
        "window_seconds": 60,
    }


def test_hosted_public_rate_limit_uses_redis_even_if_memory_is_configured(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        public_routes,
        "get_settings",
        lambda: _settings(app_env="production-beta", backend="memory"),
    )
    calls: list[dict[str, Any]] = []

    def unavailable(**kwargs: Any) -> None:
        calls.append(kwargs)
        raise RateLimitUnavailable("redis unavailable")

    monkeypatch.setattr(public_routes, "check_rate_limit", unavailable)

    response = client.post(
        "/v1/geocode",
        json={"query": "Taipei 101", "input_type": "landmark", "limit": 1},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "abuse_guard_unavailable"
    assert calls[0]["backend"] == "redis"


def test_hosted_public_rate_limit_fails_closed_without_redis_url(monkeypatch) -> None:
    monkeypatch.setattr(
        public_routes,
        "get_settings",
        lambda: _settings(app_env="production-beta", backend="redis", redis_url=None),
    )

    response = client.post(
        "/v1/geocode",
        json={"query": "Taipei 101", "input_type": "landmark", "limit": 1},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "abuse_guard_unavailable"
