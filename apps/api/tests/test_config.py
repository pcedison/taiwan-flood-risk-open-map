from app.core.config import get_settings


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
