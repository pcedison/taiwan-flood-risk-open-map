from __future__ import annotations

import json
import os
import subprocess
import sys
import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "local-source-candidate-smoke.py"
MODULE = REPO_ROOT / "apps" / "workers" / "app" / "ops" / "local_source_candidate_smoke.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("local_source_candidate_smoke", MODULE)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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
        "taipei_flood_depth_simulation_metadata",
        "new_taipei_pump_station_metadata",
        "new_taipei_water_gate_metadata",
        "taoyuan_water_gate_metadata",
        "taoyuan_pump_inventory",
        "taichung_pump_station_metadata",
        "taichung_gate_metadata",
        "miaoli_sewer_monitoring",
        "yunlin_flood_sensor_depth",
        "chiayi_county_management_api",
        "kaohsiung_rainfall",
        "tainan_pump_station_metadata",
        "tainan_water_gate_metadata",
        "pingtung_pteoc_rain_station",
        "taitung_flood_warning",
        "penghu_drainage_metadata",
        "kinmen_kwis_token_gated_api",
        "lienchiang_flood_prone_metadata",
        "lienchiang_erbwater_non_qualifying",
    }.issubset(keys)


def test_local_source_candidate_smoke_cli_writes_timestamped_artifact(
    tmp_path: Path,
) -> None:
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT / "apps" / "workers")}
    output = tmp_path / "candidate-smoke.json"

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--no-fetch",
            "--format",
            "json",
            "--captured-at",
            "2026-07-01T02:30:00+08:00",
            "--output",
            str(output),
        ],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    stdout_payload = json.loads(completed.stdout)
    artifact = json.loads(output.read_text(encoding="utf-8"))

    assert artifact["schema_version"] == "local-source-candidate-smoke/v1"
    assert artifact["captured_at"] == "2026-07-01T02:30:00+08:00"
    assert artifact["result"] == stdout_payload
    assert artifact["summary"]["source_count"] == stdout_payload["source_count"]
    assert artifact["summary"]["tls_verification"] == "enabled"
    assert artifact["summary"]["promotion_ready_count"] == stdout_payload[
        "status_counts"
    ].get("promotion_ready", 0)


def test_candidate_source_smoke_reports_fetch_errors_as_blockers() -> None:
    module = _load_module()
    definition = module.CandidateSourceDefinition(
        key="broken_tls_source",
        county="測試縣",
        name="TLS 失敗來源",
        url="https://example.test/source",
        expected_signal_types=("water_level",),
    )
    fetch = module.CandidateSourceFetchResult(
        url="https://example.test/source",
        status_code=None,
        content_type=None,
        error="[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed",
    )

    qualification = module.qualify_candidate_source_fetch(definition, fetch)

    assert qualification.status == "blocked_fetch_error"
    assert qualification.next_action == "retry_live_smoke_or_manual_review"
    assert qualification.observed_capabilities == ()
