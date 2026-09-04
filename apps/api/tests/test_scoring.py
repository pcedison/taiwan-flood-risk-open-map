from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest

from app.domain.risk import RiskEvidenceSignal, RiskScoringResult, score_risk

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "scoring"


@pytest.mark.parametrize(
    "fixture_name",
    [
        "flood_potential_only.json",
        "heavy_rainfall_water_level.json",
        "no_evidence_found.json",
        "partial_source_outage.json",
        "stale_official_realtime.json",
        "conflicting_public_report_low_official_signal.json",
    ],
)
def test_scoring_golden_fixtures(fixture_name: str) -> None:
    fixture = json.loads((FIXTURE_DIR / fixture_name).read_text(encoding="utf-8"))
    result = score_risk(
        tuple(_signal_from_fixture(signal) for signal in fixture["signals"]),
        now=datetime.fromisoformat(fixture["now"]),
    )

    expected = fixture["expected"]
    assert result.score_version == expected["score_version"]
    assert result.realtime_level == expected["realtime_level"]
    assert result.historical_level == expected["historical_level"]
    assert result.confidence_level == expected["confidence_level"]
    assert result.missing_sources == tuple(expected["missing_sources"])
    assert result.main_reasons
    assert result.explanation_summary


def test_scoring_returns_unknown_without_evidence() -> None:
    result = score_risk((), now=datetime.fromisoformat("2026-04-29T00:00:00+00:00"))

    assert result.realtime_level == "未知"
    assert result.historical_level == "未知"
    assert result.confidence_level == "未知"


def test_status_only_context_signals_never_move_the_score() -> None:
    now = datetime.fromisoformat("2026-08-26T02:20:00+00:00")
    context = RiskEvidenceSignal(
        source_type="official",
        event_type="status_only",
        confidence=0.62,
        distance_to_query_m=30.0,
        freshness_score=0.95,
        source_weight=1.0,
        observed_at=now,
    )

    baseline = score_risk((), now=now)
    with_context = score_risk((context,), now=now)

    assert with_context.realtime_score == baseline.realtime_score
    assert with_context.historical_score == baseline.historical_score
    assert with_context.realtime_level == baseline.realtime_level
    assert with_context.historical_level == baseline.historical_level
    assert with_context.realtime_level == "未知"
    assert with_context.historical_level == "未知"


def _score_fixture(name: str) -> RiskScoringResult:
    payload = json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))
    return score_risk(
        tuple(_signal_from_fixture(item) for item in payload["signals"]),
        now=datetime.fromisoformat(payload["now"]),
    )


def test_partial_source_outage_can_be_low_before_public_safety_gate() -> None:
    result = _score_fixture("partial_source_outage.json")

    assert result.realtime_level == "低"
    assert result.missing_sources


def test_stale_official_realtime_is_unknown_in_base_scorer() -> None:
    assert _score_fixture("stale_official_realtime.json").realtime_level == "未知"


def test_overlapping_flood_potential_polygons_do_not_stack_to_extreme() -> None:
    signals = tuple(
        RiskEvidenceSignal(
            source_type="official",
            event_type="flood_potential",
            confidence=0.78,
            distance_to_query_m=0.0,
            freshness_score=1.0,
            source_weight=1.0,
        )
        for _ in range(31)
    )

    result = score_risk(signals, now=datetime.fromisoformat("2026-05-05T14:30:00+00:00"))

    assert result.historical_score == 40.0
    assert result.historical_level == "中"
    assert result.realtime_level == "未知"
    assert "情境參考" in result.main_reasons[0]


def test_scoring_explains_observed_history_and_official_potential_counts() -> None:
    signals = (
        RiskEvidenceSignal(
            source_type="news",
            event_type="flood_report",
            confidence=0.86,
            distance_to_query_m=54.0,
            freshness_score=0.95,
            source_weight=1.0,
        ),
        RiskEvidenceSignal(
            source_type="news",
            event_type="flood_report",
            confidence=0.78,
            distance_to_query_m=918.0,
            freshness_score=0.95,
            source_weight=0.9,
        ),
        RiskEvidenceSignal(
            source_type="official",
            event_type="flood_potential",
            confidence=0.78,
            distance_to_query_m=0.0,
            freshness_score=0.7,
            source_weight=1.0,
        ),
    )

    result = score_risk(signals, now=datetime.fromisoformat("2026-05-12T00:00:00+00:00"))

    assert "2 筆官方災點、公開新聞或淹水事件紀錄" in result.main_reasons[0]
    assert "1 筆官方淹水潛勢規劃圖資" in result.main_reasons[1]


def test_observed_flood_report_within_one_km_is_at_least_medium_history() -> None:
    result = score_risk(
        (
            RiskEvidenceSignal(
                source_type="official",
                event_type="flood_report",
                confidence=0.82,
                distance_to_query_m=958.0,
                freshness_score=0.74,
                source_weight=1.0,
            ),
        ),
        now=datetime.fromisoformat("2026-05-13T00:00:00+00:00"),
    )

    assert result.historical_score == 25.0
    assert result.historical_level == "中"


def test_current_zero_depth_sensor_is_not_scored_or_described_as_history() -> None:
    now = datetime.fromisoformat("2026-08-29T02:00:00+00:00")
    result = score_risk(
        (
            RiskEvidenceSignal(
                source_type="official",
                event_type="flood_report",
                confidence=0.9,
                distance_to_query_m=700.0,
                freshness_score=0.9,
                source_weight=1.0,
                risk_factor=0.0,
                observed_at=now,
                evidence_scope="current",
            ),
        ),
        now=now,
    )

    assert result.realtime_level == "低"
    assert result.historical_level == "未知"
    assert not any("官方災點" in reason for reason in result.main_reasons)


def test_correlated_nearby_station_count_cannot_inflate_signal_family_score() -> None:
    now = datetime.fromisoformat("2026-08-29T02:00:00+00:00")
    signals = tuple(
        RiskEvidenceSignal(
            source_type="official",
            event_type=event_type,
            confidence=1.0,
            distance_to_query_m=50.0,
            freshness_score=1.0,
            source_weight=1.0,
            risk_factor=1.0,
            observed_at=now,
            evidence_scope="current",
        )
        for event_type in ("rainfall",) * 20 + ("water_level",) * 20
    )

    result = score_risk(signals, now=now)

    assert result.realtime_score == 75.0
    assert result.realtime_level == "高"
    assert result.historical_level == "未知"


def test_correlated_station_family_uses_strongest_observation_not_station_count() -> None:
    now = datetime.fromisoformat("2026-08-29T02:00:00+00:00")

    def rainfall_signal() -> RiskEvidenceSignal:
        return RiskEvidenceSignal(
            source_type="official",
            event_type="rainfall",
            confidence=1.0,
            distance_to_query_m=50.0,
            freshness_score=1.0,
            source_weight=1.0,
            risk_factor=0.25,
            observed_at=now,
            evidence_scope="current",
        )

    one_station = score_risk((rainfall_signal(),), now=now)
    four_stations = score_risk(tuple(rainfall_signal() for _ in range(4)), now=now)

    assert one_station.realtime_score == 10.0
    assert four_stations.realtime_score == one_station.realtime_score


def test_current_sensor_does_not_reduce_historical_potential_context_cap() -> None:
    now = datetime.fromisoformat("2026-08-29T02:00:00+00:00")
    result = score_risk(
        (
            RiskEvidenceSignal(
                source_type="official",
                event_type="flood_potential",
                confidence=1.0,
                distance_to_query_m=0.0,
                freshness_score=1.0,
                source_weight=1.0,
                evidence_scope="historical",
            ),
            RiskEvidenceSignal(
                source_type="official",
                event_type="flood_report",
                confidence=1.0,
                distance_to_query_m=100.0,
                freshness_score=1.0,
                source_weight=1.0,
                risk_factor=0.0,
                observed_at=now,
                evidence_scope="current",
            ),
        ),
        now=now,
    )

    assert result.historical_score == 40.0
    assert result.historical_level == "中"


def test_high_realtime_reason_names_the_signal_mix_without_implying_rain_only() -> None:
    observed_at = datetime.fromisoformat("2026-06-29T00:00:00+00:00")
    result = score_risk(
        (
            RiskEvidenceSignal(
                source_type="official",
                event_type="water_level",
                confidence=1.0,
                distance_to_query_m=80.0,
                freshness_score=1.0,
                source_weight=1.0,
                risk_factor=1.0,
                observed_at=observed_at,
            ),
            RiskEvidenceSignal(
                source_type="official",
                event_type="flood_warning",
                confidence=1.0,
                distance_to_query_m=80.0,
                freshness_score=1.0,
                source_weight=1.0,
                risk_factor=1.0,
                observed_at=observed_at,
            ),
            RiskEvidenceSignal(
                source_type="official",
                event_type="rainfall",
                confidence=1.0,
                distance_to_query_m=80.0,
                freshness_score=1.0,
                source_weight=1.0,
                risk_factor=1.0,
                observed_at=observed_at - timedelta(hours=7),
            ),
            RiskEvidenceSignal(
                source_type="official",
                event_type="flood_report",
                confidence=0.0,
                distance_to_query_m=80.0,
                freshness_score=1.0,
                source_weight=1.0,
                risk_factor=1.0,
                observed_at=observed_at,
            ),
            RiskEvidenceSignal(
                source_type="official",
                event_type="road_closure",
                confidence=1.0,
                distance_to_query_m=80.0,
                freshness_score=1.0,
                source_weight=0.0,
                risk_factor=1.0,
                observed_at=observed_at,
            ),
        ),
        now=observed_at,
    )

    assert result.realtime_level == "極高"
    reason_text = " ".join(result.main_reasons)
    assert "水位" in reason_text
    assert "官方警戒" in reason_text
    assert "雨量" not in reason_text
    assert "通報" not in reason_text
    assert "道路封閉" not in reason_text
    assert all("雨量或水位" not in reason for reason in result.main_reasons)


def test_flood_potential_context_does_not_escalate_single_observed_history_to_high() -> None:
    result = score_risk(
        (
            RiskEvidenceSignal(
                source_type="official",
                event_type="flood_report",
                confidence=0.82,
                distance_to_query_m=101.0,
                freshness_score=0.74,
                source_weight=1.0,
                location_precision="point",
            ),
            RiskEvidenceSignal(
                source_type="official",
                event_type="flood_potential",
                confidence=0.78,
                distance_to_query_m=185.0,
                freshness_score=1.0,
                source_weight=1.0,
            ),
            RiskEvidenceSignal(
                source_type="official",
                event_type="flood_potential",
                confidence=0.78,
                distance_to_query_m=240.0,
                freshness_score=1.0,
                source_weight=1.0,
            ),
        ),
        now=datetime.fromisoformat("2026-06-10T14:30:00+00:00"),
    )

    assert result.historical_score == 45.0
    assert result.historical_level == "中"
    assert result.realtime_level == "未知"


def test_weak_admin_area_report_cannot_lower_flood_potential_context_score() -> None:
    # A single weak, imprecise flood_report must never make the historical
    # score go DOWN relative to having no such report at all: that would mean
    # garbage evidence actively suppresses a legitimate flood_potential score.
    now = datetime.fromisoformat("2026-09-05T00:00:00+00:00")
    flood_potential_only = score_risk(
        (
            RiskEvidenceSignal(
                source_type="official",
                event_type="flood_potential",
                confidence=0.9,
                distance_to_query_m=0.0,
                freshness_score=0.8,
                source_weight=1.0,
            ),
        ),
        now=now,
    )
    with_weak_admin_area_report = score_risk(
        (
            RiskEvidenceSignal(
                source_type="official",
                event_type="flood_potential",
                confidence=0.9,
                distance_to_query_m=0.0,
                freshness_score=0.8,
                source_weight=1.0,
            ),
            RiskEvidenceSignal(
                source_type="news",
                event_type="flood_report",
                confidence=0.4,
                distance_to_query_m=None,
                freshness_score=0.5,
                source_weight=0.5,
                location_precision="admin_area",
            ),
        ),
        now=now,
    )

    assert with_weak_admin_area_report.historical_score >= flood_potential_only.historical_score


def test_admin_area_only_historical_evidence_is_capped_at_medium() -> None:
    # Mirrors the production bug: several admin-area-level citations of the
    # same generic county-wide event, each floored to the observed-history
    # minimum, would otherwise stack to "極高" with no point-level backing.
    now = datetime.fromisoformat("2026-09-01T00:00:00+00:00")
    signals = tuple(
        RiskEvidenceSignal(
            source_type="news",
            event_type="flood_report",
            confidence=0.6,
            distance_to_query_m=100.0,
            freshness_score=0.9,
            source_weight=1.0,
            location_precision="admin_area",
        )
        for _ in range(4)
    )

    result = score_risk(signals, now=now)

    assert result.historical_score <= 40.0
    assert result.historical_level == "中"


def test_point_precision_historical_evidence_is_not_reduced() -> None:
    now = datetime.fromisoformat("2026-09-01T00:00:00+00:00")

    def flood_report(precision: str) -> RiskEvidenceSignal:
        return RiskEvidenceSignal(
            source_type="news",
            event_type="flood_report",
            confidence=0.9,
            distance_to_query_m=2000.0,
            freshness_score=0.95,
            source_weight=1.0,
            location_precision=precision,
        )

    point_result = score_risk((flood_report("point"),), now=now)
    admin_area_result = score_risk((flood_report("admin_area"),), now=now)

    expected_unweighted = 35.0 * 0.9 * 0.95 * 0.5
    assert point_result.historical_score == pytest.approx(expected_unweighted, abs=0.001)
    assert point_result.historical_score > admin_area_result.historical_score


def test_realtime_flood_report_score_is_unaffected_by_location_precision() -> None:
    now = datetime.fromisoformat("2026-09-01T00:00:00+00:00")

    def current_flood_report(precision: str) -> RiskEvidenceSignal:
        return RiskEvidenceSignal(
            source_type="official",
            event_type="flood_report",
            confidence=0.9,
            distance_to_query_m=80.0,
            freshness_score=0.95,
            source_weight=1.0,
            risk_factor=1.0,
            observed_at=now,
            evidence_scope="current",
            location_precision=precision,
        )

    admin_area_result = score_risk((current_flood_report("admin_area"),), now=now)
    point_result = score_risk((current_flood_report("point"),), now=now)

    assert admin_area_result.realtime_score == point_result.realtime_score
    assert admin_area_result.realtime_level == point_result.realtime_level


def _signal_from_fixture(payload: dict[str, object]) -> RiskEvidenceSignal:
    observed_at = payload.get("observed_at")
    return RiskEvidenceSignal(
        source_type=str(payload["source_type"]),
        event_type=str(payload["event_type"]),
        confidence=float(cast(Any, payload["confidence"])),
        distance_to_query_m=float(cast(Any, payload["distance_to_query_m"]))
        if payload.get("distance_to_query_m") is not None
        else None,
        freshness_score=float(cast(Any, payload["freshness_score"])),
        source_weight=float(cast(Any, payload["source_weight"])),
        risk_factor=float(cast(Any, payload.get("risk_factor", 1.0))),
        observed_at=datetime.fromisoformat(str(observed_at)) if observed_at else None,
        location_precision=str(payload.get("location_precision", "unknown")),
    )
