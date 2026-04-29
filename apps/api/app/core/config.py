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
    )

