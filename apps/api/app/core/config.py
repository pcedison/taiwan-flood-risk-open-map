from dataclasses import dataclass
from functools import lru_cache
import os
from typing import Literal


RateLimitBackend = Literal["redis", "memory"]


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
    user_reports_rate_limit_enabled: bool
    user_reports_rate_limit_backend: RateLimitBackend
    user_reports_rate_limit_max_requests: int
    user_reports_rate_limit_window_seconds: int
    user_reports_rate_limit_client_header: str | None
    abuse_hash_salt: str | None


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
        user_reports_rate_limit_enabled=_env_bool(
            "USER_REPORTS_RATE_LIMIT_ENABLED",
            default=True,
        ),
        user_reports_rate_limit_backend=_env_choice(
            "USER_REPORTS_RATE_LIMIT_BACKEND",
            choices={"redis", "memory"},
            default="redis",
        ),
        user_reports_rate_limit_max_requests=_env_int(
            "USER_REPORTS_RATE_LIMIT_MAX_REQUESTS",
            default=5,
            minimum=1,
        ),
        user_reports_rate_limit_window_seconds=_env_int(
            "USER_REPORTS_RATE_LIMIT_WINDOW_SECONDS",
            default=60,
            minimum=1,
        ),
        user_reports_rate_limit_client_header=_env_str_or_none(
            "USER_REPORTS_RATE_LIMIT_CLIENT_HEADER"
        ),
        abuse_hash_salt=os.getenv("ABUSE_HASH_SALT") or None,
    )


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_str_or_none(name: str) -> str | None:
    raw = os.getenv(name)
    if raw is None:
        return None
    stripped = raw.strip()
    return stripped or None


def _env_int(name: str, *, default: int, minimum: int | None = None) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        return default
    if minimum is not None and value < minimum:
        return default
    return value


def _env_choice(name: str, *, choices: set[RateLimitBackend], default: RateLimitBackend) -> RateLimitBackend:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    return normalized if normalized in choices else default
