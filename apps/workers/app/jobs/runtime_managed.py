from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from app.adapters.contracts import DataSourceAdapter
from app.adapters.registry import ADAPTER_REGISTRY, enabled_adapter_keys
from app.config import WorkerSettings, load_worker_settings
from app.jobs.freshness import FreshnessCheck
from app.jobs.ingestion import (
    AdapterBatchRunSummary,
    IngestionRunSummaryWriter,
    record_pipeline_status,
    record_runtime_selection,
)
from app.logging import log_event
from app.pipelines.ingestion_runs import PostgresIngestionRunWriter
from app.pipelines.postgres_writer import PostgresStagingBatchWriter
from app.pipelines.promotion import (
    EvidencePromotionWriter,
    PostgresEvidencePromotionWriter,
    PromotionResult,
    promote_accepted_staging,
)
from app.pipelines.staging import StagingBatchWriter
from app.scheduler import run_scheduled_ingestion_cycle


ManagedRuntimeStatus = Literal["succeeded", "partial", "failed", "skipped"]
RuntimeAdapterBuilder = Callable[[WorkerSettings], Mapping[str, DataSourceAdapter]]


@dataclass(frozen=True)
class ManagedRuntimeIngestionResult:
    status: ManagedRuntimeStatus
    reason: str | None = None
    summaries: tuple[AdapterBatchRunSummary, ...] = ()
    freshness_checks: tuple[FreshnessCheck, ...] = ()
    promoted: int = 0
    evidence_ids: tuple[str, ...] = ()
    error_code: str | None = None
    error_message: str | None = None

    @property
    def has_alerts(self) -> bool:
        return any(check.is_alert() for check in self.freshness_checks)

    @property
    def failed(self) -> bool:
        return self.status == "failed"


@dataclass(frozen=True)
class _ManagedPersistenceWriters:
    staging_writer: StagingBatchWriter
    run_writer: IngestionRunSummaryWriter
    promotion_writer: EvidencePromotionWriter | None


def run_managed_runtime_ingestion_cycle(
    adapter_by_key: Mapping[str, DataSourceAdapter] | None = None,
    *,
    settings: WorkerSettings | None = None,
    database_url: str | None = None,
    staging_writer: StagingBatchWriter | None = None,
    run_writer: IngestionRunSummaryWriter | None = None,
    promotion_writer: EvidencePromotionWriter | None = None,
    adapter_builder: RuntimeAdapterBuilder | None = None,
    promote: bool = False,
    promotion_limit: int | None = None,
    promotion_adapter_keys: tuple[str, ...] | None = None,
    job_key: str = "runtime.managed.ingest.enabled_adapters",
) -> ManagedRuntimeIngestionResult:
    cycle_started_at = datetime.now(UTC)
    resolved_settings = settings or load_worker_settings()
    selected_adapter_keys = enabled_adapter_keys(resolved_settings)
    runtime_status_writer = _resolve_runtime_status_writer(
        resolved_settings,
        database_url=database_url,
        run_writer=run_writer,
    )
    if not selected_adapter_keys:
        record_runtime_selection(
            runtime_status_writer,
            enabled_adapter_keys=(),
            known_adapter_keys=tuple(ADAPTER_REGISTRY),
        )
        log_event("runtime.managed.ingestion.noop", reason="no_enabled_adapters")
        return ManagedRuntimeIngestionResult(status="skipped", reason="no_enabled_adapters")

    persistence = _resolve_persistence_writers(
        resolved_settings,
        database_url=database_url,
        staging_writer=staging_writer,
        run_writer=runtime_status_writer,
        promotion_writer=promotion_writer,
        promote=promote,
    )
    if persistence is None:
        record_runtime_selection(
            runtime_status_writer,
            enabled_adapter_keys=selected_adapter_keys,
            known_adapter_keys=tuple(ADAPTER_REGISTRY),
        )
        log_event(
            "runtime.managed.ingestion.noop",
            reason="no_database_url",
            promote=promote,
            enabled_adapter_keys=selected_adapter_keys,
        )
        return ManagedRuntimeIngestionResult(status="skipped", reason="no_database_url")

    record_runtime_selection(
        persistence.run_writer,
        enabled_adapter_keys=selected_adapter_keys,
        known_adapter_keys=tuple(ADAPTER_REGISTRY),
    )
    try:
        adapters = _resolve_adapters(
            adapter_by_key,
            settings=resolved_settings,
            adapter_builder=adapter_builder,
        )
    except Exception as exc:
        record_pipeline_status(
            persistence.run_writer,
            adapter_keys=selected_adapter_keys,
            status="failed",
            complete=False,
            run_at=cycle_started_at,
        )
        log_event(
            "runtime.managed.adapter_initialization.failed",
            error_code=exc.__class__.__name__,
        )
        raise
    if adapters is None:
        record_pipeline_status(
            persistence.run_writer,
            adapter_keys=selected_adapter_keys,
            status="failed",
            complete=False,
            run_at=cycle_started_at,
        )
        log_event(
            "runtime.managed.ingestion.noop",
            reason="no_adapters",
            enabled_adapter_keys=selected_adapter_keys,
        )
        return ManagedRuntimeIngestionResult(status="skipped", reason="no_adapters")

    missing_adapter_keys = tuple(key for key in selected_adapter_keys if key not in adapters)
    if missing_adapter_keys:
        log_event(
            "runtime.managed.ingestion.partial_runtime",
            missing_adapter_keys=missing_adapter_keys,
            available_adapter_keys=tuple(adapters),
        )

    cycle = run_scheduled_ingestion_cycle(
        adapters,
        settings=resolved_settings,
        job_key=job_key,
        writer=persistence.staging_writer,
        run_writer=persistence.run_writer,
        pipeline_run_at=cycle_started_at,
    )
    status = _status_from_cycle(
        summaries=cycle.summaries,
        freshness_checks=cycle.freshness_checks,
    )
    reason = _reason_from_cycle(
        summaries=cycle.summaries,
        missing_adapter_keys=missing_adapter_keys,
    )
    if missing_adapter_keys:
        status = "failed"

    promotion = PromotionResult(promoted=0, evidence_ids=())
    if promote and cycle.summaries:
        target_adapter_keys = promotion_adapter_keys or _promotion_adapter_keys(cycle.summaries)
        try:
            promotion = promote_accepted_staging(
                _promotion_writer(persistence),
                limit=promotion_limit,
                adapter_keys=target_adapter_keys,
            )
        except Exception as exc:
            _record_pipeline_status_for_adapter_keys(
                persistence.run_writer,
                adapter_keys=target_adapter_keys,
                summaries=cycle.summaries,
                status="failed",
                complete=False,
            )
            log_event(
                "runtime.managed.promotion.failed",
                error_code=exc.__class__.__name__,
                error_message=str(exc),
            )
            return ManagedRuntimeIngestionResult(
                status="failed",
                reason="promotion_failed",
                summaries=cycle.summaries,
                freshness_checks=cycle.freshness_checks,
                error_code=exc.__class__.__name__,
                error_message=str(exc),
            )
        _record_pipeline_status_for_adapter_keys(
            persistence.run_writer,
            adapter_keys=target_adapter_keys,
            summaries=cycle.summaries,
            status="succeeded",
            complete=promotion_limit is None,
        )

    log_event(
        "runtime.managed.ingestion.completed",
        status=status,
        reason=reason,
        adapter_count=len(cycle.summaries),
        promoted=promotion.promoted,
    )
    return ManagedRuntimeIngestionResult(
        status=status,
        reason=reason,
        summaries=cycle.summaries,
        freshness_checks=cycle.freshness_checks,
        promoted=promotion.promoted,
        evidence_ids=promotion.evidence_ids,
    )


def _resolve_persistence_writers(
    settings: WorkerSettings,
    *,
    database_url: str | None,
    staging_writer: StagingBatchWriter | None,
    run_writer: IngestionRunSummaryWriter | None,
    promotion_writer: EvidencePromotionWriter | None,
    promote: bool,
) -> _ManagedPersistenceWriters | None:
    resolved_database_url = database_url or settings.database_url
    needs_database_url = (
        staging_writer is None
        or run_writer is None
        or (promote and promotion_writer is None)
    )
    if needs_database_url and not resolved_database_url:
        return None

    resolved_staging_writer = (
        staging_writer
        if staging_writer is not None
        else PostgresStagingBatchWriter(database_url=resolved_database_url)
    )
    resolved_run_writer = (
        run_writer
        if run_writer is not None
        else PostgresIngestionRunWriter(database_url=resolved_database_url)
    )
    resolved_promotion_writer = (
        promotion_writer
        if promotion_writer is not None
        else (
            PostgresEvidencePromotionWriter(database_url=resolved_database_url)
            if promote
            else None
        )
    )

    return _ManagedPersistenceWriters(
        staging_writer=resolved_staging_writer,
        run_writer=resolved_run_writer,
        promotion_writer=resolved_promotion_writer,
    )


def _resolve_runtime_status_writer(
    settings: WorkerSettings,
    *,
    database_url: str | None,
    run_writer: IngestionRunSummaryWriter | None,
) -> IngestionRunSummaryWriter | None:
    if run_writer is not None:
        return run_writer
    resolved_database_url = database_url or settings.database_url
    if not resolved_database_url:
        return None
    return PostgresIngestionRunWriter(database_url=resolved_database_url)


def _resolve_adapters(
    adapter_by_key: Mapping[str, DataSourceAdapter] | None,
    *,
    settings: WorkerSettings,
    adapter_builder: RuntimeAdapterBuilder | None,
) -> Mapping[str, DataSourceAdapter] | None:
    if adapter_by_key is not None:
        return adapter_by_key
    if adapter_builder is None:
        return None
    return adapter_builder(settings)


def _promotion_writer(persistence: _ManagedPersistenceWriters) -> EvidencePromotionWriter:
    if persistence.promotion_writer is None:
        raise RuntimeError("promotion writer is required when promote=True")
    return persistence.promotion_writer


def _promotion_adapter_keys(
    summaries: tuple[AdapterBatchRunSummary, ...],
) -> tuple[str, ...]:
    return tuple(dict.fromkeys(summary.adapter_key for summary in summaries))


def _record_pipeline_status_for_adapter_keys(
    run_writer: IngestionRunSummaryWriter,
    *,
    adapter_keys: tuple[str, ...],
    summaries: tuple[AdapterBatchRunSummary, ...],
    status: Literal["succeeded", "failed"],
    complete: bool,
) -> None:
    summary_by_key = {summary.adapter_key: summary for summary in summaries}
    for adapter_key in adapter_keys:
        summary = summary_by_key.get(adapter_key)
        record_pipeline_status(
            run_writer,
            adapter_keys=(adapter_key,),
            status=status,
            complete=complete,
            run_at=summary.started_at if summary is not None else None,
        )


def _status_from_cycle(
    *,
    summaries: tuple[AdapterBatchRunSummary, ...],
    freshness_checks: tuple[FreshnessCheck, ...],
) -> ManagedRuntimeStatus:
    if not summaries:
        return "skipped"
    if any(summary.status == "failed" for summary in summaries):
        return "failed"
    if any(check.is_alert() for check in freshness_checks):
        return "failed"
    if any(summary.status in {"partial", "skipped"} for summary in summaries):
        return "partial"
    return "succeeded"


def _reason_from_cycle(
    *,
    summaries: tuple[AdapterBatchRunSummary, ...],
    missing_adapter_keys: tuple[str, ...],
) -> str | None:
    if missing_adapter_keys:
        return "missing_enabled_adapters"
    if not summaries:
        return "no_matching_adapters"
    return None
