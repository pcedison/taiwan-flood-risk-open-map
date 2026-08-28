from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.adapters.registry import ADAPTER_REGISTRY
from app.adapters.wra import WRA_FLOOD_WARNING_KML_URLS

REPO_ROOT = Path(__file__).resolve().parents[3]
CATALOG_PATH = REPO_ROOT / "docs" / "data-sources" / "official" / "official-source-catalog.yaml"


def _catalog() -> dict[str, Any]:
    payload = yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_official_source_catalog_schema_and_primary_sources() -> None:
    catalog = _catalog()
    assert catalog["schema_version"] == "official-source-catalog/v1"
    sources = {source["key"]: source for source in catalog["sources"]}

    assert sources["official.cwa.rainfall"]["data_gov_dataset_id"] == "9177"
    assert sources["official.cwa.tide_level"]["data_gov_dataset_id"] == "O-B0075-001"
    assert sources["official.cwa.heavy_rain_warning"]["data_gov_dataset_id"] == "W-C0033-003"
    assert sources["official.cwa.heavy_rain_warning"]["status"] == "disabled_by_default"
    assert sources["official.cwa.heavy_rain_warning"]["license"] == (
        "中央氣象署開放資料平臺使用規範"
    )
    assert sources["official.cwa.heavy_rain_warning"]["license_url"] == (
        "https://opendata.cwa.gov.tw/about/rules"
    )
    assert sources["official.wra.water_level"]["data_gov_dataset_id"] == "25768"
    assert sources["official.wra_iow.flood_depth"]["data_gov_dataset_id"] == "142980"
    assert sources["official.wra_iow.flood_depth"]["update_frequency"] == (
        "data.gov.tw metadata: every 1 hour"
    )
    assert sources["official.wra.historical_flood"]["data_gov_dataset_id"] == "25770"
    assert sources["official.wra.historical_flood"]["resource_url"] == (
        "https://opendata.wra.gov.tw/api/v2/"
        "72d7aee9-e29b-49a2-bd0b-54acc8e3b75c?format=JSON&sort=_importdate+asc"
    )
    assert sources["official.wra.historical_flood"]["status"] == "disabled_by_default"
    assert sources["official.ncdr.cap"]["status"] == "disabled_by_default"
    assert sources["official.ncdr.cap"]["resource_url"] == (
        "https://alerts.ncdr.nat.gov.tw/RssAtomFeeds.ashx"
    )
    assert sources["official.ncdr.cap"]["dump_url"] == (
        "https://alerts.ncdr.nat.gov.tw/api/dump/datastore"
    )
    assert sources["official.ncdr.cap"]["resource_format"] == (
        "public active-warning Atom index to CAP XML; member datastore remains supported when an API key is configured"
    )
    assert sources["official.npa.police_radio_traffic"]["status"] == ("disabled_by_default")
    assert sources["official.npa.police_radio_traffic"]["data_gov_dataset_id"] == "15221"
    assert sources["official.npa.police_radio_traffic"]["data_gov_url"] == (
        "https://data.gov.tw/dataset/15221"
    )
    assert sources["official.npa.police_radio_traffic"]["resource_url"] == (
        "https://rtr.pbs.gov.tw/NMP103_PbsWS/resources/roadData/opendata"
    )
    assert sources["official.flood_potential.geojson"]["data_gov_dataset_id"] == "25766"
    assert sources["official.wra.flood_warning"]["status"] == "disabled_by_default"
    assert sources["official.wra.flood_warning"]["data_gov_dataset_ids"] == [
        "5982",
        "5983",
        "5984",
    ]
    assert sources["official.wra.flood_warning"]["active_fixture_reviewed"] is False
    assert sources["official.wra.flood_warning"]["kml_resource_urls"] == list(
        WRA_FLOOD_WARNING_KML_URLS
    )
    assert sources["geocoder.moi.village_boundary"]["data_gov_url"].startswith(
        "https://data.gov.tw/dataset/"
    )

    for source in catalog["sources"]:
        assert source["data_gov_url"].startswith(
            (
                "https://data.gov.tw/",
                "https://opendata.cwa.gov.tw/",
                "https://alerts.ncdr.nat.gov.tw/",
            )
        )
        assert source["resource_url"].startswith("https://")
        assert source["license"]
        assert source["limitations"]


def test_runtime_official_adapter_metadata_matches_source_catalog() -> None:
    catalog = _catalog()
    sources = {source["key"]: source for source in catalog["sources"]}

    for adapter_key in (
        "official.cwa.rainfall",
        "official.cwa.tide_level",
        "official.cwa.heavy_rain_warning",
        "official.wra.water_level",
        "official.wra_iow.flood_depth",
        "official.wra.historical_flood",
        "official.ncdr.cap",
        "official.npa.police_radio_traffic",
        "official.wra.flood_warning",
        "official.flood_potential.geojson",
    ):
        metadata = ADAPTER_REGISTRY[adapter_key]
        source = sources[adapter_key]

        assert metadata.data_gov_dataset_id == source["data_gov_dataset_id"]
        assert metadata.data_gov_url == source["data_gov_url"]
        assert metadata.resource_url is not None
        assert metadata.resource_url.startswith(source["resource_url"])
        assert metadata.license == source["license"]
        assert metadata.limitations


def test_migration_0038_registered_keys_stay_disabled_in_catalog_and_registry() -> None:
    migration = (
        REPO_ROOT / "infra" / "migrations" / "0038_official_incident_context_sources.sql"
    ).read_text(encoding="utf-8")
    registered_keys = {
        "official.cwa.heavy_rain_warning",
        "official.ncdr.cap",
        "official.npa.police_radio_traffic",
        "official.wra.flood_warning",
    }
    sources = {source["key"]: source for source in _catalog()["sources"]}

    for key in registered_keys:
        assert f"'{key}'" in migration, key
        assert sources[key]["status"] == "disabled_by_default", key
        assert ADAPTER_REGISTRY[key].enabled_by_default is False, key

    assert "true" not in migration
    assert migration.count("false") == len(registered_keys)
