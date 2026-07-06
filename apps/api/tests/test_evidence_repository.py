from __future__ import annotations

from datetime import UTC, datetime, timezone

import psycopg
import pytest

from app.domain.layers import fetch_map_layer, fetch_map_layers
from app.domain.evidence.repository import (
    EvidenceUpsert,
    EvidenceRepositoryUnavailable,
    RiskAssessmentPersistence,
    fetch_evidence_by_ids,
    fetch_query_heat_snapshot,
    persist_risk_assessment,
    query_nearby_evidence,
    query_nearby_latest_official,
    query_nearby_realtime_coverage_rows,
    upsert_public_evidence,
)


def test_fetch_map_layers_reads_layer_metadata() -> None:
    updated_at = datetime(2026, 4, 30, 3, 0, tzinfo=timezone.utc)
    connection = _FakeConnection(
        rows=[
            {
                "layer_id": "flood-potential",
                "name": "Flood potential",
                "description": "Seeded layer",
                "category": "flood_potential",
                "status": "disabled",
                "minzoom": 8,
                "maxzoom": 18,
                "attribution": "Government open data",
                "tilejson_url": "/v1/layers/flood-potential/tilejson",
                "updated_at": updated_at,
                "metadata": {
                    "tiles": ["/v1/tiles/flood-potential/{z}/{x}/{y}.mvt"],
                    "bounds": [119.3, 21.8, 122.1, 25.4],
                },
            }
        ]
    )

    layers = fetch_map_layers(
        database_url="postgresql://example.test/flood",
        connection_factory=lambda: connection,
    )

    sql, params = connection.cursor_instance.executions[0]
    assert "FROM map_layers" in sql
    assert "ORDER BY" in sql
    assert params == ()
    assert layers[0].id == "flood-potential"
    assert layers[0].status == "disabled"
    assert layers[0].metadata["bounds"] == [119.3, 21.8, 122.1, 25.4]


def test_fetch_map_layer_filters_by_layer_id() -> None:
    connection = _FakeConnection(
        rows=[
            {
                "layer_id": "query-heat",
                "name": "Query heat",
                "description": None,
                "category": "query_heat",
                "status": "disabled",
                "minzoom": 8,
                "maxzoom": 14,
                "attribution": None,
                "tilejson_url": "/v1/layers/query-heat/tilejson",
                "updated_at": None,
                "metadata": '{"tiles":["https://tiles.local/query-heat/{z}/{x}/{y}.pbf"]}',
            }
        ]
    )

    layer = fetch_map_layer(
        database_url="postgresql://example.test/flood",
        layer_id="query-heat",
        connection_factory=lambda: connection,
    )

    sql, params = connection.cursor_instance.executions[0]
    assert "WHERE layer_id = %s" in sql
    assert params == ("query-heat",)
    assert layer is not None
    assert layer.id == "query-heat"
    assert layer.metadata["tiles"] == ["https://tiles.local/query-heat/{z}/{x}/{y}.pbf"]


def test_fetch_query_heat_snapshot_buckets_nearby_location_queries() -> None:
    connection = _FakeConnection(
        row={
            "query_count": 17,
            "unique_approx_count": 6,
            "updated_at": datetime(2026, 4, 30, 3, 0, tzinfo=timezone.utc),
        }
    )

    snapshot = fetch_query_heat_snapshot(
        database_url="postgresql://example.test/flood",
        lat=25.033,
        lng=121.5654,
        radius_m=500,
        connection_factory=lambda: connection,
    )

    timeout_sql, timeout_params = connection.cursor_instance.executions[0]
    sql, params = connection.cursor_instance.executions[1]
    assert timeout_sql == "SELECT set_config('statement_timeout', %s, true)"
    assert timeout_params == ("1200ms",)
    assert "FROM location_queries lq" in sql
    assert "JOIN risk_assessments ra ON ra.query_id = lq.id" in sql
    assert "lq.geom && ST_Expand(qp.geom, qp.degree_radius)" in sql
    assert "ST_DWithin" in sql
    assert params == (121.5654, 25.033, 121.5654, 25.033, 500, "7 days", 500)
    assert snapshot.period == "P7D"
    assert snapshot.query_count == 17
    assert snapshot.query_count_bucket == "10-49"
    assert snapshot.unique_approx_count_bucket == "1-9"


def test_query_nearby_evidence_uses_point_on_surface_for_non_point_geometry() -> None:
    connection = _FakeConnection(rows=[])

    records = query_nearby_evidence(
        database_url="postgresql://example.test/flood",
        lat=25.033,
        lng=121.5654,
        radius_m=500,
        connection_factory=lambda: connection,
    )

    sql, params = connection.cursor_instance.executions[0]
    assert records == ()
    assert "ST_PointOnSurface(c.geom::geometry)" in sql
    assert "ST_AsGeoJSON(ST_PointOnSurface(c.geom::geometry)) AS geometry" in sql
    assert "candidate_rows AS" in sql
    assert "e.geom && ST_Expand(qp.geom, qp.degree_radius)" in sql
    assert "event_type IN ('rainfall', 'water_level')" in sql
    assert "MATERIALIZED" not in sql
    assert "FROM recent_rainfall" not in sql
    assert "FROM recent_water_level" not in sql
    # Without relevance arguments the realtime relevance collapses to the radius.
    assert params == (
        121.5654,
        25.033,
        121.5654,
        25.033,
        500,
        500,
        500,
        500,
        50,
        500,
        None,
        None,
        1,
        500,
        None,
        None,
        1,
        50,
    )


def test_query_nearby_evidence_extends_radius_for_realtime_stations() -> None:
    connection = _FakeConnection(rows=[])
    realtime_since = datetime(2026, 6, 16, 5, 0, tzinfo=timezone.utc)

    query_nearby_evidence(
        database_url="postgresql://example.test/flood",
        lat=25.033,
        lng=121.5654,
        radius_m=500,
        rainfall_relevance_m=5000,
        water_relevance_m=3000,
        official_realtime_since=realtime_since,
        connection_factory=lambda: connection,
    )

    sql, params = connection.cursor_instance.executions[0]
    assert "event_type = 'rainfall'" in sql
    assert "event_type = 'water_level'" in sql
    assert "observed_at >= %s::timestamptz" in sql
    assert "MATERIALIZED" not in sql
    # bbox uses the max relevance (5000); radius=500, rainfall=5000, water=3000.
    assert params == (
        121.5654,
        25.033,
        121.5654,
        25.033,
        500,
        5000,
        3000,
        500,
        50,
        5000,
        realtime_since,
        realtime_since,
        1,
        3000,
        realtime_since,
        realtime_since,
        1,
        50,
    )


def test_query_nearby_realtime_coverage_rows_counts_radius_buckets() -> None:
    connection = _FakeConnection(
        rows=[
            {
                "adapter_key": "local.kaohsiung.rainfall",
                "source_id": "local.kaohsiung.rainfall:ST-001",
                "event_type": "rainfall",
                "station_id": "ST-001",
                "observed_at": datetime(2026, 6, 29, 11, 55, tzinfo=UTC),
                "ingested_at": datetime(2026, 6, 29, 11, 56, tzinfo=UTC),
                "distance_to_query_m": 230.4,
                "freshness_state": "fresh",
            }
        ]
    )

    rows = query_nearby_realtime_coverage_rows(
        database_url="postgresql://example",
        lat=22.6273,
        lng=120.3014,
        observed_since=datetime(2026, 6, 29, 9, 0, tzinfo=UTC),
        connection_factory=lambda: connection,
    )

    assert rows[0].adapter_key == "local.kaohsiung.rainfall"
    assert rows[0].distance_to_query_m == 230.4
    query_call = next(
        (item for item in connection.cursor_instance.executions if "official_realtime_latest" in item[0]),
        None,
    )
    assert query_call is not None
    sql, params = query_call
    assert "official_realtime_latest" in sql
    assert "ST_DWithin" in sql
    assert 5000 in params


def test_query_nearby_realtime_coverage_rows_falls_back_to_official_evidence_when_latest_empty() -> None:
    observed_since = datetime(2026, 6, 29, 9, 0, tzinfo=UTC)
    latest_connection = _FakeConnection(rows=[])
    fallback_connection = _FakeConnection(
        rows=[
            {
                "adapter_key": "official.cwa.rainfall",
                "source_id": "cwa-rainfall:C0A520:2026-06-29T11:55:00Z",
                "event_type": "rainfall",
                "station_id": "cwa-rainfall:C0A520:2026-06-29T11:55:00Z",
                "observed_at": datetime(2026, 6, 29, 11, 55, tzinfo=UTC),
                "ingested_at": datetime(2026, 6, 29, 11, 56, tzinfo=UTC),
                "distance_to_query_m": 1219.4,
                "freshness_state": "fresh",
            }
        ]
    )
    connections = iter([latest_connection, fallback_connection])

    rows = query_nearby_realtime_coverage_rows(
        database_url="postgresql://example",
        lat=23.01929,
        lng=120.18726,
        observed_since=observed_since,
        connection_factory=lambda: next(connections),
    )

    assert len(rows) == 1
    assert rows[0].adapter_key == "official.cwa.rainfall"
    assert rows[0].event_type == "rainfall"
    assert rows[0].station_id == "C0A520"
    assert rows[0].distance_to_query_m == 1219.4
    latest_sql, _latest_params = next(
        item
        for item in latest_connection.cursor_instance.executions
        if "official_realtime_latest" in item[0]
    )
    fallback_sql, fallback_params = next(
        item
        for item in fallback_connection.cursor_instance.executions
        if "FROM evidence e" in item[0]
    )
    assert "FROM official_realtime_latest latest" in latest_sql
    assert "FROM evidence e" in fallback_sql
    assert "JOIN data_sources ds" in fallback_sql
    assert "e.source_type = 'official'" in fallback_sql
    assert "e.event_type IN" in fallback_sql
    assert "'rainfall'" in fallback_sql
    assert "'water_level'" in fallback_sql
    assert "'flood_sensor'" not in fallback_sql
    assert observed_since in fallback_params


def test_query_nearby_realtime_coverage_rows_falls_back_when_table_missing() -> None:
    connection = _FakeConnection(
        rows=[],
        execute_side_effects=[_undefined_table_error(table_name="official_realtime_latest")],
    )

    rows = query_nearby_realtime_coverage_rows(
        database_url="postgresql://example.test/flood",
        lat=22.6273,
        lng=120.3014,
        connection_factory=lambda: connection,
    )

    assert rows == ()

def test_query_nearby_latest_official_uses_flood_depth_radius() -> None:

    connection = _FakeConnection(rows=[])

    records = query_nearby_latest_official(
        database_url="postgresql://example.test/flood",
        lat=25.033,
        lng=121.5654,
        connection_factory=lambda: connection,
    )

    sql, params = connection.cursor_instance.executions[0]
    assert records == ()
    assert "FROM official_realtime_latest latest" in sql
    assert "event_type = 'flood_report'" in sql
    assert "event_type = 'flood_warning'" in sql
    assert "flood_depth_degree" in sql
    assert params == (
        121.5654,
        25.033,
        121.5654,
        25.033,
        10000,
        3000,
        1000,
        10000,
        50,
    )


def test_query_nearby_latest_official_filters_rows_by_observed_since() -> None:
    connection = _FakeConnection(rows=[])
    observed_since = datetime(2026, 6, 16, 2, 0, tzinfo=timezone.utc)

    records = query_nearby_latest_official(
        database_url="postgresql://example.test/flood",
        lat=25.033,
        lng=121.5654,
        observed_since=observed_since,
        connection_factory=lambda: connection,
    )

    sql, params = connection.cursor_instance.executions[0]
    assert records == ()
    assert "latest.observed_at >= %s::timestamptz" in sql
    assert params == (
        121.5654,
        25.033,
        121.5654,
        25.033,
        10000,
        3000,
        1000,
        10000,
        observed_since,
        50,
    )


def test_query_nearby_latest_official_falls_back_when_table_missing() -> None:
    connection = _FakeConnection(
        rows=[],
        execute_side_effects=[_undefined_table_error(table_name="official_realtime_latest")],
    )

    records = query_nearby_latest_official(
        database_url="postgresql://example.test/flood",
        lat=25.033,
        lng=121.5654,
        connection_factory=lambda: connection,
    )

    assert records == ()


def test_query_nearby_latest_official_raises_when_other_relation_missing() -> None:
    connection = _FakeConnection(
        rows=[],
        execute_side_effects=[_undefined_table_error(table_name="evidence")],
    )

    with pytest.raises(EvidenceRepositoryUnavailable, match="evidence"):
        query_nearby_latest_official(
            database_url="postgresql://example.test/flood",
            lat=25.033,
            lng=121.5654,
            connection_factory=lambda: connection,
        )


def test_query_nearby_latest_official_decodes_latest_row_metrics() -> None:
    observed_at = datetime(2026, 6, 16, 5, 0, tzinfo=timezone.utc)
    connection = _FakeConnection(
        rows=[
            {
                "id": "latest-rainfall-1",
                "source_id": "cwa-rainfall:C0A520:2026-06-16T05:00:00+00:00",
                "source_type": "official",
                "event_type": "rainfall",
                "title": "官方最新雨量站觀測",
                "summary": "官方最新雨量站觀測值。",
                "url": "https://example.test/latest",
                "occurred_at": None,
                "observed_at": observed_at,
                "ingested_at": observed_at,
                "lat": 25.033,
                "lng": 121.5654,
                "geometry": '{"type":"Point","coordinates":[121.5654,25.033]}',
                "distance_to_query_m": 88.0,
                "confidence": 0.91,
                "freshness_score": 0.87,
                "source_weight": 1.0,
                "privacy_level": "public",
                "raw_ref": "official-realtime-latest:official.cwa.rainfall:rainfall:C0A520",
                "rainfall_mm_1h": 42.5,
                "water_level_m": 1.75,
                "warning_level_m": 2.25,
                "flood_depth_cm": 18.0,
                "realtime_risk_factor": 0.6,
            }
        ]
    )

    records = query_nearby_latest_official(
        database_url="postgresql://example.test/flood",
        lat=25.033,
        lng=121.5654,
        connection_factory=lambda: connection,
    )

    assert len(records) == 1
    assert records[0].rainfall_mm_1h == 42.5
    assert records[0].water_level_m == 1.75
    assert records[0].warning_level_m == 2.25
    assert records[0].flood_depth_cm == 18.0
    assert records[0].realtime_risk_factor == 0.6


def test_fetch_evidence_by_ids_preserves_requested_order() -> None:
    ingested_at = datetime(2026, 5, 12, 2, 0, tzinfo=timezone.utc)
    connection = _FakeConnection(
        rows=[
            {
                "id": "22222222-2222-4222-8222-222222222222",
                "source_id": "official:flood-potential",
                "source_type": "official",
                "event_type": "flood_potential",
                "title": "Official profile top evidence",
                "summary": "Representative official profile evidence.",
                "url": None,
                "occurred_at": None,
                "observed_at": ingested_at,
                "ingested_at": ingested_at,
                "lat": 22.65646,
                "lng": 120.32574,
                "geometry": '{"type":"Point","coordinates":[120.32574,22.65646]}',
                "distance_to_query_m": 88.0,
                "confidence": 0.86,
                "freshness_score": 0.72,
                "source_weight": 1.0,
                "privacy_level": "public",
                "raw_ref": "profile-top:official",
            },
            {
                "id": "11111111-1111-4111-8111-111111111111",
                "source_id": "news:flood-report",
                "source_type": "news",
                "event_type": "flood_report",
                "title": "News profile top evidence",
                "summary": "Representative news profile evidence.",
                "url": "https://example.test/news",
                "occurred_at": ingested_at,
                "observed_at": ingested_at,
                "ingested_at": ingested_at,
                "lat": 22.65646,
                "lng": 120.32574,
                "geometry": '{"type":"Point","coordinates":[120.32574,22.65646]}',
                "distance_to_query_m": 90.0,
                "confidence": 0.9,
                "freshness_score": 0.8,
                "source_weight": 0.72,
                "privacy_level": "public",
                "raw_ref": "profile-top:news",
            },
        ]
    )

    records = fetch_evidence_by_ids(
        database_url="postgresql://example.test/flood",
        evidence_ids=(
            "22222222-2222-4222-8222-222222222222",
            "11111111-1111-4111-8111-111111111111",
        ),
        connection_factory=lambda: connection,
    )

    sql, params = connection.cursor_instance.executions[0]
    assert "WITH requested AS" in sql
    assert "WITH ORDINALITY" in sql
    assert "ORDER BY requested.ordinality ASC" in sql
    assert params == (
        [
            "22222222-2222-4222-8222-222222222222",
            "11111111-1111-4111-8111-111111111111",
        ],
    )
    assert [record.id for record in records] == [
        "22222222-2222-4222-8222-222222222222",
        "11111111-1111-4111-8111-111111111111",
    ]
    assert records[0].geometry == {"type": "Point", "coordinates": [120.32574, 22.65646]}


def test_upsert_public_evidence_writes_point_geometry_and_metadata() -> None:
    ingested_at = datetime(2026, 5, 4, 3, 0, tzinfo=timezone.utc)
    connection = _FakeConnection(
        row={
            "id": "f442ec3f-f013-58d2-8fcb-93f62db8d51c",
            "source_id": "gdelt-on-demand:test",
            "source_type": "news",
            "event_type": "flood_report",
            "title": "高雄岡山嘉新東路豪雨淹水",
            "summary": "公開新聞索引標題與查詢地點及淹水關鍵字相符。",
            "url": "https://example.test/news",
            "occurred_at": ingested_at,
            "observed_at": ingested_at,
            "ingested_at": ingested_at,
            "lat": 22.8052,
            "lng": 120.3034,
            "geometry": '{"type":"Point","coordinates":[120.3034,22.8052]}',
            "distance_to_query_m": 0,
            "confidence": 0.9,
            "freshness_score": 0.95,
            "source_weight": 1.0,
            "privacy_level": "public",
            "raw_ref": "gdelt-doc:test",
        }
    )

    records = upsert_public_evidence(
        database_url="postgresql://example.test/flood",
        records=(
            EvidenceUpsert(
                id="f442ec3f-f013-58d2-8fcb-93f62db8d51c",
                adapter_key="news.public_web.gdelt_backfill",
                source_id="gdelt-on-demand:test",
                source_type="news",
                event_type="flood_report",
                title="高雄岡山嘉新東路豪雨淹水",
                summary="公開新聞索引標題與查詢地點及淹水關鍵字相符。",
                url="https://example.test/news",
                occurred_at=ingested_at,
                observed_at=ingested_at,
                ingested_at=ingested_at,
                lat=22.8052,
                lng=120.3034,
                distance_to_query_m=0.0,
                confidence=0.9,
                freshness_score=0.95,
                source_weight=1.0,
                privacy_level="public",
                raw_ref="gdelt-doc:test",
                properties={"full_text_stored": False},
            ),
        ),
        connection_factory=lambda: connection,
    )

    sql, params = connection.cursor_instance.executions[0]
    assert "INSERT INTO evidence" in sql
    assert "ST_SetSRID(ST_MakePoint" in sql
    assert "ON CONFLICT ON CONSTRAINT evidence_source_raw_ref_unique" in sql
    assert params[0] == "f442ec3f-f013-58d2-8fcb-93f62db8d51c"
    assert params[1] == "news.public_web.gdelt_backfill"
    assert params[11:13] == (120.3034, 22.8052)
    assert records[0].source_id == "gdelt-on-demand:test"
    assert records[0].geometry == {"type": "Point", "coordinates": [120.3034, 22.8052]}


def test_persist_risk_assessment_inserts_query_assessment_and_links_evidence() -> None:
    connection = _FakeConnection()
    created_at = datetime(2026, 4, 30, 3, 0, tzinfo=timezone.utc)
    expires_at = datetime(2026, 4, 30, 3, 10, tzinfo=timezone.utc)

    persist_risk_assessment(
        database_url="postgresql://example.test/flood",
        assessment=RiskAssessmentPersistence(
            assessment_id="d315d0e6-9c1e-475a-9118-f299d12d5c62",
            lat=25.033,
            lng=121.5654,
            radius_m=500,
            score_version="risk-v0.1.0",
            realtime_score=12.5,
            historical_score=34.5,
            confidence_score=0.67,
            realtime_level="雿?",
            historical_level="擃?",
            explanation={"summary": "Stored assessment"},
            data_freshness=[{"source_id": "db-evidence", "health_status": "healthy"}],
            result_snapshot={
                "assessment_id": "d315d0e6-9c1e-475a-9118-f299d12d5c62",
                "location": {"lat": 25.033, "lng": 121.5654},
                "radius_m": 500,
                "score_version": "risk-v0.1.0",
            },
            evidence_ids=("b3f22a36-7316-4e2a-92b6-c6f6443c8528",),
            created_at=created_at,
            expires_at=expires_at,
        ),
        connection_factory=lambda: connection,
    )

    sql, params = connection.cursor_instance.executions[0]
    assert "INSERT INTO location_queries" in sql
    assert "lat" in sql
    assert "lng" in sql
    assert "INSERT INTO risk_assessments" in sql
    assert "risk_level" in sql
    assert "result_snapshot" in sql
    assert "INSERT INTO risk_assessment_evidence" in sql
    assert "JOIN evidence ON evidence.id = ANY" in sql
    # ADR-0006: raw query text must never be stored and coordinates must be
    # coarsened to the ~1 km privacy bucket before hitting the database.
    assert params[0:9] == (
        None,
        25.03,
        121.57,
        121.57,
        25.03,
        500,
        "25.03,121.57",
        "25.03,121.57",
        created_at,
    )
    assert params[9] == "d315d0e6-9c1e-475a-9118-f299d12d5c62"
    assert params[14:17] == ("low", "high", "high")
    assert params[-1] == ["b3f22a36-7316-4e2a-92b6-c6f6443c8528"]


class _FakeConnection:
    def __init__(
        self,
        *,
        row: dict[str, object] | None = None,
        rows: list[dict[str, object]] | None = None,
        execute_side_effects: list[BaseException] | None = None,
    ) -> None:
        self.cursor_instance = _FakeCursor(
            row=row,
            rows=rows,
            execute_side_effects=execute_side_effects,
        )

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def cursor(self) -> "_FakeCursor":
        return self.cursor_instance


class _FakeCursor:
    def __init__(
        self,
        *,
        row: dict[str, object] | None = None,
        rows: list[dict[str, object]] | None = None,
        execute_side_effects: list[BaseException] | None = None,
    ) -> None:
        self._row = row
        self._rows = rows
        self._execute_side_effects = list(execute_side_effects or [])
        self.executions: list[tuple[str, tuple[object, ...]]] = []

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        self.executions.append((sql, params))
        if self._execute_side_effects:
            raise self._execute_side_effects.pop(0)

    def fetchone(self) -> dict[str, object]:
        assert self._row is not None
        return self._row

    def fetchall(self) -> list[dict[str, object]]:
        assert self._rows is not None
        return self._rows


class _Diagnostic:
    def __init__(self, table_name: str | None) -> None:
        self.table_name = table_name


class _UndefinedTableWithDiag(psycopg.errors.UndefinedTable):
    def __init__(self, message: str, *, table_name: str | None) -> None:
        super().__init__(message)
        self._diag = _Diagnostic(table_name)

    @property
    def diag(self) -> _Diagnostic:
        return self._diag


def _undefined_table_error(*, table_name: str | None, message: str | None = None) -> psycopg.errors.UndefinedTable:
    relation = table_name or "unknown"
    return _UndefinedTableWithDiag(
        message or f'relation "{relation}" does not exist',
        table_name=table_name,
    )
