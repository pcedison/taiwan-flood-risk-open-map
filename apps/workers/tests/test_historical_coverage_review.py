from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest

from app.jobs.historical_coverage_review import (
    APPROVED_HISTORICAL_COVERAGE_GAP_REVIEW_SHA256,
    HistoricalCoverageGapReviewError,
    PostgresHistoricalCoverageGapReviewWriter,
    load_historical_coverage_gap_review,
)
from app.main import main


REPO_ROOT = Path(__file__).resolve().parents[3]
REVIEW_MANIFEST = (
    REPO_ROOT
    / "docs"
    / "data-sources"
    / "official"
    / "historical-coverage-gap-review-2026-09-02.json"
)
REVIEW_MANIFEST_SHA256 = "01ca620ee29d8a8815ff00fffb7894ef02e1acf36a01960b00e2d625b1598d3c"


def _manifest() -> Any:
    manifest, digest = load_historical_coverage_gap_review(
        REVIEW_MANIFEST,
        expected_sha256=REVIEW_MANIFEST_SHA256,
        now=datetime(2026, 9, 2, 6, 0, tzinfo=UTC),
    )
    assert digest == REVIEW_MANIFEST_SHA256
    return manifest


def test_review_manifest_is_pinned_and_keeps_absence_fail_closed() -> None:
    manifest = _manifest()

    assert REVIEW_MANIFEST_SHA256 == APPROVED_HISTORICAL_COVERAGE_GAP_REVIEW_SHA256
    assert manifest.target_cell_count == 44
    assert [(target.year, target.status) for target in manifest.targets] == [
        (2017, "not_published"),
        (2026, "failed"),
    ]
    assert "does not show that no local flood occurred" in manifest.targets[0].status_reason
    assert manifest.adapter_keys_for(manifest.targets[0]) == (
        "official.nstc.flood_disaster_points",
        "official.wra.historical_flood",
    )


def test_review_manifest_rejects_wrong_digest() -> None:
    with pytest.raises(HistoricalCoverageGapReviewError, match="does not match"):
        load_historical_coverage_gap_review(
            REVIEW_MANIFEST,
            expected_sha256="0" * 64,
        )


def test_review_manifest_rejects_modified_content_with_matching_operator_digest(
    tmp_path: Path,
) -> None:
    raw = json.loads(REVIEW_MANIFEST.read_text(encoding="utf-8"))
    raw["targets"][0]["status_reason"] += " Modified after approval."
    modified = tmp_path / "modified-review.json"
    modified.write_text(
        json.dumps(raw, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    operator_digest = sha256(modified.read_bytes()).hexdigest()

    with pytest.raises(HistoricalCoverageGapReviewError, match="code-approved revision"):
        load_historical_coverage_gap_review(
            modified,
            expected_sha256=operator_digest,
            now=datetime(2026, 9, 2, 6, 0, tzinfo=UTC),
        )


def test_dry_run_simulates_only_unassessed_targets_without_mutation() -> None:
    database = _CoverageDatabase()
    database.cells[("J01", 2017)] = ("partial", "source-snapshot-review")
    writer = PostgresHistoricalCoverageGapReviewWriter(connection_factory=lambda: database)

    result = writer.assess(
        _manifest(),
        manifest_sha256=REVIEW_MANIFEST_SHA256,
        persist=False,
    )

    assert result.target_cell_count == 44
    assert result.would_update_cell_count == 43
    assert result.applied_cell_count == 0
    assert result.preserved_cell_count == 1
    assert result.remaining_unassessed_cell_count == 286
    assert result.status_counts == {
        "failed": 22,
        "not_published": 21,
        "partial": 1,
        "unassessed": 286,
    }
    assert database.cells[("J01", 2017)] == ("partial", "source-snapshot-review")
    assert database.rollback_count == 1


def test_persist_preserves_source_results_and_rerun_is_idempotent() -> None:
    database = _CoverageDatabase()
    database.cells[("J01", 2017)] = ("partial", "source-snapshot-review")
    writer = PostgresHistoricalCoverageGapReviewWriter(connection_factory=lambda: database)

    first = writer.assess(
        _manifest(),
        manifest_sha256=REVIEW_MANIFEST_SHA256,
        persist=True,
    )
    second = writer.assess(
        _manifest(),
        manifest_sha256=REVIEW_MANIFEST_SHA256,
        persist=True,
    )

    assert first.applied_cell_count == 43
    assert first.remaining_unassessed_cell_count == 286
    assert first.status_counts == {
        "failed": 22,
        "not_published": 21,
        "partial": 1,
        "unassessed": 286,
    }
    assert second.would_update_cell_count == 0
    assert second.applied_cell_count == 0
    assert second.preserved_cell_count == 44
    assert database.cells[("J01", 2017)] == ("partial", "source-snapshot-review")
    assert database.commit_count == 2


def test_cli_defaults_to_manifest_only_no_network_dry_run(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        [
            "--run-historical-coverage-gap-review",
            "--historical-coverage-review-manifest",
            str(REVIEW_MANIFEST),
            "--historical-coverage-review-expected-sha256",
            REVIEW_MANIFEST_SHA256,
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "succeeded"
    assert payload["mode"] == "dry-run"
    assert payload["network_allowed"] is False
    assert payload["database_checked"] is False
    assert payload["target_cell_count"] == 44


@pytest.mark.parametrize(
    ("extra_args", "reason"),
    [
        ([], "target-environment"),
        (
            ["--historical-coverage-review-target-environment", "staging"],
            "approval-ack",
        ),
        (
            [
                "--historical-coverage-review-target-environment",
                "production",
                "--historical-coverage-review-approval-ack",
            ],
            "production-ack",
        ),
    ],
)
def test_cli_persist_requires_explicit_approval_gates(
    extra_args: list[str],
    reason: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        [
            "--run-historical-coverage-gap-review",
            "--historical-coverage-review-manifest",
            str(REVIEW_MANIFEST),
            "--historical-coverage-review-expected-sha256",
            REVIEW_MANIFEST_SHA256,
            "--persist",
            *extra_args,
        ]
    )

    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "failed"
    assert reason in payload["reason"]
    assert payload["network_allowed"] is False


class _CoverageDatabase:
    def __init__(self) -> None:
        self.cells = {
            (f"J{jurisdiction:02d}", year): ("unassessed", None)
            for jurisdiction in range(1, 23)
            for year in range(2012, 2027)
        }
        self.commit_count = 0
        self.rollback_count = 0

    def __enter__(self) -> _CoverageDatabase:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def cursor(self) -> _CoverageCursor:
        return _CoverageCursor(self)

    def commit(self) -> None:
        self.commit_count += 1

    def rollback(self) -> None:
        self.rollback_count += 1


class _CoverageCursor:
    def __init__(self, database: _CoverageDatabase) -> None:
        self.database = database
        self.rowcount = 0
        self._rows: list[tuple[Any, ...]] = []

    def __enter__(self) -> _CoverageCursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(
        self,
        statement: str,
        parameters: tuple[Any, ...] | None = None,
    ) -> None:
        normalized = " ".join(statement.split())
        self.rowcount = 0
        if "count(DISTINCT jurisdiction_code)" in normalized:
            self._rows = [(330, 22, 15, 2012, 2026)]
            return
        if normalized.startswith("SELECT jurisdiction_code, coverage_year, status, review_ref"):
            assert parameters is not None
            years = set(parameters[0])
            self._rows = [
                (code, year, status, review_ref)
                for (code, year), (status, review_ref) in sorted(self.database.cells.items())
                if year in years
            ]
            return
        if normalized.startswith("SELECT status, count(*)::integer"):
            counts = Counter(status for status, _review_ref in self.database.cells.values())
            self._rows = sorted(counts.items())
            return
        if normalized.startswith("UPDATE historical_coverage_cells SET"):
            assert parameters is not None
            status = str(parameters[0])
            review_ref = str(parameters[5])
            year = int(parameters[7])
            for key, (existing_status, _existing_review_ref) in tuple(self.database.cells.items()):
                if key[1] == year and existing_status == "unassessed":
                    self.database.cells[key] = (status, review_ref)
                    self.rowcount += 1
            self._rows = []
            return
        raise AssertionError(f"unexpected SQL: {normalized}")

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._rows)
