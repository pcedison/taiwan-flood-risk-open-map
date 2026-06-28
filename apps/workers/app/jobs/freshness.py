from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from app.jobs.ingestion import AdapterBatchRunSummary
from app.logging import log_event


FreshnessStatus = Literal["fresh", "degraded", "stale", "failed"]
FreshnessCadence = Literal["realtime", "event", "static", "legacy"]

REALTIME_FRESH_SECONDS = 10 * 60
REALTIME_DEGRADED_SECONDS = 30 * 60
REALTIME_STALE_SECONDS = 60 * 60
REALTIME_ADAPTER_KEYS = frozenset(
    {
        "official.cwa.rainfall",
        "official.wra.water_level",
        "official.wra_iow.flood_depth",
        "official.civil_iot.flood_sensor",
        "official.civil_iot.river_water_level",
        "official.civil_iot.pond_water_level",
        "official.civil_iot.sewer_water_level",
        "official.civil_iot.pump_water_level",
        "official.civil_iot.gate_water_level",
        "local.taipei.sewer_water_level",
        "local.taipei.river_water_level",
        "local.taipei.pump_station",
        "local.taoyuan.flood_sensor",
        "local.taoyuan.water_level",
        "local.taoyuan.rainfall",
        "local.chiayi_city.water_level",
        "local.chiayi_city.rainfall",
        "local.taichung.water_level",
        "local.tainan.flood_sensor",
    }
)
STATIC_SLOW_CADENCE_ADAPTER_KEYS = frozenset({"official.flood_potential.geojson"})


@dataclass(frozen=True)
class FreshnessCheck:
    adapter_key: str
    status: FreshnessStatus
    checked_at: datetime
    max_age_seconds: int
    cadence: FreshnessCadence = "realtime"
    source_timestamp_max: datetime | None = None
    age_seconds: int | None = None
    reason: str | None = None

    def is_alert(self) -> bool:
        if self.cadence == "event":
            return self.status == "failed"
        return self.status in {"stale", "failed"}

    def log_fields(self) -> dict[str, object]:
        return {
            "adapter_key": self.adapter_key,
            "status": self.status,
            "cadence": self.cadence,
            "source_timestamp_max": self.source_timestamp_max,
            "age_seconds": self.age_seconds,
            "max_age_seconds": self.max_age_seconds,
            "reason": self.reason,
            "checked_at": self.checked_at,
        }


def check_summary_freshness(
    summary: AdapterBatchRunSummary,
    *,
    checked_at: datetime | None = None,
    max_age_seconds: int,
) -> FreshnessCheck:
    resolved_checked_at = _aware_utc(checked_at or datetime.now(UTC))
    cadence = _cadence_for_adapter(summary.adapter_key)
    if summary.status == "failed":
        return FreshnessCheck(
            adapter_key=summary.adapter_key,
            status="failed",
            checked_at=resolved_checked_at,
            max_age_seconds=max_age_seconds,
            cadence=cadence,
            source_timestamp_max=summary.source_timestamp_max,
            reason=summary.error_message or summary.error_code or "adapter batch failed",
        )

    if summary.adapter_key == "official.ncdr.cap":
        return check_ncdr_cap_freshness(
            adapter_key=summary.adapter_key,
            effective_at=summary.source_timestamp_min,
            expires_at=summary.source_timestamp_max,
            checked_at=resolved_checked_at,
        )

    if summary.source_timestamp_max is None:
        return FreshnessCheck(
            adapter_key=summary.adapter_key,
            status="stale",
            checked_at=resolved_checked_at,
            max_age_seconds=max_age_seconds,
            cadence=cadence,
            reason="adapter batch has no source timestamp",
        )

    source_timestamp_max = _aware_utc(summary.source_timestamp_max)
    age = resolved_checked_at - source_timestamp_max
    age_seconds = max(0, int(age.total_seconds()))
    if cadence == "static":
        return FreshnessCheck(
            adapter_key=summary.adapter_key,
            status="fresh",
            checked_at=resolved_checked_at,
            max_age_seconds=max_age_seconds,
            cadence=cadence,
            source_timestamp_max=source_timestamp_max,
            age_seconds=age_seconds,
            reason="static/slow-cadence source is not evaluated against realtime thresholds",
        )

    if cadence == "realtime":
        return _realtime_freshness_check(
            summary.adapter_key,
            checked_at=resolved_checked_at,
            source_timestamp_max=source_timestamp_max,
            age_seconds=age_seconds,
        )

    if age > timedelta(seconds=max_age_seconds):
        return FreshnessCheck(
            adapter_key=summary.adapter_key,
            status="stale",
            checked_at=resolved_checked_at,
            max_age_seconds=max_age_seconds,
            cadence=cadence,
            source_timestamp_max=source_timestamp_max,
            age_seconds=age_seconds,
            reason="source data is older than freshness threshold",
        )

    return FreshnessCheck(
        adapter_key=summary.adapter_key,
        status="fresh",
        checked_at=resolved_checked_at,
        max_age_seconds=max_age_seconds,
        cadence=cadence,
        source_timestamp_max=source_timestamp_max,
        age_seconds=age_seconds,
    )


def check_batch_freshness(
    summaries: tuple[AdapterBatchRunSummary, ...],
    *,
    checked_at: datetime | None = None,
    max_age_seconds: int,
) -> tuple[FreshnessCheck, ...]:
    resolved_checked_at = checked_at or datetime.now(UTC)
    checks = tuple(
        check_summary_freshness(
            summary,
            checked_at=resolved_checked_at,
            max_age_seconds=max_age_seconds,
        )
        for summary in summaries
    )
    for check in checks:
        event_name = "freshness.alert" if check.is_alert() else "freshness.ok"
        log_event(event_name, **check.log_fields())
    return checks


def check_ncdr_cap_freshness(
    *,
    adapter_key: str,
    effective_at: datetime | None,
    expires_at: datetime | None,
    checked_at: datetime | None = None,
) -> FreshnessCheck:
    resolved_checked_at = _aware_utc(checked_at or datetime.now(UTC))
    if effective_at is None or expires_at is None:
        return FreshnessCheck(
            adapter_key=adapter_key,
            status="stale",
            checked_at=resolved_checked_at,
            max_age_seconds=0,
            cadence="event",
            reason="CAP alert is missing effective or expires timestamp",
        )

    resolved_effective_at = _aware_utc(effective_at)
    resolved_expires_at = _aware_utc(expires_at)
    max_age_seconds = max(
        0,
        int((resolved_expires_at - resolved_effective_at).total_seconds()),
    )
    age_seconds = max(
        0,
        int((resolved_checked_at - resolved_effective_at).total_seconds()),
    )
    if resolved_expires_at < resolved_checked_at:
        return FreshnessCheck(
            adapter_key=adapter_key,
            status="stale",
            checked_at=resolved_checked_at,
            max_age_seconds=max_age_seconds,
            cadence="event",
            source_timestamp_max=resolved_effective_at,
            age_seconds=age_seconds,
            reason="CAP alert expired; no active alert",
        )
    if resolved_effective_at > resolved_checked_at:
        return FreshnessCheck(
            adapter_key=adapter_key,
            status="degraded",
            checked_at=resolved_checked_at,
            max_age_seconds=max_age_seconds,
            cadence="event",
            source_timestamp_max=resolved_effective_at,
            age_seconds=0,
            reason="CAP alert is not yet effective",
        )
    return FreshnessCheck(
        adapter_key=adapter_key,
        status="fresh",
        checked_at=resolved_checked_at,
        max_age_seconds=max_age_seconds,
        cadence="event",
        source_timestamp_max=resolved_effective_at,
        age_seconds=age_seconds,
    )


def _realtime_freshness_check(
    adapter_key: str,
    *,
    checked_at: datetime,
    source_timestamp_max: datetime,
    age_seconds: int,
) -> FreshnessCheck:
    if age_seconds <= REALTIME_FRESH_SECONDS:
        status: FreshnessStatus = "fresh"
        reason = None
    elif age_seconds <= REALTIME_DEGRADED_SECONDS:
        status = "degraded"
        reason = "source data is older than fresh freshness threshold"
    elif age_seconds <= REALTIME_STALE_SECONDS:
        status = "stale"
        reason = "source data is older than stale freshness threshold"
    else:
        status = "failed"
        reason = "source data is older than failed freshness threshold"

    return FreshnessCheck(
        adapter_key=adapter_key,
        status=status,
        checked_at=checked_at,
        max_age_seconds=REALTIME_STALE_SECONDS,
        cadence="realtime",
        source_timestamp_max=source_timestamp_max,
        age_seconds=age_seconds,
        reason=reason,
    )


def _cadence_for_adapter(adapter_key: str) -> FreshnessCadence:
    if adapter_key in STATIC_SLOW_CADENCE_ADAPTER_KEYS:
        return "static"
    if adapter_key == "official.ncdr.cap":
        return "event"
    if adapter_key in REALTIME_ADAPTER_KEYS:
        return "realtime"
    return "legacy"


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
