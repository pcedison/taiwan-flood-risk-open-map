from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime
from threading import Event, Thread
from typing import Any, Self
from uuid import uuid4

import pytest

from app.adapters.cap_identity import cap_message_digest
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


@pytest.mark.parametrize(("first_value", "second_value"), [(3.2, 9.9), (9.9, 3.2)])
def test_absent_latest_key_is_serialized_without_equal_time_overwrite(
    database_url: str,
    first_value: float,
    second_value: float,
) -> None:
    suffix = uuid4().hex
    station_id = f"RACE-{suffix}"
    staging_ids = _insert_staging_candidates(database_url, suffix, 2)
    first_has_lock = Event()
    release_first = Event()
    second_started = Event()
    results: dict[str, str | None] = {}

    first_writer = PostgresEvidencePromotionWriter(
        connection_factory=_gated_connection_factory(
            database_url,
            lock_predicate=lambda key: key.startswith("official-realtime-dedupe|"),
            acquired=first_has_lock,
            release=release_first,
        )
    )
    second_writer = PostgresEvidencePromotionWriter(database_url=database_url)
    first_payload = _water_payload(
        suffix=suffix,
        station_id=station_id,
        value=first_value,
        staging_id=staging_ids[0],
    )
    second_payload = _water_payload(
        suffix=suffix + "-second",
        station_id=station_id,
        value=second_value,
        staging_id=staging_ids[1],
    )

    first_thread = Thread(
        target=lambda: results.__setitem__("first", first_writer.write_evidence(first_payload))
    )

    def run_second() -> None:
        second_started.set()
        results["second"] = second_writer.write_evidence(second_payload)

    second_thread = Thread(target=run_second)
    try:
        first_thread.start()
        assert first_has_lock.wait(5)
        second_thread.start()
        assert second_started.wait(5)
        release_first.set()
        first_thread.join(10)
        second_thread.join(10)
        assert not first_thread.is_alive()
        assert not second_thread.is_alive()
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
                (staging_ids[1],),
            )
            assert cursor.fetchone() == ("rejected", "conflicting_latest")
    finally:
        release_first.set()
        _cleanup_race(database_url, suffix, station_id, staging_ids)


def test_same_staging_concurrent_retry_is_consumed_once_without_rejection(
    database_url: str,
) -> None:
    suffix = uuid4().hex
    station_id = f"SAME-STAGING-{suffix}"
    staging_ids = _insert_staging_candidates(database_url, suffix, 1)
    first_has_lock = Event()
    release_first = Event()
    results: dict[str, str | None] = {}
    payload = _water_payload(
        suffix=suffix,
        station_id=station_id,
        value=3.2,
        staging_id=staging_ids[0],
    )
    first_writer = PostgresEvidencePromotionWriter(
        connection_factory=_gated_connection_factory(
            database_url,
            lock_predicate=lambda key: key.startswith("official-realtime-dedupe|"),
            acquired=first_has_lock,
            release=release_first,
        )
    )
    second_writer = PostgresEvidencePromotionWriter(database_url=database_url)
    first_thread = Thread(
        target=lambda: results.__setitem__("first", first_writer.write_evidence(payload))
    )
    second_thread = Thread(
        target=lambda: results.__setitem__("second", second_writer.write_evidence(payload))
    )
    try:
        first_thread.start()
        assert first_has_lock.wait(5)
        second_thread.start()
        release_first.set()
        first_thread.join(10)
        second_thread.join(10)
        assert not first_thread.is_alive()
        assert not second_thread.is_alive()
        assert results["first"] is not None
        assert results["second"] is None

        import psycopg

        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT validation_status, rejection_reason FROM staging_evidence WHERE id = %s",
                (staging_ids[0],),
            )
            assert cursor.fetchone() == ("accepted", None)
            cursor.execute(
                "SELECT count(*) FROM evidence WHERE source_id = %s",
                (payload.source_id,),
            )
            assert cursor.fetchone() == (1,)
    finally:
        release_first.set()
        _cleanup_race(database_url, suffix, station_id, staging_ids)


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
    results: dict[str, str | None] = {}
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
    second_writer = PostgresEvidencePromotionWriter(database_url=database_url)
    first_thread = Thread(
        target=lambda: results.__setitem__("first", first_writer.write_evidence(first_payload))
    )
    second_thread = Thread(
        target=lambda: results.__setitem__("second", second_writer.write_evidence(second_payload))
    )
    try:
        first_thread.start()
        assert acquired.wait(5)
        second_thread.start()
        release.set()
        first_thread.join(10)
        second_thread.join(10)
        assert not first_thread.is_alive()
        assert not second_thread.is_alive()

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
    finally:
        release.set()
        _cleanup_cap_race(database_url, suffix)


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


def _insert_staging_candidates(database_url: str, suffix: str, count: int) -> tuple[str, ...]:
    import psycopg

    ids: list[str] = []
    with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
        for index in range(count):
            cursor.execute(
                """
                INSERT INTO staging_evidence (
                    data_source_id, source_id, source_type, event_type, title, summary,
                    occurred_at, observed_at, confidence, validation_status, payload
                )
                VALUES (
                    (SELECT id FROM data_sources WHERE adapter_key = 'official.wra.water_level'),
                    %s, 'official', 'water_level', 'race', 'race', %s, %s, 0.9,
                    'accepted', '{}'::jsonb
                )
                RETURNING id
                """,
                (f"task8-race-{suffix}-{index}", NOW, NOW),
            )
            ids.append(str(cursor.fetchone()[0]))
    return tuple(ids)


def _water_payload(
    *, suffix: str, station_id: str, value: float, staging_id: str
) -> EvidencePromotionPayload:
    return EvidencePromotionPayload(
        data_source_id=None,
        adapter_key="official.wra.water_level",
        source_id=f"task8-race-{suffix}",
        source_type="official",
        event_type="water_level",
        title="race",
        summary="race",
        url=None,
        occurred_at=NOW,
        observed_at=NOW,
        confidence=0.9,
        raw_ref=f"raw/task8-race-{suffix}.json",
        properties={
            "evidence_scope": "current",
            "station_id": station_id,
            "water_level_m": value,
            "warning_level_m": 4.0,
            "location_precision": "point",
            "staging_evidence_id": staging_id,
            "location_payload": {
                "geometry": {"type": "Point", "coordinates": [120.2, 23.0]}
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
) -> EvidencePromotionPayload:
    properties: dict[str, Any] = {
        "evidence_scope": "current",
        "location_precision": "admin_area",
        "admin_code": admin_code,
        "cap_sender": "sender@example.test",
        "cap_identifier": identifier,
        "cap_sent": NOW.isoformat(),
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
        occurred_at=NOW,
        observed_at=NOW,
        confidence=0.95,
        raw_ref=f"raw/task8-cap-{suffix}-{identifier}.xml",
        properties=properties,
    )


def _gated_connection_factory(
    database_url: str,
    *,
    lock_predicate: Callable[[str], bool],
    acquired: Event,
    release: Event,
) -> Callable[[], Any]:
    import psycopg

    def factory() -> _GateConnection:
        return _GateConnection(
            psycopg.connect(database_url),
            lock_predicate=lock_predicate,
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
        acquired: Event,
        release: Event,
    ) -> None:
        self._connection = connection
        self._lock_predicate = lock_predicate
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
        acquired: Event,
        release: Event,
    ) -> None:
        self._cursor = cursor
        self._lock_predicate = lock_predicate
        self._acquired = acquired
        self._release = release

    def __enter__(self) -> Self:
        self._cursor.__enter__()
        return self

    def __exit__(self, *args: object) -> object:
        return self._cursor.__exit__(*args)

    def execute(self, sql: str, params: tuple[object, ...]) -> object:
        result = self._cursor.execute(sql, params)
        if (
            "pg_advisory_xact_lock" in sql
            and params
            and self._lock_predicate(str(params[0]))
            and not self._acquired.is_set()
        ):
            self._acquired.set()
            assert self._release.wait(10)
        return result

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


def _cleanup_race(
    database_url: str,
    suffix: str,
    station_id: str,
    staging_ids: tuple[str, ...],
) -> None:
    import psycopg

    with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "DELETE FROM official_realtime_latest WHERE station_id = %s", (station_id,)
        )
        cursor.execute("DELETE FROM evidence WHERE source_id LIKE %s", (f"task8-race-{suffix}%",))
        cursor.execute("DELETE FROM staging_evidence WHERE id = ANY(%s::uuid[])", (list(staging_ids),))


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
