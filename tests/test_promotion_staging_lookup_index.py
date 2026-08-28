from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = REPO_ROOT / "infra" / "migrations" / "0042_evidence_staging_lookup_index.sql"
PROMOTION = REPO_ROOT / "apps" / "workers" / "app" / "pipelines" / "promotion.py"
HEALTH = REPO_ROOT / "apps" / "api" / "app" / "api" / "routes" / "health.py"


def test_latest_schema_indexes_the_per_candidate_staging_lookup() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")
    promotion = PROMOTION.read_text(encoding="utf-8")
    health = HEALTH.read_text(encoding="utf-8")

    assert "CREATE INDEX IF NOT EXISTS idx_evidence_staging_evidence_id" in migration
    assert "((properties ->> 'staging_evidence_id'))" in migration
    assert "WHERE properties ? 'staging_evidence_id'" in migration
    assert "properties ? 'staging_evidence_id'" in promotion
    assert 'REQUIRED_SCHEMA_VERSION = 42' in health
    assert 'REQUIRED_SCHEMA_FILENAME = "0042_evidence_staging_lookup_index.sql"' in health
