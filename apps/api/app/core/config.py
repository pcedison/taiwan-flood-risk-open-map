from dataclasses import dataclass
from functools import lru_cache
import os
from typing import Literal, TypeVar, cast


RateLimitBackend = Literal["redis", "memory"]
ChallengeProvider = Literal["turnstile", "static"]
ChoiceT = TypeVar("ChoiceT", bound=str)


@dataclass(frozen=True)
class Settings:
    app_title: str
    service_id: str
    app_version: str
    deployment_sha: str | None
    app_env: str
    database_url: str
    redis_url: str
    minio_endpoint: str
    cors_origins: tuple[str, ...]
    admin_bearer_token: str | None
    realtime_official_enabled: bool
    cwa_api_authorization: str | None
    source_cwa_api_enabled: bool
    source_wra_api_enabled: bool
    source_news_enabled: bool
    source_terms_review_ack: bool
    evidence_repository_enabled: bool
    geocoder_open_data_paths: tuple[str, ...]
    historical_news_on_demand_enabled: bool
    historical_news_on_demand_writeback_enabled: bool
    historical_news_on_demand_max_records: int
    historical_news_on_demand_timeout_seconds: float
    user_reports_enabled: bool
    user_reports_rate_limit_enabled: bool
    user_reports_rate_limit_backend: RateLimitBackend
    user_reports_rate_limit_max_requests: int
    user_reports_rate_limit_window_seconds: int
    user_reports_rate_limit_client_header: str | None
    abuse_hash_salt: str | None
    user_reports_challenge_required: bool
    user_reports_challenge_provider: ChallengeProvider
    user_reports_challenge_secret_key: str | None
    user_reports_challenge_static_token: str | None
    user_reports_challenge_verify_url: str
    user_reports_challenge_timeout_seconds: float
    user_reports_challenge_non_production_bypass: bool


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    cors_origins = tuple(
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
        if origin.strip()
    )
    app_env = os.getenv("APP_ENV", "local")
    non_production_default = app_env.strip().lower() in {"local", "development", "test"}
    return Settings(
        app_title="Flood Risk API",
        service_id="flood-risk-api",
        app_version=os.getenv("API_VERSION", "0.1.0-draft"),
        deployment_sha=_deployment_sha(),
        app_env=app_env,
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
        source_cwa_api_enabled=_env_bool("SOURCE_CWA_API_ENABLED", default=False),
        source_wra_api_enabled=_env_bool("SOURCE_WRA_API_ENABLED", default=False),
        source_news_enabled=_env_bool("SOURCE_NEWS_ENABLED", default=non_production_default),
        source_terms_review_ack=_env_bool(
            "SOURCE_TERMS_REVIEW_ACK",
            default=non_production_default,
        ),
        evidence_repository_enabled=_env_bool("EVIDENCE_REPOSITORY_ENABLED", default=True),
        geocoder_open_data_paths=_env_csv("GEOCODER_OPEN_DATA_PATHS"),
        historical_news_on_demand_enabled=_env_bool(
            "HISTORICAL_NEWS_ON_DEMAND_ENABLED",
            default=non_production_default,
        ),
        historical_news_on_demand_writeback_enabled=_env_bool(
            "HISTORICAL_NEWS_ON_DEMAND_WRITEBACK_ENABLED",
            default=non_production_default,
        ),
        historical_news_on_demand_max_records=_env_int(
            "HISTORICAL_NEWS_ON_DEMAND_MAX_RECORDS",
            default=5,
            minimum=1,
        ),
        historical_news_on_demand_timeout_seconds=_env_float(
            "HISTORICAL_NEWS_ON_DEMAND_TIMEOUT_SECONDS",
            default=4.0,
            minimum=0.5,
        ),
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
        user_reports_challenge_required=_env_bool(
            "USER_REPORTS_CHALLENGE_REQUIRED",
            default=False,
        ),
        user_reports_challenge_provider=_env_choice(
            "USER_REPORTS_CHALLENGE_PROVIDER",
            choices={"turnstile", "static"},
            default="turnstile",
        ),
        user_reports_challenge_secret_key=_env_str_or_none(
            "USER_REPORTS_CHALLENGE_SECRET_KEY"
        ),
        user_reports_challenge_static_token=_env_str_or_none(
            "USER_REPORTS_CHALLENGE_STATIC_TOKEN"
        ),
        user_reports_challenge_verify_url=os.getenv(
            "USER_REPORTS_CHALLENGE_VERIFY_URL",
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
        ),
        user_reports_challenge_timeout_seconds=_env_float(
            "USER_REPORTS_CHALLENGE_TIMEOUT_SECONDS",
            default=2.0,
            minimum=0.1,
        ),
        user_reports_challenge_non_production_bypass=_env_bool(
            "USER_REPORTS_CHALLENGE_NON_PRODUCTION_BYPASS",
            default=False,
        ),
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


def _deployment_sha() -> str | None:
    for name in (
        "DEPLOYMENT_SHA",
        "GIT_COMMIT_SHA",
        "COMMIT_SHA",
        "SOURCE_COMMIT",
        "ZB_GIT_COMMIT_SHA",
        "VERCEL_GIT_COMMIT_SHA",
    ):
        value = _env_str_or_none(name)
        if value is not None:
            return value
    return None


def _env_csv(name: str) -> tuple[str, ...]:
    raw = os.getenv(name)
    if raw is None:
        return ()
    return tuple(item.strip() for item in raw.split(",") if item.strip())


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


def _env_float(name: str, *, default: float, minimum: float | None = None) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw.strip())
    except ValueError:
        return default
    if minimum is not None and value < minimum:
        return default
    return value


def _env_choice(name: str, *, choices: set[ChoiceT], default: ChoiceT) -> ChoiceT:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    return cast(ChoiceT, normalized) if normalized in choices else default
