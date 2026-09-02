from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "infra"
    / "migrations"
    / "0061_staging_snapshot_idempotency.sql"
)


def test_staging_snapshot_idempotency_keeps_promoted_provenance_before_dedup() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "promoted.properties->>'staging_evidence_id'" in sql
    assert "ranked.duplicate_rank > 1" in sql
    assert "uq_staging_evidence_snapshot_evidence_id" in sql
    assert "raw_snapshot_id" in sql
    assert "payload->>'evidence_id'" in sql
