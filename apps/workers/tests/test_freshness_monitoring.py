from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.jobs.freshness import check_batch_freshness, check_summary_freshness
from app.jobs.ingestion import AdapterBatchRunSummary, AdapterBatchStatus


CHECKED_AT = datetime(2026, 4, 30, 4, 0, tzinfo=UTC)


def test_freshness_check_marks_recent_source_timestamp_fresh() -> None:
    check = check_summary_freshness(
        _summary(source_timestamp_max=CHECKED_AT - timedelta(minutes=15)),
        checked_at=CHECKED_AT,
        max_age_seconds=60 * 60,
    )

    assert check.status == "fresh"
    assert check.age_seconds == 15 * 60
    assert not check.is_alert()


def test_freshness_check_marks_old_source_timestamp_stale() -> None:
    check = check_summary_freshness(
        _summary(source_timestamp_max=CHECKED_AT - timedelta(hours=7)),
        checked_at=CHECKED_AT,
        max_age_seconds=6 * 60 * 60,
    )

    assert check.status == "stale"
    assert check.reason == "source data is older than freshness threshold"
    assert check.is_alert()


def test_freshness_check_marks_failed_batch_failed() -> None:
    check = check_summary_freshness(
        _summary(status="failed", error_message="fetch failed"),
        checked_at=CHECKED_AT,
        max_age_seconds=6 * 60 * 60,
    )

    assert check.status == "failed"
    assert check.reason == "fetch failed"
    assert check.is_alert()


def test_batch_freshness_checks_each_summary() -> None:
    checks = check_batch_freshness(
        (
            _summary(adapter_key="official.cwa.rainfall"),
            _summary(adapter_key="official.wra.water_level", status="failed"),
        ),
        checked_at=CHECKED_AT,
        max_age_seconds=6 * 60 * 60,
    )

    assert [check.status for check in checks] == ["fresh", "failed"]


def _summary(
    *,
    adapter_key: str = "official.cwa.rainfall",
    status: AdapterBatchStatus = "succeeded",
    source_timestamp_max: datetime | None = CHECKED_AT,
    error_message: str | None = None,
) -> AdapterBatchRunSummary:
    return AdapterBatchRunSummary(
        adapter_key=adapter_key,
        status=status,
        started_at=CHECKED_AT,
        finished_at=CHECKED_AT,
        items_fetched=1,
        items_promoted=1,
        items_rejected=0,
        error_message=error_message,
        source_timestamp_max=source_timestamp_max,
    )
