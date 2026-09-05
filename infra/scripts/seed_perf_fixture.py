"""Seed a production-shaped performance fixture into a local PostGIS database.

The production ``evidence`` table carries roughly 1.1M rows: 1,342 official
rainfall stations, 358 river/pond water level stations and 2,000 Civil IoT sewer
stations, each publishing one observation every 10 minutes across the 48 hour
retention window, plus a long tail of historical flood reports and flood
potential polygons.  Local development databases are effectively empty, so the
query plans that matter on production (``query_nearby_evidence`` and
``query_nearby_realtime_coverage_rows``) cannot be reproduced without a fixture
of the same shape.

This script builds that fixture deterministically so ``EXPLAIN (ANALYZE,
BUFFERS)`` runs are comparable across before/after index changes.  It is a
development tool only: every row it writes is tagged with the ``perf:``
``source_id`` prefix and ``--reset`` removes exactly those rows.

Usage::

    python infra/scripts/seed_perf_fixture.py \
        --database-url postgresql://flood_risk:change-me-local@127.0.0.1:5432/flood_risk \
        --reset
"""

from __future__ import annotations

import argparse
import math
import random
import sys
from dataclasses import dataclass

import psycopg

SOURCE_ID_PREFIX = "perf:"

RAINFALL_ADAPTER = "official.cwa.rainfall"
WATER_LEVEL_ADAPTER = "official.wra.water_level"
SEWER_ADAPTER = "official.civil_iot.sewer_water_level"
FLOOD_REPORT_ADAPTER = "official.wra_iow.flood_depth"
FLOOD_POTENTIAL_ADAPTER = "official.flood_potential.geojson"

RAINFALL_STATIONS = 1_342
WATER_LEVEL_STATIONS = 358
SEWER_STATIONS = 2_000
HISTORICAL_ROWS = 50_000

RETENTION_HOURS = 48
OBSERVATION_INTERVAL_MINUTES = 10

# Taiwan main-island bounding box, used for the uniformly scattered stations.
LNG_MIN, LNG_MAX = 120.03, 122.01
LAT_MIN, LAT_MAX = 21.90, 25.30

# Urban clusters carry most of the sensor network in production.  The three
# cities the SDD 3.3 latency budget is measured against are listed first so the
# fixture reproduces their station density.
URBAN_CENTERS: tuple[tuple[str, float, float, float], ...] = (
    ("kaohsiung", 120.3014, 22.6273, 0.16),
    ("taichung", 120.6736, 24.1477, 0.14),
    ("chiayi_city", 120.4491, 23.4801, 0.06),
    ("taipei", 121.5654, 25.0330, 0.14),
    ("new_taipei", 121.4628, 25.0169, 0.10),
    ("taoyuan", 121.3010, 24.9937, 0.08),
    ("tainan", 120.2270, 22.9998, 0.10),
    ("hsinchu", 120.9686, 24.8066, 0.05),
    ("changhua", 120.5417, 24.0685, 0.05),
    ("yunlin", 120.4313, 23.7092, 0.04),
    ("pingtung", 120.4890, 22.6820, 0.04),
    ("yilan", 121.7539, 24.7021, 0.04),
)

# Fraction of stations placed inside an urban cluster rather than scattered.
CLUSTERED_FRACTION = 0.62
# Standard deviation, in kilometres, of the Gaussian spread inside a cluster.
CLUSTER_SIGMA_KM = 6.0

KM_PER_DEGREE_LAT = 110.574


@dataclass(frozen=True)
class Station:
    adapter_key: str
    event_type: str
    station_id: str
    lng: float
    lat: float


def _km_per_degree_lng(lat: float) -> float:
    return 111.320 * math.cos(math.radians(lat))


def _clustered_point(rng: random.Random) -> tuple[float, float]:
    roll = rng.random()
    cumulative = 0.0
    chosen = URBAN_CENTERS[0]
    for center in URBAN_CENTERS:
        cumulative += center[3]
        if roll <= cumulative:
            chosen = center
            break
    _, clng, clat, _ = chosen
    lat = clat + rng.gauss(0.0, CLUSTER_SIGMA_KM / KM_PER_DEGREE_LAT)
    lng = clng + rng.gauss(0.0, CLUSTER_SIGMA_KM / _km_per_degree_lng(clat))
    return (
        min(max(lng, LNG_MIN), LNG_MAX),
        min(max(lat, LAT_MIN), LAT_MAX),
    )


def _scattered_point(rng: random.Random) -> tuple[float, float]:
    return (rng.uniform(LNG_MIN, LNG_MAX), rng.uniform(LAT_MIN, LAT_MAX))


def _build_stations(rng: random.Random) -> list[Station]:
    stations: list[Station] = []
    plan = (
        (RAINFALL_ADAPTER, "rainfall", "rain", RAINFALL_STATIONS),
        (WATER_LEVEL_ADAPTER, "water_level", "wl", WATER_LEVEL_STATIONS),
        (SEWER_ADAPTER, "water_level", "sewer", SEWER_STATIONS),
    )
    for adapter_key, event_type, prefix, count in plan:
        for index in range(count):
            if rng.random() < CLUSTERED_FRACTION:
                lng, lat = _clustered_point(rng)
            else:
                lng, lat = _scattered_point(rng)
            stations.append(
                Station(
                    adapter_key=adapter_key,
                    event_type=event_type,
                    station_id=f"{prefix}-{index:05d}",
                    lng=round(lng, 6),
                    lat=round(lat, 6),
                )
            )
    return stations


def _reset(cursor: psycopg.Cursor) -> None:
    cursor.execute(
        "DELETE FROM official_realtime_latest WHERE source_id LIKE %s",
        (f"{SOURCE_ID_PREFIX}%",),
    )
    deleted_latest = cursor.rowcount
    cursor.execute(
        "DELETE FROM evidence WHERE source_id LIKE %s",
        (f"{SOURCE_ID_PREFIX}%",),
    )
    print(
        f"reset: removed {cursor.rowcount} evidence rows and "
        f"{deleted_latest} official_realtime_latest rows"
    )


def _create_station_table(cursor: psycopg.Cursor, stations: list[Station]) -> None:
    cursor.execute(
        """
        CREATE TEMP TABLE perf_stations (
            adapter_key text NOT NULL,
            event_type text NOT NULL,
            station_id text NOT NULL,
            lng double precision NOT NULL,
            lat double precision NOT NULL
        ) ON COMMIT DROP
        """
    )
    with cursor.copy(
        "COPY perf_stations (adapter_key, event_type, station_id, lng, lat) FROM STDIN"
    ) as copy:
        for station in stations:
            copy.write_row(
                (
                    station.adapter_key,
                    station.event_type,
                    station.station_id,
                    station.lng,
                    station.lat,
                )
            )
    cursor.execute("CREATE INDEX ON perf_stations (adapter_key)")
    cursor.execute("ANALYZE perf_stations")
    print(f"staged {len(stations)} stations")


def _insert_realtime_evidence(cursor: psycopg.Cursor) -> None:
    cursor.execute(
        """
        INSERT INTO evidence (
            data_source_id,
            source_id,
            source_type,
            event_type,
            title,
            summary,
            url,
            occurred_at,
            observed_at,
            ingested_at,
            geom,
            confidence,
            freshness_score,
            source_weight,
            privacy_level,
            raw_ref,
            ingestion_status,
            properties,
            created_at,
            updated_at
        )
        SELECT
            ds.id,
            %(prefix)s || s.adapter_key || ':' || s.station_id || ':'
                || to_char(slot.ts, 'YYYYMMDDHH24MI'),
            'official',
            s.event_type,
            s.station_id || ' 觀測站',
            'perf fixture observation',
            'https://example.invalid/perf/' || s.station_id,
            slot.ts,
            slot.ts,
            slot.ts,
            ST_SetSRID(ST_MakePoint(s.lng, s.lat), 4326),
            0.9,
            0.9,
            1.0,
            'public',
            NULL,
            'accepted',
            CASE
                WHEN s.event_type = 'rainfall' THEN jsonb_build_object(
                    'station_id', s.station_id,
                    'evidence_scope', 'current',
                    'location_precision', 'point',
                    'rainfall_mm_1h',
                        round((extract(epoch FROM slot.ts)::numeric %% 37) / 2, 1)
                )
                ELSE jsonb_build_object(
                    'station_id', s.station_id,
                    'evidence_scope', 'current',
                    'location_precision', 'point',
                    'water_level_m',
                        round((extract(epoch FROM slot.ts)::numeric %% 53) / 10, 2),
                    'warning_level_m', 4.5
                )
            END,
            slot.ts,
            slot.ts
        FROM perf_stations s
        JOIN data_sources ds ON ds.adapter_key = s.adapter_key
        CROSS JOIN LATERAL generate_series(
            date_trunc('hour', now()) - make_interval(hours => %(hours)s),
            date_trunc('hour', now()),
            make_interval(mins => %(interval)s)
        ) AS slot(ts)
        """,
        {
            "prefix": SOURCE_ID_PREFIX,
            "hours": RETENTION_HOURS,
            "interval": OBSERVATION_INTERVAL_MINUTES,
        },
    )
    print(f"inserted {cursor.rowcount} official realtime evidence rows")


def _insert_historical_evidence(cursor: psycopg.Cursor) -> None:
    cursor.execute(
        """
        INSERT INTO evidence (
            data_source_id,
            source_id,
            source_type,
            event_type,
            title,
            summary,
            url,
            occurred_at,
            observed_at,
            ingested_at,
            geom,
            confidence,
            freshness_score,
            source_weight,
            privacy_level,
            raw_ref,
            ingestion_status,
            properties,
            created_at,
            updated_at
        )
        SELECT
            ds.id,
            %(prefix)s || 'history:' || sample.event_type || ':' || sample.n,
            'official',
            sample.event_type,
            '歷史淹水紀錄 ' || sample.n,
            'perf fixture historical record',
            'https://example.invalid/perf/history/' || sample.n,
            sample.occurred_at,
            NULL,
            sample.occurred_at,
            ST_SetSRID(ST_MakePoint(sample.lng, sample.lat), 4326),
            0.8,
            0.6,
            1.0,
            'public',
            NULL,
            'accepted',
            jsonb_build_object(
                'evidence_scope', 'historical',
                'location_precision', 'point',
                'flood_depth_cm', 10 + (sample.n %% 90)
            ),
            sample.occurred_at,
            sample.occurred_at
        FROM (
            SELECT
                n,
                CASE WHEN n %% 2 = 0 THEN 'flood_report' ELSE 'flood_potential' END
                    AS event_type,
                CASE
                    WHEN n %% 2 = 0 THEN %(report_adapter)s
                    ELSE %(potential_adapter)s
                END AS adapter_key,
                %(lng_min)s + (%(lng_max)s - %(lng_min)s)
                    * (((n::bigint * 7919) %% 100000)::double precision / 100000.0) AS lng,
                %(lat_min)s + (%(lat_max)s - %(lat_min)s)
                    * (((n::bigint * 104729) %% 100000)::double precision / 100000.0) AS lat,
                now() - make_interval(days => (n %% 3650)) AS occurred_at
            FROM generate_series(1, %(rows)s) AS n
        ) sample
        JOIN data_sources ds ON ds.adapter_key = sample.adapter_key
        """,
        {
            "prefix": SOURCE_ID_PREFIX,
            "rows": HISTORICAL_ROWS,
            "report_adapter": FLOOD_REPORT_ADAPTER,
            "potential_adapter": FLOOD_POTENTIAL_ADAPTER,
            "lng_min": LNG_MIN,
            "lng_max": LNG_MAX,
            "lat_min": LAT_MIN,
            "lat_max": LAT_MAX,
        },
    )
    print(f"inserted {cursor.rowcount} historical evidence rows")


def _insert_latest_projection(cursor: psycopg.Cursor) -> None:
    cursor.execute(
        """
        INSERT INTO official_realtime_latest (
            source_id,
            adapter_key,
            event_type,
            station_id,
            station_name,
            authority,
            observed_at,
            ingested_at,
            geom,
            rainfall_mm_1h,
            water_level_m,
            warning_level_m,
            confidence,
            freshness_score,
            source_weight
        )
        SELECT
            %(prefix)s || s.adapter_key || ':' || s.station_id,
            s.adapter_key,
            s.event_type,
            s.station_id,
            s.station_id || ' 觀測站',
            'perf fixture authority',
            date_trunc('hour', now()),
            date_trunc('hour', now()),
            ST_SetSRID(ST_MakePoint(s.lng, s.lat), 4326),
            CASE WHEN s.event_type = 'rainfall' THEN 3.5 ELSE NULL END,
            CASE WHEN s.event_type = 'water_level' THEN 2.4 ELSE NULL END,
            CASE WHEN s.event_type = 'water_level' THEN 4.5 ELSE NULL END,
            0.9,
            0.9,
            1.0
        FROM perf_stations s
        ON CONFLICT (adapter_key, event_type, station_id) DO NOTHING
        """,
        {"prefix": SOURCE_ID_PREFIX},
    )
    print(f"inserted {cursor.rowcount} official_realtime_latest rows")


def _analyze(connection: psycopg.Connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute("ANALYZE evidence")
        cursor.execute("ANALYZE official_realtime_latest")
        cursor.execute("ANALYZE data_sources")
    print("analyzed evidence, official_realtime_latest, data_sources")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default="postgresql://flood_risk:change-me-local@127.0.0.1:5432/flood_risk",
        help="PostGIS connection string for the local development database.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete previously seeded fixture rows before inserting.",
    )
    parser.add_argument("--seed", type=int, default=20260905, help="Station layout seed.")
    args = parser.parse_args(argv)

    rng = random.Random(args.seed)
    stations = _build_stations(rng)

    with psycopg.connect(args.database_url) as connection:
        with connection.cursor() as cursor:
            if args.reset:
                _reset(cursor)
            _create_station_table(cursor, stations)
            _insert_realtime_evidence(cursor)
            _insert_historical_evidence(cursor)
            _insert_latest_projection(cursor)
        connection.commit()
    with psycopg.connect(args.database_url, autocommit=True) as connection:
        _analyze(connection)
    return 0


if __name__ == "__main__":
    sys.exit(main())
