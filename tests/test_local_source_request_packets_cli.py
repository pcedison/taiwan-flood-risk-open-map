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
    assert [packet["county"] for packet in payload] == ["金門縣", "連江縣"]
    assert payload[0]["packet_type"] == "authorization_request"
    assert payload[1]["target_signal_types"] == ["hydrologic_observation"]


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
    assert "## 金門縣：金門縣 KWIS 即時水情 read API 授權請求" in markdown
    assert "## 連江縣：連江縣即時水文觀測資料釋出請求" in markdown
