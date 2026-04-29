from __future__ import annotations

from datetime import UTC, datetime, timedelta
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

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
    jobs = _sample_jobs()
    if status is not None:
        jobs = [job for job in jobs if job.status == status]
    if job_key is not None:
        jobs = [job for job in jobs if job.job_key == job_key]
    return AdminJobsResponse(jobs=jobs)


@router.get("/sources", response_model=AdminSourcesResponse)
async def list_admin_sources(
    _admin: Annotated[None, Depends(_require_admin)],
    health_status: HealthStatus | None = None,
) -> AdminSourcesResponse:
    sources = _sample_sources()
    if health_status is not None:
        sources = [source for source in sources if source.health_status == health_status]
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
