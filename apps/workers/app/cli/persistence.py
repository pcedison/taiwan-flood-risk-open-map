"""Persistence writer bundles shared by worker CLI commands."""

from __future__ import annotations

from dataclasses import dataclass

from app.config import WorkerSettings
from app.jobs.ingestion import IngestionRunSummaryWriter
from app.jobs.runtime import build_runtime_persistence_writers
from app.pipelines.ingestion_runs import PostgresIngestionRunWriter
from app.pipelines.postgres_writer import PostgresStagingBatchWriter
from app.pipelines.promotion import EvidencePromotionWriter, PostgresEvidencePromotionWriter
from app.pipelines.staging import StagingBatchWriter


@dataclass(frozen=True)
class DemoPersistenceWriters:
    staging_writer: StagingBatchWriter
    run_writer: IngestionRunSummaryWriter
    promotion_writer: EvidencePromotionWriter


def build_demo_persistence_writers(
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


def build_runtime_persistence_bundle(
    settings: WorkerSettings,
    *,
    database_url: str | None = None,
) -> DemoPersistenceWriters:
    resolved_database_url = database_url or settings.database_url
    if not resolved_database_url:
        raise SystemExit(
            "--persist requires --database-url, WORKER_DATABASE_URL, or DATABASE_URL"
        )

    staging_writer, run_writer, promotion_writer = build_runtime_persistence_writers(
        resolved_database_url
    )
    return DemoPersistenceWriters(
        staging_writer=staging_writer,
        run_writer=run_writer,
        promotion_writer=promotion_writer,
    )
