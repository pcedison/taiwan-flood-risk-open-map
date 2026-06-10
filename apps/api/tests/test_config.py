from app.core.config import get_settings


def test_settings_uses_bundled_geocoder_open_data_when_paths_unset(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("APP_ENV", "production-beta")
    monkeypatch.delenv("GEOCODER_OPEN_DATA_PATHS", raising=False)
    monkeypatch.delenv("GEOCODER_BUNDLED_OPEN_DATA_ENABLED", raising=False)

    settings = get_settings()

    assert len(settings.geocoder_open_data_paths) == 3
    assert all(path.endswith(".normalized.jsonl.gz") for path in settings.geocoder_open_data_paths)
    assert settings.geocoder_postgis_enabled is True
    assert settings.geocoder_postgis_bootstrap_enabled is False
    get_settings.cache_clear()


def test_settings_can_disable_bundled_geocoder_open_data(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("APP_ENV", "production-beta")
    monkeypatch.delenv("GEOCODER_OPEN_DATA_PATHS", raising=False)
    monkeypatch.setenv("GEOCODER_BUNDLED_OPEN_DATA_ENABLED", "false")

    settings = get_settings()

    assert settings.geocoder_open_data_paths == ()
    assert settings.geocoder_postgis_enabled is True
    assert settings.geocoder_postgis_bootstrap_enabled is False
    get_settings.cache_clear()


def test_settings_can_explicitly_enable_hosted_postgis_bootstrap(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("APP_ENV", "production-beta")
    monkeypatch.setenv("GEOCODER_POSTGIS_BOOTSTRAP_ENABLED", "true")

    settings = get_settings()

    assert settings.geocoder_postgis_enabled is True
    assert settings.geocoder_postgis_bootstrap_enabled is True
    get_settings.cache_clear()


def test_settings_does_not_enable_bundled_geocoder_open_data_for_default_local(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("GEOCODER_OPEN_DATA_PATHS", raising=False)
    monkeypatch.delenv("GEOCODER_BUNDLED_OPEN_DATA_ENABLED", raising=False)

    settings = get_settings()

    assert settings.geocoder_open_data_paths == ()
    assert settings.geocoder_postgis_enabled is False
    assert settings.geocoder_postgis_bootstrap_enabled is False
    assert settings.official_flood_disaster_points_enabled is False
    assert settings.risk_assessment_response_cache_seconds == 0
    get_settings.cache_clear()


def test_settings_enables_bundled_official_disaster_points_for_hosted_runtime(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("APP_ENV", "production-beta")
    monkeypatch.delenv("OFFICIAL_FLOOD_DISASTER_POINTS_ENABLED", raising=False)
    monkeypatch.delenv("OFFICIAL_FLOOD_DISASTER_POINTS_PATH", raising=False)

    settings = get_settings()

    assert settings.official_flood_disaster_points_enabled is True
    assert settings.official_flood_disaster_points_path is not None
    assert settings.official_flood_disaster_points_path.endswith(
        "flood_disaster_points_130016.csv"
    )
    get_settings.cache_clear()


def test_settings_enables_short_risk_response_cache_for_hosted_runtime(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("APP_ENV", "production-beta")
    monkeypatch.delenv("RISK_ASSESSMENT_RESPONSE_CACHE_SECONDS", raising=False)

    settings = get_settings()

    assert settings.risk_assessment_response_cache_seconds == 120
    assert settings.realtime_official_diagnostic_fallback_enabled is False
    assert settings.tile_dynamic_fallback_enabled is False
    get_settings.cache_clear()


def test_settings_local_defaults_allow_realtime_diagnostic_fallback(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("REALTIME_OFFICIAL_DIAGNOSTIC_FALLBACK_ENABLED", raising=False)

    settings = get_settings()

    assert settings.realtime_official_diagnostic_fallback_enabled is True
    assert settings.tile_dynamic_fallback_enabled is True
    get_settings.cache_clear()


def test_settings_can_explicitly_enable_hosted_tile_dynamic_fallback(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("APP_ENV", "production-beta")
    monkeypatch.setenv("TILE_DYNAMIC_FALLBACK_ENABLED", "true")

    settings = get_settings()

    assert settings.tile_dynamic_fallback_enabled is True
    get_settings.cache_clear()


def test_settings_can_explicitly_enable_hosted_realtime_diagnostic_fallback(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("APP_ENV", "production-beta")
    monkeypatch.setenv("REALTIME_OFFICIAL_DIAGNOSTIC_FALLBACK_ENABLED", "true")

    settings = get_settings()

    assert settings.realtime_official_diagnostic_fallback_enabled is True
    get_settings.cache_clear()


def test_settings_allows_disabling_risk_response_cache(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("APP_ENV", "production-beta")
    monkeypatch.setenv("RISK_ASSESSMENT_RESPONSE_CACHE_SECONDS", "0")

    settings = get_settings()

    assert settings.risk_assessment_response_cache_seconds == 0
    get_settings.cache_clear()


def test_settings_hosted_defaults_disable_admin_samples_and_enable_public_redis_limits(
    monkeypatch,
):
    get_settings.cache_clear()
    monkeypatch.setenv("APP_ENV", "production-beta")
    monkeypatch.delenv("ADMIN_SAMPLE_DATA_ENABLED", raising=False)
    monkeypatch.delenv("DEMO_MODE_ENABLED", raising=False)
    monkeypatch.delenv("PUBLIC_RATE_LIMIT_ENABLED", raising=False)
    monkeypatch.delenv("PUBLIC_RATE_LIMIT_BACKEND", raising=False)
    monkeypatch.delenv("GEOCODE_RATE_LIMIT_MAX_REQUESTS", raising=False)
    monkeypatch.delenv("RISK_ASSESSMENT_RATE_LIMIT_MAX_REQUESTS", raising=False)
    monkeypatch.delenv("PUBLIC_RATE_LIMIT_WINDOW_SECONDS", raising=False)

    settings = get_settings()

    assert settings.admin_sample_data_enabled is False
    assert settings.public_rate_limit_enabled is True
    assert settings.public_rate_limit_backend == "redis"
    assert settings.geocode_rate_limit_max_requests == 60
    assert settings.risk_assessment_rate_limit_max_requests == 30
    assert settings.public_rate_limit_window_seconds == 60
    get_settings.cache_clear()


def test_settings_local_defaults_allow_admin_samples_without_public_rate_limit(
    monkeypatch,
):
    get_settings.cache_clear()
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("ADMIN_SAMPLE_DATA_ENABLED", raising=False)
    monkeypatch.delenv("DEMO_MODE_ENABLED", raising=False)
    monkeypatch.delenv("PUBLIC_RATE_LIMIT_ENABLED", raising=False)
    monkeypatch.delenv("PUBLIC_RATE_LIMIT_BACKEND", raising=False)

    settings = get_settings()

    assert settings.admin_sample_data_enabled is True
    assert settings.public_rate_limit_enabled is False
    assert settings.public_rate_limit_backend == "memory"
    get_settings.cache_clear()


def test_settings_admin_sample_data_can_be_enabled_by_demo_flag(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("APP_ENV", "production-beta")
    monkeypatch.setenv("DEMO_MODE_ENABLED", "true")
    monkeypatch.delenv("ADMIN_SAMPLE_DATA_ENABLED", raising=False)

    settings = get_settings()

    assert settings.admin_sample_data_enabled is True
    get_settings.cache_clear()


def test_settings_public_rate_limit_env_overrides(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("PUBLIC_RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("PUBLIC_RATE_LIMIT_BACKEND", "memory")
    monkeypatch.setenv("PUBLIC_RATE_LIMIT_CLIENT_HEADER", "x-forwarded-for")
    monkeypatch.setenv("GEOCODE_RATE_LIMIT_MAX_REQUESTS", "12")
    monkeypatch.setenv("RISK_ASSESSMENT_RATE_LIMIT_MAX_REQUESTS", "7")
    monkeypatch.setenv("PUBLIC_RATE_LIMIT_WINDOW_SECONDS", "15")

    settings = get_settings()

    assert settings.public_rate_limit_enabled is True
    assert settings.public_rate_limit_backend == "memory"
    assert settings.public_rate_limit_client_header == "x-forwarded-for"
    assert settings.geocode_rate_limit_max_requests == 12
    assert settings.risk_assessment_rate_limit_max_requests == 7
    assert settings.public_rate_limit_window_seconds == 15
    get_settings.cache_clear()


def test_settings_falls_back_to_zeabur_postgres_and_redis_refs(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_URL", "${POSTGRES_CONNECTION_STRING}")
    monkeypatch.setenv("POSTGRES_CONNECTION_STRING", "postgresql://prod.example.test/flood")
    monkeypatch.setenv("REDIS_URL", "${REDIS_CONNECTION_STRING}")
    monkeypatch.setenv("REDIS_CONNECTION_STRING", "redis://:secret@redis.example.test:6379/0")

    settings = get_settings()

    assert settings.database_url == "postgresql://prod.example.test/flood"
    assert settings.redis_url == "redis://:secret@redis.example.test:6379/0"
    get_settings.cache_clear()


def test_settings_keeps_explicit_database_and_redis_urls(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_URL", "postgresql://explicit.example.test/flood")
    monkeypatch.setenv("POSTGRES_CONNECTION_STRING", "postgresql://fallback.example.test/flood")
    monkeypatch.setenv("REDIS_URL", "redis://explicit.example.test:6379/0")
    monkeypatch.setenv("REDIS_CONNECTION_STRING", "redis://fallback.example.test:6379/0")

    settings = get_settings()

    assert settings.database_url == "postgresql://explicit.example.test/flood"
    assert settings.redis_url == "redis://explicit.example.test:6379/0"
    get_settings.cache_clear()


def test_realtime_cwa_bridge_auto_enables_when_token_is_present(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.delenv("SOURCE_CWA_API_ENABLED", raising=False)
    monkeypatch.setenv("CWA_API_AUTHORIZATION", "test-cwa-token")

    settings = get_settings()

    assert settings.cwa_api_authorization == "test-cwa-token"
    assert settings.source_cwa_api_enabled is True
    get_settings.cache_clear()


def test_realtime_cwa_bridge_respects_explicit_disable(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("CWA_API_AUTHORIZATION", "test-cwa-token")
    monkeypatch.setenv("SOURCE_CWA_API_ENABLED", "false")

    settings = get_settings()

    assert settings.source_cwa_api_enabled is False
    get_settings.cache_clear()


def test_realtime_wra_bridge_defaults_to_public_endpoint_enabled(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.delenv("SOURCE_WRA_API_ENABLED", raising=False)

    settings = get_settings()

    assert settings.source_wra_api_enabled is True
    get_settings.cache_clear()
