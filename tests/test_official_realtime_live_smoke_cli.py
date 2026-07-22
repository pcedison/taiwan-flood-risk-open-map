from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

from app.ops.official_realtime_live_smoke import (
    OfficialRealtimeSmokeResult,
    SmokeSourceResult,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "official-realtime-live-smoke.py"


def _load_script_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "official_realtime_live_smoke_cli_under_test",
        SCRIPT,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_official_realtime_live_smoke_cli_writes_evidence_output(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    module = _load_script_module()
    evidence_path = tmp_path / "official-live-smoke.json"

    monkeypatch.setattr(module, "load_env_file", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        module,
        "run_official_realtime_live_smoke",
        lambda **_kwargs: OfficialRealtimeSmokeResult(
            results=(
                SmokeSourceResult(
                    adapter_key="official.civil_iot.sewer_water_level",
                    status="healthy",
                    fetched_count=3,
                    normalized_count=3,
                    covered_county_count=2,
                    kinmen_count=2,
                    lienchiang_count=1,
                    county_counts_by_county={"金門縣": 2, "連江縣": 1},
                ),
            )
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "official-realtime-live-smoke.py",
            "--evidence-output",
            str(evidence_path),
        ],
    )

    assert module.main() == 0

    stdout_payload = json.loads(capsys.readouterr().out)
    assert stdout_payload["results"][0]["county_counts_by_county"] == {
        "金門縣": 2,
        "連江縣": 1,
    }

    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["schema_version"] == "official-realtime-live-smoke/v1"
    assert evidence["result"] == stdout_payload
