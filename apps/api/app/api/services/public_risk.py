from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from app.api.schemas import (
    ConfidenceBlock,
    DataFreshness,
    Evidence,
    Explanation,
    QueryHeat,
    NearbyRealtimeCoverage,
    RiskAssessRequest,
    RiskAssessmentResponse,
    RiskLevelBlock,
)
from app.api.services import public_evidence, public_freshness
from app.core.config import Settings
from app.domain.evidence.repository import NearbyCoverageRow
from app.domain.geocoding import stable_uuid
from app.domain.history import HistoricalFloodRecord, OfficialFloodDisasterLookup
from app.domain.history.news_enrichment import OnDemandNewsSearchResult
from app.domain.profiles import RiskProfileRecord
from app.domain.realtime.nearby_coverage import (
    RADIUS_BUCKETS_M,
    REQUIRED_SIGNAL_TYPES,
    build_nearby_realtime_coverage,
)
from app.domain.realtime import (
    OfficialRealtimeBundle,
    OfficialRealtimeObservation,
)
from app.domain.risk import RiskScoringResult, score_risk

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
        nearby_realtime_coverage: NearbyRealtimeCoverage,
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
        nearby_realtime_coverage: NearbyRealtimeCoverage,
        created_at: datetime,
        expires_at: datetime,
    ) -> None: ...


class QueryHeatLookup(Protocol):
    def __call__(self, request: RiskAssessRequest, /, *, now: datetime) -> QueryHeat: ...


class NearbyRealtimeCoverageLookup(Protocol):
    def __call__(
        self, request: RiskAssessRequest, /, *, now: datetime
    ) -> NearbyRealtimeCoverage: ...


_NEARBY_REALTIME_COVERAGE_NOTE = ('縣市層級涵蓋只作背景參考，不代表查詢點附近的感測器覆蓋；附近涵蓋會依查詢點重新計算。')


def build_placeholder_nearby_realtime_coverage(
    *, evaluated_at: datetime, query_radius_m: int
) -> NearbyRealtimeCoverage:
    return NearbyRealtimeCoverage(
        overall_level="unavailable",
        evaluated_at=evaluated_at,
        query_radius_m=query_radius_m,
        radius_buckets_m=list(RADIUS_BUCKETS_M),
        summary='目前僅提供縣市層級背景涵蓋資訊；查詢點附近涵蓋會依查詢點重新計算。',
        signal_breakdown=[],
        missing_signal_types=[
            "rainfall",
            "water_level",
            "flood_depth",
            "sewer_water_level",
        ],
        limitations=[_NEARBY_REALTIME_COVERAGE_NOTE],
        county_level_note=_NEARBY_REALTIME_COVERAGE_NOTE,
    )


@dataclass(frozen=True)
class RiskAssessmentDependencies:

    risk_assessment_response_cache_key: Callable[[RiskAssessRequest, Settings], str]
    cached_risk_assessment_response: CachedRiskAssessmentResponse
    fetch_official_realtime_bundle: FetchOfficialRealtimeBundle
    nearby_realtime_coverage: NearbyRealtimeCoverageLookup
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
    on_demand_public_news_result: OnDemandPublicNewsLookup
    needs_historical_event_lookup: HistoricalLookupGate
    persist_or_build_on_demand_evidence: PersistOrBuildOnDemandEvidence
    historical_data_freshness: HistoricalDataFreshness
    display_evidence_items: Callable[[list[Evidence]], list[Evidence]]
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
    official_flood_disaster_data_freshness: Callable[
        [OfficialFloodDisasterLookup], list[DataFreshness]
    ]
    on_demand_data_freshness: OnDemandDataFreshness
    persist_assessment: PersistAssessment
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
    nearby_coverage = _nearby_realtime_coverage_with_bridge_fallback(
        dependencies.nearby_realtime_coverage(risk_request, now=created_at),
        realtime_bundle,
        request=risk_request,
        created_at=created_at,
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
                nearby_realtime_coverage=nearby_coverage,
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
        if public_freshness.should_attempt_public_news_lookup(
            historical_records=historical_records,
            db_evidence_items=None,
        ):
            on_demand_news = dependencies.on_demand_public_news_result(
                risk_request,
                now=created_at,
            )
        historical_evidence_items = [
            public_evidence.historical_record_evidence(record, distance_to_query_m=distance_m)
            for record, distance_m in historical_records
        ]
        historical_evidence_items.extend(
            public_evidence.evidence_from_upsert(record) for record in on_demand_news.records
        )
        historical_signals = (
            *tuple(
                public_evidence.signal_from_historical_record(
                    record,
                    distance_to_query_m=distance_m,
                )
                for record, distance_m in historical_records
            ),
            *tuple(
                public_evidence.signal_from_evidence(item)
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
            if public_freshness.should_attempt_public_news_lookup(
                historical_records=historical_records,
                db_evidence_items=db_evidence_items,
            ):
                on_demand_news = dependencies.on_demand_public_news_result(
                    risk_request,
                    now=created_at,
                )
            historical_record_evidence_items = [
                public_evidence.historical_record_evidence(record, distance_to_query_m=distance_m)
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
                *tuple(public_evidence.signal_from_evidence(item) for item in db_evidence_items),
                *tuple(
                    public_evidence.signal_from_historical_record(
                        record,
                        distance_to_query_m=distance_m,
                    )
                    for record, distance_m in historical_records
                ),
                *tuple(
                    public_evidence.signal_from_evidence(item)
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
                public_evidence.signal_from_evidence(item) for item in historical_evidence_items
            )
            historical_freshness_db_items = tuple(historical_evidence_items)
    historical_freshness = dependencies.historical_data_freshness(
        historical_records=historical_records,
        db_evidence_items=historical_freshness_db_items,
        now=created_at,
    )
    evidence_items = [
        *(
            public_evidence.official_realtime_evidence(observation)
            for observation in realtime_bundle.observations
        ),
        *historical_evidence_items,
    ]
    display_evidence_items = dependencies.display_evidence_items(evidence_items)
    scoring = score_risk(
        (
            *(
                public_evidence.signal_from_official_realtime(observation)
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
            public_freshness.freshness_from_status(status)
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
        nearby_realtime_coverage=nearby_coverage,
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
        evidence=[public_evidence.evidence_preview(item) for item in display_evidence_items],
        data_freshness=data_freshness,
        query_heat=dependencies.query_heat(risk_request, now=created_at),
        nearby_realtime_coverage=nearby_coverage,
    )
    if can_cache_response:
        dependencies.cache_risk_assessment_response(
            response_cache_key,
            response,
            now=created_at,
            ttl_seconds=settings.risk_assessment_response_cache_seconds,
        )
    return response


def _nearby_realtime_coverage_with_bridge_fallback(
    coverage: NearbyRealtimeCoverage,
    realtime_bundle: OfficialRealtimeBundle,
    *,
    request: RiskAssessRequest,
    created_at: datetime,
) -> NearbyRealtimeCoverage:
    # The realtime bundle and persisted coverage repository are separate paths.
    # A healthy bridge observation must repair an empty repository result too;
    # otherwise the same response can show a live station in evidence while the
    # coverage panel incorrectly says that no sensor exists.
    if not realtime_bundle.observations:
        return coverage
    if coverage.overall_level == "no_local_sensor" and _coverage_has_observations(coverage):
        # The repository also includes local-government and status adapters that
        # are absent from the central bridge.  Preserve those rows instead of
        # replacing a sparse/stale/regional result with a narrower source set.
        return coverage
    if coverage.overall_level not in {"unavailable", "no_local_sensor"}:
        return coverage
    return build_nearby_realtime_coverage(
        rows=tuple(
            _nearby_coverage_row_from_observation(observation, now=created_at)
            for observation in realtime_bundle.observations
        ),
        query_radius_m=request.radius_m,
        evaluated_at=created_at,
        source_health=tuple(coverage.source_health),
        source_health_unavailable=(
            not coverage.source_health_checked and not coverage.source_health
        ),
        source_health_checked=coverage.source_health_checked,
        jurisdiction_status=coverage.jurisdiction_status,
        jurisdiction_checked=coverage.jurisdiction_checked,
        jurisdiction_complete_signal_types=tuple(
            signal_type
            for signal_type in REQUIRED_SIGNAL_TYPES
            if signal_type not in coverage.jurisdiction_unverified_signal_types
        ),
        home_jurisdiction=coverage.home_jurisdiction,
        considered_jurisdictions=tuple(coverage.considered_jurisdictions),
        jurisdiction_mapping_revisions=tuple(
            coverage.jurisdiction_mapping_revisions
        ),
    )


def _coverage_has_observations(coverage: NearbyRealtimeCoverage) -> bool:
    return any(
        signal.nearest_distance_m is not None
        or signal.fresh_count + signal.degraded_count + signal.stale_count
        + signal.status_only_count
        > 0
        or any(signal.counts_by_radius_m.values())
        for signal in coverage.signal_breakdown
    )


def _nearby_coverage_row_from_observation(
    observation: OfficialRealtimeObservation,
    *,
    now: datetime,
) -> NearbyCoverageRow:
    return NearbyCoverageRow(
        adapter_key=_official_realtime_adapter_key(observation),
        source_id=observation.source_id,
        event_type=observation.event_type,
        station_id=observation.source_id,
        observed_at=observation.observed_at,
        ingested_at=observation.ingested_at,
        distance_to_query_m=observation.distance_to_query_m,
        freshness_state=_official_realtime_freshness_state(observation, now=now),
    )


def _official_realtime_adapter_key(observation: OfficialRealtimeObservation) -> str:
    if observation.event_type == "rainfall":
        return "official.cwa.rainfall"
    if observation.event_type == "water_level":
        return "official.wra.water_level"
    return f"official.realtime.{observation.event_type}"


def _official_realtime_freshness_state(
    observation: OfficialRealtimeObservation,
    *,
    now: datetime,
) -> str:
    if observation.observed_at >= now - timedelta(minutes=10):
        return "fresh"
    if observation.observed_at >= now - timedelta(minutes=30):
        return "degraded"
    return "stale"


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
    nearby_realtime_coverage: NearbyRealtimeCoverage,
    created_at: datetime,
    expires_at: datetime,
) -> dict[str, Any]:
    return {
        "assessment_id": assessment_id,
        # ADR-0006: the stored snapshot must not contain raw query text or
        # precise coordinates; keep the keys for shape compatibility but
        # coarsen to the ~1 km privacy bucket.
        "location": {
            "lat": round(request.point.lat, 2),
            "lng": round(request.point.lng, 2),
        },
        "radius_m": request.radius_m,
        "location_text": None,
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
        "nearby_realtime_coverage": nearby_realtime_coverage.model_dump(mode="json"),
        "created_at": created_at.isoformat(),
        "expires_at": expires_at.isoformat(),
    }
