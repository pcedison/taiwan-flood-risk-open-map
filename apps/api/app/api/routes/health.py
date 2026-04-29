from datetime import UTC, datetime

from fastapi import APIRouter

from app.core.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    settings = get_settings()
    return {
        "status": "ok",
        "service": settings.service_id,
        "version": settings.app_version,
        "checked_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }

