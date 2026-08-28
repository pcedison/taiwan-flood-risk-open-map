from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    REPO_ROOT
    / "infra"
    / "migrations"
    / "0045_current_snapshot_staging_lookup_index.sql"
)
PROMOTION = REPO_ROOT / "apps" / "workers" / "app" / "pipelines" / "promotion.py"


def test_current_snapshot_promotion_has_a_matching_staging_index() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")
    promotion = PROMOTION.read_text(encoding="utf-8")

    assert "idx_staging_evidence_accepted_raw_snapshot_id" in migration
    assert "ON staging_evidence (raw_snapshot_id)" in migration
    assert "WHERE validation_status = 'accepted'" in migration
    assert "AND raw_snapshot_id IS NOT NULL" in migration
    assert "FROM raw_snapshots rs" in promotion
    assert "JOIN staging_evidence se ON se.raw_snapshot_id = rs.id" in promotion
