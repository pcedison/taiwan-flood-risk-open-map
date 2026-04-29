from datetime import UTC, datetime

from fastapi import APIRouter, Response

from app.api.schemas import DependencyReadiness, HealthResponse, ReadyResponse
from app.core.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        service=settings.service_id,
        version=settings.app_version,
        checked_at=_now_utc(),
    )


@router.get("/ready", response_model=ReadyResponse, responses={503: {"model": ReadyResponse}})
async def ready(response: Response) -> ReadyResponse:
    settings = get_settings()
    dependencies = {
        "database": _check_database(settings.database_url),
        "redis": _check_redis(settings.redis_url),
    }
    is_ready = all(dependency.status == "healthy" for dependency in dependencies.values())
    if not is_ready:
        response.status_code = 503
    return ReadyResponse(
        status="ok" if is_ready else "down",
        service=settings.service_id,
        version=settings.app_version,
        checked_at=_now_utc(),
        dependencies=dependencies,
    )


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _check_database(database_url: str) -> DependencyReadiness:
    try:
        import psycopg

        with psycopg.connect(database_url, connect_timeout=2) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
    except Exception as exc:
        return DependencyReadiness(status="failed", checked_at=_now_utc(), message=str(exc))
    return DependencyReadiness(status="healthy", checked_at=_now_utc(), message=None)


def _check_redis(redis_url: str) -> DependencyReadiness:
    try:
        import redis

        client = redis.Redis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)
        client.ping()
        client.close()
    except Exception as exc:
        return DependencyReadiness(status="failed", checked_at=_now_utc(), message=str(exc))
    return DependencyReadiness(status="healthy", checked_at=_now_utc(), message=None)
