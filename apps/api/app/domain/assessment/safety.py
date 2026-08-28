from dataclasses import replace

from app.domain.assessment.models import AssessmentData, OverallDecision
from app.domain.risk import RiskScoringResult

_USABLE_LOCAL_STATES = frozenset({"fresh_nearby", "degraded_nearby"})
_HYDROLOGY = frozenset({"water_level", "flood_depth", "sewer_water_level"})
_RISK_LEVEL_RANK = {"未知": 0, "低": 1, "中": 2, "高": 3, "極高": 4}


def _query_local_signal_types(data: AssessmentData) -> frozenset[str]:
    return frozenset(
        item.signal_type
        for item in data.nearby_coverage.signal_breakdown
        if item.availability_state in _USABLE_LOCAL_STATES
    )


def can_support_low_realtime(data: AssessmentData) -> bool:
    if not all(
        (
            data.current_available,
            data.coverage_available,
            data.health_available,
            data.jurisdiction_available,
            data.nearby_coverage.source_health_checked,
            data.nearby_coverage.jurisdiction_checked,
            data.nearby_coverage.jurisdiction_catalog_complete,
        )
    ):
        return False
    state_by_key = {state.source_key: state.state for state in data.source_states}
    if any(
        state_by_key.get(key) not in {"fresh", "degraded", "not_applicable"}
        for key in data.required_realtime_source_keys
    ):
        return False
    local = _query_local_signal_types(data)
    return "rainfall" in local and bool(local & _HYDROLOGY)


def apply_realtime_safety(
    scoring: RiskScoringResult,
    data: AssessmentData,
) -> RiskScoringResult:
    if scoring.realtime_level != "低" or can_support_low_realtime(data):
        return scoring
    message = "必要的官方即時來源或查詢點附近涵蓋不足，不能把結果判為低風險。"
    return replace(
        scoring,
        realtime_level="未知",
        explanation_summary="即時資料不足，無法判定目前風險；請另見歷史背景區塊。",
        missing_sources=tuple(dict.fromkeys((*scoring.missing_sources, message))),
    )


def compose_base_overall(
    realtime_scoring: RiskScoringResult,
    historical_scoring: RiskScoringResult,
) -> OverallDecision:
    realtime_level = realtime_scoring.realtime_level
    historical_level = historical_scoring.historical_level
    if _RISK_LEVEL_RANK[historical_level] > _RISK_LEVEL_RANK[realtime_level]:
        if realtime_level == "未知":
            context_reason = "目前缺少可採用的即時證據；此等級只代表歷史背景風險。"
        else:
            context_reason = (
                f"歷史參考風險（{historical_level}）高於即時風險（{realtime_level}）；"
                "綜合等級採較高者，但不表示目前正在淹水。"
            )
        return OverallDecision(
            historical_level,
            historical_scoring.confidence_level,
            "historical_context",
            tuple(dict.fromkeys((context_reason, *historical_scoring.main_reasons))),
        )
    if realtime_scoring.realtime_level != "未知":
        return OverallDecision(
            realtime_level,
            realtime_scoring.confidence_level,
            "realtime",
            realtime_scoring.main_reasons,
        )
    return OverallDecision(
        "未知",
        "未知",
        "unknown",
        ("目前即時與歷史資料都不足，不能解讀為低風險。",),
    )
