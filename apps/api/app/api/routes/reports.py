from fastapi import APIRouter, HTTPException

from app.api.errors import error_payload
from app.api.schemas import UserReportCreateRequest, UserReportCreateResponse
from app.core.config import get_settings
from app.domain.reports import UserReportRepositoryUnavailable, create_pending_user_report

router = APIRouter(prefix="/v1", tags=["Public"])


@router.post("/reports", response_model=UserReportCreateResponse, status_code=202)
async def create_user_report(request: UserReportCreateRequest) -> UserReportCreateResponse:
    settings = get_settings()
    if not settings.user_reports_enabled:
        raise HTTPException(
            status_code=404,
            detail=error_payload(
                "feature_disabled",
                "User report intake is disabled until legal, privacy, abuse, and moderation gates are approved.",
            )["error"],
        )

    try:
        report = create_pending_user_report(
            database_url=settings.database_url,
            lat=request.point.lat,
            lng=request.point.lng,
            summary=request.summary,
        )
    except UserReportRepositoryUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail=error_payload(
                "repository_unavailable",
                "User report intake is temporarily unavailable.",
            )["error"],
        ) from exc

    return UserReportCreateResponse(report_id=report.id, status="pending")
