from datetime import UTC, datetime

from fastapi import APIRouter, Response
from fastapi.responses import PlainTextResponse

from app.api.schemas import DependencyReadiness, HealthResponse, ReadyResponse
from app.core.config import get_settings
from app.domain.geocoding.postgis_bootstrap import fetch_postgis_geocoder_summary

router = APIRouter(tags=["health"])

REQUIRED_SCHEMA_VERSION = 36
REQUIRED_SCHEMA_FILENAME = "0036_database_privacy_fence.sql"
REQUIRED_SCHEMA_CHECKSUM = "8384077000cdac131f7e20671a36ba31e7d45f5803dde81129a6a3f22d23bbac"
REQUIRED_SCHEMA_RELATIONS = (
    "public.station_inventory_snapshots",
    "public.realtime_jurisdiction_boundary_snapshots",
    "public.realtime_jurisdiction_boundaries",
    "public.realtime_jurisdiction_signal_contracts",
    "public.realtime_source_jurisdictions",
)
DATABASE_READINESS_FAILURE_MESSAGE = "Database readiness check failed."
REDIS_READINESS_FAILURE_MESSAGE = "Redis readiness check failed."


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        service=settings.service_id,
        version=settings.app_version,
        deployment_sha=settings.deployment_sha,
        checked_at=_now_utc(),
    )


@router.get("/ready", response_model=ReadyResponse, responses={503: {"model": ReadyResponse}})
def ready(response: Response) -> ReadyResponse:
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
        deployment_sha=settings.deployment_sha,
        checked_at=_now_utc(),
        dependencies=dependencies,
    )


@router.get("/metrics", include_in_schema=False)
def metrics() -> PlainTextResponse:
    settings = get_settings()
    content = "\n".join(
        (
            "# HELP flood_risk_api_up API process liveness.",
            "# TYPE flood_risk_api_up gauge",
            "flood_risk_api_up 1",
            "# HELP flood_risk_api_info API build metadata.",
            "# TYPE flood_risk_api_info gauge",
            (
                "flood_risk_api_info"
                f'{{service="{_prometheus_label_value(settings.service_id)}",'
                f'version="{_prometheus_label_value(settings.app_version)}",'
                f'deployment_sha="{_prometheus_label_value(settings.deployment_sha or "unknown")}"}} 1'
            ),
            *_geocoder_open_data_metrics(settings),
            "",
        )
    )
    return PlainTextResponse(content, media_type="text/plain; version=0.0.4")


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _prometheus_label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _geocoder_open_data_metrics(settings: object) -> tuple[str, ...]:
    database_url = getattr(settings, "database_url", "")
    postgis_enabled = bool(getattr(settings, "geocoder_postgis_enabled", False))
    if not postgis_enabled or not database_url:
        return (
            "# HELP flood_risk_geocoder_open_data_ready PostGIS open-data geocoder import readiness.",
            "# TYPE flood_risk_geocoder_open_data_ready gauge",
            "flood_risk_geocoder_open_data_ready 0",
            "# HELP flood_risk_geocoder_open_data_rows Imported PostGIS open-data geocoder rows.",
            "# TYPE flood_risk_geocoder_open_data_rows gauge",
            "flood_risk_geocoder_open_data_rows 0",
        )
    try:
        summary = fetch_postgis_geocoder_summary(database_url)
    except Exception:
        return (
            "# HELP flood_risk_geocoder_open_data_ready PostGIS open-data geocoder import readiness.",
            "# TYPE flood_risk_geocoder_open_data_ready gauge",
            "flood_risk_geocoder_open_data_ready 0",
            "# HELP flood_risk_geocoder_open_data_rows Imported PostGIS open-data geocoder rows.",
            "# TYPE flood_risk_geocoder_open_data_rows gauge",
            "flood_risk_geocoder_open_data_rows 0",
        )

    row_count = int(summary.get("row_count") or 0)
    lines = [
        "# HELP flood_risk_geocoder_open_data_ready PostGIS open-data geocoder import readiness.",
        "# TYPE flood_risk_geocoder_open_data_ready gauge",
        f"flood_risk_geocoder_open_data_ready {1 if row_count > 0 else 0}",
        "# HELP flood_risk_geocoder_open_data_rows Imported PostGIS open-data geocoder rows.",
        "# TYPE flood_risk_geocoder_open_data_rows gauge",
        f"flood_risk_geocoder_open_data_rows {row_count}",
    ]
    for row in summary.get("source_counts") or ():
        if not isinstance(row, dict):
            continue
        source_key = _prometheus_label_value(str(row.get("source_key") or "unknown"))
        source_row_count = int(row.get("row_count") or 0)
        lines.append(f'flood_risk_geocoder_open_data_rows{{source_key="{source_key}"}} {source_row_count}')
    return tuple(lines)


def _check_database(database_url: str) -> DependencyReadiness:
    try:
        import psycopg

        with psycopg.connect(database_url, connect_timeout=2) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
                _check_required_schema(cursor)
    except Exception:
        return DependencyReadiness(
            status="failed",
            checked_at=_now_utc(),
            message=DATABASE_READINESS_FAILURE_MESSAGE,
        )
    return DependencyReadiness(status="healthy", checked_at=_now_utc(), message=None)


def _check_required_schema(cursor: object) -> None:
    execute = getattr(cursor, "execute")
    fetchone = getattr(cursor, "fetchone")
    relation_checks = ", ".join("to_regclass(%s) IS NOT NULL" for _ in REQUIRED_SCHEMA_RELATIONS)
    execute(
        f"""
        SELECT
            EXISTS (
                SELECT 1
                FROM schema_migrations
                WHERE version = %s
                  AND filename = %s
                  AND checksum = %s
            ),
            COALESCE((SELECT MAX(version) = %s FROM schema_migrations), false),
            {relation_checks}
        """,
        (
            REQUIRED_SCHEMA_VERSION,
            REQUIRED_SCHEMA_FILENAME,
            REQUIRED_SCHEMA_CHECKSUM,
            REQUIRED_SCHEMA_VERSION,
            *REQUIRED_SCHEMA_RELATIONS,
        ),
    )
    row = fetchone()
    if row is None or not all(bool(value) for value in row):
        raise RuntimeError(
            f"required database schema migration {REQUIRED_SCHEMA_VERSION:04d} is incomplete"
        )


def _check_redis(redis_url: str) -> DependencyReadiness:
    try:
        import redis

        client = redis.Redis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)
        client.ping()
        client.close()
    except Exception:
        return DependencyReadiness(
            status="failed",
            checked_at=_now_utc(),
            message=REDIS_READINESS_FAILURE_MESSAGE,
        )
    return DependencyReadiness(status="healthy", checked_at=_now_utc(), message=None)
