"""PostGIS acceptance for the nearby-candidate profile of the DB diagnostics.

The profile repeats the bounding-box pre-filter of the nearby-evidence branch
against the real schema, so the one thing a fake cursor cannot prove is that
its SQL still names the columns and indexes production has. This suite runs it
on the full migration set. It skips when ``EVIDENCE_TEST_DATABASE_URL`` is
absent and fails instead of skipping when ``OFFICIAL_DB_ACCEPTANCE_REQUIRED=1``.
"""

from __future__ import annotations

from collections.abc import Iterator
import os
from pathlib import Path
import sys
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest

from app.api.schemas import AdminDbDiagnosticsResponse
from app.ops import db_diagnostics

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from infra.scripts.apply_migrations import apply_migrations  # noqa: E402

# The profile searches SAMPLE_RADIUS_M around the sample point with the request
# path's bounding box, radius_m / 90000 degrees on each side. A blob in the
# far corner of that box overlaps it while its nearest edge is ~770 m from the
# sample point, so it is exactly the row the request reads only to discard.
BOX_HALF_WIDTH_DEG = db_diagnostics.SAMPLE_RADIUS_M / 90000.0
CORNER_LNG = db_diagnostics.SAMPLE_LNG - BOX_HALF_WIDTH_DEG
CORNER_LAT = db_diagnostics.SAMPLE_LAT - BOX_HALF_WIDTH_DEG
CORNER_BLOB_WKT = (
    "POLYGON(("
    f"{CORNER_LNG - 0.0009} {CORNER_LAT - 0.0009}, "
    f"{CORNER_LNG + 0.0002} {CORNER_LAT - 0.0009}, "
    f"{CORNER_LNG + 0.0002} {CORNER_LAT + 0.0002}, "
    f"{CORNER_LNG - 0.0009} {CORNER_LAT + 0.0002}, "
    f"{CORNER_LNG - 0.0009} {CORNER_LAT - 0.0009}"
    "))"
)
NEAR_POINT_WKT = (
    f"POINT({db_diagnostics.SAMPLE_LNG + 0.0005} {db_diagnostics.SAMPLE_LAT})"
)


def _database_url() -> str:
    database_url = os.getenv("EVIDENCE_TEST_DATABASE_URL")
    required = os.getenv("OFFICIAL_DB_ACCEPTANCE_REQUIRED") == "1"
    if not database_url:
        if required:
            pytest.fail(
                "EVIDENCE_TEST_DATABASE_URL is required when "
                "OFFICIAL_DB_ACCEPTANCE_REQUIRED=1"
            )
        pytest.skip("EVIDENCE_TEST_DATABASE_URL is not configured")
    try:
        with psycopg.connect(database_url) as connection:
            connection.execute("SELECT PostGIS_Version()")
    except (OSError, psycopg.Error) as exc:
        if required:
            pytest.fail(f"required PostGIS is unreachable: {exc}")
        pytest.skip(f"PostGIS is unreachable: {exc}")
    return database_url


@pytest.fixture(scope="module")
def migrated_schema_url() -> Iterator[str]:
    """A throwaway schema with the full migration set applied once."""

    database_url = _database_url()
    schema_name = f"db_diagnostics_{uuid4().hex}"
    with psycopg.connect(database_url, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
    connection_info = psycopg.conninfo.conninfo_to_dict(database_url)
    existing_options = connection_info.get("options", "")
    connection_info["options"] = (
        f"{existing_options} -c search_path={schema_name},public".strip()
    )
    isolated_url = psycopg.conninfo.make_conninfo(**connection_info)
    try:
        apply_migrations(database_url=isolated_url)
        yield isolated_url
    finally:
        with psycopg.connect(database_url, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name))
            )


@pytest.fixture
def seeded_url(migrated_schema_url: str) -> Iterator[str]:
    """Reset evidence, then insert one row per candidate outcome under test."""

    with psycopg.connect(migrated_schema_url) as connection:
        connection.execute("TRUNCATE evidence CASCADE")
        # The migrations seed the official adapters and other tables reference
        # them, so the sources are upserted rather than replaced.
        connection.execute(
            """
            INSERT INTO data_sources (name, adapter_key, source_type, metadata)
            VALUES
                ('Local flood reports', 'local.test.flood_report', 'official', '{}'),
                (
                    'WRA historical flood',
                    'official.wra.historical_flood',
                    'official',
                    '{"active_snapshot_raw_ref": "snapshot-2"}'
                ),
                ('CWA rainfall', 'official.cwa.rainfall', 'official', '{}')
            ON CONFLICT (adapter_key) DO UPDATE
                SET metadata = EXCLUDED.metadata, is_enabled = true
            """
        )
        connection.execute(
            """
            INSERT INTO evidence (
                data_source_id, source_id, source_type, event_type, title, summary,
                geom, confidence, raw_ref, ingestion_status, properties
            )
            SELECT
                ds.id, seed.source_id, 'official', seed.event_type, seed.title,
                'seed', ST_GeomFromText(seed.wkt, 4326), 0.9, seed.raw_ref,
                seed.ingestion_status, '{}'::jsonb
            FROM (VALUES
                -- Kept by the request: a point inside the radius.
                ('local.test.flood_report', 'near-point', 'flood_report',
                 'near point', %(point)s, 'near-1', 'accepted'),
                -- Fetched then discarded: overlaps the box, outside the radius.
                ('local.test.flood_report', 'corner-blob', 'flood_report',
                 'corner blob', %(blob)s, 'blob-1', 'accepted'),
                -- Fetched then discarded twice over: a superseded snapshot.
                ('official.wra.historical_flood', 'stale-snapshot', 'flood_report',
                 'stale snapshot', %(blob)s, 'snapshot-1', 'accepted'),
                -- Never a candidate: official rainfall has its own branch.
                ('official.cwa.rainfall', 'rain-station', 'rainfall',
                 'rain station', %(point)s, 'rain-1', 'accepted'),
                -- Never a candidate: rejected rows are outside the index.
                ('local.test.flood_report', 'rejected-point', 'flood_report',
                 'rejected point', %(point)s, 'rejected-1', 'rejected')
            ) AS seed(adapter_key, source_id, event_type, title, wkt, raw_ref,
                      ingestion_status)
            JOIN data_sources ds ON ds.adapter_key = seed.adapter_key
            """,
            {"point": NEAR_POINT_WKT, "blob": CORNER_BLOB_WKT},
        )
        connection.commit()
    yield migrated_schema_url


def test_profile_groups_the_bounding_box_candidates_by_outcome(
    seeded_url: str,
) -> None:
    section = db_diagnostics._nearby_candidate_profile(seeded_url, None)

    assert section["status"] == "ok", section
    assert section["error"] is None
    groups = {
        (
            group["adapter_key"],
            group["geometry_type"],
            group["within_radius"],
            group["active_snapshot"],
        ): group
        for group in section["groups"]
    }
    assert set(groups) == {
        ("local.test.flood_report", "POINT", True, True),
        ("local.test.flood_report", "POLYGON", False, True),
        ("official.wra.historical_flood", "POLYGON", False, False),
    }
    for group in groups.values():
        assert group["rows"] == 1
        assert group["event_type"] == "flood_report"
        assert group["geom_bytes"] > 0
        assert group["properties_bytes"] > 0
    assert groups[("local.test.flood_report", "POINT", True, True)]["max_npoints"] == 1
    assert groups[("local.test.flood_report", "POLYGON", False, True)]["max_npoints"] == 5
    # Heaviest group first, so a reader sees what costs the request most.
    weights = [group["geom_bytes"] + group["properties_bytes"] for group in section["groups"]]
    assert weights == sorted(weights, reverse=True)


def test_full_diagnostics_payload_satisfies_the_admin_contract(
    seeded_url: str,
) -> None:
    payload = db_diagnostics.collect_db_diagnostics(database_url=seeded_url)

    response = AdminDbDiagnosticsResponse.model_validate(payload)

    assert response.nearby_candidate_profile.status == "ok"
    assert len(response.nearby_candidate_profile.groups) == 3
    assert [plan.status for plan in response.query_plans] == ["ok", "ok", "ok"]
