from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Self

import pytest

from app.adapters.cap_identity import cap_message_digest
from app.pipelines.promotion import (
    EvidencePromotionPayload,
    PostgresEvidencePromotionWriter,
    PromotionCandidate,
    build_evidence_promotion_payload,
    promote_accepted_staging,
)

OCCURRED_AT = datetime(2026, 4, 28, 8, 30, tzinfo=UTC)
OBSERVED_AT = datetime(2026, 4, 28, 10, 0, tzinfo=UTC)


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


def test_promote_accepted_staging_counts_only_actual_writes() -> None:
    writer = _MemoryPromotionWriter(
        [
            _candidate(staging_evidence_id="staging-id-1", source_id="first"),
            _candidate(staging_evidence_id="staging-id-2", source_id="duplicate"),
            _candidate(staging_evidence_id="staging-id-3", source_id="third"),
        ],
        terminal_source_ids={"duplicate"},
    )

    result = promote_accepted_staging(writer)

    assert result.promoted == 2
    assert result.evidence_ids == ("evidence-1", "evidence-3")


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


def test_advisory_lock_precedes_any_latest_read_or_evidence_insert() -> None:
    connection = _FakeConnection(rows=[], evidence_id="evidence-id")
    writer = PostgresEvidencePromotionWriter(connection_factory=lambda: connection)

    writer.write_evidence(_reviewed_realtime_payload())

    statements = [statement for statement, _ in connection.cursor_instance.executions]
    assert any("pg_advisory_xact_lock" in statement for statement in statements)
    lock_index = next(
        index for index, statement in enumerate(statements) if "pg_advisory_xact_lock" in statement
    )
    decision_index = next(
        index
        for index, statement in enumerate(statements)
        if "FROM official_realtime_latest" in statement or "INSERT INTO evidence" in statement
    )
    assert lock_index < decision_index


@pytest.mark.parametrize("scope", ["historical", "context", "unspecified", None])
def test_non_current_scope_is_never_upserted_to_official_latest(
    scope: str | None,
) -> None:
    connection = _FakeConnection(rows=[], evidence_id="evidence-id")
    writer = PostgresEvidencePromotionWriter(connection_factory=lambda: connection)
    payload = _reviewed_realtime_payload()
    payload.properties["evidence_scope"] = scope

    evidence_id = writer.write_evidence(payload)

    assert evidence_id == "evidence-id"
    assert not any(
        "INSERT INTO official_realtime_latest" in statement
        for statement, _ in connection.cursor_instance.executions
    )


def test_unreviewed_civil_iot_pair_is_audit_only_even_with_current_scope() -> None:
    connection = _FakeConnection(rows=[], evidence_id="evidence-id")
    writer = PostgresEvidencePromotionWriter(connection_factory=lambda: connection)
    payload = _reviewed_realtime_payload()
    payload = EvidencePromotionPayload(
        **{
            **payload.__dict__,
            "adapter_key": "official.civil_iot.flood_sensor",
            "event_type": "flood_report",
        }
    )

    evidence_id = writer.write_evidence(payload)

    assert evidence_id == "evidence-id"
    assert not any(
        "INSERT INTO official_realtime_latest" in statement
        for statement, _ in connection.cursor_instance.executions
    )


@pytest.mark.parametrize(
    ("adapter_key", "event_type"),
    [
        ("official.cwa.rainfall", "rainfall"),
        ("official.wra.water_level", "water_level"),
        ("official.wra_iow.flood_depth", "flood_report"),
        ("local.tainan.flood_sensor", "flood_report"),
    ],
)
def test_each_reviewed_current_adapter_pair_upserts_exactly_one_latest(
    adapter_key: str,
    event_type: str,
) -> None:
    connection = _FakeConnection(rows=[], evidence_id="evidence-id")
    writer = PostgresEvidencePromotionWriter(connection_factory=lambda: connection)
    payload = _reviewed_realtime_payload()
    properties = dict(payload.properties)
    if event_type == "rainfall":
        properties["rainfall_mm_1h"] = 12.0
    if event_type == "flood_report":
        properties["flood_depth_cm"] = 12.0
    payload = EvidencePromotionPayload(
        **{
            **payload.__dict__,
            "adapter_key": adapter_key,
            "event_type": event_type,
            "properties": properties,
        }
    )

    evidence_id = writer.write_evidence(payload)

    assert evidence_id == "evidence-id"
    assert sum(
        "INSERT INTO official_realtime_latest" in statement
        for statement, _ in connection.cursor_instance.executions
    ) == 1


def test_equal_time_equal_value_is_terminal_idempotent() -> None:
    staging_id = "11111111-1111-4111-8111-111111111111"
    connection = _FakeConnection(
        rows=[],
        evidence_id="evidence-id",
        existing_latest_row=(
            OBSERVED_AT,
            "WRA-001",
            None,
            None,
            3.2,
            None,
            4.0,
            '{"type":"Point","coordinates":[121.48,25.03]}',
        ),
    )
    writer = PostgresEvidencePromotionWriter(connection_factory=lambda: connection)
    payload = _reviewed_realtime_payload()
    payload.properties["staging_evidence_id"] = staging_id

    result = writer.write_evidence(payload)

    assert result is None
    assert connection.cursor_instance.terminal_rejections == [
        (staging_id, "idempotent_existing_observation")
    ]
    assert not any(
        "INSERT INTO evidence" in statement
        for statement, _ in connection.cursor_instance.executions
    )


def test_equal_time_conflicting_value_is_terminal_conflict() -> None:
    staging_id = "22222222-2222-4222-8222-222222222222"
    connection = _FakeConnection(
        rows=[],
        evidence_id="evidence-id",
        existing_latest_row=(
            OBSERVED_AT,
            "WRA-001",
            None,
            None,
            9.9,
            None,
            4.0,
            '{"type":"Point","coordinates":[121.48,25.03]}',
        ),
    )
    writer = PostgresEvidencePromotionWriter(connection_factory=lambda: connection)
    payload = _reviewed_realtime_payload()
    payload.properties["staging_evidence_id"] = staging_id

    result = writer.write_evidence(payload)

    assert result is None
    assert connection.cursor_instance.terminal_rejections == [
        (staging_id, "conflicting_latest")
    ]
    assert not any(
        "INSERT INTO evidence" in statement
        for statement, _ in connection.cursor_instance.executions
    )


def test_same_staging_retry_never_rejects_the_consumed_staging_row() -> None:
    staging_id = "33333333-3333-4333-8333-333333333333"
    connection = _FakeConnection(
        rows=[], evidence_id="evidence-id", same_staging_used=True
    )
    writer = PostgresEvidencePromotionWriter(connection_factory=lambda: connection)
    payload = _reviewed_realtime_payload()
    payload.properties["staging_evidence_id"] = staging_id

    result = writer.write_evidence(payload)

    assert result is None
    assert connection.cursor_instance.terminal_rejections == []


def test_central_first_rejects_exact_tainan_duplicate() -> None:
    staging_id = "44444444-4444-4444-8444-444444444444"
    connection = _FakeConnection(
        rows=[],
        evidence_id="evidence-id",
        exact_duplicate_row=("official.wra_iow.flood_depth", "WRA-DEPTH-1"),
    )
    writer = PostgresEvidencePromotionWriter(connection_factory=lambda: connection)
    payload = _depth_payload(adapter_key="local.tainan.flood_sensor", station_id="TN-1")
    payload.properties["staging_evidence_id"] = staging_id

    result = writer.write_evidence(payload)

    assert result is None
    assert connection.cursor_instance.terminal_rejections == [
        (staging_id, "duplicate_central")
    ]


def test_local_first_is_replaced_by_exact_wra_iow_duplicate() -> None:
    connection = _FakeConnection(
        rows=[],
        evidence_id="evidence-id",
        exact_duplicate_row=("local.tainan.flood_sensor", "TN-1"),
    )
    writer = PostgresEvidencePromotionWriter(connection_factory=lambda: connection)

    result = writer.write_evidence(
        _depth_payload(adapter_key="official.wra_iow.flood_depth", station_id="WRA-DEPTH-1")
    )

    assert result == "evidence-id"
    assert any(
        "DELETE FROM official_realtime_latest" in statement
        and "local.tainan.flood_sensor" in str(params)
        for statement, params in connection.cursor_instance.executions
    )


@pytest.mark.parametrize(
    "adapter_key",
    ["official.cwa.heavy_rain_warning", "official.ncdr.cap"],
)
def test_cap_area_uses_canonical_message_admin_key_and_reviewed_boundary(
    adapter_key: str,
) -> None:
    multipolygon = {
        "type": "MultiPolygon",
        "coordinates": [[[[120.0, 22.8], [120.4, 22.8], [120.4, 23.2], [120.0, 22.8]]]],
    }
    point = {"type": "Point", "coordinates": [120.2, 23.0]}
    connection = _FakeConnection(
        rows=[],
        evidence_id="evidence-id",
        reviewed_boundary_row=(json.dumps(multipolygon), json.dumps(point)),
    )
    writer = PostgresEvidencePromotionWriter(connection_factory=lambda: connection)
    payload = _cap_payload(adapter_key=adapter_key)

    evidence_id = writer.write_evidence(payload)

    assert evidence_id == "evidence-id"
    insert_params = next(
        params
        for statement, params in connection.cursor_instance.executions
        if "INSERT INTO evidence" in statement
    )
    assert json.loads(str(insert_params[11])) == multipolygon
    latest_params = next(
        params
        for statement, params in connection.cursor_instance.executions
        if "INSERT INTO official_realtime_latest" in statement
    )
    assert latest_params[3] == "cap:67000000:" + cap_message_digest(
        sender="sender@example.test",
        identifier="alert-1",
        sent=datetime(2026, 8, 24, 1, 0, tzinfo=UTC),
    )
    assert json.loads(str(latest_params[7])) == point
    quality_flags = json.loads(str(latest_params[21]))
    assert quality_flags["location_precision"] == "admin_area"
    assert quality_flags["ingestion_generation_started_at"] == (
        "2026-08-24T01:05:00+00:00"
    )
    assert quality_flags["active_until"] == "2027-08-24T03:00:00+00:00"


def test_unresolved_or_unreviewed_cap_boundary_remains_unlocated_audit() -> None:
    connection = _FakeConnection(rows=[], evidence_id="evidence-id")
    writer = PostgresEvidencePromotionWriter(connection_factory=lambda: connection)

    evidence_id = writer.write_evidence(_cap_payload())

    assert evidence_id == "evidence-id"
    boundary_sql = next(
        statement
        for statement, _ in connection.cursor_instance.executions
        if "/* reviewed-warning-boundary */" in statement
    )
    assert "snapshot.is_active" in boundary_sql
    assert "snapshot.reviewed_at IS NOT NULL" in boundary_sql
    assert "snapshot.manifest_sha256 = snapshot.approved_manifest_sha256" in boundary_sql
    assert "boundary_integrity.geom_sha256" in boundary_sql
    assert not any(
        "INSERT INTO official_realtime_latest" in statement
        for statement, _ in connection.cursor_instance.executions
    )


@pytest.mark.parametrize("message_type", ["Update", "Cancel"])
def test_cap_mutation_retires_only_exact_reference_triples(message_type: str) -> None:
    reference = {
        "sender": "sender@example.test",
        "identifier": "alert-1",
        "sent": "2026-08-24T01:00:00+00:00",
    }
    connection = _FakeConnection(
        rows=[],
        evidence_id="evidence-id",
        reviewed_boundary_row=(
            '{"type":"MultiPolygon","coordinates":[[[[120,22],[121,22],[121,23],[120,22]]]]}',
            '{"type":"Point","coordinates":[120.5,22.5]}',
        ),
    )
    writer = PostgresEvidencePromotionWriter(connection_factory=lambda: connection)
    payload = _cap_payload(
        message_type=message_type,
        identifier=f"{message_type.lower()}-2",
        references=[reference],
        admin_code=None if message_type == "Cancel" else "67000000",
    )

    evidence_id = writer.write_evidence(payload)

    assert evidence_id == "evidence-id"
    assert any(
        "/* retire-cap-references */" in statement
        for statement, _ in connection.cursor_instance.executions
    )
    retire_statement, retire_params = next(
        execution
        for execution in connection.cursor_instance.executions
        if "/* retire-cap-references */" in execution[0]
    )
    assert "USING evidence" in retire_statement
    assert json.loads(str(retire_params[0])) == [reference]
    latest_writes = [
        statement
        for statement, _ in connection.cursor_instance.executions
        if "INSERT INTO official_realtime_latest" in statement
    ]
    assert bool(latest_writes) is (message_type == "Update")


def test_cap_reference_origin_locks_are_global_across_adapters() -> None:
    reference = {
        "sender": "sender@example.test",
        "identifier": "alert-1",
        "sent": "2026-08-24T01:00:00+00:00",
    }
    cwa_connection = _FakeConnection(rows=[], evidence_id="cwa")
    ncdr_connection = _FakeConnection(rows=[], evidence_id="ncdr")
    PostgresEvidencePromotionWriter(connection_factory=lambda: cwa_connection).write_evidence(
        _cap_payload(message_type="Update", identifier="update-2", references=[reference])
    )
    PostgresEvidencePromotionWriter(connection_factory=lambda: ncdr_connection).write_evidence(
        _cap_payload(
            adapter_key="official.ncdr.cap",
            message_type="Cancel",
            identifier="cancel-3",
            references=[reference],
            admin_code=None,
        )
    )

    def origin_locks(connection: _FakeConnection) -> set[str]:
        return {
            str(params[0])
            for statement, params in connection.cursor_instance.executions
            if "pg_advisory_xact_lock" in statement
            and str(params[0]).startswith("official-warning-origin|")
        }

    assert origin_locks(cwa_connection) & origin_locks(ncdr_connection)


def test_retained_cap_tombstone_blocks_alert_replay_without_new_evidence() -> None:
    staging_id = "55555555-5555-4555-8555-555555555555"
    connection = _FakeConnection(
        rows=[], evidence_id="evidence-id", cap_tombstone_exists=True
    )
    writer = PostgresEvidencePromotionWriter(connection_factory=lambda: connection)
    payload = _cap_payload()
    payload.properties["staging_evidence_id"] = staging_id

    result = writer.write_evidence(payload)

    assert result is None
    assert connection.cursor_instance.terminal_rejections == [
        (staging_id, "retired_cap_replay")
    ]
    assert not any(
        "INSERT INTO evidence" in statement
        for statement, _ in connection.cursor_instance.executions
    )


def test_expired_cap_candidate_is_terminal_before_evidence_insert() -> None:
    staging_id = "66666666-6666-4666-8666-666666666666"
    connection = _FakeConnection(rows=[], evidence_id="evidence-id")
    writer = PostgresEvidencePromotionWriter(connection_factory=lambda: connection)
    payload = _cap_payload()
    payload.properties["staging_evidence_id"] = staging_id
    payload.properties["active_until"] = "2020-01-01T00:00:00+00:00"

    result = writer.write_evidence(payload)

    assert result is None
    assert connection.cursor_instance.terminal_rejections == [
        (staging_id, "inactive_cap_window")
    ]


@pytest.mark.parametrize(
    "generation",
    [None, "2026-08-24T01:05:00"],
)
def test_cap_promotion_without_aware_worker_generation_fails_closed(
    generation: str | None,
) -> None:
    staging_id = "77777777-7777-4777-8777-777777777777"
    connection = _FakeConnection(rows=[], evidence_id="evidence-id")
    writer = PostgresEvidencePromotionWriter(connection_factory=lambda: connection)
    payload = _cap_payload(message_type="Cancel", admin_code=None)
    payload.properties["staging_evidence_id"] = staging_id
    if generation is None:
        payload.properties.pop("ingestion_generation_started_at")
    else:
        payload.properties["ingestion_generation_started_at"] = generation

    result = writer.write_evidence(payload)

    assert result is None
    assert connection.cursor_instance.terminal_rejections == [
        (staging_id, "invalid_ingestion_generation")
    ]
    assert not any(
        "INSERT INTO evidence" in statement
        for statement, _ in connection.cursor_instance.executions
    )


def test_write_evidence_keeps_civil_iot_flood_depth_audit_only() -> None:
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
    assert len(connection.cursor_instance.executions) == 1
    assert "INSERT INTO evidence" in connection.cursor_instance.executions[0][0]


def test_write_evidence_keeps_unreviewed_status_only_audit_only() -> None:
    connection = _FakeConnection(rows=[], evidence_id="evidence-id")
    writer = PostgresEvidencePromotionWriter(connection_factory=lambda: connection)
    payload = EvidencePromotionPayload(
        data_source_id="data-source-id",
        adapter_key="local.yunlin.water_level",
        source_id="YL-FS-001:2026-06-28T09:00:02.651000+00:00",
        source_type="official",
        event_type="status_only",
        title="Yunlin iflood status",
        summary="Status-only flood-sensor alarm state; no depth value exposed.",
        url="https://yliflood.yunlin.gov.tw/ifloodboard/",
        occurred_at=OCCURRED_AT,
        observed_at=OBSERVED_AT,
        confidence=0.32,
        raw_ref="raw/local-yunlin/status-only.json",
        properties={
            "station_id": "YL-FS-001",
            "station_name": "港西村_中正路3-23號",
            "authority": "雲林縣政府",
            "alarm_state": "正常",
            "source_weight": 0.05,
            "location_payload": {
                "geometry": {"type": "Point", "coordinates": [120.147835, 23.575771]}
            },
        },
    )

    evidence_id = writer.write_evidence(payload)

    assert evidence_id == "evidence-id"
    assert len(connection.cursor_instance.executions) == 1
    assert "INSERT INTO evidence" in connection.cursor_instance.executions[0][0]


def test_write_evidence_does_not_enrich_audit_only_civil_iot_geometry() -> None:
    connection = _FakeConnection(
        rows=[],
        evidence_id="evidence-id",
        admin_area_row=("臺北市", "中正區", "黎明里"),
    )
    writer = PostgresEvidencePromotionWriter(connection_factory=lambda: connection)
    payload = EvidencePromotionPayload(
        data_source_id="data-source-id",
        adapter_key="official.civil_iot.gate_water_level",
        source_id="GATE-001:2026-06-15T03:00:00+00:00",
        source_type="official",
        event_type="water_level",
        title="Gate water level",
        summary="Observed external gate water level",
        url="https://example.test/civil-iot/gate/GATE-001",
        occurred_at=OCCURRED_AT,
        observed_at=OBSERVED_AT,
        confidence=0.9,
        raw_ref="raw/civil-iot/gate/gate-001.json",
        properties={
            "adapter_key": "official.civil_iot.gate_water_level",
            "station_id": "GATE-001",
            "station_name": "水門監測站",
            "authority": "第四河川分署",
            "water_level_m": 1.38,
            "location_payload": {
                "geometry": {"type": "Point", "coordinates": [121.52, 25.04]}
            },
        },
    )

    evidence_id = writer.write_evidence(payload)

    assert evidence_id == "evidence-id"
    insert_sql, insert_params = connection.cursor_instance.executions[0]
    assert "INSERT INTO evidence" in insert_sql
    properties = json.loads(str(insert_params[14]))
    assert "county" not in properties
    assert not any(
        "INSERT INTO official_realtime_latest" in statement
        for statement, _ in connection.cursor_instance.executions
    )


def test_local_without_current_scope_remains_audit_only_without_fuzzy_dedupe() -> None:
    connection = _FakeConnection(
        rows=[],
        evidence_id="evidence-id",
        central_duplicate_row=("official.civil_iot.flood_sensor", "CIVIL-FS-001"),
    )
    writer = PostgresEvidencePromotionWriter(connection_factory=lambda: connection)
    payload = EvidencePromotionPayload(
        data_source_id="data-source-id",
        adapter_key="local.tainan.flood_sensor",
        source_id="TN-FS-001:2026-06-15T03:00:00+00:00",
        source_type="official",
        event_type="flood_report",
        title="Tainan flood sensor report",
        summary="Observed local flood depth 17 cm",
        url="https://example.test/tainan/flood-sensor/TN-FS-001",
        occurred_at=OCCURRED_AT,
        observed_at=OBSERVED_AT,
        confidence=0.9,
        raw_ref="raw/tainan/flood-sensor/tn-fs-001.json",
        properties={
            "adapter_key": "local.tainan.flood_sensor",
            "station_id": "TN-FS-001",
            "station_name": "臺南淹水感測器",
            "authority": "Tainan City Government",
            "flood_depth_cm": 17.0,
            "location_payload": {
                "geometry": {"type": "Point", "coordinates": [120.2, 23.0]}
            },
        },
    )

    evidence_id = writer.write_evidence(payload)

    assert evidence_id == "evidence-id"
    insert_sql, insert_params = connection.cursor_instance.executions[0]
    properties = json.loads(str(insert_params[14]))
    assert "duplicate_candidate" not in properties.get("quality_flags", {})
    assert "INSERT INTO evidence" in insert_sql
    assert not any(
        "official_realtime_latest" in statement
        for statement, _ in connection.cursor_instance.executions
    )


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


def test_write_evidence_does_not_fallback_station_id_for_cap_source_prefix() -> None:
    connection = _FakeConnection(rows=[], evidence_id="evidence-id")
    writer = PostgresEvidencePromotionWriter(connection_factory=lambda: connection)
    payload = EvidencePromotionPayload(
        data_source_id="data-source-id",
        adapter_key="official.ncdr.cap",
        source_id="ALERT01:2026-06-15T03:00:00+00:00",
        source_type="official",
        event_type="flood_warning",
        title="Flood warning",
        summary="Regional flood warning",
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


def test_write_evidence_does_not_fallback_station_id_from_generic_word_prefix() -> None:
    connection = _FakeConnection(rows=[], evidence_id="evidence-id")
    writer = PostgresEvidencePromotionWriter(connection_factory=lambda: connection)
    payload = EvidencePromotionPayload(
        data_source_id="data-source-id",
        adapter_key="official.cwa.rainfall",
        source_id="alert:2026-06-15T03:00:00+00:00",
        source_type="official",
        event_type="rainfall",
        title="Rainfall observation",
        summary="Observed rainfall 42 mm",
        url="https://example.test/rainfall/alert",
        occurred_at=OCCURRED_AT,
        observed_at=OBSERVED_AT,
        confidence=0.92,
        raw_ref="raw/cwa/rainfall/alert.json",
        properties={
            "adapter_key": "official.cwa.rainfall",
            "station_name": "Unknown",
            "authority": "CWA",
            "rainfall_mm_1h": 42.0,
            "location_payload": {
                "geometry": {"type": "Point", "coordinates": [121.0, 24.0]}
            },
        },
    )

    evidence_id = writer.write_evidence(payload)

    assert evidence_id == "evidence-id"
    assert connection.committed is True
    assert len(connection.cursor_instance.executions) == 1
    assert "INSERT INTO evidence" in connection.cursor_instance.executions[0][0]


def test_write_evidence_does_not_overwrite_newer_latest_with_older_observation() -> None:
    connection = _FakeConnection(
        rows=[],
        evidence_id="evidence-id",
        existing_latest_observed_at=datetime(2026, 4, 28, 10, 5, tzinfo=UTC),
    )
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
        observed_at=datetime(2026, 4, 28, 9, 50, tzinfo=UTC),
        confidence=0.88,
        raw_ref="raw/wra/water-level/wra-001.json",
        properties={
            "adapter_key": "official.wra.water_level",
            "evidence_scope": "current",
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

    latest_sql, latest_params = next(
        execution
        for execution in connection.cursor_instance.executions
        if "INSERT INTO official_realtime_latest" in execution[0]
    )
    assert "WHERE EXCLUDED.observed_at > official_realtime_latest.observed_at" in latest_sql
    assert latest_params[6] == datetime(2026, 4, 28, 9, 50, tzinfo=UTC)
    assert connection.cursor_instance.latest_attempted is True
    assert connection.cursor_instance.latest_has_freshness_guard is True
    assert connection.cursor_instance.latest_updated is False


def test_write_evidence_skips_latest_upsert_for_non_point_geometry() -> None:
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
            "flood_depth_cm": 18.0,
            "location_payload": {
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [120.2, 23.0],
                            [120.3, 23.0],
                            [120.3, 23.1],
                            [120.2, 23.1],
                            [120.2, 23.0],
                        ]
                    ],
                }
            },
        },
    )

    evidence_id = writer.write_evidence(payload)

    assert evidence_id == "evidence-id"
    assert connection.committed is True
    assert len(connection.cursor_instance.executions) == 1
    assert "INSERT INTO evidence" in connection.cursor_instance.executions[0][0]


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


def _reviewed_realtime_payload() -> EvidencePromotionPayload:
    return EvidencePromotionPayload(
        data_source_id="data-source-id",
        adapter_key="official.wra.water_level",
        source_id="WRA-001:2026-04-28T10:00:00+00:00",
        source_type="official",
        event_type="water_level",
        title="Water level observation",
        summary="Observed water level 3.2 m",
        url="https://example.test/wra/WRA-001",
        occurred_at=OBSERVED_AT,
        observed_at=OBSERVED_AT,
        confidence=0.9,
        raw_ref="raw/wra/water-level/wra-001.json",
        properties={
            "adapter_key": "official.wra.water_level",
            "evidence_scope": "current",
            "station_id": "WRA-001",
            "station_name": "Dahan Bridge",
            "authority": "Water Resources Agency",
            "water_level_m": 3.2,
            "warning_level_m": 4.0,
            "location_precision": "point",
            "location_payload": {
                "geometry": {"type": "Point", "coordinates": [121.48, 25.03]}
            },
        },
    )


def _depth_payload(*, adapter_key: str, station_id: str) -> EvidencePromotionPayload:
    return EvidencePromotionPayload(
        data_source_id="data-source-id",
        adapter_key=adapter_key,
        source_id=f"{station_id}:{OBSERVED_AT.isoformat()}",
        source_type="official",
        event_type="flood_report",
        title="Flood depth observation",
        summary="Observed flood depth 12 cm",
        url="https://example.test/depth",
        occurred_at=OBSERVED_AT,
        observed_at=OBSERVED_AT,
        confidence=0.9,
        raw_ref=f"raw/{station_id}.json",
        properties={
            "adapter_key": adapter_key,
            "evidence_scope": "current",
            "station_id": station_id,
            "flood_depth_cm": 12.0,
            "location_precision": "point",
            "location_payload": {
                "geometry": {"type": "Point", "coordinates": [120.219, 22.916]}
            },
        },
    )


def _cap_payload(
    *,
    adapter_key: str = "official.cwa.heavy_rain_warning",
    message_type: str = "Alert",
    identifier: str = "alert-1",
    references: list[dict[str, str]] | None = None,
    admin_code: str | None = "67000000",
) -> EvidencePromotionPayload:
    sent = datetime(2026, 8, 24, 1, 0, tzinfo=UTC)
    return EvidencePromotionPayload(
        data_source_id="data-source-id",
        adapter_key=adapter_key,
        source_id=f"cap-source-{identifier}",
        source_type="official",
        event_type="flood_warning",
        title="Heavy rain warning",
        summary="Active warning for Tainan.",
        url="https://example.test/cap",
        occurred_at=sent,
        observed_at=sent,
        confidence=0.95,
        raw_ref=f"raw/cap/{identifier}.xml",
        properties={
            "adapter_key": adapter_key,
            "evidence_scope": "current",
            "location_precision": "admin_area",
            "admin_code": admin_code,
            "cap_sender": "sender@example.test",
            "cap_identifier": identifier,
            "cap_sent": sent.isoformat(),
            "cap_references": references or [],
            "cap_status": "Actual",
            "cap_message_type": message_type,
            "active_from": "2026-08-24T00:00:00+00:00",
            "active_until": "2027-08-24T03:00:00+00:00",
            "ingestion_generation_started_at": "2026-08-24T01:05:00+00:00",
        },
    )


class _MemoryPromotionWriter:
    def __init__(
        self,
        candidates: list[PromotionCandidate],
        *,
        terminal_source_ids: set[str] | None = None,
    ) -> None:
        self._candidates = tuple(candidates)
        self._terminal_source_ids = terminal_source_ids or set()
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

    def write_evidence(self, payload: EvidencePromotionPayload) -> str | None:
        self.payloads.append(payload)
        if payload.source_id in self._terminal_source_ids:
            return None
        return f"evidence-{len(self.payloads)}"


class _FakeConnection:
    def __init__(
        self,
        *,
        rows: list[tuple[object, ...]],
        evidence_id: str,
        existing_latest_observed_at: datetime | None = None,
        existing_latest_row: tuple[object, ...] | None = None,
        same_staging_used: bool = False,
        exact_duplicate_row: tuple[str, str] | None = None,
        reviewed_boundary_row: tuple[str, str] | None = None,
        cap_tombstone_exists: bool = False,
        admin_area_row: tuple[str, str | None, str | None] | None = None,
        central_duplicate_row: tuple[str, str] | None = None,
    ) -> None:
        self.cursor_instance = _FakeCursor(
            rows=rows,
            evidence_id=evidence_id,
            existing_latest_observed_at=existing_latest_observed_at,
            existing_latest_row=existing_latest_row,
            same_staging_used=same_staging_used,
            exact_duplicate_row=exact_duplicate_row,
            reviewed_boundary_row=reviewed_boundary_row,
            cap_tombstone_exists=cap_tombstone_exists,
            admin_area_row=admin_area_row,
            central_duplicate_row=central_duplicate_row,
        )
        self.committed = False

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def cursor(self) -> _FakeCursor:
        return self.cursor_instance

    def commit(self) -> None:
        self.committed = True


class _FakeCursor:
    def __init__(
        self,
        *,
        rows: list[tuple[object, ...]],
        evidence_id: str,
        existing_latest_observed_at: datetime | None,
        existing_latest_row: tuple[object, ...] | None,
        same_staging_used: bool,
        exact_duplicate_row: tuple[str, str] | None,
        reviewed_boundary_row: tuple[str, str] | None,
        cap_tombstone_exists: bool,
        admin_area_row: tuple[str, str | None, str | None] | None,
        central_duplicate_row: tuple[str, str] | None,
    ) -> None:
        self._rows = tuple(rows)
        self._evidence_id = evidence_id
        self._admin_area_row = admin_area_row
        self._central_duplicate_row = central_duplicate_row
        self.executions: list[tuple[str, tuple[object, ...]]] = []
        self._existing_latest_observed_at = existing_latest_observed_at
        self._existing_latest_row = existing_latest_row
        self._same_staging_used = same_staging_used
        self._exact_duplicate_row = exact_duplicate_row
        self._reviewed_boundary_row = reviewed_boundary_row
        self._cap_tombstone_exists = cap_tombstone_exists
        self.terminal_rejections: list[tuple[str, str]] = []
        self.latest_attempted = False
        self.latest_has_freshness_guard = False
        self.latest_updated: bool | None = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        self.executions.append((sql, params))
        if "UPDATE staging_evidence" in sql:
            self.terminal_rejections.append((str(params[1]), str(params[0])))
        if "INSERT INTO official_realtime_latest" not in sql:
            return

        self.latest_attempted = True
        self.latest_has_freshness_guard = (
            "WHERE EXCLUDED.observed_at > official_realtime_latest.observed_at" in sql
        )

        incoming_observed_at = params[6]
        if self._existing_latest_observed_at is None:
            self.latest_updated = True
            return

        if self.latest_has_freshness_guard:
            self.latest_updated = incoming_observed_at > self._existing_latest_observed_at
            return

        self.latest_updated = True

    def fetchall(self) -> tuple[tuple[object, ...], ...]:
        return self._rows

    def fetchone(self) -> tuple[str]:
        if self.executions and "/* same-staging-evidence */" in self.executions[-1][0]:
            return ("1",) if self._same_staging_used else None
        if self.executions and "/* latest-decision */" in self.executions[-1][0]:
            return self._existing_latest_row
        if self.executions and "/* exact-central-local-duplicate */" in self.executions[-1][0]:
            return self._exact_duplicate_row
        if self.executions and "/* reviewed-warning-boundary */" in self.executions[-1][0]:
            return self._reviewed_boundary_row
        if self.executions and "/* retained-cap-tombstone */" in self.executions[-1][0]:
            return ("1",) if self._cap_tombstone_exists else None
        if self.executions and "FROM admin_area_profiles" in self.executions[-1][0]:
            return self._admin_area_row
        if self.executions and "FROM official_realtime_latest" in self.executions[-1][0]:
            return self._central_duplicate_row
        return (self._evidence_id,)
