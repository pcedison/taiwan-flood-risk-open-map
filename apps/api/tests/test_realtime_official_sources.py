from datetime import UTC, datetime

import pytest

import app.domain.realtime.official as official


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
