from __future__ import annotations

import csv
import hashlib
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from typing import Any, Literal, Protocol

from app.adapters.nstc.flood_disaster_points import (
    MAX_NSTC_FLOOD_DISASTER_POINTS_BYTES,
    NSTC_FLOOD_DISASTER_POINTS_METADATA,
    NSTC_SNAPSHOT_AUTHORITY_REVIEWED_FROZEN_BACKFILL,
    NstcFloodDisasterPointsAdapter,
    NstcFloodDisasterPointsPayloadError,
)
from app.jobs.historical_coverage import HistoricalCoverageWriteResult
from app.jobs.ingestion import (
    AdapterBatchRunSummary,
    IngestionRunSummaryWriter,
    run_adapter_batch,
)
from app.pipelines.promotion import (
    EvidencePromotionPayload,
    EvidencePromotionWriter,
    PromotionCandidate,
    PromotionResult,
    promote_accepted_staging,
)
from app.pipelines.staging import AdapterStagingBatch, StagingBatchWriter


NSTC_FROZEN_SNAPSHOT_SHA256 = "9919ed734ca8cca4d0541ac88148f4909d47e1939d56199da34af7964ef72f5d"
NSTC_FROZEN_SNAPSHOT_ROW_COUNT = 5_923
NSTC_FROZEN_SNAPSHOT_INPUT_YEAR_COUNTS = {
    2018: 1_923,
    2019: 1_267,
    2020: 489,
    2021: 1_812,
    2022: 432,
}
NSTC_FROZEN_SNAPSHOT_NORMALIZED_YEAR_COUNTS = {
    2018: 1_923,
    2019: 1_265,
    2020: 487,
    2021: 1_812,
    2022: 432,
}
NSTC_FROZEN_SNAPSHOT_REJECTION_REASON_COUNTS = {
    "nstc_outside_taiwan_bounds": 4,
}
NSTC_BACKFILL_AUTHORITATIVE_COVERAGE_YEARS = (2018, 2019, 2020)
NSTC_BACKFILL_JOB_KEY = "worker.nstc_snapshot.backfill"
NSTC_FROZEN_SNAPSHOT_RETENTION_POLICY = "non_expiring_reviewed_frozen_snapshot"

NstcBackfillTargetEnvironment = Literal["staging", "production"]


class NstcSnapshotBackfillError(RuntimeError):
    pass


class HistoricalCoverageWriter(Protocol):
    def record_success(
        self,
        *,
        adapter_key: str,
        raw_ref: str,
        assessed_at: datetime,
        authoritative_years: tuple[int, ...] | None = None,
        review_ref: str | None = None,
    ) -> HistoricalCoverageWriteResult:
        """Record reviewed historical coverage for one persisted raw revision."""


@dataclass(frozen=True)
class _NonExpiringSnapshotWriter:
    """Keep the reviewed frozen revision available for durable replay/audit."""

    writer: StagingBatchWriter

    def write_batch(self, batch: AdapterStagingBatch) -> None:
        raw_snapshot = replace(
            batch.raw_snapshot,
            retention_expires_at=None,
            metadata={
                **batch.raw_snapshot.metadata,
                "retention_policy": NSTC_FROZEN_SNAPSHOT_RETENTION_POLICY,
            },
        )
        self.writer.write_batch(replace(batch, raw_snapshot=raw_snapshot))


@dataclass
class _CountingPromotionWriter:
    """Track confirmed writes so a terminal failure audit stays truthful."""

    writer: EvidencePromotionWriter
    promoted: int = 0

    def fetch_accepted_staging(
        self,
        *,
        limit: int | None = None,
        adapter_keys: tuple[str, ...] | None = None,
        raw_refs: tuple[str, ...] | None = None,
    ) -> tuple[PromotionCandidate, ...]:
        return self.writer.fetch_accepted_staging(
            limit=limit,
            adapter_keys=adapter_keys,
            raw_refs=raw_refs,
        )

    def write_evidence(self, payload: EvidencePromotionPayload) -> str | None:
        evidence_id = self.writer.write_evidence(payload)
        if evidence_id is not None:
            self.promoted += 1
        return evidence_id

    def write_evidence_batch(
        self,
        payloads: tuple[EvidencePromotionPayload, ...],
    ) -> tuple[str | None, ...]:
        batch_write = getattr(self.writer, "write_evidence_batch", None)
        if callable(batch_write):
            batch_results = tuple(batch_write(payloads))
            self.promoted += sum(result is not None for result in batch_results)
            return batch_results

        individual_results: list[str | None] = []
        for payload in payloads:
            evidence_id = self.writer.write_evidence(payload)
            individual_results.append(evidence_id)
            if evidence_id is not None:
                self.promoted += 1
        return tuple(individual_results)

    def retire_warning_latest_for_no_active_event(
        self,
        *,
        adapter_key: str,
        generation_started_at: datetime,
        completed_at: datetime,
    ) -> int:
        return self.writer.retire_warning_latest_for_no_active_event(
            adapter_key=adapter_key,
            generation_started_at=generation_started_at,
            completed_at=completed_at,
        )


@dataclass(frozen=True)
class NstcSnapshotBackfillConfig:
    input_path: Path
    expected_sha256: str
    persist: bool = False
    target_environment: NstcBackfillTargetEnvironment | None = None
    review_ref: str | None = None
    approval_ack: bool = False
    production_ack: bool = False
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class NstcSnapshotBackfillResult:
    mode: Literal["dry-run", "persist"]
    target_environment: NstcBackfillTargetEnvironment | None
    snapshot_sha256: str
    snapshot_bytes: int
    raw_ref: str
    input_row_count: int
    year_counts: dict[int, int]
    normalized_year_counts: dict[int, int]
    normalized_count: int
    rejected_count: int
    rejection_reason_counts: dict[str, int]
    unique_source_record_key_count: int
    duplicate_source_record_count: int
    duplicate_source_record_key_count: int
    summary: AdapterBatchRunSummary | None = None
    promotion: PromotionResult | None = None
    coverage: HistoricalCoverageWriteResult | None = None
    review_ref: str | None = None

    def as_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": "succeeded",
            "mode": self.mode,
            "target_environment": self.target_environment,
            "adapter_key": NSTC_FLOOD_DISASTER_POINTS_METADATA.key,
            "snapshot_sha256": self.snapshot_sha256,
            "snapshot_bytes": self.snapshot_bytes,
            "raw_ref": self.raw_ref,
            "input_row_count": self.input_row_count,
            "year_counts": {str(year): count for year, count in sorted(self.year_counts.items())},
            "normalized_year_counts": {
                str(year): count for year, count in sorted(self.normalized_year_counts.items())
            },
            "normalized_count": self.normalized_count,
            "rejected_count": self.rejected_count,
            "rejection_reason_counts": dict(sorted(self.rejection_reason_counts.items())),
            "unique_source_record_key_count": self.unique_source_record_key_count,
            "duplicate_source_record_count": self.duplicate_source_record_count,
            "duplicate_source_record_key_count": self.duplicate_source_record_key_count,
            "coverage_authoritative_years": list(NSTC_BACKFILL_AUTHORITATIVE_COVERAGE_YEARS),
            "coverage_excluded_newer_years": [2021, 2022],
            "review_ref": self.review_ref,
        }
        if self.summary is not None:
            payload["staging"] = {
                "status": self.summary.status,
                "accepted_count": self.summary.items_promoted,
                "rejected_count": self.summary.items_rejected,
                "ingestion_job_id": self.summary.ingestion_job_id,
            }
        if self.promotion is not None:
            payload["promotion"] = {"new_evidence_count": self.promotion.promoted}
        if self.coverage is not None:
            payload["coverage"] = {
                "assessed_years": list(self.coverage.assessed_years),
                "source_check_count": self.coverage.source_check_count,
                "attributed_record_count": self.coverage.attributed_record_count,
                "boundary_adjusted_record_count": (self.coverage.boundary_adjusted_record_count),
            }
        return payload


def run_nstc_snapshot_backfill(
    config: NstcSnapshotBackfillConfig,
    *,
    staging_writer: StagingBatchWriter | None = None,
    run_writer: IngestionRunSummaryWriter | None = None,
    promotion_writer: EvidencePromotionWriter | None = None,
    coverage_writer: HistoricalCoverageWriter | None = None,
) -> NstcSnapshotBackfillResult:
    _validate_config(config)
    payload = _read_snapshot(config.input_path)
    actual_sha256 = hashlib.sha256(payload).hexdigest()
    expected_sha256 = _normalized_sha256(config.expected_sha256)
    if actual_sha256 != expected_sha256:
        raise NstcSnapshotBackfillError(
            "NSTC snapshot SHA-256 does not match --nstc-backfill-expected-sha256"
        )
    if actual_sha256 != NSTC_FROZEN_SNAPSHOT_SHA256:
        raise NstcSnapshotBackfillError(
            "NSTC snapshot is not the reviewed 2018-2022 frozen revision"
        )

    text = _decode_snapshot(payload)
    input_year_counts = _input_year_counts(text)
    raw_ref = _raw_ref(actual_sha256)
    adapter = NstcFloodDisasterPointsAdapter(
        fetched_at=config.fetched_at,
        fetch_text=lambda _url, _timeout: text,
        raw_snapshot_key=raw_ref,
        dataset_revision_sha256=actual_sha256,
        snapshot_authority=NSTC_SNAPSHOT_AUTHORITY_REVIEWED_FROZEN_BACKFILL,
    )
    adapter_result = adapter.run()
    normalized_year_counts = Counter(
        year
        for item in adapter_result.fetched
        if isinstance((year := item.payload.get("year")), int) and not isinstance(year, bool)
    )
    source_record_keys = tuple(
        key
        for item in adapter_result.fetched
        if isinstance((key := item.payload.get("source_record_key")), str) and key
    )
    source_record_key_counts = Counter(source_record_keys)
    rejection_reason_counts = Counter(
        rejection.reason_code for rejection in adapter_result.source_rejections
    )
    duplicate_source_record_key_count = sum(
        count > 1 for count in source_record_key_counts.values()
    )
    duplicate_source_record_count = sum(
        count - 1 for count in source_record_key_counts.values() if count > 1
    )
    _validate_reviewed_snapshot(
        row_count=len(adapter_result.fetched),
        input_year_counts=input_year_counts,
        normalized_year_counts=dict(normalized_year_counts),
        normalized_count=len(adapter_result.normalized),
        rejected_count=len(adapter_result.rejected),
        rejection_reason_counts=dict(rejection_reason_counts),
        source_record_key_count=len(source_record_keys),
    )

    review_ref = _persisted_review_ref(config.review_ref, actual_sha256)
    base_result = NstcSnapshotBackfillResult(
        mode="persist" if config.persist else "dry-run",
        target_environment=config.target_environment if config.persist else None,
        snapshot_sha256=actual_sha256,
        snapshot_bytes=len(payload),
        raw_ref=raw_ref,
        input_row_count=len(adapter_result.fetched),
        year_counts=input_year_counts,
        normalized_year_counts=dict(normalized_year_counts),
        normalized_count=len(adapter_result.normalized),
        rejected_count=len(adapter_result.rejected),
        rejection_reason_counts=dict(rejection_reason_counts),
        unique_source_record_key_count=len(source_record_key_counts),
        duplicate_source_record_count=duplicate_source_record_count,
        duplicate_source_record_key_count=duplicate_source_record_key_count,
        review_ref=review_ref if config.persist else None,
    )
    if not config.persist:
        return base_result

    if any(
        writer is None
        for writer in (
            staging_writer,
            run_writer,
            promotion_writer,
            coverage_writer,
        )
    ):
        raise NstcSnapshotBackfillError(
            "persist mode requires staging, run, promotion, and coverage writers"
        )
    assert staging_writer is not None
    assert run_writer is not None
    assert promotion_writer is not None
    assert coverage_writer is not None
    audit_parameters = {
        "snapshot_sha256": actual_sha256,
        "snapshot_bytes": len(payload),
        "input_row_count": len(adapter_result.fetched),
        "input_year_counts": dict(sorted(input_year_counts.items())),
        "normalized_year_counts": dict(sorted(normalized_year_counts.items())),
        "rejection_reason_counts": dict(sorted(rejection_reason_counts.items())),
        "target_environment": config.target_environment,
        "review_ref": review_ref,
        "coverage_authoritative_years": NSTC_BACKFILL_AUTHORITATIVE_COVERAGE_YEARS,
    }
    summary = run_adapter_batch(
        adapter,
        writer=_NonExpiringSnapshotWriter(staging_writer),
    )
    audit_id = _begin_backfill_audit(run_writer, summary, parameters=audit_parameters)
    if summary.status not in ("succeeded", "partial") or summary.raw_ref != raw_ref:
        error = NstcSnapshotBackfillError(
            "NSTC snapshot staging did not complete as the reviewed raw revision"
        )
        _finalize_backfill_audit(
            run_writer,
            audit_id,
            summary,
            parameters=audit_parameters,
            phase="staging",
            confirmed_promoted=0,
            promotion_count_complete=False,
            error=error,
        )
        raise error
    counting_promotion_writer = _CountingPromotionWriter(promotion_writer)
    try:
        promotion = promote_accepted_staging(
            counting_promotion_writer,
            adapter_keys=(NSTC_FLOOD_DISASTER_POINTS_METADATA.key,),
            raw_refs=(raw_ref,),
        )
    except Exception as exc:  # noqa: BLE001 - sanitize the persistence boundary
        _finalize_backfill_audit(
            run_writer,
            audit_id,
            summary,
            parameters=audit_parameters,
            phase="promotion",
            confirmed_promoted=counting_promotion_writer.promoted,
            promotion_count_complete=False,
            error=exc,
        )
        raise NstcSnapshotBackfillError(
            "NSTC snapshot promotion failed "
            f"({exc.__class__.__name__}); inspect the private worker logs"
        ) from exc
    try:
        coverage = coverage_writer.record_success(
            adapter_key=NSTC_FLOOD_DISASTER_POINTS_METADATA.key,
            raw_ref=raw_ref,
            assessed_at=config.fetched_at,
            authoritative_years=NSTC_BACKFILL_AUTHORITATIVE_COVERAGE_YEARS,
            review_ref=review_ref,
        )
        if coverage.assessed_years != NSTC_BACKFILL_AUTHORITATIVE_COVERAGE_YEARS:
            raise NstcSnapshotBackfillError(
                "NSTC coverage writer did not assess exactly 2018-2020"
            )
    except Exception as exc:  # noqa: BLE001 - sanitize the persistence boundary
        _finalize_backfill_audit(
            run_writer,
            audit_id,
            summary,
            parameters=audit_parameters,
            phase="coverage",
            confirmed_promoted=promotion.promoted,
            promotion_count_complete=True,
            error=exc,
        )
        raise NstcSnapshotBackfillError(
            "NSTC coverage attribution failed "
            f"({exc.__class__.__name__}); inspect the private worker logs"
        ) from exc
    _finalize_backfill_audit(
        run_writer,
        audit_id,
        summary,
        parameters=audit_parameters,
        phase="complete",
        confirmed_promoted=promotion.promoted,
        promotion_count_complete=True,
        error=None,
    )
    return replace(
        base_result,
        summary=replace(summary, ingestion_job_id=audit_id),
        promotion=promotion,
        coverage=coverage,
    )


def _begin_backfill_audit(
    writer: IngestionRunSummaryWriter,
    summary: AdapterBatchRunSummary,
    *,
    parameters: dict[str, Any],
) -> str:
    begin = getattr(writer, "begin_non_operational_summary", None)
    if not callable(begin):
        raise NstcSnapshotBackfillError(
            "NSTC persist requires a pending non-operational audit writer"
        )
    try:
        audit_id = begin(summary, job_key=NSTC_BACKFILL_JOB_KEY, parameters=parameters)
    except Exception as exc:  # noqa: BLE001 - sanitize the persistence boundary
        raise NstcSnapshotBackfillError(
            "NSTC pending audit write failed "
            f"({exc.__class__.__name__}); inspect the private worker logs"
        ) from exc
    if not isinstance(audit_id, str) or not audit_id:
        raise NstcSnapshotBackfillError("NSTC pending audit writer did not return an audit ID")
    return audit_id


def _finalize_backfill_audit(
    writer: IngestionRunSummaryWriter,
    audit_id: str,
    staging_summary: AdapterBatchRunSummary,
    *,
    parameters: dict[str, Any],
    phase: Literal["staging", "promotion", "coverage", "complete"],
    confirmed_promoted: int,
    promotion_count_complete: bool,
    error: Exception | None,
) -> None:
    finalize = getattr(writer, "finalize_non_operational_summary", None)
    if not callable(finalize):
        raise NstcSnapshotBackfillError(
            "NSTC persist requires a terminal non-operational audit writer"
        )
    terminal_summary = replace(
        staging_summary,
        status="failed" if error is not None else staging_summary.status,
        finished_at=datetime.now(UTC),
        items_promoted=confirmed_promoted,
        error_code=(f"nstc_{phase}_failed" if error is not None else None),
        error_message=(
            f"{error.__class__.__name__}; inspect the private worker logs"
            if error is not None
            else None
        ),
        ingestion_job_id=audit_id,
    )
    terminal_parameters = {
        **parameters,
        "terminal_phase": phase,
        "confirmed_promoted_count": confirmed_promoted,
        "promotion_count_complete": promotion_count_complete,
    }
    try:
        finalize(
            audit_id,
            terminal_summary,
            job_key=NSTC_BACKFILL_JOB_KEY,
            parameters=terminal_parameters,
        )
    except Exception as exc:  # noqa: BLE001 - sanitize the persistence boundary
        raise NstcSnapshotBackfillError(
            "NSTC terminal audit write failed "
            f"({exc.__class__.__name__}); inspect the private worker logs"
        ) from exc


def _validate_config(config: NstcSnapshotBackfillConfig) -> None:
    if config.fetched_at.tzinfo is None or config.fetched_at.utcoffset() is None:
        raise NstcSnapshotBackfillError("fetched_at must be timezone-aware")
    _normalized_sha256(config.expected_sha256)
    if not config.persist:
        return
    if config.target_environment not in ("staging", "production"):
        raise NstcSnapshotBackfillError("persist mode requires --nstc-backfill-target-environment")
    if not config.approval_ack:
        raise NstcSnapshotBackfillError("persist mode requires --nstc-backfill-approval-ack")
    _validated_operator_review_ref(config.review_ref)
    # The target environment is an operator label, not an independently
    # authenticated property of the database connection.  Fail closed for
    # every persistence invocation so a copied staging command cannot reach a
    # production URL without the second acknowledgement.
    if not config.production_ack:
        raise NstcSnapshotBackfillError(
            "persist mode requires --nstc-backfill-production-ack because "
            "the database target cannot be inferred from the environment label"
        )


def _read_snapshot(path: Path) -> bytes:
    if not path.is_file():
        raise NstcSnapshotBackfillError("NSTC snapshot input path must be a file")
    payload = path.read_bytes()
    if not payload:
        raise NstcSnapshotBackfillError("NSTC snapshot input file is empty")
    if len(payload) > MAX_NSTC_FLOOD_DISASTER_POINTS_BYTES:
        raise NstcSnapshotBackfillError("NSTC snapshot exceeds the reviewed byte limit")
    return payload


def _decode_snapshot(payload: bytes) -> str:
    for encoding in ("utf-8-sig", "cp950"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise NstcFloodDisasterPointsPayloadError("NSTC flood-disaster CSV is neither UTF-8 nor CP950")


def _input_year_counts(text: str) -> dict[int, int]:
    counts: Counter[int] = Counter()
    for row in csv.DictReader(StringIO(text)):
        try:
            year = int(str(row.get("year", "")).strip())
        except ValueError:
            continue
        counts[year] += 1
    return dict(counts)


def _normalized_sha256(value: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise NstcSnapshotBackfillError(
            "--nstc-backfill-expected-sha256 must be a 64-character SHA-256 digest"
        )
    return normalized


def _raw_ref(snapshot_sha256: str) -> str:
    return f"raw/official/nstc/flood_disaster_points/backfill/{snapshot_sha256}.csv"


def _validated_operator_review_ref(value: str | None) -> str:
    if value is None:
        raise NstcSnapshotBackfillError("persist mode requires --nstc-backfill-review-ref")
    if not value or value != value.strip() or "\n" in value or "\r" in value or len(value) > 180:
        raise NstcSnapshotBackfillError(
            "NSTC backfill review reference must be a trimmed single-line value "
            "of at most 180 characters"
        )
    return value


def _persisted_review_ref(value: str | None, snapshot_sha256: str) -> str | None:
    if value is None:
        return None
    return f"nstc-backfill:v1:{_validated_operator_review_ref(value)}:{snapshot_sha256}"


def _validate_reviewed_snapshot(
    *,
    row_count: int,
    input_year_counts: dict[int, int],
    normalized_year_counts: dict[int, int],
    normalized_count: int,
    rejected_count: int,
    rejection_reason_counts: dict[str, int],
    source_record_key_count: int,
) -> None:
    if row_count != NSTC_FROZEN_SNAPSHOT_ROW_COUNT:
        raise NstcSnapshotBackfillError(
            "NSTC frozen snapshot row count no longer matches the reviewed contract"
        )
    if input_year_counts != NSTC_FROZEN_SNAPSHOT_INPUT_YEAR_COUNTS:
        raise NstcSnapshotBackfillError(
            "NSTC frozen snapshot input year counts no longer match the reviewed contract"
        )
    if normalized_year_counts != NSTC_FROZEN_SNAPSHOT_NORMALIZED_YEAR_COUNTS:
        raise NstcSnapshotBackfillError(
            "NSTC frozen snapshot normalized year counts no longer match the reviewed contract"
        )
    if normalized_count != 5_919 or rejected_count != 4:
        raise NstcSnapshotBackfillError(
            "NSTC frozen snapshot acceptance counts no longer match the reviewed contract"
        )
    if rejection_reason_counts != NSTC_FROZEN_SNAPSHOT_REJECTION_REASON_COUNTS:
        raise NstcSnapshotBackfillError(
            "NSTC frozen snapshot rejection reasons no longer match the reviewed contract"
        )
    if source_record_key_count != normalized_count:
        raise NstcSnapshotBackfillError(
            "NSTC frozen snapshot accepted rows do not all have stable source-record keys"
        )
