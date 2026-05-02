from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal

from app.adapters.contracts import DataSourceAdapter
from app.adapters.registry import enabled_adapter_keys
from app.config import WorkerSettings, load_worker_settings
from app.jobs.freshness import FreshnessCheck
from app.jobs.ingestion import AdapterBatchRunSummary, IngestionRunSummaryWriter
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
    resolved_settings = settings or load_worker_settings()
    selected_adapter_keys = enabled_adapter_keys(resolved_settings)
    if not selected_adapter_keys:
        log_event("runtime.managed.ingestion.noop", reason="no_enabled_adapters")
        return ManagedRuntimeIngestionResult(status="skipped", reason="no_enabled_adapters")

    persistence = _resolve_persistence_writers(
        resolved_settings,
        database_url=database_url,
        staging_writer=staging_writer,
        run_writer=run_writer,
        promotion_writer=promotion_writer,
        promote=promote,
    )
    if persistence is None:
        log_event(
            "runtime.managed.ingestion.noop",
            reason="no_database_url",
            promote=promote,
            enabled_adapter_keys=selected_adapter_keys,
        )
        return ManagedRuntimeIngestionResult(status="skipped", reason="no_database_url")

    adapters = _resolve_adapters(
        adapter_by_key,
        settings=resolved_settings,
        adapter_builder=adapter_builder,
    )
    if adapters is None:
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
    )
    status = _status_from_cycle(
        summaries=cycle.summaries,
        freshness_checks=cycle.freshness_checks,
    )
    reason = _reason_from_cycle(
        summaries=cycle.summaries,
        missing_adapter_keys=missing_adapter_keys,
    )

    promotion = PromotionResult(promoted=0, evidence_ids=())
    if promote and cycle.summaries:
        try:
            promotion = promote_accepted_staging(
                _promotion_writer(persistence),
                limit=promotion_limit,
                adapter_keys=promotion_adapter_keys or _promotion_adapter_keys(cycle.summaries),
            )
        except Exception as exc:
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
    if not summaries:
        return "no_matching_adapters"
    if missing_adapter_keys:
        return "missing_enabled_adapters"
    return None
