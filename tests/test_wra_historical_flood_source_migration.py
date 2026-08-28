from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    REPO_ROOT
    / "infra"
    / "migrations"
    / "0047_wra_historical_flood_source.sql"
)


def test_historical_flood_source_migration_registers_and_enables_reviewed_source() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "'official.wra.historical_flood'" in sql
    assert "'Government Open Data License, version 1.0'" in sql
    assert "'snapshot_generation_mode', 'complete_replace'" in sql
    assert "'evidence_scope', 'historical'" in sql
    assert "metadata = data_sources.metadata || EXCLUDED.metadata" in sql
    assert "is_enabled = EXCLUDED.is_enabled" in sql


def test_historical_flood_source_migration_repairs_pre_fix_orphans_and_snapshot() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "orphan.data_source_id IS NULL" in sql
    assert "orphan.properties->>'adapter_key' = source.adapter_key" in sql
    assert "'{active_snapshot_raw_ref}'" in sql
    assert "ORDER BY max(evidence.ingested_at) DESC, evidence.raw_ref DESC" in sql
    assert "rejection_reason = 'idempotent_existing_evidence'" in sql
    assert "promoted.raw_ref IS NOT DISTINCT FROM snapshot.raw_ref" in sql
