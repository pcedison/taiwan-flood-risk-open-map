"""Anti-drift guardrail for the ADR-0010 dual CWA/WRA realtime parsers.

ADR-0010 (docs/adr/0010-realtime-bridge-as-local-diagnostic.md) deliberately
keeps two parallel implementations that each parse the same upstream CWA/WRA
responses:

- The API bridge, used only as a local diagnostic tool:
  apps/api/app/domain/realtime/official.py
- The workers adapters, the hosted runtime's source of truth:
  apps/workers/app/adapters/cwa/rainfall.py, apps/workers/app/adapters/wra/water_level.py

The ADR accepts this duplication (collapsing it into a shared package would
break the editable-install layout both apps and CI rely on) but calls out that
"an upstream schema change must be applied in both places" only lives in
people's memory. This test feeds the SAME raw upstream fixtures into both
parsers and asserts station id, coordinates, observed value, and observed time
line up, so single-sided drift goes red instead of silently reaching
production.

The two apps are separate regular packages that both expose a top-level ``app``
package, so they cannot be imported into one interpreter reliably. Each side's
parser therefore runs in a subprocess whose cwd is that app's root (see
tests/support/dual_parse_extract.py), and this test compares the JSON output.

Known, deliberate parser differences NOT covered here (audit F2-A): the workers
CWA adapter keeps a station if ANY precipitation window (10m/1h/24h) is valid
while the bridge requires the 1-hour window; the bridge requires a WRA metadata
row with observationstatus == "現存" while the worker does not. The shared
fixtures' malformed stations are rejected by both sides regardless, so these
differences are not exercised here.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_FIXTURES_DIR = REPO_ROOT / "packages" / "contracts" / "fixtures" / "upstream"
EXTRACTOR = REPO_ROOT / "tests" / "support" / "dual_parse_extract.py"
API_ROOT = REPO_ROOT / "apps" / "api"
WORKERS_ROOT = REPO_ROOT / "apps" / "workers"


def _extract(mode: str, app_root: Path, fixture: str) -> list[dict[str, Any]]:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    result = subprocess.run(
        [sys.executable, str(EXTRACTOR), mode, str(UPSTREAM_FIXTURES_DIR / fixture)],
        cwd=str(app_root),
        capture_output=True,
        env=env,
    )
    stderr = result.stderr.decode("utf-8", errors="replace")
    assert result.returncode == 0, f"{mode} extractor failed:\n{stderr}"
    return json.loads(result.stdout.decode("utf-8"))


def _by_id(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {record["station_id"]: record for record in records}


def test_cwa_rainfall_dual_parse_contract() -> None:
    """Bridge and worker CWA rainfall parsers must agree on the same sample."""
    bridge = _by_id(_extract("cwa-bridge", API_ROOT, "cwa-rainfall.json"))
    worker = _by_id(_extract("cwa-worker", WORKERS_ROOT, "cwa-rainfall.json"))

    assert bridge.keys() == worker.keys()
    assert bridge.keys() == {"C0A560"}

    for station_id, b in bridge.items():
        w = worker[station_id]
        assert b["station_name"] == w["station_name"]
        assert b["lat"] == w["lat"]
        assert b["lng"] == w["lng"]
        assert b["rainfall_1h"] == w["rainfall_1h"]
        assert b["rainfall_10m"] == w["rainfall_10m"]
        assert b["rainfall_24h"] == w["rainfall_24h"]
        assert b["observed_at"] == w["observed_at"]


def test_wra_water_level_dual_parse_contract() -> None:
    """Bridge and worker WRA water-level parsers must agree on the same sample."""
    bridge = _by_id(_extract("wra-bridge", API_ROOT, "wra-water-level.json"))
    worker = _by_id(_extract("wra-worker", WORKERS_ROOT, "wra-water-level.json"))

    assert bridge.keys() == worker.keys()
    assert bridge.keys() == {"1010H006"}

    for station_id, b in bridge.items():
        w = worker[station_id]
        assert b["station_name"] == w["station_name"]
        assert b["river_name"] == w["river_name"]
        assert b["lat"] == w["lat"]
        assert b["lng"] == w["lng"]
        assert b["water_level_m"] == w["water_level_m"]
        assert b["observed_at"] == w["observed_at"]
        assert b["warning_level_m"] == w["warning_level_m"]
