from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from app.domain.evidence import query_nearby_evidence, query_nearby_latest_official


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
