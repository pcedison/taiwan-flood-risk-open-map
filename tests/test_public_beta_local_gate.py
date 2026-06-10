from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
GATE_SCRIPT = REPO_ROOT / "scripts" / "public-beta-local-gate.ps1"


def test_public_beta_local_gate_includes_roadmap_checks() -> None:
    script = GATE_SCRIPT.read_text(encoding="utf-8")

    required_snippets = [
        "[switch]$SkipDockerConfig",
        '"Docker compose config"',
        '"docker"',
        '"compose", "config", "--quiet"',
        '"API mypy"',
        '"-m", "mypy", "app", "--no-incremental"',
        '"infra\\scripts\\validate_source_allowlist.py"',
        '"infra\\scripts\\validate_openapi.py"',
        '"infra\\scripts\\validate_contract_fixtures.py"',
        '"infra\\scripts\\validate_migrations.py"',
        '"infra\\scripts\\validate_monitoring_assets.py"',
        '"infra\\scripts\\validate_production_readiness_evidence.py"',
        '"infra\\scripts\\validate_basemap_cdn_evidence.py"',
        '"infra\\scripts\\validate_public_reports_launch_evidence.py"',
        '"infra\\scripts\\validate_risk_calibration_manifest.py"',
        '"infra\\scripts\\validate_flood_potential_import.py"',
        '"npm"',
        '"audit"',
        '"run", "build"',
        '"scripts\\event_public_value_smoke.py"',
        '"no-network"',
        '"simulated-heavy-rain"',
    ]

    missing = [snippet for snippet in required_snippets if snippet not in script]

    assert missing == []


def test_public_beta_event_smoke_outputs_are_gitignored_artifacts() -> None:
    script = GATE_SCRIPT.read_text(encoding="utf-8")

    assert "Join-Path $TestResultsRoot" in script
    assert "--markdown-output" in script
    assert 'docs\\reviews' not in script
    assert "docs/reviews" not in script


def test_public_beta_gate_requires_explicit_skip_for_docker_config() -> None:
    script = GATE_SCRIPT.read_text(encoding="utf-8")

    assert "Skip = $SkipDockerConfig" in script
    assert "Skipped by flag." in script
