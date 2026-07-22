from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "public-api-contract-probe.py"


def test_public_api_contract_probe_cli_writes_fixture_backed_artifact(
    tmp_path: Path,
) -> None:
    fixture_path = tmp_path / "responses.json"
    output_path = tmp_path / "probe.json"
    fixture_path.write_text(
        json.dumps(
            {
                "default": {
                    "status_code": 200,
                    "content_type": "text/html",
                    "text": "<html><body>成果頁，含雨量文字。</body></html>",
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--captured-at",
            "2026-06-30T18:50:00+08:00",
            "--timeout-seconds",
            "2",
            "--allow-insecure-tls",
            "--fixture-response-json",
            str(fixture_path),
            "--output",
            str(output_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert str(output_path) in result.stderr
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "public-api-contract-probe/v1"
    assert payload["captured_at"] == "2026-06-30T18:50:00+08:00"
    assert payload["summary"]["public_api_contract_review_count"] == 3
    assert payload["summary"]["candidate_live_read_api_count"] == 0


def test_public_api_contract_probe_cli_can_fail_when_live_candidate_found(
    tmp_path: Path,
) -> None:
    fixture_path = tmp_path / "responses.json"
    fixture_path.write_text(
        json.dumps(
            {
                "default": {
                    "status_code": 200,
                    "content_type": "application/json",
                    "text": (
                        '{"station_id":"A1","observed_at":"2026-06-30T18:00:00+08:00",'
                        '"measurement_value":1,"measurement_unit":"m",'
                        '"longitude":120,"latitude":22,"license":"ODGL"}'
                    ),
                }
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--fixture-response-json",
            str(fixture_path),
            "--fail-on-live-candidate",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "candidate_live_read_api_found" in result.stderr
