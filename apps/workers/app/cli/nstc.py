from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from app.cli.persistence import build_demo_persistence_writers
from app.config import WorkerSettings
from app.jobs.historical_coverage import PostgresHistoricalCoverageWriter
from app.jobs.nstc_snapshot_backfill import (
    NstcSnapshotBackfillConfig,
    NstcSnapshotBackfillError,
    run_nstc_snapshot_backfill,
)


def run_nstc_snapshot_backfill_command(
    *,
    args: argparse.Namespace,
    settings: WorkerSettings,
) -> int:
    try:
        if not args.nstc_backfill_input:
            raise NstcSnapshotBackfillError("--nstc-backfill-input is required")
        if not args.nstc_backfill_expected_sha256:
            raise NstcSnapshotBackfillError("--nstc-backfill-expected-sha256 is required")
        config = NstcSnapshotBackfillConfig(
            input_path=Path(args.nstc_backfill_input),
            expected_sha256=args.nstc_backfill_expected_sha256,
            persist=args.persist,
            target_environment=args.nstc_backfill_target_environment,
            review_ref=args.nstc_backfill_review_ref,
            approval_ack=args.nstc_backfill_approval_ack,
            production_ack=args.nstc_backfill_production_ack,
            fetched_at=datetime.now(UTC),
        )
        if not args.persist:
            result = run_nstc_snapshot_backfill(config)
        else:
            resolved_database_url = args.database_url or settings.database_url
            if not resolved_database_url:
                raise NstcSnapshotBackfillError(
                    "--persist requires --database-url, WORKER_DATABASE_URL, or DATABASE_URL"
                )
            persistence = build_demo_persistence_writers(
                settings,
                database_url=args.database_url,
            )
            result = run_nstc_snapshot_backfill(
                config,
                staging_writer=persistence.staging_writer,
                run_writer=persistence.run_writer,
                promotion_writer=persistence.promotion_writer,
                coverage_writer=PostgresHistoricalCoverageWriter(
                    database_url=resolved_database_url
                ),
            )
    except (NstcSnapshotBackfillError, OSError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "mode": "persist" if args.persist else "dry-run",
                    "reason": str(exc),
                    "network_allowed": False,
                },
                sort_keys=True,
            )
        )
        return 1

    print(json.dumps(result.as_payload(), sort_keys=True))
    return 0
