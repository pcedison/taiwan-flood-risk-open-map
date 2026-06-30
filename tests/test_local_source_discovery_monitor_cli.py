from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "local-source-discovery-monitor.py"


def _load_script_module():
    preserved_app_modules = {
        name: module
        for name, module in sys.modules.items()
        if name == "app" or name.startswith("app.ops")
    }
    for name in preserved_app_modules:
        sys.modules.pop(name, None)

    spec = importlib.util.spec_from_file_location(
        "local_source_discovery_monitor_cli",
        SCRIPT,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        for name in tuple(sys.modules):
            if name == "app" or name.startswith("app.ops"):
                sys.modules.pop(name, None)
        sys.modules.update(preserved_app_modules)
    return module


def test_local_source_discovery_monitor_cli_writes_utf8_evidence_output(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script_module()
    evidence_output = tmp_path / "signal-gap-discovery.json"

    monkeypatch.setattr(
        module,
        "fetch_data_gov_dataset_export",
        lambda *, timeout_seconds: [
            {
                "\u8cc7\u6599\u96c6\u8b58\u5225\u78bc": "120801",
                "\u8cc7\u6599\u96c6\u540d\u7a31": (
                    "\u81fa\u4e2d\u5e02\u96e8\u6c34\u4e0b\u6c34\u9053"
                    "\u4eba\u5b54\u5716"
                ),
                "\u8cc7\u6599\u63d0\u4f9b\u5c6c\u6027": "\u6a94\u6848\u8cc7\u6599",
                "\u6a94\u6848\u683c\u5f0f": "CSV",
                "\u4e3b\u8981\u6b04\u4f4d\u8aaa\u660e": (
                    "\u8cc7\u6599\u96c6\u540d\u7a31;"
                    "\u8cc7\u6599\u683c\u5f0f;"
                    "\u4e0b\u8f09\u7db2\u5740;"
                    "\u4e0a\u67b6\u65e5\u671f;"
                    "\u8cc7\u6599\u8cc7\u6e90\u6b04\u4f4d"
                ),
            }
        ],
    )

    result = module.main(
        [
            "--county",
            "\u81fa\u4e2d\u5e02",
            "--signal-type",
            "sewer_water_level",
            "--captured-at",
            "2026-06-30T13:40:00+08:00",
            "--evidence-output",
            str(evidence_output),
        ]
    )

    assert result == 0
    raw = evidence_output.read_bytes()
    assert not raw.startswith(b"\xff\xfe")
    evidence = json.loads(raw.decode("utf-8"))
    assert evidence["schema_version"] == "local-source-discovery-refresh/v1"
    assert evidence["captured_at"] == "2026-06-30T13:40:00+08:00"
    assert evidence["source_catalog_url"] == (
        "https://data.gov.tw/api/front/dataset/export?format=json"
    )
    assert evidence["discovery"]["target_counties"] == ["\u81fa\u4e2d\u5e02"]
    assert evidence["discovery"]["required_signal_types"] == ["sewer_water_level"]
    assert evidence["discovery"]["candidate_count"] == 1
    assert evidence["discovery"]["summary"]["candidate_live_read_api_count_by_county"] == {}
    assert evidence["conclusion"] == "no_candidate_live_read_api_found"


def test_local_source_discovery_monitor_cli_marks_live_candidate_conclusion(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script_module()
    evidence_output = tmp_path / "live-candidate-discovery.json"

    monkeypatch.setattr(
        module,
        "fetch_data_gov_dataset_export",
        lambda *, timeout_seconds: [
            {
                "title": "\u91d1\u9580\u7e23\u5373\u6642\u6c34\u4f4d API",
                "description": "\u91d1\u9580\u6c34\u4f4d\u7ad9\u5373\u6642 API",
                "identifier": "kinmen-live-water-level",
                "distribution": [{"format": "JSON"}],
            }
        ],
    )

    result = module.main(
        [
            "--county",
            "\u91d1\u9580\u7e23",
            "--captured-at",
            "2026-06-30T13:45:00+08:00",
            "--evidence-output",
            str(evidence_output),
        ]
    )

    assert result == 0
    evidence = json.loads(evidence_output.read_text(encoding="utf-8"))
    assert evidence["conclusion"] == "candidate_live_read_api_found"
    assert evidence["discovery"]["summary"]["candidate_live_read_api_count_by_county"] == {
        "\u91d1\u9580\u7e23": 1
    }
