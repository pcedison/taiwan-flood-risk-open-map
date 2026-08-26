"""Aggregate release contract for the safe-fast official incident expansion.

This test reads only checked-in artifacts. It proves the code landed and every
new source is off by default. It proves nothing about any deployed environment
and must never be read as an activation claim.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_EXAMPLE = REPO_ROOT / ".env.example"
REGISTRY = REPO_ROOT / "apps" / "workers" / "app" / "adapters" / "registry.py"
CONFIG = REPO_ROOT / "apps" / "workers" / "app" / "config.py"
RUNTIME = REPO_ROOT / "apps" / "workers" / "app" / "jobs" / "runtime.py"
CATALOG = (
    REPO_ROOT / "docs" / "data-sources" / "official" / "official-source-catalog.yaml"
)
MIGRATION = (
    REPO_ROOT
    / "infra"
    / "migrations"
    / "0038_official_incident_context_sources.sql"
)
RUNBOOK = (
    REPO_ROOT / "docs" / "runbooks" / "safe-fast-official-incident-activation.md"
)

ADAPTER_KEYS = (
    "official.cwa.heavy_rain_warning",
    "official.ncdr.cap",
    "official.npa.police_radio_traffic",
    "official.wra.flood_warning",
)
DEFAULT_FALSE_FLAGS = (
    "SOURCE_CWA_ENABLED",
    "SOURCE_CWA_HEAVY_RAIN_WARNING_ENABLED",
    "SOURCE_NCDR_CAP_ENABLED",
    "SOURCE_NCDR_CAP_API_ENABLED",
    "SOURCE_NCDR_CAP_CONTRACT_ENABLED",
    "SOURCE_NPA_POLICE_RADIO_ENABLED",
    "SOURCE_NPA_POLICE_RADIO_API_ENABLED",
    "SOURCE_NPA_POLICE_RADIO_CONTRACT_ENABLED",
    "SOURCE_WRA_FLOOD_WARNING_ENABLED",
    "SOURCE_WRA_FLOOD_WARNING_API_ENABLED",
    "SOURCE_WRA_FLOOD_WARNING_CONTRACT_ENABLED",
)
WRA_FLOOD_WARNING_KML_URLS = (
    "https://fhy.wra.gov.tw/pub_web_2011/kml/KmlShare/NewstFloodWarm.kml",
    "https://fhy.wra.gov.tw/pub_web_2011/kml/KmlShare/NewstWaterWarm.kml",
    "https://fhy.wra.gov.tw/pub_web_2011/kml/KmlShare/NewstReservoirWarm.kml",
    "https://fhy.wra.gov.tw/pub_web_2011/kml/KmlShare/AnnounceFlood.kml",
)
POLICE_LIMITATION = "警廣即時路況通報，尚未由淹水感測器確認。"
RELEASE_STATEMENT = "code landed/default off; not production activated"
ROLLBACK_ORDER = (
    "disable the catalog row first",
    "then the runtime, api, and contract gates",
)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _catalog_sources() -> dict[str, dict[str, object]]:
    payload = yaml.safe_load(_text(CATALOG))
    return {str(source["key"]): source for source in payload["sources"]}


def test_every_gate_defaults_to_false_in_the_checked_in_environment() -> None:
    env = _text(ENV_EXAMPLE)

    for flag in DEFAULT_FALSE_FLAGS:
        assert f"{flag}=false" in env, flag
        assert f"{flag}=true" not in env, flag


def test_all_four_adapter_keys_are_registered_and_catalogued_disabled() -> None:
    adapters_root = REPO_ROOT / "apps" / "workers" / "app" / "adapters"
    declared = "\n".join(
        _text(module) for module in sorted(adapters_root.rglob("*.py"))
    )
    registry = _text(REGISTRY)
    sources = _catalog_sources()

    for key in ADAPTER_KEYS:
        # The metadata literal lives in the adapter module; the registry wires it
        # into the enablement gates by key or by an explicit metadata predicate.
        assert f'"{key}"' in declared, key
        assert key.rsplit(".", 1)[-1] in registry, key
        assert sources[key]["status"] == "disabled_by_default", key


def test_runtime_builders_require_every_independent_gate() -> None:
    runtime = _text(RUNTIME)
    config = _text(CONFIG)

    for prefix in ("source_ncdr_cap", "source_npa_police_radio", "source_wra_flood_warning"):
        for suffix in ("_enabled", "_api_enabled", "_contract_enabled"):
            assert f"{prefix}{suffix}" in config, f"{prefix}{suffix}"
            assert f"settings.{prefix}{suffix}" in runtime, f"{prefix}{suffix}"


def test_ncdr_keeps_its_exact_datastore_and_dump_contract() -> None:
    ncdr = _catalog_sources()["official.ncdr.cap"]

    assert ncdr["resource_url"] == "https://alerts.ncdr.nat.gov.tw/api/datastore"
    assert ncdr["dump_url"] == "https://alerts.ncdr.nat.gov.tw/api/dump/datastore"
    assert ncdr["resource_format"] == "JSON datastore index to CAP XML dump"


def test_wra_warning_allowlist_is_exact_and_immutable() -> None:
    adapter = _text(
        REPO_ROOT / "apps" / "workers" / "app" / "adapters" / "wra" / "flood_warning.py"
    )
    catalog_urls = _catalog_sources()["official.wra.flood_warning"]["kml_resource_urls"]

    assert list(catalog_urls) == list(WRA_FLOOD_WARNING_KML_URLS)
    for url in WRA_FLOOD_WARNING_KML_URLS:
        assert adapter.count(f'"{url}"') == 1, url


def test_police_context_keeps_its_exact_public_limitation() -> None:
    adapter = _text(
        REPO_ROOT
        / "apps"
        / "workers"
        / "app"
        / "adapters"
        / "police_radio_traffic"
        / "road_incidents.py"
    )
    catalog = _catalog_sources()["official.npa.police_radio_traffic"]

    assert POLICE_LIMITATION in adapter
    assert POLICE_LIMITATION in [str(item) for item in catalog["limitations"]]


def test_migration_leaves_every_new_row_disabled() -> None:
    migration = _text(MIGRATION)

    assert "is_enabled = EXCLUDED.is_enabled" in migration
    assert migration.count("false") == len(ADAPTER_KEYS)
    assert "true" not in migration


def test_runbook_states_the_release_status_and_rollback_order() -> None:
    runbook = _text(RUNBOOK)
    # Order and wording are the contract; sentence capitalization is not.
    lowered = runbook.lower()

    assert RELEASE_STATEMENT in runbook
    for phrase in ROLLBACK_ORDER:
        assert phrase in lowered, phrase
    assert lowered.index(ROLLBACK_ORDER[0]) < lowered.index(ROLLBACK_ORDER[1])


def test_runbook_carries_no_credential_and_no_activation_claim() -> None:
    runbook = _text(RUNBOOK).lower()

    for forbidden in ("password", "bearer ", "private-ops://", "cwa-abcd"):
        assert forbidden not in runbook, forbidden
    for claim in (
        "source is now enabled",
        "activated in production",
        "production activated",
    ):
        assert claim not in runbook.replace(RELEASE_STATEMENT, ""), claim


def test_runbook_documents_the_non_scoring_and_audit_only_boundaries() -> None:
    runbook = _text(RUNBOOK)

    assert "audit-only" in runbook
    assert "non-scoring" in runbook
    for key in ADAPTER_KEYS:
        assert key in runbook, key
