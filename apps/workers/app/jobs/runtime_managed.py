from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Final, Literal

from app.adapters.contracts import DataSourceAdapter
from app.adapters.registry import ADAPTER_REGISTRY, enabled_adapter_keys
from app.config import WorkerSettings, load_worker_settings
from app.jobs.freshness import FreshnessCheck
from app.jobs.frozen_legacy import report_frozen_legacy
from app.jobs.ingestion import (
    AdapterBatchRunSummary,
    IngestionRunSummaryWriter,
    is_successful_no_active_warning_summary,
    record_pipeline_status,
    record_runtime_selection,
)
from app.jobs.source_catalog import (
    SourceCatalogReader,
    SourceCatalogUnavailable,
    filter_catalog_enabled_adapter_keys,
    resolve_source_catalog_reader,
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
from app.scheduler import _execute_scheduled_ingestion_cycle

ManagedRuntimeStatus = Literal["succeeded", "partial", "failed", "skipped"]
RuntimeAdapterBuilder = Callable[[WorkerSettings], Mapping[str, DataSourceAdapter]]
_TRANSIENT_PROMOTION_SQLSTATE_PREFIXES: Final[tuple[str, ...]] = ("08", "40")
_TRANSIENT_PROMOTION_SQLSTATES: Final[frozenset[str]] = frozenset(
    {"53300", "55P03", "57014", "57P01", "57P02", "57P03"}
)
_TRANSIENT_PSYCOPG_EXCEPTION_NAMES: Final[frozenset[str]] = frozenset(
    {"InterfaceError", "OperationalError"}
)
# Adapters the v1 baseline runner may execute, one isolated cycle at a time.
#
# Membership does NOT enable a source: each still needs its own runtime gates and
# an enabled persisted catalog row. Membership only means "the runner is allowed
# to consider this source". A source outside this tuple can never ingest, no
# matter how its gates or catalog row are set -- which is exactly how five
# backbone sources and thirty-five local sources went silently dark.
#
# The two non-scoring context sources are deliberately excluded. Drift is caught
# by test_v1_baseline_runner.py, which fails if a registered official/local
# adapter is missing here, forcing an explicit decision instead of silence.
V1_BASELINE_ADAPTER_KEYS: Final[tuple[str, ...]] = (
    # Official national backbone.
    "official.civil_iot.flood_sensor",
    "official.civil_iot.gate_water_level",
    "official.civil_iot.pond_water_level",
    "official.civil_iot.pump_water_level",
    "official.civil_iot.river_water_level",
    "official.civil_iot.sewer_water_level",
    "official.cwa.heavy_rain_warning",
    "official.cwa.rainfall",
    "official.cwa.tide_level",
    "official.flood_potential.geojson",
    "official.ncdr.cap",
    "official.wra.historical_flood",
    "official.wra.water_level",
    "official.wra_iow.flood_depth",
    # Local government sources. Each still has its own runtime gates and
    # persisted catalog row; scope membership only makes the source eligible.
    "local.changhua.flood_sensor",
    "local.chiayi_city.rainfall",
    "local.chiayi_city.water_level",
    "local.chiayi_county.flood_sensor",
    "local.hsinchu_city.flood_sensor",
    "local.hsinchu_city.sewer_water_level",
    "local.hsinchu_county.flood_sensor",
    "local.hualien.flood_sensor",
    "local.kaohsiung.flood_sensor",
    "local.kaohsiung.rainfall",
    "local.kaohsiung.sewer_water_level",
    "local.keelung.flood_sensor",
    "local.keelung.rainfall",
    "local.keelung.water_level",
    "local.kinmen.kwis_pump_station",
    "local.miaoli.flood_sensor",
    "local.nantou.sewer_water_level",
    "local.new_taipei.drainage_water_level",
    "local.new_taipei.flood_sensor",
    "local.new_taipei.rainfall",
    "local.new_taipei.water_level",
    "local.penghu.water_level",
    "local.pingtung.flood_sensor",
    "local.taichung.water_level",
    "local.tainan.flood_sensor",
    "local.taipei.pump_station",
    "local.taipei.river_water_level",
    "local.taipei.sewer_water_level",
    "local.taitung.flood_sensor",
    "local.taoyuan.flood_sensor",
    "local.taoyuan.rainfall",
    "local.taoyuan.water_level",
    "local.yilan.flood_sensor",
    "local.yilan.mobile_pump_status",
    "local.yilan.water_level",
    "local.yunlin.water_level",
)


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
) -> int:
    del (
        adapter_by_key,
        settings,
        database_url,
        staging_writer,
        run_writer,
        promotion_writer,
        adapter_builder,
        promote,
        promotion_limit,
        promotion_adapter_keys,
        job_key,
    )
    return report_frozen_legacy()


def run_v1_baseline_adapter_cycle(
    adapter_by_key: Mapping[str, DataSourceAdapter],
    *,
    settings: WorkerSettings,
    runtime_selection_adapter_keys: tuple[str, ...] | None = None,
    write_runtime_selection_revision: bool = True,
    database_url: str | None = None,
    staging_writer: StagingBatchWriter | None = None,
    run_writer: IngestionRunSummaryWriter | None = None,
    promotion_writer: EvidencePromotionWriter | None = None,
    source_catalog_reader: SourceCatalogReader | None = None,
    promote: bool = False,
    promotion_limit: int | None = None,
    promotion_adapter_keys: tuple[str, ...] | None = None,
    job_key: str = "runtime.v1_baseline.ingest.adapter",
) -> ManagedRuntimeIngestionResult:
    adapter_keys = tuple(adapter_by_key)
    if len(adapter_keys) != 1:
        return _invalid_v1_baseline_scope_result()
    adapter_key = adapter_keys[0]
    reporting_scope_is_valid = (
        runtime_selection_adapter_keys is None
        or (
            bool(runtime_selection_adapter_keys)
            and adapter_key in runtime_selection_adapter_keys
            and all(
                key in V1_BASELINE_ADAPTER_KEYS
                for key in runtime_selection_adapter_keys
            )
        )
    )
    if (
        adapter_key not in V1_BASELINE_ADAPTER_KEYS
        or settings.enabled_adapter_keys != (adapter_key,)
        or adapter_by_key[adapter_key].metadata.key != adapter_key
        or promotion_adapter_keys not in {None, (adapter_key,)}
        or not reporting_scope_is_valid
    ):
        return _invalid_v1_baseline_scope_result()
    return _execute_managed_runtime_ingestion_cycle(
        adapter_by_key,
        settings=settings,
        runtime_selection_adapter_keys=runtime_selection_adapter_keys,
        write_runtime_selection_revision=write_runtime_selection_revision,
        database_url=database_url,
        staging_writer=staging_writer,
        run_writer=run_writer,
        promotion_writer=promotion_writer,
        source_catalog_reader=source_catalog_reader,
        promote=promote,
        promotion_limit=promotion_limit,
        promotion_adapter_keys=promotion_adapter_keys,
        job_key=job_key,
    )


def _invalid_v1_baseline_scope_result() -> ManagedRuntimeIngestionResult:
    return ManagedRuntimeIngestionResult(
        status="failed",
        reason="invalid_v1_baseline_scope",
        error_code="invalid_v1_baseline_scope",
    )


def _execute_managed_runtime_ingestion_cycle(
    adapter_by_key: Mapping[str, DataSourceAdapter] | None = None,
    *,
    settings: WorkerSettings | None = None,
    runtime_selection_adapter_keys: tuple[str, ...] | None = None,
    write_runtime_selection_revision: bool = True,
    database_url: str | None = None,
    staging_writer: StagingBatchWriter | None = None,
    run_writer: IngestionRunSummaryWriter | None = None,
    promotion_writer: EvidencePromotionWriter | None = None,
    adapter_builder: RuntimeAdapterBuilder | None = None,
    source_catalog_reader: SourceCatalogReader | None = None,
    promote: bool = False,
    promotion_limit: int | None = None,
    promotion_adapter_keys: tuple[str, ...] | None = None,
    job_key: str = "runtime.managed.ingest.enabled_adapters",
) -> ManagedRuntimeIngestionResult:
    cycle_started_at = datetime.now(UTC)
    resolved_settings = settings or load_worker_settings()
    selected_adapter_keys = enabled_adapter_keys(resolved_settings)
    reported_adapter_keys = (
        runtime_selection_adapter_keys
        if runtime_selection_adapter_keys is not None
        else selected_adapter_keys
    )
    runtime_status_writer = _resolve_runtime_status_writer(
        resolved_settings,
        database_url=database_url,
        run_writer=run_writer,
    )
    if not selected_adapter_keys:
        _write_runtime_selection_revision(
            runtime_status_writer,
            enabled_adapter_keys=reported_adapter_keys,
            enabled=write_runtime_selection_revision,
        )
        log_event("runtime.managed.ingestion.noop", reason="no_enabled_adapters")
        return ManagedRuntimeIngestionResult(status="skipped", reason="no_enabled_adapters")

    resolved_catalog_reader = resolve_source_catalog_reader(
        database_url=database_url or resolved_settings.database_url,
        source_catalog_reader=source_catalog_reader,
    )
    if resolved_catalog_reader is not None:
        try:
            selected_adapter_keys = filter_catalog_enabled_adapter_keys(
                selected_adapter_keys,
                source_catalog_reader=resolved_catalog_reader,
            )
        except SourceCatalogUnavailable:
            _record_source_catalog_unavailable_audit(
                runtime_status_writer,
                adapter_keys=selected_adapter_keys,
                run_at=cycle_started_at,
                write_runtime_selection_revision=write_runtime_selection_revision,
            )
            log_event("runtime.source_catalog.unavailable")
            return ManagedRuntimeIngestionResult(
                status="failed",
                reason="source_catalog_unavailable",
                error_code="source_catalog_unavailable",
            )

    if not selected_adapter_keys:
        _write_runtime_selection_revision(
            runtime_status_writer,
            enabled_adapter_keys=reported_adapter_keys,
            enabled=write_runtime_selection_revision,
        )
        log_event("runtime.source_catalog.disabled")
        return ManagedRuntimeIngestionResult(status="skipped", reason="source_catalog_disabled")

    resolved_settings = replace(
        resolved_settings,
        enabled_adapter_keys=selected_adapter_keys,
    )
    if promotion_adapter_keys is not None:
        promotion_adapter_keys = tuple(
            key for key in promotion_adapter_keys if key in selected_adapter_keys
        )

    persistence = _resolve_persistence_writers(
        resolved_settings,
        database_url=database_url,
        staging_writer=staging_writer,
        run_writer=runtime_status_writer,
        promotion_writer=promotion_writer,
        promote=promote,
    )
    if persistence is None:
        _write_runtime_selection_revision(
            runtime_status_writer,
            enabled_adapter_keys=reported_adapter_keys,
            enabled=write_runtime_selection_revision,
        )
        log_event(
            "runtime.managed.ingestion.noop",
            reason="no_database_url",
            promote=promote,
            enabled_adapter_keys=selected_adapter_keys,
        )
        return ManagedRuntimeIngestionResult(status="skipped", reason="no_database_url")

    _write_runtime_selection_revision(
        persistence.run_writer,
        enabled_adapter_keys=reported_adapter_keys,
        enabled=write_runtime_selection_revision,
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

    cycle = _execute_scheduled_ingestion_cycle(
        adapters,
        settings=resolved_settings,
        runtime_selection_adapter_keys=reported_adapter_keys,
        write_runtime_selection_revision=False,
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
        target_adapter_keys = (
            promotion_adapter_keys
            if promotion_adapter_keys is not None
            else _promotion_adapter_keys(cycle.summaries)
        )
        if not target_adapter_keys:
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
        promotion_writer_instance = _promotion_writer(persistence)
        no_active_summaries = tuple(
            summary
            for summary in cycle.summaries
            if is_successful_no_active_warning_summary(summary)
        )
        try:
            for summary in no_active_summaries:
                promotion_writer_instance.retire_warning_latest_for_no_active_event(
                    adapter_key=summary.adapter_key,
                    generation_started_at=summary.started_at,
                    completed_at=summary.finished_at,
                )
        except Exception as exc:  # noqa: BLE001 - persist retirement failure as managed state
            _record_pipeline_status_for_adapter_keys(
                persistence.run_writer,
                adapter_keys=tuple(summary.adapter_key for summary in no_active_summaries),
                summaries=cycle.summaries,
                status="failed",
                complete=False,
            )
            log_event(
                "runtime.managed.no_active_event_retirement.failed",
                error_code=exc.__class__.__name__,
            )
            return ManagedRuntimeIngestionResult(
                status="failed",
                reason="no_active_event_retirement_failed",
                summaries=cycle.summaries,
                freshness_checks=cycle.freshness_checks,
                error_code=exc.__class__.__name__,
                error_message=str(exc),
            )
        try:
            current_raw_refs = tuple(
                dict.fromkeys(
                    summary.raw_ref
                    for summary in cycle.summaries
                    if summary.adapter_key in target_adapter_keys
                    and summary.status in {"succeeded", "partial"}
                    and summary.raw_ref is not None
                )
            )
            if current_raw_refs:
                promotion = _promote_accepted_staging_with_retry(
                    promotion_writer_instance,
                    limit=promotion_limit,
                    adapter_keys=target_adapter_keys,
                    raw_refs=current_raw_refs,
                )
        except Exception as exc:  # noqa: BLE001 - persist adapter failure as a managed result
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


def _promote_accepted_staging_with_retry(
    writer: EvidencePromotionWriter,
    *,
    limit: int | None,
    adapter_keys: tuple[str, ...],
    raw_refs: tuple[str, ...],
) -> PromotionResult:
    try:
        return promote_accepted_staging(
            writer,
            limit=limit,
            adapter_keys=adapter_keys,
            raw_refs=raw_refs,
        )
    except Exception as exc:
        if not _is_transient_promotion_error(exc):
            raise
        log_event(
            "runtime.managed.promotion.retrying",
            attempt=2,
            max_attempts=2,
            error_code=exc.__class__.__name__,
        )
    return promote_accepted_staging(
        writer,
        limit=limit,
        adapter_keys=adapter_keys,
        raw_refs=raw_refs,
    )


def _is_transient_promotion_error(exc: BaseException) -> bool:
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        sqlstate = getattr(current, "sqlstate", None)
        if isinstance(sqlstate, str) and (
            sqlstate in _TRANSIENT_PROMOTION_SQLSTATES
            or sqlstate.startswith(_TRANSIENT_PROMOTION_SQLSTATE_PREFIXES)
        ):
            return True
        exception_type = type(current)
        if (
            exception_type.__module__.startswith("psycopg")
            and exception_type.__name__ in _TRANSIENT_PSYCOPG_EXCEPTION_NAMES
        ):
            return True
        current = current.__cause__ or current.__context__
    return False


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
        staging_writer is None or run_writer is None or (promote and promotion_writer is None)
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
            PostgresEvidencePromotionWriter(database_url=resolved_database_url) if promote else None
        )
    )

    return _ManagedPersistenceWriters(
        staging_writer=resolved_staging_writer,
        run_writer=resolved_run_writer,
        promotion_writer=resolved_promotion_writer,
    )


def _write_runtime_selection_revision(
    run_writer: IngestionRunSummaryWriter | None,
    *,
    enabled_adapter_keys: tuple[str, ...],
    enabled: bool,
) -> None:
    if not enabled:
        return
    record_runtime_selection(
        run_writer,
        enabled_adapter_keys=enabled_adapter_keys,
        known_adapter_keys=tuple(ADAPTER_REGISTRY),
    )


def _record_source_catalog_unavailable_audit(
    run_writer: IngestionRunSummaryWriter | None,
    *,
    adapter_keys: tuple[str, ...],
    run_at: datetime,
    write_runtime_selection_revision: bool = True,
) -> None:
    try:
        _write_runtime_selection_revision(
            run_writer,
            enabled_adapter_keys=adapter_keys,
            enabled=write_runtime_selection_revision,
        )
        record_pipeline_status(
            run_writer,
            adapter_keys=adapter_keys,
            status="failed",
            complete=False,
            run_at=run_at,
        )
    except Exception:  # noqa: BLE001 - preserve the catalog failure boundary
        log_event("runtime.source_catalog.audit_unavailable", status="failed")


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
        active_snapshot_raw_ref = (
            summary.raw_ref
            if (
                status == "succeeded"
                and complete
                and summary is not None
                and summary.status in {"succeeded", "partial"}
                and summary.snapshot_generation_mode == "complete_replace"
                and summary.snapshot_activation_eligible
                and summary.raw_ref is not None
            )
            else None
        )
        record_pipeline_status(
            run_writer,
            adapter_keys=(adapter_key,),
            status=status,
            complete=complete,
            run_at=summary.started_at if summary is not None else None,
            active_snapshot_raw_ref=active_snapshot_raw_ref,
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
