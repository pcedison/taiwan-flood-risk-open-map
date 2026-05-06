import yaml

from infra.scripts.import_geocoder_open_data import (
    DEFAULT_MANIFEST_PATH,
    geocoder_row_from_mapping,
    load_manifest,
    manifest_sources,
    read_source_file,
)


def test_geocoding_manifest_lists_required_beta_coverage_sources() -> None:
    manifest = load_manifest(DEFAULT_MANIFEST_PATH)
    datasets = manifest["datasets"]
    categories = {dataset["category"] for dataset in datasets}
    keys = {dataset["key"] for dataset in datasets}

    assert {"roads", "villages", "poi"} <= categories
    assert {
        "moi-national-road-names",
        "moi-village-boundary-twd97-119",
        "nfa-evacuation-shelter-locations",
        "npa-police-station-addresses",
    } <= keys
    for dataset in datasets:
        assert dataset["landing_url"].startswith("https://data.gov.tw/")
        assert dataset["license"]
        assert dataset["update_frequency"]


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
