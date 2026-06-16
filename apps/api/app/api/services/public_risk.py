from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from app.api.schemas import (
    ConfidenceBlock,
    DataFreshness,
    Evidence,
    EvidencePreview,
    Explanation,
    QueryHeat,
    RiskAssessRequest,
    RiskAssessmentResponse,
    RiskLevelBlock,
)
from app.core.config import Settings
from app.domain.evidence import EvidenceUpsert
from app.domain.geocoding import stable_uuid
from app.domain.history import HistoricalFloodRecord, OfficialFloodDisasterLookup
from app.domain.history.news_enrichment import OnDemandNewsSearchResult
from app.domain.profiles import RiskProfileRecord
from app.domain.realtime import (
    OfficialRealtimeBundle,
    OfficialRealtimeObservation,
    OfficialRealtimeSourceStatus,
)
from app.domain.risk import RiskEvidenceSignal, RiskScoringResult

HistoricalRecordsWithDistance = tuple[tuple[HistoricalFloodRecord, float], ...]


class CachedRiskAssessmentResponse(Protocol):
    def __call__(
        self, cache_key: str, /, *, now: datetime, ttl_seconds: int
    ) -> RiskAssessmentResponse | None: ...


class CacheRiskAssessmentResponse(Protocol):
    def __call__(
        self,
        cache_key: str,
        response: RiskAssessmentResponse,
        /,
        *,
        now: datetime,
        ttl_seconds: int,
    ) -> None: ...


class FetchOfficialRealtimeBundle(Protocol):
    def __call__(
        self,
        *,
        lat: float,
        lng: float,
        radius_m: int,
        cwa_authorization: str | None,
        enabled: bool,
        cwa_enabled: bool,
        wra_enabled: bool,
        now: datetime,
    ) -> OfficialRealtimeBundle: ...


class OfficialFloodDisasterLookupFn(Protocol):
    def __call__(
        self, request: RiskAssessRequest, /, *, now: datetime
    ) -> OfficialFloodDisasterLookup: ...


class PrecomputedRiskProfile(Protocol):
    def __call__(
        self, request: RiskAssessRequest, /, *, now: datetime
    ) -> RiskProfileRecord | None: ...


class EnqueueProfileRefresh(Protocol):
    def __call__(
        self, profile: RiskProfileRecord, /, *, request: RiskAssessRequest
    ) -> None: ...


class ProfileBackedResponse(Protocol):
    def __call__(
        self,
        *,
        request: RiskAssessRequest,
        assessment_id: str,
        profile: RiskProfileRecord,
        realtime_bundle: OfficialRealtimeBundle,
        created_at: datetime,
    ) -> RiskAssessmentResponse: ...


class HistoricalLookupGate(Protocol):
    def __call__(
        self,
        *,
        historical_records: HistoricalRecordsWithDistance,
        db_evidence_items: tuple[Evidence, ...] | None,
    ) -> bool: ...


class OnDemandPublicNewsLookup(Protocol):
    def __call__(
        self, request: RiskAssessRequest, /, *, now: datetime
    ) -> OnDemandNewsSearchResult: ...


class HistoricalRecordEvidence(Protocol):
    def __call__(
        self, record: HistoricalFloodRecord, /, *, distance_to_query_m: float
    ) -> Evidence: ...


class SignalFromHistoricalRecord(Protocol):
    def __call__(
        self, record: HistoricalFloodRecord, /, *, distance_to_query_m: float
    ) -> RiskEvidenceSignal: ...


class HistoricalScoringDistance(Protocol):
    def __call__(
        self,
        *,
        record: HistoricalFloodRecord,
        distance_to_query_m: float,
        radius_m: int,
        location_text: str | None,
    ) -> float: ...


class PersistOrBuildOnDemandEvidence(Protocol):
    def __call__(
        self, result: OnDemandNewsSearchResult, /, *, writeback_enabled: bool
    ) -> tuple[Evidence, ...]: ...


class HistoricalDataFreshness(Protocol):
    def __call__(
        self,
        *,
        historical_records: HistoricalRecordsWithDistance,
        db_evidence_items: tuple[Evidence, ...] | None,
        now: datetime,
    ) -> DataFreshness: ...


class ScoreRisk(Protocol):
    def __call__(
        self, signals: tuple[RiskEvidenceSignal, ...], /, *, now: datetime
    ) -> RiskScoringResult: ...


class PersistedOfficialRealtimeDataFreshness(Protocol):
    def __call__(
        self, evidence_items: tuple[Evidence, ...], /, *, now: datetime
    ) -> list[DataFreshness]: ...


class OnDemandDataFreshness(Protocol):
    def __call__(
        self, result: OnDemandNewsSearchResult, /, *, now: datetime
    ) -> list[DataFreshness]: ...


class PersistAssessment(Protocol):
    def __call__(
        self,
        *,
        assessment_id: str,
        request: RiskAssessRequest,
        scoring: RiskScoringResult,
        explanation: Explanation,
        data_freshness: list[DataFreshness],
        evidence_items: list[Evidence],
        created_at: datetime,
        expires_at: datetime,
    ) -> None: ...


class QueryHeatLookup(Protocol):
    def __call__(self, request: RiskAssessRequest, /, *, now: datetime) -> QueryHeat: ...


@dataclass(frozen=True)
class RiskAssessmentDependencies:
    risk_assessment_response_cache_key: Callable[[RiskAssessRequest, Settings], str]
    cached_risk_assessment_response: CachedRiskAssessmentResponse
    fetch_official_realtime_bundle: FetchOfficialRealtimeBundle
    nearby_db_evidence: Callable[[RiskAssessRequest], tuple[Evidence, ...] | None]
    official_flood_disaster_lookup: OfficialFloodDisasterLookupFn
    can_use_profile_fast_path: Callable[[tuple[Evidence, ...] | None], bool]
    precomputed_risk_profile: PrecomputedRiskProfile
    profile_has_public_news: Callable[[RiskProfileRecord], bool]
    enqueue_profile_refresh: EnqueueProfileRefresh
    profile_backed_response: ProfileBackedResponse
    cache_risk_assessment_response: CacheRiskAssessmentResponse
    fallback_historical_records: Callable[[RiskAssessRequest], HistoricalRecordsWithDistance]
    use_local_historical_fallback: Callable[[str], bool]
    should_attempt_public_news_lookup: HistoricalLookupGate
    on_demand_public_news_result: OnDemandPublicNewsLookup
    historical_record_evidence: HistoricalRecordEvidence
    evidence_from_upsert: Callable[[EvidenceUpsert], Evidence]
    signal_from_historical_record: SignalFromHistoricalRecord
    historical_scoring_distance: HistoricalScoringDistance
    signal_from_evidence: Callable[[Evidence], RiskEvidenceSignal]
    needs_historical_event_lookup: HistoricalLookupGate
    persist_or_build_on_demand_evidence: PersistOrBuildOnDemandEvidence
    historical_data_freshness: HistoricalDataFreshness
    official_realtime_evidence: Callable[[OfficialRealtimeObservation], Evidence]
    display_evidence_items: Callable[[list[Evidence]], list[Evidence]]
    score_risk: ScoreRisk
    signal_from_official_realtime: Callable[[OfficialRealtimeObservation], RiskEvidenceSignal]
    cache_assessment_evidence: Callable[[str, list[Evidence]], None]
    persisted_official_realtime_data_freshness: PersistedOfficialRealtimeDataFreshness
    visible_source_limitations: Callable[
        [
            OfficialRealtimeBundle,
            HistoricalRecordsWithDistance,
            tuple[Evidence, ...] | None,
            OnDemandNewsSearchResult,
        ],
        list[str],
    ]
    freshness_from_status: Callable[[OfficialRealtimeSourceStatus], DataFreshness]
    official_flood_disaster_data_freshness: Callable[
        [OfficialFloodDisasterLookup], list[DataFreshness]
    ]
    on_demand_data_freshness: OnDemandDataFreshness
    persist_assessment: PersistAssessment
    evidence_preview: Callable[[Evidence], EvidencePreview]
    query_heat: QueryHeatLookup


def assess_risk(
    risk_request: RiskAssessRequest,
    *,
    settings: Settings,
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
    can_cache_response = db_evidence_items is not None or not settings.evidence_repository_enabled
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
    if can_cache_response:
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


def assessment_result_snapshot(
    *,
    assessment_id: str,
    request: RiskAssessRequest,
    scoring: RiskScoringResult,
    explanation: Explanation,
    data_freshness: list[DataFreshness],
    evidence_items: list[Evidence],
    created_at: datetime,
    expires_at: datetime,
) -> dict[str, Any]:
    return {
        "assessment_id": assessment_id,
        "location": request.point.model_dump(mode="json"),
        "radius_m": request.radius_m,
        "location_text": request.location_text,
        "score_version": scoring.score_version,
        "scores": {
            "realtime": scoring.realtime_score,
            "historical": scoring.historical_score,
            "confidence": scoring.confidence_score,
        },
        "levels": {
            "realtime": scoring.realtime_level,
            "historical": scoring.historical_level,
            "confidence": scoring.confidence_level,
        },
        "explanation": explanation.model_dump(mode="json"),
        "evidence_ids": [item.id for item in evidence_items],
        "evidence_count": len(evidence_items),
        "data_freshness": [item.model_dump(mode="json") for item in data_freshness],
        "created_at": created_at.isoformat(),
        "expires_at": expires_at.isoformat(),
    }
