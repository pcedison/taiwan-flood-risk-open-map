from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    REPO_ROOT
    / "infra"
    / "migrations"
    / "0049_cap_warning_lifecycle_indexes.sql"
)
PROMOTION = REPO_ROOT / "apps" / "workers" / "app" / "pipelines" / "promotion.py"


def test_cap_lifecycle_queries_have_matching_partial_indexes() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")
    promotion = PROMOTION.read_text(encoding="utf-8")

    assert "idx_evidence_current_actual_cap_identity" in migration
    assert "(properties ->> 'cap_sender')" in migration
    assert "(properties ->> 'cap_identifier')" in migration
    assert "(properties ->> 'admin_code')" in migration
    assert "idx_evidence_current_actual_cap_message_type" in migration
    assert "(properties ->> 'cap_message_type')" in migration
    assert "source_type = 'official'" in migration
    assert "event_type = 'flood_warning'" in migration
    assert "properties ->> 'evidence_scope' = 'current'" in migration
    assert "properties ->> 'cap_status' = 'Actual'" in migration

    assert "/* canonical-cap-idempotence */" in promotion
    assert "/* retained-cap-tombstone */" in promotion
    assert "cap_evidence.properties ->> 'cap_sender'" in promotion
    assert "cap_evidence.properties ->> 'cap_identifier'" in promotion
    assert "lifecycle_evidence.properties ->> 'cap_message_type'" in promotion
