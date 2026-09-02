from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import psycopg

from app.config import WorkerSettings
from app.jobs.historical_coverage_review import (
    HistoricalCoverageGapReviewError,
    PostgresHistoricalCoverageGapReviewWriter,
    load_historical_coverage_gap_review,
)


def run_historical_coverage_gap_review_command(
    *,
    args: argparse.Namespace,
    settings: WorkerSettings,
) -> int:
    try:
        manifest_path = args.historical_coverage_review_manifest
        expected_sha256 = args.historical_coverage_review_expected_sha256
        if not manifest_path:
            raise HistoricalCoverageGapReviewError(
                "--historical-coverage-review-manifest is required"
            )
        if not expected_sha256:
            raise HistoricalCoverageGapReviewError(
                "--historical-coverage-review-expected-sha256 is required"
            )
        _require_persist_approval(args)
        manifest, manifest_sha256 = load_historical_coverage_gap_review(
            Path(manifest_path),
            expected_sha256=expected_sha256,
        )
        database_url = args.database_url or settings.database_url
        if args.persist and not database_url:
            raise HistoricalCoverageGapReviewError(
                "--persist requires --database-url, WORKER_DATABASE_URL, or DATABASE_URL"
            )
        if database_url:
            result = PostgresHistoricalCoverageGapReviewWriter(database_url=database_url).assess(
                manifest,
                manifest_sha256=manifest_sha256,
                persist=args.persist,
            )
            payload: dict[str, Any] = result.as_payload()
            payload["database_checked"] = True
        else:
            payload = {
                "database_checked": False,
                "manifest_sha256": manifest_sha256,
                "persisted_review_ref": None,
                "target_cell_count": manifest.target_cell_count,
                "target_years": [target.year for target in manifest.targets],
                "target_statuses": {str(target.year): target.status for target in manifest.targets},
            }
    except psycopg.Error as exc:
        return _print_failure(
            persist=args.persist,
            reason=(
                "historical coverage database operation failed "
                f"({exc.__class__.__name__}); inspect the private worker logs"
            ),
        )
    except (HistoricalCoverageGapReviewError, OSError, ValueError) as exc:
        return _print_failure(persist=args.persist, reason=str(exc))

    payload.update(
        {
            "status": "succeeded",
            "mode": "persist" if args.persist else "dry-run",
            "network_allowed": False,
            "review_ref": manifest.review_ref,
            "reviewed_at": manifest.reviewed_at.isoformat(),
            "target_environment": (
                args.historical_coverage_review_target_environment
                if args.persist
                else None
            ),
        }
    )
    print(json.dumps(payload, sort_keys=True))
    return 0


def _print_failure(*, persist: bool, reason: str) -> int:
    print(
        json.dumps(
            {
                "status": "failed",
                "mode": "persist" if persist else "dry-run",
                "reason": reason,
                "network_allowed": False,
            },
            sort_keys=True,
        )
    )
    return 1


def _require_persist_approval(args: argparse.Namespace) -> None:
    if not args.persist:
        return
    target_environment = args.historical_coverage_review_target_environment
    if target_environment is None:
        raise HistoricalCoverageGapReviewError(
            "--persist requires --historical-coverage-review-target-environment"
        )
    if not args.historical_coverage_review_approval_ack:
        raise HistoricalCoverageGapReviewError(
            "--persist requires --historical-coverage-review-approval-ack"
        )
    # The target environment is an operator label, not an independently
    # authenticated property of the selected database URL. Fail closed for
    # every write so a staging command cannot be copied onto production.
    if not args.historical_coverage_review_production_ack:
        raise HistoricalCoverageGapReviewError(
            "--persist requires --historical-coverage-review-production-ack because "
            "the database target cannot be inferred from the environment label"
        )
