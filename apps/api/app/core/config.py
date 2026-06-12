from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path
from typing import Literal, TypeVar, cast


RateLimitBackend = Literal["redis", "memory"]
ChallengeProvider = Literal["turnstile", "static"]
ChoiceT = TypeVar("ChoiceT", bound=str)
APP_ROOT = Path(__file__).resolve().parents[1]
BUNDLED_GEOCODER_DATA_DIR = APP_ROOT / "data" / "geocoder"
BUNDLED_OFFICIAL_DATA_DIR = APP_ROOT / "data" / "official"
BUNDLED_GEOCODER_OPEN_DATA_FILENAMES = (
    "roads-114.normalized.jsonl.gz",
    "shelters.normalized.jsonl.gz",
    "villages.normalized.jsonl.gz",
)
BUNDLED_OFFICIAL_FLOOD_DISASTER_POINTS_FILENAME = "flood_disaster_points_130016.csv"


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
    admin_sample_data_enabled: bool
    realtime_official_enabled: bool
    realtime_official_diagnostic_fallback_enabled: bool
    cwa_api_authorization: str | None
    source_cwa_api_enabled: bool
    source_wra_api_enabled: bool
    source_news_enabled: bool
    source_terms_review_ack: bool
    evidence_repository_enabled: bool
    geocoder_open_data_paths: tuple[str, ...]
    geocoder_postgis_enabled: bool
    geocoder_postgis_bootstrap_enabled: bool
    historical_news_on_demand_enabled: bool
    historical_news_on_demand_writeback_enabled: bool
    historical_news_on_demand_max_records: int
    historical_news_on_demand_timeout_seconds: float
    official_flood_disaster_points_enabled: bool
    official_flood_disaster_points_path: str | None
    risk_assessment_response_cache_seconds: int
    risk_assessment_response_cache_backend: RateLimitBackend
    risk_assessment_evidence_cache_ttl_seconds: int
    risk_assessment_evidence_cache_backend: RateLimitBackend
    tile_dynamic_fallback_enabled: bool
    public_rate_limit_enabled: bool
    public_rate_limit_backend: RateLimitBackend
    public_rate_limit_client_header: str | None
    geocode_rate_limit_max_requests: int
    risk_assessment_rate_limit_max_requests: int
    public_rate_limit_window_seconds: int
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
        for origin in os.getenv(
            "CORS_ORIGINS",
            "http://localhost:3000,http://127.0.0.1:3000",
        ).split(",")
        if origin.strip()
    )
    app_env = os.getenv("APP_ENV", "local")
    non_production_default = app_env.strip().lower() in {"local", "development", "test"}
    cwa_api_authorization = os.getenv("CWA_API_AUTHORIZATION") or None
    return Settings(
        app_title="Flood Risk API",
        service_id="flood-risk-api",
        app_version=os.getenv("API_VERSION", "0.1.0-draft"),
        deployment_sha=_deployment_sha(),
        app_env=app_env,
        database_url=_env_url(
            ("DATABASE_URL", "POSTGRES_CONNECTION_STRING", "POSTGRES_URI"),
            default="postgresql://flood_risk:change-me-local@postgres:5432/flood_risk",
        ),
        redis_url=_env_url(
            ("REDIS_URL", "REDIS_CONNECTION_STRING", "REDIS_URI"),
            default="redis://redis:6379/0",
        ),
        minio_endpoint=os.getenv("MINIO_ENDPOINT", "http://minio:9000"),
        cors_origins=cors_origins,
        admin_bearer_token=os.getenv("ADMIN_BEARER_TOKEN") or None,
        admin_sample_data_enabled=_admin_sample_data_enabled(app_env),
        realtime_official_enabled=_env_bool("REALTIME_OFFICIAL_ENABLED", default=True),
        realtime_official_diagnostic_fallback_enabled=_env_bool(
            "REALTIME_OFFICIAL_DIAGNOSTIC_FALLBACK_ENABLED",
            default=_local_or_test_runtime(app_env),
        ),
        cwa_api_authorization=cwa_api_authorization,
        source_cwa_api_enabled=_env_bool(
            "SOURCE_CWA_API_ENABLED",
            default=cwa_api_authorization is not None,
        ),
        source_wra_api_enabled=_env_bool("SOURCE_WRA_API_ENABLED", default=True),
        source_news_enabled=_env_bool("SOURCE_NEWS_ENABLED", default=non_production_default),
        source_terms_review_ack=_env_bool(
            "SOURCE_TERMS_REVIEW_ACK",
            default=non_production_default,
        ),
        evidence_repository_enabled=_env_bool("EVIDENCE_REPOSITORY_ENABLED", default=True),
        geocoder_open_data_paths=_geocoder_open_data_paths(app_env),
        geocoder_postgis_enabled=_env_bool(
            "GEOCODER_POSTGIS_ENABLED",
            default=_hosted_runtime(app_env),
        ),
        geocoder_postgis_bootstrap_enabled=_env_bool(
            "GEOCODER_POSTGIS_BOOTSTRAP_ENABLED",
            default=False,
        ),
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
        official_flood_disaster_points_enabled=_env_bool(
            "OFFICIAL_FLOOD_DISASTER_POINTS_ENABLED",
            default=_hosted_runtime(app_env),
        ),
        official_flood_disaster_points_path=_official_flood_disaster_points_path(),
        risk_assessment_response_cache_seconds=_env_int(
            "RISK_ASSESSMENT_RESPONSE_CACHE_SECONDS",
            default=120 if _hosted_runtime(app_env) else 0,
            minimum=0,
        ),
        risk_assessment_response_cache_backend=_env_choice(
            "RISK_ASSESSMENT_RESPONSE_CACHE_BACKEND",
            choices={"redis", "memory"},
            default="memory" if _local_or_test_runtime(app_env) else "redis",
        ),
        risk_assessment_evidence_cache_ttl_seconds=_env_int(
            "RISK_ASSESSMENT_EVIDENCE_CACHE_TTL_SECONDS",
            default=3600,
            minimum=0,
        ),
        risk_assessment_evidence_cache_backend=_env_choice(
            "RISK_ASSESSMENT_EVIDENCE_CACHE_BACKEND",
            choices={"redis", "memory"},
            default="memory" if _local_or_test_runtime(app_env) else "redis",
        ),
        tile_dynamic_fallback_enabled=_env_bool(
            "TILE_DYNAMIC_FALLBACK_ENABLED",
            default=_local_or_test_runtime(app_env),
        ),
        public_rate_limit_enabled=_env_bool(
            "PUBLIC_RATE_LIMIT_ENABLED",
            default=_hosted_runtime(app_env),
        ),
        public_rate_limit_backend=_env_choice(
            "PUBLIC_RATE_LIMIT_BACKEND",
            choices={"redis", "memory"},
            default="memory" if _local_or_test_runtime(app_env) else "redis",
        ),
        public_rate_limit_client_header=_env_str_or_none(
            "PUBLIC_RATE_LIMIT_CLIENT_HEADER"
        ),
        geocode_rate_limit_max_requests=_env_int(
            "GEOCODE_RATE_LIMIT_MAX_REQUESTS",
            default=60,
            minimum=1,
        ),
        risk_assessment_rate_limit_max_requests=_env_int(
            "RISK_ASSESSMENT_RATE_LIMIT_MAX_REQUESTS",
            default=30,
            minimum=1,
        ),
        public_rate_limit_window_seconds=_env_int(
            "PUBLIC_RATE_LIMIT_WINDOW_SECONDS",
            default=60,
            minimum=1,
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


def _env_url(names: tuple[str, ...], *, default: str) -> str:
    for name in names:
        value = _env_str_or_none(name)
        if value is not None and not _looks_like_unresolved_ref(value):
            return value
    return default


def _looks_like_unresolved_ref(value: str) -> bool:
    return "${" in value or "}" in value


def _deployment_sha() -> str | None:
    for name in (
        "DEPLOYMENT_SHA",
        "GIT_COMMIT_SHA",
        "COMMIT_SHA",
        "SOURCE_COMMIT",
        "ZEABUR_GIT_COMMIT_SHA",
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


def _geocoder_open_data_paths(app_env: str) -> tuple[str, ...]:
    configured_paths = _env_csv("GEOCODER_OPEN_DATA_PATHS")
    if configured_paths:
        return configured_paths
    # Hosted beta should have project-controlled road/POI/admin fallback even before PostGIS import.
    hosted_default = _hosted_runtime(app_env)
    if not _env_bool("GEOCODER_BUNDLED_OPEN_DATA_ENABLED", default=hosted_default):
        return ()
    return tuple(
        str(path)
        for path in (
            BUNDLED_GEOCODER_DATA_DIR / filename
            for filename in BUNDLED_GEOCODER_OPEN_DATA_FILENAMES
        )
        if path.is_file()
    )


def _official_flood_disaster_points_path() -> str | None:
    configured_path = _env_str_or_none("OFFICIAL_FLOOD_DISASTER_POINTS_PATH")
    if configured_path is not None:
        return configured_path
    bundled_path = BUNDLED_OFFICIAL_DATA_DIR / BUNDLED_OFFICIAL_FLOOD_DISASTER_POINTS_FILENAME
    return str(bundled_path) if bundled_path.is_file() else None


def _hosted_runtime(app_env: str) -> bool:
    return app_env.strip().lower() in {"staging", "production", "production-beta"}


def _local_or_test_runtime(app_env: str) -> bool:
    return app_env.strip().lower() in {"local", "development", "test"}


def _admin_sample_data_enabled(app_env: str) -> bool:
    return _local_or_test_runtime(app_env) or _env_bool(
        "ADMIN_SAMPLE_DATA_ENABLED",
        default=False,
    ) or _env_bool("DEMO_MODE_ENABLED", default=False)


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
