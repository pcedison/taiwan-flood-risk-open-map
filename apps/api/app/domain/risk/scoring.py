from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal


PublicRiskLevel = Literal["低", "中", "高", "極高", "未知"]
PublicConfidenceLevel = Literal["低", "中", "高", "未知"]

SCORE_VERSION = "risk-v0.1.0"

REALTIME_WEIGHTS = {
    "rainfall": 40.0,
    "water_level": 35.0,
    "flood_warning": 50.0,
    "flood_report": 20.0,
    "road_closure": 20.0,
}
HISTORICAL_WEIGHTS = {
    "flood_potential": 40.0,
    "flood_report": 35.0,
    "road_closure": 15.0,
}
EVENT_SCORE_CAPS = {
    # Flood-potential polygons are correlated planning/reference layers. Multiple
    # overlapping polygons should not stack into an "active disaster" signal.
    "flood_potential": 40.0,
}
REQUIRED_REALTIME_EVENTS = {"rainfall", "water_level"}


@dataclass(frozen=True)
class RiskEvidenceSignal:
    source_type: str
    event_type: str
    confidence: float
    distance_to_query_m: float | None
    freshness_score: float
    source_weight: float
    risk_factor: float = 1.0
    observed_at: datetime | None = None


@dataclass(frozen=True)
class RiskScoringResult:
    score_version: str
    realtime_score: float
    historical_score: float
    confidence_score: float
    realtime_level: PublicRiskLevel
    historical_level: PublicRiskLevel
    confidence_level: PublicConfidenceLevel
    explanation_summary: str
    main_reasons: tuple[str, ...]
    missing_sources: tuple[str, ...]


def score_risk(signals: tuple[RiskEvidenceSignal, ...], *, now: datetime) -> RiskScoringResult:
    realtime_score = _weighted_score(signals, REALTIME_WEIGHTS, now=now, max_age=timedelta(hours=6))
    historical_score = _weighted_score(signals, HISTORICAL_WEIGHTS)
    confidence_score = _confidence_score(signals)
    missing_sources = _missing_sources(signals)
    has_historical_evidence = _has_weighted_evidence(signals, HISTORICAL_WEIGHTS)

    if missing_sources and confidence_score > 0.74:
        confidence_score = 0.74
    if not has_historical_evidence and confidence_score > 0.74:
        confidence_score = 0.74

    realtime_level = _risk_level(
        realtime_score,
        has_evidence=_has_weighted_evidence(
            signals,
            REALTIME_WEIGHTS,
            now=now,
            max_age=timedelta(hours=6),
        ),
    )
    historical_level = _risk_level(
        historical_score,
        has_evidence=has_historical_evidence,
    )
    confidence_level = _confidence_level(confidence_score, has_evidence=bool(signals))
    main_reasons = _main_reasons(signals, realtime_level, historical_level)

    return RiskScoringResult(
        score_version=SCORE_VERSION,
        realtime_score=round(realtime_score, 3),
        historical_score=round(historical_score, 3),
        confidence_score=round(confidence_score, 3),
        realtime_level=realtime_level,
        historical_level=historical_level,
        confidence_level=confidence_level,
        explanation_summary=_summary(realtime_level, historical_level, confidence_level),
        main_reasons=main_reasons,
        missing_sources=missing_sources,
    )


def _weighted_score(
    signals: tuple[RiskEvidenceSignal, ...],
    weights: dict[str, float],
    *,
    now: datetime | None = None,
    max_age: timedelta | None = None,
) -> float:
    totals_by_event: dict[str, float] = {}
    for signal in signals:
        weight = weights.get(signal.event_type, 0.0)
        if weight == 0:
            continue
        if now is not None and max_age is not None and not _is_recent(signal, now, max_age):
            continue
        contribution = (
            weight
            * _clamp(signal.confidence)
            * _clamp(signal.freshness_score)
            * _clamp(signal.risk_factor)
            * _distance_factor(signal.distance_to_query_m)
            * max(signal.source_weight, 0.0)
        )
        event_total = totals_by_event.get(signal.event_type, 0.0) + contribution
        event_cap = EVENT_SCORE_CAPS.get(signal.event_type)
        totals_by_event[signal.event_type] = (
            min(event_total, event_cap) if event_cap is not None else event_total
        )
    total = sum(totals_by_event.values())
    return min(total, 100.0)


def _has_weighted_evidence(
    signals: tuple[RiskEvidenceSignal, ...],
    weights: dict[str, float],
    *,
    now: datetime | None = None,
    max_age: timedelta | None = None,
) -> bool:
    return any(
        weights.get(signal.event_type, 0.0) > 0
        and (now is None or max_age is None or _is_recent(signal, now, max_age))
        for signal in signals
    )


def _is_recent(signal: RiskEvidenceSignal, now: datetime, max_age: timedelta) -> bool:
    if signal.observed_at is None:
        return False
    observed_at = signal.observed_at
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=now.tzinfo)
    return now - max_age <= observed_at <= now + timedelta(minutes=5)


def _confidence_score(signals: tuple[RiskEvidenceSignal, ...]) -> float:
    if not signals:
        return 0.0
    weighted_confidences = [
        _clamp(signal.confidence) * max(signal.source_weight, 0.0) for signal in signals
    ]
    total_weight = sum(max(signal.source_weight, 0.0) for signal in signals)
    if total_weight == 0:
        return 0.0
    source_bonus = 0.06 if any(signal.source_type == "official" for signal in signals) else 0.0
    return min((sum(weighted_confidences) / total_weight) + source_bonus, 1.0)


def _distance_factor(distance_to_query_m: float | None) -> float:
    if distance_to_query_m is None:
        return 0.85
    if distance_to_query_m <= 100:
        return 1.0
    if distance_to_query_m <= 500:
        return 0.75
    return 0.5


def _risk_level(score: float, *, has_evidence: bool) -> PublicRiskLevel:
    if not has_evidence:
        return "未知"
    if score >= 85:
        return "極高"
    if score >= 55:
        return "高"
    if score >= 25:
        return "中"
    return "低"


def _confidence_level(score: float, *, has_evidence: bool) -> PublicConfidenceLevel:
    if not has_evidence:
        return "未知"
    if score >= 0.8:
        return "高"
    if score >= 0.5:
        return "中"
    return "低"


def _missing_sources(signals: tuple[RiskEvidenceSignal, ...]) -> tuple[str, ...]:
    event_types = {signal.event_type for signal in signals}
    missing = []
    if "rainfall" not in event_types:
        missing.append("尚未接入即時雨量資料。")
    if "water_level" not in event_types:
        missing.append("尚未接入即時水位資料。")
    return tuple(missing)


def _main_reasons(
    signals: tuple[RiskEvidenceSignal, ...],
    realtime_level: PublicRiskLevel,
    historical_level: PublicRiskLevel,
) -> tuple[str, ...]:
    if not signals:
        return ("目前缺少可採用的即時或歷史資料，尚不能判定風險高低。",)

    event_types = {signal.event_type for signal in signals}
    reasons = []
    if realtime_level in {"高", "極高"}:
        reasons.append("附近即時雨量或水位資料偏高。")
    if historical_level in {"中", "高", "極高"} and "flood_potential" in event_types:
        reasons.append("查詢半徑內與淹水潛勢規劃圖資相交；這是情境參考，不代表即時災害警報。")
    if "flood_report" in event_types:
        reasons.append("附近有近期公開淹水通報或新聞線索。")
    if not reasons:
        reasons.append("目前可用資料未形成強烈即時淹水訊號。")
    return tuple(reasons)


def _summary(
    realtime_level: PublicRiskLevel,
    historical_level: PublicRiskLevel,
    confidence_level: PublicConfidenceLevel,
) -> str:
    if (
        realtime_level == "未知"
        and historical_level == "未知"
        and confidence_level == "未知"
    ):
        return "目前資料不足，無法判定即時或歷史淹水風險；請把結果視為待查證，而不是低風險。"
    if realtime_level == "未知" and historical_level != "未知":
        return (
            f"即時資料不足，無法判定即時風險；"
            f"歷史與淹水潛勢參考為{historical_level}，資料信心為{confidence_level}。"
        )
    return f"即時風險為{realtime_level}，歷史與淹水潛勢參考為{historical_level}，資料信心為{confidence_level}。"


def _clamp(value: float) -> float:
    return min(max(value, 0.0), 1.0)
