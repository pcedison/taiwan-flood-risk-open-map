from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = REPO_ROOT / "infra" / "migrations" / "0050_retention_cleanup_indexes.sql"
RETENTION = (
    REPO_ROOT
    / "apps"
    / "workers"
    / "app"
    / "jobs"
    / "evidence_retention.py"
)


def test_retention_queries_have_matching_bounded_indexes() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")
    retention = RETENTION.read_text(encoding="utf-8")

    assert "idx_evidence_official_retention_cutoff_event" in migration
    assert "event_type" in migration
    assert "COALESCE(observed_at, ingested_at, created_at)" in migration
    assert "WHERE source_type = 'official'" in migration
    assert "idx_raw_snapshots_retention_expires_at" in migration
    assert "ON raw_snapshots (retention_expires_at)" in migration
    assert "WHERE retention_expires_at IS NOT NULL" in migration
    assert "idx_staging_evidence_raw_snapshot_id" in migration
    assert "ON staging_evidence (raw_snapshot_id)" in migration

    assert "DELETE FROM evidence" in retention
    assert "event_type = ANY(%s::text[])" in retention
    assert "DELETE FROM raw_snapshots" in retention
    assert "ORDER BY retention_expires_at ASC" in retention
