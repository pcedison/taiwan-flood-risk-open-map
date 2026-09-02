from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal


ConnectionFactory = Callable[[], Any]
CoverageGapStatus = Literal["not_published", "failed"]

HISTORICAL_COVERAGE_GAP_REVIEW_SCHEMA = "historical-coverage-gap-review/v1"
HISTORICAL_COVERAGE_GAP_REVIEW_WINDOW = (2012, 2026)
HISTORICAL_COVERAGE_GAP_REVIEW_JURISDICTIONS = 22
HISTORICAL_COVERAGE_GAP_REVIEW_CELL_COUNT = 330
APPROVED_HISTORICAL_SOURCE_URLS = {
    "official.wra.historical_flood": "https://data.gov.tw/dataset/25770",
    "official.nstc.flood_disaster_points": "https://data.gov.tw/dataset/130016",
}


class HistoricalCoverageGapReviewError(RuntimeError):
    pass


@dataclass(frozen=True)
class HistoricalSourceGapReview:
    review_id: str
    adapter_key: str
    official_dataset_url: str
    resource_url: str
    revision: str
    observed_years: tuple[int, ...]
    fetched_count: int
    normalized_count: int
    rejected_count: int
    outcome: Literal["year_absent_from_snapshot"]


@dataclass(frozen=True)
class HistoricalCoverageGapTarget:
    year: int
    status: CoverageGapStatus
    source_review_ids: tuple[str, ...]
    status_reason: str


@dataclass(frozen=True)
class HistoricalCoverageGapReviewManifest:
    review_ref: str
    reviewed_at: datetime
    source_reviews: tuple[HistoricalSourceGapReview, ...]
    targets: tuple[HistoricalCoverageGapTarget, ...]

    @property
    def target_cell_count(self) -> int:
        return len(self.targets) * HISTORICAL_COVERAGE_GAP_REVIEW_JURISDICTIONS

    def adapter_keys_for(self, target: HistoricalCoverageGapTarget) -> tuple[str, ...]:
        by_id = {review.review_id: review.adapter_key for review in self.source_reviews}
        return tuple(sorted({by_id[review_id] for review_id in target.source_review_ids}))


@dataclass(frozen=True)
class HistoricalCoverageGapReviewResult:
    manifest_sha256: str
    persisted_review_ref: str
    target_cell_count: int
    would_update_cell_count: int
    applied_cell_count: int
    preserved_cell_count: int
    remaining_unassessed_cell_count: int
    status_counts: dict[str, int]

    def as_payload(self) -> dict[str, Any]:
        return {
            "manifest_sha256": self.manifest_sha256,
            "persisted_review_ref": self.persisted_review_ref,
            "target_cell_count": self.target_cell_count,
            "would_update_cell_count": self.would_update_cell_count,
            "applied_cell_count": self.applied_cell_count,
            "preserved_cell_count": self.preserved_cell_count,
            "remaining_unassessed_cell_count": self.remaining_unassessed_cell_count,
            "status_counts": dict(sorted(self.status_counts.items())),
        }


def load_historical_coverage_gap_review(
    path: Path,
    *,
    expected_sha256: str,
    now: datetime | None = None,
) -> tuple[HistoricalCoverageGapReviewManifest, str]:
    if not path.is_file():
        raise HistoricalCoverageGapReviewError(
            "historical coverage review manifest path must be a file"
        )
    payload = path.read_bytes()
    if not payload or len(payload) > 256 * 1024:
        raise HistoricalCoverageGapReviewError(
            "historical coverage review manifest is empty or too large"
        )
    actual_sha256 = hashlib.sha256(payload).hexdigest()
    if actual_sha256 != _normalized_sha256(expected_sha256):
        raise HistoricalCoverageGapReviewError(
            "historical coverage review manifest SHA-256 does not match"
        )
    try:
        raw = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HistoricalCoverageGapReviewError(
            "historical coverage review manifest must be UTF-8 JSON"
        ) from exc
    manifest = _manifest_from_raw(raw, now=now or datetime.now(UTC))
    return manifest, actual_sha256


class PostgresHistoricalCoverageGapReviewWriter:
    def __init__(
        self,
        *,
        database_url: str | None = None,
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        if database_url is None and connection_factory is None:
            raise ValueError("database_url or connection_factory is required")
        self._database_url = database_url
        self._connection_factory = connection_factory

    def assess(
        self,
        manifest: HistoricalCoverageGapReviewManifest,
        *,
        manifest_sha256: str,
        persist: bool,
    ) -> HistoricalCoverageGapReviewResult:
        persisted_review_ref = _persisted_review_ref(manifest, manifest_sha256)
        with self._connect() as connection:
            with connection.cursor() as cursor:
                _require_exact_coverage_matrix(cursor)
                target_rows = _target_rows(cursor, manifest.targets)
                expected_target_rows = manifest.target_cell_count
                if len(target_rows) != expected_target_rows:
                    raise HistoricalCoverageGapReviewError(
                        "historical coverage review target matrix is incomplete"
                    )
                would_update = sum(
                    status == "unassessed" for _code, _year, status, _review_ref in target_rows
                )
                newly_assessed_unassessed = would_update
                preserved = expected_target_rows - would_update
                applied = 0
                if persist:
                    for target in manifest.targets:
                        adapter_keys = manifest.adapter_keys_for(target)
                        cursor.execute(
                            _APPLY_GAP_REVIEW_SQL,
                            (
                                target.status,
                                len(adapter_keys),
                                list(adapter_keys),
                                manifest.reviewed_at,
                                manifest.reviewed_at,
                                persisted_review_ref,
                                target.status_reason,
                                target.year,
                            ),
                        )
                        applied += cursor.rowcount
                status_counts = _status_counts(cursor)
                remaining_unassessed = status_counts.get("unassessed", 0)
            if persist:
                connection.commit()
            else:
                connection.rollback()
        return HistoricalCoverageGapReviewResult(
            manifest_sha256=manifest_sha256,
            persisted_review_ref=persisted_review_ref,
            target_cell_count=expected_target_rows,
            would_update_cell_count=would_update,
            applied_cell_count=applied,
            preserved_cell_count=preserved,
            remaining_unassessed_cell_count=(
                remaining_unassessed - newly_assessed_unassessed
                if not persist
                else remaining_unassessed
            ),
            status_counts=_simulated_status_counts(
                status_counts,
                manifest=manifest,
                target_rows=target_rows,
                persisted=persist,
            ),
        )

    def _connect(self) -> Any:
        if self._connection_factory is not None:
            return self._connection_factory()
        import psycopg

        assert self._database_url is not None
        return psycopg.connect(self._database_url)


def _manifest_from_raw(
    value: object,
    *,
    now: datetime,
) -> HistoricalCoverageGapReviewManifest:
    raw = _mapping(value, "manifest")
    if raw.get("schema_version") != HISTORICAL_COVERAGE_GAP_REVIEW_SCHEMA:
        raise HistoricalCoverageGapReviewError(
            "unsupported historical coverage review schema_version"
        )
    if raw.get("absence_is_safety_evidence") is not False:
        raise HistoricalCoverageGapReviewError(
            "coverage review must declare absence_is_safety_evidence=false"
        )
    if raw.get("data_coverage_complete") is not False:
        raise HistoricalCoverageGapReviewError(
            "coverage review must declare data_coverage_complete=false"
        )
    window = _mapping(raw.get("window"), "window")
    if (
        window.get("start_year"),
        window.get("end_year"),
        window.get("jurisdiction_count"),
    ) != (*HISTORICAL_COVERAGE_GAP_REVIEW_WINDOW, 22):
        raise HistoricalCoverageGapReviewError(
            "coverage review window must be exactly 2012-2026 across 22 jurisdictions"
        )
    review_ref = _trimmed(raw.get("review_ref"), "review_ref", maximum=180)
    reviewed_at = _aware_datetime(raw.get("reviewed_at"), "reviewed_at")
    if reviewed_at > now.astimezone(UTC) + timedelta(minutes=5):
        raise HistoricalCoverageGapReviewError("reviewed_at cannot be in the future")
    source_reviews = tuple(
        _source_review(item) for item in _list(raw.get("source_reviews"), "source_reviews")
    )
    if not source_reviews:
        raise HistoricalCoverageGapReviewError("source_reviews must not be empty")
    source_ids = [review.review_id for review in source_reviews]
    if len(source_ids) != len(set(source_ids)):
        raise HistoricalCoverageGapReviewError("source review IDs must be unique")
    targets = tuple(_target(item) for item in _list(raw.get("targets"), "targets"))
    if not targets or len({target.year for target in targets}) != len(targets):
        raise HistoricalCoverageGapReviewError("target years must be non-empty and unique")
    review_by_id = {review.review_id: review for review in source_reviews}
    for target in targets:
        if not target.source_review_ids:
            raise HistoricalCoverageGapReviewError(
                "every target must reference at least one source review"
            )
        unknown = set(target.source_review_ids).difference(review_by_id)
        if unknown:
            raise HistoricalCoverageGapReviewError("target references an unknown source review")
        if any(
            target.year in review_by_id[item].observed_years for item in target.source_review_ids
        ):
            raise HistoricalCoverageGapReviewError(
                "gap target year is present in a linked source snapshot"
            )
    return HistoricalCoverageGapReviewManifest(
        review_ref=review_ref,
        reviewed_at=reviewed_at,
        source_reviews=source_reviews,
        targets=targets,
    )


def _source_review(value: object) -> HistoricalSourceGapReview:
    raw = _mapping(value, "source_review")
    adapter_key = _trimmed(raw.get("adapter_key"), "adapter_key", maximum=128)
    official_url = _trimmed(
        raw.get("official_dataset_url"),
        "official_dataset_url",
        maximum=512,
    )
    if APPROVED_HISTORICAL_SOURCE_URLS.get(adapter_key) != official_url:
        raise HistoricalCoverageGapReviewError(
            "source review adapter and official dataset URL are not approved"
        )
    observed_years = tuple(
        sorted(
            {
                _integer(year, "observed_year")
                for year in _list(raw.get("observed_years"), "observed_years")
            }
        )
    )
    if not observed_years:
        raise HistoricalCoverageGapReviewError("observed_years must not be empty")
    outcome = raw.get("outcome")
    if outcome != "year_absent_from_snapshot":
        raise HistoricalCoverageGapReviewError("source review outcome is unsupported")
    return HistoricalSourceGapReview(
        review_id=_trimmed(raw.get("review_id"), "review_id", maximum=128),
        adapter_key=adapter_key,
        official_dataset_url=official_url,
        resource_url=_https_url(raw.get("resource_url"), "resource_url"),
        revision=_trimmed(raw.get("revision"), "revision", maximum=256),
        observed_years=observed_years,
        fetched_count=_nonnegative_integer(raw.get("fetched_count"), "fetched_count"),
        normalized_count=_nonnegative_integer(raw.get("normalized_count"), "normalized_count"),
        rejected_count=_nonnegative_integer(raw.get("rejected_count"), "rejected_count"),
        outcome=outcome,
    )


def _target(value: object) -> HistoricalCoverageGapTarget:
    raw = _mapping(value, "target")
    year = _integer(raw.get("year"), "target year")
    if not (
        HISTORICAL_COVERAGE_GAP_REVIEW_WINDOW[0] <= year <= HISTORICAL_COVERAGE_GAP_REVIEW_WINDOW[1]
    ):
        raise HistoricalCoverageGapReviewError("target year is outside the reviewed window")
    status = raw.get("status")
    if status not in ("not_published", "failed"):
        raise HistoricalCoverageGapReviewError("gap review status is unsupported")
    source_review_ids = tuple(
        dict.fromkeys(
            _trimmed(item, "source_review_id", maximum=128)
            for item in _list(raw.get("source_review_ids"), "source_review_ids")
        )
    )
    return HistoricalCoverageGapTarget(
        year=year,
        status=status,
        source_review_ids=source_review_ids,
        status_reason=_trimmed(raw.get("status_reason"), "status_reason", maximum=1000),
    )


def _require_exact_coverage_matrix(cursor: Any) -> None:
    cursor.execute(
        """
        SELECT
            count(*)::integer,
            count(DISTINCT jurisdiction_code)::integer,
            count(DISTINCT coverage_year)::integer,
            min(coverage_year)::integer,
            max(coverage_year)::integer
        FROM historical_coverage_cells
        """
    )
    row = cursor.fetchone()
    expected = (330, 22, 15, 2012, 2026)
    if row is None or tuple(int(value) for value in row) != expected:
        raise HistoricalCoverageGapReviewError(
            "historical coverage matrix must be exactly 22 x 15 for 2012-2026"
        )


def _target_rows(
    cursor: Any,
    targets: tuple[HistoricalCoverageGapTarget, ...],
) -> tuple[tuple[str, int, str, str | None], ...]:
    cursor.execute(
        """
        SELECT jurisdiction_code, coverage_year, status, review_ref
        FROM historical_coverage_cells
        WHERE coverage_year = ANY(%s::integer[])
        ORDER BY coverage_year, jurisdiction_code
        """,
        ([target.year for target in targets],),
    )
    return tuple(
        (
            str(row[0]),
            int(row[1]),
            str(row[2]),
            str(row[3]) if row[3] is not None else None,
        )
        for row in cursor.fetchall()
    )


def _status_counts(cursor: Any) -> dict[str, int]:
    cursor.execute(
        """
        SELECT status, count(*)::integer
        FROM historical_coverage_cells
        GROUP BY status
        ORDER BY status
        """
    )
    return {str(row[0]): int(row[1]) for row in cursor.fetchall()}


def _simulated_status_counts(
    status_counts: dict[str, int],
    *,
    manifest: HistoricalCoverageGapReviewManifest,
    target_rows: tuple[tuple[str, int, str, str | None], ...],
    persisted: bool,
) -> dict[str, int]:
    if persisted:
        return status_counts
    simulated = Counter(status_counts)
    target_by_year = {target.year: target for target in manifest.targets}
    updated = 0
    for _code, year, status, _existing_review_ref in target_rows:
        if status != "unassessed":
            continue
        target_status = target_by_year[year].status
        simulated[status] -= 1
        simulated[target_status] += 1
        updated += 1
    if sum(simulated.values()) != HISTORICAL_COVERAGE_GAP_REVIEW_CELL_COUNT:
        raise HistoricalCoverageGapReviewError(
            f"coverage dry-run simulation lost cells while updating {updated} targets"
        )
    return {status: count for status, count in simulated.items() if count}


def _persisted_review_ref(
    manifest: HistoricalCoverageGapReviewManifest,
    manifest_sha256: str,
) -> str:
    return f"coverage-gap-review:v1:{manifest.review_ref}:{manifest_sha256}"


_APPLY_GAP_REVIEW_SQL = """
    UPDATE historical_coverage_cells
    SET
        status = %s,
        record_count = 0,
        checked_source_count = %s,
        successful_source_count = 0,
        source_adapter_keys = %s::text[],
        assessed_at = %s,
        last_attempted_at = %s,
        last_succeeded_at = NULL,
        review_ref = %s,
        status_reason = %s,
        updated_at = now()
    WHERE coverage_year = %s
      AND status = 'unassessed'
"""


def _normalized_sha256(value: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise HistoricalCoverageGapReviewError(
            "expected manifest SHA-256 must be a 64-character digest"
        )
    return normalized


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise HistoricalCoverageGapReviewError(f"{label} must be an object")
    return value


def _list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise HistoricalCoverageGapReviewError(f"{label} must be an array")
    return value


def _trimmed(value: object, label: str, *, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\n" in value
        or "\r" in value
        or len(value) > maximum
    ):
        raise HistoricalCoverageGapReviewError(f"{label} must be a trimmed string")
    return value


def _aware_datetime(value: object, label: str) -> datetime:
    raw = _trimmed(value, label, maximum=64)
    normalized = f"{raw[:-1]}+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise HistoricalCoverageGapReviewError(f"{label} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise HistoricalCoverageGapReviewError(f"{label} must include a timezone")
    return parsed.astimezone(UTC)


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise HistoricalCoverageGapReviewError(f"{label} must be an integer")
    return value


def _nonnegative_integer(value: object, label: str) -> int:
    parsed = _integer(value, label)
    if parsed < 0:
        raise HistoricalCoverageGapReviewError(f"{label} must not be negative")
    return parsed


def _https_url(value: object, label: str) -> str:
    parsed = _trimmed(value, label, maximum=1000)
    if not parsed.startswith("https://"):
        raise HistoricalCoverageGapReviewError(f"{label} must use HTTPS")
    return parsed
