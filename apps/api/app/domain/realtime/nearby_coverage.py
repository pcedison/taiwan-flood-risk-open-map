from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import cast

from app.api.schemas import (
    NearbyCoverageLevel,
    NearbyCoverageSignal,
    NearbyCoverageSignalType,
    NearbyRealtimeCoverage,
)
from app.domain.evidence.repository import NearbyCoverageRow

RADIUS_BUCKETS_M = (500, 1000, 3000, 5000)
REQUIRED_SIGNAL_TYPES: tuple[NearbyCoverageSignalType, ...] = (
    "rainfall",
    "water_level",
    "flood_depth",
    "sewer_water_level",
)
SIGNAL_LABELS: dict[NearbyCoverageSignalType, str] = {
    "rainfall": "雨量",
    "water_level": "水位",
    "flood_depth": "淹水深度",
    "sewer_water_level": "下水道水位",
    "pump_or_gate_status": "抽水站/水門狀態",
    "flood_warning": "淹水警戒",
    "status_only": "狀態線索",
}

_ALL_SIGNAL_TYPES: tuple[NearbyCoverageSignalType, ...] = REQUIRED_SIGNAL_TYPES + (
    "pump_or_gate_status",
    "flood_warning",
    "status_only",
)
_COUNTY_LEVEL_NOTE = (
    "縣市層級涵蓋只作背景參考，不代表查詢點附近的感測器覆蓋；"
    "附近涵蓋會依查詢點重新計算。"
)
_RANK_BY_LEVEL: dict[NearbyCoverageLevel, int] = {
    "no_local_sensor": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
}
_LEVEL_BY_RANK: dict[int, NearbyCoverageLevel] = {
    rank: level for level, rank in _RANK_BY_LEVEL.items()
}
_THRESHOLDS_BY_SIGNAL: dict[NearbyCoverageSignalType, tuple[int, int, int]] = {
    "rainfall": (1000, 3000, 5000),
    "water_level": (500, 1000, 3000),
    "flood_depth": (500, 1000, 3000),
    "sewer_water_level": (500, 1000, 3000),
    "pump_or_gate_status": (500, 1000, 3000),
    "flood_warning": (500, 1000, 3000),
    "status_only": (500, 1000, 3000),
}
_ADAPTER_SIGNAL_TYPES: dict[str, NearbyCoverageSignalType] = {
    "official.cwa.rainfall": "rainfall",
    "official.wra.water_level": "water_level",
    "official.wra_iow.flood_depth": "flood_depth",
    "official.civil_iot.flood_sensor": "flood_depth",
    "official.civil_iot.river_water_level": "water_level",
    "official.civil_iot.pond_water_level": "water_level",
    "official.civil_iot.sewer_water_level": "sewer_water_level",
    "official.civil_iot.pump_water_level": "pump_or_gate_status",
    "official.civil_iot.gate_water_level": "pump_or_gate_status",
    "official.ncdr.cap": "flood_warning",
    "local.taipei.sewer_water_level": "sewer_water_level",
    "local.taipei.river_water_level": "water_level",
    "local.taipei.pump_station": "pump_or_gate_status",
    "local.new_taipei.water_level": "water_level",
    "local.new_taipei.flood_sensor": "flood_depth",
    "local.new_taipei.rainfall": "rainfall",
    "local.new_taipei.drainage_water_level": "sewer_water_level",
    "local.keelung.water_level": "water_level",
    "local.keelung.flood_sensor": "flood_depth",
    "local.keelung.rainfall": "rainfall",
    "local.taoyuan.flood_sensor": "flood_depth",
    "local.taoyuan.water_level": "water_level",
    "local.taoyuan.rainfall": "rainfall",
    "local.hsinchu_city.sewer_water_level": "sewer_water_level",
    "local.hsinchu_city.flood_sensor": "flood_depth",
    "local.hsinchu_county.flood_sensor": "flood_depth",
    "local.miaoli.flood_sensor": "flood_depth",
    "local.taichung.water_level": "water_level",
    "local.changhua.flood_sensor": "flood_depth",
    "local.nantou.sewer_water_level": "sewer_water_level",
    "local.yunlin.water_level": "water_level",
    "local.chiayi_city.water_level": "water_level",
    "local.chiayi_city.rainfall": "rainfall",
    "local.chiayi_county.flood_sensor": "flood_depth",
    "local.tainan.flood_sensor": "flood_depth",
    "local.kaohsiung.sewer_water_level": "sewer_water_level",
    "local.kaohsiung.flood_sensor": "flood_depth",
    "local.kaohsiung.rainfall": "rainfall",
    "local.pingtung.flood_sensor": "flood_depth",
    "local.yilan.flood_sensor": "flood_depth",
    "local.yilan.water_level": "water_level",
    "local.hualien.flood_sensor": "flood_depth",
    "local.taitung.flood_sensor": "flood_depth",
    "local.penghu.water_level": "water_level",
}
_EVENT_TYPE_ALIASES: dict[str, NearbyCoverageSignalType] = {
    "river_water_level": "water_level",
    "pond_water_level": "water_level",
    "pump_water_level": "pump_or_gate_status",
    "gate_water_level": "pump_or_gate_status",
    "pump_status": "pump_or_gate_status",
    "gate_status": "pump_or_gate_status",
    "flood_report": "flood_depth",
    "flood_sensor": "flood_depth",
}


@dataclass(frozen=True)
class _SignalEvaluation:
    signal_type: NearbyCoverageSignalType
    model: NearbyCoverageSignal
    has_rows: bool


def coverage_signal_type(event_type: str, adapter_key: str) -> NearbyCoverageSignalType:
    if event_type == "status_only":
        return "status_only"
    adapter_signal_type = _ADAPTER_SIGNAL_TYPES.get(adapter_key)
    if adapter_signal_type is not None:
        return adapter_signal_type
    alias_signal_type = _EVENT_TYPE_ALIASES.get(event_type)
    if alias_signal_type is not None:
        return alias_signal_type
    if event_type in _ALL_SIGNAL_TYPES:
        return cast(NearbyCoverageSignalType, event_type)
    return "status_only"


def build_nearby_realtime_coverage(
    *,
    rows: tuple[NearbyCoverageRow, ...],
    query_radius_m: int,
    evaluated_at: datetime,
    repository_unavailable: bool = False,
) -> NearbyRealtimeCoverage:
    if repository_unavailable:
        summary = "資料庫目前無法查詢附近即時涵蓋。"
        return NearbyRealtimeCoverage(
            overall_level="unavailable",
            evaluated_at=evaluated_at,
            query_radius_m=query_radius_m,
            radius_buckets_m=list(RADIUS_BUCKETS_M),
            summary=summary,
            signal_breakdown=[],
            missing_signal_types=list(REQUIRED_SIGNAL_TYPES),
            limitations=[summary, _COUNTY_LEVEL_NOTE],
            county_level_note=_COUNTY_LEVEL_NOTE,
        )

    grouped_rows = _group_rows(rows)
    evaluations = [
        _evaluate_signal(signal_type=signal_type, rows=grouped_rows.get(signal_type, ()))
        for signal_type in _ALL_SIGNAL_TYPES
    ]
    overall_level = _overall_level(evaluations)
    summary = _build_summary(evaluations=evaluations, overall_level=overall_level)
    missing_signal_types = [
        evaluation.signal_type
        for evaluation in evaluations
        if evaluation.signal_type in REQUIRED_SIGNAL_TYPES
        and evaluation.model.coverage_level == "no_local_sensor"
    ]
    limitations = [_COUNTY_LEVEL_NOTE]
    if _has_status_only_rows(evaluations):
        limitations.append("狀態線索只表示設備或警示狀態，不能代表雨量、水位或淹水深度。")
    if overall_level == "low" and _has_only_rainfall_or_warning(evaluations):
        limitations.append("目前只有雨量或淹水警戒可作背景參考，尚無近距離水文觀測。")
    elif overall_level == "no_local_sensor":
        if _has_status_only_rows(evaluations):
            limitations.append("附近缺少可用的即時量測資料。")
        else:
            limitations.append("附近沒有可用的即時感測資料。")

    return NearbyRealtimeCoverage(
        overall_level=overall_level,
        evaluated_at=evaluated_at,
        query_radius_m=query_radius_m,
        radius_buckets_m=list(RADIUS_BUCKETS_M),
        summary=summary,
        signal_breakdown=[evaluation.model for evaluation in evaluations],
        missing_signal_types=missing_signal_types,
        limitations=limitations,
        county_level_note=_COUNTY_LEVEL_NOTE,
    )


def _group_rows(
    rows: tuple[NearbyCoverageRow, ...],
) -> dict[NearbyCoverageSignalType, tuple[NearbyCoverageRow, ...]]:
    grouped: dict[NearbyCoverageSignalType, list[NearbyCoverageRow]] = {
        signal_type: [] for signal_type in _ALL_SIGNAL_TYPES
    }
    for row in rows:
        if row.distance_to_query_m > RADIUS_BUCKETS_M[-1]:
            continue
        grouped[coverage_signal_type(row.event_type, row.adapter_key)].append(row)
    return {signal_type: tuple(items) for signal_type, items in grouped.items()}


def _evaluate_signal(
    *,
    signal_type: NearbyCoverageSignalType,
    rows: tuple[NearbyCoverageRow, ...],
) -> _SignalEvaluation:
    in_range_rows = tuple(row for row in rows if row.distance_to_query_m <= RADIUS_BUCKETS_M[-1])
    fresh_rows = [row for row in in_range_rows if row.freshness_state == "fresh"]
    stale_rows = [row for row in in_range_rows if row.freshness_state != "fresh"]
    nearest_row = min(in_range_rows, key=lambda row: row.distance_to_query_m, default=None)
    nearest_fresh_row = min(fresh_rows, key=lambda row: row.distance_to_query_m, default=None)
    counts_by_radius_m = {
        str(radius_m): sum(1 for row in in_range_rows if row.distance_to_query_m <= radius_m)
        for radius_m in RADIUS_BUCKETS_M
    }
    coverage_level = _coverage_level(signal_type, nearest_fresh_row)
    missing_reason = None
    if not in_range_rows:
        missing_reason = f"查詢點 5 公里內沒有{SIGNAL_LABELS[signal_type]}資料。"
    elif not fresh_rows and signal_type in REQUIRED_SIGNAL_TYPES:
        missing_reason = f"查詢點 5 公里內只有過期的{SIGNAL_LABELS[signal_type]}資料。"
    elif signal_type == "status_only":
        missing_reason = None

    return _SignalEvaluation(
        signal_type=signal_type,
        model=NearbyCoverageSignal(
            signal_type=signal_type,
            label=SIGNAL_LABELS[signal_type],
            coverage_level=coverage_level,
            nearest_distance_m=nearest_row.distance_to_query_m if nearest_row is not None else None,
            nearest_source_id=nearest_row.source_id if nearest_row is not None else None,
            nearest_observed_at=nearest_row.observed_at if nearest_row is not None else None,
            counts_by_radius_m=counts_by_radius_m,
            fresh_count=len(fresh_rows),
            stale_count=len(stale_rows),
            status_only_count=len(in_range_rows) if signal_type == "status_only" else 0,
            missing_reason=missing_reason,
        ),
        has_rows=bool(in_range_rows),
    )


def _coverage_level(
    signal_type: NearbyCoverageSignalType,
    nearest_fresh_row: NearbyCoverageRow | None,
) -> NearbyCoverageLevel:
    if nearest_fresh_row is None:
        return "no_local_sensor"
    thresholds = _THRESHOLDS_BY_SIGNAL[signal_type]
    distance = nearest_fresh_row.distance_to_query_m
    if distance <= thresholds[0]:
        return "high"
    if distance <= thresholds[1]:
        return "medium"
    if distance <= thresholds[2]:
        return "low"
    return "no_local_sensor"


def _overall_level(evaluations: list[_SignalEvaluation]) -> NearbyCoverageLevel:
    hydrologic_rank = 0
    for evaluation in evaluations:
        if evaluation.signal_type in {"water_level", "flood_depth", "sewer_water_level"}:
            hydrologic_rank = max(hydrologic_rank, _RANK_BY_LEVEL[evaluation.model.coverage_level])
    if hydrologic_rank:
        return _LEVEL_BY_RANK[hydrologic_rank]
    if any(
        evaluation.signal_type == "rainfall"
        and evaluation.model.coverage_level != "no_local_sensor"
        for evaluation in evaluations
    ):
        return "low"
    return "no_local_sensor"


def _has_only_rainfall_or_warning(evaluations: list[_SignalEvaluation]) -> bool:
    relevant_types = {
        evaluation.signal_type
        for evaluation in evaluations
        if _has_fresh_coverage(evaluation)
        and evaluation.signal_type
        in {"rainfall", "flood_warning", "water_level", "flood_depth", "sewer_water_level"}
    }
    return bool(relevant_types) and relevant_types <= {"rainfall", "flood_warning"}


def _has_status_only_rows(evaluations: list[_SignalEvaluation]) -> bool:
    return any(
        evaluation.signal_type == "status_only" and evaluation.has_rows
        for evaluation in evaluations
    )


def _has_fresh_coverage(evaluation: _SignalEvaluation) -> bool:
    return evaluation.model.coverage_level != "no_local_sensor"


def _build_summary(
    *, evaluations: list[_SignalEvaluation], overall_level: NearbyCoverageLevel
) -> str:
    if overall_level == "unavailable":
        return "資料庫目前無法查詢附近即時涵蓋。"
    if overall_level == "low" and _has_only_rainfall_or_warning(evaluations):
        return "目前只有雨量或淹水警戒可作背景參考。"
    if overall_level == "no_local_sensor":
        if _has_status_only_rows(evaluations):
            return "附近有狀態線索，但沒有可用的雨量、水位或淹水深度量測。"
        return "目前沒有可用的近距離即時感測資料。"
    available = [evaluation.signal_type for evaluation in evaluations if _has_fresh_coverage(evaluation)]
    return f"附近即時涵蓋最佳等級為 {overall_level}，可用訊號：{', '.join(available)}。"


__all__ = [
    "RADIUS_BUCKETS_M",
    "REQUIRED_SIGNAL_TYPES",
    "SIGNAL_LABELS",
    "build_nearby_realtime_coverage",
    "coverage_signal_type",
]
