"""Precomputed risk-profile fast-path response assembly.

Builds the profile-backed assessment response and its evidence summaries.
Repository lookups (best profile, top evidence rows) stay in the route layer
so tests can monkeypatch them; this module receives their results.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Literal, cast

from app.api.schemas import (
    ConfidenceBlock,
    DataFreshness,
    Evidence,
    Explanation,
    GeoJsonGeometry,
    QueryHeat,
    RiskAssessRequest,
    RiskAssessmentResponse,
    RiskLevelBlock,
)
from app.api.services import public_evidence, public_freshness
from app.domain.geocoding import stable_uuid
from app.domain.profiles import RiskProfileRecord
from app.domain.realtime import OfficialRealtimeBundle
from app.domain.risk import score_risk

_PROFILE_SOURCE_TYPE_FALLBACKS = {
    "official": "official",
    "news": "news",
    "forum": "forum",
    "social": "social",
    "user_report": "user_report",
}
_PROFILE_EVENT_TYPE_FALLBACKS = {
    "rainfall",
    "water_level",
    "flood_warning",
    "flood_potential",
    "flood_report",
    "road_closure",
    "discussion",
}


def can_use_profile_fast_path(db_evidence_items: tuple[Evidence, ...] | None) -> bool:
    if db_evidence_items is None:
        return False
    return not any(
        item.event_type in public_freshness.OBSERVED_HISTORICAL_EVENT_TYPES
        for item in db_evidence_items
    )


def profile_has_observed_history(profile: RiskProfileRecord) -> bool:
    for count_key, raw_count in profile.evidence_counts.items():
        count = positive_int(raw_count)
        if count is None:
            continue
        _, event_type = profile_count_key_types(count_key)
        if event_type in public_freshness.OBSERVED_HISTORICAL_EVENT_TYPES:
            return True
    return False


def profile_has_public_news(profile: RiskProfileRecord) -> bool:
    for count_key, raw_count in profile.evidence_counts.items():
        count = positive_int(raw_count)
        if count is None:
            continue
        source_type, event_type = profile_count_key_types(count_key)
        if source_type == "news" and event_type in public_freshness.OBSERVED_HISTORICAL_EVENT_TYPES:
            return True
    return False


def profile_backed_response(
    *,
    request: RiskAssessRequest,
    assessment_id: str,
    profile: RiskProfileRecord,
    realtime_bundle: OfficialRealtimeBundle,
    created_at: datetime,
    top_evidence_items: tuple[Evidence, ...],
    query_heat: QueryHeat,
) -> RiskAssessmentResponse:
    realtime_scoring = score_risk(
        tuple(
            public_evidence.signal_from_official_realtime(observation)
            for observation in realtime_bundle.observations
        ),
        now=created_at,
    )
    realtime_level = (
        realtime_scoring.realtime_level
        if realtime_scoring.realtime_level != "未知"
        else public_risk_level(profile.realtime_level)
    )
    historical_level = profile_public_historical_level(profile)
    confidence_level = public_confidence_level(profile.confidence_level)
    expires_at = profile.expires_at or created_at + timedelta(minutes=5)
    data_freshness = [
        *(
            public_freshness.freshness_from_status(status)
            for status in realtime_bundle.source_statuses
        ),
        profile_data_freshness(profile, now=created_at),
    ]
    profile_items = profile_evidence_items(
        profile,
        request=request,
        created_at=created_at,
        top_evidence_items=top_evidence_items,
    )
    public_evidence.cache_assessment_evidence(assessment_id, profile_items)
    explanation = Explanation(
        summary=(
            "此結果先使用預先計算的區域風險 profile 回應，"
            "精準半徑資料會由背景工作重新整理；請視為 beta 初步參考。"
        ),
        main_reasons=profile_main_reasons(profile),
        missing_sources=profile_missing_source_messages(profile),
    )
    return RiskAssessmentResponse(
        assessment_id=assessment_id,
        location=request.point,
        radius_m=request.radius_m,
        score_version=profile.score_version,
        created_at=created_at,
        expires_at=expires_at,
        realtime=RiskLevelBlock(level=realtime_level),
        historical=RiskLevelBlock(level=historical_level),
        confidence=ConfidenceBlock(level=confidence_level),
        explanation=explanation,
        evidence=[public_evidence.evidence_preview(item) for item in profile_items],
        data_freshness=data_freshness,
        query_heat=query_heat,
    )


def profile_data_freshness(profile: RiskProfileRecord, *, now: datetime) -> DataFreshness:
    return DataFreshness(
        source_id="precomputed-risk-profile",
        name="預先計算區域風險 profile",
        health_status="healthy" if profile.status == "healthy" else "degraded",
        observed_at=profile.latest_observed_at or profile.latest_occurred_at,
        ingested_at=profile.latest_ingested_at or profile.computed_at or now,
        feature_count=profile_evidence_total(profile),
        message=(
            f"已使用預先計算的 {profile.profile_kind}:{profile.profile_scope} profile；"
            f"範圍半徑約 {profile.profile_radius_m} 公尺，"
            f"計算時間 {profile.computed_at.isoformat()}。"
        ),
    )


def profile_public_historical_level(
    profile: RiskProfileRecord,
) -> Literal["低", "中", "高", "極高", "未知"]:
    level = public_risk_level(profile.historical_level)
    if level in {"高", "極高"}:
        return "中"
    return level


def profile_main_reasons(profile: RiskProfileRecord) -> list[str]:
    reasons = [
        f"已命中預先計算的 {profile.profile_kind}:{profile.profile_scope} 區域風險 profile。",
    ]
    if profile.evidence_counts:
        reasons.append(
            f"歷史參考來自 profile 彙整的 {profile_evidence_total(profile)} 筆公開資料："
            + profile_evidence_count_summary(profile)
        )
        reasons.append("資料信心由來源類型、資料筆數、時間新鮮度與 coverage gap 綜合推估。")
    if profile.coverage_gaps:
        reasons.append("profile 仍有資料覆蓋限制：" + "、".join(profile.coverage_gaps))
    return reasons


def profile_missing_source_messages(profile: RiskProfileRecord) -> list[str]:
    messages = []
    for source in profile.missing_sources:
        if source == "rainfall":
            messages.append("profile 未納入即時雨量來源；這會限制即時風險，不代表歷史參考沒有依據。")
        elif source == "water_level":
            messages.append("profile 未納入即時水位來源；這會限制即時風險，不代表歷史參考沒有依據。")
        else:
            messages.append(f"profile 未納入 {source} 來源；請把它視為資料覆蓋限制。")
    if profile.status != "healthy":
        messages.append("profile 目前不是 healthy 狀態，結果只能作為初步參考。")
    return messages


def profile_evidence_items(
    profile: RiskProfileRecord,
    *,
    request: RiskAssessRequest,
    created_at: datetime,
    top_evidence_items: tuple[Evidence, ...],
) -> list[Evidence]:
    represented_count_keys = {
        profile_normalized_count_key(item.source_type, item.event_type)
        for item in top_evidence_items
    }
    evidence_items: list[Evidence] = list(top_evidence_items)
    for count_key, raw_count in sorted(profile.evidence_counts.items()):
        count = positive_int(raw_count)
        if count is None:
            continue
        source_type, event_type = profile_count_key_types(count_key)
        normalized_count_key = profile_normalized_count_key(source_type, event_type)
        if normalized_count_key in represented_count_keys:
            continue
        label = profile_count_label(source_type, event_type)
        evidence_items.append(
            Evidence(
                id=stable_uuid(
                    "profile-evidence-summary",
                    profile.profile_kind,
                    profile.profile_key,
                    count_key,
                ),
                source_id=f"precomputed-risk-profile:{count_key}",
                source_type=cast(Any, source_type),
                event_type=cast(Any, event_type),
                title=f"{label} profile 摘要",
                summary=(
                    f"預先計算 profile 彙整 {count} 筆{label}。"
                    "這是區域層級的摘要證據，不等於逐篇新聞清單；"
                    "精準半徑資料會由背景工作更新。"
                ),
                url=public_evidence.public_evidence_url(
                    source_type=source_type,
                    event_type=event_type,
                    fallback_url=None,
                ),
                occurred_at=profile.latest_occurred_at,
                observed_at=profile.latest_observed_at,
                ingested_at=profile.latest_ingested_at or profile.computed_at or created_at,
                point=request.point,
                geometry=GeoJsonGeometry(
                    type="Point",
                    coordinates=[request.point.lng, request.point.lat],
                ),
                distance_to_query_m=profile.distance_to_query_m,
                confidence=profile_evidence_confidence(profile),
                freshness_score=profile_evidence_freshness_score(profile),
                source_weight=profile_source_weight(source_type),
                privacy_level="aggregated",
                raw_ref=profile_evidence_raw_ref(profile, count_key=count_key),
            )
        )
    return evidence_items


def profile_evidence_raw_ref(profile: RiskProfileRecord, *, count_key: str) -> str:
    if not profile.top_evidence_ids:
        return f"profile:{profile.profile_kind}:{profile.profile_key}:{count_key}"
    top_ids = ",".join(profile.top_evidence_ids[:5])
    return f"profile:{profile.profile_kind}:{profile.profile_key}:{count_key}:top={top_ids}"


def profile_count_key_types(count_key: str) -> tuple[str, str]:
    if ":" in count_key:
        source_key, event_key = count_key.split(":", 1)
    else:
        source_key = count_key
        event_key = {
            "official": "flood_potential",
            "news": "flood_report",
            "forum": "discussion",
            "social": "discussion",
            "user_report": "flood_report",
        }.get(source_key, "discussion")
    source_type = _PROFILE_SOURCE_TYPE_FALLBACKS.get(source_key, "derived")
    event_type = event_key if event_key in _PROFILE_EVENT_TYPE_FALLBACKS else "discussion"
    return source_type, event_type


def profile_normalized_count_key(source_type: str, event_type: str) -> str:
    return f"{source_type}:{event_type}"


def profile_count_label(source_type: str, event_type: str) -> str:
    source_labels = {
        "official": "官方",
        "news": "新聞",
        "forum": "討論區",
        "social": "社群",
        "user_report": "民眾回報",
        "derived": "衍生",
    }
    event_labels = {
        "rainfall": "雨量資料",
        "water_level": "水位資料",
        "flood_warning": "淹水警戒",
        "flood_potential": "淹水潛勢資料",
        "flood_report": "淹水事件資料",
        "road_closure": "道路封閉資料",
        "discussion": "公開討論資料",
    }
    return f"{source_labels.get(source_type, '資料')}{event_labels.get(event_type, '資料')}"


def profile_evidence_count_summary(profile: RiskProfileRecord) -> str:
    parts = []
    for count_key, raw_count in sorted(profile.evidence_counts.items()):
        count = positive_int(raw_count)
        if count is None:
            continue
        source_type, event_type = profile_count_key_types(count_key)
        parts.append(f"{profile_count_label(source_type, event_type)} {count} 筆")
    return "、".join(parts) if parts else "尚無可列出的資料筆數"


def profile_evidence_total(profile: RiskProfileRecord) -> int:
    total = 0
    for raw_count in profile.evidence_counts.values():
        count = positive_int(raw_count)
        if count is not None:
            total += count
    return total


def positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        count = int(value)
    elif isinstance(value, int):
        count = value
    elif isinstance(value, float):
        count = int(value)
    elif isinstance(value, str):
        try:
            count = int(value)
        except ValueError:
            return None
    else:
        return None
    return count if count > 0 else None


def profile_evidence_confidence(profile: RiskProfileRecord) -> float:
    return {
        "high": 0.86,
        "medium": 0.68,
        "low": 0.46,
        "unknown": 0.25,
    }.get(profile.confidence_level, 0.55)


def profile_evidence_freshness_score(profile: RiskProfileRecord) -> float:
    if profile.latest_observed_at or profile.latest_occurred_at:
        return 0.72
    if profile.latest_ingested_at:
        return 0.62
    return 0.5


def profile_source_weight(source_type: str) -> float:
    return {
        "official": 1.0,
        "news": 0.72,
        "forum": 0.48,
        "social": 0.42,
        "user_report": 0.58,
        "derived": 0.5,
    }.get(source_type, 0.5)


def public_risk_level(level: str) -> Literal["低", "中", "高", "極高", "未知"]:
    return cast(
        Literal["低", "中", "高", "極高", "未知"],
        {
            "low": "低",
            "medium": "中",
            "high": "高",
            "severe": "極高",
            "unknown": "未知",
        }.get(level, "未知"),
    )


def public_confidence_level(level: str) -> Literal["低", "中", "高", "未知"]:
    return cast(
        Literal["低", "中", "高", "未知"],
        {
            "low": "低",
            "medium": "中",
            "high": "高",
            "unknown": "未知",
        }.get(level, "未知"),
    )
