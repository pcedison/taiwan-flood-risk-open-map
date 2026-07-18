from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from app.adapters._helpers import parse_observed_at_utc
from app.adapters.registry import ADAPTER_REGISTRY, enabled_adapter_keys
from app.config import WorkerSettings
from app.adapters.contracts import AdapterRunResult, DataSourceAdapter, StationInventoryProof
from app.logging import log_event
from app.pipelines.staging import StagingBatchWriter, build_staging_batch, persist_staging_batch


AdapterBatchStatus = Literal["succeeded", "partial", "failed", "skipped"]
NCDR_CAP_ADAPTER_KEY = "official.ncdr.cap"


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
    station_inventory_proof: StationInventoryProof | None = None

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
            "station_inventory_proof": (
                self.station_inventory_proof.public_summary()
                if self.station_inventory_proof is not None
                else None
            ),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


class IngestionRunSummaryWriter(Protocol):
    def write_summary(
        self,
        summary: AdapterBatchRunSummary,
        *,
        job_key: str,
        parameters: dict[str, Any] | None = None,
    ) -> None:
        """Persist an operational audit row for an adapter batch run."""


def record_runtime_selection(
    run_writer: IngestionRunSummaryWriter | None,
    *,
    enabled_adapter_keys: tuple[str, ...],
    known_adapter_keys: tuple[str, ...],
) -> None:
    if run_writer is None:
        return
    write_runtime_selection = getattr(run_writer, "write_runtime_selection", None)
    if callable(write_runtime_selection):
        write_runtime_selection(
            enabled_adapter_keys=enabled_adapter_keys,
            known_adapter_keys=known_adapter_keys,
            checked_at=_now(),
        )


def record_pipeline_status(
    run_writer: IngestionRunSummaryWriter | None,
    *,
    adapter_keys: tuple[str, ...],
    status: Literal["succeeded", "failed"],
    complete: bool,
    run_at: datetime | None = None,
) -> None:
    if run_writer is None or not adapter_keys:
        return
    write_pipeline_status = getattr(run_writer, "write_pipeline_status", None)
    if callable(write_pipeline_status):
        checked_at = _now()
        write_pipeline_status(
            adapter_keys=adapter_keys,
            status=status,
            complete=complete,
            checked_at=checked_at,
            # Pre-fetch failures (for example adapter construction) have no
            # ingestion summary.  Give them a generation timestamp anyway so
            # an older overlapping cycle cannot later overwrite the fault.
            run_at=run_at or checked_at,
        )


def run_adapter_batch(
    adapter: DataSourceAdapter,
    *,
    writer: StagingBatchWriter | None = None,
    run_writer: IngestionRunSummaryWriter | None = None,
    job_key: str = "ingest.adapter",
    parameters: dict[str, Any] | None = None,
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
                station_inventory_proof=result.station_inventory_proof,
            )

    if run_writer is not None:
        try:
            run_writer.write_summary(summary, job_key=job_key, parameters=parameters)
        except Exception as exc:
            summary = AdapterBatchRunSummary(
                adapter_key=summary.adapter_key,
                status="failed",
                started_at=summary.started_at,
                finished_at=_now(),
                items_fetched=summary.items_fetched,
                items_promoted=summary.items_promoted,
                items_rejected=summary.items_rejected,
                raw_ref=summary.raw_ref,
                error_code=exc.__class__.__name__,
                error_message=f"run summary write failed: {exc}",
                source_timestamp_min=summary.source_timestamp_min,
                source_timestamp_max=summary.source_timestamp_max,
                station_inventory_proof=summary.station_inventory_proof,
            )

    log_event("adapter.batch.completed", job_key=job_key, **summary.log_fields())
    return summary


def run_adapter_batches(
    adapters: Iterable[DataSourceAdapter],
    *,
    writer: StagingBatchWriter | None = None,
    run_writer: IngestionRunSummaryWriter | None = None,
    job_key: str = "ingest.adapter",
    parameters: dict[str, Any] | None = None,
) -> tuple[AdapterBatchRunSummary, ...]:
    return tuple(
        run_adapter_batch(
            adapter,
            writer=writer,
            run_writer=run_writer,
            job_key=job_key,
            parameters=parameters,
        )
        for adapter in adapters
    )


def run_enabled_adapter_batches(
    adapter_by_key: Mapping[str, DataSourceAdapter],
    *,
    settings: WorkerSettings | None = None,
    writer: StagingBatchWriter | None = None,
    run_writer: IngestionRunSummaryWriter | None = None,
    job_key: str = "ingest.enabled_adapters",
    parameters: dict[str, Any] | None = None,
    pipeline_run_at: datetime | None = None,
) -> tuple[AdapterBatchRunSummary, ...]:
    selected_keys = enabled_adapter_keys(settings)
    selected_adapters = tuple(
        adapter_by_key[key]
        for key in selected_keys
        if key in adapter_by_key
    )
    record_runtime_selection(
        run_writer,
        enabled_adapter_keys=selected_keys,
        known_adapter_keys=tuple(ADAPTER_REGISTRY),
    )
    missing_adapter_keys = tuple(key for key in selected_keys if key not in adapter_by_key)
    record_pipeline_status(
        run_writer,
        adapter_keys=missing_adapter_keys,
        status="failed",
        complete=False,
        run_at=pipeline_run_at,
    )
    return run_adapter_batches(
        selected_adapters,
        writer=writer,
        run_writer=run_writer,
        job_key=job_key,
        parameters={
            **(parameters or {}),
            "enabled_adapter_keys": selected_keys,
            "available_adapter_keys": tuple(adapter_by_key),
        },
    )


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
            station_inventory_proof=result.station_inventory_proof,
        )

    batch = build_staging_batch(result)
    if writer is not None:
        persist_staging_batch(batch, writer)

    items_rejected = len(batch.rejected) + len(batch.rejected_raw_source_ids)
    status: AdapterBatchStatus = "succeeded" if items_rejected == 0 else "partial"
    source_timestamp_min = batch.raw_snapshot.source_timestamp_min
    source_timestamp_max = batch.raw_snapshot.source_timestamp_max
    if result.adapter_key == NCDR_CAP_ADAPTER_KEY:
        cap_window = _ncdr_cap_effective_expires_window(result)
        if cap_window is not None:
            source_timestamp_min, source_timestamp_max = cap_window

    return AdapterBatchRunSummary(
        adapter_key=result.adapter_key,
        status=status,
        started_at=started_at,
        finished_at=_now(),
        items_fetched=len(result.fetched),
        items_promoted=len(batch.accepted),
        items_rejected=items_rejected,
        raw_ref=batch.raw_snapshot.raw_ref,
        source_timestamp_min=source_timestamp_min,
        source_timestamp_max=source_timestamp_max,
        station_inventory_proof=result.station_inventory_proof,
    )


def _ncdr_cap_effective_expires_window(
    result: AdapterRunResult,
) -> tuple[datetime, datetime] | None:
    if result.adapter_key != NCDR_CAP_ADAPTER_KEY:
        return None

    effective_values: list[datetime] = []
    expires_values: list[datetime] = []
    for raw_item in result.fetched:
        effective_at = parse_observed_at_utc(raw_item.payload.get("effective"))
        expires_at = parse_observed_at_utc(raw_item.payload.get("expires"))
        if effective_at is None or expires_at is None:
            continue
        effective_values.append(effective_at)
        expires_values.append(expires_at)

    if not effective_values or not expires_values:
        return None
    return min(effective_values), max(expires_values)


def _now() -> datetime:
    return datetime.now(UTC)
