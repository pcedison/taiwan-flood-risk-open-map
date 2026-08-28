"""Fail-closed contracts for reviewed NCDR township alert geometry."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
IMPORTER_PATH = REPO_ROOT / "infra" / "scripts" / "import_ncdr_alert_area_boundaries.py"
MIGRATION_PATH = REPO_ROOT / "infra" / "migrations" / "0046_ncdr_alert_area_boundaries.sql"

_spec = importlib.util.spec_from_file_location("_ncdr_boundary_importer", IMPORTER_PATH)
assert _spec is not None and _spec.loader is not None
importer = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = importer
_spec.loader.exec_module(importer)


def test_official_archive_and_profile_are_pinned() -> None:
    assert importer.EXPECTED_TOWN_COUNT == 368
    assert importer.GEOCODE_PROFILE == "Taiwan_Geocode_103"
    assert importer.EXPECTED_ARCHIVE_SHA256 == (
        "26a0e1d3496847905a5d4956cf29369a932febba546bf165d9923085aa3ed9bb"
    )
    assert importer.SOURCE_URL == (
        "https://alerts.ncdr.nat.gov.tw/web/StaticFile/Document/"
        "town_103.shp(utf8).zip"
    )


def test_importer_rejects_unsafe_archive_members() -> None:
    with pytest.raises(SystemExit, match="unsafe member path"):
        importer._safe_member_name("../escape.shp")

    with pytest.raises(SystemExit, match="unsafe member path"):
        importer._safe_member_name("/absolute/escape.shp")


def test_geometry_write_binds_ewkb_through_postgis() -> None:
    source = IMPORTER_PATH.read_text(encoding="utf-8")

    assert "ST_GeomFromEWKB(%s)" in source
    assert "COPY ncdr_alert_area_boundaries" not in source
    assert "extractall" not in source


def test_migration_requires_one_reviewed_complete_368_row_snapshot() -> None:
    migration = MIGRATION_PATH.read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS ncdr_alert_area_boundary_snapshots" in migration
    assert "CREATE TABLE IF NOT EXISTS ncdr_alert_area_boundaries" in migration
    assert "CHECK (expected_count = 368)" in migration
    assert "archive_sha256 = approved_archive_sha256" in migration
    assert "manifest_sha256 = approved_manifest_sha256" in migration
    assert "WHERE is_active" in migration
    assert "reviewed NCDR alert boundaries are immutable" in migration


def test_runtime_image_contains_review_commands_and_pyshp() -> None:
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    api_project = (REPO_ROOT / "apps" / "api" / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )

    assert "import_ncdr_alert_area_boundaries.py" in dockerfile
    assert "activate_ncdr_alert_area_boundary_snapshot.py" in dockerfile
    assert '"pyshp>=2.3.1,<3"' in api_project
    assert "tests/test_ncdr_alert_area_boundary_contract.py" in workflow
