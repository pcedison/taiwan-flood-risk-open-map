from __future__ import annotations

import pytest

from app.adapters.registry import enabled_adapter_keys
from app.config import load_worker_settings


def test_default_enabled_adapters_are_official_only() -> None:
    settings = load_worker_settings({})

    assert enabled_adapter_keys(settings) == (
        "official.cwa.rainfall",
        "official.wra.water_level",
        "official.flood_potential.geojson",
    )


def test_official_source_flags_can_disable_individual_adapters() -> None:
    settings = load_worker_settings(
        {
            "SOURCE_CWA_ENABLED": "false",
            "SOURCE_WRA_ENABLED": "1",
            "SOURCE_FLOOD_POTENTIAL_ENABLED": "0",
        }
    )

    assert enabled_adapter_keys(settings) == ("official.wra.water_level",)


def test_cwa_api_runtime_client_config_is_safe_by_default() -> None:
    settings = load_worker_settings({})

    assert settings.source_cwa_api_enabled is False
    assert settings.cwa_api_authorization is None
    assert settings.cwa_api_url is None
    assert settings.cwa_api_timeout_seconds == 8


def test_cwa_api_runtime_client_config_reads_env() -> None:
    settings = load_worker_settings(
        {
            "SOURCE_CWA_API_ENABLED": "true",
            "CWA_API_AUTHORIZATION": "test-token",
            "CWA_API_URL": "https://example.test/cwa/rainfall",
            "CWA_API_TIMEOUT_SECONDS": "4",
        }
    )

    assert settings.source_cwa_api_enabled is True
    assert settings.cwa_api_authorization == "test-token"
    assert settings.cwa_api_url == "https://example.test/cwa/rainfall"
    assert settings.cwa_api_timeout_seconds == 4


def test_reviewed_news_adapter_requires_family_flag_and_terms_ack() -> None:
    without_ack = load_worker_settings({"SOURCE_NEWS_ENABLED": "true"})
    with_ack = load_worker_settings(
        {
            "SOURCE_NEWS_ENABLED": "true",
            "SOURCE_TERMS_REVIEW_ACK": "true",
        }
    )

    assert "news.public_web.gdelt_backfill" not in enabled_adapter_keys(without_ack)
    assert "news.public_web.gdelt_backfill" in enabled_adapter_keys(with_ack)


def test_sample_adapters_require_sample_data_flag() -> None:
    settings = load_worker_settings(
        {
            "SOURCE_NEWS_ENABLED": "true",
            "SOURCE_SAMPLE_DATA_ENABLED": "true",
        }
    )

    assert "news.public_web.sample" in enabled_adapter_keys(settings)


def test_forum_sources_require_family_source_and_terms_flags() -> None:
    missing_terms = load_worker_settings(
        {
            "SOURCE_FORUM_ENABLED": "true",
            "SOURCE_PTT_ENABLED": "true",
            "SOURCE_DCARD_ENABLED": "true",
        }
    )
    explicit_ptt = load_worker_settings(
        {
            "SOURCE_FORUM_ENABLED": "true",
            "SOURCE_PTT_ENABLED": "true",
            "SOURCE_DCARD_ENABLED": "false",
            "SOURCE_TERMS_REVIEW_ACK": "true",
        }
    )

    assert "ptt" not in enabled_adapter_keys(missing_terms)
    assert "dcard" not in enabled_adapter_keys(missing_terms)
    assert "ptt" in enabled_adapter_keys(explicit_ptt)
    assert "dcard" not in enabled_adapter_keys(explicit_ptt)


def test_explicit_adapter_allowlist_limits_enabled_adapters() -> None:
    settings = load_worker_settings(
        {
            "WORKER_ENABLED_ADAPTER_KEYS": (
                "official.wra.water_level,official.flood_potential.geojson"
            ),
        }
    )

    assert enabled_adapter_keys(settings) == (
        "official.wra.water_level",
        "official.flood_potential.geojson",
    )


def test_explicit_adapter_allowlist_can_enable_news_after_terms_ack() -> None:
    settings = load_worker_settings(
        {
            "WORKER_ENABLED_ADAPTER_KEYS": "news.public_web.gdelt_backfill",
            "SOURCE_TERMS_REVIEW_ACK": "true",
        }
    )

    assert enabled_adapter_keys(settings) == ("news.public_web.gdelt_backfill",)


def test_explicit_adapter_allowlist_does_not_bypass_terms_ack() -> None:
    settings = load_worker_settings(
        {
            "WORKER_ENABLED_ADAPTER_KEYS": (
                "news.public_web.gdelt_backfill,ptt,dcard,official.cwa.rainfall"
            ),
        }
    )

    assert enabled_adapter_keys(settings) == ("official.cwa.rainfall",)


def test_explicit_adapter_allowlist_does_not_bypass_sample_data_gate() -> None:
    without_sample_flag = load_worker_settings(
        {"WORKER_ENABLED_ADAPTER_KEYS": "news.public_web.sample"}
    )
    with_sample_flag = load_worker_settings(
        {
            "WORKER_ENABLED_ADAPTER_KEYS": "news.public_web.sample",
            "SOURCE_SAMPLE_DATA_ENABLED": "true",
        }
    )

    assert enabled_adapter_keys(without_sample_flag) == ()
    assert enabled_adapter_keys(with_sample_flag) == ("news.public_web.sample",)


def test_source_flags_can_disable_allowlisted_adapters() -> None:
    settings = load_worker_settings(
        {
            "WORKER_ENABLED_ADAPTER_KEYS": "official.cwa.rainfall,ptt",
            "SOURCE_CWA_ENABLED": "false",
            "SOURCE_FORUM_ENABLED": "false",
            "SOURCE_PTT_ENABLED": "true",
            "SOURCE_TERMS_REVIEW_ACK": "true",
        }
    )

    assert enabled_adapter_keys(settings) == ()


def test_unknown_adapter_allowlist_key_raises() -> None:
    settings = load_worker_settings(
        {
            "WORKER_ENABLED_ADAPTER_KEYS": (
                "official.cwa.rainfall,official.unknown.sensor"
            ),
        }
    )

    with pytest.raises(ValueError, match="official.unknown.sensor"):
        enabled_adapter_keys(settings)
