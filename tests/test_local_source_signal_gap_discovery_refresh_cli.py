from __future__ import annotations

import json
import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "local-source-signal-gap-discovery-refresh.py"


def test_local_source_signal_gap_discovery_refresh_writes_group_artifacts(
    tmp_path: Path,
) -> None:
    dataset_export = tmp_path / "data-gov-export.json"
    output_dir = tmp_path / "artifacts"
    dataset_export.write_text(
        json.dumps(
            [
                {
                    "title": "金門縣即時抽水站 API",
                    "identifier": "kinmen-pump-live",
                    "fieldDescription": (
                        "observed_at; station_or_device_id; measurement_value; "
                        "longitude; latitude; pump_status"
                    ),
                    "format": "JSON",
                    "downloadURL": "https://example.test/kinmen/pump.json",
                    "accrualPeriodicity": "每5分鐘",
                    "data_provision_type": "API",
                },
                {
                    "title": "臺北市降雨淹水模擬圖",
                    "identifier": "taipei-flood-depth-metadata",
                    "fieldDescription": "GRIDCODE;depth;case;year;AGENCYCODE",
                    "format": "KML",
                    "downloadURL": "https://example.test/taipei/flood-depth.kml",
                    "accrualPeriodicity": "每5年",
                    "data_provision_type": "檔案資料",
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--dataset-export-json",
            str(dataset_export),
            "--captured-at",
            "2026-07-01T11:15:00+08:00",
            "--output-dir",
            str(output_dir),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)

    assert summary["schema_version"] == "local-source-signal-gap-discovery-refresh/v1"
    assert summary["captured_at"] == "2026-07-01T11:15:00+08:00"
    assert [group["signal_type"] for group in summary["groups"]] == [
        "pump_or_gate_status",
        "flood_depth",
        "sewer_water_level",
    ]
    assert summary["signal_gap_group_count"] == 3
    assert summary["total_candidate_live_read_api_count"] == 1
    assert summary["total_metadata_only_count"] == 1
    assert summary["live_candidate_signal_types"] == ["pump_or_gate_status"]

    files = sorted(path.name for path in output_dir.iterdir())
    assert files == [
        "signal-gap-discovery-refresh-flood-depth.json",
        "signal-gap-discovery-refresh-pump-or-gate-status.json",
        "signal-gap-discovery-refresh-sewer-water-level.json",
        "signal-gap-discovery-refresh-summary.json",
    ]

    pump = json.loads(
        (output_dir / "signal-gap-discovery-refresh-pump-or-gate-status.json").read_text(
            encoding="utf-8"
        )
    )
    assert pump["schema_version"] == "local-source-discovery-refresh/v1"
    assert pump["conclusion"] == "candidate_live_read_api_found"
    assert pump["discovery"]["summary"]["candidate_live_read_api_count_by_county"] == {
        "金門縣": 1
    }

    sewer = json.loads(
        (output_dir / "signal-gap-discovery-refresh-sewer-water-level.json").read_text(
            encoding="utf-8"
        )
    )
    assert sewer["conclusion"] == "no_candidate_live_read_api_found"
    assert sewer["discovery"]["candidate_count"] == 0


def test_local_source_signal_gap_discovery_refresh_can_fail_on_live_candidate(
    tmp_path: Path,
) -> None:
    dataset_export = tmp_path / "data-gov-export.json"
    dataset_export.write_text(
        json.dumps(
            [
                {
                    "title": "金門縣即時抽水站 API",
                    "identifier": "kinmen-pump-live",
                    "fieldDescription": (
                        "observed_at; station_or_device_id; measurement_value; "
                        "longitude; latitude; pump_status"
                    ),
                    "format": "JSON",
                    "downloadURL": "https://example.test/kinmen/pump.json",
                    "accrualPeriodicity": "每5分鐘",
                    "data_provision_type": "API",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--dataset-export-json",
            str(dataset_export),
            "--captured-at",
            "2026-07-01T11:15:00+08:00",
            "--fail-on-live-candidate",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )

    assert result.returncode == 1
    summary = json.loads(result.stdout)
    assert summary["total_candidate_live_read_api_count"] == 1


def test_local_source_signal_gap_discovery_refresh_can_degrade_on_live_fetch_failure(
    tmp_path: Path,
    capsys: Any,
    monkeypatch: Any,
) -> None:
    module = _load_script_module()
    output_dir = tmp_path / "artifacts"
    monkeypatch.setattr(module, "_load_worker_discovery_module", lambda: _FailingDiscovery())

    result = module.main(
        [
            "--allow-fetch-failure",
            "--captured-at",
            "2026-07-01T19:40:00+08:00",
            "--output-dir",
            str(output_dir),
        ]
    )

    assert result == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["source_catalog_fetch_status"] == "failed"
    assert "timed out" in summary["source_catalog_fetch_error"]
    assert summary["total_candidate_live_read_api_count"] == 0
    assert summary["signal_gap_group_count"] == 3

    pump = json.loads(
        (output_dir / "signal-gap-discovery-refresh-pump-or-gate-status.json").read_text(
            encoding="utf-8"
        )
    )
    assert pump["conclusion"] == "source_catalog_fetch_failed"
    assert pump["source_catalog_fetch_status"] == "failed"


def _load_script_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "local_source_signal_gap_discovery_refresh_under_test",
        SCRIPT,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FailingDiscovery:
    DATA_GOV_DATASET_EXPORT_URL = "https://data.gov.tw/api/front/dataset/export?format=json"

    @staticmethod
    def fetch_data_gov_dataset_export(**_kwargs: Any) -> object:
        raise RuntimeError("Failed to fetch data.gov.tw dataset export: timed out")

    @staticmethod
    def discover_local_source_candidates(
        payload: object,
        *,
        target_counties: list[str],
        required_signal_types: tuple[str, ...],
    ) -> "_EmptyDiscoveryResult":
        assert payload == []
        assert required_signal_types
        return _EmptyDiscoveryResult(target_counties)


class _EmptyDiscoveryResult:
    def __init__(self, target_counties: list[str]) -> None:
        self._target_counties = target_counties

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_count": 0,
            "candidates": [],
            "summary": {
                "by_county": {
                    county: {"readiness_state": "no_candidate"}
                    for county in self._target_counties
                },
                "target_counties_without_candidates": self._target_counties,
            },
        }
