from __future__ import annotations

from datetime import datetime, timezone

from app.domain.layers import fetch_map_layer, fetch_map_layers
from app.domain.evidence.repository import (
    EvidenceUpsert,
    RiskAssessmentPersistence,
    fetch_query_heat_snapshot,
    persist_risk_assessment,
    query_nearby_evidence,
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
                    "tiles": [
                        "https://tiles.placeholder.flood-risk.local/"
                        "flood-potential/{z}/{x}/{y}.pbf"
                    ],
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

    sql, params = connection.cursor_instance.executions[0]
    assert "FROM location_queries lq" in sql
    assert "JOIN risk_assessments ra ON ra.query_id = lq.id" in sql
    assert "ST_DWithin" in sql
    assert params == (121.5654, 25.033, "7 days", 500)
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
    assert "ST_PointOnSurface(e.geom::geometry)" in sql
    assert params == (121.5654, 25.033, 500, 50)


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
            location_text="Taipei 101",
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
    assert params[0:9] == (
        "Taipei 101",
        25.033,
        121.5654,
        121.5654,
        25.033,
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
    ) -> None:
        self.cursor_instance = _FakeCursor(row=row, rows=rows)

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
    ) -> None:
        self._row = row
        self._rows = rows
        self.executions: list[tuple[str, tuple[object, ...]]] = []

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        self.executions.append((sql, params))

    def fetchone(self) -> dict[str, object]:
        assert self._row is not None
        return self._row

    def fetchall(self) -> list[dict[str, object]]:
        assert self._rows is not None
        return self._rows
