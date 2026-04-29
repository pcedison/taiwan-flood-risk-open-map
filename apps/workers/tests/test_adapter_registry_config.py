from __future__ import annotations

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
