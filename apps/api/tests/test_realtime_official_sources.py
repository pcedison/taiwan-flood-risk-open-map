import ssl
from datetime import UTC, datetime, timedelta
from urllib.error import URLError

import pytest

import app.domain.realtime.official as official


@pytest.fixture(autouse=True)
def clear_official_json_cache() -> None:
    official._json_cache.clear()
    official._json_refreshing_keys.clear()
    yield
    official._json_cache.clear()
    official._json_refreshing_keys.clear()


def test_official_realtime_bundle_can_disable_cwa_and_wra_individually(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        official,
        "_nearest_rainfall_observation",
        lambda **_kwargs: pytest.fail("CWA lookup should not run when disabled"),
    )
    monkeypatch.setattr(
        official,
        "_nearest_water_level_observation",
        lambda **_kwargs: pytest.fail("WRA lookup should not run when disabled"),
    )

    now = datetime(2026, 5, 4, 8, 0, tzinfo=UTC)
    bundle = official.fetch_official_realtime_bundle(
        lat=23.05753,
        lng=120.20144,
        radius_m=500,
        enabled=True,
        cwa_enabled=False,
        wra_enabled=False,
        now=now,
    )

    assert bundle.observations == ()
    assert [status.source_id for status in bundle.source_statuses] == [
        "cwa-rainfall",
        "wra-water-level",
    ]
    assert all(status.health_status == "degraded" for status in bundle.source_statuses)
    assert "尚未啟用" in bundle.source_statuses[0].message
    assert "未品管" in bundle.source_statuses[1].message


def test_official_realtime_global_disable_reports_both_sources_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        official,
        "_nearest_rainfall_observation",
        lambda **_kwargs: pytest.fail("CWA lookup should not run when globally disabled"),
    )
    monkeypatch.setattr(
        official,
        "_nearest_water_level_observation",
        lambda **_kwargs: pytest.fail("WRA lookup should not run when globally disabled"),
    )

    bundle = official.fetch_official_realtime_bundle(
        lat=23.05753,
        lng=120.20144,
        radius_m=500,
        enabled=False,
        cwa_enabled=True,
        wra_enabled=True,
        now=datetime(2026, 5, 4, 8, 0, tzinfo=UTC),
    )

    assert bundle.observations == ()
    assert [status.message for status in bundle.source_statuses] == [
        "即時雨量資料來源目前已停用。",
        "即時水位資料來源目前已停用。",
    ]


def test_enabled_cwa_without_token_reports_missing_process_secret() -> None:
    observations, status = official._nearest_rainfall_observation(
        lat=23.05753,
        lng=120.20144,
        radius_m=500,
        cwa_authorization=None,
        checked_at=datetime(2026, 5, 4, 8, 0, tzinfo=UTC),
    )

    assert observations == []
    assert status.source_id == "cwa-rainfall"
    assert status.health_status == "failed"
    assert "CWA_API_AUTHORIZATION 未載入" in (status.message or "")
    assert "重新啟動服務" in (status.message or "")


def test_far_wra_station_is_reported_as_limited_not_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        official,
        "_fetch_wra_water_level_stations",
        lambda: (
            official._WaterLevelStation(
                station_id="wra-far",
                station_name="長潤橋",
                river_name="典寶溪排水",
                lat=22.752,
                lng=120.260,
                observed_at=datetime(2026, 5, 5, 14, 20, tzinfo=UTC),
                water_level_m=0.09,
                alert_level_1_m=None,
                alert_level_2_m=None,
            ),
        ),
    )

    observations, status = official._nearest_water_level_observation(
        lat=22.68709,
        lng=120.30761,
        radius_m=500,
        checked_at=datetime(2026, 5, 5, 14, 30, tzinfo=UTC),
    )

    assert observations == []
    assert status.source_id == "wra-water-level"
    assert status.health_status == "degraded"
    assert "長潤橋" in (status.message or "")
    assert "未納入本次即時風險判斷" in (status.message or "")


def test_far_wra_station_exclusion_applies_across_taiwan_regions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    representative_points = (
        ("台北", 25.04776, 121.51706),
        ("台中", 24.13716, 120.68686),
        ("高雄", 22.68192, 120.28909),
        ("花蓮", 23.9928, 121.60195),
        ("澎湖", 23.56548, 119.58627),
        ("金門", 24.43213, 118.31708),
        ("連江", 26.16024, 119.95167),
    )
    observed_at = datetime(2026, 5, 5, 14, 20, tzinfo=UTC)

    for label, lat, lng in representative_points:
        far_station = official._WaterLevelStation(
            station_id=f"wra-far-{label}",
            station_name=f"{label}遠距測站",
            river_name="測試排水",
            lat=lat + 0.05,
            lng=lng,
            observed_at=observed_at,
            water_level_m=0.09,
            alert_level_1_m=None,
            alert_level_2_m=None,
        )
        monkeypatch.setattr(
            official,
            "_fetch_wra_water_level_stations",
            lambda station=far_station: (station,),
        )

        observations, status = official._nearest_water_level_observation(
            lat=lat,
            lng=lng,
            radius_m=500,
            checked_at=datetime(2026, 5, 5, 14, 30, tzinfo=UTC),
        )

        assert observations == [], label
        assert status.health_status == "degraded", label
        assert "超過 3,000 公尺參考範圍" in (status.message or ""), label
        assert "未納入本次即時風險判斷" in (status.message or ""), label


def test_near_low_wra_station_remains_low_risk_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_at = datetime(2026, 5, 5, 14, 20, tzinfo=UTC)
    monkeypatch.setattr(
        official,
        "_fetch_wra_water_level_stations",
        lambda: (
            official._WaterLevelStation(
                station_id="wra-near",
                station_name="左營測站",
                river_name="測試排水",
                lat=22.6872,
                lng=120.3078,
                observed_at=observed_at,
                water_level_m=0.09,
                alert_level_1_m=2.5,
                alert_level_2_m=None,
            ),
        ),
    )

    observations, status = official._nearest_water_level_observation(
        lat=22.68709,
        lng=120.30761,
        radius_m=500,
        checked_at=datetime(2026, 5, 5, 14, 30, tzinfo=UTC),
    )

    assert status.health_status == "healthy"
    assert len(observations) == 1
    assert observations[0].risk_factor == 0.0
    assert "未達警戒門檻" in observations[0].summary


def test_fetch_json_uses_configured_official_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_timeouts: list[float] = []

    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"ok": true}'

    def fake_urlopen(request: object, *, timeout: float, **_kwargs: object) -> Response:
        captured_timeouts.append(timeout)
        return Response()

    monkeypatch.setenv("OFFICIAL_REALTIME_FETCH_TIMEOUT_SECONDS", "1.25")
    monkeypatch.setattr(official, "urlopen", fake_urlopen)

    assert official._fetch_json("https://example.test/realtime.json") == {"ok": True}
    assert captured_timeouts == [1.25]


def test_fetch_json_returns_none_on_ssl_error_without_unverified_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_kwargs: list[dict[str, object]] = []

    def fail_unverified_context() -> None:
        pytest.fail("official realtime fetch must not create an unverified TLS context")

    def fake_urlopen(request: object, *, timeout: float, **kwargs: object) -> object:
        captured_kwargs.append(kwargs)
        raise ssl.SSLError("certificate verify failed")

    monkeypatch.setattr(official.ssl, "_create_unverified_context", fail_unverified_context)
    monkeypatch.setattr(official, "urlopen", fake_urlopen)

    assert official._fetch_json("https://example.test/realtime.json") is None
    assert captured_kwargs == [{}]


def test_fetch_json_returns_none_on_urlerror_ssl_reason_without_unverified_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_kwargs: list[dict[str, object]] = []

    def fail_unverified_context() -> None:
        pytest.fail("official realtime fetch must not create an unverified TLS context")

    def fake_urlopen(request: object, *, timeout: float, **kwargs: object) -> object:
        captured_kwargs.append(kwargs)
        raise URLError(ssl.SSLError("certificate verify failed"))

    monkeypatch.setattr(official.ssl, "_create_unverified_context", fail_unverified_context)
    monkeypatch.setattr(official, "urlopen", fake_urlopen)

    assert official._fetch_json("https://example.test/realtime.json") is None
    assert captured_kwargs == [{}]


def test_fetch_json_allows_explicit_local_diagnostic_tls_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_kwargs: list[dict[str, object]] = []
    unverified_context = object()

    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"ok": true}'

    def fake_unverified_context() -> object:
        return unverified_context

    def fake_urlopen(request: object, *, timeout: float, **kwargs: object) -> object:
        captured_kwargs.append(kwargs)
        if "context" not in kwargs:
            raise URLError(ssl.SSLError("certificate verify failed"))
        assert kwargs["context"] is unverified_context
        return Response()

    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("REALTIME_OFFICIAL_DIAGNOSTIC_FALLBACK_ENABLED", "true")
    monkeypatch.setattr(official.ssl, "_create_unverified_context", fake_unverified_context)
    monkeypatch.setattr(official, "urlopen", fake_urlopen)

    assert official._fetch_json("https://example.test/realtime.json") == {"ok": True}
    assert captured_kwargs == [{}, {"context": unverified_context}]


def test_fetch_json_blocks_diagnostic_tls_retry_in_hosted_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_kwargs: list[dict[str, object]] = []

    def fail_unverified_context() -> None:
        pytest.fail("hosted official realtime fetch must not create an unverified TLS context")

    def fake_urlopen(request: object, *, timeout: float, **kwargs: object) -> object:
        captured_kwargs.append(kwargs)
        raise URLError(ssl.SSLError("certificate verify failed"))

    monkeypatch.setenv("APP_ENV", "production-beta")
    monkeypatch.setenv("REALTIME_OFFICIAL_DIAGNOSTIC_FALLBACK_ENABLED", "true")
    monkeypatch.setattr(official.ssl, "_create_unverified_context", fail_unverified_context)
    monkeypatch.setattr(official, "urlopen", fake_urlopen)

    assert official._fetch_json("https://example.test/realtime.json") is None
    assert captured_kwargs == [{}]


@pytest.mark.parametrize("app_env", [None, "staging", "production", "production-beta"])
def test_official_source_tls_failure_yields_failed_status_without_unverified_context(
    monkeypatch: pytest.MonkeyPatch,
    app_env: str | None,
) -> None:
    fetch_attempts = 0
    unverified_context_calls = 0

    if app_env is None:
        monkeypatch.delenv("APP_ENV", raising=False)
    else:
        monkeypatch.setenv("APP_ENV", app_env)

    def fail_unverified_context() -> None:
        nonlocal unverified_context_calls
        unverified_context_calls += 1
        pytest.fail("official realtime fetch must not create an unverified TLS context")

    def fake_urlopen(request: object, *, timeout: float, **kwargs: object) -> object:
        nonlocal fetch_attempts
        assert "context" not in kwargs
        fetch_attempts += 1
        raise ssl.SSLError("certificate verify failed")

    monkeypatch.setattr(official.ssl, "_create_unverified_context", fail_unverified_context)
    monkeypatch.setattr(official, "urlopen", fake_urlopen)

    observations, status = official._nearest_water_level_observation(
        lat=22.68709,
        lng=120.30761,
        radius_m=500,
        checked_at=datetime(2026, 5, 5, 14, 30, tzinfo=UTC),
    )

    assert observations == []
    assert status.source_id == "wra-water-level"
    assert status.health_status == "failed"
    assert fetch_attempts == 2
    assert unverified_context_calls == 0


def test_expired_official_cache_returns_stale_payload_and_refreshes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class InlineExecutor:
        def submit(self, fn: object, *args: object) -> object:
            assert callable(fn)
            fn(*args)

            class CompletedFuture:
                pass

            return CompletedFuture()

    monkeypatch.setenv("OFFICIAL_REALTIME_CACHE_STALE_SECONDS", "600")
    monkeypatch.setattr(official, "_CACHE_REFRESH_EXECUTOR", InlineExecutor())
    monkeypatch.setattr(
        official,
        "_fetch_json",
        lambda _url: {"fresh": True},
    )
    official._json_cache["cwa-rainfall"] = (
        datetime.now(UTC) - timedelta(seconds=301),
        {"stale": True},
    )

    payload = official._fetch_cached_json(
        "cwa-rainfall",
        "https://example.test/realtime.json",
        ttl=300,
    )

    assert payload == {"stale": True}
    assert official._json_cache["cwa-rainfall"][1] == {"fresh": True}
