from __future__ import annotations

import argparse
from contextlib import contextmanager
from decimal import Decimal
import json
import os
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
from typing import Any, Iterator

import psycopg

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from infra.scripts.apply_migrations import apply_migrations  # noqa: E402


MIGRATIONS_DIR = REPO_ROOT / "infra" / "migrations"
EXPECTED_PRE_UPGRADE_VERSION = 32
EXPECTED_POST_UPGRADE_VERSION = 36
EXPECTED_JURISDICTION_COUNT = 22
EXPECTED_SIGNAL_CONTRACT_COUNT = 88
EXPECTED_SOURCE_MAPPING_COUNT = 46

QUERY_ID = "10000000-0000-0000-0000-000000000001"
ASSESSMENT_ID = "20000000-0000-0000-0000-000000000001"
RUNTIME_JOB_ID = "30000000-0000-0000-0000-000000000001"
GAP_QUERY_ID = "10000000-0000-0000-0000-000000000002"
GAP_ASSESSMENT_ID = "20000000-0000-0000-0000-000000000002"
GAP_RUNTIME_JOB_ID = "30000000-0000-0000-0000-000000000002"
POST_FENCE_QUERY_ID = "10000000-0000-0000-0000-000000000003"
POST_FENCE_ASSESSMENT_ID = "20000000-0000-0000-0000-000000000003"
POST_FENCE_RUNTIME_JOB_ID = "30000000-0000-0000-0000-000000000003"
PRECISE_LAT = Decimal("25.047812")
PRECISE_LNG = Decimal("121.531234")
SCRUBBED_LAT = Decimal("25.05")
SCRUBBED_LNG = Decimal("121.53")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify a populated production-style migration upgrade from 0032 to 0036."
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("MIGRATION_UPGRADE_TEST_DATABASE_URL"),
        help=(
            "Connection URL for an empty, isolated test database. Defaults to "
            "MIGRATION_UPGRADE_TEST_DATABASE_URL. The URL is never printed."
        ),
    )
    args = parser.parse_args(argv)
    if not args.database_url:
        parser.error(
            "--database-url or MIGRATION_UPGRADE_TEST_DATABASE_URL is required"
        )

    _require_empty_database(args.database_url)
    with _migration_manifests() as manifests:
        through_0032, through_0035, through_0036 = manifests
        first = apply_migrations(
            database_url=args.database_url,
            migrations_dir=through_0032,
        )
        _expect_equal("migrations applied through 0032", len(first.applied), 32)
        _expect_equal("migrations skipped through 0032", len(first.skipped), 0)
        _verify_schema_manifest(args.database_url, expected_version=32)

        _seed_populated_0032_database(args.database_url)

        second = apply_migrations(
            database_url=args.database_url,
            migrations_dir=through_0035,
        )
        _expect_equal(
            "migrations applied during upgrade",
            second.applied,
            (
                "0033_location_queries_privacy.sql",
                "0034_public_realtime_source_health.sql",
                "0035_station_inventory_and_jurisdiction_proofs.sql",
            ),
        )
        _expect_equal("migrations skipped during upgrade", len(second.skipped), 32)

        _verify_schema_manifest(args.database_url, expected_version=35)
        _verify_privacy_scrub(args.database_url)
        _verify_inventory_schema_and_fail_closed_seed(args.database_url)

        # Simulate an old container writing after 0033 committed but before the
        # database fence is installed. Migration 0036 must repair these rows.
        _insert_precise_privacy_fixture(
            args.database_url,
            query_id=GAP_QUERY_ID,
            assessment_id=GAP_ASSESSMENT_ID,
            runtime_job_id=GAP_RUNTIME_JOB_ID,
            marker="gap",
        )

        third = apply_migrations(
            database_url=args.database_url,
            migrations_dir=through_0036,
        )
        _expect_equal(
            "privacy fence migration applied",
            third.applied,
            ("0036_database_privacy_fence.sql",),
        )
        _expect_equal("migrations skipped before privacy fence", len(third.skipped), 35)

    _verify_schema_manifest(args.database_url, expected_version=36)
    _verify_privacy_scrub(args.database_url)
    _verify_fenced_privacy_fixture(
        args.database_url,
        query_id=GAP_QUERY_ID,
        assessment_id=GAP_ASSESSMENT_ID,
        runtime_job_id=GAP_RUNTIME_JOB_ID,
        marker="gap",
    )
    _reapply_privacy_fence(args.database_url)

    # Old INSERT and UPDATE shapes must be scrubbed by the database itself
    # after 0036, even if the rolling deployment still has an old app process.
    _insert_precise_privacy_fixture(
        args.database_url,
        query_id=POST_FENCE_QUERY_ID,
        assessment_id=POST_FENCE_ASSESSMENT_ID,
        runtime_job_id=POST_FENCE_RUNTIME_JOB_ID,
        marker="post-insert",
    )
    _update_with_precise_privacy_fixture(args.database_url, marker="post-update")
    _verify_fenced_privacy_fixture(
        args.database_url,
        query_id=POST_FENCE_QUERY_ID,
        assessment_id=POST_FENCE_ASSESSMENT_ID,
        runtime_job_id=POST_FENCE_RUNTIME_JOB_ID,
        marker="post-insert",
    )
    _verify_fenced_privacy_fixture(
        args.database_url,
        query_id=QUERY_ID,
        assessment_id=ASSESSMENT_ID,
        runtime_job_id=RUNTIME_JOB_ID,
        marker="post-update",
    )
    _verify_inventory_schema_and_fail_closed_seed(args.database_url)
    print(
        "Populated migration upgrade verified: "
        "0032->0036, gap repair, database privacy fences, indexes, seed counts, "
        "and fail-closed defaults."
    )
    return 0


def _require_empty_database(database_url: str) -> None:
    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT count(*)
                FROM pg_catalog.pg_class relation
                JOIN pg_catalog.pg_namespace namespace
                    ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'public'
                    AND relation.relkind IN ('r', 'p')
                """
            )
            row = cursor.fetchone()
    table_count = int(row[0]) if row is not None else -1
    if table_count != 0:
        raise RuntimeError(
            "Migration upgrade verification requires an empty isolated database"
        )


def _reapply_privacy_fence(database_url: str) -> None:
    migration_sql = (MIGRATIONS_DIR / "0036_database_privacy_fence.sql").read_text(
        encoding="utf-8"
    )
    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(migration_sql)


@contextmanager
def _migration_manifests() -> Iterator[tuple[Path, Path, Path]]:
    migration_paths = sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql"))
    versions = tuple(int(path.name[:4]) for path in migration_paths)
    _expect_equal(
        "checked-in migration versions",
        versions,
        tuple(range(1, EXPECTED_POST_UPGRADE_VERSION + 1)),
    )
    with TemporaryDirectory(prefix="flood-risk-migration-upgrade-") as temporary:
        temporary_path = Path(temporary)
        through_0032 = temporary_path / "through-0032"
        through_0035 = temporary_path / "through-0035"
        through_0036 = temporary_path / "through-0036"
        through_0032.mkdir()
        through_0035.mkdir()
        through_0036.mkdir()
        for migration in migration_paths:
            shutil.copy2(migration, through_0036 / migration.name)
            if int(migration.name[:4]) <= 35:
                shutil.copy2(migration, through_0035 / migration.name)
            if int(migration.name[:4]) <= EXPECTED_PRE_UPGRADE_VERSION:
                shutil.copy2(migration, through_0032 / migration.name)
        yield through_0032, through_0035, through_0036


def _verify_schema_manifest(database_url: str, *, expected_version: int) -> None:
    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT version, filename FROM schema_migrations ORDER BY version"
            )
            rows = cursor.fetchall()
    versions = tuple(int(row[0]) for row in rows)
    _expect_equal(
        f"recorded schema versions through {expected_version:04d}",
        versions,
        tuple(range(1, expected_version + 1)),
    )
    expected_filename = {
        32: "0032_cwa_tide_level_source.sql",
        35: "0035_station_inventory_and_jurisdiction_proofs.sql",
        36: "0036_database_privacy_fence.sql",
    }[expected_version]
    _expect_equal(
        "latest recorded migration filename",
        str(rows[-1][1]),
        expected_filename,
    )


def _seed_populated_0032_database(database_url: str) -> None:
    risk_snapshot = """
        {
          "location_text": "precise test address",
          "location": {
            "lat": 25.047812,
            "lng": 121.531234,
            "precision": "rooftop"
          },
          "keep": "assessment-marker"
        }
    """
    runtime_payload = """
        {
          "location_text": "precise queued address",
          "lat": 25.047812,
          "lng": 121.531234,
          "keep": "runtime-marker"
        }
    """
    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO location_queries (
                    id,
                    input_type,
                    raw_input,
                    geom,
                    radius_m,
                    lat,
                    lng,
                    metadata
                )
                VALUES (
                    %s::uuid,
                    'address',
                    'precise test address',
                    ST_SetSRID(ST_MakePoint(%s, %s), 4326),
                    500,
                    %s,
                    %s,
                    '{"keep":"query-marker"}'::jsonb
                )
                """,
                (QUERY_ID, PRECISE_LNG, PRECISE_LAT, PRECISE_LAT, PRECISE_LNG),
            )
            cursor.execute(
                """
                INSERT INTO risk_assessments (
                    id,
                    query_id,
                    score_version,
                    risk_level,
                    result_snapshot
                )
                VALUES (%s::uuid, %s::uuid, 'upgrade-test-v1', 'unknown', %s::jsonb)
                """,
                (ASSESSMENT_ID, QUERY_ID, risk_snapshot),
            )
            cursor.execute(
                """
                INSERT INTO worker_runtime_jobs (
                    id,
                    job_key,
                    adapter_key,
                    status,
                    payload
                )
                VALUES (
                    %s::uuid,
                    'migration-upgrade-test',
                    'official.cwa.rainfall',
                    'queued',
                    %s::jsonb
                )
                """,
                (RUNTIME_JOB_ID, runtime_payload),
            )
            cursor.execute(
                """
                INSERT INTO ingestion_jobs (
                    job_key,
                    adapter_key,
                    started_at,
                    finished_at,
                    status,
                    items_fetched,
                    items_promoted,
                    created_at
                )
                SELECT
                    'migration-upgrade-ingestion-' || series::text,
                    CASE WHEN series % 2 = 0
                        THEN 'official.cwa.rainfall'
                        ELSE 'official.wra.water_level'
                    END,
                    now() - make_interval(mins => series),
                    now() - make_interval(mins => series - 1),
                    'succeeded',
                    series,
                    series,
                    now() - make_interval(mins => series)
                FROM generate_series(1, 6) AS series
                """
            )


def _privacy_fixture_payloads(marker: str) -> tuple[str, str, str]:
    query_metadata = json.dumps({"keep": f"{marker}-query", "nested": {"retain": True}})
    risk_snapshot = json.dumps(
        {
            "location_text": f"{marker} precise address",
            "location": {
                "lat": float(PRECISE_LAT),
                "lng": float(PRECISE_LNG),
                "precision": "rooftop",
                "source": "legacy",
            },
            "keep": f"{marker}-assessment",
            "nested": {"retain": True},
        }
    )
    runtime_payload = json.dumps(
        {
            "location_text": f"{marker} queued address",
            "lat": float(PRECISE_LAT),
            "lng": float(PRECISE_LNG),
            "keep": f"{marker}-runtime",
            "nested": {"retain": True},
        }
    )
    return query_metadata, risk_snapshot, runtime_payload


def _insert_precise_privacy_fixture(
    database_url: str,
    *,
    query_id: str,
    assessment_id: str,
    runtime_job_id: str,
    marker: str,
) -> None:
    query_metadata, risk_snapshot, runtime_payload = _privacy_fixture_payloads(marker)
    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO location_queries (
                    id,
                    input_type,
                    raw_input,
                    geom,
                    radius_m,
                    lat,
                    lng,
                    metadata
                )
                VALUES (
                    %s::uuid,
                    'address',
                    %s,
                    ST_SetSRID(ST_MakePoint(%s, %s), 4326),
                    500,
                    %s,
                    %s,
                    %s::jsonb
                )
                """,
                (
                    query_id,
                    f"{marker} precise address",
                    PRECISE_LNG,
                    PRECISE_LAT,
                    PRECISE_LAT,
                    PRECISE_LNG,
                    query_metadata,
                ),
            )
            cursor.execute(
                """
                INSERT INTO risk_assessments (
                    id,
                    query_id,
                    score_version,
                    risk_level,
                    result_snapshot
                )
                VALUES (%s::uuid, %s::uuid, 'upgrade-test-v1', 'unknown', %s::jsonb)
                """,
                (assessment_id, query_id, risk_snapshot),
            )
            cursor.execute(
                """
                INSERT INTO worker_runtime_jobs (
                    id,
                    job_key,
                    adapter_key,
                    status,
                    payload
                )
                VALUES (
                    %s::uuid,
                    %s,
                    'official.cwa.rainfall',
                    'queued',
                    %s::jsonb
                )
                """,
                (runtime_job_id, f"migration-upgrade-{marker}", runtime_payload),
            )


def _update_with_precise_privacy_fixture(database_url: str, *, marker: str) -> None:
    query_metadata, risk_snapshot, runtime_payload = _privacy_fixture_payloads(marker)
    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE location_queries
                SET
                    raw_input = %s,
                    geom = ST_SetSRID(ST_MakePoint(%s, %s), 4326),
                    lat = %s,
                    lng = %s,
                    metadata = %s::jsonb
                WHERE id = %s::uuid
                """,
                (
                    f"{marker} precise address",
                    PRECISE_LNG,
                    PRECISE_LAT,
                    PRECISE_LAT,
                    PRECISE_LNG,
                    query_metadata,
                    QUERY_ID,
                ),
            )
            cursor.execute(
                """
                UPDATE risk_assessments
                SET result_snapshot = %s::jsonb
                WHERE id = %s::uuid
                """,
                (risk_snapshot, ASSESSMENT_ID),
            )
            cursor.execute(
                """
                UPDATE worker_runtime_jobs
                SET payload = %s::jsonb
                WHERE id = %s::uuid
                """,
                (runtime_payload, RUNTIME_JOB_ID),
            )


def _verify_privacy_scrub(database_url: str) -> None:
    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    raw_input,
                    lat,
                    lng,
                    ST_Y(geom)::numeric,
                    ST_X(geom)::numeric,
                    metadata
                FROM location_queries
                WHERE id = %s::uuid
                """,
                (QUERY_ID,),
            )
            query_row = cursor.fetchone()
            cursor.execute(
                "SELECT result_snapshot FROM risk_assessments WHERE id = %s::uuid",
                (ASSESSMENT_ID,),
            )
            assessment_row = cursor.fetchone()
            cursor.execute(
                "SELECT payload FROM worker_runtime_jobs WHERE id = %s::uuid",
                (RUNTIME_JOB_ID,),
            )
            runtime_row = cursor.fetchone()

    if query_row is None or assessment_row is None or runtime_row is None:
        raise RuntimeError("Seeded privacy verification rows are missing")
    _expect_equal("location raw input scrubbed", query_row[0], None)
    _expect_equal("location latitude rounded", query_row[1], SCRUBBED_LAT)
    _expect_equal("location longitude rounded", query_row[2], SCRUBBED_LNG)
    _expect_equal("location geometry latitude rounded", query_row[3], SCRUBBED_LAT)
    _expect_equal("location geometry longitude rounded", query_row[4], SCRUBBED_LNG)
    _expect_equal("location metadata preserved", query_row[5], {"keep": "query-marker"})

    assessment = assessment_row[0]
    _expect_equal(
        "assessment location text scrubbed", assessment["location_text"], None
    )
    _expect_equal(
        "assessment location rounded",
        assessment["location"],
        {"lat": 25.05, "lng": 121.53},
    )
    _expect_equal(
        "assessment unrelated data preserved", assessment["keep"], "assessment-marker"
    )

    runtime_payload = runtime_row[0]
    _expect_equal(
        "runtime location text removed",
        "location_text" in runtime_payload,
        False,
    )
    _expect_equal("runtime latitude rounded", runtime_payload["lat"], 25.05)
    _expect_equal("runtime longitude rounded", runtime_payload["lng"], 121.53)
    _expect_equal(
        "runtime unrelated data preserved", runtime_payload["keep"], "runtime-marker"
    )


def _verify_fenced_privacy_fixture(
    database_url: str,
    *,
    query_id: str,
    assessment_id: str,
    runtime_job_id: str,
    marker: str,
) -> None:
    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    raw_input,
                    lat,
                    lng,
                    ST_Y(geom)::numeric,
                    ST_X(geom)::numeric,
                    metadata
                FROM location_queries
                WHERE id = %s::uuid
                """,
                (query_id,),
            )
            query_row = cursor.fetchone()
            cursor.execute(
                "SELECT result_snapshot FROM risk_assessments WHERE id = %s::uuid",
                (assessment_id,),
            )
            assessment_row = cursor.fetchone()
            cursor.execute(
                "SELECT payload FROM worker_runtime_jobs WHERE id = %s::uuid",
                (runtime_job_id,),
            )
            runtime_row = cursor.fetchone()

    if query_row is None or assessment_row is None or runtime_row is None:
        raise RuntimeError(f"{marker}: privacy fence fixture rows are missing")
    _expect_equal(f"{marker} raw input scrubbed", query_row[0], None)
    _expect_equal(f"{marker} latitude rounded", query_row[1], SCRUBBED_LAT)
    _expect_equal(f"{marker} longitude rounded", query_row[2], SCRUBBED_LNG)
    _expect_equal(f"{marker} geometry latitude rounded", query_row[3], SCRUBBED_LAT)
    _expect_equal(f"{marker} geometry longitude rounded", query_row[4], SCRUBBED_LNG)
    _expect_equal(
        f"{marker} query metadata preserved",
        query_row[5],
        {"keep": f"{marker}-query", "nested": {"retain": True}},
    )

    assessment = assessment_row[0]
    _expect_equal(
        f"{marker} assessment location text scrubbed",
        assessment["location_text"],
        None,
    )
    _expect_equal(
        f"{marker} assessment location scrubbed without dropping siblings",
        assessment["location"],
        {
            "lat": 25.05,
            "lng": 121.53,
            "precision": "rooftop",
            "source": "legacy",
        },
    )
    _expect_equal(
        f"{marker} assessment unrelated data preserved",
        (assessment["keep"], assessment["nested"]),
        (f"{marker}-assessment", {"retain": True}),
    )

    runtime_payload = runtime_row[0]
    _expect_equal(
        f"{marker} runtime location text removed",
        "location_text" in runtime_payload,
        False,
    )
    _expect_equal(f"{marker} runtime latitude rounded", runtime_payload["lat"], 25.05)
    _expect_equal(f"{marker} runtime longitude rounded", runtime_payload["lng"], 121.53)
    _expect_equal(
        f"{marker} runtime unrelated data preserved",
        (runtime_payload["keep"], runtime_payload["nested"]),
        (f"{marker}-runtime", {"retain": True}),
    )


def _verify_inventory_schema_and_fail_closed_seed(database_url: str) -> None:
    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = 'public'
                    AND tablename = 'ingestion_jobs'
                    AND indexname IN (
                        'idx_ingestion_jobs_adapter_created',
                        'idx_ingestion_jobs_adapter_started'
                    )
                ORDER BY indexname
                """
            )
            indexes = tuple(str(row[0]) for row in cursor.fetchall())
            cursor.execute("SELECT count(*) FROM realtime_jurisdictions")
            jurisdiction_count = _require_int_row(
                cursor.fetchone(), "jurisdiction seed count", columns=1
            )[0]
            cursor.execute(
                "SELECT count(*) FROM realtime_jurisdiction_signal_contracts"
            )
            signal_contract_count = _require_int_row(
                cursor.fetchone(), "signal contract seed count", columns=1
            )[0]
            cursor.execute("SELECT count(*) FROM realtime_source_jurisdictions")
            source_mapping_count = _require_int_row(
                cursor.fetchone(), "source mapping seed count", columns=1
            )[0]
            cursor.execute(
                """
                SELECT
                    (SELECT count(*)
                     FROM realtime_jurisdiction_boundary_snapshots
                     WHERE is_active OR is_complete OR reviewed_at IS NOT NULL),
                    (SELECT count(*)
                     FROM realtime_jurisdiction_signal_contracts
                     WHERE catalog_status <> 'unreviewed'),
                    (SELECT count(*)
                     FROM data_sources
                     WHERE station_inventory_reviewed),
                    (SELECT count(*) FROM station_inventory_snapshots)
                """
            )
            fail_closed_counts = _require_int_row(
                cursor.fetchone(),
                "fail-closed review state counts",
                columns=4,
            )

    _expect_equal(
        "ingestion job indexes",
        indexes,
        (
            "idx_ingestion_jobs_adapter_created",
            "idx_ingestion_jobs_adapter_started",
        ),
    )
    _expect_equal(
        "jurisdiction seed count",
        jurisdiction_count,
        EXPECTED_JURISDICTION_COUNT,
    )
    _expect_equal(
        "jurisdiction signal contract seed count",
        signal_contract_count,
        EXPECTED_SIGNAL_CONTRACT_COUNT,
    )
    _expect_equal(
        "source jurisdiction mapping seed count",
        source_mapping_count,
        EXPECTED_SOURCE_MAPPING_COUNT,
    )
    _expect_equal(
        "active/reviewed/inventory fail-closed counts",
        fail_closed_counts,
        (0, 0, 0, 0),
    )


def _expect_equal(label: str, actual: object, expected: object) -> None:
    if actual != expected:
        raise RuntimeError(f"{label}: expected {expected!r}, got {actual!r}")


def _require_row(
    row: tuple[Any, ...] | None,
    label: str,
) -> tuple[Any, ...]:
    if row is None:
        raise RuntimeError(f"{label}: query returned no row")
    return row


def _require_int_row(
    row: tuple[Any, ...] | None,
    label: str,
    *,
    columns: int,
) -> tuple[int, ...]:
    required = _require_row(row, label)
    if len(required) != columns:
        raise RuntimeError(f"{label}: expected {columns} columns, got {len(required)}")
    if any(isinstance(value, bool) or not isinstance(value, int) for value in required):
        raise RuntimeError(f"{label}: query returned a non-integer count")
    return tuple(required)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
