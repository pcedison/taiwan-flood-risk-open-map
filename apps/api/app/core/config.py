from dataclasses import dataclass
from functools import lru_cache
import os


@dataclass(frozen=True)
class Settings:
    app_title: str
    service_id: str
    app_version: str
    app_env: str
    database_url: str
    redis_url: str
    minio_endpoint: str
    cors_origins: tuple[str, ...]
    admin_bearer_token: str | None
    realtime_official_enabled: bool
    cwa_api_authorization: str | None
    user_reports_enabled: bool


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    cors_origins = tuple(
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
        if origin.strip()
    )
    return Settings(
        app_title="Flood Risk API",
        service_id="flood-risk-api",
        app_version=os.getenv("API_VERSION", "0.1.0-draft"),
        app_env=os.getenv("APP_ENV", "local"),
        database_url=os.getenv(
            "DATABASE_URL",
            "postgresql://flood_risk:change-me-local@postgres:5432/flood_risk",
        ),
        redis_url=os.getenv("REDIS_URL", "redis://redis:6379/0"),
        minio_endpoint=os.getenv("MINIO_ENDPOINT", "http://minio:9000"),
        cors_origins=cors_origins,
        admin_bearer_token=os.getenv("ADMIN_BEARER_TOKEN") or None,
        realtime_official_enabled=_env_bool("REALTIME_OFFICIAL_ENABLED", default=True),
        cwa_api_authorization=os.getenv("CWA_API_AUTHORIZATION") or None,
        user_reports_enabled=_env_bool("USER_REPORTS_ENABLED", default=False),
    )


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
