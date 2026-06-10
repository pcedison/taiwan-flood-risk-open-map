from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.api.schemas import (
    ConfidenceBlock,
    DataFreshness,
    Explanation,
    RiskAssessRequest,
    RiskAssessmentResponse,
    RiskLevelBlock,
)
from app.domain.geocoding import stable_uuid
from app.domain.history.news_enrichment import OnDemandNewsSearchResult


@dataclass(frozen=True)
class RiskAssessmentDependencies:
    risk_assessment_response_cache_key: Callable[..., str]
    cached_risk_assessment_response: Callable[..., RiskAssessmentResponse | None]
    fetch_official_realtime_bundle: Callable[..., Any]
    nearby_db_evidence: Callable[..., Any]
    official_flood_disaster_lookup: Callable[..., Any]
    can_use_profile_fast_path: Callable[..., bool]
    precomputed_risk_profile: Callable[..., Any]
    profile_has_public_news: Callable[..., bool]
    enqueue_profile_refresh: Callable[..., None]
    profile_backed_response: Callable[..., RiskAssessmentResponse]
    cache_risk_assessment_response: Callable[..., None]
    fallback_historical_records: Callable[..., Any]
    use_local_historical_fallback: Callable[..., bool]
    should_attempt_public_news_lookup: Callable[..., bool]
    on_demand_public_news_result: Callable[..., OnDemandNewsSearchResult]
    historical_record_evidence: Callable[..., Any]
    evidence_from_upsert: Callable[..., Any]
    signal_from_historical_record: Callable[..., Any]
    historical_scoring_distance: Callable[..., float]
    signal_from_evidence: Callable[..., Any]
    needs_historical_event_lookup: Callable[..., bool]
    persist_or_build_on_demand_evidence: Callable[..., Any]
    historical_data_freshness: Callable[..., Any]
    official_realtime_evidence: Callable[..., Any]
    display_evidence_items: Callable[..., Any]
    score_risk: Callable[..., Any]
    signal_from_official_realtime: Callable[..., Any]
    cache_assessment_evidence: Callable[..., None]
    persisted_official_realtime_data_freshness: Callable[..., list[DataFreshness]]
    visible_source_limitations: Callable[..., list[str]]
    freshness_from_status: Callable[..., DataFreshness]
    official_flood_disaster_data_freshness: Callable[..., list[DataFreshness]]
    on_demand_data_freshness: Callable[..., list[DataFreshness]]
    persist_assessment: Callable[..., None]
    evidence_preview: Callable[..., Any]
    query_heat: Callable[..., Any]


def assess_risk(
    risk_request: RiskAssessRequest,
    *,
    settings: Any,
    created_at: datetime,
    dependencies: RiskAssessmentDependencies,
) -> RiskAssessmentResponse:
    response_cache_key = dependencies.risk_assessment_response_cache_key(risk_request, settings)
    cached_response = dependencies.cached_risk_assessment_response(
        response_cache_key,
        now=created_at,
        ttl_seconds=settings.risk_assessment_response_cache_seconds,
    )
    if cached_response is not None:
        return cached_response
    assessment_id = stable_uuid(
        "assessment",
        risk_request.point.lat,
        risk_request.point.lng,
        risk_request.radius_m,
        created_at.isoformat(),
    )
    realtime_bundle = dependencies.fetch_official_realtime_bundle(
        lat=risk_request.point.lat,
        lng=risk_request.point.lng,
        radius_m=risk_request.radius_m,
        cwa_authorization=settings.cwa_api_authorization,
        enabled=settings.realtime_official_enabled,
        cwa_enabled=settings.source_cwa_api_enabled,
        wra_enabled=settings.source_wra_api_enabled,
        now=created_at,
    )
    db_evidence_items = dependencies.nearby_db_evidence(risk_request)
    official_history_lookup = dependencies.official_flood_disaster_lookup(
        risk_request,
        now=created_at,
    )
    official_historical_records = official_history_lookup.records
    if (
        dependencies.can_use_profile_fast_path(db_evidence_items)
        and not official_historical_records
    ):
        profile = dependencies.precomputed_risk_profile(risk_request, now=created_at)
        if profile is not None and dependencies.profile_has_public_news(profile):
            dependencies.enqueue_profile_refresh(profile, request=risk_request)
            response = dependencies.profile_backed_response(
                request=risk_request,
                assessment_id=assessment_id,
                profile=profile,
                realtime_bundle=realtime_bundle,
                created_at=created_at,
            )
            dependencies.cache_risk_assessment_response(
                response_cache_key,
                response,
                now=created_at,
                ttl_seconds=settings.risk_assessment_response_cache_seconds,
            )
            return response
    on_demand_news = OnDemandNewsSearchResult(
        attempted=False,
        source_id="on-demand-public-news",
        message="未啟動公開新聞補查。",
        records=(),
    )
    if db_evidence_items is None:
        curated_historical_records = (
            dependencies.fallback_historical_records(risk_request)
            if dependencies.use_local_historical_fallback(settings.app_env)
            else ()
        )
        historical_records = (*official_historical_records, *curated_historical_records)
        if dependencies.should_attempt_public_news_lookup(
            historical_records=historical_records,
            db_evidence_items=None,
        ):
            on_demand_news = dependencies.on_demand_public_news_result(
                risk_request,
                now=created_at,
            )
        historical_evidence_items = [
            dependencies.historical_record_evidence(record, distance_to_query_m=distance_m)
            for record, distance_m in historical_records
        ]
        historical_evidence_items.extend(
            dependencies.evidence_from_upsert(record) for record in on_demand_news.records
        )
        historical_signals = (
            *tuple(
                dependencies.signal_from_historical_record(
                    record,
                    distance_to_query_m=dependencies.historical_scoring_distance(
                        record=record,
                        distance_to_query_m=distance_m,
                        radius_m=risk_request.radius_m,
                        location_text=risk_request.location_text,
                    ),
                )
                for record, distance_m in historical_records
            ),
            *tuple(
                dependencies.signal_from_evidence(item)
                for item in historical_evidence_items[len(historical_records) :]
            ),
        )
        historical_freshness_db_items = (
            tuple(historical_evidence_items) if on_demand_news.records else None
        )
    else:
        needs_historical_event_lookup = dependencies.needs_historical_event_lookup(
            historical_records=(),
            db_evidence_items=db_evidence_items,
        )
        historical_records = (
            (
                *official_historical_records,
                *(
                    dependencies.fallback_historical_records(risk_request)
                    if dependencies.use_local_historical_fallback(settings.app_env)
                    else ()
                ),
            )
            if needs_historical_event_lookup or official_historical_records
            else ()
        )
        if historical_records:
            if dependencies.should_attempt_public_news_lookup(
                historical_records=historical_records,
                db_evidence_items=db_evidence_items,
            ):
                on_demand_news = dependencies.on_demand_public_news_result(
                    risk_request,
                    now=created_at,
                )
            historical_record_evidence_items = [
                dependencies.historical_record_evidence(record, distance_to_query_m=distance_m)
                for record, distance_m in historical_records
            ]
            on_demand_evidence_items = dependencies.persist_or_build_on_demand_evidence(
                on_demand_news,
                writeback_enabled=settings.historical_news_on_demand_writeback_enabled,
            )
            historical_evidence_items = [
                *db_evidence_items,
                *historical_record_evidence_items,
                *on_demand_evidence_items,
            ]
            historical_signals = (
                *tuple(dependencies.signal_from_evidence(item) for item in db_evidence_items),
                *tuple(
                    dependencies.signal_from_historical_record(
                        record,
                        distance_to_query_m=dependencies.historical_scoring_distance(
                            record=record,
                            distance_to_query_m=distance_m,
                            radius_m=risk_request.radius_m,
                            location_text=risk_request.location_text,
                        ),
                    )
                    for record, distance_m in historical_records
                ),
                *tuple(
                    dependencies.signal_from_evidence(item)
                    for item in on_demand_evidence_items
                ),
            )
            historical_freshness_db_items = (
                tuple(historical_evidence_items) if db_evidence_items else None
            )
        else:
            if needs_historical_event_lookup:
                on_demand_news = dependencies.on_demand_public_news_result(
                    risk_request,
                    now=created_at,
                )
            on_demand_evidence_items = dependencies.persist_or_build_on_demand_evidence(
                on_demand_news,
                writeback_enabled=settings.historical_news_on_demand_writeback_enabled,
            )
            historical_evidence_items = [*db_evidence_items, *on_demand_evidence_items]
            historical_signals = tuple(
                dependencies.signal_from_evidence(item) for item in historical_evidence_items
            )
            historical_freshness_db_items = tuple(historical_evidence_items)
    historical_freshness = dependencies.historical_data_freshness(
        historical_records=historical_records,
        db_evidence_items=historical_freshness_db_items,
        now=created_at,
    )
    evidence_items = [
        *(
            dependencies.official_realtime_evidence(observation)
            for observation in realtime_bundle.observations
        ),
        *historical_evidence_items,
    ]
    display_evidence_items = dependencies.display_evidence_items(evidence_items)
    scoring = dependencies.score_risk(
        (
            *(
                dependencies.signal_from_official_realtime(observation)
                for observation in realtime_bundle.observations
            ),
            *historical_signals,
        ),
        now=created_at,
    )
    dependencies.cache_assessment_evidence(assessment_id, display_evidence_items)
    expires_at = created_at + timedelta(minutes=10)
    explanation = Explanation(
        summary=scoring.explanation_summary,
        main_reasons=list(scoring.main_reasons),
        missing_sources=dependencies.visible_source_limitations(
            realtime_bundle,
            historical_records,
            historical_freshness_db_items,
            on_demand_news,
        ),
    )
    persisted_realtime_freshness = dependencies.persisted_official_realtime_data_freshness(
        tuple(historical_evidence_items),
        now=created_at,
    )
    realtime_data_freshness = _merge_realtime_data_freshness(
        [
            dependencies.freshness_from_status(status)
            for status in realtime_bundle.source_statuses
        ],
        persisted_realtime_freshness,
    )
    data_freshness = [
        *realtime_data_freshness,
        *dependencies.official_flood_disaster_data_freshness(official_history_lookup),
        DataFreshness(
            source_id=historical_freshness.source_id,
            name="歷史淹水紀錄與公開新聞",
            health_status=historical_freshness.health_status,
            observed_at=historical_freshness.observed_at,
            ingested_at=historical_freshness.ingested_at,
            feature_count=historical_freshness.feature_count,
            message=historical_freshness.message,
        ),
        *dependencies.on_demand_data_freshness(on_demand_news, now=created_at),
    ]
    dependencies.persist_assessment(
        assessment_id=assessment_id,
        request=risk_request,
        scoring=scoring,
        explanation=explanation,
        data_freshness=data_freshness,
        evidence_items=display_evidence_items,
        created_at=created_at,
        expires_at=expires_at,
    )
    response = RiskAssessmentResponse(
        assessment_id=assessment_id,
        location=risk_request.point,
        radius_m=risk_request.radius_m,
        score_version=scoring.score_version,
        created_at=created_at,
        expires_at=created_at + timedelta(minutes=10),
        realtime=RiskLevelBlock(level=scoring.realtime_level),
        historical=RiskLevelBlock(level=scoring.historical_level),
        confidence=ConfidenceBlock(level=scoring.confidence_level),
        explanation=explanation,
        evidence=[dependencies.evidence_preview(item) for item in display_evidence_items],
        data_freshness=data_freshness,
        query_heat=dependencies.query_heat(risk_request, now=created_at),
    )
    dependencies.cache_risk_assessment_response(
        response_cache_key,
        response,
        now=created_at,
        ttl_seconds=settings.risk_assessment_response_cache_seconds,
    )
    return response


def _merge_realtime_data_freshness(
    fallback_items: list[DataFreshness],
    persisted_items: list[DataFreshness],
) -> list[DataFreshness]:
    if not persisted_items:
        return fallback_items
    persisted_by_source = {item.source_id: item for item in persisted_items}
    merged = [
        persisted_by_source.pop(item.source_id, item)
        for item in fallback_items
    ]
    merged.extend(persisted_by_source.values())
    return merged
