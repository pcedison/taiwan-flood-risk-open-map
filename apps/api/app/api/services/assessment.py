from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from app.api.schemas import (
    CommunityRiskBlock,
    ConfidenceBlock,
    DataFreshness,
    DataStatus,
    Evidence,
    Explanation,
    HealthStatus,
    PublicSourceStatus,
    QueryHeat,
    RiskAssessmentResponse,
    RiskAssessRequest,
    RiskLevelBlock,
)
from app.api.services.public_evidence import (
    display_evidence_items,
    evidence_from_record,
    evidence_preview,
    signal_from_evidence,
)
from app.domain.assessment import (
    AssessmentData,
    AssessmentRepository,
    apply_realtime_safety,
    compose_base_overall,
)
from app.domain.evidence import EvidenceRepositoryUnavailable, RiskAssessmentPersistence
from app.domain.risk import RiskEvidenceSignal, RiskScoringResult


class RiskScorer(Protocol):
    def __call__(
        self,
        signals: tuple[RiskEvidenceSignal, ...],
        *,
        now: datetime,
    ) -> RiskScoringResult: ...


class AssessmentService:
    def __init__(self, repository: AssessmentRepository, scorer: RiskScorer) -> None:
        self._repository = repository
        self._scorer = scorer

    def assess(
        self,
        request: RiskAssessRequest,
        *,
        now: datetime,
    ) -> RiskAssessmentResponse:
        data = self._repository.load(
            lat=request.point.lat,
            lng=request.point.lng,
            radius_m=request.radius_m,
            as_of=now,
        )
        current_items = tuple(evidence_from_record(item) for item in data.current_official)
        historical_items = tuple(evidence_from_record(item) for item in data.historical)
        current_scoring = self._scorer(
            tuple(signal_from_evidence(item) for item in current_items),
            now=now,
        )
        historical_scoring = self._scorer(
            tuple(signal_from_evidence(item) for item in historical_items),
            now=now,
        )
        current_scoring = apply_realtime_safety(current_scoring, data)
        overall = compose_base_overall(current_scoring, historical_scoring)

        display_items = display_evidence_items(
            list(_deduplicate_evidence((*current_items, *historical_items)))
        )
        persisted_evidence_ids = tuple(
            item.id for item in display_items if _is_uuid(item.id)
        )
        data_freshness = _data_freshness(data)
        data_status = _data_status(data)
        explanation = Explanation(
            summary=(
                overall.reasons[0]
                if overall.reasons
                else current_scoring.explanation_summary
            ),
            main_reasons=list(overall.reasons),
            missing_sources=list(
                dict.fromkeys(
                    (
                        *current_scoring.missing_sources,
                        *historical_scoring.missing_sources,
                        *data_status.missing,
                    )
                )
            ),
        )
        assessment_id = str(uuid4())
        expires_at = now + timedelta(minutes=10)
        response = RiskAssessmentResponse(
            assessment_id=assessment_id,
            location=request.point,
            radius_m=request.radius_m,
            score_version=current_scoring.score_version,
            created_at=now,
            expires_at=expires_at,
            realtime=RiskLevelBlock(
                level=current_scoring.realtime_level,
                confidence=current_scoring.confidence_level,
                reasons=list(current_scoring.main_reasons),
            ),
            historical=RiskLevelBlock(
                level=historical_scoring.historical_level,
                confidence=historical_scoring.confidence_level,
                reasons=list(historical_scoring.main_reasons),
            ),
            confidence=ConfidenceBlock(level=overall.confidence),
            explanation=explanation,
            evidence=[evidence_preview(item) for item in display_items[:10]],
            data_freshness=data_freshness,
            query_heat=QueryHeat(
                period="frozen",
                attention_level="未知",
                query_count_bucket="frozen",
                unique_approx_count_bucket="frozen",
                updated_at=now,
            ),
            nearby_realtime_coverage=data.nearby_coverage,
            as_of=now,
            community=CommunityRiskBlock(),
            overall=RiskLevelBlock(
                level=overall.level,
                confidence=overall.confidence,
                reasons=list(overall.reasons),
            ),
            dominant_mode=overall.dominant_mode,
            data_status=data_status,
        )
        assert response.overall is not None
        persistence = RiskAssessmentPersistence(
            assessment_id=assessment_id,
            lat=request.point.lat,
            lng=request.point.lng,
            radius_m=request.radius_m,
            score_version=response.score_version,
            realtime_score=current_scoring.realtime_score,
            historical_score=historical_scoring.historical_score,
            confidence_score=max(
                current_scoring.confidence_score,
                historical_scoring.confidence_score,
            ),
            realtime_level=response.realtime.level,
            historical_level=response.historical.level,
            overall_level=response.overall.level,
            dominant_mode=response.dominant_mode,
            explanation=explanation.model_dump(mode="json"),
            data_freshness=[item.model_dump(mode="json") for item in data_freshness],
            result_snapshot=_privacy_safe_result_snapshot(
                request=request,
                response=response,
                current_scoring=current_scoring,
                historical_scoring=historical_scoring,
                evidence_ids=persisted_evidence_ids,
            ),
            evidence_ids=persisted_evidence_ids,
            created_at=now,
            expires_at=expires_at,
        )
        try:
            self._repository.persist(persistence)
        except EvidenceRepositoryUnavailable:
            pass
        return response


def _deduplicate_evidence(items: tuple[Evidence, ...]) -> tuple[Evidence, ...]:
    unique: list[Evidence] = []
    seen: set[str] = set()
    for item in items:
        if item.id in seen:
            continue
        seen.add(item.id)
        unique.append(item)
    return tuple(unique)


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except (ValueError, AttributeError):
        return False
    return True


def _data_freshness(data: AssessmentData) -> list[DataFreshness]:
    if data.source_states:
        return [
            DataFreshness(
                source_id=state.source_key,
                name=state.signal_type,
                health_status=_source_health(state.state),
                observed_at=state.observed_at,
                ingested_at=state.checked_at,
                message=state.message,
            )
            for state in data.source_states
        ]
    return [
        DataFreshness(
            source_id="persisted-current-official",
            name="已保存官方即時資料",
            health_status="unknown" if not data.current_available else "healthy",
            feature_count=len(data.current_official),
            message=(None if data.current_available else "官方即時資料庫讀取暫時無法使用。"),
        ),
        DataFreshness(
            source_id="persisted-historical",
            name="已保存歷史資料",
            health_status="unknown" if not data.historical_available else "healthy",
            feature_count=len(data.historical),
            message=(None if data.historical_available else "歷史資料庫讀取暫時無法使用。"),
        ),
    ]


def _source_health(state: str) -> HealthStatus:
    health_by_state: dict[str, HealthStatus] = {
        "fresh": "healthy",
        "degraded": "degraded",
        "stale": "degraded",
        "failed": "failed",
        "disabled": "disabled",
        "not_applicable": "unknown",
    }
    return health_by_state.get(state, "unknown")


def _data_status(data: AssessmentData) -> DataStatus:
    sources = [
        PublicSourceStatus(
            source_key=state.source_key,
            signal_type=state.signal_type,
            state=state.state,
            observed_at=state.observed_at,
            checked_at=state.checked_at,
            message=state.message,
        )
        for state in data.source_states
    ]
    missing = [
        state.message
        for state in data.source_states
        if state.state not in {"fresh", "not_applicable"} and state.message
    ]
    missing.extend(data.local_machine_feed_missing)
    availability_messages = (
        (data.current_available, "官方即時資料庫讀取暫時無法使用。"),
        (data.historical_available, "歷史資料庫讀取暫時無法使用。"),
        (data.coverage_available, "附近即時涵蓋資料暫時無法使用。"),
        (data.health_available, "官方來源健康狀態暫時無法使用。"),
        (data.jurisdiction_available, "查詢點行政區解析暫時無法使用。"),
    )
    missing.extend(message for available, message in availability_messages if not available)
    return DataStatus(sources=sources, missing=list(dict.fromkeys(missing)))


def _privacy_safe_result_snapshot(
    *,
    request: RiskAssessRequest,
    response: RiskAssessmentResponse,
    current_scoring: RiskScoringResult,
    historical_scoring: RiskScoringResult,
    evidence_ids: tuple[str, ...],
) -> dict[str, object]:
    assert response.overall is not None
    return {
        "assessment_id": response.assessment_id,
        "location": {
            "lat": round(request.point.lat, 2),
            "lng": round(request.point.lng, 2),
        },
        "location_text": None,
        "radius_m": request.radius_m,
        "score_version": response.score_version,
        "scores": {
            "realtime": current_scoring.realtime_score,
            "historical": historical_scoring.historical_score,
            "confidence": max(
                current_scoring.confidence_score,
                historical_scoring.confidence_score,
            ),
        },
        "levels": {
            "realtime": response.realtime.level,
            "historical": response.historical.level,
            "overall": response.overall.level,
            "confidence": response.overall.confidence,
        },
        "dominant_mode": response.dominant_mode,
        "evidence_ids": list(evidence_ids),
        "data_status": response.data_status.model_dump(mode="json"),
        "created_at": response.created_at.isoformat(),
        "expires_at": response.expires_at.isoformat(),
    }
