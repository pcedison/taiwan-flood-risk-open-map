from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from app.pipelines.promotion import (
    EvidencePromotionPayload,
    PostgresEvidencePromotionWriter,
    PromotionCandidate,
    build_evidence_promotion_payload,
    promote_accepted_staging,
)


OCCURRED_AT = datetime(2026, 4, 28, 8, 30, tzinfo=timezone.utc)
OBSERVED_AT = datetime(2026, 4, 28, 10, 0, tzinfo=timezone.utc)


def test_build_evidence_promotion_payload_maps_accepted_staging_row() -> None:
    candidate = _candidate()

    payload = build_evidence_promotion_payload(candidate)

    assert payload.source_id == "sample-news-001"
    assert payload.adapter_key == "news.public_web.sample"
    assert payload.source_type == "news"
    assert payload.event_type == "flood_report"
    assert payload.raw_ref == "raw/news-public-web/sample.json"
    assert payload.properties["location_text"] == "Riverside District"
    assert payload.properties["staging_evidence_id"] == "staging-id"
    assert payload.properties["raw_snapshot_id"] == "raw-snapshot-id"


def test_build_evidence_promotion_payload_rejects_non_accepted_staging_row() -> None:
    candidate = _candidate(validation_status="rejected")

    try:
        build_evidence_promotion_payload(candidate)
    except ValueError as exc:
        assert str(exc) == "only accepted staging evidence can be promoted"
    else:
        raise AssertionError("expected ValueError")


def test_promote_accepted_staging_uses_writer_protocol() -> None:
    writer = _MemoryPromotionWriter([_candidate()])

    result = promote_accepted_staging(
        writer,
        limit=10,
        adapter_keys=("news.public_web.sample",),
    )

    assert result.promoted == 1
    assert result.evidence_ids == ("evidence-1",)
    assert writer.requested_limit == 10
    assert writer.requested_adapter_keys == ("news.public_web.sample",)
    assert len(writer.payloads) == 1
    assert writer.payloads[0].source_id == "sample-news-001"


def test_promote_accepted_staging_deduplicates_duplicate_source_raw_ref_candidates() -> None:
    writer = _MemoryPromotionWriter(
        [
            _candidate(staging_evidence_id="staging-id-1"),
            _candidate(staging_evidence_id="staging-id-2"),
            _candidate(
                staging_evidence_id="staging-id-3",
                source_id="sample-news-002",
                raw_ref=None,
            ),
            _candidate(
                staging_evidence_id="staging-id-4",
                source_id="sample-news-002",
                raw_ref=None,
            ),
        ]
    )

    result = promote_accepted_staging(writer)

    assert result.promoted == 2
    assert result.evidence_ids == ("evidence-1", "evidence-2")
    assert [payload.properties["staging_evidence_id"] for payload in writer.payloads] == [
        "staging-id-1",
        "staging-id-3",
    ]


def test_postgres_promotion_writer_fetches_accepted_rows_and_inserts_evidence() -> None:
    connection = _FakeConnection(
        rows=[
            (
                "staging-id",
                "raw-snapshot-id",
                "raw/news-public-web/sample.json",
                "data-source-id",
                "sample-news-001",
                "news",
                "flood_report",
                "Heavy rain reported near riverside district",
                "Public report describes street flooding near the riverside district.",
                "https://example.test/news/flood-001",
                OCCURRED_AT,
                OBSERVED_AT,
                0.72,
                "accepted",
                json.dumps(
                    {
                        "adapter_key": "news.public_web.sample",
                        "location_text": "Riverside District",
                    }
                ),
            )
        ],
        evidence_id="evidence-id",
    )
    writer = PostgresEvidencePromotionWriter(connection_factory=lambda: connection)

    candidates = writer.fetch_accepted_staging(limit=5)
    evidence_id = writer.write_evidence(build_evidence_promotion_payload(candidates[0]))

    assert evidence_id == "evidence-id"
    assert connection.committed is True
    assert len(connection.cursor_instance.executions) == 2
    select_sql, select_params = connection.cursor_instance.executions[0]
    insert_sql, insert_params = connection.cursor_instance.executions[1]
    assert "FROM staging_evidence se" in select_sql
    assert "SELECT DISTINCT ON (se.source_id, rs.raw_ref)" in select_sql
    assert "LEFT JOIN data_sources ds" in select_sql
    assert "COALESCE(se.data_source_id, rs.data_source_id, ds.id) AS data_source_id" in select_sql
    assert "se.validation_status = 'accepted'" in select_sql
    assert "NOT EXISTS" in select_sql
    assert select_params == (5,)
    assert "INSERT INTO evidence" in insert_sql
    assert "ON CONFLICT ON CONSTRAINT evidence_source_raw_ref_unique" in insert_sql
    assert "DO UPDATE SET" in insert_sql
    assert "updated_at = evidence.updated_at" in insert_sql
    assert "ST_GeomFromGeoJSON" in insert_sql
    assert "SELECT id FROM data_sources WHERE adapter_key = %s" in insert_sql
    assert insert_params[1] == "news.public_web.sample"
    assert insert_params[2] == "sample-news-001"
    assert insert_params[11] is None
    assert insert_params[12] is None
    assert insert_params[13] == "raw/news-public-web/sample.json"
    properties = json.loads(str(insert_params[14]))
    assert properties["location_text"] == "Riverside District"
    assert properties["staging_evidence_id"] == "staging-id"


def test_postgres_promotion_writer_inserts_geojson_geometry_when_present() -> None:
    connection = _FakeConnection(rows=[], evidence_id="evidence-id")
    writer = PostgresEvidencePromotionWriter(connection_factory=lambda: connection)
    payload = build_evidence_promotion_payload(
        _candidate(
            payload={
                "adapter_key": "official.flood_potential.geojson",
                "location_payload": {
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [121.50, 25.03],
                                [121.51, 25.03],
                                [121.51, 25.04],
                                [121.50, 25.04],
                                [121.50, 25.03],
                            ]
                        ],
                    }
                },
            }
        )
    )

    evidence_id = writer.write_evidence(payload)

    assert evidence_id == "evidence-id"
    insert_params = connection.cursor_instance.executions[0][1]
    assert json.loads(str(insert_params[11]))["type"] == "Polygon"
    assert insert_params[11] == insert_params[12]


def test_write_evidence_upserts_official_realtime_latest_for_flood_depth() -> None:
    connection = _FakeConnection(rows=[], evidence_id="evidence-id")
    writer = PostgresEvidencePromotionWriter(connection_factory=lambda: connection)
    payload = EvidencePromotionPayload(
        data_source_id="data-source-id",
        adapter_key="official.civil_iot.flood_sensor",
        source_id="FS-001:2026-06-15T03:00:00+00:00",
        source_type="official",
        event_type="flood_report",
        title="Flood sensor report",
        summary="Observed flood depth 18 cm",
        url="https://example.test/flood-sensor/FS-001",
        occurred_at=OCCURRED_AT,
        observed_at=OBSERVED_AT,
        confidence=0.91,
        raw_ref="raw/civil-iot/flood-sensor/fs-001.json",
        properties={
            "adapter_key": "official.civil_iot.flood_sensor",
            "station_name": "Zhongzheng Road Sensor",
            "authority": "Water Resources Agency",
            "source_url": "https://example.test/flood-sensor/FS-001",
            "flood_depth_cm": 18.0,
            "location_payload": {
                "geometry": {"type": "Point", "coordinates": [120.2, 23.0]}
            },
        },
    )

    evidence_id = writer.write_evidence(payload)

    assert evidence_id == "evidence-id"
    assert connection.committed is True
    assert len(connection.cursor_instance.executions) == 2
    latest_sql, latest_params = connection.cursor_instance.executions[1]
    assert "INSERT INTO official_realtime_latest" in latest_sql
    assert "WHERE EXCLUDED.observed_at >= official_realtime_latest.observed_at" in latest_sql
    assert latest_params[0] == "FS-001:2026-06-15T03:00:00+00:00"
    assert latest_params[1] == "official.civil_iot.flood_sensor"
    assert latest_params[2] == "flood_report"
    assert latest_params[3] == "FS-001"
    assert latest_params[4] == "Zhongzheng Road Sensor"
    assert latest_params[5] == "Water Resources Agency"
    assert latest_params[6] == OBSERVED_AT
    assert json.loads(str(latest_params[7])) == {"type": "Point", "coordinates": [120.2, 23.0]}
    assert latest_params[12] == 18.0
    assert latest_params[16] == 0.5
    assert latest_params[17] == "evidence-id"


def test_write_evidence_skips_latest_when_station_id_missing() -> None:
    connection = _FakeConnection(rows=[], evidence_id="evidence-id")
    writer = PostgresEvidencePromotionWriter(connection_factory=lambda: connection)
    payload = EvidencePromotionPayload(
        data_source_id="data-source-id",
        adapter_key="official.ncdr.cap",
        source_id="official.ncdr.cap",
        source_type="official",
        event_type="flood_warning",
        title="Flood warning",
        summary="Regional warning",
        url="https://example.test/cap/flood-warning",
        occurred_at=OCCURRED_AT,
        observed_at=OBSERVED_AT,
        confidence=0.95,
        raw_ref="raw/ncdr/cap/flood-warning.xml",
        properties={
            "adapter_key": "official.ncdr.cap",
            "authority": "NCDR",
            "location_payload": {
                "geometry": {"type": "Point", "coordinates": [121.5, 25.0]}
            },
        },
    )

    evidence_id = writer.write_evidence(payload)

    assert evidence_id == "evidence-id"
    assert connection.committed is True
    assert len(connection.cursor_instance.executions) == 1
    assert "INSERT INTO evidence" in connection.cursor_instance.executions[0][0]


def test_write_evidence_does_not_overwrite_newer_latest_with_older_observation() -> None:
    connection = _FakeConnection(rows=[], evidence_id="evidence-id")
    writer = PostgresEvidencePromotionWriter(connection_factory=lambda: connection)
    payload = EvidencePromotionPayload(
        data_source_id="data-source-id",
        adapter_key="official.wra.water_level",
        source_id="WRA-001:2026-04-28T09:50:00+00:00",
        source_type="official",
        event_type="water_level",
        title="Water level observation",
        summary="Observed water level 3.2 m",
        url="https://example.test/wra/WRA-001",
        occurred_at=OCCURRED_AT,
        observed_at=datetime(2026, 4, 28, 9, 50, tzinfo=timezone.utc),
        confidence=0.88,
        raw_ref="raw/wra/water-level/wra-001.json",
        properties={
            "adapter_key": "official.wra.water_level",
            "station_id": "WRA-001",
            "station_name": "Dahan Bridge",
            "authority": "Water Resources Agency",
            "water_level_m": 3.2,
            "warning_level_m": 4.0,
            "location_payload": {
                "geometry": {"type": "Point", "coordinates": [121.48, 25.03]}
            },
        },
    )

    writer.write_evidence(payload)

    latest_sql, latest_params = connection.cursor_instance.executions[1]
    assert "WHERE EXCLUDED.observed_at >= official_realtime_latest.observed_at" in latest_sql
    assert latest_params[6] == datetime(2026, 4, 28, 9, 50, tzinfo=timezone.utc)


def test_promotion_idempotency_migration_handles_null_raw_ref_uniqueness() -> None:
    migration_sql = (
        Path(__file__).resolve().parents[3]
        / "infra"
        / "migrations"
        / "0010_promotion_evidence_idempotency.sql"
    ).read_text(encoding="utf-8")

    assert "evidence_source_raw_ref_unique" in migration_sql
    assert "UNIQUE NULLS NOT DISTINCT (source_id, raw_ref)" in migration_sql


def test_postgres_promotion_writer_can_filter_accepted_rows_by_adapter_key() -> None:
    connection = _FakeConnection(rows=[], evidence_id="unused")
    writer = PostgresEvidencePromotionWriter(connection_factory=lambda: connection)

    candidates = writer.fetch_accepted_staging(
        limit=5,
        adapter_keys=("official.cwa.rainfall", "official.wra.water_level"),
    )

    assert candidates == ()
    select_sql, select_params = connection.cursor_instance.executions[0]
    assert "COALESCE(se.payload ->> 'adapter_key', rs.adapter_key) = ANY(%s)" in select_sql
    assert select_params == (["official.cwa.rainfall", "official.wra.water_level"], 5)


def test_postgres_promotion_writer_requires_database_url_or_connection_factory() -> None:
    try:
        PostgresEvidencePromotionWriter()
    except ValueError as exc:
        assert str(exc) == "database_url or connection_factory is required"
    else:
        raise AssertionError("expected ValueError")


def _candidate(
    *,
    staging_evidence_id: str = "staging-id",
    raw_ref: str | None = "raw/news-public-web/sample.json",
    source_id: str = "sample-news-001",
    validation_status: str = "accepted",
    payload: dict[str, object] | None = None,
) -> PromotionCandidate:
    return PromotionCandidate(
        staging_evidence_id=staging_evidence_id,
        raw_snapshot_id="raw-snapshot-id",
        raw_ref=raw_ref,
        data_source_id="data-source-id",
        source_id=source_id,
        source_type="news",
        event_type="flood_report",
        title="Heavy rain reported near riverside district",
        summary="Public report describes street flooding near the riverside district.",
        url="https://example.test/news/flood-001",
        occurred_at=OCCURRED_AT,
        observed_at=OBSERVED_AT,
        confidence=0.72,
        validation_status=validation_status,
        payload=payload
        or {
            "adapter_key": "news.public_web.sample",
            "location_text": "Riverside District",
        },
    )


class _MemoryPromotionWriter:
    def __init__(self, candidates: list[PromotionCandidate]) -> None:
        self._candidates = tuple(candidates)
        self.requested_limit: int | None = None
        self.requested_adapter_keys: tuple[str, ...] | None = None
        self.payloads: list[EvidencePromotionPayload] = []

    def fetch_accepted_staging(
        self,
        *,
        limit: int | None = None,
        adapter_keys: tuple[str, ...] | None = None,
    ) -> tuple[PromotionCandidate, ...]:
        self.requested_limit = limit
        self.requested_adapter_keys = adapter_keys
        return self._candidates

    def write_evidence(self, payload: EvidencePromotionPayload) -> str:
        self.payloads.append(payload)
        return f"evidence-{len(self.payloads)}"


class _FakeConnection:
    def __init__(self, *, rows: list[tuple[object, ...]], evidence_id: str) -> None:
        self.cursor_instance = _FakeCursor(rows=rows, evidence_id=evidence_id)
        self.committed = False

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def cursor(self) -> _FakeCursor:
        return self.cursor_instance

    def commit(self) -> None:
        self.committed = True


class _FakeCursor:
    def __init__(self, *, rows: list[tuple[object, ...]], evidence_id: str) -> None:
        self._rows = tuple(rows)
        self._evidence_id = evidence_id
        self.executions: list[tuple[str, tuple[object, ...]]] = []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        self.executions.append((sql, params))

    def fetchall(self) -> tuple[tuple[object, ...], ...]:
        return self._rows

    def fetchone(self) -> tuple[str]:
        return (self._evidence_id,)
