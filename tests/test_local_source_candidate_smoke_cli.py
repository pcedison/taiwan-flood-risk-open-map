from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "local-source-candidate-smoke.py"


def test_local_source_candidate_smoke_cli_outputs_static_catalog_without_fetching() -> None:
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT / "apps" / "workers")}

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--no-fetch", "--format", "json"],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    payload = json.loads(completed.stdout)

    assert payload["source_count"] >= 7
    assert payload["status_counts"]["not_checked"] >= 7
    keys = {source["key"] for source in payload["sources"]}
    assert {
        "taipei_evacuate_gate",
        "miaoli_sewer_monitoring",
        "yunlin_flood_sensor_depth",
        "chiayi_county_management_api",
        "kaohsiung_rainfall",
        "pingtung_pteoc_rain_station",
        "taitung_flood_warning",
    }.issubset(keys)
