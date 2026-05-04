from __future__ import annotations

import pytest

from app.adapters.dcard import (
    ADAPTER_DISABLED_REASON as DCARD_DISABLED_REASON,
    METADATA as DCARD_METADATA,
    REQUIRED_ACCEPTANCE_FIELDS as DCARD_REQUIRED_ACCEPTANCE_FIELDS,
    SOURCE_APPROVAL_STATUS as DCARD_SOURCE_APPROVAL_STATUS,
)
from app.adapters.ptt import (
    ADAPTER_DISABLED_REASON as PTT_DISABLED_REASON,
    METADATA as PTT_METADATA,
    REQUIRED_ACCEPTANCE_FIELDS as PTT_REQUIRED_ACCEPTANCE_FIELDS,
    SOURCE_APPROVAL_STATUS as PTT_SOURCE_APPROVAL_STATUS,
)
from app.adapters.registry import ADAPTER_REGISTRY, enabled_adapter_keys
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
    assert settings.source_wra_api_enabled is False
    assert settings.source_flood_potential_geojson_enabled is False
    assert settings.source_ptt_candidate_approval_ack is False
    assert settings.source_dcard_candidate_approval_ack is False
    assert settings.cwa_api_authorization is None
    assert settings.cwa_api_url is None
    assert settings.cwa_api_timeout_seconds == 8
    assert settings.wra_api_url is None
    assert settings.wra_api_token is None
    assert settings.wra_api_timeout_seconds == 8
    assert settings.flood_potential_geojson_url is None
    assert settings.flood_potential_geojson_timeout_seconds == 8


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


def test_wra_api_runtime_client_config_reads_env() -> None:
    settings = load_worker_settings(
        {
            "SOURCE_WRA_API_ENABLED": "true",
            "WRA_API_URL": "https://example.test/wra/water-level",
            "WRA_API_TOKEN": "optional-token",
            "WRA_API_TIMEOUT_SECONDS": "6",
        }
    )

    assert settings.source_wra_api_enabled is True
    assert settings.wra_api_url == "https://example.test/wra/water-level"
    assert settings.wra_api_token == "optional-token"
    assert settings.wra_api_timeout_seconds == 6


def test_flood_potential_geojson_runtime_client_config_reads_env() -> None:
    settings = load_worker_settings(
        {
            "SOURCE_FLOOD_POTENTIAL_GEOJSON_ENABLED": "true",
            "FLOOD_POTENTIAL_GEOJSON_URL": "https://example.test/flood-potential.geojson",
            "FLOOD_POTENTIAL_GEOJSON_TIMEOUT_SECONDS": "10",
        }
    )

    assert settings.source_flood_potential_geojson_enabled is True
    assert settings.flood_potential_geojson_url == (
        "https://example.test/flood-potential.geojson"
    )
    assert settings.flood_potential_geojson_timeout_seconds == 10


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
    missing_candidate_ack = load_worker_settings(
        {
            "SOURCE_FORUM_ENABLED": "true",
            "SOURCE_PTT_ENABLED": "true",
            "SOURCE_DCARD_ENABLED": "false",
            "SOURCE_TERMS_REVIEW_ACK": "true",
        }
    )
    explicit_ptt = load_worker_settings(
        {
            "SOURCE_FORUM_ENABLED": "true",
            "SOURCE_PTT_ENABLED": "true",
            "SOURCE_DCARD_ENABLED": "false",
            "SOURCE_TERMS_REVIEW_ACK": "true",
            "SOURCE_PTT_CANDIDATE_APPROVAL_ACK": "true",
        }
    )

    assert "ptt" not in enabled_adapter_keys(missing_terms)
    assert "dcard" not in enabled_adapter_keys(missing_terms)
    assert "ptt" not in enabled_adapter_keys(missing_candidate_ack)
    assert "ptt" in enabled_adapter_keys(explicit_ptt)
    assert "dcard" not in enabled_adapter_keys(explicit_ptt)


def test_forum_adapter_modules_expose_blocked_approval_boundaries() -> None:
    assert ADAPTER_REGISTRY["ptt"] == PTT_METADATA
    assert ADAPTER_REGISTRY["dcard"] == DCARD_METADATA
    assert PTT_SOURCE_APPROVAL_STATUS == "blocked"
    assert DCARD_SOURCE_APPROVAL_STATUS == "blocked"
    assert "blocked pending source approval" in PTT_DISABLED_REASON
    assert "blocked pending source approval" in DCARD_DISABLED_REASON
    assert "approved_board_allowlist" in PTT_REQUIRED_ACCEPTANCE_FIELDS
    assert "approved_forum_allowlist" in DCARD_REQUIRED_ACCEPTANCE_FIELDS


@pytest.mark.parametrize(
    ("adapter_key", "specific_flag", "approval_flag"),
    (
        ("ptt", "SOURCE_PTT_ENABLED", "SOURCE_PTT_CANDIDATE_APPROVAL_ACK"),
        ("dcard", "SOURCE_DCARD_ENABLED", "SOURCE_DCARD_CANDIDATE_APPROVAL_ACK"),
    ),
)
@pytest.mark.parametrize(
    "env",
    (
        {},
        {"SOURCE_TERMS_REVIEW_ACK": "true"},
        {"SOURCE_FORUM_ENABLED": "true", "SOURCE_TERMS_REVIEW_ACK": "true"},
        {"SOURCE_PTT_ENABLED": "true", "SOURCE_DCARD_ENABLED": "true"},
        {
            "SOURCE_FORUM_ENABLED": "true",
            "SOURCE_PTT_ENABLED": "true",
            "SOURCE_DCARD_ENABLED": "true",
        },
        {
            "SOURCE_FORUM_ENABLED": "true",
            "SOURCE_PTT_ENABLED": "true",
            "SOURCE_DCARD_ENABLED": "true",
            "SOURCE_TERMS_REVIEW_ACK": "true",
        },
    ),
)
def test_explicit_forum_allowlist_requires_family_specific_and_terms_flags(
    adapter_key: str,
    specific_flag: str,
    approval_flag: str,
    env: dict[str, str],
) -> None:
    settings = load_worker_settings({"WORKER_ENABLED_ADAPTER_KEYS": adapter_key, **env})

    assert enabled_adapter_keys(settings) == ()

    accepted_settings = load_worker_settings(
        {
            "WORKER_ENABLED_ADAPTER_KEYS": adapter_key,
            "SOURCE_FORUM_ENABLED": "true",
            specific_flag: "true",
            "SOURCE_TERMS_REVIEW_ACK": "true",
            approval_flag: "true",
        }
    )

    assert enabled_adapter_keys(accepted_settings) == (adapter_key,)


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
            "SOURCE_NEWS_ENABLED": "true",
            "SOURCE_TERMS_REVIEW_ACK": "true",
        }
    )

    assert enabled_adapter_keys(settings) == ("news.public_web.gdelt_backfill",)


def test_explicit_adapter_allowlist_does_not_bypass_news_family_gate() -> None:
    settings = load_worker_settings(
        {
            "WORKER_ENABLED_ADAPTER_KEYS": "news.public_web.gdelt_backfill",
            "SOURCE_TERMS_REVIEW_ACK": "true",
        }
    )

    assert enabled_adapter_keys(settings) == ()


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
