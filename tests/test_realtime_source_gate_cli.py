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
SCRIPT = REPO_ROOT / "scripts" / "realtime-source-gate.py"


def _load_script_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "realtime_source_gate_cli_under_test",
        SCRIPT,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_realtime_source_gate_cli_can_fail_on_missing_production_gates(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    module = _load_script_module()
    evidence_path = tmp_path / "production-gates.json"
    evidence_path.write_text(
        json.dumps(
            {
                "credential_review": True,
                "source_license_review": True,
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(module, "load_env_file", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        module,
        "run_official_realtime_live_smoke",
        lambda **_kwargs: OfficialRealtimeSmokeResult(
            results=(SmokeSourceResult("official.wra.water_level", "healthy"),)
        ),
    )
    monkeypatch.setattr(module, "fetch_data_gov_dataset_export", lambda **_kwargs: [])
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "realtime-source-gate.py",
            "--production-gate-evidence-json",
            str(evidence_path),
            "--fail-on-missing-production-gates",
        ],
    )

    assert module.main() == 1

    payload = json.loads(capsys.readouterr().out)
    assert payload["production_readiness"]["satisfied_gates"] == [
        "credential_review",
        "source_license_review",
    ]
    assert "hosted_egress_review" in payload["production_readiness"]["missing_gates"]
    assert any(
        "missing production readiness gates" in failure
        for failure in payload["failures"]
    )
