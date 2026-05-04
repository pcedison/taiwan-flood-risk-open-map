from __future__ import annotations

from datetime import UTC, datetime, timedelta
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


@router.get("/jobs", response_model=AdminJobsResponse)
async def list_admin_jobs(
    _admin: Annotated[str, Depends(_require_admin)],
    status: JobStatus | None = None,
    job_key: str | None = Query(default=None, min_length=1, max_length=120),
) -> AdminJobsResponse:
    try:
        jobs = _db_jobs(status=status, job_key=job_key)
    except (OSError, psycopg.Error):
        jobs = _filter_jobs(_sample_jobs(), status=status, job_key=job_key)
    return AdminJobsResponse(jobs=jobs)


@router.get("/sources", response_model=AdminSourcesResponse)
async def list_admin_sources(
    _admin: Annotated[str, Depends(_require_admin)],
    health_status: HealthStatus | None = None,
) -> AdminSourcesResponse:
    try:
        sources = _db_sources(health_status=health_status)
    except (OSError, psycopg.Error):
        sources = _filter_sources(_sample_sources(), health_status=health_status)
    return AdminSourcesResponse(sources=sources)


@router.get("/reports/pending", response_model=AdminUserReportsResponse)
async def list_pending_admin_reports(
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
async def moderate_admin_report(
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
async def redact_admin_report_privacy(
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
        where.append("health_status = %s")
        params.append(health_status)

    query = """
        SELECT
            id::text AS id,
            name,
            adapter_key,
            source_type,
            license,
            update_frequency,
            last_success_at,
            last_failure_at,
            health_status,
            legal_basis,
            source_timestamp_min,
            source_timestamp_max
        FROM data_sources
    """
    if where:
        query += " WHERE " + " AND ".join(where)
    query += " ORDER BY name ASC, adapter_key ASC LIMIT 100"

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
    return DataSource(
        **{
            **row,
            "license": row.get("license") or "",
            "update_frequency": row.get("update_frequency") or "",
        }
    )


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
