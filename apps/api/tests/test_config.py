from app.core.config import get_settings


def test_settings_uses_bundled_geocoder_open_data_when_paths_unset(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("APP_ENV", "production-beta")
    monkeypatch.delenv("GEOCODER_OPEN_DATA_PATHS", raising=False)
    monkeypatch.delenv("GEOCODER_BUNDLED_OPEN_DATA_ENABLED", raising=False)

    settings = get_settings()

    assert len(settings.geocoder_open_data_paths) == 3
    assert all(path.endswith(".normalized.jsonl.gz") for path in settings.geocoder_open_data_paths)
    get_settings.cache_clear()


def test_settings_can_disable_bundled_geocoder_open_data(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("APP_ENV", "production-beta")
    monkeypatch.delenv("GEOCODER_OPEN_DATA_PATHS", raising=False)
    monkeypatch.setenv("GEOCODER_BUNDLED_OPEN_DATA_ENABLED", "false")

    settings = get_settings()

    assert settings.geocoder_open_data_paths == ()
    get_settings.cache_clear()


def test_settings_does_not_enable_bundled_geocoder_open_data_for_default_local(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("GEOCODER_OPEN_DATA_PATHS", raising=False)
    monkeypatch.delenv("GEOCODER_BUNDLED_OPEN_DATA_ENABLED", raising=False)

    settings = get_settings()

    assert settings.geocoder_open_data_paths == ()
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
