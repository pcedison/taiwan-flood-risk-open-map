from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.domain.assessment.repository import _complete_signal_types
from app.domain.evidence import (
    fetch_assessment_evidence,
    query_nearby_evidence,
    query_nearby_latest_official,
    query_nearby_recent_context,
)
from app.domain.evidence.repository import (
    query_realtime_jurisdiction_context,
    query_realtime_source_health_rows,
)


def _database_url() -> str:
    database_url = os.getenv("EVIDENCE_TEST_DATABASE_URL")
    required = os.getenv("OFFICIAL_DB_ACCEPTANCE_REQUIRED") == "1"
    if not database_url:
        if required:
            pytest.fail(
                "EVIDENCE_TEST_DATABASE_URL is required when OFFICIAL_DB_ACCEPTANCE_REQUIRED=1"
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


@contextmanager
def _isolated_schema(database_url: str) -> Iterator[str]:
    schema_name = f"task3_{uuid4().hex}"
    with psycopg.connect(database_url, autocommit=True) as connection:
        connection.execute(
            sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name))
        )

    connection_info = psycopg.conninfo.conninfo_to_dict(database_url)
    existing_options = connection_info.get("options", "")
    connection_info["options"] = (
        f"{existing_options} -c search_path={schema_name},public".strip()
    )
    isolated_url = psycopg.conninfo.make_conninfo(**connection_info)
    try:
        yield isolated_url
    finally:
        with psycopg.connect(database_url, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name))
            )


def _prepare_latest_schema(database_url: str) -> None:
    with psycopg.connect(database_url) as connection:
        connection.execute(
            """
            CREATE TABLE data_sources (
                adapter_key text PRIMARY KEY,
                is_enabled boolean NOT NULL
            );
            CREATE TABLE evidence (
                id uuid PRIMARY KEY,
                event_type text NOT NULL,
                title text NOT NULL,
                summary text NOT NULL,
                url text,
                occurred_at timestamptz,
                observed_at timestamptz,
                ingested_at timestamptz NOT NULL DEFAULT now(),
                geom geometry(Geometry, 4326),
                confidence numeric(6,3),
                freshness_score numeric(6,3),
                source_weight numeric(6,3),
                properties jsonb NOT NULL DEFAULT '{}'::jsonb
            );
            CREATE TABLE official_realtime_latest (
                source_id text NOT NULL,
                adapter_key text NOT NULL,
                event_type text NOT NULL,
                station_id text NOT NULL,
                observed_at timestamptz NOT NULL,
                ingested_at timestamptz NOT NULL DEFAULT now(),
                geom geometry(Point, 4326) NOT NULL,
                rainfall_mm_1h double precision,
                water_level_m double precision,
                warning_level_m double precision,
                flood_depth_cm double precision,
                confidence numeric(6,3),
                freshness_score numeric(6,3),
                source_weight numeric(6,3),
                risk_factor numeric(6,3),
                evidence_id uuid,
                source_url text,
                quality_flags jsonb NOT NULL DEFAULT '{}'::jsonb,
                updated_at timestamptz NOT NULL DEFAULT now(),
                PRIMARY KEY (adapter_key, event_type, station_id)
            );
            CREATE TABLE ingestion_jobs (
                adapter_key text,
                started_at timestamptz,
                status text NOT NULL,
                error_code text
            )
            """
        )


def _prepare_history_snapshot_schema(database_url: str) -> None:
    with psycopg.connect(database_url) as connection:
        connection.execute(
            """
            CREATE TABLE data_sources (
                id uuid PRIMARY KEY,
                adapter_key text NOT NULL UNIQUE,
                is_enabled boolean NOT NULL,
                metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
                runtime_pipeline_status text
            );
            CREATE TABLE evidence (
                id uuid PRIMARY KEY,
                data_source_id uuid NOT NULL REFERENCES data_sources(id),
                source_id text NOT NULL,
                source_type text NOT NULL,
                event_type text NOT NULL,
                title text NOT NULL,
                summary text NOT NULL,
                url text,
                occurred_at timestamptz,
                observed_at timestamptz,
                ingested_at timestamptz NOT NULL DEFAULT now(),
                geom geometry(Geometry, 4326),
                distance_to_query_m numeric(10,2),
                confidence numeric(6,3) NOT NULL,
                freshness_score numeric(6,3),
                source_weight numeric(6,3),
                privacy_level text NOT NULL DEFAULT 'public',
                raw_ref text,
                ingestion_status text NOT NULL DEFAULT 'accepted',
                properties jsonb NOT NULL DEFAULT '{}'::jsonb,
                created_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )


def test_wra_history_reader_switches_complete_snapshot_and_keeps_last_known_good() -> None:
    database_url = _database_url()
    raw_a = f"raw/official/wra/historical_flood/{'a' * 64}.json"
    raw_b = f"raw/official/wra/historical_flood/{'b' * 64}.json"
    history_source_id = uuid4()
    ordinary_source_id = uuid4()
    a_shared_id, a_removed_id, b_shared_id, ordinary_id, disabled_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )

    with _isolated_schema(database_url) as isolated_url:
        _prepare_history_snapshot_schema(isolated_url)
        with psycopg.connect(isolated_url) as connection:
            connection.execute(
                """
                INSERT INTO data_sources (
                    id, adapter_key, is_enabled, metadata, runtime_pipeline_status
                ) VALUES
                    (%s, 'official.wra.historical_flood', true, %s::jsonb, 'succeeded'),
                    (%s, 'official.test.ordinary', true, '{}'::jsonb, 'succeeded')
                """,
                (
                    history_source_id,
                    Jsonb({"active_snapshot_raw_ref": raw_a}),
                    ordinary_source_id,
                ),
            )
            for evidence_id, data_source_id, source_id, raw_ref, title, properties in (
                (
                    a_shared_id,
                    history_source_id,
                    "shared-record",
                    raw_a,
                    "A shared",
                    {"evidence_scope": "historical"},
                ),
                (
                    a_removed_id,
                    history_source_id,
                    "removed-in-b",
                    raw_a,
                    "A removed",
                    {"evidence_scope": "historical"},
                ),
                (
                    b_shared_id,
                    history_source_id,
                    "shared-record",
                    raw_b,
                    "B shared",
                    {"evidence_scope": "historical"},
                ),
                (
                    ordinary_id,
                    ordinary_source_id,
                    "ordinary",
                    None,
                    "Ordinary",
                    {"evidence_scope": "current"},
                ),
                (
                    disabled_id,
                    ordinary_source_id,
                    "disabled-station",
                    None,
                    "Disabled station",
                    {
                        "evidence_scope": "current",
                        "realtime_station_enabled": False,
                    },
                ),
            ):
                connection.execute(
                    """
                    INSERT INTO evidence (
                        id, data_source_id, source_id, source_type, event_type,
                        title, summary, occurred_at, observed_at, geom,
                        confidence, privacy_level, raw_ref, ingestion_status,
                        properties
                    ) VALUES (
                        %s, %s, %s, 'official', 'flood_report', %s, %s,
                        now(), now(),
                        ST_SetSRID(ST_MakePoint(120.0, 23.0), 4326),
                        0.9, 'public', %s, 'accepted', %s::jsonb
                    )
                    """,
                    (
                        evidence_id,
                        data_source_id,
                        source_id,
                        title,
                        title,
                        raw_ref,
                        Jsonb(properties),
                    ),
                )

        def visible_ids() -> set[str]:
            return {
                record.id
                for record in query_nearby_evidence(
                    database_url=isolated_url,
                    lat=23.0,
                    lng=120.0,
                    radius_m=500,
                    limit=100,
                    connection_factory=lambda: _unpooled_connection(isolated_url),
                )
            }

        # B may already be promoted/auditable, but A remains public until activation.
        assert visible_ids() == {
            str(a_shared_id),
            str(a_removed_id),
            str(ordinary_id),
        }

        with psycopg.connect(isolated_url) as connection:
            connection.execute(
                """
                UPDATE data_sources
                SET metadata = jsonb_build_object(
                    'active_snapshot_raw_ref',
                    %s::text
                )
                WHERE adapter_key = 'official.wra.historical_flood'
                """,
                (raw_b,),
            )
        # Atomic activation switches the full generation, including removed rows.
        assert visible_ids() == {str(b_shared_id), str(ordinary_id)}

        with psycopg.connect(isolated_url) as connection:
            connection.execute(
                """
                UPDATE data_sources
                SET runtime_pipeline_status = 'failed'
                WHERE adapter_key = 'official.wra.historical_flood'
                """
            )
        assert visible_ids() == {str(b_shared_id), str(ordinary_id)}

        with psycopg.connect(isolated_url) as connection:
            connection.execute(
                """
                UPDATE data_sources
                SET metadata = '{}'::jsonb
                WHERE adapter_key = 'official.wra.historical_flood'
                """
            )
        assert visible_ids() == {str(ordinary_id)}


def test_source_health_safely_resolves_bounded_catalog_thresholds() -> None:
    database_url = _database_url()
    adapter_key = f"test.threshold.{uuid4().hex}"
    cases = (
        (" 120 ", 120),
        ("not-a-number", 600),
        ("0", 600),
        ("-1", 600),
        ("9" * 1000, 600),
        ("86401", 600),
        ("86400", 86_400),
    )

    try:
        with psycopg.connect(database_url) as connection:
            connection.execute(
                """
                INSERT INTO data_sources (
                    name,
                    adapter_key,
                    source_type,
                    is_enabled,
                    metadata
                )
                VALUES (%s, %s, 'official', true, '{}'::jsonb)
                """,
                ("Task 9 threshold fixture", adapter_key),
            )

        for raw_threshold, expected in cases:
            with psycopg.connect(database_url) as connection:
                connection.execute(
                    """
                    UPDATE data_sources
                    SET metadata = jsonb_build_object(
                        'freshness_threshold_seconds',
                        %s::text
                    )
                    WHERE adapter_key = %s
                    """,
                    (raw_threshold, adapter_key),
                )

            rows = query_realtime_source_health_rows(
                database_url=database_url,
                adapter_keys=(adapter_key,),
                connection_factory=lambda: psycopg.connect(
                    database_url,
                    row_factory=dict_row,
                ),
            )

            assert rows[0].freshness_threshold_seconds == expected
    finally:
        with psycopg.connect(database_url) as connection:
            connection.execute(
                "DELETE FROM data_sources WHERE adapter_key = %s",
                (adapter_key,),
            )


def _unpooled_connection(database_url: str) -> psycopg.Connection:
    return psycopg.connect(database_url, row_factory=dict_row)


def _prepare_jurisdiction_schema(database_url: str) -> None:
    with psycopg.connect(database_url) as connection:
        connection.execute(
            """
            CREATE TABLE realtime_jurisdictions (
                jurisdiction_code text PRIMARY KEY,
                jurisdiction_name text NOT NULL
            );
            CREATE TABLE realtime_jurisdiction_boundary_snapshots (
                id uuid PRIMARY KEY,
                expected_count integer NOT NULL,
                imported_count integer NOT NULL,
                manifest_sha256 text,
                approved_manifest_sha256 text,
                is_complete boolean NOT NULL,
                reviewed_at timestamptz,
                review_ref text,
                is_active boolean NOT NULL
            );
            CREATE TABLE realtime_jurisdiction_boundaries (
                snapshot_id uuid NOT NULL,
                jurisdiction_code text NOT NULL,
                geom geometry(MultiPolygon, 4326) NOT NULL,
                geom_sha256 text NOT NULL
            );
            CREATE TABLE realtime_jurisdiction_signal_contracts (
                jurisdiction_code text NOT NULL,
                signal_type text NOT NULL,
                catalog_status text NOT NULL,
                mapping_revision text NOT NULL,
                mapping_manifest_version text NOT NULL,
                approved_mapping_count integer,
                approved_mapping_manifest_sha256 text,
                reviewed_at timestamptz,
                review_ref text
            );
            CREATE TABLE realtime_source_jurisdictions (
                adapter_key text NOT NULL,
                signal_type text NOT NULL,
                coverage_scope text NOT NULL,
                jurisdiction_code text NOT NULL,
                requirement_role text NOT NULL,
                redundancy_of_adapter_key text,
                mapping_revision text NOT NULL
            )
            """
        )


def _insert_latest_source(connection: psycopg.Connection, adapter_key: str) -> None:
    connection.execute(
        "INSERT INTO data_sources (adapter_key, is_enabled) VALUES (%s, true)",
        (adapter_key,),
    )


def _insert_latest_row(
    connection: psycopg.Connection,
    *,
    adapter_key: str,
    station_id: str,
    event_type: str,
    observed_at: datetime,
    evidence_id: object | None,
) -> None:
    connection.execute(
        """
        INSERT INTO official_realtime_latest (
            source_id, adapter_key, event_type, station_id,
            observed_at, geom, evidence_id
        ) VALUES (
            %s, %s, %s, %s, %s,
            ST_SetSRID(ST_MakePoint(120.0, 23.0), 4326), %s
        )
        """,
        (
            f"source:{station_id}",
            adapter_key,
            event_type,
            station_id,
            observed_at,
            evidence_id,
        ),
    )


def _insert_evidence(
    connection: psycopg.Connection,
    *,
    evidence_id: object,
    station_id: str,
    event_type: str,
    observed_at: datetime,
    properties: dict[str, object],
    polygon: bool = False,
) -> None:
    geometry_wkt = (
        "POLYGON((119.999 22.999,120.001 22.999,120.001 23.001,"
        "119.999 23.001,119.999 22.999))"
        if polygon
        else "POINT(120.0 23.0)"
    )
    connection.execute(
        """
        INSERT INTO evidence (
            id, event_type, title, summary, observed_at,
            geom, confidence, properties
        ) VALUES (
            %s, %s, %s, %s, %s,
            ST_GeomFromText(%s, 4326), 0.9, %s::jsonb
        )
        """,
        (
            evidence_id,
            event_type,
            station_id,
            station_id,
            observed_at,
            geometry_wkt,
            Jsonb(properties),
        ),
    )


def _insert_migrated_source(
    connection: psycopg.Connection,
    *,
    source_id: object,
    adapter_key: str,
    enabled: bool = True,
) -> None:
    connection.execute(
        """
        INSERT INTO data_sources (
            id, name, adapter_key, source_type, is_enabled
        ) VALUES (%s, 'Task 5 privacy regression', %s, 'official', %s)
        """,
        (source_id, adapter_key, enabled),
    )


def _insert_migrated_evidence(
    connection: psycopg.Connection,
    *,
    evidence_id: object,
    source_id: object,
    observed_at: datetime,
    limitations: object,
    event_type: str = "flood_potential",
    privacy_level: str = "public",
) -> None:
    connection.execute(
        """
        INSERT INTO evidence (
            id, data_source_id, source_id, source_type, event_type,
            title, summary, occurred_at, observed_at, geom, confidence,
            privacy_level, properties
        ) VALUES (
            %s, %s, %s, 'official', %s,
            'Task 5 privacy regression', 'Task 5 privacy regression', %s, %s,
            ST_SetSRID(ST_MakePoint(120.0, 23.0), 4326), 0.9,
            %s, %s::jsonb
        )
        """,
        (
            evidence_id,
            source_id,
            f"task5:{evidence_id}",
            event_type,
            observed_at,
            observed_at,
            privacy_level,
            Jsonb(
                {
                    "evidence_scope": (
                        "context" if event_type == "flood_potential" else "historical"
                    ),
                    "limitations": limitations,
                }
            ),
        ),
    )


def _warning_properties(
    *,
    now: datetime,
    identifier: str,
    generation: datetime,
) -> dict[str, object]:
    return {
        "evidence_scope": "current",
        "cap_status": "Actual",
        "cap_message_type": "Alert",
        "active_from": (now - timedelta(hours=1)).isoformat(),
        "active_until": (now + timedelta(hours=1)).isoformat(),
        "cap_sender": "sender@example.tw",
        "cap_identifier": identifier,
        "cap_sent": (now - timedelta(minutes=30)).isoformat(),
        "admin_code": "67000000",
        "ingestion_generation_started_at": generation.isoformat(),
    }


def test_jurisdiction_proof_requires_every_considered_county_in_real_sql() -> None:
    database_url = _database_url()
    revision = "2026-08-24-v1-baseline"
    warning_revision = "2026-08-28-v1-warning-alignment"
    now = datetime(2026, 8, 24, 4, 0, tzinfo=UTC)
    snapshot_id = uuid4()
    codes = ["67000000", "64000000"] + [f"9{index:07d}" for index in range(20)]
    with _isolated_schema(database_url) as isolated_url:
        _prepare_jurisdiction_schema(isolated_url)
        with psycopg.connect(isolated_url) as connection:
            connection.execute(
                """
                INSERT INTO realtime_jurisdiction_boundary_snapshots (
                    id, expected_count, imported_count,
                    is_complete, is_active
                ) VALUES (%s, 22, 22, true, true)
                """,
                (snapshot_id,),
            )
            for index, code in enumerate(codes):
                if code == "67000000":
                    name = "臺南市"
                    polygon = (
                        "MULTIPOLYGON(((119.999 22.999,120.0005 22.999,"
                        "120.0005 23.001,119.999 23.001,119.999 22.999)))"
                    )
                elif code == "64000000":
                    name = "高雄市"
                    polygon = (
                        "MULTIPOLYGON(((120.001 22.999,120.002 22.999,"
                        "120.002 23.001,120.001 23.001,120.001 22.999)))"
                    )
                else:
                    name = f"遠端縣市 {index}"
                    x_min = 121.0 + index * 0.01
                    x_max = x_min + 0.001
                    polygon = (
                        f"MULTIPOLYGON((({x_min} 24.0,{x_max} 24.0,"
                        f"{x_max} 24.001,{x_min} 24.001,{x_min} 24.0)))"
                    )
                connection.execute(
                    "INSERT INTO realtime_jurisdictions VALUES (%s, %s)",
                    (code, name),
                )
                connection.execute(
                    """
                    WITH geometry_row AS (
                        SELECT ST_GeomFromText(%s, 4326)::geometry(MultiPolygon, 4326)
                            AS geom
                    )
                    INSERT INTO realtime_jurisdiction_boundaries (
                        snapshot_id, jurisdiction_code, geom, geom_sha256
                    )
                    SELECT
                        %s, %s, geom,
                        encode(digest(ST_AsEWKB(geom), 'sha256'), 'hex')
                    FROM geometry_row
                    """,
                    (polygon, snapshot_id, code),
                )
            connection.execute(
                """
                WITH manifest AS (
                    SELECT encode(
                        digest(
                            convert_to(
                                jsonb_agg(
                                    jsonb_build_array(jurisdiction_code, geom_sha256)
                                    ORDER BY jurisdiction_code
                                )::text,
                                'UTF8'
                            ),
                            'sha256'
                        ),
                        'hex'
                    ) AS sha256
                    FROM realtime_jurisdiction_boundaries
                    WHERE snapshot_id = %s
                )
                UPDATE realtime_jurisdiction_boundary_snapshots
                SET manifest_sha256 = manifest.sha256,
                    approved_manifest_sha256 = manifest.sha256,
                    reviewed_at = %s,
                    review_ref = 'task-3-regression'
                FROM manifest
                WHERE id = %s
                """,
                (snapshot_id, now, snapshot_id),
            )

            mapping_hashes: dict[str, str] = {}
            for signal_type in ("rainfall", "water_level", "flood_depth"):
                adapter_key = f"test.task3.{signal_type}"
                connection.execute(
                    """
                    INSERT INTO realtime_source_jurisdictions VALUES (
                        %s, %s, 'national', 'TW', 'required', NULL, %s
                    )
                    """,
                    (adapter_key, signal_type, revision),
                )
                mapping_hashes[signal_type] = connection.execute(
                    """
                    SELECT encode(
                        digest(
                            convert_to(
                                jsonb_build_array(
                                    jsonb_build_array(
                                        %s::text, %s::text, 'national', 'TW',
                                        'required', NULL, %s::text
                                    )
                                )::text,
                                'UTF8'
                            ),
                            'sha256'
                        ),
                        'hex'
                    )
                    """,
                    (adapter_key, signal_type, revision),
                ).fetchone()[0]

            connection.execute(
                """
                INSERT INTO realtime_source_jurisdictions VALUES
                    (
                        'official.ncdr.cap', 'flood_warning', 'national', 'TW',
                        'required', NULL, %s
                    ),
                    (
                        'official.cwa.heavy_rain_warning', 'flood_warning',
                        'national', 'TW', 'redundant_subset', 'official.ncdr.cap', %s
                    ),
                    (
                        'test.task4.warning.stale', 'flood_warning', 'national', 'TW',
                        'required', NULL, %s
                    )
                """,
                (warning_revision, warning_revision, revision),
            )
            warning_mapping_hash = connection.execute(
                """
                SELECT encode(
                    digest(
                        convert_to(
                            jsonb_agg(
                                jsonb_build_array(
                                    adapter_key, signal_type, coverage_scope,
                                    jurisdiction_code, requirement_role,
                                    redundancy_of_adapter_key, mapping_revision
                                )
                                ORDER BY adapter_key, coverage_scope,
                                    jurisdiction_code, requirement_role,
                                    redundancy_of_adapter_key, mapping_revision
                            )::text,
                            'UTF8'
                        ),
                        'sha256'
                    ),
                    'hex'
                )
                FROM realtime_source_jurisdictions
                WHERE signal_type = 'flood_warning'
                    AND mapping_revision = %s
                """,
                (warning_revision,),
            ).fetchone()[0]

            for code in ("67000000", "64000000"):
                for signal_type in ("rainfall", "water_level", "flood_depth"):
                    status = (
                        "unreviewed"
                        if code == "64000000" and signal_type == "water_level"
                        else "reviewed_complete"
                    )
                    connection.execute(
                        """
                        INSERT INTO realtime_jurisdiction_signal_contracts (
                            jurisdiction_code, signal_type, catalog_status,
                            mapping_revision, mapping_manifest_version,
                            approved_mapping_count,
                            approved_mapping_manifest_sha256,
                            reviewed_at, review_ref
                        ) VALUES (
                            %s, %s, %s, %s, 'jurisdiction-source-jsonb-v1',
                            1, %s, %s, 'task-3-regression'
                        )
                        """,
                        (
                            code,
                            signal_type,
                            status,
                            revision,
                            mapping_hashes[signal_type],
                            now,
                        ),
                    )
                connection.execute(
                    """
                    INSERT INTO realtime_jurisdiction_signal_contracts (
                        jurisdiction_code, signal_type, catalog_status,
                        mapping_revision, mapping_manifest_version,
                        approved_mapping_count,
                        approved_mapping_manifest_sha256,
                        reviewed_at, review_ref
                    ) VALUES (
                        %s, 'flood_warning', 'reviewed_complete', %s,
                        'jurisdiction-source-jsonb-v1', 2, %s, %s,
                        'task-4-warning-revision-regression'
                    )
                    """,
                    (code, warning_revision, warning_mapping_hash, now),
                )

        context = query_realtime_jurisdiction_context(
            database_url=isolated_url,
            lat=23.0,
            lng=120.0,
            search_radius_m=500,
            connection_factory=lambda: _unpooled_connection(isolated_url),
        )
        assert context.resolution_status == "verified"
        assert {code for code, _ in context.considered_jurisdictions} == {
            "67000000",
            "64000000",
        }
        kaohsiung_water = next(
            contract
            for contract in context.signal_contracts
            if contract.jurisdiction_code == "64000000"
            and contract.signal_type == "water_level"
        )
        assert kaohsiung_water.mapping_proof_valid is False
        assert _complete_signal_types(context) == ("flood_depth", "rainfall")
        assert {
            (contract.signal_type, contract.mapping_revision)
            for contract in context.signal_contracts
        } >= {
            ("rainfall", revision),
            ("water_level", revision),
            ("flood_depth", revision),
            ("flood_warning", warning_revision),
        }
        assert {mapping.adapter_key for mapping in context.source_mappings} >= {
            "official.ncdr.cap",
            "official.cwa.heavy_rain_warning",
            "test.task3.rainfall",
            "test.task3.water_level",
            "test.task3.flood_depth",
        }
        assert "test.task4.warning.stale" not in {
            mapping.adapter_key for mapping in context.source_mappings
        }


def test_latest_reader_rejects_dirty_or_missing_scope_and_honors_depth_lookback() -> None:
    database_url = _database_url()
    now = datetime(2026, 8, 24, 4, 0, tzinfo=UTC)
    with _isolated_schema(database_url) as isolated_url:
        _prepare_latest_schema(isolated_url)
        adapter_key = "test.task3.scope"
        with psycopg.connect(isolated_url) as connection:
            _insert_latest_source(connection, adapter_key)
            expected_ids = []
            for station_id, event_type, scope, observed_at, enabled_properties in (
                ("current", "rainfall", "current", now, {}),
                ("context", "water_level", "context", now, {}),
                ("missing", "flood_report", None, now, {}),
                ("depth-recent", "flood_depth", "current", now, {}),
                ("depth-old", "flood_depth", "current", now - timedelta(hours=7), {}),
                (
                    "disabled-realtime",
                    "flood_report",
                    "current",
                    now,
                    {"realtime_station_enabled": False},
                ),
                (
                    "disabled-metadata",
                    "flood_report",
                    "current",
                    now,
                    {"metadata_station_enabled": False},
                ),
            ):
                evidence_id = uuid4()
                properties = {} if scope is None else {"evidence_scope": scope}
                properties.update(enabled_properties)
                _insert_evidence(
                    connection,
                    evidence_id=evidence_id,
                    station_id=station_id,
                    event_type=event_type,
                    observed_at=observed_at,
                    properties=properties,
                )
                _insert_latest_row(
                    connection,
                    adapter_key=adapter_key,
                    station_id=station_id,
                    event_type=event_type,
                    observed_at=observed_at,
                    evidence_id=evidence_id,
                )
                if station_id in {"current", "depth-recent"}:
                    expected_ids.append(str(evidence_id))
            _insert_latest_row(
                connection,
                adapter_key=adapter_key,
                station_id="unlinked",
                event_type="rainfall",
                observed_at=now,
                evidence_id=None,
            )

        records = query_nearby_latest_official(
            database_url=isolated_url,
            lat=23.0,
            lng=120.0,
            radius_m=500,
            as_of=now,
            observed_since=now - timedelta(hours=6),
            connection_factory=lambda: _unpooled_connection(isolated_url),
        )
        assert {record.id for record in records} == set(expected_ids)
        depth = next(record for record in records if record.event_type == "flood_depth")
        assert depth.evidence_scope == "current"


def test_latest_reader_preserves_reviewed_precision_and_limitations() -> None:
    database_url = _database_url()
    now = datetime(2026, 8, 24, 4, 0, tzinfo=UTC)
    with _isolated_schema(database_url) as isolated_url:
        _prepare_latest_schema(isolated_url)
        adapter_key = "test.task5.precision"
        cases = (
            ("absent", None, "point", ["array limitation"], ("array limitation",)),
            ("allowed", "road_or_lane", "road_or_lane", "scalar", ()),
            ("exact", "exact_address", "unknown", {"dirty": True}, ()),
            ("unknown", "unknown", "unknown", None, ()),
        )
        with psycopg.connect(isolated_url) as connection:
            _insert_latest_source(connection, adapter_key)
            for (
                station_id,
                stored_precision,
                _expected_precision,
                stored_limitations,
                _expected_limitations,
            ) in cases:
                evidence_id = uuid4()
                _insert_evidence(
                    connection,
                    evidence_id=evidence_id,
                    station_id=station_id,
                    event_type="rainfall",
                    observed_at=now,
                    properties={
                        "evidence_scope": "current",
                        "limitations": stored_limitations,
                    },
                )
                _insert_latest_row(
                    connection,
                    adapter_key=adapter_key,
                    station_id=station_id,
                    event_type="rainfall",
                    observed_at=now,
                    evidence_id=evidence_id,
                )
                if stored_precision is not None:
                    connection.execute(
                        """
                        UPDATE official_realtime_latest
                        SET quality_flags = %s::jsonb
                        WHERE adapter_key = %s
                            AND event_type = 'rainfall'
                            AND station_id = %s
                        """,
                        (
                            Jsonb({"location_precision": stored_precision}),
                            adapter_key,
                            station_id,
                        ),
                    )

        records = query_nearby_latest_official(
            database_url=isolated_url,
            lat=23.0,
            lng=120.0,
            radius_m=500,
            as_of=now,
            connection_factory=lambda: _unpooled_connection(isolated_url),
        )
        by_station = {record.source_id.removeprefix("source:"): record for record in records}
        assert set(by_station) == {station_id for station_id, *_rest in cases}
        for (
            station_id,
            _stored_precision,
            expected_precision,
            _stored_limitations,
            expected_limitations,
        ) in cases:
            assert by_station[station_id].location_precision == expected_precision
            assert by_station[station_id].limitations == expected_limitations


def test_latest_reader_excludes_regex_shaped_invalid_cap_fields_per_row() -> None:
    database_url = _database_url()
    now = datetime(2026, 8, 24, 4, 0, tzinfo=UTC)
    generation = now - timedelta(minutes=10)
    invalid_timestamp = "2026-02-30T04:00:00+00:00"
    with _isolated_schema(database_url) as isolated_url:
        _prepare_latest_schema(isolated_url)
        adapter_key = "test.task3.malformed-cap"
        valid_id = uuid4()
        with psycopg.connect(isolated_url) as connection:
            _insert_latest_source(connection, adapter_key)
            cases: tuple[tuple[str, str | None, object], ...] = (
                ("valid", None, "unchanged"),
                ("bad-active-from", "active_from", invalid_timestamp),
                ("bad-active-until", "active_until", invalid_timestamp),
                ("bad-sent", "cap_sent", invalid_timestamp),
                (
                    "bad-generation",
                    "ingestion_generation_started_at",
                    invalid_timestamp,
                ),
                ("missing-sender", "cap_sender", ""),
                ("unicode-admin", "admin_code", "６７００００００"),
            )
            for station_id, field, value in cases:
                evidence_id = valid_id if station_id == "valid" else uuid4()
                properties = _warning_properties(
                    now=now,
                    identifier=station_id,
                    generation=generation,
                )
                if field is not None:
                    properties[field] = value
                _insert_evidence(
                    connection,
                    evidence_id=evidence_id,
                    station_id=station_id,
                    event_type="flood_warning",
                    observed_at=now,
                    properties=properties,
                    polygon=True,
                )
                _insert_latest_row(
                    connection,
                    adapter_key=adapter_key,
                    station_id=station_id,
                    event_type="flood_warning",
                    observed_at=now,
                    evidence_id=evidence_id,
                )

        records = query_nearby_latest_official(
            database_url=isolated_url,
            lat=23.0,
            lng=120.0,
            radius_m=500,
            as_of=now,
            connection_factory=lambda: _unpooled_connection(isolated_url),
        )
        assert [record.id for record in records] == [str(valid_id)]


def test_cancel_overwrites_and_retires_prior_alert_latest_row() -> None:
    database_url = _database_url()
    now = datetime(2026, 8, 24, 4, 0, tzinfo=UTC)
    generation = now - timedelta(minutes=10)
    with _isolated_schema(database_url) as isolated_url:
        _prepare_latest_schema(isolated_url)
        adapter_key = "test.task3.cancel"
        alert_id, cancel_id = uuid4(), uuid4()
        with psycopg.connect(isolated_url) as connection:
            _insert_latest_source(connection, adapter_key)
            alert = _warning_properties(
                now=now,
                identifier="same-cap",
                generation=generation,
            )
            _insert_evidence(
                connection,
                evidence_id=alert_id,
                station_id="same-cap",
                event_type="flood_warning",
                observed_at=now,
                properties=alert,
                polygon=True,
            )
            _insert_latest_row(
                connection,
                adapter_key=adapter_key,
                station_id="same-cap",
                event_type="flood_warning",
                observed_at=now,
                evidence_id=alert_id,
            )

        before_cancel = query_nearby_latest_official(
            database_url=isolated_url,
            lat=23.0,
            lng=120.0,
            radius_m=500,
            as_of=now,
            connection_factory=lambda: _unpooled_connection(isolated_url),
        )
        assert [record.id for record in before_cancel] == [str(alert_id)]

        with psycopg.connect(isolated_url) as connection:
            cancel = dict(alert)
            cancel["cap_message_type"] = "Cancel"
            _insert_evidence(
                connection,
                evidence_id=cancel_id,
                station_id="same-cap-cancel",
                event_type="flood_warning",
                observed_at=now + timedelta(minutes=1),
                properties=cancel,
                polygon=True,
            )
            connection.execute(
                """
                UPDATE official_realtime_latest
                SET source_id = 'source:same-cap-cancel',
                    observed_at = %s,
                    evidence_id = %s,
                    updated_at = %s
                WHERE adapter_key = %s
                    AND event_type = 'flood_warning'
                    AND station_id = 'same-cap'
                """,
                (
                    now + timedelta(minutes=1),
                    cancel_id,
                    now + timedelta(minutes=1),
                    adapter_key,
                ),
            )

        assert query_nearby_latest_official(
            database_url=isolated_url,
            lat=23.0,
            lng=120.0,
            radius_m=500,
            as_of=now + timedelta(minutes=1),
            connection_factory=lambda: _unpooled_connection(isolated_url),
        ) == ()


def test_no_active_event_generation_retires_prior_warning() -> None:
    database_url = _database_url()
    now = datetime(2026, 8, 24, 4, 0, tzinfo=UTC)
    generation = now - timedelta(minutes=10)
    with _isolated_schema(database_url) as isolated_url:
        _prepare_latest_schema(isolated_url)
        adapter_key = "test.task3.no-active-event"
        evidence_id = uuid4()
        with psycopg.connect(isolated_url) as connection:
            _insert_latest_source(connection, adapter_key)
            _insert_evidence(
                connection,
                evidence_id=evidence_id,
                station_id="prior-warning",
                event_type="flood_warning",
                observed_at=now,
                properties=_warning_properties(
                    now=now,
                    identifier="prior-warning",
                    generation=generation,
                ),
                polygon=True,
            )
            _insert_latest_row(
                connection,
                adapter_key=adapter_key,
                station_id="prior-warning",
                event_type="flood_warning",
                observed_at=now,
                evidence_id=evidence_id,
            )
            connection.execute(
                """
                INSERT INTO ingestion_jobs (
                    adapter_key, started_at, status, error_code
                ) VALUES (%s, %s, 'succeeded', 'no_active_event')
                """,
                (adapter_key, generation + timedelta(minutes=1)),
            )

        assert query_nearby_latest_official(
            database_url=isolated_url,
            lat=23.0,
            lng=120.0,
            radius_m=500,
            as_of=now,
            connection_factory=lambda: _unpooled_connection(isolated_url),
        ) == ()


def test_canonical_warning_dedupe_precedes_limit_and_prefers_cwa() -> None:
    database_url = _database_url()
    now = datetime(2026, 8, 24, 4, 0, tzinfo=UTC)
    generation = now - timedelta(minutes=10)
    with _isolated_schema(database_url) as isolated_url:
        _prepare_latest_schema(isolated_url)
        cwa_key = "official.cwa.heavy_rain_warning"
        ncdr_key = "official.ncdr.cap"
        cwa_id, ncdr_duplicate_id, other_id = uuid4(), uuid4(), uuid4()
        with psycopg.connect(isolated_url) as connection:
            _insert_latest_source(connection, cwa_key)
            _insert_latest_source(connection, ncdr_key)
            for adapter_key, station_id, evidence_id, identifier in (
                (cwa_key, "cwa-duplicate", cwa_id, "shared-origin"),
                (ncdr_key, "ncdr-duplicate", ncdr_duplicate_id, "shared-origin"),
                (ncdr_key, "other-warning", other_id, "other-origin"),
            ):
                _insert_evidence(
                    connection,
                    evidence_id=evidence_id,
                    station_id=station_id,
                    event_type="flood_warning",
                    observed_at=now,
                    properties=_warning_properties(
                        now=now,
                        identifier=identifier,
                        generation=generation,
                    ),
                    polygon=True,
                )
                _insert_latest_row(
                    connection,
                    adapter_key=adapter_key,
                    station_id=station_id,
                    event_type="flood_warning",
                    observed_at=now,
                    evidence_id=evidence_id,
                )

        records = query_nearby_latest_official(
            database_url=isolated_url,
            lat=23.0,
            lng=120.0,
            radius_m=500,
            as_of=now,
            limit=2,
            connection_factory=lambda: _unpooled_connection(isolated_url),
        )
        assert {record.id for record in records} == {str(cwa_id), str(other_id)}
        assert str(ncdr_duplicate_id) not in {record.id for record in records}


def test_cap_shaped_non_warning_cannot_take_warning_rank() -> None:
    database_url = _database_url()
    now = datetime(2026, 8, 24, 4, 0, tzinfo=UTC)
    generation = now - timedelta(minutes=10)
    with _isolated_schema(database_url) as isolated_url:
        _prepare_latest_schema(isolated_url)
        adapter_key = "official.cwa.heavy_rain_warning"
        warning_id, rainfall_id = uuid4(), uuid4()
        shared_properties = _warning_properties(
            now=now,
            identifier="shared-cross-event-origin",
            generation=generation,
        )
        with psycopg.connect(isolated_url) as connection:
            _insert_latest_source(connection, adapter_key)
            for station_id, event_type, evidence_id, observed_at, polygon in (
                ("active-warning", "flood_warning", warning_id, now, True),
                (
                    "newer-rainfall",
                    "rainfall",
                    rainfall_id,
                    now + timedelta(minutes=1),
                    False,
                ),
            ):
                _insert_evidence(
                    connection,
                    evidence_id=evidence_id,
                    station_id=station_id,
                    event_type=event_type,
                    observed_at=observed_at,
                    properties=shared_properties,
                    polygon=polygon,
                )
                _insert_latest_row(
                    connection,
                    adapter_key=adapter_key,
                    station_id=station_id,
                    event_type=event_type,
                    observed_at=observed_at,
                    evidence_id=evidence_id,
                )

        records = query_nearby_latest_official(
            database_url=isolated_url,
            lat=23.0,
            lng=120.0,
            radius_m=500,
            as_of=now + timedelta(minutes=2),
            connection_factory=lambda: _unpooled_connection(isolated_url),
        )
        assert {record.id for record in records} == {
            str(warning_id),
            str(rainfall_id),
        }


def test_generic_history_uses_exact_geography_radius_polygon_and_kill_switch() -> None:
    database_url = _database_url()
    source_id = uuid4()
    outside_point_id = uuid4()
    intersecting_polygon_id = uuid4()
    adapter_key = f"test.task3.{source_id}"
    try:
        with psycopg.connect(database_url) as connection:
            connection.execute(
                """
                INSERT INTO data_sources (id, name, adapter_key, source_type, is_enabled)
                VALUES (%s, 'Task 3 PostGIS regression', %s, 'official', true)
                """,
                (source_id, adapter_key),
            )
            connection.execute(
                """
                INSERT INTO evidence (
                    id, data_source_id, source_id, source_type, event_type,
                    title, summary, geom, confidence, privacy_level, properties
                ) VALUES
                (
                    %s, %s, 'outside-point', 'official', 'flood_potential',
                    'outside', 'outside',
                    ST_SetSRID(ST_MakePoint(120.00985, 23.0), 4326),
                    0.9, 'public', '{"evidence_scope":"context"}'::jsonb
                ),
                (
                    %s, %s, 'intersecting-polygon', 'official', 'flood_potential',
                    'polygon', 'polygon',
                    ST_GeomFromText(
                        'POLYGON((120.0085 22.9995,120.0095 22.9995,'
                        '120.0095 23.0005,120.0085 23.0005,120.0085 22.9995))',
                        4326
                    ),
                    0.9, 'public', '{"evidence_scope":"context"}'::jsonb
                )
                """,
                (outside_point_id, source_id, intersecting_polygon_id, source_id),
            )

        records = query_nearby_evidence(
            database_url=database_url,
            lat=23.0,
            lng=120.0,
            radius_m=1000,
        )
        assert str(outside_point_id) not in {item.id for item in records}
        polygon = next(item for item in records if item.id == str(intersecting_polygon_id))
        assert polygon.distance_to_query_m is not None
        assert polygon.distance_to_query_m <= 1000
        assert polygon.geometry is not None
        assert polygon.geometry["type"] in {"Polygon", "MultiPolygon"}

        with psycopg.connect(database_url) as connection:
            connection.execute(
                "UPDATE data_sources SET is_enabled = false WHERE id = %s", (source_id,)
            )
        assert (
            query_nearby_evidence(database_url=database_url, lat=23.0, lng=120.0, radius_m=1000)
            == ()
        )

        with psycopg.connect(database_url) as connection:
            connection.execute(
                "UPDATE data_sources SET is_enabled = true WHERE id = %s", (source_id,)
            )
        assert str(intersecting_polygon_id) in {
            item.id
            for item in query_nearby_evidence(
                database_url=database_url, lat=23.0, lng=120.0, radius_m=1000
            )
        }
    finally:
        with psycopg.connect(database_url) as connection:
            connection.execute("DELETE FROM evidence WHERE data_source_id = %s", (source_id,))
            connection.execute("DELETE FROM data_sources WHERE id = %s", (source_id,))


def test_generic_reader_isolates_malformed_limitations_roots() -> None:
    database_url = _database_url()
    source_id = uuid4()
    adapter_key = f"test.task5.generic-limitations.{source_id}"
    now = datetime.now(UTC)
    cases = (
        (uuid4(), ["array limitation"], ("array limitation",)),
        (uuid4(), "scalar limitation", ()),
        (uuid4(), {"dirty": True}, ()),
        (uuid4(), None, ()),
    )
    try:
        with psycopg.connect(database_url) as connection:
            _insert_migrated_source(
                connection,
                source_id=source_id,
                adapter_key=adapter_key,
            )
            for evidence_id, limitations, _expected in cases:
                _insert_migrated_evidence(
                    connection,
                    evidence_id=evidence_id,
                    source_id=source_id,
                    observed_at=now,
                    limitations=limitations,
                )

        records = query_nearby_evidence(
            database_url=database_url,
            lat=23.0,
            lng=120.0,
            radius_m=500,
            limit=100,
        )
        by_id = {record.id: record for record in records}
        assert {str(evidence_id) for evidence_id, *_rest in cases} <= set(by_id)
        for evidence_id, _stored, expected in cases:
            assert by_id[str(evidence_id)].limitations == expected
    finally:
        with psycopg.connect(database_url) as connection:
            connection.execute("DELETE FROM evidence WHERE data_source_id = %s", (source_id,))
            connection.execute("DELETE FROM data_sources WHERE id = %s", (source_id,))


def test_detail_reader_enforces_retention_source_and_privacy_authority() -> None:
    database_url = _database_url()
    enabled_source_id, disabled_source_id = uuid4(), uuid4()
    query_id = uuid4()
    active_assessment_id, expired_assessment_id, null_assessment_id = (
        uuid4(),
        uuid4(),
        uuid4(),
    )
    active_id, disabled_id, redacted_id, expired_id, null_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    now = datetime.now(UTC)
    assessment_ids = (
        active_assessment_id,
        expired_assessment_id,
        null_assessment_id,
    )
    evidence_ids = (active_id, disabled_id, redacted_id, expired_id, null_id)
    try:
        with psycopg.connect(database_url) as connection:
            _insert_migrated_source(
                connection,
                source_id=enabled_source_id,
                adapter_key=f"test.task5.detail-enabled.{enabled_source_id}",
            )
            _insert_migrated_source(
                connection,
                source_id=disabled_source_id,
                adapter_key=f"test.task5.detail-disabled.{disabled_source_id}",
                enabled=False,
            )
            connection.execute(
                """
                INSERT INTO location_queries (id, input_type, geom, radius_m)
                VALUES (
                    %s, 'map_click',
                    ST_SetSRID(ST_MakePoint(120.0, 23.0), 4326), 500
                )
                """,
                (query_id,),
            )
            for assessment_id, expires_at in (
                (active_assessment_id, now + timedelta(minutes=10)),
                (expired_assessment_id, now - timedelta(minutes=1)),
                (null_assessment_id, None),
            ):
                connection.execute(
                    """
                    INSERT INTO risk_assessments (
                        id, query_id, score_version, created_at, expires_at
                    ) VALUES (%s, %s, 'task5-privacy-red', %s, %s)
                    """,
                    (assessment_id, query_id, now, expires_at),
                )
            for evidence_id, source_id, privacy_level in (
                (active_id, enabled_source_id, "public"),
                (disabled_id, disabled_source_id, "public"),
                (redacted_id, enabled_source_id, "redacted"),
                (expired_id, enabled_source_id, "public"),
                (null_id, enabled_source_id, "public"),
            ):
                _insert_migrated_evidence(
                    connection,
                    evidence_id=evidence_id,
                    source_id=source_id,
                    observed_at=now,
                    limitations=["retained array limitation"],
                    event_type="flood_report",
                    privacy_level=privacy_level,
                )
            for assessment_id, linked_ids in (
                (active_assessment_id, (active_id, disabled_id, redacted_id)),
                (expired_assessment_id, (expired_id,)),
                (null_assessment_id, (null_id,)),
            ):
                for evidence_id in linked_ids:
                    connection.execute(
                        """
                        INSERT INTO risk_assessment_evidence (
                            risk_assessment_id, evidence_id
                        ) VALUES (%s, %s)
                        """,
                        (assessment_id, evidence_id),
                    )

        active_records = fetch_assessment_evidence(
            database_url=database_url,
            assessment_id=str(active_assessment_id),
        )
        assert [record.id for record in active_records] == [str(active_id)]
        assert active_records[0].limitations == ("retained array limitation",)
        assert fetch_assessment_evidence(
            database_url=database_url,
            assessment_id=str(expired_assessment_id),
        ) == ()
        assert fetch_assessment_evidence(
            database_url=database_url,
            assessment_id=str(null_assessment_id),
        ) == ()
    finally:
        with psycopg.connect(database_url) as connection:
            connection.execute(
                "DELETE FROM evidence WHERE id = ANY(%s::uuid[])",
                (list(evidence_ids),),
            )
            connection.execute(
                "DELETE FROM risk_assessments WHERE id = ANY(%s::uuid[])",
                (list(assessment_ids),),
            )
            connection.execute("DELETE FROM location_queries WHERE id = %s", (query_id,))
            connection.execute(
                "DELETE FROM data_sources WHERE id = ANY(%s::uuid[])",
                ([enabled_source_id, disabled_source_id],),
            )


def test_detail_reader_isolates_malformed_limitations_roots() -> None:
    database_url = _database_url()
    source_id, query_id, assessment_id = uuid4(), uuid4(), uuid4()
    now = datetime.now(UTC)
    cases = (
        (uuid4(), ["array limitation"], ("array limitation",)),
        (uuid4(), "scalar limitation", ()),
        (uuid4(), {"dirty": True}, ()),
        (uuid4(), None, ()),
    )
    try:
        with psycopg.connect(database_url) as connection:
            _insert_migrated_source(
                connection,
                source_id=source_id,
                adapter_key=f"test.task5.detail-limitations.{source_id}",
            )
            connection.execute(
                """
                INSERT INTO location_queries (id, input_type, geom, radius_m)
                VALUES (
                    %s, 'map_click',
                    ST_SetSRID(ST_MakePoint(120.0, 23.0), 4326), 500
                )
                """,
                (query_id,),
            )
            connection.execute(
                """
                INSERT INTO risk_assessments (
                    id, query_id, score_version, created_at, expires_at
                ) VALUES (%s, %s, 'task5-privacy-red', %s, %s)
                """,
                (assessment_id, query_id, now, now + timedelta(minutes=10)),
            )
            for evidence_id, limitations, _expected in cases:
                _insert_migrated_evidence(
                    connection,
                    evidence_id=evidence_id,
                    source_id=source_id,
                    observed_at=now,
                    limitations=limitations,
                    event_type="flood_report",
                )
                connection.execute(
                    """
                    INSERT INTO risk_assessment_evidence (
                        risk_assessment_id, evidence_id
                    ) VALUES (%s, %s)
                    """,
                    (assessment_id, evidence_id),
                )

        records = fetch_assessment_evidence(
            database_url=database_url,
            assessment_id=str(assessment_id),
        )
        by_id = {record.id: record for record in records}
        assert set(by_id) == {str(evidence_id) for evidence_id, *_rest in cases}
        for evidence_id, _stored, expected in cases:
            assert by_id[str(evidence_id)].limitations == expected
    finally:
        with psycopg.connect(database_url) as connection:
            connection.execute(
                "DELETE FROM evidence WHERE id = ANY(%s::uuid[])",
                ([evidence_id for evidence_id, *_rest in cases],),
            )
            connection.execute("DELETE FROM risk_assessments WHERE id = %s", (assessment_id,))
            connection.execute("DELETE FROM location_queries WHERE id = %s", (query_id,))
            connection.execute("DELETE FROM data_sources WHERE id = %s", (source_id,))


def test_warning_read_uses_area_geometry_active_window_and_not_station_lookback() -> None:
    database_url = _database_url()
    source_id = uuid4()
    adapter_key = f"test.task3.cap.{source_id}"
    active_id, expired_id, cancel_id = uuid4(), uuid4(), uuid4()
    now = datetime(2026, 8, 24, 4, 0, tzinfo=UTC)
    generation = now - timedelta(days=2, minutes=1)
    try:
        with psycopg.connect(database_url) as connection:
            connection.execute(
                """
                INSERT INTO data_sources (id, name, adapter_key, source_type, is_enabled)
                VALUES (%s, 'Task 3 CAP regression', %s, 'official', true)
                """,
                (source_id, adapter_key),
            )
            for evidence_id, station_id, message_type, active_until in (
                (active_id, "active", "Alert", now + timedelta(hours=1)),
                (expired_id, "expired", "Alert", now),
                (cancel_id, "cancel", "Cancel", now + timedelta(hours=1)),
            ):
                properties = {
                    "evidence_scope": "current",
                    "cap_status": "Actual",
                    "cap_message_type": message_type,
                    "active_from": (now - timedelta(days=2)).isoformat(),
                    "active_until": active_until.isoformat(),
                    "cap_sender": "sender@example.tw",
                    "cap_identifier": station_id,
                    "cap_sent": (now - timedelta(days=2)).isoformat(),
                    "admin_code": "67000000",
                    "ingestion_generation_started_at": generation.isoformat(),
                }
                connection.execute(
                    """
                    INSERT INTO evidence (
                        id, data_source_id, source_id, source_type, event_type,
                        title, summary, observed_at, geom, confidence,
                        privacy_level, properties
                    ) VALUES (
                        %s, %s, %s, 'official', 'flood_warning',
                        %s, %s, %s,
                        ST_GeomFromText(
                            'POLYGON((120.004 22.999,120.020 22.999,'
                            '120.020 23.001,120.004 23.001,120.004 22.999))',
                            4326
                        ),
                        0.9, 'public', %s::jsonb
                    )
                    """,
                    (
                        evidence_id,
                        source_id,
                        f"cap:{station_id}",
                        station_id,
                        station_id,
                        now - timedelta(days=2),
                        Jsonb(properties),
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO official_realtime_latest (
                        source_id, adapter_key, event_type, station_id,
                        observed_at, geom, evidence_id
                    ) VALUES (
                        %s, %s, 'flood_warning', %s, %s,
                        ST_SetSRID(ST_MakePoint(120.020, 23.0), 4326), %s
                    )
                    """,
                    (
                        f"cap:{station_id}",
                        adapter_key,
                        station_id,
                        now - timedelta(days=2),
                        evidence_id,
                    ),
                )

        records = query_nearby_latest_official(
            database_url=database_url,
            lat=23.0,
            lng=120.0,
            radius_m=500,
            as_of=now,
            observed_since=now - timedelta(hours=6),
        )
        assert [item.id for item in records] == [str(active_id)]
        assert records[0].distance_to_query_m is not None
        assert records[0].distance_to_query_m <= 500
        assert records[0].geometry is not None
        assert records[0].geometry["type"] == "Polygon"
        assert records[0].official_event_origin_key is not None
    finally:
        with psycopg.connect(database_url) as connection:
            connection.execute(
                "DELETE FROM official_realtime_latest WHERE adapter_key = %s",
                (adapter_key,),
            )
            connection.execute("DELETE FROM evidence WHERE data_source_id = %s", (source_id,))
            connection.execute("DELETE FROM data_sources WHERE id = %s", (source_id,))


_CONTEXT_LAT = 23.0478
_CONTEXT_LNG = 120.1842
_CONTEXT_AS_OF = datetime(2026, 8, 26, 2, 20, tzinfo=UTC)


def _context_row(
    *,
    source_key: str,
    source_id: str,
    observed_at: datetime,
    upstream_updated_at: datetime | None = None,
    incident_state: str = "active",
    event_type: str = "status_only",
    evidence_scope: str = "context",
    lng: float = _CONTEXT_LNG,
    lat: float = _CONTEXT_LAT,
    geom: bool = True,
    title: str | None = None,
) -> dict[str, object]:
    properties: dict[str, object] = {
        "evidence_scope": evidence_scope,
        "incident_state": incident_state,
    }
    if upstream_updated_at is not None:
        properties["upstream_updated_at"] = upstream_updated_at.isoformat()
    return {
        "id": uuid4(),
        "source_key": source_key,
        "source_id": source_id,
        "event_type": event_type,
        "title": title or source_id,
        "observed_at": observed_at,
        "lng": lng,
        "lat": lat,
        "geom": geom,
        "properties": properties,
    }


def _insert_context_rows(
    connection: psycopg.Connection,
    source_ids: dict[str, object],
    rows: list[dict[str, object]],
) -> None:
    for row in rows:
        connection.execute(
            """
            INSERT INTO evidence (
                id, data_source_id, source_id, source_type, event_type,
                title, summary, url, occurred_at, observed_at, geom,
                confidence, privacy_level, ingestion_status, properties
            ) VALUES (
                %s, %s, %s, 'official', %s,
                %s, 'summary', NULL, NULL, %s,
                CASE WHEN %s THEN ST_SetSRID(ST_MakePoint(%s, %s), 4326) ELSE NULL END,
                0.62, 'public', 'accepted', %s::jsonb
            )
            """,
            (
                row["id"],
                source_ids[row["source_key"]],
                row["source_id"],
                row["event_type"],
                row["title"],
                row["observed_at"],
                row["geom"],
                row["lng"],
                row["lat"],
                Jsonb(row["properties"]),
            ),
        )


def test_recent_context_reader_returns_only_latest_active_recent_in_radius_rows() -> None:
    database_url = _database_url()
    police_id, wra_id, rainfall_id = uuid4(), uuid4(), uuid4()

    with _isolated_schema(database_url) as isolated_url:
        _prepare_history_snapshot_schema(isolated_url)
        with psycopg.connect(isolated_url) as connection:
            connection.execute(
                """
                INSERT INTO data_sources (id, adapter_key, is_enabled) VALUES
                    (%s, 'official.npa.police_radio_traffic', true),
                    (%s, 'official.wra.flood_warning', true),
                    (%s, 'official.cwa.rainfall', true)
                """,
                (police_id, wra_id, rainfall_id),
            )
            source_ids = {
                "police": police_id,
                "wra": wra_id,
                "rainfall": rainfall_id,
            }
            _insert_context_rows(
                connection,
                source_ids,
                [
                    _context_row(
                        source_key="police",
                        source_id="UID-ACTIVE",
                        observed_at=_CONTEXT_AS_OF - timedelta(minutes=30),
                    ),
                    _context_row(
                        source_key="police",
                        source_id="UID-STALE",
                        observed_at=_CONTEXT_AS_OF - timedelta(hours=7),
                    ),
                    _context_row(
                        source_key="police",
                        source_id="UID-FUTURE",
                        observed_at=_CONTEXT_AS_OF + timedelta(minutes=30),
                    ),
                    _context_row(
                        source_key="police",
                        source_id="UID-RESOLVED",
                        observed_at=_CONTEXT_AS_OF - timedelta(minutes=40),
                        upstream_updated_at=_CONTEXT_AS_OF - timedelta(minutes=40),
                        incident_state="active",
                    ),
                    _context_row(
                        source_key="police",
                        source_id="UID-RESOLVED",
                        observed_at=_CONTEXT_AS_OF - timedelta(minutes=10),
                        upstream_updated_at=_CONTEXT_AS_OF - timedelta(minutes=10),
                        incident_state="resolved",
                    ),
                    _context_row(
                        source_key="police",
                        source_id="UID-DUP",
                        observed_at=_CONTEXT_AS_OF - timedelta(minutes=50),
                        upstream_updated_at=_CONTEXT_AS_OF - timedelta(minutes=50),
                        title="older version",
                    ),
                    _context_row(
                        source_key="police",
                        source_id="UID-DUP",
                        observed_at=_CONTEXT_AS_OF - timedelta(minutes=5),
                        upstream_updated_at=_CONTEXT_AS_OF - timedelta(minutes=5),
                        title="newest version",
                    ),
                    _context_row(
                        source_key="police",
                        source_id="UID-FAR",
                        observed_at=_CONTEXT_AS_OF - timedelta(minutes=15),
                        lng=_CONTEXT_LNG + 0.08,
                    ),
                    _context_row(
                        source_key="police",
                        source_id="UID-NO-GEOM",
                        observed_at=_CONTEXT_AS_OF - timedelta(minutes=15),
                        geom=False,
                    ),
                    _context_row(
                        source_key="police",
                        source_id="UID-WRONG-EVENT",
                        observed_at=_CONTEXT_AS_OF - timedelta(minutes=15),
                        event_type="flood_report",
                    ),
                    _context_row(
                        source_key="police",
                        source_id="UID-WRONG-SCOPE",
                        observed_at=_CONTEXT_AS_OF - timedelta(minutes=15),
                        evidence_scope="current",
                    ),
                    _context_row(
                        source_key="wra",
                        source_id="NewstFloodWarm.kml:FW-1",
                        observed_at=_CONTEXT_AS_OF - timedelta(minutes=20),
                    ),
                    _context_row(
                        source_key="rainfall",
                        source_id="RAIN-CTX",
                        observed_at=_CONTEXT_AS_OF - timedelta(minutes=20),
                    ),
                ],
            )
            connection.commit()

        records = query_nearby_recent_context(
            database_url=isolated_url,
            lat=_CONTEXT_LAT,
            lng=_CONTEXT_LNG,
            radius_m=800,
            as_of=_CONTEXT_AS_OF,
        )

        assert sorted(item.source_id for item in records) == [
            "NewstFloodWarm.kml:FW-1",
            "UID-ACTIVE",
            "UID-DUP",
        ]
        duplicate = next(item for item in records if item.source_id == "UID-DUP")
        assert duplicate.title == "newest version"
        assert {item.adapter_key for item in records} == {
            "official.npa.police_radio_traffic",
            "official.wra.flood_warning",
        }
        assert all(item.evidence_scope == "context" for item in records)
        assert all(item.event_type == "status_only" for item in records)
        assert all(item.geometry is not None for item in records)

        with psycopg.connect(isolated_url) as connection:
            connection.execute("UPDATE data_sources SET is_enabled = false")
            connection.commit()

        assert (
            query_nearby_recent_context(
                database_url=isolated_url,
                lat=_CONTEXT_LAT,
                lng=_CONTEXT_LNG,
                radius_m=800,
                as_of=_CONTEXT_AS_OF,
            )
            == ()
        )
