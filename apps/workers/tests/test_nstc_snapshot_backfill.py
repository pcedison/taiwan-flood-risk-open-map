from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.jobs.historical_coverage import HistoricalCoverageWriteResult
from app.jobs.nstc_snapshot_backfill import (
    NSTC_BACKFILL_AUTHORITATIVE_COVERAGE_YEARS,
    NSTC_FROZEN_SNAPSHOT_SHA256,
    NstcSnapshotBackfillConfig,
    NstcSnapshotBackfillError,
    run_nstc_snapshot_backfill,
)
from app.main import main


REPO_ROOT = Path(__file__).resolve().parents[3]
FROZEN_SNAPSHOT = (
    REPO_ROOT / "apps" / "api" / "app" / "data" / "official" / "flood_disaster_points_130016.csv"
)
FETCHED_AT = datetime(2026, 9, 2, 8, 0, tzinfo=UTC)


def _config(**overrides: Any) -> NstcSnapshotBackfillConfig:
    values: dict[str, Any] = {
        "input_path": FROZEN_SNAPSHOT,
        "expected_sha256": NSTC_FROZEN_SNAPSHOT_SHA256,
        "fetched_at": FETCHED_AT,
    }
    values.update(overrides)
    return NstcSnapshotBackfillConfig(**values)


def test_reviewed_frozen_snapshot_dry_run_reports_raw_and_normalized_counts() -> None:
    result = run_nstc_snapshot_backfill(_config())

    assert result.mode == "dry-run"
    assert result.input_row_count == 5_923
    assert result.year_counts == {
        2018: 1_923,
        2019: 1_267,
        2020: 489,
        2021: 1_812,
        2022: 432,
    }
    assert result.normalized_year_counts == {
        2018: 1_923,
        2019: 1_265,
        2020: 487,
        2021: 1_812,
        2022: 432,
    }
    assert result.normalized_count == 5_919
    assert result.rejection_reason_counts == {"nstc_outside_taiwan_bounds": 4}
    assert result.unique_source_record_key_count == 5_018
    assert result.duplicate_source_record_count == 901
    assert result.review_ref is None


def test_wrong_snapshot_digest_fails_before_any_writer_is_required() -> None:
    with pytest.raises(NstcSnapshotBackfillError, match="does not match"):
        run_nstc_snapshot_backfill(_config(expected_sha256="0" * 64))


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"persist": True}, "target-environment"),
        (
            {"persist": True, "target_environment": "staging"},
            "approval-ack",
        ),
        (
            {
                "persist": True,
                "target_environment": "staging",
                "approval_ack": True,
            },
            "review-ref",
        ),
        (
            {
                "persist": True,
                "target_environment": "production",
                "approval_ack": True,
                "review_ref": "PR-313",
            },
            "production-ack",
        ),
    ],
)
def test_persist_gates_fail_before_writer_construction(
    overrides: dict[str, Any],
    message: str,
) -> None:
    with pytest.raises(NstcSnapshotBackfillError, match=message):
        run_nstc_snapshot_backfill(_config(**overrides))


def test_persist_path_is_raw_ref_scoped_and_limits_coverage_to_2018_2020() -> None:
    staging_writer = _StagingWriter()
    run_writer = _RunWriter()
    promotion_writer = _PromotionWriter()
    coverage_writer = _CoverageWriter()

    result = run_nstc_snapshot_backfill(
        _config(
            persist=True,
            target_environment="staging",
            approval_ack=True,
            review_ref="PR-313/staging-rehearsal",
        ),
        staging_writer=staging_writer,
        run_writer=run_writer,
        promotion_writer=promotion_writer,
        coverage_writer=coverage_writer,
    )

    assert result.mode == "persist"
    assert result.summary is not None
    assert result.summary.status == "partial"
    assert result.summary.items_promoted == 5_919
    assert result.summary.items_rejected == 4
    assert result.summary.ingestion_job_id == "ingestion-job-fixture"
    assert len(staging_writer.batches) == 1
    assert run_writer.job_keys == ["worker.nstc_snapshot.backfill"]
    assert promotion_writer.adapter_keys == ("official.nstc.flood_disaster_points",)
    assert promotion_writer.raw_refs == (result.raw_ref,)
    assert coverage_writer.authoritative_years == (2018, 2019, 2020)
    assert coverage_writer.review_ref is not None
    assert coverage_writer.review_ref.startswith("nstc-backfill:v1:PR-313/staging-rehearsal:")


def test_cli_defaults_to_no_network_dry_run(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(
        [
            "--run-nstc-snapshot-backfill",
            "--nstc-backfill-input",
            str(FROZEN_SNAPSHOT),
            "--nstc-backfill-expected-sha256",
            NSTC_FROZEN_SNAPSHOT_SHA256,
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "succeeded"
    assert payload["mode"] == "dry-run"
    assert payload["coverage_authoritative_years"] == [2018, 2019, 2020]


class _StagingWriter:
    def __init__(self) -> None:
        self.batches: list[Any] = []

    def write_batch(self, batch: Any) -> None:
        self.batches.append(batch)


class _RunWriter:
    def __init__(self) -> None:
        self.job_keys: list[str] = []

    def write_summary(
        self,
        summary: Any,
        *,
        job_key: str,
        parameters: dict[str, Any] | None = None,
    ) -> str:
        del summary, parameters
        self.job_keys.append(job_key)
        return "ingestion-job-fixture"


class _PromotionWriter:
    def __init__(self) -> None:
        self.adapter_keys: tuple[str, ...] | None = None
        self.raw_refs: tuple[str, ...] | None = None

    def fetch_accepted_staging(
        self,
        *,
        limit: int | None = None,
        adapter_keys: tuple[str, ...] | None = None,
        raw_refs: tuple[str, ...] | None = None,
    ) -> tuple[Any, ...]:
        del limit
        self.adapter_keys = adapter_keys
        self.raw_refs = raw_refs
        return ()

    def write_evidence(self, payload: Any) -> str | None:
        raise AssertionError(f"unexpected promotion payload: {payload!r}")

    def retire_warning_latest_for_no_active_event(self, **_kwargs: Any) -> int:
        return 0


class _CoverageWriter:
    def __init__(self) -> None:
        self.authoritative_years: tuple[int, ...] | None = None
        self.review_ref: str | None = None

    def record_success(
        self,
        *,
        adapter_key: str,
        raw_ref: str,
        assessed_at: datetime,
        authoritative_years: tuple[int, ...] | None = None,
        review_ref: str | None = None,
    ) -> HistoricalCoverageWriteResult:
        del raw_ref, assessed_at
        self.authoritative_years = authoritative_years
        self.review_ref = review_ref
        return HistoricalCoverageWriteResult(
            adapter_key=adapter_key,
            assessed_years=NSTC_BACKFILL_AUTHORITATIVE_COVERAGE_YEARS,
            source_check_count=66,
            attributed_record_count=5_018,
            boundary_adjusted_record_count=0,
        )
