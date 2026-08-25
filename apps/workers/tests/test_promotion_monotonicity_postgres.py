from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Barrier, Event, Thread
from time import monotonic
from typing import Any, Self
from uuid import uuid4

import pytest

from app.adapters.cap_identity import cap_message_digest
from app.jobs.ingestion import AdapterBatchRunSummary
from app.pipelines.ingestion_runs import PostgresIngestionRunWriter
from app.pipelines.promotion import EvidencePromotionPayload, PostgresEvidencePromotionWriter

DATABASE_URL_ENV = "PROMOTION_TEST_DATABASE_URL"
REQUIRED_ENV = "OFFICIAL_DB_ACCEPTANCE_REQUIRED"
NOW = datetime(2026, 8, 24, 2, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def database_url() -> str:
    import psycopg

    url = os.getenv(DATABASE_URL_ENV)
    required = os.getenv(REQUIRED_ENV) == "1"
    if not url:
        if required:
            pytest.fail(f"{DATABASE_URL_ENV} is required for official DB acceptance")
        pytest.skip(f"set {DATABASE_URL_ENV} to run PostGIS promotion races")
    try:
        with psycopg.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT postgis_version()")
            assert cursor.fetchone() is not None
    except (OSError, psycopg.Error) as exc:
        if required:
            pytest.fail(f"required PostGIS database is unreachable: {exc}")
        pytest.skip(f"PostGIS database is unreachable: {exc}")
    return url


def test_complete_replace_marker_preserves_lkg_across_failure_and_older_runs(
    database_url: str,
) -> None:
    import psycopg

    suffix = uuid4().hex
    adapter_key = f"test.complete-replace.{suffix}"
    raw_a = f"raw/test/complete-replace/{'a' * 64}.json"
    raw_b = f"raw/test/complete-replace/{'b' * 64}.json"
    raw_c = f"raw/test/complete-replace/{'c' * 64}.json"
    older_at = NOW - timedelta(minutes=1)
    active_at = NOW
    failed_at = NOW + timedelta(minutes=1)
    blocked_at = NOW + timedelta(minutes=2)
    newer_job_at = NOW + timedelta(minutes=3)
    writer = PostgresIngestionRunWriter(database_url=database_url)

    try:
        with psycopg.connect(database_url) as connection:
            connection.execute(
                """
                INSERT INTO data_sources (
                    name, adapter_key, source_type, is_enabled, metadata
                ) VALUES (%s, %s, 'derived', true, %s::jsonb)
                """,
                (
                    "Complete-replace activation fixture",
                    adapter_key,
                    json.dumps({"active_snapshot_raw_ref": raw_a}),
                ),
            )

        writer.write_pipeline_status(
            adapter_keys=(adapter_key,),
            status="succeeded",
            complete=True,
            checked_at=active_at,
            run_at=active_at,
            active_snapshot_raw_ref=raw_b,
        )
        writer.write_pipeline_status(
            adapter_keys=(adapter_key,),
            status="failed",
            complete=False,
            checked_at=failed_at,
            run_at=failed_at,
        )
        writer.write_pipeline_status(
            adapter_keys=(adapter_key,),
            status="succeeded",
            complete=True,
            checked_at=older_at,
            run_at=older_at,
            active_snapshot_raw_ref=raw_a,
        )

        with psycopg.connect(database_url) as connection:
            connection.execute(
                """
                INSERT INTO ingestion_jobs (
                    job_key, adapter_key, started_at, finished_at, status
                ) VALUES (%s, %s, %s, %s, 'succeeded')
                """,
                (
                    f"complete-replace-newer-{suffix}",
                    adapter_key,
                    newer_job_at,
                    newer_job_at,
                ),
            )

        writer.write_pipeline_status(
            adapter_keys=(adapter_key,),
            status="succeeded",
            complete=True,
            checked_at=blocked_at,
            run_at=blocked_at,
            active_snapshot_raw_ref=raw_c,
        )

        with psycopg.connect(database_url) as connection:
            row = connection.execute(
                """
                SELECT
                    metadata->>'active_snapshot_raw_ref',
                    runtime_pipeline_status,
                    runtime_pipeline_complete,
                    runtime_pipeline_run_at
                FROM data_sources
                WHERE adapter_key = %s
                """,
                (adapter_key,),
            ).fetchone()
        assert row == (raw_b, "failed", False, failed_at)
    finally:
        with psycopg.connect(database_url) as connection:
            connection.execute(
                "DELETE FROM ingestion_jobs WHERE adapter_key = %s",
                (adapter_key,),
            )
            connection.execute(
                "DELETE FROM data_sources WHERE adapter_key = %s",
                (adapter_key,),
            )


@pytest.mark.parametrize(("first_value", "second_value"), [(3.2, 9.9), (9.9, 3.2)])
def test_absent_latest_key_is_serialized_without_equal_time_overwrite(
    database_url: str,
    first_value: float,
    second_value: float,
) -> None:
    suffix = uuid4().hex
    station_id = f"RACE-{suffix}"
    staging_fixtures = _insert_staging_candidates(database_url, suffix, 2)
    first_has_lock = Event()
    release_first = Event()
    second_attempted = Event()
    second_acquired = Event()
    results: dict[str, str | None] = {}
    errors: dict[str, BaseException] = {}

    first_writer = PostgresEvidencePromotionWriter(
        connection_factory=_gated_connection_factory(
            database_url,
            lock_predicate=lambda key: key.startswith("official-realtime-dedupe|"),
            acquired=first_has_lock,
            release=release_first,
        )
    )
    second_application_name = f"task8-absent-wait-{suffix}"
    second_writer = PostgresEvidencePromotionWriter(
        connection_factory=_gated_connection_factory(
            database_url,
            lock_predicate=lambda key: key.startswith("official-realtime-dedupe|"),
            attempted=second_attempted,
            acquired=second_acquired,
            release=None,
            application_name=second_application_name,
        )
    )
    first_payload = _water_payload(
        station_id=station_id,
        value=first_value,
        staging=staging_fixtures[0],
    )
    second_payload = _water_payload(
        station_id=station_id,
        value=second_value,
        staging=staging_fixtures[1],
    )
    _bind_staging_payload(database_url, first_payload)
    _bind_staging_payload(database_url, second_payload)

    first_thread = Thread(
        target=lambda: _capture_write(
            "first", first_writer, first_payload, results, errors
        )
    )

    def run_second() -> None:
        _capture_write("second", second_writer, second_payload, results, errors)

    second_thread = Thread(target=run_second)
    try:
        first_thread.start()
        assert first_has_lock.wait(5)
        second_thread.start()
        assert second_attempted.wait(5)
        assert _wait_for_advisory_wait(database_url, second_application_name)
        assert not second_acquired.is_set()
        release_first.set()
        first_thread.join(10)
        second_thread.join(10)
        assert not first_thread.is_alive()
        assert not second_thread.is_alive()
        assert second_acquired.is_set()
        assert errors == {}
        assert results["first"] is not None
        assert results["second"] is None

        import psycopg

        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT water_level_m, count(*) OVER ()
                FROM official_realtime_latest
                WHERE adapter_key = 'official.wra.water_level'
                    AND event_type = 'water_level'
                    AND station_id = %s
                """,
                (station_id,),
            )
            assert cursor.fetchone() == (first_value, 1)
            cursor.execute(
                "SELECT validation_status, rejection_reason FROM staging_evidence WHERE id = %s",
                (staging_fixtures[1]["staging_id"],),
            )
            assert cursor.fetchone() == ("rejected", "conflicting_latest")
    finally:
        release_first.set()
        _cleanup_race(database_url, suffix, station_id, staging_fixtures)


def test_same_staging_concurrent_retry_is_consumed_once_without_rejection(
    database_url: str,
) -> None:
    suffix = uuid4().hex
    station_id = f"SAME-STAGING-{suffix}"
    staging_fixtures = _insert_staging_candidates(database_url, suffix, 1)
    first_has_lock = Event()
    release_first = Event()
    results: dict[str, str | None] = {}
    errors: dict[str, BaseException] = {}
    second_started = Event()
    payload = _water_payload(
        station_id=station_id,
        value=3.2,
        staging=staging_fixtures[0],
    )
    _bind_staging_payload(database_url, payload)
    first_writer = PostgresEvidencePromotionWriter(
        connection_factory=_gated_connection_factory(
            database_url,
            lock_predicate=lambda key: key.startswith("official-realtime-dedupe|"),
            acquired=first_has_lock,
            release=release_first,
        )
    )
    second_application_name = f"task8-same-staging-wait-{suffix}"
    second_writer = PostgresEvidencePromotionWriter(
        connection_factory=lambda: _named_connection(
            database_url, second_application_name
        )
    )
    first_thread = Thread(
        target=lambda: _capture_write("first", first_writer, payload, results, errors)
    )
    def run_second() -> None:
        second_started.set()
        _capture_write("second", second_writer, payload, results, errors)

    second_thread = Thread(target=run_second)
    try:
        first_thread.start()
        assert first_has_lock.wait(5)
        second_thread.start()
        assert second_started.wait(5)
        assert _wait_for_database_lock(database_url, second_application_name)
        release_first.set()
        first_thread.join(10)
        second_thread.join(10)
        assert not first_thread.is_alive()
        assert not second_thread.is_alive()
        assert errors == {}
        assert results["first"] is not None
        assert results["second"] is None

        import psycopg

        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT validation_status, rejection_reason FROM staging_evidence WHERE id = %s",
                (staging_fixtures[0]["staging_id"],),
            )
            assert cursor.fetchone() == ("accepted", None)
            cursor.execute(
                "SELECT count(*) FROM evidence WHERE source_id = %s",
                (payload.source_id,),
            )
            assert cursor.fetchone() == (1,)
    finally:
        release_first.set()
        _cleanup_race(database_url, suffix, station_id, staging_fixtures)


@pytest.mark.parametrize("commit_order", ["update_first", "cancel_first"])
def test_cross_adapter_update_cancel_share_global_origin_lock(
    database_url: str,
    commit_order: str,
) -> None:
    suffix = uuid4().hex
    update_identifier = f"update-{suffix}"
    shared_origin = "official-warning-origin|" + cap_message_digest(
        sender="sender@example.test",
        identifier=update_identifier,
        sent=NOW,
    )
    acquired = Event()
    release = Event()
    second_attempted = Event()
    second_acquired = Event()
    results: dict[str, str | None] = {}
    errors: dict[str, BaseException] = {}
    update = _cap_update_payload(suffix, update_identifier)
    cancel = _cap_cancel_payload(suffix, update_identifier)
    first_payload, second_payload = (
        (update, cancel) if commit_order == "update_first" else (cancel, update)
    )
    first_writer = PostgresEvidencePromotionWriter(
        connection_factory=_gated_connection_factory(
            database_url,
            lock_predicate=lambda key: key == shared_origin,
            acquired=acquired,
            release=release,
        )
    )
    second_application_name = f"task8-cap-wait-{suffix}"
    second_writer = PostgresEvidencePromotionWriter(
        connection_factory=_gated_connection_factory(
            database_url,
            lock_predicate=lambda key: key == shared_origin,
            attempted=second_attempted,
            acquired=second_acquired,
            release=None,
            application_name=second_application_name,
        )
    )
    first_thread = Thread(
        target=lambda: _capture_write(
            "first", first_writer, first_payload, results, errors
        )
    )
    second_thread = Thread(
        target=lambda: _capture_write(
            "second", second_writer, second_payload, results, errors
        )
    )
    try:
        first_thread.start()
        assert acquired.wait(5)
        second_thread.start()
        assert second_attempted.wait(5)
        assert _wait_for_advisory_wait(database_url, second_application_name)
        assert not second_acquired.is_set()
        release.set()
        first_thread.join(10)
        second_thread.join(10)
        assert not first_thread.is_alive()
        assert not second_thread.is_alive()
        assert second_acquired.is_set()
        assert errors == {}
        if commit_order == "update_first":
            assert results["first"] is not None
            assert results["second"] is not None
        else:
            assert results["first"] is not None
            assert results["second"] is None

        import psycopg

        station_id = "cap:67000000:" + cap_message_digest(
            sender="sender@example.test", identifier=update_identifier, sent=NOW
        )
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT count(*)
                FROM official_realtime_latest
                WHERE event_type = 'flood_warning' AND station_id = %s
                """,
                (station_id,),
            )
            assert cursor.fetchone() == (0,)
            cursor.execute(
                "SELECT count(*) FROM evidence WHERE source_id LIKE %s",
                (f"task8-cap-{suffix}-%",),
            )
            assert cursor.fetchone() == ((2,) if commit_order == "update_first" else (1,))
    finally:
        release.set()
        _cleanup_cap_race(database_url, suffix)


@pytest.mark.parametrize("commit_order", ["empty_first", "alert_first"])
def test_older_empty_generation_never_retires_newer_alert(
    database_url: str,
    commit_order: str,
) -> None:
    latest_count, evidence_count = _race_no_active_and_warning_alert(
        database_url,
        empty_generation=NOW,
        alert_generation=NOW + timedelta(seconds=1),
        commit_order=commit_order,
    )

    assert latest_count == 1
    assert evidence_count == 1


@pytest.mark.parametrize("commit_order", ["empty_first", "alert_first"])
def test_newer_empty_generation_blocks_older_alert_resurrection(
    database_url: str,
    commit_order: str,
) -> None:
    latest_count, evidence_count = _race_no_active_and_warning_alert(
        database_url,
        empty_generation=NOW + timedelta(seconds=1),
        alert_generation=NOW,
        commit_order=commit_order,
    )

    assert latest_count == 0
    assert evidence_count == 1


def test_blocked_update_keeps_same_and_peer_referenced_warning_latest(
    database_url: str,
) -> None:
    import psycopg

    suffix = uuid4().hex
    cwa_adapter = "official.cwa.heavy_rain_warning"
    ncdr_adapter = "official.ncdr.cap"
    same_identifier = f"task9-same-alert-{suffix}"
    peer_identifier = f"task9-peer-alert-{suffix}"
    same_alert = _cap_payload(
        adapter_key=cwa_adapter,
        suffix=suffix,
        identifier=same_identifier,
        message_type="Alert",
        admin_code="67000000",
        references=[],
        geometry=True,
        sent=NOW,
    )
    peer_alert = _cap_payload(
        adapter_key=ncdr_adapter,
        suffix=suffix,
        identifier=peer_identifier,
        message_type="Alert",
        admin_code="64000000",
        references=[],
        geometry=True,
        sent=NOW + timedelta(minutes=1),
    )
    update = _cap_payload(
        adapter_key=cwa_adapter,
        suffix=suffix,
        identifier=f"task9-blocked-update-{suffix}",
        message_type="Update",
        admin_code="67000000",
        references=[
            {
                "sender": "sender@example.test",
                "identifier": same_identifier,
                "sent": NOW.isoformat(),
            },
            {
                "sender": "sender@example.test",
                "identifier": peer_identifier,
                "sent": (NOW + timedelta(minutes=1)).isoformat(),
            },
        ],
        geometry=True,
        sent=NOW + timedelta(minutes=5),
    )
    for alert in (same_alert, peer_alert):
        alert.properties["ingestion_generation_started_at"] = (
            NOW + timedelta(seconds=1)
        ).isoformat()
    writer = PostgresEvidencePromotionWriter(database_url=database_url)

    try:
        assert writer.write_evidence(same_alert) is not None
        assert writer.write_evidence(peer_alert) is not None
        _insert_no_active_job(
            database_url,
            suffix=suffix,
            adapter_key=cwa_adapter,
            generation=NOW,
        )

        update_evidence_id = writer.write_evidence(update)

        assert update_evidence_id is not None
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT adapter_key, source_id
                FROM official_realtime_latest
                WHERE source_id = ANY(%s)
                ORDER BY adapter_key, source_id
                """,
                ([same_alert.source_id, peer_alert.source_id],),
            )
            latest_rows = cursor.fetchall()
            cursor.execute(
                """
                SELECT
                    properties ->> 'evidence_scope',
                    properties ->> 'historical_reason'
                FROM evidence
                WHERE id = %s
                """,
                (update_evidence_id,),
            )
            update_state = cursor.fetchone()

        assert latest_rows == sorted(
            [
                (cwa_adapter, same_alert.source_id),
                (ncdr_adapter, peer_alert.source_id),
            ]
        )
        assert update_state == ("historical", "superseded_by_no_active_event")
    finally:
        _cleanup_cap_race(database_url, suffix)
        _cleanup_no_active_job(database_url, suffix=suffix)


@pytest.mark.parametrize("commit_order", ["update_first", "empty_marker_first"])
def test_update_and_empty_marker_race_preserves_newer_same_and_peer_latest(
    database_url: str,
    commit_order: str,
) -> None:
    surviving_rows, update_state = _race_update_and_no_active_marker(
        database_url,
        commit_order=commit_order,
    )

    assert surviving_rows == (
        "official.cwa.heavy_rain_warning",
        "official.ncdr.cap",
    )
    if commit_order == "empty_marker_first":
        assert update_state == ("historical", "superseded_by_no_active_event")


def test_no_active_retirement_preserves_peer_adapter_latest_and_audit_evidence(
    database_url: str,
) -> None:
    suffix = uuid4().hex
    cwa_adapter = "official.cwa.heavy_rain_warning"
    ncdr_adapter = "official.ncdr.cap"
    cwa_payload = _cap_payload(
        adapter_key=cwa_adapter,
        suffix=suffix,
        identifier=f"task9-cwa-{suffix}",
        message_type="Alert",
        admin_code="67000000",
        references=[],
        geometry=True,
        sent=NOW,
    )
    ncdr_payload = _cap_payload(
        adapter_key=ncdr_adapter,
        suffix=suffix,
        identifier=f"task9-ncdr-{suffix}",
        message_type="Alert",
        admin_code="64000000",
        references=[],
        geometry=True,
        sent=NOW,
    )
    writer = PostgresEvidencePromotionWriter(
        connection_factory=lambda: _named_connection(
            database_url, f"task9-cross-adapter-{suffix}"
        )
    )

    try:
        assert writer.write_evidence(cwa_payload) is not None
        assert writer.write_evidence(ncdr_payload) is not None

        retired = writer.retire_warning_latest_for_no_active_event(
            adapter_key=cwa_adapter,
            generation_started_at=NOW + timedelta(seconds=1),
            completed_at=NOW + timedelta(seconds=2),
        )

        import psycopg

        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT adapter_key, source_id
                FROM official_realtime_latest
                WHERE source_id = ANY(%s)
                ORDER BY adapter_key
                """,
                ([cwa_payload.source_id, ncdr_payload.source_id],),
            )
            latest_rows = cursor.fetchall()
            cursor.execute(
                "SELECT count(*) FROM evidence WHERE source_id = ANY(%s)",
                ([cwa_payload.source_id, ncdr_payload.source_id],),
            )
            evidence_count = int(cursor.fetchone()[0])

        assert retired == 1
        assert latest_rows == [(ncdr_adapter, ncdr_payload.source_id)]
        assert evidence_count == 2
    finally:
        _cleanup_cap_race(database_url, suffix)


def test_no_active_retirement_fails_closed_for_malformed_latest_generation(
    database_url: str,
) -> None:
    suffix = uuid4().hex
    adapter_key = "official.cwa.heavy_rain_warning"
    payload = _cap_payload(
        adapter_key=adapter_key,
        suffix=suffix,
        identifier=f"task9-malformed-generation-{suffix}",
        message_type="Alert",
        admin_code="67000000",
        references=[],
        geometry=True,
        sent=NOW,
    )
    writer = PostgresEvidencePromotionWriter(
        connection_factory=lambda: _named_connection(
            database_url, f"task9-malformed-generation-{suffix}"
        )
    )

    try:
        assert writer.write_evidence(payload) is not None

        import psycopg

        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE official_realtime_latest
                SET quality_flags = jsonb_set(
                    quality_flags,
                    '{ingestion_generation_started_at}',
                    '"malformed"'::jsonb
                )
                WHERE adapter_key = %s AND source_id = %s
                """,
                (adapter_key, payload.source_id),
            )

        retired = writer.retire_warning_latest_for_no_active_event(
            adapter_key=adapter_key,
            generation_started_at=NOW + timedelta(seconds=1),
            completed_at=NOW + timedelta(seconds=2),
        )

        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT count(*)
                FROM official_realtime_latest
                WHERE adapter_key = %s AND source_id = %s
                """,
                (adapter_key, payload.source_id),
            )
            latest_count = int(cursor.fetchone()[0])
            cursor.execute(
                "SELECT count(*) FROM evidence WHERE source_id = %s",
                (payload.source_id,),
            )
            evidence_count = int(cursor.fetchone()[0])

        assert retired == 0
        assert latest_count == 1
        assert evidence_count == 1
    finally:
        _cleanup_cap_race(database_url, suffix)


@pytest.mark.parametrize("arrival_order", ["central_first", "local_first"])
def test_live_exact_central_local_duplicate_always_keeps_central_latest(
    database_url: str,
    arrival_order: str,
) -> None:
    suffix = uuid4().hex
    central = _depth_payload(
        suffix=suffix,
        adapter_key="official.wra_iow.flood_depth",
        station_id=f"WRA-{suffix}",
        observed_at=NOW,
        value=12.0,
        longitude=120.2190,
        latitude=22.9160,
    )
    local = _depth_payload(
        suffix=suffix,
        adapter_key="local.tainan.flood_sensor",
        station_id=f"TN-{suffix}",
        observed_at=NOW,
        value=12.0,
        longitude=120.2195,
        latitude=22.9160,
    )
    first, second = (
        (central, local) if arrival_order == "central_first" else (local, central)
    )
    writer = PostgresEvidencePromotionWriter(database_url=database_url)
    try:
        first_result = writer.write_evidence(first)
        second_result = writer.write_evidence(second)

        assert first_result is not None
        if arrival_order == "central_first":
            assert second_result is None
        else:
            assert second_result is not None

        import psycopg

        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT adapter_key
                FROM official_realtime_latest
                WHERE station_id = ANY(%s)
                ORDER BY adapter_key
                """,
                ([central.properties["station_id"], local.properties["station_id"]],),
            )
            assert cursor.fetchall() == [("official.wra_iow.flood_depth",)]
            cursor.execute(
                "SELECT count(*) FROM evidence WHERE source_id LIKE %s",
                (f"task8-depth-{suffix}-%",),
            )
            assert cursor.fetchone() == (
                (1,) if arrival_order == "central_first" else (2,)
            )
    finally:
        _cleanup_depth_race(database_url, suffix, central, local)


@pytest.mark.parametrize("non_match", ["different_time", "different_value", "far_point"])
def test_live_central_local_negative_controls_keep_both_latest_rows(
    database_url: str,
    non_match: str,
) -> None:
    suffix = uuid4().hex
    central = _depth_payload(
        suffix=suffix,
        adapter_key="official.wra_iow.flood_depth",
        station_id=f"WRA-{suffix}",
        observed_at=NOW,
        value=12.0,
        longitude=120.2190,
        latitude=22.9160,
    )
    local = _depth_payload(
        suffix=suffix,
        adapter_key="local.tainan.flood_sensor",
        station_id=f"TN-{suffix}",
        observed_at=(NOW + timedelta(minutes=1) if non_match == "different_time" else NOW),
        value=13.0 if non_match == "different_value" else 12.0,
        longitude=121.0 if non_match == "far_point" else 120.2195,
        latitude=25.0 if non_match == "far_point" else 22.9160,
    )
    writer = PostgresEvidencePromotionWriter(database_url=database_url)
    try:
        assert writer.write_evidence(central) is not None
        assert writer.write_evidence(local) is not None

        import psycopg

        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT adapter_key
                FROM official_realtime_latest
                WHERE station_id = ANY(%s)
                ORDER BY adapter_key
                """,
                ([central.properties["station_id"], local.properties["station_id"]],),
            )
            assert cursor.fetchall() == [
                ("local.tainan.flood_sensor",),
                ("official.wra_iow.flood_depth",),
            ]
    finally:
        _cleanup_depth_race(database_url, suffix, central, local)


def test_reviewed_snapshot_resolves_real_multipolygon_and_point_on_surface(
    database_url: str,
) -> None:
    import psycopg

    suffix = uuid4().hex
    with psycopg.connect(database_url) as connection:
        try:
            _install_transactional_reviewed_snapshot(connection, suffix)
            writer = PostgresEvidencePromotionWriter(
                connection_factory=lambda: _BorrowedConnection(connection)
            )
            payload = _cap_payload(
                adapter_key="official.cwa.heavy_rain_warning",
                suffix=suffix,
                identifier=f"boundary-{suffix}",
                message_type="Alert",
                admin_code="67000000",
                references=[],
                geometry=False,
            )

            evidence_id = writer.write_evidence(payload)

            assert evidence_id is not None
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT GeometryType(e.geom), GeometryType(latest.geom)
                    FROM evidence e
                    JOIN official_realtime_latest latest ON latest.evidence_id = e.id
                    WHERE e.id = %s
                    """,
                    (evidence_id,),
                )
                assert cursor.fetchone() == ("MULTIPOLYGON", "POINT")
        finally:
            connection.rollback()


@pytest.mark.parametrize(
    "boundary_case",
    [
        "inactive",
        "unreviewed",
        "ambiguous_active",
        "checksum_mismatch",
        "exact_code_mismatch",
    ],
)
def test_live_boundary_negative_cases_remain_unlocated_audit_evidence(
    database_url: str,
    boundary_case: str,
) -> None:
    import psycopg

    suffix = uuid4().hex
    with psycopg.connect(database_url) as connection:
        try:
            _install_temp_boundary_case(connection, boundary_case, suffix)
            writer = PostgresEvidencePromotionWriter(
                connection_factory=lambda: _BorrowedConnection(connection)
            )
            payload = _cap_payload(
                adapter_key="official.cwa.heavy_rain_warning",
                suffix=suffix,
                identifier=f"boundary-negative-{suffix}",
                message_type="Alert",
                admin_code=(
                    "99999999" if boundary_case == "exact_code_mismatch" else "67000000"
                ),
                references=[],
                geometry=False,
            )

            evidence_id = writer.write_evidence(payload)

            assert evidence_id is not None
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT e.geom IS NULL, latest.evidence_id IS NULL
                    FROM evidence e
                    LEFT JOIN official_realtime_latest latest ON latest.evidence_id = e.id
                    WHERE e.id = %s
                    """,
                    (evidence_id,),
                )
                assert cursor.fetchone() == (True, True)
        finally:
            connection.rollback()


@pytest.mark.parametrize("message_type", ["Alert", "Update", "Cancel"])
def test_live_cap_canonical_replay_across_raw_refs_returns_none(
    database_url: str,
    message_type: str,
) -> None:
    suffix = uuid4().hex
    references = (
        []
        if message_type == "Alert"
        else [
            {
                "sender": "sender@example.test",
                "identifier": f"earlier-{suffix}",
                "sent": (NOW - timedelta(minutes=1)).isoformat(),
            }
        ]
    )
    canonical = _cap_payload(
        adapter_key="official.cwa.heavy_rain_warning",
        suffix=suffix,
        identifier=f"canonical-{message_type.lower()}-{suffix}",
        message_type=message_type,
        admin_code=None if message_type == "Cancel" else "67000000",
        references=references,
        geometry=message_type != "Cancel",
    )
    replay = replace(
        canonical,
        raw_ref=f"raw/task8-cap-{suffix}-{message_type.lower()}-replay.xml",
    )
    writer = PostgresEvidencePromotionWriter(database_url=database_url)
    try:
        first_id = writer.write_evidence(canonical)
        replay_id = writer.write_evidence(replay)

        assert first_id is not None
        assert replay_id is None

        import psycopg

        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM evidence WHERE source_id = %s",
                (canonical.source_id,),
            )
            assert cursor.fetchone() == (1,)
    finally:
        _cleanup_cap_race(database_url, suffix)


def test_live_cap_identity_keeps_adapters_and_admin_areas_physically_separate(
    database_url: str,
) -> None:
    suffix = uuid4().hex
    identifier = f"matrix-{suffix}"
    cwa_tainan = _cap_payload(
        adapter_key="official.cwa.heavy_rain_warning",
        suffix=suffix,
        identifier=identifier,
        message_type="Alert",
        admin_code="67000000",
        references=[],
        geometry=True,
    )
    ncdr_tainan = replace(
        cwa_tainan,
        adapter_key="official.ncdr.cap",
        raw_ref=f"raw/task8-cap-{suffix}-ncdr-tainan.xml",
    )
    cwa_kaohsiung = replace(
        cwa_tainan,
        source_id=f"task8-cap-{suffix}-{identifier}-64000000",
        raw_ref=f"raw/task8-cap-{suffix}-cwa-kaohsiung.xml",
        properties={**cwa_tainan.properties, "admin_code": "64000000"},
    )
    writer = PostgresEvidencePromotionWriter(database_url=database_url)
    try:
        assert writer.write_evidence(cwa_tainan) is not None
        assert writer.write_evidence(ncdr_tainan) is not None
        assert writer.write_evidence(cwa_kaohsiung) is not None

        import psycopg

        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM evidence WHERE source_id LIKE %s",
                (f"task8-cap-{suffix}-%",),
            )
            assert cursor.fetchone() == (3,)
    finally:
        _cleanup_cap_race(database_url, suffix)


@pytest.mark.parametrize("message_type", ["Update", "Cancel"])
def test_live_stale_mixed_cap_mutation_cannot_retire_or_tombstone_later_alert(
    database_url: str,
    message_type: str,
) -> None:
    import psycopg

    suffix = uuid4().hex
    stale_sent = NOW + timedelta(minutes=5)
    later_sent = NOW + timedelta(minutes=10)
    later_identifier = f"later-{suffix}"
    later = _cap_payload(
        adapter_key="official.cwa.heavy_rain_warning",
        suffix=suffix,
        identifier=later_identifier,
        message_type="Alert",
        admin_code="67000000",
        references=[],
        geometry=True,
        sent=later_sent,
    )
    stale = _cap_payload(
        adapter_key="official.ncdr.cap",
        suffix=suffix,
        identifier=f"stale-{message_type.lower()}-{suffix}",
        message_type=message_type,
        admin_code=None if message_type == "Cancel" else "64000000",
        references=[
            {
                "sender": "sender@example.test",
                "identifier": f"earlier-{suffix}",
                "sent": NOW.isoformat(),
            },
            {
                "sender": "sender@example.test",
                "identifier": later_identifier,
                "sent": later_sent.isoformat(),
            },
        ],
        geometry=message_type == "Update",
        sent=stale_sent,
    )
    later_station_id = "cap:67000000:" + cap_message_digest(
        sender="sender@example.test",
        identifier=later_identifier,
        sent=later_sent,
    )
    writer = PostgresEvidencePromotionWriter(database_url=database_url)
    try:
        later_evidence_id = writer.write_evidence(later)
        assert later_evidence_id is not None
        assert writer.write_evidence(stale) is not None

        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM official_realtime_latest WHERE station_id = %s",
                (later_station_id,),
            )
            assert cursor.fetchone() == (1,)
            cursor.execute(
                "DELETE FROM official_realtime_latest WHERE evidence_id = %s",
                (later_evidence_id,),
            )
            cursor.execute("DELETE FROM evidence WHERE id = %s", (later_evidence_id,))

        replay = replace(
            later,
            raw_ref=f"raw/task8-cap-{suffix}-later-replay.xml",
        )
        assert writer.write_evidence(replay) is not None
    finally:
        _cleanup_cap_race(database_url, suffix)


@pytest.mark.parametrize(
    "invalid_geometry",
    [
        pytest.param(
            {
                "type": "MultiPolygon",
                "coordinates": [
                    [[[999.0, 23.0], [1000.0, 23.0], [1000.0, 24.0], [999.0, 23.0]]]
                ],
            },
            id="out_of_range",
        ),
        pytest.param(
            {"type": "MultiPolygon", "coordinates": []},
            id="empty",
        ),
        pytest.param(
            {
                "type": "MultiPolygon",
                "coordinates": [
                    [
                        [
                            [120.0, 23.0],
                            [121.0, 24.0],
                            [121.0, 23.0],
                            [120.0, 24.0],
                            [120.0, 23.0],
                        ]
                    ]
                ],
            },
            id="invalid_topology",
        ),
        pytest.param(
            {"type": "LineString", "coordinates": [[120.0, 23.0], [121.0, 24.0]]},
            id="wrong_type",
        ),
        pytest.param(
            {
                "type": "MultiPolygon",
                "coordinates": [
                    [[[120.0, 23.0], [float("inf"), 23.0], [121.0, 24.0], [120.0, 23.0]]]
                ],
            },
            id="non_finite",
        ),
    ],
)
def test_live_invalid_cap_area_update_preserves_referenced_alert(
    database_url: str,
    invalid_geometry: dict[str, Any],
) -> None:
    import psycopg

    suffix = uuid4().hex
    alert_identifier = f"geometry-alert-{suffix}"
    alert = _cap_payload(
        adapter_key="official.cwa.heavy_rain_warning",
        suffix=suffix,
        identifier=alert_identifier,
        message_type="Alert",
        admin_code="67000000",
        references=[],
        geometry=True,
        sent=NOW,
    )
    update = _cap_payload(
        adapter_key="official.ncdr.cap",
        suffix=suffix,
        identifier=f"geometry-update-{suffix}",
        message_type="Update",
        admin_code="67000000",
        references=[
            {
                "sender": "sender@example.test",
                "identifier": alert_identifier,
                "sent": NOW.isoformat(),
            }
        ],
        geometry=True,
        sent=NOW + timedelta(minutes=5),
    )
    update.properties["location_payload"] = {"geometry": invalid_geometry}
    staging_fixture: dict[str, str] | None = None
    if _jsonb_representable(invalid_geometry):
        update, staging_fixture = _insert_staged_payload(database_url, update)
    alert_station_id = "cap:67000000:" + cap_message_digest(
        sender="sender@example.test",
        identifier=alert_identifier,
        sent=NOW,
    )
    writer = PostgresEvidencePromotionWriter(database_url=database_url)
    try:
        alert_evidence_id = writer.write_evidence(alert)
        assert alert_evidence_id is not None

        assert writer.write_evidence(update) is None

        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM evidence WHERE id = %s", (alert_evidence_id,))
            assert cursor.fetchone() == (1,)
            cursor.execute(
                """
                SELECT count(*)
                FROM official_realtime_latest
                WHERE station_id = %s AND evidence_id = %s
                """,
                (alert_station_id, alert_evidence_id),
            )
            assert cursor.fetchone() == (1,)
            cursor.execute(
                "SELECT count(*) FROM evidence WHERE source_id = %s",
                (update.source_id,),
            )
            assert cursor.fetchone() == (0,)
            if staging_fixture is not None:
                cursor.execute(
                    """
                    SELECT validation_status, rejection_reason
                    FROM staging_evidence
                    WHERE id = %s
                    """,
                    (staging_fixture["staging_id"],),
                )
                assert cursor.fetchone() == ("rejected", "invalid_geometry")
    finally:
        _cleanup_cap_race(database_url, suffix)
        if staging_fixture is not None:
            _cleanup_staged_payload(database_url, staging_fixture)


def test_live_generic_natural_key_race_returns_one_id_and_one_none(
    database_url: str,
) -> None:
    suffix = uuid4().hex
    payload = EvidencePromotionPayload(
        data_source_id=None,
        adapter_key="news.public_web.sample",
        source_id=f"task8-generic-race-{suffix}",
        source_type="news",
        event_type="flood_report",
        title="generic race",
        summary="generic natural-key race",
        url="https://example.test/generic-race",
        occurred_at=NOW,
        observed_at=NOW,
        confidence=0.7,
        raw_ref=f"raw/task8-generic-race-{suffix}.json",
        properties={
            "adapter_key": "news.public_web.sample",
            "evidence_scope": "context",
            "location_precision": "unknown",
        },
    )
    ready = Event()
    insert_barrier = Barrier(2)
    results: dict[str, str | None] = {}
    errors: dict[str, BaseException] = {}

    def race(name: str) -> None:
        assert ready.wait(5)
        _capture_write(
            name,
            PostgresEvidencePromotionWriter(
                connection_factory=lambda: _insert_barrier_connection(
                    database_url, insert_barrier
                )
            ),
            payload,
            results,
            errors,
        )

    threads = [Thread(target=race, args=(name,)) for name in ("first", "second")]
    try:
        for thread in threads:
            thread.start()
        ready.set()
        for thread in threads:
            thread.join(10)
        assert all(not thread.is_alive() for thread in threads)
        assert errors == {}
        assert sorted(value is None for value in results.values()) == [False, True]

        import psycopg

        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM evidence WHERE source_id = %s",
                (payload.source_id,),
            )
            assert cursor.fetchone() == (1,)
    finally:
        import psycopg

        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute("DELETE FROM evidence WHERE source_id = %s", (payload.source_id,))


def test_live_distinct_authorized_natural_key_loser_is_terminally_consumed(
    database_url: str,
) -> None:
    import psycopg

    suffix = uuid4().hex
    direct = EvidencePromotionPayload(
        data_source_id=None,
        adapter_key="news.public_web.sample",
        source_id=f"task8-staged-natural-race-{suffix}",
        source_type="news",
        event_type="flood_report",
        title="staged generic race",
        summary="two authorized rows share one evidence natural key",
        url="https://example.test/staged-generic-race",
        occurred_at=NOW,
        observed_at=NOW,
        confidence=0.7,
        raw_ref=f"raw/task8-staged-natural-race-{suffix}.json",
        properties={
            "adapter_key": "news.public_web.sample",
            "evidence_scope": "context",
            "location_precision": "unknown",
        },
    )
    first, fixture = _insert_staged_payload(database_url, direct)
    second, second_staging_id = _duplicate_staged_payload(
        database_url, first, fixture["staging_id"]
    )
    payloads = {"first": first, "second": second}
    ready = Event()
    insert_barrier = Barrier(2)
    results: dict[str, str | None] = {}
    errors: dict[str, BaseException] = {}

    def race(name: str) -> None:
        assert ready.wait(5)
        _capture_write(
            name,
            PostgresEvidencePromotionWriter(
                connection_factory=lambda: _insert_barrier_connection(
                    database_url, insert_barrier
                )
            ),
            payloads[name],
            results,
            errors,
        )

    threads = [Thread(target=race, args=(name,)) for name in payloads]
    try:
        for thread in threads:
            thread.start()
        ready.set()
        for thread in threads:
            thread.join(10)
        assert all(not thread.is_alive() for thread in threads)
        assert errors == {}
        assert sorted(value is None for value in results.values()) == [False, True]
        winner = next(name for name, value in results.items() if value is not None)
        loser = next(name for name, value in results.items() if value is None)

        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id::text, validation_status, rejection_reason
                FROM staging_evidence
                WHERE id = ANY(%s::uuid[])
                ORDER BY id
                """,
                ([fixture["staging_id"], second_staging_id],),
            )
            rows = {row[0]: row[1:] for row in cursor.fetchall()}
            assert rows[payloads[winner].properties["staging_evidence_id"]] == (
                "accepted",
                None,
            )
            assert rows[payloads[loser].properties["staging_evidence_id"]] == (
                "rejected",
                "idempotent_existing_evidence",
            )
            cursor.execute(
                "SELECT count(*) FROM evidence WHERE source_id = %s",
                (direct.source_id,),
            )
            assert cursor.fetchone() == (1,)

        fetched_ids = {
            candidate.staging_evidence_id
            for candidate in PostgresEvidencePromotionWriter(
                database_url=database_url
            ).fetch_accepted_staging(adapter_keys=("news.public_web.sample",))
        }
        assert payloads[loser].properties["staging_evidence_id"] not in fetched_ids
    finally:
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute("DELETE FROM evidence WHERE source_id = %s", (direct.source_id,))
        _cleanup_staged_payload(
            database_url,
            fixture,
            extra_staging_ids=(second_staging_id,),
        )


@pytest.mark.parametrize(
    "mismatch",
    [
        "source_id",
        "data_source_id",
        "source_type",
        "raw_ref",
        "adapter_key",
        "event_type",
        "occurred_at",
        "observed_at",
        "raw_snapshot_id",
        "title",
        "summary",
        "url",
        "confidence",
        "metric",
        "geometry",
    ],
)
def test_live_forged_staging_identity_is_inert(
    database_url: str,
    mismatch: str,
) -> None:
    suffix = uuid4().hex
    station_id = f"FORGED-{suffix}"
    staging_fixtures = _insert_staging_candidates(database_url, suffix, 1)
    payload = _water_payload(
        station_id=station_id,
        value=3.2,
        staging=staging_fixtures[0],
    )
    _bind_staging_payload(database_url, payload)
    properties = dict(payload.properties)
    replacements: dict[str, object] = {}
    if mismatch == "source_id":
        replacements["source_id"] = f"forged-{suffix}"
    elif mismatch == "data_source_id":
        replacements["data_source_id"] = staging_fixtures[0]["other_data_source_id"]
    elif mismatch == "source_type":
        replacements["source_type"] = "news"
    elif mismatch == "raw_ref":
        replacements["raw_ref"] = f"raw/forged-{suffix}.json"
    elif mismatch == "adapter_key":
        replacements["adapter_key"] = "official.cwa.rainfall"
    elif mismatch == "event_type":
        replacements["event_type"] = "rainfall"
    elif mismatch == "occurred_at":
        replacements["occurred_at"] = NOW + timedelta(seconds=1)
    elif mismatch == "observed_at":
        replacements["observed_at"] = NOW + timedelta(seconds=1)
    elif mismatch == "raw_snapshot_id":
        properties["raw_snapshot_id"] = str(uuid4())
    elif mismatch == "title":
        replacements["title"] = "forged title"
    elif mismatch == "summary":
        replacements["summary"] = "forged summary"
    elif mismatch == "url":
        replacements["url"] = "https://example.test/forged"
    elif mismatch == "confidence":
        replacements["confidence"] = 0.1
    elif mismatch == "metric":
        properties["water_level_m"] = 999.0
    else:
        properties["location_payload"] = {
            "geometry": {"type": "Point", "coordinates": [121.5, 25.0]}
        }
    forged = replace(payload, properties=properties, **replacements)
    try:
        writer = PostgresEvidencePromotionWriter(database_url=database_url)

        assert writer.write_evidence(forged) is None

        import psycopg

        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT validation_status, rejection_reason FROM staging_evidence WHERE id = %s",
                (staging_fixtures[0]["staging_id"],),
            )
            assert cursor.fetchone() == ("accepted", None)
            cursor.execute(
                "SELECT count(*) FROM evidence WHERE source_id IN (%s, %s)",
                (payload.source_id, f"forged-{suffix}"),
            )
            assert cursor.fetchone() == (0,)
            cursor.execute(
                "SELECT count(*) FROM official_realtime_latest WHERE station_id = %s",
                (station_id,),
            )
            assert cursor.fetchone() == (0,)
    finally:
        _cleanup_race(database_url, suffix, station_id, staging_fixtures)


@pytest.mark.parametrize(
    ("field", "forged_value"),
    [
        ("cap_identifier", "forged-identifier"),
        ("cap_status", "Test"),
        (
            "cap_references",
            [
                {
                    "sender": "sender@example.test",
                    "identifier": "unreviewed-reference",
                    "sent": NOW.isoformat(),
                }
            ],
        ),
        ("active_until", "2027-08-25T00:00:00+00:00"),
        ("ingestion_generation_started_at", (NOW + timedelta(minutes=1)).isoformat()),
    ],
)
def test_live_forged_cap_lifecycle_content_is_inert(
    database_url: str,
    field: str,
    forged_value: object,
) -> None:
    import psycopg

    suffix = uuid4().hex
    direct = _cap_payload(
        adapter_key="official.ncdr.cap",
        suffix=suffix,
        identifier=f"authorized-cap-{suffix}",
        message_type="Alert",
        admin_code="67000000",
        references=[],
        geometry=True,
    )
    staged, fixture = _insert_staged_payload(database_url, direct)
    forged = replace(
        staged,
        properties={**staged.properties, field: forged_value},
    )
    try:
        assert (
            PostgresEvidencePromotionWriter(database_url=database_url).write_evidence(
                forged
            )
            is None
        )

        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT validation_status, rejection_reason
                FROM staging_evidence
                WHERE id = %s
                """,
                (fixture["staging_id"],),
            )
            assert cursor.fetchone() == ("accepted", None)
            cursor.execute(
                "SELECT count(*) FROM evidence WHERE source_id = %s",
                (staged.source_id,),
            )
            assert cursor.fetchone() == (0,)
    finally:
        _cleanup_cap_race(database_url, suffix)
        _cleanup_staged_payload(database_url, fixture)


def _insert_staging_candidates(
    database_url: str, suffix: str, count: int
) -> tuple[dict[str, str], ...]:
    import psycopg

    fixtures: list[dict[str, str]] = []
    with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                (SELECT id::text FROM data_sources
                    WHERE adapter_key = 'official.wra.water_level'),
                (SELECT id::text FROM data_sources
                    WHERE adapter_key = 'news.public_web.sample')
            """
        )
        data_source_id, other_data_source_id = cursor.fetchone()
        assert data_source_id is not None
        assert other_data_source_id is not None
        for index in range(count):
            source_id = f"task8-race-{suffix}-{index}"
            raw_ref = f"raw/task8-race-{suffix}-{index}.json"
            cursor.execute(
                """
                INSERT INTO raw_snapshots (
                    data_source_id, adapter_key, raw_ref, fetched_at
                )
                VALUES (
                    (SELECT id FROM data_sources WHERE adapter_key = 'official.wra.water_level'),
                    'official.wra.water_level', %s, %s
                )
                RETURNING id
                """,
                (raw_ref, NOW),
            )
            raw_snapshot_id = str(cursor.fetchone()[0])
            cursor.execute(
                """
                INSERT INTO staging_evidence (
                    raw_snapshot_id, data_source_id, source_id, source_type,
                    event_type, title, summary,
                    occurred_at, observed_at, confidence, validation_status, payload
                )
                VALUES (
                    %s,
                    (SELECT id FROM data_sources WHERE adapter_key = 'official.wra.water_level'),
                    %s, 'official', 'water_level', 'race', 'race', %s, %s, 0.9,
                    'accepted', '{"adapter_key":"official.wra.water_level"}'::jsonb
                )
                RETURNING id
                """,
                (raw_snapshot_id, source_id, NOW, NOW),
            )
            fixtures.append(
                {
                    "staging_id": str(cursor.fetchone()[0]),
                    "raw_snapshot_id": raw_snapshot_id,
                    "data_source_id": data_source_id,
                    "other_data_source_id": other_data_source_id,
                    "source_id": source_id,
                    "raw_ref": raw_ref,
                }
            )
    return tuple(fixtures)


def _insert_staged_payload(
    database_url: str,
    payload: EvidencePromotionPayload,
) -> tuple[EvidencePromotionPayload, dict[str, str]]:
    import psycopg

    with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO raw_snapshots (
                data_source_id, adapter_key, raw_ref, fetched_at
            )
            VALUES (
                (SELECT id FROM data_sources WHERE adapter_key = %s),
                %s, %s, %s
            )
            RETURNING id, data_source_id
            """,
            (payload.adapter_key, payload.adapter_key, payload.raw_ref, NOW),
        )
        raw_snapshot_id, data_source_id = cursor.fetchone()
        stored_properties = {
            key: value
            for key, value in payload.properties.items()
            if key not in {"staging_evidence_id", "raw_snapshot_id"}
        }
        cursor.execute(
            """
            INSERT INTO staging_evidence (
                raw_snapshot_id, data_source_id, source_id, source_type,
                event_type, title, summary, url, occurred_at, observed_at,
                confidence, validation_status, payload
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                'accepted', %s::jsonb
            )
            RETURNING id
            """,
            (
                raw_snapshot_id,
                data_source_id,
                payload.source_id,
                payload.source_type,
                payload.event_type,
                payload.title,
                payload.summary,
                payload.url,
                payload.occurred_at,
                payload.observed_at,
                payload.confidence,
                json.dumps(stored_properties, sort_keys=True, separators=(",", ":")),
            ),
        )
        staging_id = cursor.fetchone()[0]
    fixture = {
        "staging_id": str(staging_id),
        "raw_snapshot_id": str(raw_snapshot_id),
    }
    return (
        replace(
            payload,
            data_source_id=str(data_source_id) if data_source_id is not None else None,
            properties={
                **stored_properties,
                "staging_evidence_id": str(staging_id),
                "raw_snapshot_id": str(raw_snapshot_id),
            },
        ),
        fixture,
    )


def _jsonb_representable(value: object) -> bool:
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError):
        return False
    return True


def _duplicate_staged_payload(
    database_url: str,
    payload: EvidencePromotionPayload,
    staging_id: str,
) -> tuple[EvidencePromotionPayload, str]:
    import psycopg

    with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO staging_evidence (
                raw_snapshot_id, data_source_id, source_id, source_type,
                event_type, title, summary, url, occurred_at, observed_at,
                confidence, validation_status, rejection_reason, payload
            )
            SELECT
                raw_snapshot_id, data_source_id, source_id, source_type,
                event_type, title, summary, url, occurred_at, observed_at,
                confidence, validation_status, rejection_reason, payload
            FROM staging_evidence
            WHERE id = %s
            RETURNING id
            """,
            (staging_id,),
        )
        duplicate_id = str(cursor.fetchone()[0])
    return (
        replace(
            payload,
            properties={
                **payload.properties,
                "staging_evidence_id": duplicate_id,
            },
        ),
        duplicate_id,
    )


def _water_payload(
    *, station_id: str, value: float, staging: dict[str, str]
) -> EvidencePromotionPayload:
    return EvidencePromotionPayload(
        data_source_id=staging["data_source_id"],
        adapter_key="official.wra.water_level",
        source_id=staging["source_id"],
        source_type="official",
        event_type="water_level",
        title="race",
        summary="race",
        url=None,
        occurred_at=NOW,
        observed_at=NOW,
        confidence=0.9,
        raw_ref=staging["raw_ref"],
        properties={
            "evidence_scope": "current",
            "station_id": station_id,
            "water_level_m": value,
            "warning_level_m": 4.0,
            "location_precision": "point",
            "staging_evidence_id": staging["staging_id"],
            "raw_snapshot_id": staging["raw_snapshot_id"],
            "location_payload": {
                "geometry": {"type": "Point", "coordinates": [120.2, 23.0]}
            },
        },
    )


def _bind_staging_payload(
    database_url: str,
    payload: EvidencePromotionPayload,
) -> None:
    import psycopg

    stored_properties = {
        key: value
        for key, value in payload.properties.items()
        if key not in {"staging_evidence_id", "raw_snapshot_id"}
    }
    with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE staging_evidence
            SET title = %s,
                summary = %s,
                url = %s,
                confidence = %s,
                payload = %s::jsonb
            WHERE id = %s
            """,
            (
                payload.title,
                payload.summary,
                payload.url,
                payload.confidence,
                json.dumps(stored_properties, sort_keys=True, separators=(",", ":")),
                payload.properties["staging_evidence_id"],
            ),
        )


def _depth_payload(
    *,
    suffix: str,
    adapter_key: str,
    station_id: str,
    observed_at: datetime,
    value: float,
    longitude: float,
    latitude: float,
) -> EvidencePromotionPayload:
    source_id = f"task8-depth-{suffix}-{adapter_key}-{station_id}"
    return EvidencePromotionPayload(
        data_source_id=None,
        adapter_key=adapter_key,
        source_id=source_id,
        source_type="official",
        event_type="flood_report",
        title="depth",
        summary="depth",
        url=None,
        occurred_at=observed_at,
        observed_at=observed_at,
        confidence=0.9,
        raw_ref=f"raw/{source_id}.json",
        properties={
            "evidence_scope": "current",
            "station_id": station_id,
            "flood_depth_cm": value,
            "location_precision": "point",
            "ingestion_generation_started_at": observed_at.isoformat(),
            "location_payload": {
                "geometry": {
                    "type": "Point",
                    "coordinates": [longitude, latitude],
                }
            },
        },
    )


def _cap_update_payload(suffix: str, identifier: str) -> EvidencePromotionPayload:
    previous = {
        "sender": "sender@example.test",
        "identifier": f"alert-{suffix}",
        "sent": "2026-08-24T00:00:00+00:00",
    }
    return _cap_payload(
        adapter_key="official.cwa.heavy_rain_warning",
        suffix=suffix,
        identifier=identifier,
        message_type="Update",
        admin_code="67000000",
        references=[previous],
        geometry=True,
    )


def _cap_cancel_payload(suffix: str, update_identifier: str) -> EvidencePromotionPayload:
    reference = {
        "sender": "sender@example.test",
        "identifier": update_identifier,
        "sent": NOW.isoformat(),
    }
    return _cap_payload(
        adapter_key="official.ncdr.cap",
        suffix=suffix,
        identifier=f"cancel-{suffix}",
        message_type="Cancel",
        admin_code=None,
        references=[reference],
        geometry=False,
        sent=NOW + timedelta(minutes=1),
    )


def _cap_payload(
    *,
    adapter_key: str,
    suffix: str,
    identifier: str,
    message_type: str,
    admin_code: str | None,
    references: list[dict[str, str]],
    geometry: bool,
    sent: datetime = NOW,
) -> EvidencePromotionPayload:
    properties: dict[str, Any] = {
        "adapter_key": adapter_key,
        "evidence_scope": "current",
        "location_precision": "admin_area",
        "admin_code": admin_code,
        "cap_sender": "sender@example.test",
        "cap_identifier": identifier,
        "cap_sent": sent.isoformat(),
        "cap_references": references,
        "cap_status": "Actual",
        "cap_message_type": message_type,
        "active_from": "2026-08-24T00:00:00+00:00",
        "active_until": "2027-08-24T00:00:00+00:00",
        "ingestion_generation_started_at": NOW.isoformat(),
    }
    if geometry:
        properties.update(
            {
                "location_payload": {
                    "geometry": {
                        "type": "MultiPolygon",
                        "coordinates": [
                            [[[120.0, 22.8], [120.4, 22.8], [120.4, 23.2], [120.0, 22.8]]]
                        ],
                    }
                },
                "latest_point_geometry": {
                    "type": "Point",
                    "coordinates": [120.2, 23.0],
                },
            }
        )
    return EvidencePromotionPayload(
        data_source_id=None,
        adapter_key=adapter_key,
        source_id=f"task8-cap-{suffix}-{identifier}",
        source_type="official",
        event_type="flood_warning",
        title="CAP race",
        summary="CAP race",
        url=None,
        occurred_at=sent,
        observed_at=sent,
        confidence=0.95,
        raw_ref=f"raw/task8-cap-{suffix}-{identifier}.xml",
        properties=properties,
    )


def _capture_write(
    name: str,
    writer: PostgresEvidencePromotionWriter,
    payload: EvidencePromotionPayload,
    results: dict[str, str | None],
    errors: dict[str, BaseException],
) -> None:
    try:
        results[name] = writer.write_evidence(payload)
    except BaseException as exc:  # noqa: BLE001 - surfaced in the parent test thread
        errors[name] = exc


def _race_no_active_and_warning_alert(
    database_url: str,
    *,
    empty_generation: datetime,
    alert_generation: datetime,
    commit_order: str,
) -> tuple[int, int]:
    suffix = uuid4().hex
    adapter_key = "official.cwa.heavy_rain_warning"
    payload = _cap_payload(
        adapter_key=adapter_key,
        suffix=suffix,
        identifier=f"task9-alert-{suffix}",
        message_type="Alert",
        admin_code="67000000",
        references=[],
        geometry=True,
        sent=alert_generation,
    )
    payload = replace(
        payload,
        properties={
            **payload.properties,
            "ingestion_generation_started_at": alert_generation.isoformat(),
        },
    )
    first_ready = Event()
    release_first = Event()
    results: dict[str, object] = {}
    errors: dict[str, BaseException] = {}
    second_application_name = f"task9-warning-race-{suffix}"

    def capture_alert(writer: PostgresEvidencePromotionWriter) -> None:
        try:
            results["alert"] = writer.write_evidence(payload)
        except BaseException as exc:  # noqa: BLE001 - surfaced in parent thread
            errors["alert"] = exc

    def capture_empty(writer: PostgresEvidencePromotionWriter) -> None:
        try:
            results["empty"] = writer.retire_warning_latest_for_no_active_event(
                adapter_key=adapter_key,
                generation_started_at=empty_generation,
                completed_at=empty_generation + timedelta(seconds=2),
            )
        except BaseException as exc:  # noqa: BLE001 - surfaced in parent thread
            errors["empty"] = exc

    try:
        if commit_order == "empty_first":
            _insert_no_active_job(
                database_url,
                suffix=suffix,
                adapter_key=adapter_key,
                generation=empty_generation,
            )
            first_writer = PostgresEvidencePromotionWriter(
                connection_factory=_commit_gated_connection_factory(
                    database_url,
                    ready=first_ready,
                    release=release_first,
                )
            )
            second_writer = PostgresEvidencePromotionWriter(
                connection_factory=lambda: _named_connection(
                    database_url, second_application_name
                )
            )
            first_thread = Thread(target=lambda: capture_empty(first_writer))
            second_thread = Thread(target=lambda: capture_alert(second_writer))
        else:
            first_writer = PostgresEvidencePromotionWriter(
                connection_factory=_commit_gated_connection_factory(
                    database_url,
                    ready=first_ready,
                    release=release_first,
                )
            )
            second_writer = PostgresEvidencePromotionWriter(
                connection_factory=lambda: _named_connection(
                    database_url, second_application_name
                )
            )
            first_thread = Thread(target=lambda: capture_alert(first_writer))
            second_thread = Thread(target=lambda: capture_empty(second_writer))

        first_thread.start()
        assert first_ready.wait(5)
        if commit_order == "alert_first":
            _insert_no_active_job(
                database_url,
                suffix=suffix,
                adapter_key=adapter_key,
                generation=empty_generation,
            )
        second_thread.start()
        assert _wait_for_advisory_wait(database_url, second_application_name)
        release_first.set()
        first_thread.join(10)
        second_thread.join(10)
        assert not first_thread.is_alive()
        assert not second_thread.is_alive()
        assert errors == {}

        import psycopg

        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT count(*)
                FROM official_realtime_latest
                WHERE adapter_key = %s AND source_id = %s
                """,
                (adapter_key, payload.source_id),
            )
            latest_count = int(cursor.fetchone()[0])
            cursor.execute(
                "SELECT count(*) FROM evidence WHERE source_id = %s",
                (payload.source_id,),
            )
            evidence_count = int(cursor.fetchone()[0])
        return latest_count, evidence_count
    finally:
        release_first.set()
        _cleanup_cap_race(database_url, suffix)
        _cleanup_no_active_job(database_url, suffix=suffix)


def _race_update_and_no_active_marker(
    database_url: str,
    *,
    commit_order: str,
) -> tuple[tuple[str, ...], tuple[str | None, str | None]]:
    suffix = uuid4().hex
    cwa_adapter = "official.cwa.heavy_rain_warning"
    ncdr_adapter = "official.ncdr.cap"
    update_generation = NOW
    empty_generation = NOW + timedelta(seconds=1)
    latest_generation = NOW + timedelta(seconds=2)
    same_alert = _cap_payload(
        adapter_key=cwa_adapter,
        suffix=suffix,
        identifier=f"task9-race-same-{suffix}",
        message_type="Alert",
        admin_code="67000000",
        references=[],
        geometry=True,
        sent=NOW,
    )
    peer_alert = _cap_payload(
        adapter_key=ncdr_adapter,
        suffix=suffix,
        identifier=f"task9-race-peer-{suffix}",
        message_type="Alert",
        admin_code="64000000",
        references=[],
        geometry=True,
        sent=NOW + timedelta(minutes=1),
    )
    for alert in (same_alert, peer_alert):
        alert.properties["ingestion_generation_started_at"] = (
            latest_generation.isoformat()
        )
    update = _cap_payload(
        adapter_key=cwa_adapter,
        suffix=suffix,
        identifier=f"task9-race-update-{suffix}",
        message_type="Update",
        admin_code="67000000",
        references=[
            {
                "sender": str(same_alert.properties["cap_sender"]),
                "identifier": str(same_alert.properties["cap_identifier"]),
                "sent": str(same_alert.properties["cap_sent"]),
            },
            {
                "sender": str(peer_alert.properties["cap_sender"]),
                "identifier": str(peer_alert.properties["cap_identifier"]),
                "sent": str(peer_alert.properties["cap_sent"]),
            },
        ],
        geometry=True,
        sent=NOW + timedelta(minutes=5),
    )
    update.properties["ingestion_generation_started_at"] = update_generation.isoformat()
    summary = AdapterBatchRunSummary(
        adapter_key=cwa_adapter,
        status="succeeded",
        started_at=empty_generation,
        finished_at=empty_generation + timedelta(seconds=1),
        items_fetched=0,
        items_promoted=0,
        items_rejected=0,
        error_code="no_active_event",
    )
    first_ready = Event()
    release_first = Event()
    errors: dict[str, BaseException] = {}
    update_result: dict[str, str | None] = {}
    second_application_name = f"task9-update-empty-race-{suffix}"
    seed_writer = PostgresEvidencePromotionWriter(database_url=database_url)

    def capture_update(writer: PostgresEvidencePromotionWriter) -> None:
        try:
            update_result["evidence_id"] = writer.write_evidence(update)
        except BaseException as exc:  # noqa: BLE001 - surfaced in parent thread
            errors["update"] = exc

    def capture_marker(writer: PostgresIngestionRunWriter) -> None:
        try:
            writer.write_summary(
                summary,
                job_key=f"task9-no-active-{suffix}",
            )
        except BaseException as exc:  # noqa: BLE001 - surfaced in parent thread
            errors["marker"] = exc

    try:
        assert seed_writer.write_evidence(same_alert) is not None
        assert seed_writer.write_evidence(peer_alert) is not None

        if commit_order == "update_first":
            first_writer = PostgresEvidencePromotionWriter(
                connection_factory=_commit_gated_connection_factory(
                    database_url,
                    ready=first_ready,
                    release=release_first,
                )
            )
            second_writer = PostgresIngestionRunWriter(
                connection_factory=lambda: _named_connection(
                    database_url,
                    second_application_name,
                )
            )
            first_thread = Thread(target=lambda: capture_update(first_writer))
            second_thread = Thread(target=lambda: capture_marker(second_writer))
        else:
            first_writer = PostgresIngestionRunWriter(
                connection_factory=_commit_gated_connection_factory(
                    database_url,
                    ready=first_ready,
                    release=release_first,
                )
            )
            second_writer = PostgresEvidencePromotionWriter(
                connection_factory=lambda: _named_connection(
                    database_url,
                    second_application_name,
                )
            )
            first_thread = Thread(target=lambda: capture_marker(first_writer))
            second_thread = Thread(target=lambda: capture_update(second_writer))

        first_thread.start()
        assert first_ready.wait(5)
        second_thread.start()
        assert _wait_for_advisory_wait(database_url, second_application_name)
        release_first.set()
        first_thread.join(10)
        second_thread.join(10)
        assert not first_thread.is_alive()
        assert not second_thread.is_alive()
        assert errors == {}

        seed_writer.retire_warning_latest_for_no_active_event(
            adapter_key=cwa_adapter,
            generation_started_at=empty_generation,
            completed_at=empty_generation + timedelta(seconds=2),
        )

        import psycopg

        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT adapter_key
                FROM official_realtime_latest
                WHERE source_id = ANY(%s)
                ORDER BY adapter_key
                """,
                ([same_alert.source_id, peer_alert.source_id],),
            )
            surviving_rows = tuple(str(row[0]) for row in cursor.fetchall())
            cursor.execute(
                """
                SELECT
                    properties ->> 'evidence_scope',
                    properties ->> 'historical_reason'
                FROM evidence
                WHERE id = %s
                """,
                (update_result["evidence_id"],),
            )
            raw_update_state = cursor.fetchone()
            assert raw_update_state is not None
            update_state = (raw_update_state[0], raw_update_state[1])
        return surviving_rows, update_state
    finally:
        release_first.set()
        _cleanup_cap_race(database_url, suffix)
        _cleanup_no_active_job(database_url, suffix=suffix)


def _insert_no_active_job(
    database_url: str,
    *,
    suffix: str,
    adapter_key: str,
    generation: datetime,
) -> None:
    import psycopg

    with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO ingestion_jobs (
                job_key, adapter_key, started_at, finished_at, status,
                items_fetched, items_promoted, items_rejected, error_code
            )
            VALUES (%s, %s, %s, %s, 'succeeded', 0, 0, 0, 'no_active_event')
            """,
            (
                f"task9-no-active-{suffix}",
                adapter_key,
                generation,
                generation + timedelta(seconds=1),
            ),
        )


def _cleanup_no_active_job(database_url: str, *, suffix: str) -> None:
    import psycopg

    with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "DELETE FROM ingestion_jobs WHERE job_key = %s",
            (f"task9-no-active-{suffix}",),
        )


def _wait_for_advisory_wait(
    database_url: str,
    application_name: str,
    *,
    timeout_seconds: float = 5.0,
) -> bool:
    import psycopg

    deadline = monotonic() + timeout_seconds
    while monotonic() < deadline:
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM pg_stat_activity
                    WHERE application_name = %s
                        AND wait_event_type = 'Lock'
                        AND wait_event = 'advisory'
                )
                """,
                (application_name,),
            )
            if cursor.fetchone() == (True,):
                return True
        Event().wait(0.02)
    return False


def _wait_for_database_lock(
    database_url: str,
    application_name: str,
    *,
    timeout_seconds: float = 5.0,
) -> bool:
    import psycopg

    deadline = monotonic() + timeout_seconds
    while monotonic() < deadline:
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM pg_stat_activity
                    WHERE application_name = %s
                        AND wait_event_type = 'Lock'
                )
                """,
                (application_name,),
            )
            if cursor.fetchone() == (True,):
                return True
        Event().wait(0.02)
    return False


def _named_connection(database_url: str, application_name: str) -> Any:
    import psycopg

    return psycopg.connect(database_url, application_name=application_name)


def _commit_gated_connection_factory(
    database_url: str,
    *,
    ready: Event,
    release: Event,
) -> Callable[[], Any]:
    import psycopg

    def factory() -> _CommitGateConnection:
        return _CommitGateConnection(
            psycopg.connect(database_url),
            ready=ready,
            release=release,
        )

    return factory


class _CommitGateConnection:
    def __init__(self, connection: Any, *, ready: Event, release: Event) -> None:
        self._connection = connection
        self._ready = ready
        self._release = release

    def __enter__(self) -> Self:
        self._connection.__enter__()
        return self

    def __exit__(self, *args: object) -> object:
        return self._connection.__exit__(*args)

    def cursor(self) -> Any:
        return self._connection.cursor()

    def commit(self) -> None:
        self._ready.set()
        assert self._release.wait(10)
        self._connection.commit()


def _insert_barrier_connection(database_url: str, barrier: Barrier) -> Any:
    import psycopg

    return _InsertBarrierConnection(psycopg.connect(database_url), barrier)


def _gated_connection_factory(
    database_url: str,
    *,
    lock_predicate: Callable[[str], bool],
    acquired: Event,
    release: Event | None,
    attempted: Event | None = None,
    application_name: str | None = None,
) -> Callable[[], Any]:
    import psycopg

    def factory() -> _GateConnection:
        connect_options = (
            {"application_name": application_name}
            if application_name is not None
            else {}
        )
        return _GateConnection(
            psycopg.connect(database_url, **connect_options),
            lock_predicate=lock_predicate,
            attempted=attempted,
            acquired=acquired,
            release=release,
        )

    return factory


class _GateConnection:
    def __init__(
        self,
        connection: Any,
        *,
        lock_predicate: Callable[[str], bool],
        attempted: Event | None,
        acquired: Event,
        release: Event | None,
    ) -> None:
        self._connection = connection
        self._lock_predicate = lock_predicate
        self._attempted = attempted
        self._acquired = acquired
        self._release = release

    def __enter__(self) -> Self:
        self._connection.__enter__()
        return self

    def __exit__(self, *args: object) -> object:
        return self._connection.__exit__(*args)

    def cursor(self) -> _GateCursor:
        return _GateCursor(
            self._connection.cursor(),
            lock_predicate=self._lock_predicate,
            attempted=self._attempted,
            acquired=self._acquired,
            release=self._release,
        )

    def commit(self) -> None:
        self._connection.commit()


class _GateCursor:
    def __init__(
        self,
        cursor: Any,
        *,
        lock_predicate: Callable[[str], bool],
        attempted: Event | None,
        acquired: Event,
        release: Event | None,
    ) -> None:
        self._cursor = cursor
        self._lock_predicate = lock_predicate
        self._attempted = attempted
        self._acquired = acquired
        self._release = release

    def __enter__(self) -> Self:
        self._cursor.__enter__()
        return self

    def __exit__(self, *args: object) -> object:
        return self._cursor.__exit__(*args)

    def execute(self, sql: str, params: tuple[object, ...]) -> object:
        target_lock = (
            "pg_advisory_xact_lock" in sql
            and bool(params)
            and self._lock_predicate(str(params[0]))
            and not self._acquired.is_set()
        )
        if target_lock and self._attempted is not None:
            self._attempted.set()
        result = self._cursor.execute(sql, params)
        if target_lock:
            self._acquired.set()
            if self._release is not None:
                assert self._release.wait(10)
        return result

    def fetchone(self) -> Any:
        return self._cursor.fetchone()


class _InsertBarrierConnection:
    def __init__(self, connection: Any, barrier: Barrier) -> None:
        self._connection = connection
        self._barrier = barrier

    def __enter__(self) -> Self:
        self._connection.__enter__()
        return self

    def __exit__(self, *args: object) -> object:
        return self._connection.__exit__(*args)

    def cursor(self) -> _InsertBarrierCursor:
        return _InsertBarrierCursor(self._connection.cursor(), self._barrier)

    def commit(self) -> None:
        self._connection.commit()


class _InsertBarrierCursor:
    def __init__(self, cursor: Any, barrier: Barrier) -> None:
        self._cursor = cursor
        self._barrier = barrier

    def __enter__(self) -> Self:
        self._cursor.__enter__()
        return self

    def __exit__(self, *args: object) -> object:
        return self._cursor.__exit__(*args)

    def execute(self, sql: str, params: tuple[object, ...]) -> object:
        if "INSERT INTO evidence" in sql:
            self._barrier.wait(5)
        return self._cursor.execute(sql, params)

    def fetchone(self) -> Any:
        return self._cursor.fetchone()


class _BorrowedConnection:
    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        del args

    def cursor(self) -> Any:
        return self._connection.cursor()

    def commit(self) -> None:
        return None


def _install_transactional_reviewed_snapshot(connection: Any, suffix: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE realtime_jurisdiction_boundary_snapshots SET is_active = false WHERE is_active"
        )
        cursor.execute(
            """
            INSERT INTO realtime_jurisdiction_boundary_snapshots (
                source_name, source_url, source_revision
            )
            VALUES ('Task 8 test', %s, %s)
            RETURNING id
            """,
            (f"https://example.test/boundary/{suffix}", suffix),
        )
        snapshot_id = cursor.fetchone()[0]
        cursor.execute(
            """
            WITH geometry AS (
                SELECT ST_Multi(
                    ST_GeomFromText(
                        'POLYGON((119 21, 123 21, 123 26, 119 26, 119 21))',
                        4326
                    )
                )::geometry(MultiPolygon, 4326) AS geom
            )
            INSERT INTO realtime_jurisdiction_boundaries (
                snapshot_id, jurisdiction_code, geom, geom_sha256
            )
            SELECT
                %s,
                jurisdiction.jurisdiction_code,
                geometry.geom,
                encode(digest(ST_AsEWKB(geometry.geom), 'sha256'), 'hex')
            FROM realtime_jurisdictions jurisdiction
            CROSS JOIN geometry
            """,
            (snapshot_id,),
        )
        cursor.execute(
            """
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
            )
            FROM realtime_jurisdiction_boundaries
            WHERE snapshot_id = %s
            """,
            (snapshot_id,),
        )
        manifest_sha256 = cursor.fetchone()[0]
        cursor.execute(
            """
            UPDATE realtime_jurisdiction_boundary_snapshots
            SET imported_count = 22,
                manifest_sha256 = %s,
                approved_manifest_sha256 = %s,
                is_complete = true,
                reviewed_at = %s,
                review_ref = 'task-8-postgis-test',
                is_active = true
            WHERE id = %s
            """,
            (manifest_sha256, manifest_sha256, NOW, snapshot_id),
        )


def _install_temp_boundary_case(connection: Any, boundary_case: str, suffix: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE TEMP TABLE realtime_jurisdiction_boundary_snapshots
                (LIKE public.realtime_jurisdiction_boundary_snapshots INCLUDING DEFAULTS)
                ON COMMIT DROP
            """
        )
        cursor.execute(
            """
            CREATE TEMP TABLE realtime_jurisdiction_boundaries
                (LIKE public.realtime_jurisdiction_boundaries INCLUDING DEFAULTS)
                ON COMMIT DROP
            """
        )
        snapshot_count = 2 if boundary_case == "ambiguous_active" else 1
        for index in range(snapshot_count):
            cursor.execute(
                """
                INSERT INTO realtime_jurisdiction_boundary_snapshots (
                    source_name, source_url, source_revision, expected_count,
                    imported_count, is_complete, reviewed_at, review_ref, is_active
                )
                VALUES (%s, %s, %s, 22, 22, true, %s, %s, %s)
                RETURNING id
                """,
                (
                    "Task 8 negative test",
                    f"https://example.test/boundary-negative/{suffix}/{index}",
                    f"{suffix}-{index}",
                    None if boundary_case == "unreviewed" else NOW,
                    None if boundary_case == "unreviewed" else "task-8-negative-test",
                    boundary_case != "inactive",
                ),
            )
            snapshot_id = cursor.fetchone()[0]
            cursor.execute(
                """
                WITH geometry AS (
                    SELECT ST_Multi(
                        ST_GeomFromText(
                            'POLYGON((119 21, 123 21, 123 26, 119 26, 119 21))',
                            4326
                        )
                    )::geometry(MultiPolygon, 4326) AS geom
                )
                INSERT INTO realtime_jurisdiction_boundaries (
                    snapshot_id, jurisdiction_code, geom, geom_sha256
                )
                SELECT
                    %s,
                    jurisdiction.jurisdiction_code,
                    geometry.geom,
                    CASE
                        WHEN %s = 'checksum_mismatch'
                            AND jurisdiction.jurisdiction_code = '63000000'
                            THEN repeat('0', 64)
                        ELSE encode(digest(ST_AsEWKB(geometry.geom), 'sha256'), 'hex')
                    END
                FROM public.realtime_jurisdictions jurisdiction
                CROSS JOIN geometry
                """,
                (snapshot_id, boundary_case),
            )
            cursor.execute(
                """
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
                )
                FROM realtime_jurisdiction_boundaries
                WHERE snapshot_id = %s
                """,
                (snapshot_id,),
            )
            manifest_sha256 = cursor.fetchone()[0]
            cursor.execute(
                """
                UPDATE realtime_jurisdiction_boundary_snapshots
                SET manifest_sha256 = %s, approved_manifest_sha256 = %s
                WHERE id = %s
                """,
                (manifest_sha256, manifest_sha256, snapshot_id),
            )


def _cleanup_race(
    database_url: str,
    suffix: str,
    station_id: str,
    staging_fixtures: tuple[dict[str, str], ...],
) -> None:
    import psycopg

    with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "DELETE FROM official_realtime_latest WHERE station_id = %s", (station_id,)
        )
        cursor.execute("DELETE FROM evidence WHERE source_id LIKE %s", (f"task8-race-{suffix}%",))
        cursor.execute(
            "DELETE FROM staging_evidence WHERE id = ANY(%s::uuid[])",
            ([fixture["staging_id"] for fixture in staging_fixtures],),
        )
        cursor.execute(
            "DELETE FROM raw_snapshots WHERE id = ANY(%s::uuid[])",
            ([fixture["raw_snapshot_id"] for fixture in staging_fixtures],),
        )


def _cleanup_cap_race(database_url: str, suffix: str) -> None:
    import psycopg

    with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            DELETE FROM official_realtime_latest
            WHERE evidence_id IN (
                SELECT id FROM evidence WHERE source_id LIKE %s
            )
            """,
            (f"task8-cap-{suffix}-%",),
        )
        cursor.execute("DELETE FROM evidence WHERE source_id LIKE %s", (f"task8-cap-{suffix}-%",))


def _cleanup_staged_payload(
    database_url: str,
    fixture: dict[str, str],
    *,
    extra_staging_ids: tuple[str, ...] = (),
) -> None:
    import psycopg

    with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "DELETE FROM staging_evidence WHERE id = ANY(%s::uuid[])",
            ([fixture["staging_id"], *extra_staging_ids],),
        )
        cursor.execute(
            "DELETE FROM raw_snapshots WHERE id = %s",
            (fixture["raw_snapshot_id"],),
        )


def _cleanup_depth_race(
    database_url: str,
    suffix: str,
    central: EvidencePromotionPayload,
    local: EvidencePromotionPayload,
) -> None:
    import psycopg

    with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "DELETE FROM official_realtime_latest WHERE station_id = ANY(%s)",
            ([central.properties["station_id"], local.properties["station_id"]],),
        )
        cursor.execute(
            "DELETE FROM evidence WHERE source_id LIKE %s",
            (f"task8-depth-{suffix}-%",),
        )
