from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "local-source-signal-gap-evidence.py"


def _load_script_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "local_source_signal_gap_evidence_cli_under_test",
        SCRIPT,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_local_source_signal_gap_evidence_cli_writes_artifact(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    module = _load_script_module()
    smoke_path = tmp_path / "official-live-smoke.json"
    output_path = tmp_path / "signal-gap-evidence.json"
    smoke_path.write_text(
        json.dumps(
            {
                "schema_version": "official-realtime-live-smoke/v1",
                "captured_at": "2026-06-30T19:45:00+08:00",
                "result": {
                    "healthy": True,
                    "results": [
                        {
                            "adapter_key": "official.civil_iot.pump_water_level",
                            "status": "healthy",
                            "county_counts_by_county": {"A County": 2},
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        module,
        "build_local_source_action_plan",
        lambda _records: {
            "signal_gap_priority_groups": [
                {
                    "signal_type": "pump_or_gate_status",
                    "county_count": 2,
                    "counties": ["A County", "B County"],
                }
            ]
        },
    )
    monkeypatch.setattr(module, "list_local_source_coverage", lambda: ())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "local-source-signal-gap-evidence.py",
            "--official-live-smoke-json",
            str(smoke_path),
            "--captured-at",
            "2026-06-30T20:20:00+08:00",
            "--output",
            str(output_path),
        ],
    )

    assert module.main() == 0

    stdout_payload = json.loads(capsys.readouterr().out)
    evidence = json.loads(output_path.read_text(encoding="utf-8"))

    assert stdout_payload == evidence
    assert evidence["schema_version"] == "local-source-signal-gap-evidence/v1"
    assert evidence["captured_at"] == "2026-06-30T20:20:00+08:00"
    assert evidence["summary"]["official_smoke_observed_item_count"] == 1
    assert evidence["summary"]["unresolved_after_official_smoke_item_count"] == 1


def test_local_source_signal_gap_evidence_cli_can_fail_on_unresolved(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script_module()
    smoke_path = tmp_path / "official-live-smoke.json"
    smoke_path.write_text(
        json.dumps({"result": {"results": []}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        module,
        "build_local_source_action_plan",
        lambda _records: {
            "signal_gap_priority_groups": [
                {
                    "signal_type": "flood_depth",
                    "county_count": 1,
                    "counties": ["B County"],
                }
            ]
        },
    )
    monkeypatch.setattr(module, "list_local_source_coverage", lambda: ())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "local-source-signal-gap-evidence.py",
            "--official-live-smoke-json",
            str(smoke_path),
            "--fail-on-unresolved",
        ],
    )

    assert module.main() == 1
