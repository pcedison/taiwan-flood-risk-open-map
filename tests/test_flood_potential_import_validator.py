from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = REPO_ROOT / "infra" / "scripts" / "validate_flood_potential_import.py"
IMPORTER_PATH = REPO_ROOT / "infra" / "scripts" / "import_flood_potential_layer.py"
EXAMPLE_PATH = REPO_ROOT / "docs" / "runbooks" / "flood-potential-import.example.yaml"


def _load_validator_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "validate_flood_potential_import",
        VALIDATOR_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_importer_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "import_flood_potential_layer",
        IMPORTER_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_example() -> dict[str, Any]:
    with EXAMPLE_PATH.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _errors_for(manifest: dict[str, Any], *, production: bool = False) -> list[str]:
    validator = _load_validator_module()
    errors: list[str] = []
    validator.validate_manifest(
        manifest,
        errors,
        require_production_complete=production,
    )
    return errors


def test_example_manifest_template_is_valid() -> None:
    validator = _load_validator_module()

    assert validator.validate_manifest_file(EXAMPLE_PATH) == []


def test_production_complete_manifest_is_valid() -> None:
    manifest = _production_complete_manifest()

    assert _errors_for(manifest) == []
    assert _errors_for(manifest, production=True) == []


def test_production_rejects_placeholder_package_url_and_checksum() -> None:
    manifest = _production_complete_manifest()
    manifest["source"]["package_url"] = "https://example.invalid/replace-with-reviewed-shp.zip"
    manifest["retrieval"]["source_sha256"] = "replace-with-sha256"

    errors = _errors_for(manifest)

    assert "source.package_url must be replaced before production" in errors
    assert "retrieval.source_sha256 must be a 64-character SHA-256 hex digest" in errors


def test_production_requires_nonzero_features_and_visible_attribution() -> None:
    manifest = _production_complete_manifest()
    manifest["processing"]["feature_count"] = 0
    manifest["ui"]["attribution_visible"] = False

    errors = _errors_for(manifest)

    assert "processing.feature_count must be greater than 0 for production" in errors
    assert "ui.attribution_visible must be true for production" in errors


def test_manifest_requires_not_live_warning() -> None:
    manifest = _production_complete_manifest()
    manifest["ui"]["not_live_warning"] = "此圖層為規劃參考資料。"

    errors = _errors_for(manifest)

    assert "ui.not_live_warning must clearly say the layer is not live/realtime" in errors


def test_importer_dry_run_prints_pmtiles_plan(capsys: Any) -> None:
    importer = _load_importer_module()

    assert importer.main([str(EXAMPLE_PATH), "--dry-run"]) == 0

    output = capsys.readouterr().out
    assert "Flood-potential import plan: pmtiles" in output
    assert "ogr2ogr" in output
    assert "tippecanoe" in output


def test_importer_requires_source_archive_when_running(capsys: Any) -> None:
    importer = _load_importer_module()

    assert importer.main([str(EXAMPLE_PATH)]) == 1

    error_output = capsys.readouterr().err
    assert "--source-archive is required when not using --dry-run" in error_output


def test_importer_dry_run_can_require_conversion_tools(capsys: Any) -> None:
    importer = _load_importer_module()
    importer.shutil.which = lambda _tool: None

    assert importer.main([str(EXAMPLE_PATH), "--dry-run", "--require-tools"]) == 1

    error_output = capsys.readouterr().err
    assert "required conversion tool not found on PATH: ogr2ogr" in error_output


def _production_complete_manifest() -> dict[str, Any]:
    manifest = copy.deepcopy(_load_example())
    manifest["production_complete"] = True
    manifest["demo_mode"] = False
    manifest["source"] = {
        "name": "DPRC/WRA flood-potential SHP package",
        "download_page_url": "https://www.dprcflood.org.tw/DPRC/02.html",
        "package_url": "https://cdn.flood-risk.tw/flood-potential/2026-05-04/source.zip",
        "license": "Government open data license reviewed for FR-FP-2026-05-04",
        "attribution": "經濟部水利署 / 水災保全計畫資訊服務網",
        "owner": "flood-potential-lead@flood-risk.internal",
    }
    manifest["retrieval"] = {
        "retrieved_at": "2026-05-04T10:00:00+08:00",
        "retrieved_by": "flood-potential-lead@flood-risk.internal",
        "source_sha256": "a" * 64,
        "archive_ref": "private-ops://flood-potential/source/FR-FP-2026-05-04.zip",
    }
    manifest["scenario"] = {
        "rainfall_duration": "24h",
        "return_period": "100-year",
        "scenario_label": "24h 100-year rainfall flood-potential scenario",
        "county_or_scope": "Taiwan",
    }
    manifest["processing"] = {
        "input_format": "zip-shp",
        "output_format": "pmtiles",
        "command_ref": "private-ops://flood-potential/import/FR-FP-2026-05-04.log",
        "output_ref": "s3://flood-risk-public/flood-potential/2026-05-04/layer.pmtiles",
        "feature_count": 4242,
        "source_crs": "TWD97 / TM2",
        "output_crs": "EPSG:4326",
    }
    manifest["ui"] = {
        "layer_label": "淹水潛勢圖",
        "not_live_warning": "此圖層不是即時淹水警報，僅供規劃與歷史潛勢參考。",
        "attribution_visible": True,
    }
    manifest["limitations"] = [
        "Flood-potential layer is not live flood detection.",
        "Scenario and retrieval date must be shown near the layer.",
    ]
    return manifest
