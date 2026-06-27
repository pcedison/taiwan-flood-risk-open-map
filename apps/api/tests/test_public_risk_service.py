from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from app.api.schemas import (
    ConfidenceBlock,
    DataFreshness,
    Explanation,
    LatLng,
    QueryHeat,
    RiskAssessRequest,
    RiskAssessmentResponse,
    RiskLevelBlock,
)
from app.api.routes import public as public_routes
from app.api.services import public_risk
from app.domain.evidence.repository import EvidenceRecord
from app.domain.realtime import OfficialRealtimeBundle


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


def test_assess_risk_profile_fast_path_refreshes_and_caches_response() -> None:
    request = _risk_request()
    created_at = datetime.fromisoformat("2026-06-09T03:00:00+00:00")
    profile = object()
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
    assert calls["cache_args"] == ("profile-cache-key", expected_response)
    assert calls["cache_kwargs"] == {
        "now": created_at,
        "ttl_seconds": 120,
    }
