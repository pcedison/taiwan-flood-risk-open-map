from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from app.adapters.contracts import AdapterRunResult, DataSourceAdapter
from app.logging import log_event
from app.pipelines.staging import StagingBatchWriter, build_staging_batch, persist_staging_batch


AdapterBatchStatus = Literal["succeeded", "partial", "failed", "skipped"]


@dataclass(frozen=True)
class AdapterBatchRunSummary:
    adapter_key: str
    status: AdapterBatchStatus
    started_at: datetime
    finished_at: datetime
    items_fetched: int
    items_promoted: int
    items_rejected: int
    raw_ref: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    source_timestamp_min: datetime | None = None
    source_timestamp_max: datetime | None = None

    def log_fields(self) -> dict[str, object]:
        return {
            "adapter_key": self.adapter_key,
            "status": self.status,
            "items_fetched": self.items_fetched,
            "items_promoted": self.items_promoted,
            "items_rejected": self.items_rejected,
            "raw_ref": self.raw_ref,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "source_timestamp_min": self.source_timestamp_min,
            "source_timestamp_max": self.source_timestamp_max,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


def run_adapter_batch(
    adapter: DataSourceAdapter,
    *,
    writer: StagingBatchWriter | None = None,
    job_key: str = "ingest.adapter",
) -> AdapterBatchRunSummary:
    started_at = _now()
    try:
        result = adapter.run()
    except Exception as exc:
        summary = AdapterBatchRunSummary(
            adapter_key=adapter.metadata.key,
            status="failed",
            started_at=started_at,
            finished_at=_now(),
            items_fetched=0,
            items_promoted=0,
            items_rejected=0,
            error_code=exc.__class__.__name__,
            error_message=str(exc),
        )
    else:
        try:
            summary = _summary_from_result(
                result,
                started_at=started_at,
                writer=writer,
            )
        except Exception as exc:
            summary = AdapterBatchRunSummary(
                adapter_key=result.adapter_key,
                status="failed",
                started_at=started_at,
                finished_at=_now(),
                items_fetched=len(result.fetched),
                items_promoted=0,
                items_rejected=len(result.rejected),
                error_code=exc.__class__.__name__,
                error_message=str(exc),
            )

    log_event("adapter.batch.completed", job_key=job_key, **summary.log_fields())
    return summary


def run_adapter_batches(
    adapters: Iterable[DataSourceAdapter],
    *,
    writer: StagingBatchWriter | None = None,
    job_key: str = "ingest.adapter",
) -> tuple[AdapterBatchRunSummary, ...]:
    return tuple(run_adapter_batch(adapter, writer=writer, job_key=job_key) for adapter in adapters)


def _summary_from_result(
    result: AdapterRunResult,
    *,
    started_at: datetime,
    writer: StagingBatchWriter | None,
) -> AdapterBatchRunSummary:
    if not result.fetched:
        return AdapterBatchRunSummary(
            adapter_key=result.adapter_key,
            status="skipped",
            started_at=started_at,
            finished_at=_now(),
            items_fetched=0,
            items_promoted=0,
            items_rejected=len(result.rejected),
            error_code="empty_fetch",
            error_message="adapter returned no fetched raw items",
        )

    batch = build_staging_batch(result)
    if writer is not None:
        persist_staging_batch(batch, writer)

    items_rejected = len(batch.rejected) + len(batch.rejected_raw_source_ids)
    status: AdapterBatchStatus = "succeeded" if items_rejected == 0 else "partial"
    return AdapterBatchRunSummary(
        adapter_key=result.adapter_key,
        status=status,
        started_at=started_at,
        finished_at=_now(),
        items_fetched=len(result.fetched),
        items_promoted=len(batch.accepted),
        items_rejected=items_rejected,
        raw_ref=batch.raw_snapshot.raw_ref,
        source_timestamp_min=batch.raw_snapshot.source_timestamp_min,
        source_timestamp_max=batch.raw_snapshot.source_timestamp_max,
    )


def _now() -> datetime:
    return datetime.now(UTC)
