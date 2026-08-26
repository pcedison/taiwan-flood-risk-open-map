from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI = REPO_ROOT / "scripts" / "official-incident-request-packets.py"
ARTIFACT = (
    REPO_ROOT
    / "docs"
    / "data-sources"
    / "official"
    / "official-incident-request-packets.md"
)
EXPECTED_PACKET_IDS = (
    "ncdr-citizen-disaster-report",
    "ncdr-edxl-sitrep",
    "kinmen-kwis-read-api",
    "hualien-senslink-read-api",
    "miaoli-drainage-read-api",
    "pingtung-pteoc-read-api",
    "taitung-water-read-api",
    "lienchiang-live-water-feed",
    "waze-for-cities-flood-incidents",
)
FORBIDDEN_FLAGS = (
    "--send",
    "--dispatch",
    "--login",
    "--api-key",
    "--evidence-ref",
    "--browser",
    "--webhook",
    "--mail",
)


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )


def test_json_output_lists_the_nine_manual_only_packets() -> None:
    result = _run("--format", "json")

    assert result.returncode == 0, result.stderr
    packets = json.loads(result.stdout)
    assert tuple(packet["packet_id"] for packet in packets) == EXPECTED_PACKET_IDS
    assert all(packet["submission_mode"] == "manual_only" for packet in packets)
    assert all(packet["contact_email"] is None for packet in packets)


def test_markdown_output_matches_the_checked_in_artifact() -> None:
    result = _run("--format", "markdown")

    assert result.returncode == 0, result.stderr
    assert result.stdout == ARTIFACT.read_text(encoding="utf-8")


def test_output_flag_writes_the_file(tmp_path: Path) -> None:
    destination = tmp_path / "nested" / "packets.md"

    result = _run("--format", "markdown", "--output", str(destination))

    assert result.returncode == 0, result.stderr
    assert destination.read_text(encoding="utf-8") == ARTIFACT.read_text(encoding="utf-8")
    assert result.stdout == ""


@pytest.mark.parametrize("flag", FORBIDDEN_FLAGS)
def test_cli_rejects_every_sending_flag(flag: str) -> None:
    result = _run(flag)

    assert result.returncode != 0
    assert flag not in CLI.read_text(encoding="utf-8")


def test_cli_source_imports_no_network_or_mail_client() -> None:
    source = CLI.read_text(encoding="utf-8")

    for module in ("requests", "httpx", "urllib.request", "smtplib", "selenium", "playwright"):
        assert f"import {module}" not in source, module
    assert "socket" not in source
