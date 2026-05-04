from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import re
import sys
from typing import Any
from urllib.parse import urlparse

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST_PATH = REPO_ROOT / "docs" / "runbooks" / "flood-potential-import.example.yaml"
SCHEMA_VERSION = "flood-potential-import/v1"
REQUIRED_TOP_LEVEL_FIELDS = {
    "schema_version",
    "production_complete",
    "source",
    "retrieval",
    "scenario",
    "processing",
    "ui",
    "limitations",
}
PLACEHOLDER_TOKENS = (
    "example.invalid",
    "replace-with",
    "template",
    "todo",
    "tbd",
    "data-owner",
    "operator",
)
ALLOWED_INPUT_FORMATS = {"shp", "zip-shp"}
ALLOWED_OUTPUT_FORMATS = {"postgis", "pmtiles", "mvt"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate flood-potential offline import manifest.")
    parser.add_argument(
        "manifest_path",
        nargs="?",
        default=str(DEFAULT_MANIFEST_PATH),
        help="Manifest YAML/JSON path. Defaults to the checked-in example template.",
    )
    parser.add_argument(
        "--production-complete",
        action="store_true",
        help="Require production_complete: true and real source/import evidence.",
    )
    args = parser.parse_args(argv)

    manifest_path = Path(args.manifest_path)
    errors = validate_manifest_file(
        manifest_path,
        require_production_complete=args.production_complete,
    )
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    try:
        display_path = manifest_path.resolve().relative_to(REPO_ROOT)
    except ValueError:
        display_path = manifest_path
    print(f"Flood-potential import manifest valid: {display_path}")
    return 0


def validate_manifest_file(
    path: Path,
    *,
    require_production_complete: bool = False,
) -> list[str]:
    errors: list[str] = []
    manifest = _load_manifest(path, errors)
    if isinstance(manifest, dict):
        validate_manifest(
            manifest,
            errors,
            require_production_complete=require_production_complete,
        )
    return errors


def validate_manifest(
    manifest: dict[str, Any],
    errors: list[str],
    *,
    require_production_complete: bool = False,
) -> None:
    missing = REQUIRED_TOP_LEVEL_FIELDS - set(manifest)
    if missing:
        errors.append(f"missing required fields: {sorted(missing)}")

    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION!r}")

    production_complete = manifest.get("production_complete")
    if not isinstance(production_complete, bool):
        errors.append("production_complete must be true or false")
        production_complete = require_production_complete
    if require_production_complete and production_complete is not True:
        errors.append("production_complete must be true when --production-complete is used")

    production_acceptance = production_complete is True or require_production_complete
    if production_acceptance and manifest.get("demo_mode") is True:
        errors.append("demo_mode must be false or absent when production_complete is true")

    _validate_source(manifest.get("source"), errors, production_acceptance=production_acceptance)
    _validate_retrieval(
        manifest.get("retrieval"),
        errors,
        production_acceptance=production_acceptance,
    )
    _validate_scenario(manifest.get("scenario"), errors)
    _validate_processing(
        manifest.get("processing"),
        errors,
        production_acceptance=production_acceptance,
    )
    _validate_ui(manifest.get("ui"), errors, production_acceptance=production_acceptance)
    _validate_limitations(manifest.get("limitations"), errors)


def _validate_source(
    source: object,
    errors: list[str],
    *,
    production_acceptance: bool,
) -> None:
    if not isinstance(source, dict):
        errors.append("source must be an object")
        return
    for field in ("name", "download_page_url", "package_url", "license", "attribution", "owner"):
        _require_non_empty_string(source, field, errors, prefix="source")
    _require_url(source.get("download_page_url"), "source.download_page_url", errors)
    _require_url(source.get("package_url"), "source.package_url", errors)
    if production_acceptance:
        _reject_placeholder(source, "source", errors)


def _validate_retrieval(
    retrieval: object,
    errors: list[str],
    *,
    production_acceptance: bool,
) -> None:
    if not isinstance(retrieval, dict):
        errors.append("retrieval must be an object")
        return
    for field in ("retrieved_at", "retrieved_by", "source_sha256", "archive_ref"):
        _require_non_empty_string(retrieval, field, errors, prefix="retrieval")
    _require_datetime(retrieval.get("retrieved_at"), "retrieval.retrieved_at", errors)
    sha = retrieval.get("source_sha256")
    if production_acceptance and not (
        isinstance(sha, str) and re.fullmatch(r"[a-fA-F0-9]{64}", sha)
    ):
        errors.append("retrieval.source_sha256 must be a 64-character SHA-256 hex digest")
    if production_acceptance:
        _reject_placeholder(retrieval, "retrieval", errors)


def _validate_scenario(scenario: object, errors: list[str]) -> None:
    if not isinstance(scenario, dict):
        errors.append("scenario must be an object")
        return
    for field in ("rainfall_duration", "return_period", "scenario_label", "county_or_scope"):
        _require_non_empty_string(scenario, field, errors, prefix="scenario")


def _validate_processing(
    processing: object,
    errors: list[str],
    *,
    production_acceptance: bool,
) -> None:
    if not isinstance(processing, dict):
        errors.append("processing must be an object")
        return
    for field in ("input_format", "output_format", "command_ref", "output_ref", "source_crs", "output_crs"):
        _require_non_empty_string(processing, field, errors, prefix="processing")
    if processing.get("input_format") not in ALLOWED_INPUT_FORMATS:
        errors.append(f"processing.input_format must be one of {sorted(ALLOWED_INPUT_FORMATS)}")
    if processing.get("output_format") not in ALLOWED_OUTPUT_FORMATS:
        errors.append(f"processing.output_format must be one of {sorted(ALLOWED_OUTPUT_FORMATS)}")
    feature_count = processing.get("feature_count")
    if not isinstance(feature_count, int) or feature_count < 0:
        errors.append("processing.feature_count must be a non-negative integer")
    if production_acceptance and feature_count == 0:
        errors.append("processing.feature_count must be greater than 0 for production")
    if production_acceptance:
        _reject_placeholder(processing, "processing", errors)


def _validate_ui(
    ui: object,
    errors: list[str],
    *,
    production_acceptance: bool,
) -> None:
    if not isinstance(ui, dict):
        errors.append("ui must be an object")
        return
    for field in ("layer_label", "not_live_warning"):
        _require_non_empty_string(ui, field, errors, prefix="ui")
    if "即時" not in str(ui.get("not_live_warning")) and "live" not in str(
        ui.get("not_live_warning")
    ).casefold():
        errors.append("ui.not_live_warning must clearly say the layer is not live/realtime")
    if production_acceptance and ui.get("attribution_visible") is not True:
        errors.append("ui.attribution_visible must be true for production")


def _validate_limitations(limitations: object, errors: list[str]) -> None:
    if not isinstance(limitations, list) or not limitations:
        errors.append("limitations must be a non-empty list")
        return
    if not all(isinstance(item, str) and item.strip() for item in limitations):
        errors.append("limitations entries must be non-empty strings")


def _load_manifest(path: Path, errors: list[str]) -> Any:
    if not path.exists():
        errors.append(f"manifest file not found: {path}")
        return None
    try:
        with path.open(encoding="utf-8") as handle:
            return yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        errors.append(f"manifest file is not valid YAML: {exc}")
        return None


def _require_non_empty_string(
    data: dict[str, Any],
    field: str,
    errors: list[str],
    *,
    prefix: str,
) -> None:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{prefix}.{field} is required")


def _require_url(value: object, field: str, errors: list[str]) -> None:
    if not isinstance(value, str):
        return
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        errors.append(f"{field} must be an http(s) URL")


def _require_datetime(value: object, field: str, errors: list[str]) -> None:
    if not isinstance(value, str):
        return
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        errors.append(f"{field} must be an ISO-8601 datetime")


def _reject_placeholder(data: dict[str, Any], prefix: str, errors: list[str]) -> None:
    for field, value in data.items():
        if isinstance(value, str) and _is_placeholder(value):
            errors.append(f"{prefix}.{field} must be replaced before production")


def _is_placeholder(value: str) -> bool:
    lower = value.casefold()
    return any(token in lower for token in PLACEHOLDER_TOKENS)


if __name__ == "__main__":
    raise SystemExit(main())
