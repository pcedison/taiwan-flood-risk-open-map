from __future__ import annotations

from datetime import UTC, datetime, timedelta
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import psycopg
from psycopg.rows import dict_row

from app.api.errors import error_payload
from app.api.schemas import (
    AdminJobsResponse,
    AdminSourcesResponse,
    DataSource,
    HealthStatus,
    IngestionJob,
    JobStatus,
)
from app.core.config import get_settings


router = APIRouter(prefix="/admin/v1", tags=["Admin"])
admin_bearer = HTTPBearer(auto_error=False)


@router.get("/jobs", response_model=AdminJobsResponse)
async def list_admin_jobs(
    _admin: Annotated[None, Depends(_require_admin)],
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
    _admin: Annotated[None, Depends(_require_admin)],
    health_status: HealthStatus | None = None,
) -> AdminSourcesResponse:
    try:
        sources = _db_sources(health_status=health_status)
    except (OSError, psycopg.Error):
        sources = _filter_sources(_sample_sources(), health_status=health_status)
    return AdminSourcesResponse(sources=sources)


async def _require_admin(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(admin_bearer)],
) -> None:
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
