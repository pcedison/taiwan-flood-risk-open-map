from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from app.jobs.ingestion import AdapterBatchRunSummary
from app.logging import log_event


FreshnessStatus = Literal["fresh", "stale", "failed"]


@dataclass(frozen=True)
class FreshnessCheck:
    adapter_key: str
    status: FreshnessStatus
    checked_at: datetime
    max_age_seconds: int
    source_timestamp_max: datetime | None = None
    age_seconds: int | None = None
    reason: str | None = None

    def is_alert(self) -> bool:
        return self.status in {"stale", "failed"}

    def log_fields(self) -> dict[str, object]:
        return {
            "adapter_key": self.adapter_key,
            "status": self.status,
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
    if summary.status == "failed":
        return FreshnessCheck(
            adapter_key=summary.adapter_key,
            status="failed",
            checked_at=resolved_checked_at,
            max_age_seconds=max_age_seconds,
            source_timestamp_max=summary.source_timestamp_max,
            reason=summary.error_message or summary.error_code or "adapter batch failed",
        )

    if summary.source_timestamp_max is None:
        return FreshnessCheck(
            adapter_key=summary.adapter_key,
            status="stale",
            checked_at=resolved_checked_at,
            max_age_seconds=max_age_seconds,
            reason="adapter batch has no source timestamp",
        )

    source_timestamp_max = _aware_utc(summary.source_timestamp_max)
    age = resolved_checked_at - source_timestamp_max
    age_seconds = max(0, int(age.total_seconds()))
    if age > timedelta(seconds=max_age_seconds):
        return FreshnessCheck(
            adapter_key=summary.adapter_key,
            status="stale",
            checked_at=resolved_checked_at,
            max_age_seconds=max_age_seconds,
            source_timestamp_max=source_timestamp_max,
            age_seconds=age_seconds,
            reason="source data is older than freshness threshold",
        )

    return FreshnessCheck(
        adapter_key=summary.adapter_key,
        status="fresh",
        checked_at=resolved_checked_at,
        max_age_seconds=max_age_seconds,
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


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
