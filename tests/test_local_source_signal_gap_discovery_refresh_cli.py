from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


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
