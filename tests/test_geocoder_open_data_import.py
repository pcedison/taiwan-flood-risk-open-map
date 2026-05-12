import copy

import yaml

from infra.scripts.import_geocoder_open_data import (
    DEFAULT_MANIFEST_PATH,
    geocoder_row_from_mapping,
    load_manifest,
    manifest_sources,
    read_source_file,
    write_evidence_json,
)
from infra.scripts.extract_village_centroids import row_from_shape_record
from infra.scripts.geocoder_coverage_smoke import coverage_summary


def test_geocoding_manifest_lists_required_beta_coverage_sources() -> None:
    manifest = load_manifest(DEFAULT_MANIFEST_PATH)
    datasets = manifest["datasets"]
    categories = {dataset["category"] for dataset in datasets}
    datasets_by_key = {dataset["key"]: dataset for dataset in datasets}
    keys = {dataset["key"] for dataset in datasets}

    assert {"roads", "villages", "poi"} <= categories
    assert {
        "moi-national-road-names",
        "moi-village-boundary-twd97-geographic",
        "nfa-evacuation-shelter-locations",
        "npa-police-station-addresses",
    } <= keys
    for dataset in datasets:
        assert dataset["landing_url"].startswith("https://data.gov.tw/")
        assert dataset["data_gov_url"].startswith("https://data.gov.tw/dataset/")
        assert dataset["license"]
        assert dataset["update_frequency"]
    assert datasets_by_key["moi-national-road-names"]["data_gov_dataset_id"] == "35321"
    assert datasets_by_key["moi-village-boundary-twd97-geographic"]["data_gov_dataset_id"] == "7438"
    assert datasets_by_key["nfa-evacuation-shelter-locations"]["data_gov_dataset_id"] == "73242"
    assert manifest["unavailable_sources"][0]["data_gov_suggest_url"] == (
        "https://data.gov.tw/suggests/136942"
    )


def test_geocoding_manifest_matches_official_source_catalog_for_primary_sources() -> None:
    manifest = load_manifest(DEFAULT_MANIFEST_PATH)
    catalog_path = (
        DEFAULT_MANIFEST_PATH.parents[1] / "official" / "official-source-catalog.yaml"
    )
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    catalog_sources = {source["key"]: source for source in catalog["sources"]}
    datasets_by_catalog_key = {
        dataset["source_catalog_key"]: dataset
        for dataset in manifest["datasets"]
        if dataset.get("source_catalog_key")
    }

    for catalog_key in (
        "geocoder.moi.road_names",
        "geocoder.moi.village_boundary",
        "geocoder.nfa.shelters",
    ):
        dataset = datasets_by_catalog_key[catalog_key]
        catalog_source = catalog_sources[catalog_key]
        assert dataset["data_gov_dataset_id"] == catalog_source["data_gov_dataset_id"]
        assert dataset["data_gov_url"] == catalog_source["data_gov_url"]
        assert dataset["resource_url"] == catalog_source["resource_url"]


def test_importer_normalizes_point_rows_with_manifest_defaults(tmp_path) -> None:
    manifest = load_manifest(DEFAULT_MANIFEST_PATH)
    source = manifest_sources(manifest)["npa-police-station-addresses"]
    source_path = tmp_path / "police.csv"
    source_path.write_text(
        "\n".join(
            [
                "中文單位名稱,地址,POINT_X,POINT_Y",
                "臺南市政府警察局測試派出所,臺南市安南區長溪路二段410巷16弄1號,120.20144,23.05753",
                "missing coordinate,臺南市安南區長溪路二段410巷16弄2號,,",
            ]
        ),
        encoding="utf-8",
    )

    rows, skipped = read_source_file(source_path, source)

    assert skipped == 1
    assert len(rows) == 1
    assert rows[0].precision == "poi"
    assert rows[0].place_type == "poi"
    assert "台南市安南區長溪路2段410巷16弄1號" in rows[0].normalized_aliases
    assert rows[0].attribution == "內政部警政署，警察機關地址資料"


def test_importer_maps_road_names_to_admin_centroid_with_limitation(tmp_path) -> None:
    manifest = load_manifest(DEFAULT_MANIFEST_PATH)
    source = manifest_sources(manifest)["moi-national-road-names"]
    source_path = tmp_path / "roads.csv"
    source_path.write_text(
        "\n".join(
            [
                "city,site_id,road",
                "台北市,台北市大安區,信義路三段",
                "測試縣,測試縣不存在區,不存在路",
            ]
        ),
        encoding="utf-8",
    )

    rows, skipped = read_source_file(source_path, source)

    assert skipped == 1
    assert len(rows) == 1
    assert rows[0].name == "台北市大安區信義路三段"
    assert rows[0].precision == "road_or_lane"
    assert rows[0].confidence == 0.63
    assert rows[0].metadata["coordinate_precision"] == "admin_area_centroid"
    assert rows[0].metadata["data_gov_dataset_id"] == "35321"
    assert rows[0].metadata["data_gov_url"] == "https://data.gov.tw/dataset/35321"
    assert rows[0].metadata["resource_url"].startswith("https://www.ris.gov.tw/")
    assert rows[0].limitations


def test_import_evidence_json_carries_data_gov_source_metadata(tmp_path) -> None:
    manifest = load_manifest(DEFAULT_MANIFEST_PATH)
    source = manifest_sources(manifest)["nfa-evacuation-shelter-locations"]
    row = geocoder_row_from_mapping(
        {
            "Shelter Name": "Test Shelter",
            "Shelter address": "Test Address",
            "Longitude": "120.3",
            "Latitude": "22.7",
        },
        source,
    )
    assert row is not None

    evidence_path = tmp_path / "evidence.json"
    write_evidence_json(evidence_path, source, [row], skipped=0)

    payload = yaml.safe_load(evidence_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "geocoder-import-evidence/v1"
    assert payload["data_gov_dataset_id"] == "73242"
    assert payload["data_gov_url"] == "https://data.gov.tw/dataset/73242"
    assert payload["source_catalog_key"] == "geocoder.nfa.shelters"
    assert payload["resource_url"].startswith("https://opdadm.moi.gov.tw/")


def test_village_centroid_extractor_outputs_admin_fallback_row() -> None:
    row = row_from_shape_record(
        {
            "VILLCODE": "65000050015",
            "COUNTYNAME": "新北市",
            "TOWNNAME": "新莊區",
            "VILLNAME": "西盛里",
        },
        (121.4263, 24.9952, 121.4373, 25.0250),
    )

    assert row is not None
    assert row["name"] == "新北市新莊區西盛里"
    assert row["precision"] == "admin_area"
    assert row["type"] == "admin_area"
    assert row["confidence"] == "0.70"
    assert "村里界資料" in str(row["limitations"])


def test_coverage_smoke_accepts_beta_categories_and_precisions() -> None:
    manifest = load_manifest(DEFAULT_MANIFEST_PATH)
    rows = [
        {"source_key": "moi-national-road-names", "precision": "road_or_lane"},
        {"source_key": "moi-village-boundary-twd97-geographic", "precision": "admin_area"},
        {"source_key": "nfa-evacuation-shelter-locations", "precision": "poi"},
    ]

    summary = coverage_summary(manifest, rows, production_complete=False)

    assert summary["missing_requirements"] == []
    assert summary["production_complete"] is False


def test_coverage_smoke_rejects_beta_fallback_as_production_complete() -> None:
    manifest = load_manifest(DEFAULT_MANIFEST_PATH)
    rows = [
        {"source_key": "moi-national-road-names", "precision": "road_or_lane"},
        {"source_key": "moi-village-boundary-twd97-geographic", "precision": "admin_area"},
        {"source_key": "nfa-evacuation-shelter-locations", "precision": "poi"},
    ]

    summary = coverage_summary(manifest, rows, production_complete=True)

    assert "manifest:production_complete" in summary["missing_requirements"]
    assert "production_category:addresses" in summary["missing_requirements"]
    assert "production_precision:exact_address" in summary["missing_requirements"]
    assert (
        "production_evidence:all_taiwan_address_source_ref"
        in summary["missing_requirements"]
    )
    assert summary["production_complete"] is False


def test_coverage_smoke_accepts_reviewed_address_rows_for_production_complete() -> None:
    manifest = copy.deepcopy(load_manifest(DEFAULT_MANIFEST_PATH))
    manifest["production_complete"] = True
    manifest["production_complete_evidence"] = {
        "all_taiwan_address_source_ref": "private-ops://geocoder/address-source/2026-05-06",
        "license_review_ref": "private-ops://geocoder/license-review/2026-05-06",
        "coverage_review_ref": "private-ops://geocoder/coverage-review/2026-05-06",
    }
    manifest["datasets"].append(
        {
            "key": "reviewed-national-doorplate-addresses",
            "category": "addresses",
            "status": "production_ready_imported",
        }
    )
    rows = [
        {"source_key": "reviewed-national-doorplate-addresses", "precision": "exact_address"},
        {"source_key": "moi-national-road-names", "precision": "road_or_lane"},
        {"source_key": "moi-village-boundary-twd97-geographic", "precision": "admin_area"},
        {"source_key": "nfa-evacuation-shelter-locations", "precision": "poi"},
    ]

    summary = coverage_summary(manifest, rows, production_complete=True)

    assert summary["missing_requirements"] == []
    assert summary["production_complete"] is True


def test_importer_rejects_rows_outside_taiwan_bounds() -> None:
    manifest = load_manifest(DEFAULT_MANIFEST_PATH)
    source = manifest_sources(manifest)["nfa-evacuation-shelter-locations"]

    assert (
        geocoder_row_from_mapping(
            {
                "Shelter Name": "Outside Taiwan",
                "Longitude": "-122.4194",
                "Latitude": "37.7749",
            },
            source,
        )
        is None
    )


def test_manifest_yaml_is_plain_object() -> None:
    payload = yaml.safe_load(DEFAULT_MANIFEST_PATH.read_text(encoding="utf-8"))

    assert payload["schema_version"] == "geocoding-data-manifest/v1"
    assert payload["production_complete"] is False
