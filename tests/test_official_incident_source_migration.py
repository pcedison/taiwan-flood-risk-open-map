from __future__ import annotations

import re
from pathlib import Path

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "infra"
    / "migrations"
    / "0038_official_incident_context_sources.sql"
)
EXPECTED_KEYS = {
    "official.cwa.heavy_rain_warning",
    "official.ncdr.cap",
    "official.npa.police_radio_traffic",
    "official.wra.flood_warning",
}
CONTEXT_ONLY_KEYS = {
    "official.npa.police_radio_traffic",
    "official.wra.flood_warning",
}
SPATIAL_REVIEW_KEYS = {
    "official.cwa.heavy_rain_warning",
    "official.ncdr.cap",
}


def _migration() -> str:
    return MIGRATION_PATH.read_text(encoding="utf-8")


def test_migration_registers_each_expected_adapter_key_exactly_once() -> None:
    migration = _migration()

    for key in EXPECTED_KEYS:
        assert migration.count(f"'{key}'") == 1, key

    quoted_keys = set(re.findall(r"'(official\.[a-z0-9_.]+)'", migration))
    assert quoted_keys == EXPECTED_KEYS


def test_migration_uses_one_idempotent_insert_that_forces_disabled() -> None:
    migration = _migration()

    assert migration.count("INSERT INTO data_sources") == 1
    assert "ON CONFLICT (adapter_key) DO UPDATE SET" in migration
    assert "is_enabled = EXCLUDED.is_enabled" in migration
    assert migration.count("false") == len(EXPECTED_KEYS)
    assert "true" not in migration


def test_every_row_is_official_and_unknown_health() -> None:
    migration = _migration()

    assert migration.count("'official',") == len(EXPECTED_KEYS)
    assert migration.count("'unknown',") == len(EXPECTED_KEYS)


def test_migration_stores_no_credential_value() -> None:
    migration = _migration().lower()

    for forbidden in (
        "authorization",
        "api_key",
        "apikey",
        "authorizationcode",
        "token",
        "secret",
        "password",
        "bearer",
        "cwa-",
    ):
        assert forbidden not in migration, forbidden


def test_context_rows_are_marked_context_only_and_never_scoring() -> None:
    migration = _migration()

    for key in CONTEXT_ONLY_KEYS:
        row = _row_for(migration, key)
        assert "'evidence_scope', 'context'" in row, key
        assert "'scoring_use', 'never'" in row, key


def test_cwa_and_ncdr_rows_declare_unapproved_spatial_review() -> None:
    migration = _migration()

    for key in SPATIAL_REVIEW_KEYS:
        row = _row_for(migration, key)
        assert "'spatial_review', 'unapproved'" in row, key


def test_migration_never_inserts_a_required_realtime_coverage_mapping() -> None:
    migration = _migration()

    assert "realtime_source_jurisdictions" not in migration
    assert "requirement_role" not in migration
    assert "official_realtime_latest" not in migration


def test_every_row_carries_public_safe_provenance_metadata() -> None:
    migration = _migration()

    for key in EXPECTED_KEYS:
        row = _row_for(migration, key)
        for field in (
            "'owner_authority'",
            "'source_url'",
            "'resource_url'",
            "'license_name'",
            "'limitation_zh'",
            "'review_status'",
            "'phase'",
        ):
            assert field in row, (key, field)
        assert "https://" in row, key


def _row_for(migration: str, adapter_key: str) -> str:
    start = migration.index(f"'{adapter_key}'")
    end = migration.find("\n    ),", start)
    if end == -1:
        end = migration.index("ON CONFLICT", start)
    return migration[start:end]
