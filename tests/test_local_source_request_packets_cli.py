from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "local-source-request-packets.py"


def test_local_source_request_packets_cli_emits_json() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--format", "json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert [packet["county"] for packet in payload[:6]] == [
        "連江縣",
        "金門縣",
        "花蓮縣",
        "臺北市",
        "臺東縣",
        "苗栗縣",
    ]
    assert {packet["county"] for packet in payload} >= {
        "苗栗縣",
        "屏東縣",
        "嘉義市",
    }
    assert payload[0]["packet_type"] == "metadata_release_request"
    assert payload[0]["target_signal_types"] == ["hydrologic_observation"]
    chiayi_city = next(packet for packet in payload if packet["county"] == "嘉義市")
    assert chiayi_city["packet_type"] == "signal_gap_request"
    assert chiayi_city["target_signal_types"] == [
        "flood_depth",
        "sewer_water_level",
        "pump_or_gate_status",
    ]
    yunlin = next(packet for packet in payload if packet["county"] == "雲林縣")
    assert yunlin["packet_type"] == "signal_gap_request"
    assert yunlin["status_only_source_names"] == ["雲林 iflood 淹水感測狀態"]
    assert yunlin["target_signal_types"] == ["flood_depth"]


def test_local_source_request_packets_cli_writes_markdown_output(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "request-packets.md"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--format",
            "markdown",
            "--output",
            str(output_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert str(output_path) in result.stderr
    markdown = output_path.read_text(encoding="utf-8")
    assert "## 花蓮縣：花蓮縣 Senslink/行動水情 即時水情 read API 授權請求" in markdown
    assert "## 金門縣：金門縣 KWIS 即時水情 read API 授權請求" in markdown
    assert "## 連江縣：連江縣即時水文觀測資料釋出請求" in markdown
    assert "## 屏東縣：屏東縣地方即時水情 read API contract 請求" in markdown
    assert "## 嘉義市：嘉義市缺漏水資訊訊號補齊請求" in markdown
    assert "## 雲林縣：雲林縣缺漏水資訊訊號補齊請求" in markdown
    assert "- 待補水資訊訊號：flood_depth、sewer_water_level、pump_or_gate_status" in markdown
    assert "- 既有 status-only 來源：雲林 iflood 淹水感測狀態" in markdown
