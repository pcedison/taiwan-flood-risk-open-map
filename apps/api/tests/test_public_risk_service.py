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
    RiskAssessRequest,
    RiskAssessmentResponse,
    RiskLevelBlock,
)
from app.api.routes import public as public_routes
from app.api.services import public_risk
from app.domain.evidence.repository import EvidenceRecord, NearbyCoverageRow
from app.domain.realtime import OfficialRealtimeBundle, OfficialRealtimeObservation
from app.domain.risk import score_risk


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
        "should_attempt_public_news_lookup": fail,
        "on_demand_public_news_result": fail,
        "historical_record_evidence": fail,
        "evidence_from_upsert": fail,
        "signal_from_historical_record": fail,
        "historical_scoring_distance": fail,
        "signal_from_evidence": fail,
        "needs_historical_event_lookup": fail,
        "persist_or_build_on_demand_evidence": fail,
        "historical_data_freshness": fail,
        "official_realtime_evidence": fail,
        "display_evidence_items": fail,
        "score_risk": fail,
        "signal_from_official_realtime": fail,
        "cache_assessment_evidence": fail,
        "persisted_official_realtime_data_freshness": fail,
        "visible_source_limitations": fail,
        "freshness_from_status": fail,
        "official_flood_disaster_data_freshness": fail,
        "on_demand_data_freshness": fail,
        "persist_assessment": fail,
        "evidence_preview": fail,
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
            score_risk=score_risk,
            cache_assessment_evidence=lambda *_args, **_kwargs: None,
            persisted_official_realtime_data_freshness=lambda *_args, **_kwargs: [],
            visible_source_limitations=lambda *_args, **_kwargs: [],
            official_flood_disaster_data_freshness=lambda _lookup: [],
            on_demand_data_freshness=lambda *_args, **_kwargs: [],
            persist_assessment=lambda **kwargs: persisted.update(kwargs),
            query_heat=lambda _request, *, now: QueryHeat(
                period="P7D",
                attention_level=public_routes.LOW_ATTENTION,
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
            official_realtime_evidence=public_routes._official_realtime_evidence,
            display_evidence_items=lambda items: items,
            score_risk=score_risk,
            signal_from_official_realtime=public_routes._signal_from_official_realtime,
            cache_assessment_evidence=lambda *_args, **_kwargs: None,
            persisted_official_realtime_data_freshness=lambda *_args, **_kwargs: [],
            visible_source_limitations=lambda *_args, **_kwargs: [],
            freshness_from_status=public_routes._freshness_from_status,
            official_flood_disaster_data_freshness=lambda _lookup: [],
            on_demand_data_freshness=lambda *_args, **_kwargs: [],
            persist_assessment=lambda **kwargs: persisted.update(kwargs),
            evidence_preview=public_routes._evidence_preview,
            query_heat=lambda _request, *, now: QueryHeat(
                period="P7D",
                attention_level=public_routes.LOW_ATTENTION,
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


def test_nearby_realtime_coverage_returns_unavailable_when_repository_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _risk_request()
    now = datetime.fromisoformat("2026-06-09T03:00:00+00:00")

    monkeypatch.setattr(
        public_routes,
        "get_settings",
        lambda: SimpleNamespace(evidence_repository_enabled=False),
    )
    monkeypatch.setattr(
        public_routes,
        "query_nearby_realtime_coverage_rows",
        lambda **_kwargs: pytest.fail("coverage rows should not be queried when repo is disabled"),
    )

    coverage = public_routes._nearby_realtime_coverage(request, now=now)

    assert coverage.overall_level == "unavailable"
    assert set(coverage.missing_signal_types) == {
        "rainfall",
        "water_level",
        "flood_depth",
        "sewer_water_level",
    }


def test_nearby_realtime_coverage_queries_rows_with_official_lookback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _risk_request()
    now = datetime.fromisoformat("2026-06-09T03:00:00+00:00")
    captured: dict[str, Any] = {}
    row = NearbyCoverageRow(
        adapter_key="official.cwa.rainfall",
        source_id="cwa-rainfall:station-1",
        event_type="rainfall",
        station_id="station-1",
        observed_at=now,
        ingested_at=now,
        distance_to_query_m=230.0,
        freshness_state="fresh",
    )

    monkeypatch.setattr(
        public_routes,
        "get_settings",
        lambda: SimpleNamespace(
            evidence_repository_enabled=True,
            database_url="postgresql://example.test/flood",
        ),
    )
    monkeypatch.setattr(
        public_routes,
        "query_nearby_realtime_coverage_rows",
        lambda **kwargs: captured.update(kwargs) or (row,),
    )

    coverage = public_routes._nearby_realtime_coverage(request, now=now)

    assert captured["database_url"] == "postgresql://example.test/flood"
    assert captured["lat"] == request.point.lat
    assert captured["lng"] == request.point.lng
    assert captured["observed_since"] == now - public_routes.REALTIME_OFFICIAL_LOOKBACK
    assert captured["statement_timeout_ms"] == public_routes.EVIDENCE_QUERY_STATEMENT_TIMEOUT_MS
    assert coverage.query_radius_m == 500
    assert coverage.overall_level == "low"


def test_nearby_realtime_coverage_returns_unavailable_when_repository_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _risk_request()
    now = datetime.fromisoformat("2026-06-09T03:00:00+00:00")

    monkeypatch.setattr(
        public_routes,
        "get_settings",
        lambda: SimpleNamespace(
            evidence_repository_enabled=True,
            database_url="postgresql://example.test/flood",
        ),
    )

    def unavailable(**_kwargs: object) -> tuple[NearbyCoverageRow, ...]:
        raise public_routes.EvidenceRepositoryUnavailable("coverage table timeout")

    monkeypatch.setattr(public_routes, "query_nearby_realtime_coverage_rows", unavailable)

    coverage = public_routes._nearby_realtime_coverage(request, now=now)

    assert coverage.overall_level == "unavailable"
    assert set(coverage.missing_signal_types) == {
        "rainfall",
        "water_level",
        "flood_depth",
        "sewer_water_level",
    }


def test_risk_assessment_response_cache_key_uses_nearby_coverage_version() -> None:
    settings = SimpleNamespace(
        app_env="test",
        realtime_official_enabled=True,
        realtime_official_diagnostic_fallback_enabled=False,
        source_cwa_api_enabled=True,
        source_wra_api_enabled=True,
        source_news_enabled=True,
        source_terms_review_ack=True,
        historical_news_on_demand_enabled=False,
        historical_news_on_demand_writeback_enabled=False,
        historical_news_on_demand_max_records=5,
        historical_news_on_demand_timeout_seconds=2.0,
        official_flood_disaster_points_enabled=True,
        evidence_repository_enabled=True,
    )

    cache_key = public_routes._risk_assessment_response_cache_key(_risk_request(), settings)

    assert '"cache_version": "realtime-evidence-v3-nearby-coverage"' in cache_key


def test_nearby_db_evidence_uses_latest_first_and_deduplicates(monkeypatch: pytest.MonkeyPatch) -> None:
    request = _risk_request()
    latest_record = _db_evidence_record(
        source_id="cwa-rainfall:station-1:2026-06-09T03:00:00+00:00",
        event_type="rainfall",
        raw_ref="official-realtime-latest:official.cwa.rainfall:rainfall:station-1",
    )
    duplicate_history = _db_evidence_record(
        source_id="cwa-rainfall:station-1:2026-06-09T02:00:00+00:00",
        event_type="rainfall",
    )
    historical_record = _db_evidence_record(
        source_id="flood-potential:profile-1",
        event_type="flood_potential",
        raw_ref="profile-top:official",
    )

    monkeypatch.setattr(
        public_routes,
        "get_settings",
        lambda: SimpleNamespace(
            evidence_repository_enabled=True,
            database_url="postgresql://example.test/flood",
            app_env="test",
        ),
    )
    monkeypatch.setattr(
        public_routes,
        "query_nearby_latest_official",
        lambda **_kwargs: (latest_record,),
    )
    monkeypatch.setattr(
        public_routes,
        "query_nearby_evidence",
        lambda **_kwargs: (duplicate_history, historical_record),
    )
    monkeypatch.setattr(public_routes, "_evidence_from_record", lambda record: record.source_id)

    records = public_routes._nearby_db_evidence(request)

    assert records == (
        "cwa-rainfall:station-1:2026-06-09T03:00:00+00:00",
        "flood-potential:profile-1",
    )


def test_nearby_db_evidence_falls_back_to_legacy_when_latest_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _risk_request()
    now = datetime.fromisoformat("2026-06-09T03:00:00+00:00")
    expected_cutoff = now - public_routes.REALTIME_OFFICIAL_LOOKBACK
    captured_latest_kwargs: dict[str, Any] = {}
    captured_legacy_kwargs: dict[str, Any] = {}
    legacy_record = _db_evidence_record(
        source_id="legacy-flood-report:1",
        event_type="flood_report",
    )

    monkeypatch.setattr(public_routes, "_now", lambda: now)
    monkeypatch.setattr(
        public_routes,
        "get_settings",
        lambda: SimpleNamespace(
            evidence_repository_enabled=True,
            database_url="postgresql://example.test/flood",
            app_env="test",
        ),
    )

    def latest_unavailable(**kwargs: object) -> tuple[EvidenceRecord, ...]:
        captured_latest_kwargs.update(kwargs)
        raise public_routes.EvidenceRepositoryUnavailable("latest table unavailable")

    def legacy_query(**kwargs: object) -> tuple[EvidenceRecord, ...]:
        captured_legacy_kwargs.update(kwargs)
        return (legacy_record,)

    monkeypatch.setattr(
        public_routes,
        "query_nearby_latest_official",
        latest_unavailable,
    )
    monkeypatch.setattr(
        public_routes,
        "query_nearby_evidence",
        legacy_query,
    )
    monkeypatch.setattr(public_routes, "_evidence_from_record", lambda record: record.source_id)

    records = public_routes._nearby_db_evidence(request)

    assert records == ("legacy-flood-report:1",)
    assert captured_latest_kwargs["observed_since"] == expected_cutoff
    assert captured_legacy_kwargs["official_realtime_since"] == expected_cutoff


def test_nearby_db_evidence_does_not_false_positive_dedupe_unknown_official_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _risk_request()
    latest_record = _db_evidence_record(
        source_id="station-1-latest",
        event_type="flood_warning",
        raw_ref="official-realtime-latest:official.wra.warning:flood_warning:station-1",
    )
    legacy_record = _db_evidence_record(
        source_id="station-1:2026-06-09T02:00:00+00:00",
        event_type="flood_warning",
    )

    monkeypatch.setattr(
        public_routes,
        "get_settings",
        lambda: SimpleNamespace(
            evidence_repository_enabled=True,
            database_url="postgresql://example.test/flood",
            app_env="test",
        ),
    )
    monkeypatch.setattr(public_routes, "query_nearby_latest_official", lambda **_kwargs: (latest_record,))
    monkeypatch.setattr(public_routes, "query_nearby_evidence", lambda **_kwargs: (legacy_record,))
    monkeypatch.setattr(public_routes, "_evidence_from_record", lambda record: record.source_id)

    records = public_routes._nearby_db_evidence(request)

    assert records == (
        "station-1-latest",
        "station-1:2026-06-09T02:00:00+00:00",
    )


def test_nearby_db_evidence_deduplicates_validated_legacy_cwa_station_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _risk_request()
    latest_record = _db_evidence_record(
        source_id="cwa-rainfall:C0A520:2026-06-09T03:00:00+00:00",
        event_type="rainfall",
        raw_ref="official-realtime-latest:official.cwa.rainfall:rainfall:C0A520",
    )
    legacy_record = _db_evidence_record(
        source_id="cwa-rainfall:C0A520:2026-06-09T02:00:00+00:00",
        event_type="rainfall",
    )

    monkeypatch.setattr(
        public_routes,
        "get_settings",
        lambda: SimpleNamespace(
            evidence_repository_enabled=True,
            database_url="postgresql://example.test/flood",
            app_env="test",
        ),
    )
    monkeypatch.setattr(public_routes, "query_nearby_latest_official", lambda **_kwargs: (latest_record,))
    monkeypatch.setattr(public_routes, "query_nearby_evidence", lambda **_kwargs: (legacy_record,))
    monkeypatch.setattr(public_routes, "_evidence_from_record", lambda record: record.source_id)

    records = public_routes._nearby_db_evidence(request)

    assert records == ("cwa-rainfall:C0A520:2026-06-09T03:00:00+00:00",)


def test_nearby_db_evidence_keeps_invalid_legacy_cwa_station_shape_distinct(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _risk_request()
    latest_record = _db_evidence_record(
        source_id="cwa-rainfall:C0A520:2026-06-09T03:00:00+00:00",
        event_type="rainfall",
        raw_ref="official-realtime-latest:official.cwa.rainfall:rainfall:C0A520",
    )
    legacy_record = _db_evidence_record(
        source_id="cwa-rainfall:not a station:2026-06-09T02:00:00+00:00",
        event_type="rainfall",
    )

    monkeypatch.setattr(
        public_routes,
        "get_settings",
        lambda: SimpleNamespace(
            evidence_repository_enabled=True,
            database_url="postgresql://example.test/flood",
            app_env="test",
        ),
    )
    monkeypatch.setattr(public_routes, "query_nearby_latest_official", lambda **_kwargs: (latest_record,))
    monkeypatch.setattr(public_routes, "query_nearby_evidence", lambda **_kwargs: (legacy_record,))
    monkeypatch.setattr(public_routes, "_evidence_from_record", lambda record: record.source_id)

    records = public_routes._nearby_db_evidence(request)

    assert records == (
        "cwa-rainfall:C0A520:2026-06-09T03:00:00+00:00",
        "cwa-rainfall:not a station:2026-06-09T02:00:00+00:00",
    )


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
