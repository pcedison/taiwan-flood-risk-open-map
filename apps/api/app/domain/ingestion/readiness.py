from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

import psycopg
from psycopg.rows import dict_row


INGESTION_READINESS_PROFILE = "production_backbone"
INGESTION_SCHEDULER_KEY = "scheduler.v1-baseline-adapters"
EXPECTED_JURISDICTION_COUNT = 22
EXPECTED_PRODUCTION_BACKBONE_SOURCE_COUNT = 12
REQUIRED_SIGNAL_TYPES = ("rainfall", "water_level", "flood_depth", "flood_warning")

# Adapter failures are persisted as the raised exception class name in
# ``ingestion_jobs.error_code``. Suffix matching keeps one public-safe answer to
# "is this our bug or theirs?" as adapter-specific wrapper classes come and go,
# without exposing a URL, credential, or stack detail.
#
# Transport failures: the upstream never delivered a usable response at all
# (HTTP 5xx, DNS/TLS/socket failure, timeout, dropped connection). Nothing in
# this repository can fix that, and retrying on the next cycle is the remedy.
UPSTREAM_TRANSPORT_ERROR_CODE_SUFFIXES = (
    "ConnectionError",
    "FetchError",
    "HTTPError",
    "HttpError",
    "RemoteDisconnected",
    "TimeoutError",
    "URLError",
)
# Contract drift: the upstream answered, but the payload no longer matches the
# shape our parser was written against. The data is just as unavailable, yet the
# fix is an adapter change here, so this must keep counting as our failure.
UPSTREAM_CONTRACT_ERROR_CODE_SUFFIXES = ("PayloadError",)
# Everything else stays "run_failed", i.e. ours. In particular:
#   *ConfigurationError - a missing or invalid setting in our deployment.
#   *RateLimitError     - we exceeded the published quota; our polling cadence.
#   *AuthorizationError - our credential is missing, expired, or revoked.
# None of those are evidence that the upstream service is down, so excusing them
# as an outage would hide a failure only we can clear.

SchedulerReadinessStatus = Literal["healthy", "stale", "stopped", "missing"]
SourceReadinessStatus = Literal[
    "operational",
    "degraded",
    "stale",
    "failed",
    "disabled",
    "missing",
]
JurisdictionReadinessStatus = Literal["operational", "degraded", "unavailable"]
CoverageKind = Literal["national_realtime", "local_realtime", "nationwide_history"]


class IngestionReadinessRepositoryUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class IngestionSchedulerReadiness:
    status: SchedulerReadinessStatus
    checked_at: datetime
    last_heartbeat_at: datetime | None
    stale_after_seconds: int | None


@dataclass(frozen=True)
class IngestionSourceReadiness:
    adapter_key: str
    source_id: str
    name: str
    coverage_kind: CoverageKind
    status: SourceReadinessStatus
    reason_code: str
    checked_at: datetime | None
    last_attempted_at: datetime | None
    last_succeeded_at: datetime | None
    stale_after_seconds: int


@dataclass(frozen=True)
class IngestionJurisdictionReadiness:
    county_code: str
    county: str
    status: JurisdictionReadinessStatus
    operational_signal_count: int
    degraded_signal_count: int
    unavailable_signal_count: int


@dataclass(frozen=True)
class IngestionReadinessSnapshot:
    generated_at: datetime
    scheduler: IngestionSchedulerReadiness
    sources: tuple[IngestionSourceReadiness, ...]
    jurisdictions: tuple[IngestionJurisdictionReadiness, ...]


def fetch_ingestion_readiness(
    *,
    database_url: str,
    evaluated_at: datetime | None = None,
) -> IngestionReadinessSnapshot:
    checked_at = _normalized_utc(evaluated_at or datetime.now(UTC))
    try:
        with psycopg.connect(
            database_url,
            connect_timeout=2,
            row_factory=dict_row,
        ) as connection:
            scheduler_row = connection.execute(
                """
                SELECT runtime_status, last_seen_at, stale_after_seconds
                FROM ingestion_scheduler_heartbeats
                WHERE scheduler_key = %s
                """,
                (INGESTION_SCHEDULER_KEY,),
            ).fetchone()
            source_rows = connection.execute(
                _SOURCE_READINESS_SQL,
                (INGESTION_READINESS_PROFILE,),
            ).fetchall()
            contract_rows = connection.execute(
                _JURISDICTION_READINESS_SQL,
                (list(REQUIRED_SIGNAL_TYPES),),
            ).fetchall()
    except (OSError, psycopg.Error) as exc:
        raise IngestionReadinessRepositoryUnavailable(str(exc)) from exc

    scheduler = _scheduler_readiness(scheduler_row, evaluated_at=checked_at)
    sources = tuple(
        _source_readiness(row, evaluated_at=checked_at) for row in source_rows
    )
    jurisdictions = _jurisdiction_readiness(
        contract_rows,
        source_status_by_key={source.adapter_key: source.status for source in sources},
    )
    return IngestionReadinessSnapshot(
        generated_at=checked_at,
        scheduler=scheduler,
        sources=sources,
        jurisdictions=jurisdictions,
    )


def _scheduler_readiness(
    row: dict[str, object] | None,
    *,
    evaluated_at: datetime,
) -> IngestionSchedulerReadiness:
    if row is None:
        return IngestionSchedulerReadiness(
            status="missing",
            checked_at=evaluated_at,
            last_heartbeat_at=None,
            stale_after_seconds=None,
        )
    last_seen_at = cast(datetime, row["last_seen_at"])
    stale_after_seconds = int(cast(int, row["stale_after_seconds"]))
    runtime_status = str(row["runtime_status"])
    if runtime_status == "stopped":
        status: SchedulerReadinessStatus = "stopped"
    elif _age(evaluated_at, last_seen_at) > timedelta(seconds=stale_after_seconds):
        status = "stale"
    else:
        status = "healthy"
    return IngestionSchedulerReadiness(
        status=status,
        checked_at=evaluated_at,
        last_heartbeat_at=last_seen_at,
        stale_after_seconds=stale_after_seconds,
    )


def _source_readiness(
    row: dict[str, object],
    *,
    evaluated_at: datetime,
) -> IngestionSourceReadiness:
    stale_after_seconds = int(cast(int, row["stale_after_seconds"]))
    latest_run_at = cast(datetime | None, row.get("latest_run_at"))
    last_success_at = cast(datetime | None, row.get("last_success_at"))
    runtime_enabled_checked_at = cast(datetime | None, row.get("runtime_enabled_checked_at"))
    pipeline_checked_at = cast(datetime | None, row.get("runtime_pipeline_checked_at"))
    checked_at = _latest_timestamp(
        runtime_enabled_checked_at,
        pipeline_checked_at,
        latest_run_at,
        last_success_at,
        cast(datetime | None, row.get("last_failure_at")),
    )

    status: SourceReadinessStatus
    reason_code: str
    if not bool(row.get("is_registered")):
        status, reason_code = "missing", "catalog_missing"
    elif not bool(row.get("is_enabled")):
        status, reason_code = "disabled", "catalog_disabled"
    elif runtime_enabled_checked_at is None:
        status, reason_code = "missing", "runtime_selection_missing"
    elif _age(evaluated_at, runtime_enabled_checked_at) > timedelta(
        seconds=stale_after_seconds
    ):
        status, reason_code = "stale", "runtime_selection_stale"
    elif row.get("runtime_enabled") is not True:
        status, reason_code = "disabled", "runtime_disabled"
    elif latest_run_at is None:
        status, reason_code = "missing", "run_missing"
    elif _age(evaluated_at, latest_run_at) > timedelta(seconds=stale_after_seconds):
        status, reason_code = "stale", "run_stale"
    elif str(row.get("latest_run_status") or "") == "failed":
        # An upstream outage and a broken adapter both fail the run; only the
        # second one is ours to fix, so operators must be able to tell them
        # apart without reading a private error message.
        status = "failed"
        reason_code = _failed_run_reason_code(
            cast(str | None, row.get("latest_run_error_code"))
        )
    elif _pipeline_failed_for_latest_run(row, latest_run_at):
        status, reason_code = "failed", "pipeline_failed"
    elif str(row.get("latest_run_status") or "") != "succeeded":
        status, reason_code = "degraded", "run_incomplete"
    elif not _pipeline_complete_for_latest_run(row, latest_run_at):
        status, reason_code = "degraded", "pipeline_incomplete"
    else:
        status, reason_code = "operational", "operational"

    adapter_key = str(row["adapter_key"])
    return IngestionSourceReadiness(
        adapter_key=adapter_key,
        source_id=_public_source_id(adapter_key),
        name=str(row["name"]),
        coverage_kind=cast(CoverageKind, str(row["coverage_kind"])),
        status=status,
        reason_code=reason_code,
        checked_at=checked_at,
        last_attempted_at=latest_run_at,
        last_succeeded_at=last_success_at,
        stale_after_seconds=stale_after_seconds,
    )


def _failed_run_reason_code(error_code: str | None) -> str:
    code = error_code or ""
    if code.endswith(UPSTREAM_TRANSPORT_ERROR_CODE_SUFFIXES):
        return "upstream_unavailable"
    if code.endswith(UPSTREAM_CONTRACT_ERROR_CODE_SUFFIXES):
        return "upstream_contract_changed"
    return "run_failed"


def _jurisdiction_readiness(
    rows: list[dict[str, object]],
    *,
    source_status_by_key: dict[str, SourceReadinessStatus],
) -> tuple[IngestionJurisdictionReadiness, ...]:
    by_county: dict[tuple[str, str], list[JurisdictionReadinessStatus]] = {}
    for row in rows:
        county_key = (str(row["jurisdiction_code"]), str(row["jurisdiction_name"]))
        required_adapter_keys = tuple(
            str(value) for value in cast(list[object] | None, row.get("required_adapter_keys")) or ()
        )
        if not bool(row.get("mapping_proof_valid")) or not required_adapter_keys:
            signal_status: JurisdictionReadinessStatus = "unavailable"
        else:
            required_statuses = tuple(
                source_status_by_key.get(adapter_key, "missing")
                for adapter_key in required_adapter_keys
            )
            if all(status == "operational" for status in required_statuses):
                signal_status = "operational"
            elif any(
                status in {"stale", "failed", "disabled", "missing"}
                for status in required_statuses
            ):
                signal_status = "unavailable"
            else:
                signal_status = "degraded"
        by_county.setdefault(county_key, []).append(signal_status)

    result = []
    for (county_code, county), signal_statuses in sorted(by_county.items()):
        operational_count = signal_statuses.count("operational")
        degraded_count = signal_statuses.count("degraded")
        unavailable_count = signal_statuses.count("unavailable")
        if len(signal_statuses) != len(REQUIRED_SIGNAL_TYPES) or unavailable_count:
            status: JurisdictionReadinessStatus = "unavailable"
        elif degraded_count:
            status = "degraded"
        else:
            status = "operational"
        result.append(
            IngestionJurisdictionReadiness(
                county_code=county_code,
                county=county,
                status=status,
                operational_signal_count=operational_count,
                degraded_signal_count=degraded_count,
                unavailable_signal_count=(
                    unavailable_count
                    + max(0, len(REQUIRED_SIGNAL_TYPES) - len(signal_statuses))
                ),
            )
        )
    return tuple(result)


def _pipeline_failed_for_latest_run(row: dict[str, object], latest_run_at: datetime) -> bool:
    if str(row.get("runtime_pipeline_status") or "") != "failed":
        return False
    pipeline_run_at = cast(datetime | None, row.get("runtime_pipeline_run_at"))
    pipeline_checked_at = cast(datetime | None, row.get("runtime_pipeline_checked_at"))
    comparison = pipeline_run_at or pipeline_checked_at
    return comparison is not None and _normalized_utc(comparison) >= _normalized_utc(latest_run_at)


def _pipeline_complete_for_latest_run(row: dict[str, object], latest_run_at: datetime) -> bool:
    pipeline_run_at = cast(datetime | None, row.get("runtime_pipeline_run_at"))
    return (
        bool(row.get("runtime_pipeline_complete"))
        and str(row.get("runtime_pipeline_status") or "") == "succeeded"
        and pipeline_run_at is not None
        and _normalized_utc(pipeline_run_at) == _normalized_utc(latest_run_at)
    )


def _public_source_id(adapter_key: str) -> str:
    normalized = "".join(
        character if character.isalnum() else "-" for character in adapter_key.lower()
    )
    return "-".join(part for part in normalized.split("-") if part)[:120]


def _latest_timestamp(*values: datetime | None) -> datetime | None:
    present = tuple(value for value in values if value is not None)
    return max(present, key=_normalized_utc) if present else None


def _age(now: datetime, value: datetime) -> timedelta:
    return max(timedelta(0), _normalized_utc(now) - _normalized_utc(value))


def _normalized_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


_SOURCE_READINESS_SQL = """
    WITH requested AS (
        SELECT adapter_key, coverage_kind, stale_after_seconds
        FROM ingestion_readiness_sources
        WHERE profile_key = %s
    ),
    latest_jobs AS (
        SELECT DISTINCT ON (jobs.adapter_key)
            jobs.id,
            jobs.adapter_key,
            jobs.status,
            jobs.error_code AS latest_run_error_code,
            COALESCE(jobs.started_at, jobs.created_at) AS latest_run_at
        FROM ingestion_jobs jobs
        JOIN requested ON requested.adapter_key = jobs.adapter_key
        ORDER BY
            jobs.adapter_key,
            COALESCE(jobs.started_at, jobs.created_at) DESC,
            jobs.created_at DESC,
            jobs.id DESC
    ),
    latest_runtime AS (
        SELECT
            latest_job.adapter_key,
            CASE
                WHEN adapter_run.status = 'partial' THEN 'partial'
                ELSE latest_job.status
            END AS latest_run_status,
            latest_job.latest_run_error_code,
            latest_job.latest_run_at
        FROM latest_jobs latest_job
        LEFT JOIN adapter_runs adapter_run
            ON adapter_run.ingestion_job_id = latest_job.id
            AND adapter_run.adapter_key = latest_job.adapter_key
    )
    SELECT
        requested.adapter_key,
        requested.coverage_kind,
        requested.stale_after_seconds,
        (source.adapter_key IS NOT NULL) AS is_registered,
        COALESCE(source.metadata->>'label_zh', source.name, requested.adapter_key) AS name,
        COALESCE(source.is_enabled, false) AS is_enabled,
        source.last_success_at,
        source.last_failure_at,
        source.runtime_enabled,
        source.runtime_enabled_checked_at,
        source.runtime_pipeline_status,
        source.runtime_pipeline_checked_at,
        source.runtime_pipeline_run_at,
        COALESCE(source.runtime_pipeline_complete, false) AS runtime_pipeline_complete,
        latest_runtime.latest_run_status,
        latest_runtime.latest_run_error_code,
        latest_runtime.latest_run_at
    FROM requested
    LEFT JOIN data_sources source ON source.adapter_key = requested.adapter_key
    LEFT JOIN latest_runtime ON latest_runtime.adapter_key = requested.adapter_key
    ORDER BY requested.adapter_key
"""


_JURISDICTION_READINESS_SQL = """
    WITH contract_mapping_rows AS (
        SELECT
            jurisdiction.jurisdiction_code,
            jurisdiction.jurisdiction_name,
            contract.signal_type,
            contract.catalog_status,
            contract.mapping_revision AS contract_mapping_revision,
            contract.mapping_manifest_version,
            contract.approved_mapping_count,
            contract.approved_mapping_manifest_sha256,
            contract.reviewed_at,
            contract.review_ref,
            mapping.adapter_key,
            mapping.coverage_scope,
            mapping.jurisdiction_code AS mapping_jurisdiction_code,
            mapping.requirement_role,
            mapping.redundancy_of_adapter_key,
            mapping.mapping_revision,
            CASE
                WHEN mapping.adapter_key IS NULL THEN false
                WHEN mapping.requirement_role <> 'redundant_subset' THEN true
                ELSE EXISTS (
                    SELECT 1
                    FROM realtime_source_jurisdictions parent_mapping
                    WHERE parent_mapping.adapter_key = mapping.redundancy_of_adapter_key
                        AND parent_mapping.signal_type = mapping.signal_type
                        AND parent_mapping.requirement_role = 'required'
                        AND parent_mapping.mapping_revision = mapping.mapping_revision
                        AND (
                            parent_mapping.coverage_scope = 'national'
                            OR parent_mapping.jurisdiction_code = contract.jurisdiction_code
                        )
                )
            END AS redundancy_parent_valid
        FROM realtime_jurisdictions jurisdiction
        JOIN realtime_jurisdiction_signal_contracts contract
            ON contract.jurisdiction_code = jurisdiction.jurisdiction_code
        LEFT JOIN realtime_source_jurisdictions mapping
            ON mapping.signal_type = contract.signal_type
            AND mapping.mapping_revision = contract.mapping_revision
            AND (
                mapping.coverage_scope = 'national'
                OR mapping.jurisdiction_code = contract.jurisdiction_code
            )
        WHERE contract.signal_type = ANY(%s::text[])
    ),
    manifests AS (
        SELECT
            jurisdiction_code,
            jurisdiction_name,
            signal_type,
            catalog_status,
            contract_mapping_revision,
            mapping_manifest_version,
            approved_mapping_count,
            approved_mapping_manifest_sha256,
            reviewed_at,
            review_ref,
            count(adapter_key)::integer AS actual_mapping_count,
            array_agg(adapter_key ORDER BY adapter_key)
                FILTER (WHERE requirement_role = 'required') AS required_adapter_keys,
            COALESCE(
                jsonb_agg(
                    jsonb_build_array(
                        adapter_key,
                        signal_type,
                        coverage_scope,
                        mapping_jurisdiction_code,
                        requirement_role,
                        redundancy_of_adapter_key,
                        mapping_revision
                    )
                    ORDER BY
                        adapter_key,
                        coverage_scope,
                        mapping_jurisdiction_code,
                        requirement_role,
                        redundancy_of_adapter_key,
                        mapping_revision
                ) FILTER (WHERE adapter_key IS NOT NULL),
                '[]'::jsonb
            ) AS mapping_manifest,
            COALESCE(
                bool_and(mapping_revision = contract_mapping_revision)
                    FILTER (WHERE adapter_key IS NOT NULL),
                false
            ) AS mapping_revision_consistent,
            COALESCE(
                bool_and(redundancy_parent_valid)
                    FILTER (WHERE adapter_key IS NOT NULL),
                false
            ) AS redundancy_valid
        FROM contract_mapping_rows
        GROUP BY
            jurisdiction_code,
            jurisdiction_name,
            signal_type,
            catalog_status,
            contract_mapping_revision,
            mapping_manifest_version,
            approved_mapping_count,
            approved_mapping_manifest_sha256,
            reviewed_at,
            review_ref
    )
    SELECT
        jurisdiction_code,
        jurisdiction_name,
        signal_type,
        required_adapter_keys,
        (
            catalog_status = 'reviewed_complete'
            AND mapping_manifest_version = 'jurisdiction-source-jsonb-v1'
            AND reviewed_at IS NOT NULL
            AND review_ref IS NOT NULL
            AND actual_mapping_count > 0
            AND actual_mapping_count = approved_mapping_count
            AND encode(
                digest(convert_to(mapping_manifest::text, 'UTF8'), 'sha256'),
                'hex'
            ) = approved_mapping_manifest_sha256
            AND mapping_revision_consistent
            AND redundancy_valid
        ) AS mapping_proof_valid
    FROM manifests
    ORDER BY jurisdiction_code, signal_type
"""
