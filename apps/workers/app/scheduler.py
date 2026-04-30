from __future__ import annotations

import argparse
import time
from collections.abc import Mapping
from dataclasses import dataclass

from app.adapters.registry import enabled_adapter_keys
from app.config import load_worker_settings
from app.adapters.contracts import DataSourceAdapter
from app.jobs.freshness import FreshnessCheck, check_batch_freshness
from app.jobs.ingestion import (
    AdapterBatchRunSummary,
    IngestionRunSummaryWriter,
    run_enabled_adapter_batches,
)
from app.jobs.official_demo import build_official_demo_adapters
from app.jobs.sample import run_sample_job
from app.logging import log_event
from app.pipelines.staging import StagingBatchWriter


@dataclass(frozen=True)
class ScheduledIngestionCycleResult:
    summaries: tuple[AdapterBatchRunSummary, ...]
    freshness_checks: tuple[FreshnessCheck, ...]

    @property
    def has_alerts(self) -> bool:
        return any(check.is_alert() for check in self.freshness_checks)


def run_scheduled_ingestion_cycle(
    adapter_by_key: Mapping[str, DataSourceAdapter],
    *,
    settings=None,
    job_key: str = "scheduler.ingest.enabled_adapters",
    writer: StagingBatchWriter | None = None,
    run_writer: IngestionRunSummaryWriter | None = None,
) -> ScheduledIngestionCycleResult:
    resolved_settings = settings or load_worker_settings()
    summaries = run_enabled_adapter_batches(
        adapter_by_key,
        settings=resolved_settings,
        writer=writer,
        run_writer=run_writer,
        job_key=job_key,
    )
    freshness_checks = check_batch_freshness(
        summaries,
        max_age_seconds=resolved_settings.freshness_max_age_seconds,
    )
    log_event(
        "scheduler.ingestion_cycle.completed",
        job_key=job_key,
        adapter_count=len(summaries),
        alert_count=sum(1 for check in freshness_checks if check.is_alert()),
    )
    return ScheduledIngestionCycleResult(
        summaries=summaries,
        freshness_checks=freshness_checks,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Flood Risk worker scheduler")
    parser.add_argument("--once", action="store_true", help="Run one scheduler tick and exit.")
    parser.add_argument(
        "--official-demo",
        action="store_true",
        help="Run enabled official demo adapters through the scheduler cycle.",
    )
    args = parser.parse_args()
    settings = load_worker_settings()
    log_event(
        "scheduler.started",
        interval_seconds=settings.scheduler_interval_seconds,
        enabled_adapters=enabled_adapter_keys(settings),
    )
    while True:
        if args.official_demo:
            run_scheduled_ingestion_cycle(
                build_official_demo_adapters(),
                settings=settings,
                job_key="scheduler.official_demo",
            )
        else:
            run_sample_job(
                job_key="maintenance.placeholder",
                enabled_adapters=enabled_adapter_keys(settings),
            )
        if args.once:
            return
        time.sleep(settings.scheduler_interval_seconds)


if __name__ == "__main__":
    main()
