from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any, Literal

import pytest

from app.api.schemas import (
    ConfidenceBlock,
    DataFreshness,
    Evidence,
    Explanation,
    LatLng,
    NearbyRealtimeCoverage,
    NearbySourceHealth,
    QueryHeat,
    RiskAssessmentResponse,
    RiskAssessRequest,
    RiskLevelBlock,
)
from app.api.services import public_evidence, public_risk
from app.domain.evidence import EvidenceUpsert
from app.domain.evidence.repository import (
    EvidenceRecord,
    NearbyCoverageRow,
)
from app.domain.history.news_enrichment import OnDemandNewsSearchResult
from app.domain.realtime import OfficialRealtimeBundle, OfficialRealtimeObservation


def test_worker_persisted_nstc_rows_replace_same_bundled_snapshot_ids() -> None:
    bundled_a = SimpleNamespace(source_id="data-gov-130016:2022:EMIC:1")
    bundled_b = SimpleNamespace(source_id="data-gov-130016:2019:EMIC:2")
    persisted = SimpleNamespace(source_id="data-gov-130016:2022:EMIC:1")

    filtered = public_risk._exclude_persisted_historical_records(
        ((bundled_a, 120.0), (bundled_b, 240.0)),  # type: ignore[arg-type]
        db_evidence_items=(persisted,),  # type: ignore[arg-type]
    )

    assert filtered == ((bundled_b, 240.0),)


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
        evidence_repository_enabled=True,
        historical_news_on_demand_writeback_enabled=False,
        risk_assessment_response_cache_seconds=120,
    )


def _standard_dependencies(
    created_at: datetime,
    *,
    db_evidence_items: tuple[Evidence, ...] | None = (),
    **overrides: Any,
) -> public_risk.RiskAssessmentDependencies:
    heat = QueryHeat(
        period="P7D",
        attention_level="低",
        query_count_bucket="1-9",
        unique_approx_count_bucket="1-9",
        updated_at=created_at,
    )
    values: dict[str, Any] = {
        "risk_assessment_response_cache_key": lambda *_args: "standard-cache-key",
        "cached_risk_assessment_response": lambda *_args, **_kwargs: None,
        "fetch_official_realtime_bundle": lambda **_kwargs: OfficialRealtimeBundle(
            observations=(),
            source_statuses=(),
        ),
        "nearby_realtime_coverage": lambda _request, *, now: _nearby_coverage(
            evaluated_at=now
        ),
        "nearby_db_evidence": lambda _request: db_evidence_items,
        "official_flood_disaster_lookup": lambda *_args, **_kwargs: SimpleNamespace(
            records=()
        ),
        "can_use_profile_fast_path": lambda _items: False,
        "use_local_historical_fallback": lambda _app_env: False,
        "needs_historical_event_lookup": lambda **_kwargs: False,
        "persist_or_build_on_demand_evidence": lambda *_args, **_kwargs: (),
        "historical_data_freshness": lambda **_kwargs: DataFreshness(
            source_id="historical-flood-records",
            name="historical records",
            health_status="unknown",
            ingested_at=created_at,
        ),
        "display_evidence_items": lambda items: items,
        "persisted_official_realtime_data_freshness": lambda *_args, **_kwargs: [],
        "visible_source_limitations": lambda *_args, **_kwargs: [],
        "official_flood_disaster_data_freshness": lambda _lookup: [],
        "on_demand_data_freshness": lambda *_args, **_kwargs: [],
        "persist_assessment": lambda **_kwargs: None,
        "query_heat": lambda _request, *, now: heat,
        "cache_risk_assessment_response": lambda *_args, **_kwargs: None,
    }
    values.update(overrides)
    return _dependencies(**values)


def _on_demand_record(created_at: datetime) -> EvidenceUpsert:
    return EvidenceUpsert(
        id="f442ec3f-f013-58d2-8fcb-93f62db8d51c",
        adapter_key="news.public_web.gdelt_backfill",
        source_id="gdelt-on-demand:legacy-characterization",
        source_type="news",
        event_type="flood_report",
        title="公開新聞補查淹水事件",
        summary="公開新聞 citation metadata",
        url="https://example.test/news/flood",
        occurred_at=created_at,
        observed_at=created_at,
        ingested_at=created_at,
        lat=25.033,
        lng=121.5654,
        distance_to_query_m=40.0,
        confidence=0.9,
        freshness_score=0.95,
        source_weight=1.0,
        privacy_level="public",
        raw_ref="gdelt-doc:legacy-characterization",
        properties={"full_text_stored": False},
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


def test_bridge_fallback_preserves_usable_repository_observations() -> None:
    request = _risk_request()
    created_at = datetime.fromisoformat("2026-06-09T03:00:00+00:00")
    repository_coverage = public_risk.build_nearby_realtime_coverage(
        rows=(
            NearbyCoverageRow(
                adapter_key="local.tainan.flood_sensor",
                source_id="tainan-flood-sensor:station-1",
                event_type="flood_report",
                station_id="station-1",
                observed_at=created_at - timedelta(minutes=4),
                ingested_at=created_at - timedelta(minutes=4),
                distance_to_query_m=900.0,
                freshness_state="fresh",
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
    assert flood_depth.availability_state == "fresh_nearby"


def test_bridge_fallback_replaces_stale_only_repository_coverage() -> None:
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
        source_health=(
            NearbySourceHealth(
                source_id="tainan-flood-sensor",
                name="臺南市淹水感測",
                signal_types=["flood_depth"],
                coverage_scope="local",
                health_status="failed",
                reason_code="pipeline_stalled",
                checked_at=created_at,
                required_for_absence=True,
                message="背景更新近期沒有活動。",
            ),
        ),
        source_health_checked=True,
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

    assert repaired != repository_coverage
    assert repaired.overall_level == "low"
    assert repaired.source_health == repository_coverage.source_health
    assert repaired.source_health_checked is True
    assert repaired.source_health_status == "failed"
    rainfall = next(
        item for item in repaired.signal_breakdown if item.signal_type == "rainfall"
    )
    assert rainfall.nearest_distance_m == 230.0
    assert rainfall.fresh_count == 1
    flood_depth = next(
        item for item in repaired.signal_breakdown if item.signal_type == "flood_depth"
    )
    assert flood_depth.nearest_source_id is None
    assert flood_depth.stale_count == 0


def test_bridge_fallback_preserves_repository_when_bridge_is_stale_only() -> None:
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
    stale_bridge_observation = _official_observation(
        observed_at=created_at - timedelta(minutes=31),
        distance_to_query_m=230.0,
    )

    repaired = public_risk._nearby_realtime_coverage_with_bridge_fallback(
        repository_coverage,
        OfficialRealtimeBundle(
            observations=(stale_bridge_observation,),
            source_statuses=(),
        ),
        request=request,
        created_at=created_at,
    )

    assert repaired == repository_coverage


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


@pytest.mark.parametrize("profile_case", ["missing_public_news", "ineligible"])
def test_profile_rejection_falls_through_to_standard_response(
    profile_case: str,
) -> None:
    request = _risk_request()
    created_at = datetime.fromisoformat("2026-06-09T03:00:00+00:00")
    profile = object()
    trace: list[tuple[str, object]] = []
    overrides: dict[str, Any] = {
        "can_use_profile_fast_path": lambda _items: profile_case == "missing_public_news",
        "persist_assessment": lambda **kwargs: trace.append(("persist", kwargs)),
        "cache_risk_assessment_response": lambda _key, response, **_kwargs: trace.append(
            ("cache", response)
        ),
    }
    if profile_case == "missing_public_news":
        overrides.update(
            {
                "precomputed_risk_profile": lambda *_args, **_kwargs: profile,
                "profile_has_public_news": lambda candidate: candidate is profile and False,
            }
        )

    response = public_risk.assess_risk(
        request,
        settings=_settings(),
        created_at=created_at,
        dependencies=_standard_dependencies(created_at, **overrides),
    )

    assert [name for name, _value in trace] == ["persist", "cache"]
    assert trace[1][1] is response
    assert response.query_heat.query_count_bucket == "1-9"


@pytest.mark.parametrize(
    "repository_mode",
    ["unavailable", "available_needs_history"],
)
def test_on_demand_news_branches_propagate_result_and_persistence_inputs(
    repository_mode: str,
) -> None:
    request = _risk_request()
    created_at = datetime.fromisoformat("2026-06-09T03:00:00+00:00")
    record = _on_demand_record(created_at)
    result = OnDemandNewsSearchResult(
        attempted=True,
        source_id="on-demand-public-news",
        message="公開新聞補查取得一筆事件。",
        records=(record,),
        health_status="healthy",
    )
    evidence = public_evidence.evidence_from_upsert(record)
    historical_freshness = DataFreshness(
        source_id="captured-history",
        name="captured history",
        health_status="healthy",
        ingested_at=created_at,
        feature_count=1,
    )
    on_demand_freshness = DataFreshness(
        source_id="captured-on-demand",
        name="captured on-demand",
        health_status="healthy",
        ingested_at=created_at,
        feature_count=1,
    )
    limitations = [f"captured limitation: {repository_mode}"]
    calls: dict[str, Any] = {}

    def lookup(candidate: RiskAssessRequest, *, now: datetime) -> OnDemandNewsSearchResult:
        calls["lookup"] = (candidate, now)
        return result

    def needs_history(**kwargs: object) -> bool:
        if repository_mode == "unavailable":
            pytest.fail("unavailable repository does not use the DB-history gate")
        calls["needs_history"] = kwargs
        return True

    def writeback(
        candidate: OnDemandNewsSearchResult,
        *,
        writeback_enabled: bool,
    ) -> tuple[Evidence, ...]:
        if repository_mode == "unavailable":
            pytest.fail("unavailable repository cannot write back on-demand evidence")
        calls["writeback"] = (candidate, writeback_enabled)
        return (evidence,)

    def history_freshness(**kwargs: object) -> DataFreshness:
        calls["history_freshness"] = kwargs
        return historical_freshness

    def visible_limitations(
        bundle: OfficialRealtimeBundle,
        historical_records: object,
        db_items: object,
        on_demand: OnDemandNewsSearchResult,
    ) -> list[str]:
        calls["visible_limitations"] = (
            bundle,
            historical_records,
            db_items,
            on_demand,
        )
        return limitations

    def on_demand_freshness_items(
        candidate: OnDemandNewsSearchResult,
        *,
        now: datetime,
    ) -> list[DataFreshness]:
        calls["on_demand_freshness"] = (candidate, now)
        return [on_demand_freshness]

    def persist(**kwargs: object) -> None:
        calls["persist"] = kwargs

    settings = _settings()
    settings.historical_news_on_demand_writeback_enabled = True
    db_items: tuple[Evidence, ...] | None = (
        None if repository_mode == "unavailable" else ()
    )
    response = public_risk.assess_risk(
        request,
        settings=settings,
        created_at=created_at,
        dependencies=_standard_dependencies(
            created_at,
            db_evidence_items=db_items,
            on_demand_public_news_result=lookup,
            needs_historical_event_lookup=needs_history,
            persist_or_build_on_demand_evidence=writeback,
            historical_data_freshness=history_freshness,
            visible_source_limitations=visible_limitations,
            on_demand_data_freshness=on_demand_freshness_items,
            persist_assessment=persist,
        ),
    )

    assert calls["lookup"] == (request, created_at)
    if repository_mode == "available_needs_history":
        assert calls["needs_history"] == {
            "historical_records": (),
            "db_evidence_items": (),
        }
        assert calls["writeback"] == (result, True)
    else:
        assert "needs_history" not in calls
        assert "writeback" not in calls
    assert [item.title for item in response.evidence] == [record.title]
    assert response.explanation.missing_sources == limitations
    assert on_demand_freshness in response.data_freshness
    assert calls["history_freshness"] == {
        "historical_records": (),
        "db_evidence_items": (evidence,),
        "now": created_at,
    }
    visible_args = calls["visible_limitations"]
    assert visible_args[1:] == ((), (evidence,), result)
    assert calls["on_demand_freshness"] == (result, created_at)
    persisted = calls["persist"]
    assert persisted["explanation"].missing_sources == limitations
    assert persisted["evidence_items"] == [evidence]
    assert on_demand_freshness in persisted["data_freshness"]


def test_standard_response_persists_before_query_heat_and_cache() -> None:
    request = _risk_request()
    created_at = datetime.fromisoformat("2026-06-09T03:00:00+00:00")
    heat = QueryHeat(
        period="P7D",
        attention_level="中",
        query_count_bucket="50-199",
        unique_approx_count_bucket="10-49",
        updated_at=created_at,
    )
    trace: list[str] = []
    cached: dict[str, object] = {}

    def persist(**_kwargs: object) -> None:
        trace.append("persist")

    def query_heat(candidate: RiskAssessRequest, *, now: datetime) -> QueryHeat:
        assert trace == ["persist"]
        assert (candidate, now) == (request, created_at)
        trace.append("query_heat")
        return heat

    def cache(
        key: str,
        response: RiskAssessmentResponse,
        *,
        now: datetime,
        ttl_seconds: int,
    ) -> None:
        assert trace == ["persist", "query_heat"]
        trace.append("cache")
        cached.update(key=key, response=response, now=now, ttl_seconds=ttl_seconds)

    response = public_risk.assess_risk(
        request,
        settings=_settings(),
        created_at=created_at,
        dependencies=_standard_dependencies(
            created_at,
            persist_assessment=persist,
            query_heat=query_heat,
            cache_risk_assessment_response=cache,
        ),
    )

    assert trace == ["persist", "query_heat", "cache"]
    assert response.query_heat == heat
    assert cached == {
        "key": "standard-cache-key",
        "response": response,
        "now": created_at,
        "ttl_seconds": 120,
    }


@pytest.mark.parametrize(
    ("db_evidence_items", "expected_cache_writes"),
    [
        pytest.param(None, 0, id="repository-unavailable"),
        pytest.param((), 1, id="repository-available"),
    ],
)
def test_standard_cache_write_requires_repository_availability(
    db_evidence_items: tuple[Evidence, ...] | None,
    expected_cache_writes: int,
) -> None:
    request = _risk_request()
    created_at = datetime.fromisoformat("2026-06-09T03:00:00+00:00")
    cache_writes: list[RiskAssessmentResponse] = []
    no_news = OnDemandNewsSearchResult(
        attempted=True,
        source_id="on-demand-public-news",
        message="公開新聞補查沒有結果。",
        records=(),
    )

    response = public_risk.assess_risk(
        request,
        settings=_settings(),
        created_at=created_at,
        dependencies=_standard_dependencies(
            created_at,
            db_evidence_items=db_evidence_items,
            on_demand_public_news_result=lambda *_args, **_kwargs: no_news,
            cache_risk_assessment_response=lambda _key, candidate, **_kwargs: cache_writes.append(
                candidate
            ),
        ),
    )

    assert response.assessment_id
    assert len(cache_writes) == expected_cache_writes
    if cache_writes:
        assert cache_writes == [response]
