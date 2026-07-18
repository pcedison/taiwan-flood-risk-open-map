from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

from app.api.schemas import (
    HealthStatus,
    NearbyCoverageLevel,
    NearbyMissingCause,
    NearbyCoverageSignal,
    NearbyCoverageSignalType,
    NearbyRealtimeCoverage,
    NearbySignalAvailability,
    NearbySourceHealth,
    NearbySourceHealthReason,
)
from app.domain.evidence.repository import NearbyCoverageRow, RealtimeSourceHealthRow

# Five kilometres remains the boundary for "nearby" coverage.  The wider
# buckets deliberately retain a regional fallback so a sparse network does not
# become an empty UI when a useful station exists just outside that boundary.
LOCAL_COVERAGE_RADIUS_M = 5000
RADIUS_BUCKETS_M = (500, 1000, 3000, LOCAL_COVERAGE_RADIUS_M, 10000, 15000)
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
    "water_level": (500, 1000, LOCAL_COVERAGE_RADIUS_M),
    "flood_depth": (500, 1000, LOCAL_COVERAGE_RADIUS_M),
    "sewer_water_level": (500, 1000, LOCAL_COVERAGE_RADIUS_M),
    "pump_or_gate_status": (500, 1000, LOCAL_COVERAGE_RADIUS_M),
    "flood_warning": (500, 1000, LOCAL_COVERAGE_RADIUS_M),
    "status_only": (500, 1000, LOCAL_COVERAGE_RADIUS_M),
}
_ADAPTER_SIGNAL_TYPES: dict[str, NearbyCoverageSignalType] = {
    "official.cwa.rainfall": "rainfall",
    "official.cwa.tide_level": "water_level",
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
    "local.kinmen.kwis_pump_station": "pump_or_gate_status",
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
REALTIME_SOURCE_ADAPTER_KEYS = tuple(_ADAPTER_SIGNAL_TYPES)
_SOURCE_OBSERVATION_FRESH = timedelta(minutes=10)
_SOURCE_OBSERVATION_EXPIRED = timedelta(hours=1)
_SOURCE_WORKER_DELAYED = timedelta(minutes=15)
_SOURCE_WORKER_STOPPED = timedelta(minutes=30)
_EVENT_CONTEXT_SIGNAL_TYPES = frozenset({"flood_warning", "status_only"})
_PUBLIC_SOURCE_NAMES = {
    "official.cwa.rainfall": "中央氣象署雨量觀測",
    "official.cwa.tide_level": "中央氣象署潮位觀測",
    "official.wra.water_level": "經濟部水利署河川水位觀測",
    "official.wra_iow.flood_depth": "經濟部水利署淹水感測",
    "official.civil_iot.flood_sensor": "水利署 Civil IoT 淹水感測",
    "official.civil_iot.river_water_level": "水利署 Civil IoT 河川水位",
    "official.civil_iot.pond_water_level": "水利署 Civil IoT 埤塘水位",
    "official.civil_iot.sewer_water_level": "水利署 Civil IoT 下水道水位",
    "official.civil_iot.pump_water_level": "水利署 Civil IoT 抽水站水位",
    "official.civil_iot.gate_water_level": "水利署 Civil IoT 水門水位",
    "official.ncdr.cap": "國家災害防救科技中心淹水警戒",
}
_LOCALITY_LABELS = {
    "taipei": "臺北市",
    "new_taipei": "新北市",
    "keelung": "基隆市",
    "taoyuan": "桃園市",
    "hsinchu_city": "新竹市",
    "hsinchu_county": "新竹縣",
    "miaoli": "苗栗縣",
    "taichung": "臺中市",
    "changhua": "彰化縣",
    "nantou": "南投縣",
    "yunlin": "雲林縣",
    "chiayi_city": "嘉義市",
    "chiayi_county": "嘉義縣",
    "tainan": "臺南市",
    "kaohsiung": "高雄市",
    "pingtung": "屏東縣",
    "yilan": "宜蘭縣",
    "hualien": "花蓮縣",
    "taitung": "臺東縣",
    "penghu": "澎湖縣",
    "kinmen": "金門縣",
}


@dataclass(frozen=True)
class _SignalEvaluation:
    signal_type: NearbyCoverageSignalType
    model: NearbyCoverageSignal
    has_rows: bool


@dataclass(frozen=True)
class _SourceHealthDecision:
    health_status: HealthStatus
    reason_code: NearbySourceHealthReason
    message: str


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


def build_nearby_source_health(
    rows: tuple[RealtimeSourceHealthRow, ...],
    *,
    evaluated_at: datetime,
    jurisdictions_by_adapter: dict[str, tuple[str, ...]] | None = None,
    required_adapter_keys: frozenset[str] | None = None,
) -> tuple[NearbySourceHealth, ...]:
    resolved_jurisdictions = jurisdictions_by_adapter or {}
    models = []
    for row in rows:
        signal_type = _ADAPTER_SIGNAL_TYPES.get(row.adapter_key)
        if signal_type is None:
            continue
        decision = _source_health_decision(
            row,
            signal_type=signal_type,
            evaluated_at=evaluated_at,
        )
        models.append(
            NearbySourceHealth(
                source_id=_public_source_id(row.adapter_key),
                name=_public_source_name(row.adapter_key, signal_type),
                signal_types=[signal_type],
                coverage_scope=("national" if row.adapter_key.startswith("official.") else "local"),
                health_status=decision.health_status,
                reason_code=decision.reason_code,
                observed_at=row.latest_observed_at,
                checked_at=_latest_timestamp(
                    row.runtime_pipeline_checked_at,
                    row.runtime_enabled_checked_at,
                    row.latest_run_at,
                    row.latest_ingested_at,
                    row.last_success_at,
                    row.last_failure_at,
                ),
                station_count=row.station_count,
                upstream_station_count=row.upstream_station_count,
                pages_fetched=row.pages_fetched,
                pagination_complete=row.pagination_complete,
                inventory_manifest_sha256=row.inventory_manifest_sha256,
                inventory_proof_status=cast(
                    Literal[
                        "missing",
                        "incomplete",
                        "awaiting_review",
                        "checksum_mismatch",
                        "approved",
                    ],
                    row.inventory_proof_status,
                ),
                inventory_complete=row.inventory_complete,
                jurisdictions=list(resolved_jurisdictions.get(row.adapter_key, ())),
                required_for_absence=(
                    True
                    if required_adapter_keys is None
                    else row.adapter_key in required_adapter_keys
                ),
                message=decision.message,
            )
        )
    return tuple(sorted(models, key=lambda item: (item.name, item.source_id)))


def build_nearby_realtime_coverage(
    *,
    rows: tuple[NearbyCoverageRow, ...],
    query_radius_m: int,
    evaluated_at: datetime,
    repository_unavailable: bool = False,
    source_health: tuple[NearbySourceHealth, ...] = (),
    source_health_unavailable: bool = False,
    source_health_checked: bool = False,
    jurisdiction_status: Literal[
        "verified",
        "boundary_unverified",
        "outside_coverage",
        "ambiguous",
        "unavailable",
    ] = "unavailable",
    jurisdiction_checked: bool = False,
    jurisdiction_complete_signal_types: tuple[NearbyCoverageSignalType, ...] = (),
    home_jurisdiction: str | None = None,
    considered_jurisdictions: tuple[str, ...] = (),
    jurisdiction_mapping_revisions: tuple[str, ...] = (),
) -> NearbyRealtimeCoverage:
    jurisdiction_unverified_signal_types = tuple(
        signal_type
        for signal_type in REQUIRED_SIGNAL_TYPES
        if signal_type not in jurisdiction_complete_signal_types
    )
    jurisdiction_catalog_complete = not jurisdiction_unverified_signal_types
    if repository_unavailable:
        summary = "資料庫目前無法查詢附近即時涵蓋。"
        limitations = [summary, _COUNTY_LEVEL_NOTE]
        if source_health_unavailable:
            limitations.append("來源健康診斷也暫時無法查詢；缺資料不代表現地安全。")
        elif source_health_checked and not source_health:
            limitations.append("目前沒有已登錄的即時來源健康紀錄；缺資料不代表附近沒有測站。")
        return NearbyRealtimeCoverage(
            overall_level="unavailable",
            evaluated_at=evaluated_at,
            query_radius_m=query_radius_m,
            radius_buckets_m=list(RADIUS_BUCKETS_M),
            summary=summary,
            signal_breakdown=[],
            missing_signal_types=list(REQUIRED_SIGNAL_TYPES),
            limitations=limitations,
            source_health=list(source_health),
            source_health_status=_aggregate_source_health(source_health),
            source_health_checked=source_health_checked,
            jurisdiction_status=jurisdiction_status,
            jurisdiction_checked=jurisdiction_checked,
            jurisdiction_catalog_complete=jurisdiction_catalog_complete,
            home_jurisdiction=home_jurisdiction,
            considered_jurisdictions=list(considered_jurisdictions),
            jurisdiction_mapping_revisions=list(jurisdiction_mapping_revisions),
            jurisdiction_unverified_signal_types=list(
                jurisdiction_unverified_signal_types
            ),
            county_level_note=_COUNTY_LEVEL_NOTE,
        )

    grouped_rows = _group_rows(rows)
    source_health_by_signal = _group_source_health(source_health)
    evaluations = [
        _evaluate_signal(
            signal_type=signal_type,
            rows=grouped_rows.get(signal_type, ()),
            source_health=source_health_by_signal.get(signal_type, ()),
            source_health_unavailable=source_health_unavailable,
            source_health_checked=source_health_checked,
            jurisdiction_verified=(
                jurisdiction_checked
                and signal_type in jurisdiction_complete_signal_types
            ),
        )
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
    if _has_local_usable_status_rows(evaluations):
        limitations.append("狀態線索只表示設備或警示狀態，不能代表雨量、水位或淹水深度。")
    if overall_level == "low" and _has_only_rainfall_or_warning(evaluations):
        limitations.append("目前只有雨量或淹水警戒可作背景參考，尚無近距離水文觀測。")
    elif overall_level == "no_local_sensor":
        if _has_source_fault(evaluations):
            limitations.append("部分即時來源或背景更新管線異常，不能據此判定附近真的沒有測站。")
        elif _has_source_degraded(evaluations):
            limitations.append("部分即時來源僅能提供延遲或不完整狀態，不能確認附近是否真的沒有測站。")
        elif _has_inventory_unverified(evaluations):
            limitations.append("站點清冊完整性尚未驗證，不能確認附近是否真的沒有測站。")
        elif _has_jurisdiction_unverified(evaluations):
            limitations.append("縣市邊界或管轄來源清單尚未完成審核，不能確認附近真的沒有測站。")
        elif _has_source_status_unknown(evaluations):
            limitations.append("目前無法取得完整來源健康狀態，不能確認附近是否真的沒有測站。")
        elif _has_regional_reference(evaluations):
            limitations.append("5 公里外的測站只作區域背景參考，不能代表查詢點現地狀況。")
        elif _has_stale_measurements(evaluations):
            limitations.append("過期觀測只用來說明最近曾有資料，不能代表當下狀況。")
        elif _has_local_usable_status_rows(evaluations):
            limitations.append("附近缺少可用的即時量測資料。")
        elif _has_source_not_configured(evaluations):
            limitations.append("部分即時來源尚未啟用，不能確認所有感測類型的附近測站涵蓋。")
        else:
            limitations.append("附近沒有可用的即時感測資料。")
    if source_health_unavailable:
        limitations.append("來源健康診斷暫時無法查詢；缺資料不代表現地安全。")
    elif source_health_checked and not source_health:
        limitations.append("目前沒有已登錄的即時來源健康紀錄；缺資料不代表附近沒有測站。")

    return NearbyRealtimeCoverage(
        overall_level=overall_level,
        evaluated_at=evaluated_at,
        query_radius_m=query_radius_m,
        radius_buckets_m=list(RADIUS_BUCKETS_M),
        summary=summary,
        signal_breakdown=[evaluation.model for evaluation in evaluations],
        missing_signal_types=missing_signal_types,
        limitations=limitations,
        source_health=list(source_health),
        source_health_status=_aggregate_source_health(source_health),
        source_health_checked=source_health_checked,
        jurisdiction_status=jurisdiction_status,
        jurisdiction_checked=jurisdiction_checked,
        jurisdiction_catalog_complete=jurisdiction_catalog_complete,
        home_jurisdiction=home_jurisdiction,
        considered_jurisdictions=list(considered_jurisdictions),
        jurisdiction_mapping_revisions=list(jurisdiction_mapping_revisions),
        jurisdiction_unverified_signal_types=list(jurisdiction_unverified_signal_types),
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
    source_health: tuple[NearbySourceHealth, ...],
    source_health_unavailable: bool,
    source_health_checked: bool,
    jurisdiction_verified: bool,
) -> _SignalEvaluation:
    in_range_rows = tuple(row for row in rows if row.distance_to_query_m <= RADIUS_BUCKETS_M[-1])
    fresh_rows = [row for row in in_range_rows if row.freshness_state == "fresh"]
    degraded_rows = [row for row in in_range_rows if row.freshness_state == "degraded"]
    usable_rows = [*fresh_rows, *degraded_rows]
    stale_rows = [
        row for row in in_range_rows if row.freshness_state not in {"fresh", "degraded"}
    ]
    nearest_row = min(in_range_rows, key=lambda row: row.distance_to_query_m, default=None)
    nearest_usable_row = min(
        usable_rows, key=lambda row: row.distance_to_query_m, default=None
    )
    nearest_display_row = nearest_usable_row or nearest_row
    counts_by_radius_m = {
        str(radius_m): sum(1 for row in in_range_rows if row.distance_to_query_m <= radius_m)
        for radius_m in RADIUS_BUCKETS_M
    }
    coverage_level = _coverage_level(signal_type, nearest_usable_row)
    missing_cause = _missing_cause(
        nearest_usable_row=nearest_usable_row,
        has_rows=bool(in_range_rows),
        source_health=source_health,
        source_health_unavailable=source_health_unavailable,
        source_health_checked=source_health_checked,
        jurisdiction_verified=jurisdiction_verified,
    )
    availability_state = _availability_state(
        coverage_level=coverage_level,
        nearest_usable_row=nearest_usable_row,
        missing_cause=missing_cause,
    )
    missing_reason = None
    if not in_range_rows:
        if missing_cause == "no_station_in_range":
            missing_reason = (
                f"目前適用的中央與縣市來源均正常提供已驗證完整的站點清冊；"
                f"查詢點 15 公里內沒有{SIGNAL_LABELS[signal_type]}測站。"
            )
        elif missing_cause == "inventory_unverified":
            missing_reason = (
                f"{SIGNAL_LABELS[signal_type]}來源目前可運作，但站點清冊完整性尚未驗證；"
                "不能確認查詢點附近真的沒有測站。"
            )
        elif missing_cause == "jurisdiction_unverified":
            missing_reason = (
                f"{SIGNAL_LABELS[signal_type]}的縣市邊界或管轄來源清單尚未完成審核；"
                "不能確認查詢點附近真的沒有測站。"
            )
        elif missing_cause == "update_pipeline_stalled":
            missing_reason = (
                f"{SIGNAL_LABELS[signal_type]}背景更新近期沒有活動；"
                "無法確認查詢點附近是否真的沒有測站。"
            )
        elif missing_cause == "source_failed":
            missing_reason = (
                f"{SIGNAL_LABELS[signal_type]}來源或背景更新管線目前異常；"
                "無法確認查詢點附近是否真的沒有測站。"
            )
        elif missing_cause == "source_degraded":
            missing_reason = (
                f"{SIGNAL_LABELS[signal_type]}來源目前僅能提供部分或延遲狀態；"
                "無法確認查詢點附近是否真的沒有測站。"
            )
        elif missing_cause == "source_not_configured":
            missing_reason = (
                f"{SIGNAL_LABELS[signal_type]}來源目前未啟用；"
                "無法確認查詢點附近是否真的沒有測站。"
            )
        else:
            missing_reason = (
                f"目前無法取得{SIGNAL_LABELS[signal_type]}來源健康狀態；"
                "無法確認查詢點附近是否真的沒有測站。"
            )
    elif not usable_rows and signal_type in REQUIRED_SIGNAL_TYPES:
        missing_reason = f"查詢點 15 公里內只有過期的{SIGNAL_LABELS[signal_type]}資料。"
    elif coverage_level == "no_local_sensor" and signal_type in REQUIRED_SIGNAL_TYPES:
        assert nearest_usable_row is not None
        missing_reason = (
            f"查詢點 5 公里內沒有{SIGNAL_LABELS[signal_type]}；"
            f"最近可用站距離約 {nearest_usable_row.distance_to_query_m / 1000:.1f} 公里，"
            "僅供區域參考。"
        )
    elif signal_type == "status_only":
        missing_reason = None

    return _SignalEvaluation(
        signal_type=signal_type,
        model=NearbyCoverageSignal(
            signal_type=signal_type,
            label=SIGNAL_LABELS[signal_type],
            coverage_level=coverage_level,
            availability_state=availability_state,
            nearest_distance_m=(
                nearest_display_row.distance_to_query_m
                if nearest_display_row is not None
                else None
            ),
            nearest_source_id=(
                nearest_display_row.source_id if nearest_display_row is not None else None
            ),
            nearest_observed_at=(
                nearest_display_row.observed_at if nearest_display_row is not None else None
            ),
            counts_by_radius_m=counts_by_radius_m,
            fresh_count=len(fresh_rows),
            degraded_count=len(degraded_rows),
            stale_count=len(stale_rows),
            status_only_count=len(in_range_rows) if signal_type == "status_only" else 0,
            nearest_freshness_state=(
                _normalized_freshness_state(nearest_display_row.freshness_state)
                if nearest_display_row is not None
                else None
            ),
            source_health_status=_aggregate_source_health(source_health),
            source_count=len(source_health),
            failed_source_count=sum(
                1 for item in source_health if item.health_status == "failed"
            ),
            missing_cause=missing_cause,
            missing_reason=missing_reason,
        ),
        has_rows=bool(in_range_rows),
    )


def _coverage_level(
    signal_type: NearbyCoverageSignalType,
    nearest_usable_row: NearbyCoverageRow | None,
) -> NearbyCoverageLevel:
    if nearest_usable_row is None:
        return "no_local_sensor"
    thresholds = _THRESHOLDS_BY_SIGNAL[signal_type]
    distance = nearest_usable_row.distance_to_query_m
    if distance <= thresholds[0]:
        return "high"
    if distance <= thresholds[1]:
        return "medium"
    if distance <= thresholds[2]:
        return "low"
    return "no_local_sensor"


def _availability_state(
    *,
    coverage_level: NearbyCoverageLevel,
    nearest_usable_row: NearbyCoverageRow | None,
    missing_cause: NearbyMissingCause,
) -> NearbySignalAvailability:
    if nearest_usable_row is None:
        if missing_cause == "stale_observation":
            return "stale_observation"
        if missing_cause == "no_station_in_range":
            return "no_station"
        if missing_cause in {
            "health_unknown",
            "inventory_unverified",
            "jurisdiction_unverified",
        }:
            return "source_status_unknown"
        return "source_unavailable"
    if coverage_level == "no_local_sensor":
        return "regional_reference"
    if nearest_usable_row.freshness_state == "fresh":
        return "fresh_nearby"
    return "degraded_nearby"


def _missing_cause(
    *,
    nearest_usable_row: NearbyCoverageRow | None,
    has_rows: bool,
    source_health: tuple[NearbySourceHealth, ...],
    source_health_unavailable: bool,
    source_health_checked: bool,
    jurisdiction_verified: bool,
) -> NearbyMissingCause:
    if nearest_usable_row is not None:
        return "none"
    if has_rows:
        runtime_cause = _runtime_missing_cause(source_health)
        if runtime_cause is not None:
            return runtime_cause
        return "stale_observation"
    if source_health_unavailable:
        return "health_unknown"
    if not source_health:
        if source_health_checked:
            return "source_not_configured"
        return "health_unknown"
    runtime_cause = _runtime_missing_cause(source_health)
    if runtime_cause is not None:
        return runtime_cause
    if not jurisdiction_verified:
        return "jurisdiction_unverified"
    if _has_conclusive_station_inventory(
        source_health,
        jurisdiction_verified=jurisdiction_verified,
    ):
        return "no_station_in_range"
    if any(item.health_status == "disabled" for item in source_health):
        return "source_not_configured"
    # A complementary source with unknown runtime health is still a live
    # uncertainty, even when another source is healthy.  Do not soften that
    # into an inventory-only gap: callers must be able to distinguish an
    # unaudited station inventory from a source whose worker/registration state
    # has not been established at all.
    if any(item.health_status == "unknown" for item in source_health):
        return "health_unknown"
    active_required = _active_required_sources(source_health)
    if active_required and all(
        item.health_status == "healthy" and item.reason_code == "operational"
        for item in active_required
    ):
        return "inventory_unverified"
    return "health_unknown"


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


def _has_local_usable_status_rows(evaluations: list[_SignalEvaluation]) -> bool:
    return any(
        evaluation.signal_type == "status_only"
        and evaluation.model.coverage_level != "no_local_sensor"
        and evaluation.model.fresh_count + evaluation.model.degraded_count > 0
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
        return "目前有雨量或淹水警戒可作即時背景參考，但缺少近距水位或淹水深度觀測。"
    if overall_level == "no_local_sensor":
        if _has_source_fault(evaluations):
            return "部分即時來源或背景更新管線異常，暫時無法確認附近是否真的沒有測站。"
        if _has_source_degraded(evaluations):
            return "部分即時來源更新延遲或僅部分可用，暫時無法確認附近是否真的沒有測站。"
        if _has_jurisdiction_unverified(evaluations):
            return "縣市邊界或管轄來源清單尚未完成審核，暫時不能確認附近真的沒有測站。"
        if _has_inventory_unverified(evaluations):
            return "來源目前可運作，但站點清冊完整性尚未驗證，不能確認附近真的沒有測站。"
        if _has_regional_reference(evaluations):
            return "查詢點 5 公里內缺少直接水情觀測；15 公里內有較遠測站可作區域參考。"
        if _has_stale_measurements(evaluations):
            return "附近有觀測紀錄，但目前已過期，不能代表當下狀況。"
        if _has_local_usable_status_rows(evaluations):
            return "附近有狀態線索，但沒有可用的雨量、水位或淹水深度量測。"
        if _has_source_status_unknown(evaluations):
            return "目前無法取得完整來源健康狀態，暫時不能確認附近是否真的沒有測站。"
        if _has_source_not_configured(evaluations):
            return "部分即時來源尚未啟用，暫時無法確認所有感測類型的附近測站涵蓋。"
        return "目前沒有可用的近距離即時感測資料。"
    available = [evaluation.signal_type for evaluation in evaluations if _has_fresh_coverage(evaluation)]
    return f"附近即時涵蓋最佳等級為 {overall_level}，可用訊號：{', '.join(available)}。"


def _has_regional_reference(evaluations: list[_SignalEvaluation]) -> bool:
    return any(
        evaluation.signal_type in REQUIRED_SIGNAL_TYPES
        and evaluation.model.coverage_level == "no_local_sensor"
        and evaluation.model.fresh_count + evaluation.model.degraded_count > 0
        for evaluation in evaluations
    )


def _has_stale_measurements(evaluations: list[_SignalEvaluation]) -> bool:
    return any(
        evaluation.signal_type in REQUIRED_SIGNAL_TYPES
        and evaluation.model.stale_count > 0
        for evaluation in evaluations
    )


def _has_source_fault(evaluations: list[_SignalEvaluation]) -> bool:
    return any(
        evaluation.signal_type in REQUIRED_SIGNAL_TYPES
        and evaluation.model.missing_cause
        in {"source_failed", "update_pipeline_stalled"}
        for evaluation in evaluations
    )


def _has_source_degraded(evaluations: list[_SignalEvaluation]) -> bool:
    return any(
        evaluation.signal_type in REQUIRED_SIGNAL_TYPES
        and evaluation.model.missing_cause == "source_degraded"
        for evaluation in evaluations
    )


def _has_source_not_configured(evaluations: list[_SignalEvaluation]) -> bool:
    return any(
        evaluation.signal_type in REQUIRED_SIGNAL_TYPES
        and evaluation.model.missing_cause == "source_not_configured"
        for evaluation in evaluations
    )


def _has_source_status_unknown(evaluations: list[_SignalEvaluation]) -> bool:
    return any(
        evaluation.signal_type in REQUIRED_SIGNAL_TYPES
        and evaluation.model.availability_state == "source_status_unknown"
        for evaluation in evaluations
    )


def _has_jurisdiction_unverified(evaluations: list[_SignalEvaluation]) -> bool:
    return any(
        evaluation.signal_type in REQUIRED_SIGNAL_TYPES
        and evaluation.model.missing_cause == "jurisdiction_unverified"
        for evaluation in evaluations
    )


def _has_inventory_unverified(evaluations: list[_SignalEvaluation]) -> bool:
    return any(
        evaluation.signal_type in REQUIRED_SIGNAL_TYPES
        and evaluation.model.missing_cause == "inventory_unverified"
        for evaluation in evaluations
    )


def _group_source_health(
    source_health: tuple[NearbySourceHealth, ...],
) -> dict[NearbyCoverageSignalType, tuple[NearbySourceHealth, ...]]:
    grouped: dict[NearbyCoverageSignalType, list[NearbySourceHealth]] = {
        signal_type: [] for signal_type in _ALL_SIGNAL_TYPES
    }
    for item in source_health:
        for signal_type in item.signal_types:
            grouped[signal_type].append(item)
    return {key: tuple(items) for key, items in grouped.items()}


def _aggregate_source_health(source_health: tuple[NearbySourceHealth, ...]) -> HealthStatus:
    if not source_health:
        return "unknown"
    active = [item for item in source_health if item.health_status != "disabled"]
    if not active:
        return "disabled"
    statuses = {item.health_status for item in active}
    operational = bool(statuses & {"healthy", "degraded"})
    if "failed" in statuses:
        return "degraded" if operational else "failed"
    if "unknown" in statuses:
        return "degraded" if operational else "unknown"
    if "degraded" in statuses:
        return "degraded"
    return "healthy"


def _active_required_sources(
    source_health: tuple[NearbySourceHealth, ...],
) -> tuple[NearbySourceHealth, ...]:
    return tuple(
        item
        for item in source_health
        if item.required_for_absence and item.health_status != "disabled"
    )


def _has_conclusive_station_inventory(
    source_health: tuple[NearbySourceHealth, ...],
    *,
    jurisdiction_verified: bool,
) -> bool:
    """Only fully operational, applicable required inventories prove a gap.

    Jurisdiction resolution filters out irrelevant counties before this point.
    Every required national or local complement must then be operational and
    independently complete. Reviewed redundant subsets remain visible but do
    not block an absence conclusion.
    """

    required = tuple(item for item in source_health if item.required_for_absence)
    return jurisdiction_verified and bool(required) and all(
        item.health_status != "disabled"
        and item.health_status == "healthy"
        and item.reason_code == "operational"
        and item.inventory_complete
        and item.station_count is not None
        and item.station_count > 0
        for item in required
    )


def _runtime_missing_cause(
    source_health: tuple[NearbySourceHealth, ...],
) -> NearbyMissingCause | None:
    active = _active_required_sources(source_health)
    if not active:
        return None
    failed = tuple(item for item in active if item.health_status == "failed")
    if failed:
        if len(failed) == len(active) and all(
            item.reason_code == "pipeline_stalled" for item in failed
        ):
            return "update_pipeline_stalled"
        # "Partially available" requires at least one genuinely operational
        # companion.  A failed source plus only unknown sources is still a
        # source failure, not degraded-but-usable coverage.
        if any(item.health_status in {"healthy", "degraded"} for item in active):
            return "source_degraded"
        return "source_failed"
    if any(item.health_status == "degraded" for item in active):
        return "source_degraded"
    if any(item.health_status == "unknown" for item in active):
        return "health_unknown"
    return None


def _source_health_decision(
    row: RealtimeSourceHealthRow,
    *,
    signal_type: NearbyCoverageSignalType,
    evaluated_at: datetime,
) -> _SourceHealthDecision:
    if not row.is_registered:
        return _source_decision(
            "unknown",
            "not_yet_observed",
            "此預期來源尚未完成公開健康狀態登錄。",
        )

    run_at = row.latest_run_at or row.last_success_at or row.last_failure_at
    run_age = _age(evaluated_at, run_at)
    status = (row.latest_run_status or "").lower()

    runtime_enabled_age = _age(evaluated_at, row.runtime_enabled_checked_at)
    runtime_selection_is_fresh = (
        row.runtime_enabled is not None
        and runtime_enabled_age is not None
        and runtime_enabled_age <= _SOURCE_WORKER_STOPPED
    )
    runtime_enabled_now = runtime_selection_is_fresh and row.runtime_enabled is True
    if runtime_selection_is_fresh and row.runtime_enabled is False:
        return _source_decision(
            "disabled",
            "disabled",
            "背景 worker 最近回報此來源未啟用。",
        )
    if row.runtime_enabled is not None and not runtime_selection_is_fresh:
        return _source_decision(
            "failed",
            "pipeline_stalled",
            "背景 worker 的來源啟用狀態已超過預期回報時間。",
        )

    if (
        row.runtime_pipeline_status == "failed"
        and row.runtime_pipeline_checked_at is not None
        and _pipeline_outcome_matches_run(row, run_at)
    ):
        return _source_decision(
            "failed",
            "pipeline_unavailable",
            "資料取得後的處理或發布流程未完成。",
        )
    if status == "disabled" and not runtime_enabled_now:
        return _source_decision("disabled", "disabled", "此來源目前未啟用。")

    configured_disabled = not row.is_enabled or row.configured_health_status == "disabled"
    runtime_activity_at = (
        row.latest_run_at
        or row.latest_ingested_at
        or row.last_success_at
        or row.last_failure_at
        or row.latest_observed_at
    )
    runtime_activity_age = _age(evaluated_at, runtime_activity_at)
    if configured_disabled and runtime_activity_at is None and not runtime_enabled_now:
        return _source_decision("disabled", "disabled", "此來源目前未啟用。")
    if (
        configured_disabled
        and not runtime_selection_is_fresh
        and runtime_activity_age is not None
        and runtime_activity_age > _SOURCE_WORKER_STOPPED
    ):
        return _source_decision(
            "unknown",
            "not_yet_observed",
            "目前無法確認此來源是刻意停用，或背景更新已停止。",
        )
    if run_age is not None and run_age > _SOURCE_WORKER_STOPPED:
        return _source_decision(
            "failed", "pipeline_stalled", "背景更新已超過預期排程時間。"
        )

    if runtime_enabled_now and status == "succeeded":
        pipeline_matches_run = (
            row.runtime_pipeline_status == "succeeded"
            and row.runtime_pipeline_checked_at is not None
            and row.runtime_pipeline_run_at is not None
            and run_at is not None
            and _same_instant(row.runtime_pipeline_run_at, run_at)
        )
        if not pipeline_matches_run:
            if run_age is not None and run_age > _SOURCE_WORKER_DELAYED:
                return _source_decision(
                    "failed",
                    "pipeline_unavailable",
                    "資料取得已完成，但最終處理或發布結果未在預期時間內確認。",
                )
            return _source_decision(
                "degraded",
                "delayed",
                "資料取得已完成，最終處理或發布結果仍待確認。",
            )
        if (
            row.runtime_pipeline_status == "succeeded"
            and not row.runtime_pipeline_complete
        ):
            return _source_decision(
                "degraded",
                "delayed",
                "最終處理或發布僅確認部分完成。",
            )

    if status == "failed":
        return _source_decision(
            "failed",
            "pipeline_unavailable",
            "最近一次背景更新未完成；不公開內部錯誤內容。",
        )
    if status in {"queued", "running"}:
        return _source_decision("degraded", "delayed", "背景更新仍在進行或回報延遲。")
    if status == "partial":
        return _source_decision("degraded", "delayed", "最近一次背景更新僅部分完成。")
    if status == "skipped":
        if signal_type in _EVENT_CONTEXT_SIGNAL_TYPES:
            return _source_decision("healthy", "operational", "來源正常；目前沒有有效事件。")
        return _source_decision(
            "degraded", "upstream_unavailable", "最近一次更新沒有取得可用觀測。"
        )
    if status == "succeeded":
        observation_decision = _observation_health_decision(
            row,
            signal_type=signal_type,
            evaluated_at=evaluated_at,
        )
        if (
            run_age is not None
            and run_age > _SOURCE_WORKER_DELAYED
            and observation_decision.health_status == "healthy"
        ):
            return _source_decision("degraded", "delayed", "背景更新時間晚於預期。")
        return observation_decision

    if row.last_failure_at is not None and (
        row.last_success_at is None or row.last_failure_at > row.last_success_at
    ):
        return _source_decision(
            "failed", "pipeline_unavailable", "最近可確認的背景更新未完成。"
        )
    if row.last_success_at is not None:
        return _observation_health_decision(
            row,
            signal_type=signal_type,
            evaluated_at=evaluated_at,
        )
    if row.latest_observed_at is not None:
        return _observation_health_decision(
            row,
            signal_type=signal_type,
            evaluated_at=evaluated_at,
        )
    if row.configured_health_status == "failed":
        return _source_decision(
            "failed", "pipeline_unavailable", "來源目前沒有可用的背景更新。"
        )
    if configured_disabled and not runtime_enabled_now:
        return _source_decision("disabled", "disabled", "此來源目前未啟用。")
    return _source_decision("unknown", "not_yet_observed", "尚無足夠紀錄判定來源健康。")


def _observation_health_decision(
    row: RealtimeSourceHealthRow,
    *,
    signal_type: NearbyCoverageSignalType,
    evaluated_at: datetime,
) -> _SourceHealthDecision:
    if signal_type in _EVENT_CONTEXT_SIGNAL_TYPES:
        return _source_decision("healthy", "operational", "來源正常；目前沒有有效事件。")
    if row.station_count is None:
        return _source_decision(
            "unknown", "not_yet_observed", "目前無法確認此來源的站點清冊狀態。"
        )
    if row.station_count == 0 or row.latest_observed_at is None:
        return _source_decision(
            "degraded", "upstream_unavailable", "來源有更新紀錄，但尚未產生可用站點觀測。"
        )
    if row.fresh_station_count is not None:
        fresh_station_count = max(0, row.fresh_station_count)
        delayed_station_count = max(0, row.delayed_station_count or 0)
        if fresh_station_count >= row.station_count:
            return _source_decision(
                "healthy",
                "operational",
                "所有目前已觀測站點皆在預期時間內更新；清冊完整性另行判定。",
            )
        if fresh_station_count + delayed_station_count > 0:
            return _source_decision(
                "degraded",
                "delayed",
                "目前已觀測站點僅部分在預期時間內更新。",
            )
        return _source_decision(
            "failed",
            "upstream_unavailable",
            "目前已觀測站點皆已超過可用時效。",
        )
    observed_age = _age(evaluated_at, row.latest_observed_at)
    if observed_age is None:
        return _source_decision("unknown", "not_yet_observed", "尚無足夠觀測時間資訊。")
    if observed_age <= _SOURCE_OBSERVATION_FRESH:
        return _source_decision(
            "healthy",
            "operational",
            "至少一個已觀測站點近期有更新；清冊完整性另行判定。",
        )
    if observed_age <= _SOURCE_OBSERVATION_EXPIRED:
        return _source_decision("degraded", "delayed", "站點觀測更新較慢。")
    return _source_decision(
        "failed", "upstream_unavailable", "站點觀測已超過可用時效。"
    )


def _source_decision(
    health_status: HealthStatus,
    reason_code: NearbySourceHealthReason,
    message: str,
) -> _SourceHealthDecision:
    return _SourceHealthDecision(
        health_status=health_status,
        reason_code=reason_code,
        message=message,
    )


def _public_source_id(adapter_key: str) -> str:
    normalized = "".join(
        character if character.isalnum() else "-" for character in adapter_key.lower()
    )
    return "-".join(part for part in normalized.split("-") if part)[:120]


def _public_source_name(
    adapter_key: str,
    signal_type: NearbyCoverageSignalType,
) -> str:
    public_name = _PUBLIC_SOURCE_NAMES.get(adapter_key)
    if public_name is not None:
        return public_name
    signal_label = SIGNAL_LABELS[signal_type]
    if adapter_key.startswith("official.cwa."):
        return f"中央氣象署{signal_label}觀測"
    if adapter_key.startswith("official.wra.") or adapter_key.startswith("official.wra_iow."):
        return f"經濟部水利署{signal_label}觀測"
    if adapter_key.startswith("official.civil_iot."):
        return f"水利署 Civil IoT {signal_label}觀測"
    if adapter_key.startswith("local."):
        locality_key = adapter_key.split(".", maxsplit=2)[1]
        locality = _LOCALITY_LABELS.get(locality_key, "地方政府")
        return f"{locality}{signal_label}觀測"
    return f"官方{signal_label}資料來源"


def _age(now: datetime, value: datetime | None) -> timedelta | None:
    if value is None:
        return None
    normalized_now = now.replace(tzinfo=UTC) if now.tzinfo is None else now.astimezone(UTC)
    normalized_value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return max(timedelta(0), normalized_now - normalized_value)


def _normalized_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _is_at_or_after(value: datetime, reference: datetime | None) -> bool:
    if reference is None:
        return True
    return _normalized_utc(value) >= _normalized_utc(reference)


def _same_instant(left: datetime, right: datetime) -> bool:
    return _normalized_utc(left) == _normalized_utc(right)


def _pipeline_outcome_matches_run(
    row: RealtimeSourceHealthRow,
    run_at: datetime | None,
) -> bool:
    if row.runtime_pipeline_run_at is not None:
        # Exact timestamps identify post-fetch outcomes.  A pre-fetch failure
        # has no ingestion row, so its generation is newer than the previous
        # run and must remain authoritative until a later run starts.
        return run_at is None or _is_at_or_after(row.runtime_pipeline_run_at, run_at)
    assert row.runtime_pipeline_checked_at is not None
    return _is_at_or_after(row.runtime_pipeline_checked_at, run_at)


def _latest_timestamp(*values: datetime | None) -> datetime | None:
    available = tuple(value for value in values if value is not None)
    if not available:
        return None
    return max(available, key=_normalized_utc)


def _normalized_freshness_state(value: str) -> Literal["fresh", "degraded", "stale"]:
    if value == "fresh":
        return "fresh"
    if value == "degraded":
        return "degraded"
    return "stale"


__all__ = [
    "LOCAL_COVERAGE_RADIUS_M",
    "RADIUS_BUCKETS_M",
    "REALTIME_SOURCE_ADAPTER_KEYS",
    "REQUIRED_SIGNAL_TYPES",
    "SIGNAL_LABELS",
    "build_nearby_realtime_coverage",
    "build_nearby_source_health",
    "coverage_signal_type",
]
