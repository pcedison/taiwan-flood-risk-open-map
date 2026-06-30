from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.adapters.registry import ADAPTER_REGISTRY


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
    assert sources["official.wra.water_level"]["data_gov_dataset_id"] == "25768"
    assert sources["official.wra_iow.flood_depth"]["data_gov_dataset_id"] == "142980"
    assert sources["official.flood_potential.geojson"]["data_gov_dataset_id"] == "25766"
    assert sources["official.wra.flood_warning"]["status"] == "phase4_candidate"
    assert sources["geocoder.moi.village_boundary"]["data_gov_url"].startswith(
        "https://data.gov.tw/dataset/"
    )

    for source in catalog["sources"]:
        assert source["data_gov_url"].startswith(
            ("https://data.gov.tw/", "https://opendata.cwa.gov.tw/")
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
        "official.wra.water_level",
        "official.wra_iow.flood_depth",
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
