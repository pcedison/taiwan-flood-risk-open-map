from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST_PATH = REPO_ROOT / "docs" / "data-sources" / "geocoding" / "geocoding-data-manifest.yaml"
BETA_REQUIRED_PRECISIONS = {"road_or_lane", "poi", "admin_area"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate no-secret geocoder import coverage evidence.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST_PATH))
    parser.add_argument("--input-jsonl", action="append", default=[])
    parser.add_argument("--evidence-json", help="Optional JSON output path.")
    parser.add_argument("--production-complete", action="store_true")
    args = parser.parse_args(argv)

    manifest = load_manifest(Path(args.manifest))
    rows = [row for path in args.input_jsonl for row in read_jsonl(Path(path))]
    summary = coverage_summary(manifest, rows, production_complete=args.production_complete)

    if args.evidence_json:
        output_path = Path(args.evidence_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    print(
        "geocoder coverage "
        f"rows={summary['row_count']} "
        f"categories={','.join(sorted(summary['category_counts']))} "
        f"missing={','.join(summary['missing_requirements']) or '-'}"
    )
    return 1 if summary["missing_requirements"] else 0


def load_manifest(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"manifest must be a YAML object: {path}")
    return payload


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def coverage_summary(
    manifest: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    production_complete: bool,
) -> dict[str, Any]:
    source_categories = {
        str(dataset["key"]): str(dataset["category"])
        for dataset in manifest.get("datasets", [])
        if isinstance(dataset, dict) and dataset.get("key") and dataset.get("category")
    }
    category_counts: dict[str, int] = {}
    precision_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}
    for row in rows:
        source_key = str(row.get("source_key") or "")
        precision = str(row.get("precision") or "unknown")
        category = source_categories.get(source_key, "unknown")
        source_counts[source_key] = source_counts.get(source_key, 0) + 1
        category_counts[category] = category_counts.get(category, 0) + 1
        precision_counts[precision] = precision_counts.get(precision, 0) + 1

    smoke = manifest.get("smoke_tests", {}) if isinstance(manifest.get("smoke_tests"), dict) else {}
    required_categories = set(smoke.get("required_categories") or ())
    required_precisions = set(smoke.get("required_precision_values") or ())
    missing: list[str] = []
    for category in sorted(required_categories):
        if category_counts.get(category, 0) <= 0:
            missing.append(f"category:{category}")
    for precision in sorted(BETA_REQUIRED_PRECISIONS):
        if precision_counts.get(precision, 0) <= 0:
            missing.append(f"precision:{precision}")
    if production_complete:
        for precision in sorted(required_precisions):
            if precision_counts.get(precision, 0) <= 0:
                missing.append(f"production_precision:{precision}")

    return {
        "schema_version": "geocoder-coverage-smoke/v1",
        "production_complete": production_complete and not missing,
        "row_count": len(rows),
        "source_counts": source_counts,
        "category_counts": category_counts,
        "precision_counts": precision_counts,
        "required_categories": sorted(required_categories),
        "required_precision_values": sorted(required_precisions),
        "missing_requirements": missing,
    }


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
