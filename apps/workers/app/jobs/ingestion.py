from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from app.adapters._helpers import parse_observed_at_utc
from app.adapters.contracts import (
    AdapterRunResult,
    DataSourceAdapter,
    SnapshotGenerationMode,
    StationInventoryProof,
)
from app.adapters.registry import ADAPTER_REGISTRY, enabled_adapter_keys
from app.config import WorkerSettings
from app.logging import log_event
from app.pipelines.staging import (
    AdapterStagingBatch,
    StagingBatchWriter,
    build_staging_batch,
    persist_staging_batch,
)

AdapterBatchStatus = Literal["succeeded", "partial", "failed", "skipped"]
NCDR_CAP_ADAPTER_KEY = "official.ncdr.cap"
WARNING_EVENT_ADAPTER_KEYS = frozenset(
    {"official.cwa.heavy_rain_warning", NCDR_CAP_ADAPTER_KEY}
)
WRA_FLOOD_WARNING_ADAPTER_KEY = "official.wra.flood_warning"
# A valid empty poll is a healthy signal for these reviewed adapters only.  It is
# deliberately narrower than warning-latest retirement, which stays restricted to
# `REVIEWED_WARNING_ADAPTER_KEYS` in `app.pipelines.promotion`.
VALID_EMPTY_WARNING_ADAPTER_KEYS = frozenset(
    {*WARNING_EVENT_ADAPTER_KEYS, WRA_FLOOD_WARNING_ADAPTER_KEY}
)
COMPLETE_REPLACE_MIN_VALID_FRACTION = 0.75


@dataclass(frozen=True)
class AdapterBatchRunSummary:
    adapter_key: str
    status: AdapterBatchStatus
    started_at: datetime
    finished_at: datetime
    items_fetched: int
    items_promoted: int
    items_rejected: int
    snapshot_generation_mode: SnapshotGenerationMode | None = None
    snapshot_activation_eligible: bool = False
    raw_ref: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    source_timestamp_min: datetime | None = None
    source_timestamp_max: datetime | None = None
    station_inventory_proof: StationInventoryProof | None = None
    event_active_from_min: datetime | None = None
    event_active_until_max: datetime | None = None
    ingestion_job_id: str | None = None

    def log_fields(self) -> dict[str, object]:
        return {
            "adapter_key": self.adapter_key,
            "status": self.status,
            "items_fetched": self.items_fetched,
            "items_promoted": self.items_promoted,
            "items_rejected": self.items_rejected,
            "snapshot_generation_mode": self.snapshot_generation_mode,
            "snapshot_activation_eligible": self.snapshot_activation_eligible,
            "raw_ref": self.raw_ref,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "source_timestamp_min": self.source_timestamp_min,
            "source_timestamp_max": self.source_timestamp_max,
            "event_active_from_min": self.event_active_from_min,
            "event_active_until_max": self.event_active_until_max,
            "ingestion_job_id": self.ingestion_job_id,
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
    ) -> str | None:
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
    active_snapshot_raw_ref: str | None = None,
) -> None:
    if run_writer is None or not adapter_keys:
        return
    write_pipeline_status = getattr(run_writer, "write_pipeline_status", None)
    if callable(write_pipeline_status):
        checked_at = _now()
        arguments: dict[str, object] = {
            "adapter_keys": adapter_keys,
            "status": status,
            "complete": complete,
            "checked_at": checked_at,
            # Pre-fetch failures (for example adapter construction) have no
            # ingestion summary.  Give them a generation timestamp anyway so
            # an older overlapping cycle cannot later overwrite the fault.
            "run_at": run_at or checked_at,
        }
        if active_snapshot_raw_ref is not None:
            arguments["active_snapshot_raw_ref"] = active_snapshot_raw_ref
        write_pipeline_status(**arguments)


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
    except Exception as exc:  # noqa: BLE001 - adapter boundary records arbitrary failures
        summary = AdapterBatchRunSummary(
            adapter_key=adapter.metadata.key,
            status="failed",
            started_at=started_at,
            finished_at=_now(),
            items_fetched=0,
            items_promoted=0,
            items_rejected=0,
            snapshot_generation_mode=adapter.metadata.snapshot_generation_mode,
            error_code=exc.__class__.__name__,
            error_message=str(exc),
        )
    else:
        try:
            _validate_adapter_result_identity(adapter, result)
            summary = _summary_from_result(
                result,
                started_at=started_at,
                writer=writer,
                snapshot_generation_mode=adapter.metadata.snapshot_generation_mode,
            )
        except Exception as exc:  # noqa: BLE001 - staging boundary records arbitrary failures
            summary = AdapterBatchRunSummary(
                adapter_key=adapter.metadata.key,
                status="failed",
                started_at=started_at,
                finished_at=_now(),
                items_fetched=len(result.fetched),
                items_promoted=0,
                items_rejected=len(result.rejected),
                snapshot_generation_mode=adapter.metadata.snapshot_generation_mode,
                error_code=exc.__class__.__name__,
                error_message=str(exc),
                station_inventory_proof=result.station_inventory_proof,
            )

    if run_writer is not None:
        try:
            ingestion_job_id = run_writer.write_summary(
                summary,
                job_key=job_key,
                parameters=parameters,
            )
            if ingestion_job_id is not None:
                summary = replace(summary, ingestion_job_id=ingestion_job_id)
        except Exception as exc:  # noqa: BLE001 - audit boundary records arbitrary failures
            summary = AdapterBatchRunSummary(
                adapter_key=summary.adapter_key,
                status="failed",
                started_at=summary.started_at,
                finished_at=_now(),
                items_fetched=summary.items_fetched,
                items_promoted=summary.items_promoted,
                items_rejected=summary.items_rejected,
                snapshot_generation_mode=summary.snapshot_generation_mode,
                snapshot_activation_eligible=summary.snapshot_activation_eligible,
                raw_ref=summary.raw_ref,
                error_code=exc.__class__.__name__,
                error_message=f"run summary write failed: {exc}",
                source_timestamp_min=summary.source_timestamp_min,
                source_timestamp_max=summary.source_timestamp_max,
                station_inventory_proof=summary.station_inventory_proof,
                event_active_from_min=summary.event_active_from_min,
                event_active_until_max=summary.event_active_until_max,
                ingestion_job_id=summary.ingestion_job_id,
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
    runtime_selection_adapter_keys: tuple[str, ...] | None = None,
    write_runtime_selection_revision: bool = True,
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
    reported_keys = (
        runtime_selection_adapter_keys
        if runtime_selection_adapter_keys is not None
        else selected_keys
    )
    if write_runtime_selection_revision:
        record_runtime_selection(
            run_writer,
            enabled_adapter_keys=reported_keys,
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
    snapshot_generation_mode: SnapshotGenerationMode | None,
) -> AdapterBatchRunSummary:
    if not result.fetched:
        if result.normalized:
            raise ValueError("adapter returned normalized items without fetched raw items")
        if (
            result.adapter_key in VALID_EMPTY_WARNING_ADAPTER_KEYS
            and result.no_active_event is True
            and not result.normalized
            and not result.rejected
            and result.station_inventory_proof is None
        ):
            return AdapterBatchRunSummary(
                adapter_key=result.adapter_key,
                status="succeeded",
                started_at=started_at,
                finished_at=_now(),
                items_fetched=0,
                items_promoted=0,
                items_rejected=0,
                snapshot_generation_mode=snapshot_generation_mode,
                error_code="no_active_event",
                error_message="valid warning poll returned no active event",
                station_inventory_proof=result.station_inventory_proof,
            )
        inventory_proof = result.station_inventory_proof
        if (
            inventory_proof is not None
            and (inventory_proof.upstream_total or 0) > 0
            and inventory_proof.pagination_complete
            and inventory_proof.source_items_seen == inventory_proof.upstream_total
        ):
            return AdapterBatchRunSummary(
                adapter_key=result.adapter_key,
                status="failed",
                started_at=started_at,
                finished_at=_now(),
                items_fetched=0,
                items_promoted=0,
                items_rejected=len(result.rejected),
                snapshot_generation_mode=snapshot_generation_mode,
                error_code="upstream_observations_empty",
                error_message=(
                    "upstream returned a complete nonempty station collection "
                    "but no usable observations"
                ),
                station_inventory_proof=inventory_proof,
            )
        return AdapterBatchRunSummary(
            adapter_key=result.adapter_key,
            status="skipped",
            started_at=started_at,
            finished_at=_now(),
            items_fetched=0,
            items_promoted=0,
            items_rejected=len(result.rejected),
            snapshot_generation_mode=snapshot_generation_mode,
            error_code="empty_fetch",
            error_message="adapter returned no fetched raw items",
            station_inventory_proof=result.station_inventory_proof,
        )

    batch = build_staging_batch(
        result,
        ingestion_generation_started_at=started_at,
        snapshot_generation_mode=snapshot_generation_mode,
    )
    if writer is not None:
        persist_staging_batch(batch, writer)

    items_rejected = len(batch.rejected) + len(batch.rejected_raw_source_ids)
    status: AdapterBatchStatus = "succeeded" if items_rejected == 0 else "partial"
    source_timestamp_min = batch.raw_snapshot.source_timestamp_min
    source_timestamp_max = batch.raw_snapshot.source_timestamp_max
    finished_at = _now()
    event_active_from_min: datetime | None = None
    event_active_until_max: datetime | None = None
    warning_window = _validated_warning_active_window(
        result,
        batch,
        evaluated_at=batch.raw_snapshot.fetched_at,
    )
    if warning_window is not None:
        event_active_from_min, event_active_until_max = warning_window

    snapshot_activation_eligible = _snapshot_activation_eligible(
        batch,
        snapshot_generation_mode=snapshot_generation_mode,
    )
    cancel_only_no_active_event = _is_valid_cancel_only_no_active_result(
        result,
        batch,
        snapshot_generation_mode=snapshot_generation_mode,
        snapshot_activation_eligible=snapshot_activation_eligible,
    )

    return AdapterBatchRunSummary(
        adapter_key=result.adapter_key,
        status=status,
        started_at=started_at,
        finished_at=finished_at,
        items_fetched=len(result.fetched),
        items_promoted=len(batch.accepted),
        items_rejected=items_rejected,
        snapshot_generation_mode=snapshot_generation_mode,
        snapshot_activation_eligible=snapshot_activation_eligible,
        raw_ref=batch.raw_snapshot.raw_ref,
        error_code="no_active_event" if cancel_only_no_active_event else None,
        error_message=(
            "valid complete CAP snapshot contained cancellation lifecycle messages only"
            if cancel_only_no_active_event
            else None
        ),
        source_timestamp_min=source_timestamp_min,
        source_timestamp_max=source_timestamp_max,
        station_inventory_proof=result.station_inventory_proof,
        event_active_from_min=event_active_from_min,
        event_active_until_max=event_active_until_max,
    )


def is_successful_no_active_warning_summary(summary: AdapterBatchRunSummary) -> bool:
    """Validate the two audited shapes that may retire reviewed warning latest rows."""

    common = (
        summary.adapter_key in WARNING_EVENT_ADAPTER_KEYS
        and summary.status == "succeeded"
        and summary.error_code == "no_active_event"
        and summary.items_rejected == 0
        and summary.station_inventory_proof is None
        and summary.event_active_from_min is None
        and summary.event_active_until_max is None
    )
    if not common:
        return False
    if summary.items_fetched == 0:
        return (
            summary.items_promoted == 0
            and summary.raw_ref is None
            and summary.source_timestamp_min is None
            and summary.source_timestamp_max is None
        )
    return (
        summary.adapter_key == NCDR_CAP_ADAPTER_KEY
        and summary.items_fetched == summary.items_promoted
        and summary.items_promoted > 0
        and summary.snapshot_generation_mode == "complete_replace"
        and summary.snapshot_activation_eligible
        and summary.raw_ref is not None
        and summary.source_timestamp_min is not None
        and summary.source_timestamp_max is not None
    )


def _snapshot_activation_eligible(
    batch: AdapterStagingBatch,
    *,
    snapshot_generation_mode: SnapshotGenerationMode | None,
) -> bool:
    if snapshot_generation_mode != "complete_replace":
        return False
    if not batch.accepted or batch.rejected:
        return False
    source_outcome_count = len(batch.accepted) + len(batch.rejected_raw_source_ids)
    if source_outcome_count == 0:
        return False
    return (
        len(batch.accepted) / source_outcome_count
        >= COMPLETE_REPLACE_MIN_VALID_FRACTION
    )


def _is_valid_cancel_only_no_active_result(
    result: AdapterRunResult,
    batch: AdapterStagingBatch,
    *,
    snapshot_generation_mode: SnapshotGenerationMode | None,
    snapshot_activation_eligible: bool,
) -> bool:
    return (
        result.adapter_key == NCDR_CAP_ADAPTER_KEY
        and result.no_active_event is True
        and not result.rejected
        and not result.source_rejections
        and result.station_inventory_proof is None
        and snapshot_generation_mode == "complete_replace"
        and snapshot_activation_eligible
        and bool(batch.accepted)
        and len(result.fetched) == len(batch.accepted)
        and not batch.rejected
        and not batch.rejected_raw_source_ids
        and all(staged.payload.get("cap_message_type") == "Cancel" for staged in batch.accepted)
    )


def _validated_warning_active_window(
    result: AdapterRunResult,
    batch: AdapterStagingBatch,
    *,
    evaluated_at: datetime,
) -> tuple[datetime, datetime] | None:
    if result.adapter_key not in WARNING_EVENT_ADAPTER_KEYS:
        return None

    active_from_values: list[datetime] = []
    active_until_values: list[datetime] = []
    for staged in batch.accepted:
        if staged.payload.get("cap_message_type") not in {"Alert", "Update"}:
            continue
        active_from = parse_observed_at_utc(staged.payload.get("active_from"))
        active_until = parse_observed_at_utc(staged.payload.get("active_until"))
        if active_from is None or active_until is None or active_from >= active_until:
            continue
        if not (active_from <= evaluated_at < active_until):
            continue
        active_from_values.append(active_from)
        active_until_values.append(active_until)

    if not active_from_values or not active_until_values:
        return None
    return min(active_from_values), max(active_until_values)


def _validate_adapter_result_identity(
    adapter: DataSourceAdapter,
    result: AdapterRunResult,
) -> None:
    configured_key = adapter.metadata.key
    if result.adapter_key != configured_key:
        raise ValueError(
            "adapter result key mismatch: "
            f"configured={configured_key!r}, returned={result.adapter_key!r}"
        )
    for index, normalized in enumerate(result.normalized):
        if (
            normalized.adapter_key != configured_key
            or normalized.adapter_key != result.adapter_key
        ):
            raise ValueError(
                "normalized adapter key mismatch: "
                f"configured={configured_key!r}, "
                f"result={result.adapter_key!r}, "
                f"normalized[{index}]={normalized.adapter_key!r}"
            )


def _now() -> datetime:
    return datetime.now(UTC)
