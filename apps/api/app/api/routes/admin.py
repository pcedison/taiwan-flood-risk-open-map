from __future__ import annotations

from datetime import UTC, datetime, timedelta
import os
import secrets
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import psycopg
from psycopg.rows import dict_row

from app.api.errors import error_payload
from app.api.schemas import (
    AdminJobsResponse,
    AdminSourcesResponse,
    AdminUserReportPrivacyRedaction,
    AdminUserReport,
    AdminUserReportsResponse,
    DataSource,
    FreshnessState,
    HealthStatus,
    IngestionJob,
    JobStatus,
    LatLng,
    UserReportModerationRequest,
    UserReportModerationResponse,
    UserReportPrivacyRedactionRequest,
    UserReportPrivacyRedactionResponse,
)
from app.core.config import get_settings
from app.domain.reports import (
    UserReportModerationRecord,
    UserReportPrivacyRedactionRecord,
    UserReportRepositoryUnavailable,
    list_pending_user_reports,
    moderate_user_report,
    redact_user_report_privacy,
)


router = APIRouter(prefix="/admin/v1", tags=["Admin"])
admin_bearer = HTTPBearer(auto_error=False)
REALTIME_FRESH_SECONDS = 10 * 60
REALTIME_DEGRADED_SECONDS = 30 * 60
REALTIME_STALE_SECONDS = 60 * 60
REALTIME_ADAPTER_KEYS = frozenset(
    {
        "official.cwa.rainfall",
        "official.wra.water_level",
        "official.civil_iot.flood_sensor",
        "official.civil_iot.river_water_level",
        "official.civil_iot.pond_water_level",
        "official.civil_iot.sewer_water_level",
        "official.civil_iot.pump_water_level",
        "local.tainan.flood_sensor",
    }
)
STATIC_SLOW_CADENCE_ADAPTER_KEYS = frozenset({"official.flood_potential.geojson"})
SOURCE_GATE_NAMES = {
    "official.cwa.rainfall": ("SOURCE_CWA_ENABLED", "SOURCE_CWA_API_ENABLED"),
    "official.wra.water_level": ("SOURCE_WRA_ENABLED", "SOURCE_WRA_API_ENABLED"),
    "official.ncdr.cap": ("SOURCE_NCDR_CAP_ENABLED", "SOURCE_NCDR_CAP_API_ENABLED"),
    "official.flood_potential.geojson": (
        "SOURCE_FLOOD_POTENTIAL_ENABLED",
        "SOURCE_FLOOD_POTENTIAL_GEOJSON_ENABLED",
    ),
    "official.civil_iot.flood_sensor": (
        "SOURCE_FLOOD_SENSOR_ENABLED",
        "SOURCE_FLOOD_SENSOR_API_ENABLED",
    ),
    "official.civil_iot.river_water_level": (
        "SOURCE_CIVIL_IOT_RIVER_ENABLED",
        "SOURCE_CIVIL_IOT_RIVER_API_ENABLED",
    ),
    "official.civil_iot.pond_water_level": (
        "SOURCE_CIVIL_IOT_POND_ENABLED",
        "SOURCE_CIVIL_IOT_POND_API_ENABLED",
    ),
    "official.civil_iot.sewer_water_level": (
        "SOURCE_CIVIL_IOT_SEWER_ENABLED",
        "SOURCE_CIVIL_IOT_SEWER_API_ENABLED",
    ),
    "official.civil_iot.pump_water_level": (
        "SOURCE_CIVIL_IOT_PUMP_ENABLED",
        "SOURCE_CIVIL_IOT_PUMP_API_ENABLED",
    ),
    "local.tainan.flood_sensor": (
        "SOURCE_TAINAN_FLOOD_SENSOR_ENABLED",
        "SOURCE_TAINAN_FLOOD_SENSOR_API_ENABLED",
    ),
}
TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


@router.get("/jobs", response_model=AdminJobsResponse)
def list_admin_jobs(
    _admin: Annotated[str, Depends(_require_admin)],
    status: JobStatus | None = None,
    job_key: str | None = Query(default=None, min_length=1, max_length=120),
) -> AdminJobsResponse:
    settings = get_settings()
    try:
        jobs = _db_jobs(status=status, job_key=job_key)
    except (OSError, psycopg.Error) as exc:
        if settings.admin_sample_data_enabled:
            jobs = _filter_jobs(_sample_jobs(), status=status, job_key=job_key)
        else:
            raise _admin_repository_unavailable(
                "Admin jobs repository is temporarily unavailable."
            ) from exc
    return AdminJobsResponse(jobs=jobs)


@router.get("/sources", response_model=AdminSourcesResponse)
def list_admin_sources(
    _admin: Annotated[str, Depends(_require_admin)],
    health_status: HealthStatus | None = None,
) -> AdminSourcesResponse:
    settings = get_settings()
    try:
        sources = _db_sources(health_status=health_status)
    except (OSError, psycopg.Error) as exc:
        if settings.admin_sample_data_enabled:
            sources = _filter_sources(_sample_sources(), health_status=health_status)
        else:
            raise _admin_repository_unavailable(
                "Admin sources repository is temporarily unavailable."
            ) from exc
    return AdminSourcesResponse(sources=sources)


@router.get("/reports/pending", response_model=AdminUserReportsResponse)
def list_pending_admin_reports(
    _admin: Annotated[str, Depends(_require_admin)],
    limit: int = Query(default=100, ge=1, le=100),
) -> AdminUserReportsResponse:
    settings = get_settings()
    try:
        reports = list_pending_user_reports(database_url=settings.database_url, limit=limit)
    except UserReportRepositoryUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail=error_payload(
                "repository_unavailable",
                "User report moderation storage is temporarily unavailable.",
            )["error"],
        ) from exc
    return AdminUserReportsResponse(reports=[_admin_report_from_record(report) for report in reports])


@router.patch("/reports/{report_id}/moderation", response_model=UserReportModerationResponse)
def moderate_admin_report(
    report_id: UUID,
    request: UserReportModerationRequest,
    admin_actor: Annotated[str, Depends(_require_admin)],
) -> UserReportModerationResponse:
    settings = get_settings()
    try:
        report = moderate_user_report(
            database_url=settings.database_url,
            report_id=str(report_id),
            status=request.status,
            reason_code=request.reason_code,
            actor_ref=admin_actor,
        )
    except UserReportRepositoryUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail=error_payload(
                "repository_unavailable",
                "User report moderation storage is temporarily unavailable.",
            )["error"],
        ) from exc

    if report is None:
        raise HTTPException(
            status_code=404,
            detail=error_payload("not_found", "User report was not found.")["error"],
        )
    return UserReportModerationResponse(report=_admin_report_from_record(report))


@router.post(
    "/reports/{report_id}/privacy-redaction",
    response_model=UserReportPrivacyRedactionResponse,
)
def redact_admin_report_privacy(
    report_id: UUID,
    request: UserReportPrivacyRedactionRequest,
    admin_actor: Annotated[str, Depends(_require_admin)],
) -> UserReportPrivacyRedactionResponse:
    settings = get_settings()
    try:
        redaction = redact_user_report_privacy(
            database_url=settings.database_url,
            report_id=str(report_id),
            reason_code=request.reason_code,
            actor_ref=admin_actor,
        )
    except UserReportRepositoryUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail=error_payload(
                "repository_unavailable",
                "User report privacy redaction storage is temporarily unavailable.",
            )["error"],
        ) from exc

    if redaction is None:
        raise HTTPException(
            status_code=404,
            detail=error_payload("not_found", "User report was not found.")["error"],
        )
    return UserReportPrivacyRedactionResponse(
        redaction=_privacy_redaction_from_record(redaction)
    )


async def _require_admin(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(admin_bearer)],
) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail=error_payload("unauthorized", "Missing admin bearer token.")["error"],
        )

    settings = get_settings()
    if not settings.admin_bearer_token:
        raise HTTPException(
            status_code=403,
            detail=error_payload("forbidden", "Admin API is not configured.")["error"],
        )

    if not secrets.compare_digest(credentials.credentials, settings.admin_bearer_token):
        raise HTTPException(
            status_code=401,
            detail=error_payload("unauthorized", "Invalid admin bearer token.")["error"],
        )
    return "admin_api"


def _admin_repository_unavailable(message: str) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail=error_payload("repository_unavailable", message)["error"],
    )


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _db_jobs(*, status: JobStatus | None, job_key: str | None) -> list[IngestionJob]:
    where: list[str] = []
    params: list[str] = []
    if status is not None:
        where.append("status = %s")
        params.append(status)
    if job_key is not None:
        where.append("job_key = %s")
        params.append(job_key)

    query = """
        SELECT
            job_key,
            adapter_key,
            started_at,
            finished_at,
            status,
            items_fetched,
            items_promoted,
            items_rejected,
            error_code,
            error_message,
            source_timestamp_min,
            source_timestamp_max
        FROM ingestion_jobs
    """
    if where:
        query += " WHERE " + " AND ".join(where)
    query += " ORDER BY COALESCE(started_at, created_at) DESC, created_at DESC LIMIT 100"

    settings = get_settings()
    with psycopg.connect(settings.database_url, connect_timeout=2, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, params)
            return [IngestionJob(**row) for row in cursor.fetchall()]


def _db_sources(*, health_status: HealthStatus | None) -> list[DataSource]:
    where: list[str] = []
    params: list[str] = []
    if health_status is not None:
        where.append("ds.health_status = %s")
        params.append(health_status)

    query = """
        SELECT
            ds.id::text AS id,
            ds.name,
            ds.adapter_key,
            ds.source_type,
            ds.license,
            ds.update_frequency,
            ds.last_success_at,
            ds.last_failure_at,
            ds.health_status,
            ds.legal_basis,
            ds.source_timestamp_min,
            ds.source_timestamp_max,
            ds.is_enabled,
            COALESCE(latest.latest_observed_at, ds.source_timestamp_max) AS latest_observed_at,
            raw.latest_fetched_at,
            COALESCE(
                latest.latest_ingested_at,
                latest_run.finished_at,
                latest_job.finished_at,
                ds.last_success_at
            ) AS latest_ingested_at,
            COALESCE(latest.row_count, 0)::integer AS row_count,
            COALESCE(latest_run.status, latest_job.status, ds.health_status, 'unknown') AS upstream_status
        FROM data_sources ds
        LEFT JOIN (
            SELECT
                adapter_key,
                max(observed_at) AS latest_observed_at,
                max(ingested_at) AS latest_ingested_at,
                count(*) AS row_count
            FROM official_realtime_latest
            GROUP BY adapter_key
        ) latest ON latest.adapter_key = ds.adapter_key
        LEFT JOIN (
            SELECT DISTINCT ON (adapter_key)
                adapter_key,
                fetched_at AS latest_fetched_at
            FROM raw_snapshots
            ORDER BY adapter_key, fetched_at DESC
        ) raw ON raw.adapter_key = ds.adapter_key
        LEFT JOIN (
            SELECT DISTINCT ON (adapter_key)
                adapter_key,
                status,
                finished_at
            FROM adapter_runs
            ORDER BY adapter_key, COALESCE(finished_at, created_at) DESC
        ) latest_run ON latest_run.adapter_key = ds.adapter_key
        LEFT JOIN (
            SELECT DISTINCT ON (adapter_key)
                adapter_key,
                status,
                finished_at
            FROM ingestion_jobs
            WHERE adapter_key IS NOT NULL
            ORDER BY adapter_key, COALESCE(finished_at, created_at) DESC
        ) latest_job ON latest_job.adapter_key = ds.adapter_key
    """
    if where:
        query += " WHERE " + " AND ".join(where)
    query += " ORDER BY ds.name ASC, ds.adapter_key ASC LIMIT 100"

    settings = get_settings()
    with psycopg.connect(settings.database_url, connect_timeout=2, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, params)
            return [_data_source_from_row(row) for row in cursor.fetchall()]


def _filter_jobs(
    jobs: list[IngestionJob], *, status: JobStatus | None, job_key: str | None
) -> list[IngestionJob]:
    if status is not None:
        jobs = [job for job in jobs if job.status == status]
    if job_key is not None:
        jobs = [job for job in jobs if job.job_key == job_key]
    return jobs


def _filter_sources(
    sources: list[DataSource], *, health_status: HealthStatus | None
) -> list[DataSource]:
    if health_status is not None:
        sources = [source for source in sources if source.health_status == health_status]
    return sources


def _data_source_from_row(row: dict) -> DataSource:
    is_enabled = bool(row.get("is_enabled", True))
    health_status = row.get("health_status") or "unknown"
    if not is_enabled:
        health_status = "disabled"
    latest_observed_at = row.get("latest_observed_at") or row.get("source_timestamp_max")
    latest_ingested_at = row.get("latest_ingested_at") or row.get("last_success_at")
    upstream_status = _upstream_status(row, is_enabled=is_enabled)
    return DataSource(
        **{
            "id": row["id"],
            "name": row["name"],
            "adapter_key": row["adapter_key"],
            "source_type": row["source_type"],
            "license": row.get("license") or "",
            "update_frequency": row.get("update_frequency") or "",
            "last_success_at": row.get("last_success_at"),
            "last_failure_at": row.get("last_failure_at"),
            "health_status": health_status,
            "legal_basis": row["legal_basis"],
            "source_timestamp_min": row.get("source_timestamp_min"),
            "source_timestamp_max": row.get("source_timestamp_max"),
            "is_enabled": is_enabled,
            "latest_observed_at": latest_observed_at,
            "latest_fetched_at": row.get("latest_fetched_at"),
            "latest_ingested_at": latest_ingested_at,
            "lag_seconds": _lag_seconds(latest_observed_at),
            "row_count": row.get("row_count") or 0,
            "upstream_status": upstream_status,
            "enabled_gates": _enabled_gates(row["adapter_key"], is_enabled=is_enabled),
            "freshness_state": _freshness_state(
                adapter_key=row["adapter_key"],
                health_status=health_status,
                is_enabled=is_enabled,
                latest_observed_at=latest_observed_at,
                upstream_status=upstream_status,
            ),
        }
    )


def _upstream_status(row: dict, *, is_enabled: bool) -> str:
    if not is_enabled:
        return "disabled"
    return str(row.get("upstream_status") or row.get("health_status") or "unknown")


def _lag_seconds(latest_observed_at: datetime | None) -> int | None:
    if latest_observed_at is None:
        return None
    observed_at = _aware_utc(latest_observed_at)
    return max(0, int((_now() - observed_at).total_seconds()))


def _freshness_state(
    *,
    adapter_key: str,
    health_status: HealthStatus,
    is_enabled: bool,
    latest_observed_at: datetime | None,
    upstream_status: str,
) -> FreshnessState:
    if not is_enabled:
        return "stale"
    if upstream_status == "failed" or health_status == "failed":
        return "failed"
    if adapter_key in STATIC_SLOW_CADENCE_ADAPTER_KEYS:
        if latest_observed_at is not None or upstream_status == "succeeded":
            return "fresh"
        return "stale"
    if latest_observed_at is None:
        return "stale"
    if adapter_key in REALTIME_ADAPTER_KEYS:
        age_seconds = _lag_seconds(latest_observed_at)
        if age_seconds is None:
            return "stale"
        if age_seconds <= REALTIME_FRESH_SECONDS:
            return "fresh"
        if age_seconds <= REALTIME_DEGRADED_SECONDS:
            return "degraded"
        if age_seconds <= REALTIME_STALE_SECONDS:
            return "stale"
        return "failed"
    if health_status == "healthy":
        return "fresh"
    if health_status == "degraded":
        return "degraded"
    return "stale"


def _enabled_gates(adapter_key: str, *, is_enabled: bool) -> list[str]:
    if not is_enabled:
        return []
    gates = ["data_sources.is_enabled"]
    gates.extend(
        gate_name
        for gate_name in SOURCE_GATE_NAMES.get(adapter_key, ())
        if _env_flag_enabled(gate_name)
    )
    return gates


def _env_flag_enabled(name: str) -> bool:
    raw_value = os.getenv(name)
    return raw_value is not None and raw_value.strip().lower() in TRUE_VALUES


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _admin_report_from_record(report: UserReportModerationRecord) -> AdminUserReport:
    return AdminUserReport(
        report_id=report.id,
        status=report.status,
        point=LatLng(lat=report.lat, lng=report.lng),
        summary=report.summary,
        created_at=report.created_at,
        reviewed_at=report.reviewed_at,
    )


def _privacy_redaction_from_record(
    redaction: UserReportPrivacyRedactionRecord,
) -> AdminUserReportPrivacyRedaction:
    return AdminUserReportPrivacyRedaction(
        report_id=redaction.id,
        status=redaction.status,
        privacy_level=redaction.privacy_level,
        redacted_at=redaction.redacted_at,
    )


def _sample_jobs() -> list[IngestionJob]:
    now = _now()
    return [
        IngestionJob(
            job_key="ingest.cwa.rainfall",
            adapter_key="official.cwa.rainfall",
            started_at=now - timedelta(minutes=12),
            finished_at=now - timedelta(minutes=11),
            status="succeeded",
            items_fetched=2,
            items_promoted=2,
            items_rejected=0,
            source_timestamp_min=now - timedelta(minutes=20),
            source_timestamp_max=now - timedelta(minutes=15),
        ),
        IngestionJob(
            job_key="ingest.news.search",
            adapter_key="news.public_web.sample",
            started_at=now - timedelta(minutes=30),
            finished_at=now - timedelta(minutes=29),
            status="succeeded",
            items_fetched=2,
            items_promoted=2,
            items_rejected=0,
            source_timestamp_min=now - timedelta(hours=1),
            source_timestamp_max=now - timedelta(minutes=45),
        ),
    ]


def _sample_sources() -> list[DataSource]:
    now = _now()
    return [
        DataSource(
            id="cwa-rainfall",
            name="CWA rainfall observations",
            adapter_key="official.cwa.rainfall",
            source_type="official",
            license="Government open data",
            update_frequency="PT10M",
            last_success_at=now - timedelta(minutes=11),
            health_status="healthy",
            legal_basis="L1",
            source_timestamp_min=now - timedelta(minutes=20),
            source_timestamp_max=now - timedelta(minutes=15),
        ),
        DataSource(
            id="news-public-web-sample",
            name="Sample L2 public web evidence",
            adapter_key="news.public_web.sample",
            source_type="news",
            license="Fixture only",
            update_frequency="fixture_only",
            last_success_at=now - timedelta(minutes=29),
            health_status="healthy",
            legal_basis="L2",
            source_timestamp_min=now - timedelta(hours=1),
            source_timestamp_max=now - timedelta(minutes=45),
        ),
    ]
