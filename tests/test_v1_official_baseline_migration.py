"""Data invariants the v1 jurisdiction source proof depends on.

``query_realtime_jurisdiction_context`` only emits a source mapping when its
owning signal contract carries a valid proof at the same revision. When either
half is missing, that signal's mappings must remain unavailable without
blocking independently reviewed signal revisions.

These assertions run against a database with every migration applied, so they
fail when the migrations stop producing the state the query demands.
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
import pytest

BASELINE_REVISION = "2026-08-24-v1-baseline"
WARNING_REVISION = "2026-08-28-v1-warning-alignment"
REVIEWED_SIGNAL_TYPES = ("rainfall", "water_level", "flood_depth", "flood_warning")
EXPECTED_FLOOD_WARNING_KEYS = {
    "official.cwa.heavy_rain_warning",
    "official.ncdr.cap",
}
EXPECTED_REVISIONS = {
    "rainfall": BASELINE_REVISION,
    "water_level": BASELINE_REVISION,
    "flood_depth": BASELINE_REVISION,
    "flood_warning": WARNING_REVISION,
}
REPO_ROOT = Path(__file__).resolve().parents[1]
WARNING_MIGRATION = (
    REPO_ROOT / "infra" / "migrations" / "0041_v1_warning_source_requirement_alignment.sql"
)

# Recomputed exactly as query_realtime_jurisdiction_context does, so a drift in
# either the ordering or the encoding shows up here rather than in production.
MANIFEST_SQL = """
    SELECT
        contract.jurisdiction_code,
        contract.signal_type,
        contract.catalog_status,
        contract.mapping_revision,
        contract.approved_mapping_count,
        contract.approved_mapping_manifest_sha256,
        contract.reviewed_at,
        contract.review_ref,
        count(mapping.adapter_key)::integer AS actual_count,
        encode(
            digest(
                convert_to(
                    COALESCE(
                        jsonb_agg(
                            jsonb_build_array(
                                mapping.adapter_key,
                                contract.signal_type,
                                mapping.coverage_scope,
                                mapping.jurisdiction_code,
                                mapping.requirement_role,
                                mapping.redundancy_of_adapter_key,
                                mapping.mapping_revision
                            )
                            ORDER BY
                                mapping.adapter_key,
                                mapping.coverage_scope,
                                mapping.jurisdiction_code,
                                mapping.requirement_role,
                                mapping.redundancy_of_adapter_key,
                                mapping.mapping_revision
                        ) FILTER (WHERE mapping.adapter_key IS NOT NULL),
                        '[]'::jsonb
                    )::text,
                    'UTF8'
                ),
                'sha256'
            ),
            'hex'
        ) AS actual_sha256,
        array_remove(array_agg(mapping.adapter_key), NULL) AS adapter_keys,
        COALESCE(
            jsonb_agg(
                jsonb_build_object(
                    'adapter_key', mapping.adapter_key,
                    'requirement_role', mapping.requirement_role,
                    'redundancy_of_adapter_key', mapping.redundancy_of_adapter_key,
                    'mapping_revision', mapping.mapping_revision
                )
                ORDER BY mapping.adapter_key
            ) FILTER (WHERE mapping.adapter_key IS NOT NULL),
            '[]'::jsonb
        ) AS mappings,
        COALESCE(
            bool_and(mapping.mapping_revision = contract.mapping_revision)
                FILTER (WHERE mapping.adapter_key IS NOT NULL),
            false
        ) AS mapping_revision_consistent,
        COALESCE(
            bool_and(
                CASE
                    WHEN mapping.requirement_role <> 'redundant_subset' THEN true
                    ELSE EXISTS (
                        SELECT 1
                        FROM realtime_source_jurisdictions parent_mapping
                        WHERE parent_mapping.adapter_key
                                = mapping.redundancy_of_adapter_key
                            AND parent_mapping.signal_type = mapping.signal_type
                            AND parent_mapping.requirement_role = 'required'
                            AND parent_mapping.mapping_revision = mapping.mapping_revision
                            AND (
                                parent_mapping.coverage_scope = 'national'
                                OR parent_mapping.jurisdiction_code
                                    = contract.jurisdiction_code
                            )
                    )
                END
            ) FILTER (WHERE mapping.adapter_key IS NOT NULL),
            false
        ) AS redundancy_valid,
        contract.mapping_manifest_version
    FROM realtime_jurisdiction_signal_contracts contract
    LEFT JOIN realtime_source_jurisdictions mapping
        ON mapping.signal_type = contract.signal_type
        AND mapping.mapping_revision = contract.mapping_revision
        AND (
            mapping.coverage_scope = 'national'
            OR mapping.jurisdiction_code = contract.jurisdiction_code
        )
    GROUP BY contract.jurisdiction_code, contract.signal_type,
        contract.mapping_manifest_version
"""


def _rows() -> list[dict]:
    database_url = os.getenv("MIGRATION_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("MIGRATION_TEST_DATABASE_URL is not configured")
    try:
        with psycopg.connect(database_url) as connection:
            with connection.cursor(row_factory=psycopg.rows.dict_row) as cursor:
                cursor.execute(MANIFEST_SQL)
                return cursor.fetchall()
    except (OSError, psycopg.Error) as exc:  # pragma: no cover - environment
        pytest.skip(f"migration test database is unreachable: {exc}")


def test_reviewed_signal_contracts_carry_a_valid_proof_at_the_query_revision() -> None:
    rows = _rows()
    reviewed = [row for row in rows if row["signal_type"] in REVIEWED_SIGNAL_TYPES]

    assert reviewed, "no reviewed signal contracts exist"
    for row in reviewed:
        where = f"{row['jurisdiction_code']}/{row['signal_type']}"
        assert row["catalog_status"] == "reviewed_complete", where
        assert row["mapping_revision"] == EXPECTED_REVISIONS[row["signal_type"]], where
        assert row["reviewed_at"] is not None, where
        assert row["review_ref"], where
        assert row["actual_count"] > 0, where
        assert row["approved_mapping_count"] == row["actual_count"], where
        assert row["approved_mapping_manifest_sha256"] == row["actual_sha256"], where


def test_every_jurisdiction_gets_both_reviewed_flood_warning_keys() -> None:
    # The plan requires this to fail closed rather than silently omit CAP.
    rows = [row for row in _rows() if row["signal_type"] == "flood_warning"]

    assert len(rows) == 22, f"expected 22 flood_warning contracts, got {len(rows)}"
    for row in rows:
        assert set(row["adapter_keys"]) == EXPECTED_FLOOD_WARNING_KEYS, (
            row["jurisdiction_code"]
        )
        mappings = {mapping["adapter_key"]: mapping for mapping in row["mappings"]}
        assert mappings["official.ncdr.cap"] == {
            "adapter_key": "official.ncdr.cap",
            "requirement_role": "required",
            "redundancy_of_adapter_key": None,
            "mapping_revision": WARNING_REVISION,
        }
        assert mappings["official.cwa.heavy_rain_warning"] == {
            "adapter_key": "official.cwa.heavy_rain_warning",
            "requirement_role": "redundant_subset",
            "redundancy_of_adapter_key": "official.ncdr.cap",
            "mapping_revision": WARNING_REVISION,
        }
        assert row["mapping_revision"] == WARNING_REVISION
        assert row["approved_mapping_count"] == 2
        assert row["approved_mapping_manifest_sha256"] == row["actual_sha256"]
        assert row["redundancy_valid"] is True


def test_warning_alignment_is_append_only_and_matches_the_deployed_backbone() -> None:
    migration = WARNING_MIGRATION.read_text(encoding="utf-8")
    entrypoint = (REPO_ROOT / "infra" / "docker" / "entrypoint.sh").read_text(
        encoding="utf-8"
    )

    assert WARNING_REVISION in migration
    assert "official.ncdr.cap" in migration
    assert "official.cwa.heavy_rain_warning" in migration
    assert "redundant_subset" in migration
    assert "UPDATE data_sources" not in migration
    assert "is_enabled =" not in migration
    backbone = entrypoint.split('realtime_backbone_adapter_keys="', 1)[1].split('"', 1)[0]
    assert "official.ncdr.cap" in backbone.split(",")
    assert "official.cwa.heavy_rain_warning" not in backbone.split(",")


def test_sewer_water_level_is_recorded_as_a_known_gap() -> None:
    rows = [row for row in _rows() if row["signal_type"] == "sewer_water_level"]

    assert rows, "no sewer_water_level contracts exist"
    for row in rows:
        assert row["catalog_status"] == "known_gap", row["jurisdiction_code"]
        assert row["approved_mapping_count"] is None, row["jurisdiction_code"]
        assert row["approved_mapping_manifest_sha256"] is None, row["jurisdiction_code"]


def test_the_mapping_proof_gate_actually_opens_for_every_reviewed_contract() -> None:
    # The eight conditions of `mapping_proof_valid` in
    # query_realtime_jurisdiction_context, evaluated against the migrated data.
    # Asserting the individual columns is not enough: this is the expression the
    # source_mappings subquery joins on, and it is the thing that was false in
    # production for every county in Taiwan.
    rows = [row for row in _rows() if row["signal_type"] in REVIEWED_SIGNAL_TYPES]

    assert rows
    for row in rows:
        proof_valid = (
            row["catalog_status"] == "reviewed_complete"
            and row["mapping_manifest_version"] == "jurisdiction-source-jsonb-v1"
            and row["reviewed_at"] is not None
            and row["review_ref"] is not None
            and row["actual_count"] > 0
            and row["actual_count"] == row["approved_mapping_count"]
            and row["actual_sha256"] == row["approved_mapping_manifest_sha256"]
            and row["mapping_revision_consistent"]
            and row["redundancy_valid"]
        )
        assert proof_valid, f"{row['jurisdiction_code']}/{row['signal_type']}"
