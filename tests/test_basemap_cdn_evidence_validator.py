from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = REPO_ROOT / "infra" / "scripts" / "validate_basemap_cdn_evidence.py"
EXAMPLE_PATH = REPO_ROOT / "docs" / "runbooks" / "basemap-cdn-evidence.example.yaml"


def _load_validator_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "validate_basemap_cdn_evidence",
        VALIDATOR_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_example() -> dict[str, Any]:
    with EXAMPLE_PATH.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _errors_for(evidence: dict[str, Any]) -> list[str]:
    validator = _load_validator_module()
    errors: list[str] = []
    validator.validate_evidence(evidence, errors)
    return errors


def _production_errors_for(evidence: dict[str, Any]) -> list[str]:
    validator = _load_validator_module()
    errors: list[str] = []
    validator.validate_evidence(evidence, errors, require_production_complete=True)
    return errors


def test_example_evidence_template_is_valid() -> None:
    validator = _load_validator_module()

    assert validator.validate_evidence_file(EXAMPLE_PATH) == []


def test_production_complete_evidence_is_valid() -> None:
    evidence = _production_complete_evidence()

    assert _errors_for(evidence) == []
    assert _production_errors_for(evidence) == []


def test_production_complete_rejects_missing_range_206() -> None:
    evidence = _production_complete_evidence()
    evidence["range_request"]["status"] = 200
    evidence["range_request"]["content_range"] = ""

    errors = _errors_for(evidence)

    assert "range_request.status must be 206 when production_complete is true" in errors
    assert "range_request.content_range is required" in errors


def test_production_complete_rejects_runbook_only_browser_evidence() -> None:
    evidence = _production_complete_evidence()
    evidence["desktop_screenshot_ref"] = "docs/runbooks/open-basemap-pmtiles.md#browser-smoke"

    errors = _errors_for(evidence)

    assert (
        "desktop_screenshot_ref must reference production evidence, "
        "not only runbook instructions"
    ) in errors


def test_production_complete_requires_range_probe_evidence_ref() -> None:
    evidence = _production_complete_evidence()
    evidence["range_request"].pop("evidence_ref")

    errors = _errors_for(evidence)

    assert "range_request.evidence_ref is required" in errors


def test_production_complete_rejects_public_osm_request_log() -> None:
    evidence = _production_complete_evidence()
    evidence["no_public_osm_tile_request"]["production_request_log"] = [
        "https://tile.openstreetmap.org/12/3456/1789.png",
    ]

    errors = _errors_for(evidence)

    assert (
        "no_public_osm_tile_request production request log must not include "
        "tile.openstreetmap.org"
    ) in errors


def test_production_complete_rejects_placeholder_owner() -> None:
    evidence = _production_complete_evidence()
    evidence["provider"]["owner"] = "basemap-owner"

    errors = _errors_for(evidence)

    assert (
        "provider.owner must name a real production owner, not a template placeholder"
    ) in errors


def _production_complete_evidence() -> dict[str, Any]:
    evidence = copy.deepcopy(_load_example())
    evidence["production_complete"] = True
    evidence["demo_mode"] = False
    evidence["style_url"] = "https://cdn.flood-risk.tw/basemaps/taiwan/2026-05-04/style.json"
    evidence["style_url_source"] = "R2 custom-domain CDN release manifest FR-MAP-2026-05-04"
    evidence["pmtiles_url"] = (
        "https://cdn.flood-risk.tw/basemaps/taiwan/2026-05-04/taiwan.pmtiles"
    )
    evidence["pmtiles_url_source"] = "R2 custom-domain CDN object basemaps/taiwan/2026-05-04"
    evidence["attribution"] = (
        '<a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> '
        "contributors; provider attribution reviewed for FR-MAP-2026-05-04"
    )

    evidence["provider"] = {
        "name": "Flood Risk self-hosted Protomaps-derived Taiwan extract",
        "owner": "maps-data-lead@flood-risk.internal",
        "evidence_ref": "private-ops://basemap/provider-review/FR-MAP-2026-05-04",
    }
    evidence["license"] = {
        "name": "ODbL and provider style asset review",
        "owner": "legal-reviewer@flood-risk.internal",
        "evidence_ref": "private-ops://basemap/license-review/FR-MAP-2026-05-04",
    }
    evidence["cadence"] = {
        "update_frequency": "monthly or emergency rebuild after accepted upstream issue",
        "owner": "maps-release-owner@flood-risk.internal",
        "last_reviewed_at": "2026-05-04T10:00:00+08:00",
        "evidence_ref": "private-ops://basemap/cadence-review/FR-MAP-2026-05-04",
    }
    evidence["range_request"] = {
        "method": "GET",
        "request_header": "Range: bytes=0-16383",
        "status": 206,
        "content_range": "bytes 0-16383/987654321",
        "accept_ranges": "bytes",
        "evidence_ref": "private-ops://basemap/probe/FR-MAP-2026-05-04.json",
    }
    evidence["cors"] = {
        "request_origin": "https://flood-risk.tw",
        "access_control_allow_origin": "https://flood-risk.tw",
        "validated": True,
        "evidence_ref": "private-ops://basemap/probe/FR-MAP-2026-05-04.json",
    }
    evidence["cache_control"] = {
        "header": "public, max-age=31536000, immutable",
        "validated": True,
        "evidence_ref": "private-ops://basemap/probe/FR-MAP-2026-05-04.json",
    }
    evidence["browser_network_log_ref"] = (
        "private-ops://basemap/browser-network/desktop-2026-05-04.har"
    )
    evidence["desktop_screenshot_ref"] = (
        "private-ops://basemap/screenshots/desktop-2026-05-04.png"
    )
    evidence["mobile_screenshot_ref"] = (
        "private-ops://basemap/screenshots/mobile-2026-05-04.png"
    )
    evidence["no_public_osm_tile_request"] = {
        "validated": True,
        "production_request_log_ref": (
            "private-ops://basemap/browser-network/desktop-2026-05-04.har"
        ),
        "observed_hosts": [
            "flood-risk.tw",
            "cdn.flood-risk.tw",
            "protomaps.github.io",
        ],
    }
    return evidence
