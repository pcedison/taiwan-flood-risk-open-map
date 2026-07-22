from app.core.config import get_settings
from app.main import create_app


def test_hosted_app_env_disables_interactive_docs_and_openapi_schema(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("APP_ENV", "production")

    try:
        settings = get_settings()
        application = create_app()

        assert settings.app_env == "production"
        assert application.docs_url is None
        assert application.redoc_url is None
        assert application.openapi_url is None
    finally:
        get_settings.cache_clear()


def test_local_app_env_keeps_interactive_docs_and_openapi_schema(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("APP_ENV", "local")

    try:
        settings = get_settings()
        application = create_app()

        assert settings.app_env == "local"
        assert application.docs_url == "/docs"
        assert application.redoc_url == "/redoc"
        assert application.openapi_url == "/openapi.json"
    finally:
        get_settings.cache_clear()
