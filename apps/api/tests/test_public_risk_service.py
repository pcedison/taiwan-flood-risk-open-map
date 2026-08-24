from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any, Literal

import pytest

from app.api.schemas import (
    ConfidenceBlock,
    DataFreshness,
    Explanation,
    LatLng,
    NearbyRealtimeCoverage,
    QueryHeat,
    RiskAssessmentResponse,
    RiskAssessRequest,
    RiskLevelBlock,
)
from app.api.services import public_risk
from app.domain.evidence.repository import (
    EvidenceRecord,
    NearbyCoverageRow,
)
from app.domain.realtime import OfficialRealtimeBundle, OfficialRealtimeObservation


def _risk_request() -> RiskAssessRequest:
    return RiskAssessRequest(
        point=LatLng(lat=25.033, lng=121.5654),
        radius_m=500,
        time_context="now",
    )


def _risk_response(
    request: RiskAssessRequest,
    *,
    assessment_id: str = "cached-assessment",
    created_at: datetime | None = None,
) -> RiskAssessmentResponse:
    created_at = created_at or datetime.fromisoformat("2026-06-09T03:00:00+00:00")
    return RiskAssessmentResponse(
        assessment_id=assessment_id,
        location=request.point,
        radius_m=request.radius_m,
        score_version="test-score",
        created_at=created_at,
        expires_at=created_at + timedelta(minutes=10),
        realtime=RiskLevelBlock(level="未知"),
        historical=RiskLevelBlock(level="未知"),
        confidence=ConfidenceBlock(level="未知"),
        explanation=Explanation(summary="cached response"),
        evidence=[],
        data_freshness=[
            DataFreshness(
                source_id="test-source",
                name="測試來源",
                health_status="unknown",
                ingested_at=created_at,
            )
        ],
        query_heat=QueryHeat(
            period="P7D",
            attention_level="未知",
            query_count_bucket=None,
            unique_approx_count_bucket=None,
            updated_at=created_at,
        ),
        nearby_realtime_coverage=public_risk.build_placeholder_nearby_realtime_coverage(
            evaluated_at=created_at, query_radius_m=request.radius_m
        ),
    )


def _nearby_coverage(
    *, evaluated_at: datetime, query_radius_m: int = 500
) -> NearbyRealtimeCoverage:
    return NearbyRealtimeCoverage(
        overall_level="medium",
        evaluated_at=evaluated_at,
        query_radius_m=query_radius_m,
        radius_buckets_m=[500, 1000, 3000, 5000],
        summary="nearby realtime coverage available",
        signal_breakdown=[],
        missing_signal_types=["flood_depth"],
        limitations=["coverage is query-point specific"],
        county_level_note="county source coverage is not nearby sensor coverage",
    )


def _unavailable_nearby_coverage(
    *, evaluated_at: datetime, query_radius_m: int = 500
) -> NearbyRealtimeCoverage:
    return NearbyRealtimeCoverage(
        overall_level="unavailable",
        evaluated_at=evaluated_at,
        query_radius_m=query_radius_m,
        radius_buckets_m=[500, 1000, 3000, 5000],
        summary="nearby realtime coverage repository unavailable",
        signal_breakdown=[],
        missing_signal_types=["rainfall", "water_level", "flood_depth", "sewer_water_level"],
        limitations=["repository unavailable"],
        county_level_note="county source coverage is not nearby sensor coverage",
    )


def _official_observation(
    *,
    event_type: Literal["rainfall", "water_level"] = "rainfall",
    source_id: str = "cwa-rainfall:station-1",
    distance_to_query_m: float = 230.0,
    observed_at: datetime,
) -> OfficialRealtimeObservation:
    return OfficialRealtimeObservation(
        source_id=source_id,
        source_name="Realtime station",
        event_type=event_type,
        title="Realtime station",
        summary="Realtime observation",
        observed_at=observed_at,
        ingested_at=observed_at,
        lat=25.033,
        lng=121.5654,
        distance_to_query_m=distance_to_query_m,
        confidence=0.92,
        freshness_score=1.0,
        source_weight=1.0,
        risk_factor=0.0,
    )


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        app_env="test",
        cwa_api_authorization=None,
        realtime_official_enabled=True,
        source_cwa_api_enabled=True,
        source_wra_api_enabled=True,
        historical_news_on_demand_writeback_enabled=False,
        risk_assessment_response_cache_seconds=120,
    )


def _dependencies(**overrides: Any) -> public_risk.RiskAssessmentDependencies:
    def fail(*_args: Any, **_kwargs: Any) -> Any:
        pytest.fail("unexpected risk service dependency call")

    values: dict[str, Any] = {
        "risk_assessment_response_cache_key": fail,
        "cached_risk_assessment_response": fail,
        "fetch_official_realtime_bundle": fail,
        "nearby_realtime_coverage": fail,
        "nearby_db_evidence": fail,
        "official_flood_disaster_lookup": fail,
        "can_use_profile_fast_path": fail,
        "precomputed_risk_profile": fail,
        "profile_has_public_news": fail,
        "enqueue_profile_refresh": fail,
        "profile_backed_response": fail,
        "cache_risk_assessment_response": fail,
        "fallback_historical_records": fail,
        "use_local_historical_fallback": fail,
        "on_demand_public_news_result": fail,
        "needs_historical_event_lookup": fail,
        "persist_or_build_on_demand_evidence": fail,
        "historical_data_freshness": fail,
        "display_evidence_items": fail,
        "persisted_official_realtime_data_freshness": fail,
        "visible_source_limitations": fail,
        "official_flood_disaster_data_freshness": fail,
        "on_demand_data_freshness": fail,
        "persist_assessment": fail,
        "query_heat": fail,
    }
    values.update(overrides)
    return public_risk.RiskAssessmentDependencies(**values)


def _db_evidence_record(
    *,
    source_id: str,
    event_type: str,
    raw_ref: str | None = None,
) -> EvidenceRecord:
    observed_at = datetime.fromisoformat("2026-06-09T03:00:00+00:00")
    return EvidenceRecord(
        id=f"{source_id}-id",
        source_id=source_id,
        source_type="official",
        event_type=event_type,
        title=f"{event_type} evidence",
        summary="db evidence",
        url=None,
        occurred_at=observed_at,
        observed_at=observed_at,
        ingested_at=observed_at,
        lat=25.033,
        lng=121.5654,
        geometry={"type": "Point", "coordinates": [121.5654, 25.033]},
        distance_to_query_m=120.0,
        confidence=0.9,
        freshness_score=0.9,
        source_weight=1.0,
        privacy_level="public",
        raw_ref=raw_ref,
    )


def test_assess_risk_returns_cached_response_before_source_work() -> None:
    request = _risk_request()
    created_at = datetime.fromisoformat("2026-06-09T03:00:00+00:00")
    cached_response = _risk_response(request, created_at=created_at)

    result = public_risk.assess_risk(
        request,
        settings=_settings(),
        created_at=created_at,
        dependencies=_dependencies(
            risk_assessment_response_cache_key=lambda *_args: "cache-key",
            cached_risk_assessment_response=lambda *_args, **_kwargs: cached_response,
        ),
    )

    assert result is cached_response


def test_assess_risk_includes_nearby_realtime_coverage() -> None:
    request = _risk_request()
    created_at = datetime.fromisoformat("2026-06-09T03:00:00+00:00")
    coverage = _nearby_coverage(evaluated_at=created_at)
    persisted: dict[str, Any] = {}

    response = public_risk.assess_risk(
        request,
        settings=_settings(),
        created_at=created_at,
        dependencies=_dependencies(
            risk_assessment_response_cache_key=lambda *_args: "standard-cache-key",
            cached_risk_assessment_response=lambda *_args, **_kwargs: None,
            fetch_official_realtime_bundle=lambda **_kwargs: OfficialRealtimeBundle(
                observations=(),
                source_statuses=(),
            ),
            nearby_realtime_coverage=lambda _request, *, now: coverage,
            nearby_db_evidence=lambda _request: (),
            official_flood_disaster_lookup=lambda *_args, **_kwargs: SimpleNamespace(records=()),
            can_use_profile_fast_path=lambda _items: False,
            needs_historical_event_lookup=lambda **_kwargs: False,
            persist_or_build_on_demand_evidence=lambda *_args, **_kwargs: (),
            historical_data_freshness=lambda **_kwargs: DataFreshness(
                source_id="historical-flood-records",
                name="historical records",
                health_status="unknown",
                ingested_at=created_at,
            ),
            display_evidence_items=lambda items: items,
            persisted_official_realtime_data_freshness=lambda *_args, **_kwargs: [],
            visible_source_limitations=lambda *_args, **_kwargs: [],
            official_flood_disaster_data_freshness=lambda _lookup: [],
            on_demand_data_freshness=lambda *_args, **_kwargs: [],
            persist_assessment=lambda **kwargs: persisted.update(kwargs),
            query_heat=lambda _request, *, now: QueryHeat(
                period="P7D",
                attention_level="低",
                query_count_bucket=None,
                unique_approx_count_bucket=None,
                updated_at=now,
            ),
            cache_risk_assessment_response=lambda *_args, **_kwargs: None,
        ),
    )

    assert response.nearby_realtime_coverage == coverage
    assert persisted["nearby_realtime_coverage"] == coverage


def test_assess_risk_uses_realtime_bridge_for_nearby_coverage_when_repository_unavailable() -> None:
    request = _risk_request()
    created_at = datetime.fromisoformat("2026-06-09T03:00:00+00:00")
    coverage = _unavailable_nearby_coverage(evaluated_at=created_at)
    observation = _official_observation(observed_at=created_at - timedelta(minutes=5))
    persisted: dict[str, Any] = {}

    response = public_risk.assess_risk(
        request,
        settings=_settings(),
        created_at=created_at,
        dependencies=_dependencies(
            risk_assessment_response_cache_key=lambda *_args: "standard-cache-key",
            cached_risk_assessment_response=lambda *_args, **_kwargs: None,
            fetch_official_realtime_bundle=lambda **_kwargs: OfficialRealtimeBundle(
                observations=(observation,),
                source_statuses=(),
            ),
            nearby_realtime_coverage=lambda _request, *, now: coverage,
            nearby_db_evidence=lambda _request: (),
            official_flood_disaster_lookup=lambda *_args, **_kwargs: SimpleNamespace(records=()),
            can_use_profile_fast_path=lambda _items: False,
            needs_historical_event_lookup=lambda **_kwargs: False,
            persist_or_build_on_demand_evidence=lambda *_args, **_kwargs: (),
            historical_data_freshness=lambda **_kwargs: DataFreshness(
                source_id="historical-flood-records",
                name="historical records",
                health_status="unknown",
                ingested_at=created_at,
            ),
            display_evidence_items=lambda items: items,
            persisted_official_realtime_data_freshness=lambda *_args, **_kwargs: [],
            visible_source_limitations=lambda *_args, **_kwargs: [],
            official_flood_disaster_data_freshness=lambda _lookup: [],
            on_demand_data_freshness=lambda *_args, **_kwargs: [],
            persist_assessment=lambda **kwargs: persisted.update(kwargs),
            query_heat=lambda _request, *, now: QueryHeat(
                period="P7D",
                attention_level="低",
                query_count_bucket=None,
                unique_approx_count_bucket=None,
                updated_at=now,
            ),
            cache_risk_assessment_response=lambda *_args, **_kwargs: None,
        ),
    )

    assert response.nearby_realtime_coverage.overall_level != "unavailable"
    rainfall = next(
        item
        for item in response.nearby_realtime_coverage.signal_breakdown
        if item.signal_type == "rainfall"
    )
    assert rainfall.nearest_source_id == observation.source_id
    assert rainfall.counts_by_radius_m["500"] == 1
    assert persisted["nearby_realtime_coverage"] == response.nearby_realtime_coverage


def test_assess_risk_repairs_empty_repository_coverage_with_realtime_observation() -> None:
    request = _risk_request()
    created_at = datetime.fromisoformat("2026-06-09T03:00:00+00:00")
    empty_coverage = public_risk.build_nearby_realtime_coverage(
        rows=(),
        query_radius_m=request.radius_m,
        evaluated_at=created_at,
    )
    observation = _official_observation(
        observed_at=created_at - timedelta(minutes=16),
        distance_to_query_m=2042.0,
    )

    repaired = public_risk._nearby_realtime_coverage_with_bridge_fallback(
        empty_coverage,
        OfficialRealtimeBundle(observations=(observation,), source_statuses=()),
        request=request,
        created_at=created_at,
    )

    rainfall = next(item for item in repaired.signal_breakdown if item.signal_type == "rainfall")
    assert repaired.overall_level == "low"
    assert rainfall.nearest_distance_m == 2042.0
    assert rainfall.degraded_count == 1


def test_bridge_fallback_preserves_existing_repository_observations() -> None:
    request = _risk_request()
    created_at = datetime.fromisoformat("2026-06-09T03:00:00+00:00")
    repository_coverage = public_risk.build_nearby_realtime_coverage(
        rows=(
            NearbyCoverageRow(
                adapter_key="local.tainan.flood_sensor",
                source_id="tainan-flood-sensor:station-1",
                event_type="flood_report",
                station_id="station-1",
                observed_at=created_at - timedelta(hours=4),
                ingested_at=created_at - timedelta(hours=4),
                distance_to_query_m=900.0,
                freshness_state="stale",
            ),
        ),
        query_radius_m=request.radius_m,
        evaluated_at=created_at,
    )
    bridge_observation = _official_observation(
        observed_at=created_at - timedelta(minutes=5),
        distance_to_query_m=230.0,
    )

    repaired = public_risk._nearby_realtime_coverage_with_bridge_fallback(
        repository_coverage,
        OfficialRealtimeBundle(observations=(bridge_observation,), source_statuses=()),
        request=request,
        created_at=created_at,
    )

    assert repaired == repository_coverage
    flood_depth = next(
        item for item in repaired.signal_breakdown if item.signal_type == "flood_depth"
    )
    assert flood_depth.nearest_source_id == "tainan-flood-sensor:station-1"
    assert flood_depth.availability_state == "stale_observation"


def test_bridge_freshness_uses_inclusive_ten_and_thirty_minute_boundaries() -> None:
    now = datetime.fromisoformat("2026-06-09T03:00:00+00:00")
    exactly_ten = _official_observation(observed_at=now - timedelta(minutes=10))
    exactly_thirty = _official_observation(observed_at=now - timedelta(minutes=30))
    over_thirty = _official_observation(
        observed_at=now - timedelta(minutes=30, microseconds=1)
    )

    assert public_risk._official_realtime_freshness_state(exactly_ten, now=now) == "fresh"
    assert (
        public_risk._official_realtime_freshness_state(exactly_thirty, now=now)
        == "degraded"
    )
    assert public_risk._official_realtime_freshness_state(over_thirty, now=now) == "stale"


def test_assess_risk_profile_fast_path_receives_nearby_realtime_coverage() -> None:
    request = _risk_request()
    created_at = datetime.fromisoformat("2026-06-09T03:00:00+00:00")
    profile = object()
    coverage = _nearby_coverage(evaluated_at=created_at)
    expected_response = _risk_response(
        request,
        assessment_id="profile-assessment",
        created_at=created_at,
    )
    calls: dict[str, Any] = {}

    def profile_backed_response(**kwargs: Any) -> RiskAssessmentResponse:
        calls["profile_kwargs"] = kwargs
        return expected_response

    result = public_risk.assess_risk(
        request,
        settings=_settings(),
        created_at=created_at,
        dependencies=_dependencies(
            risk_assessment_response_cache_key=lambda *_args: "profile-cache-key",
            cached_risk_assessment_response=lambda *_args, **_kwargs: None,
            fetch_official_realtime_bundle=lambda **_kwargs: OfficialRealtimeBundle(
                observations=(),
                source_statuses=(),
            ),
            nearby_realtime_coverage=lambda _request, *, now: coverage,
            nearby_db_evidence=lambda _request: (),
            official_flood_disaster_lookup=lambda *_args, **_kwargs: SimpleNamespace(records=()),
            can_use_profile_fast_path=lambda _items: True,
            precomputed_risk_profile=lambda *_args, **_kwargs: profile,
            profile_has_public_news=lambda _profile: True,
            enqueue_profile_refresh=lambda *_args, **_kwargs: None,
            profile_backed_response=profile_backed_response,
            cache_risk_assessment_response=lambda *_args, **_kwargs: None,
        ),
    )

    assert result is expected_response
    assert calls["profile_kwargs"]["nearby_realtime_coverage"] == coverage


def test_assess_risk_profile_fast_path_refreshes_and_caches_response() -> None:
    request = _risk_request()
    created_at = datetime.fromisoformat("2026-06-09T03:00:00+00:00")
    profile = object()
    coverage = _nearby_coverage(evaluated_at=created_at)
    expected_response = _risk_response(
        request,
        assessment_id="profile-assessment",
        created_at=created_at,
    )
    calls: dict[str, Any] = {}

    def profile_backed_response(**kwargs: Any) -> RiskAssessmentResponse:
        calls["profile_kwargs"] = kwargs
        return expected_response

    def cache_response(*args: Any, **kwargs: Any) -> None:
        calls["cache_args"] = args
        calls["cache_kwargs"] = kwargs

    result = public_risk.assess_risk(
        request,
        settings=_settings(),
        created_at=created_at,
        dependencies=_dependencies(
            risk_assessment_response_cache_key=lambda *_args: "profile-cache-key",
            cached_risk_assessment_response=lambda *_args, **_kwargs: None,
            fetch_official_realtime_bundle=lambda **_kwargs: OfficialRealtimeBundle(
                observations=(),
                source_statuses=(),
            ),
            nearby_realtime_coverage=lambda _request, *, now: coverage,
            nearby_db_evidence=lambda _request: (),
            official_flood_disaster_lookup=lambda *_args, **_kwargs: SimpleNamespace(records=()),
            can_use_profile_fast_path=lambda _items: True,
            precomputed_risk_profile=lambda *_args, **_kwargs: profile,
            profile_has_public_news=lambda _profile: True,
            enqueue_profile_refresh=lambda _profile, **kwargs: calls.setdefault(
                "refresh_kwargs",
                kwargs,
            ),
            profile_backed_response=profile_backed_response,
            cache_risk_assessment_response=cache_response,
        ),
    )

    assert result is expected_response
    assert calls["refresh_kwargs"] == {"request": request}
    assert calls["profile_kwargs"]["profile"] is profile
    assert calls["profile_kwargs"]["realtime_bundle"].observations == ()
    assert calls["profile_kwargs"]["nearby_realtime_coverage"] == coverage
    assert calls["cache_args"] == ("profile-cache-key", expected_response)
    assert calls["cache_kwargs"] == {
        "now": created_at,
        "ttl_seconds": 120,
    }
