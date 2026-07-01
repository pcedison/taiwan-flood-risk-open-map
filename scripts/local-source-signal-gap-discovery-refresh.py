#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Mapping


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
API_APP = ROOT / "apps" / "api"
WORKER_DISCOVERY_MODULE = (
    ROOT / "apps" / "workers" / "app" / "ops" / "local_source_discovery_monitor.py"
)
sys.path.insert(0, str(API_APP))

from app.domain.realtime.local_source_action_plan import (  # noqa: E402
    build_local_source_action_plan,
)
from app.domain.realtime.local_source_coverage import (  # noqa: E402
    list_local_source_coverage,
)


SUMMARY_SCHEMA_VERSION = "local-source-signal-gap-discovery-refresh/v1"
DISCOVERY_SCHEMA_VERSION = "local-source-discovery-refresh/v1"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Refresh data.gov.tw discovery evidence for every current "
            "local-source signal-gap group."
        )
    )
    parser.add_argument(
        "--dataset-export-json",
        help=(
            "Optional data.gov.tw dataset export JSON fixture. When omitted, "
            "the live data.gov.tw export is fetched once."
        ),
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=20,
        help="data.gov.tw export request timeout when fetching live data.",
    )
    parser.add_argument(
        "--captured-at",
        help="Optional ISO 8601 timestamp for reproducible evidence artifacts.",
    )
    parser.add_argument(
        "--output-dir",
        help=(
            "Optional directory for per-signal discovery artifacts and the "
            "summary artifact."
        ),
    )
    parser.add_argument(
        "--fail-on-live-candidate",
        action="store_true",
        help=(
            "Exit with status 1 when any signal-gap group has a "
            "candidate_live_read_api result."
        ),
    )
    args = parser.parse_args(argv)

    discovery = _load_worker_discovery_module()
    captured_at = args.captured_at or datetime.now(UTC).replace(microsecond=0).isoformat()
    payload = (
        _load_json(Path(args.dataset_export_json))
        if args.dataset_export_json
        else discovery.fetch_data_gov_dataset_export(
            timeout_seconds=max(1, args.timeout_seconds)
        )
    )
    plan = build_local_source_action_plan(list_local_source_coverage())
    output_dir = Path(args.output_dir) if args.output_dir else None
    summary = build_signal_gap_discovery_refresh(
        payload=payload,
        plan=plan,
        discovery_module=discovery,
        captured_at=captured_at,
        output_dir=output_dir,
    )
    output = json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True)
    print(output)
    if args.fail_on_live_candidate and summary["total_candidate_live_read_api_count"]:
        return 1
    return 0


def build_signal_gap_discovery_refresh(
    *,
    payload: object,
    plan: Mapping[str, Any],
    discovery_module: Any,
    captured_at: str,
    output_dir: Path | None,
) -> dict[str, Any]:
    groups: list[dict[str, Any]] = []
    total_candidate_count = 0
    total_live_count = 0
    total_metadata_count = 0
    live_candidate_signal_types: list[str] = []

    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)

    for group in plan.get("signal_gap_priority_groups", []):
        if not isinstance(group, Mapping):
            continue
        signal_type = str(group.get("signal_type", ""))
        counties = [str(county) for county in group.get("counties", [])]
        result = discovery_module.discover_local_source_candidates(
            payload,
            target_counties=counties,
            required_signal_types=(signal_type,),
        )
        artifact = _build_discovery_artifact(
            captured_at=captured_at,
            source_catalog_url=discovery_module.DATA_GOV_DATASET_EXPORT_URL,
            result=result,
        )
        artifact_name = f"signal-gap-discovery-refresh-{_signal_slug(signal_type)}.json"
        if output_dir is not None:
            _write_json(output_dir / artifact_name, artifact)

        result_dict = result.to_dict()
        live_count = _candidate_count(result_dict, readiness="candidate_live_read_api")
        metadata_count = _candidate_count(result_dict, readiness="metadata_only")
        candidate_count = int(result_dict["candidate_count"])
        total_candidate_count += candidate_count
        total_live_count += live_count
        total_metadata_count += metadata_count
        if live_count:
            live_candidate_signal_types.append(signal_type)
        groups.append(
            {
                "signal_type": signal_type,
                "county_count": len(counties),
                "target_counties": counties,
                "candidate_count": candidate_count,
                "candidate_live_read_api_count": live_count,
                "metadata_only_count": metadata_count,
                "target_counties_without_candidates": result_dict["summary"][
                    "target_counties_without_candidates"
                ],
                "readiness_by_county": result_dict["summary"]["by_county"],
                "artifact_name": artifact_name,
            }
        )

    summary = {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "captured_at": captured_at,
        "source_catalog_url": discovery_module.DATA_GOV_DATASET_EXPORT_URL,
        "signal_gap_group_count": len(groups),
        "total_candidate_count": total_candidate_count,
        "total_candidate_live_read_api_count": total_live_count,
        "total_metadata_only_count": total_metadata_count,
        "live_candidate_signal_types": live_candidate_signal_types,
        "groups": groups,
    }
    if output_dir is not None:
        _write_json(output_dir / "signal-gap-discovery-refresh-summary.json", summary)
    return summary


def _build_discovery_artifact(
    *,
    captured_at: str,
    source_catalog_url: str,
    result: Any,
) -> dict[str, Any]:
    result_dict = result.to_dict()
    live_candidate_found = any(
        candidate.get("readiness") == "candidate_live_read_api"
        for candidate in result_dict["candidates"]
    )
    return {
        "schema_version": DISCOVERY_SCHEMA_VERSION,
        "captured_at": captured_at,
        "source_catalog_url": source_catalog_url,
        "conclusion": (
            "candidate_live_read_api_found"
            if live_candidate_found
            else "no_candidate_live_read_api_found"
        ),
        "discovery": result_dict,
    }


def _candidate_count(result_dict: Mapping[str, Any], *, readiness: str) -> int:
    candidates = result_dict.get("candidates")
    if not isinstance(candidates, list):
        return 0
    return sum(
        1
        for candidate in candidates
        if isinstance(candidate, Mapping) and candidate.get("readiness") == readiness
    )


def _signal_slug(signal_type: str) -> str:
    return signal_type.replace("_", "-")


def _load_worker_discovery_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "worker_local_source_discovery_monitor",
        WORKER_DISCOVERY_MODULE,
    )
    if spec is None or spec.loader is None:
        raise SystemExit(f"Cannot load discovery module: {WORKER_DISCOVERY_MODULE}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"{path}: dataset export JSON is invalid") from exc


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
