from __future__ import annotations

import inspect
from datetime import UTC, datetime

from app.api.schemas import NearbyCoverageSignal, NearbyRealtimeCoverage
from app.domain.assessment import (
    AssessmentData,
    AssessmentSourceState,
    apply_realtime_safety,
    compose_base_overall,
)
from app.domain.risk import RiskScoringResult

NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
NATIONAL_REQUIRED_KEYS = frozenset(
    {
        "official.cwa.rainfall",
        "official.wra.water_level",
    }
)


def _source_state(source_key: str, *, state: str = "fresh") -> AssessmentSourceState:
    return AssessmentSourceState(
        source_key=source_key,
        signal_type=source_key.rsplit(".", 1)[-1],
        state=state,
        observed_at=NOW,
        checked_at=NOW,
        message=None,
    )


def all_required_sources_fresh() -> tuple[AssessmentSourceState, ...]:
    return tuple(_source_state(key) for key in sorted(NATIONAL_REQUIRED_KEYS))


def all_required_national_sources_fresh() -> tuple[AssessmentSourceState, ...]:
    return all_required_sources_fresh()


def one_required_source_failed() -> tuple[AssessmentSourceState, ...]:
    return (
        _source_state("official.cwa.rainfall", state="failed"),
        _source_state("official.wra.water_level"),
    )


def coverage_with(
    **signals: tuple[str, float],
) -> NearbyRealtimeCoverage:
    breakdown = [
        NearbyCoverageSignal(
            signal_type=signal_type,
            label=signal_type,
            coverage_level="high" if state in {"fresh_nearby", "degraded_nearby"} else "low",
            availability_state=state,
            nearest_distance_m=distance_m,
            nearest_source_id=f"test:{signal_type}",
            nearest_observed_at=NOW,
            counts_by_radius_m={"2000": int(distance_m <= 2_000)},
            fresh_count=int(state == "fresh_nearby"),
            degraded_count=int(state == "degraded_nearby"),
            stale_count=0,
            status_only_count=0,
            nearest_freshness_state=(
                "fresh"
                if state == "fresh_nearby"
                else "degraded"
                if state == "degraded_nearby"
                else None
            ),
            source_health_status="healthy",
            source_count=1,
            failed_source_count=0,
            missing_cause="none",
        )
        for signal_type, (state, distance_m) in signals.items()
    ]
    return NearbyRealtimeCoverage(
        overall_level="high",
        evaluated_at=NOW,
        query_radius_m=2_000,
        radius_buckets_m=[2_000],
        summary="test coverage",
        signal_breakdown=breakdown,
        missing_signal_types=[],
        limitations=[],
        source_health_status="healthy",
        source_health_checked=True,
        jurisdiction_status="verified",
        jurisdiction_checked=True,
        jurisdiction_catalog_complete=True,
        home_jurisdiction="高雄市",
        considered_jurisdictions=["高雄市"],
        county_level_note="county context only",
    )


def assessment_data(
    *,
    coverage: NearbyRealtimeCoverage | None = None,
    source_states: tuple[AssessmentSourceState, ...] | None = None,
    required_realtime_source_keys: frozenset[str] = NATIONAL_REQUIRED_KEYS,
    local_machine_feed_missing: tuple[str, ...] = (),
) -> AssessmentData:
    return AssessmentData(
        current_official=(),
        historical=(),
        nearby_coverage=coverage
        or coverage_with(
            rainfall=("fresh_nearby", 900.0),
            water_level=("fresh_nearby", 1_200.0),
        ),
        source_states=source_states or all_required_sources_fresh(),
        required_realtime_source_keys=required_realtime_source_keys,
        current_available=True,
        historical_available=True,
        coverage_available=True,
        health_available=True,
        jurisdiction_available=True,
        resolved_admin_code="64000",
        resolved_admin_name="高雄市",
        local_machine_feed_missing=local_machine_feed_missing,
    )


def _scoring(*, realtime_level: str, historical_level: str = "未知") -> RiskScoringResult:
    return RiskScoringResult(
        score_version="test",
        realtime_score=0.0,
        historical_score=0.0,
        confidence_score=0.9,
        realtime_level=realtime_level,
        historical_level=historical_level,
        confidence_level="高",
        explanation_summary="test scoring",
        main_reasons=("test reason",),
        missing_sources=(),
    )


def low_scoring() -> RiskScoringResult:
    return _scoring(realtime_level="低")


def high_scoring() -> RiskScoringResult:
    return _scoring(realtime_level="高")


def unknown_scoring() -> RiskScoringResult:
    return _scoring(realtime_level="未知")


def medium_history_scoring() -> RiskScoringResult:
    return _scoring(realtime_level="未知", historical_level="中")


def extreme_history_scoring() -> RiskScoringResult:
    return _scoring(realtime_level="未知", historical_level="極高")


def test_fresh_station_outside_query_local_radius_cannot_support_low() -> None:
    data = assessment_data(
        coverage=coverage_with(
            rainfall=("regional_reference", 8_000.0),
            water_level=("regional_reference", 7_000.0),
        ),
        source_states=all_required_sources_fresh(),
    )
    assert apply_realtime_safety(low_scoring(), data).realtime_level == "未知"


def test_query_local_rainfall_and_hydrology_can_support_low() -> None:
    data = assessment_data(
        coverage=coverage_with(
            rainfall=("fresh_nearby", 900.0),
            water_level=("fresh_nearby", 1_200.0),
        ),
        source_states=all_required_sources_fresh(),
    )
    assert apply_realtime_safety(low_scoring(), data).realtime_level == "低"


def test_reviewed_nearby_signals_can_support_low_outside_display_radius() -> None:
    data = assessment_data(
        coverage=coverage_with(
            rainfall=("fresh_nearby", 4_000.0),
            water_level=("degraded_nearby", 3_500.0),
        ),
        source_states=all_required_sources_fresh(),
    )

    assert data.nearby_coverage.query_radius_m == 2_000
    assert apply_realtime_safety(low_scoring(), data).realtime_level == "低"


def test_informational_local_gap_does_not_override_reviewed_required_mapping() -> None:
    data = assessment_data(
        coverage=coverage_with(
            rainfall=("fresh_nearby", 900.0),
            flood_depth=("fresh_nearby", 700.0),
        ),
        source_states=all_required_national_sources_fresh(),
        required_realtime_source_keys=NATIONAL_REQUIRED_KEYS,
        local_machine_feed_missing=("高雄市地方政府機器介面尚未核准",),
    )
    assert apply_realtime_safety(low_scoring(), data).realtime_level == "低"


def test_failed_required_source_changes_only_low_to_unknown() -> None:
    data = assessment_data(source_states=one_required_source_failed())
    assert apply_realtime_safety(low_scoring(), data).realtime_level == "未知"
    assert apply_realtime_safety(high_scoring(), data).realtime_level == "高"


def test_core_composer_uses_higher_realtime_risk() -> None:
    decision = compose_base_overall(high_scoring(), medium_history_scoring())
    assert (decision.level, decision.dominant_mode) == ("高", "realtime")


def test_core_composer_uses_higher_history_as_conservative_context() -> None:
    decision = compose_base_overall(low_scoring(), extreme_history_scoring())

    assert (decision.level, decision.dominant_mode) == ("極高", "historical_context")
    assert decision.confidence == extreme_history_scoring().confidence_level
    assert "不表示目前正在淹水" in " ".join(decision.reasons)


def test_core_composer_labels_history_only_as_context() -> None:
    decision = compose_base_overall(unknown_scoring(), medium_history_scoring())
    assert (decision.level, decision.dominant_mode) == ("中", "historical_context")


def test_core_composer_has_no_community_uplift() -> None:
    signature = inspect.signature(compose_base_overall)
    assert tuple(signature.parameters) == ("realtime_scoring", "historical_scoring")
