from __future__ import annotations

import argparse
import time
from collections.abc import Sequence
from dataclasses import dataclass

from app.adapters.registry import enabled_adapter_keys
from app.config import WorkerSettings, load_worker_settings
from app.jobs.official_demo import build_official_demo_adapters
from app.scheduler import (
    run_enabled_adapters_loop,
    run_enabled_adapters_once,
    run_scheduled_ingestion_cycle,
)
from app.jobs.sample import run_sample_job
from app.logging import log_event
from app.pipelines.ingestion_runs import PostgresIngestionRunWriter
from app.pipelines.postgres_writer import PostgresStagingBatchWriter
from app.pipelines.promotion import (
    PostgresEvidencePromotionWriter,
    PromotionResult,
    promote_accepted_staging,
)


@dataclass(frozen=True)
class DemoPersistenceWriters:
    staging_writer: PostgresStagingBatchWriter
    run_writer: PostgresIngestionRunWriter
    promotion_writer: PostgresEvidencePromotionWriter


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Flood Risk worker runtime")
    parser.add_argument("--once", action="store_true", help="Run one sample job and exit.")
    parser.add_argument(
        "--run-official-demo",
        action="store_true",
        help="Run enabled official demo adapters once through ingestion and freshness checks.",
    )
    parser.add_argument(
        "--run-enabled-adapters",
        action="store_true",
        help="Run configured runtime adapters once, selected by WORKER_ENABLED_ADAPTER_KEYS/config gates.",
    )
    parser.add_argument(
        "--scheduler",
        action="store_true",
        help="Run configured runtime adapters in a scheduler loop.",
    )
    parser.add_argument(
        "--max-ticks",
        type=int,
        help="Bound --scheduler ticks. Defaults to SCHEDULER_MAX_TICKS when set.",
    )
    parser.add_argument(
        "--persist",
        action="store_true",
        help="Persist --run-official-demo output to Postgres staging, ingestion runs, and evidence.",
    )
    parser.add_argument(
        "--database-url",
        help="Postgres URL for --run-official-demo --persist. Defaults to WORKER_DATABASE_URL/DATABASE_URL.",
    )
    parser.add_argument(
        "--list-adapters",
        action="store_true",
        help="Print enabled adapter keys and exit.",
    )
    args = parser.parse_args(argv)
    settings = load_worker_settings()

    if args.list_adapters:
        for adapter_key in enabled_adapter_keys(settings):
            print(adapter_key)
        return 0

    if args.once:
        run_sample_job(enabled_adapters=enabled_adapter_keys(settings))
        return 0

    if args.run_enabled_adapters:
        result = run_enabled_adapters_once(settings=settings, job_key="worker.runtime.run_once")
        return 1 if result.has_alerts else 0

    if args.scheduler:
        results = run_enabled_adapters_loop(
            settings=settings,
            max_ticks=max(1, args.max_ticks) if args.max_ticks is not None else None,
        )
        return 1 if any(result.has_alerts for result in results) else 0

    if args.run_official_demo:
        adapters = build_official_demo_adapters()
        persistence = (
            _build_demo_persistence_writers(settings, database_url=args.database_url)
            if args.persist
            else None
        )
        result = run_scheduled_ingestion_cycle(
            adapters,
            settings=settings,
            job_key="worker.official_demo",
            writer=persistence.staging_writer if persistence else None,
            run_writer=persistence.run_writer if persistence else None,
        )
        promotion = (
            promote_accepted_staging(
                persistence.promotion_writer,
                adapter_keys=tuple(adapters),
            )
            if persistence is not None
            else PromotionResult(promoted=0, evidence_ids=())
        )
        log_event(
            "worker.official_demo.completed",
            persisted=args.persist,
            promoted=promotion.promoted,
            evidence_ids=promotion.evidence_ids,
        )
        return 1 if result.has_alerts else 0

    log_event("worker.started", mode="placeholder", enabled_adapters=enabled_adapter_keys(settings))
    while True:
        run_sample_job(enabled_adapters=enabled_adapter_keys(settings))
        time.sleep(settings.worker_idle_seconds)


def _build_demo_persistence_writers(
    settings: WorkerSettings,
    *,
    database_url: str | None = None,
) -> DemoPersistenceWriters:
    resolved_database_url = database_url or settings.database_url
    if not resolved_database_url:
        raise SystemExit(
            "--persist requires --database-url, WORKER_DATABASE_URL, or DATABASE_URL"
        )

    return DemoPersistenceWriters(
        staging_writer=PostgresStagingBatchWriter(database_url=resolved_database_url),
        run_writer=PostgresIngestionRunWriter(database_url=resolved_database_url),
        promotion_writer=PostgresEvidencePromotionWriter(database_url=resolved_database_url),
    )


if __name__ == "__main__":
    raise SystemExit(main())
