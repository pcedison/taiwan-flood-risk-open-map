#!/usr/bin/env python3
"""Import the 22 county boundaries from the NLSC village boundary shapefile.

The jurisdiction boundary snapshot is what lets a query point resolve to a home
county. Without an active snapshot the assessment path falls back to national
sources only, so every local government sensor is invisible no matter how it is
configured.

County boundaries are dissolved from the village polygons by ``COUNTYCODE``
rather than sourced separately. The village file is the authoritative geometry
the geocoder also uses, so dissolving guarantees the county layer has no gaps or
overlaps against it, and guarantees both layers move together on a source update.

This script imports only. It writes the snapshot with ``is_active = false`` and
``is_complete = false``; activation is a separate reviewed step described in
docs/runbooks/station-inventory-and-jurisdiction-review.md.
"""

from __future__ import annotations

import argparse
import hashlib
import math
import sys
import tempfile
import zipfile
from itertools import pairwise
from pathlib import Path
from typing import Any

import psycopg

EXPECTED_COUNTY_COUNT = 22
SOURCE_NAME = "內政部國土測繪中心 村里界圖(TWD97經緯度)"
SOURCE_URL = "https://data.gov.tw/dataset/7438"
# The core island bounding box, used only to REPORT outlying parts, never to drop
# them. The official dataset legitimately places 東沙島, 太平島 and 釣魚台列嶼
# inside 高雄市旗津區 and 宜蘭縣頭城鎮大溪里. Filtering on this box silently
# discarded all three, and because 大溪里 is a mainland Yilan coastal village
# whose polygon reaches 釣魚台, dropping it would have punched a hole in the
# Yilan county boundary and left its residents unable to resolve to a county.
TAIWAN_CORE_LNG_RANGE = (117.0, 123.5)
TAIWAN_CORE_LAT_RANGE = (20.0, 27.5)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("zip_path", help="NLSC village boundary SHP ZIP.")
    parser.add_argument("--database-url", required=True)
    parser.add_argument(
        "--source-revision",
        required=True,
        help="NLSC release identifier, for example 1150817.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute and report checksums without writing a snapshot.",
    )
    args = parser.parse_args(argv)

    villages = _read_villages(Path(args.zip_path))
    print(f"villages read: {len(villages)}")
    counties = sorted({code for code, _ in villages})
    if len(counties) != EXPECTED_COUNTY_COUNT:
        print(
            f"refusing to import: expected {EXPECTED_COUNTY_COUNT} counties, found {len(counties)}",
            file=sys.stderr,
        )
        return 1

    with psycopg.connect(args.database_url) as connection:
        boundaries = _dissolve(connection, villages)
        _validate(boundaries)
        manifest_sha256 = _manifest_sha256(connection, boundaries)
        print(f"counties dissolved: {len(boundaries)}")
        print(f"manifest_sha256   : {manifest_sha256}")
        for code, _wkb, digest in boundaries:
            print(f"  {code}  {digest}")
        if args.dry_run:
            print("dry run: nothing written")
            return 0
        snapshot_id = _write_snapshot(
            connection,
            boundaries=boundaries,
            manifest_sha256=manifest_sha256,
            source_revision=args.source_revision,
        )
        connection.commit()
    print(f"snapshot written  : {snapshot_id} (is_active=false, is_complete=false)")
    print("activation is a separate reviewed step; see the jurisdiction review runbook")
    return 0


def _read_villages(zip_path: Path) -> list[tuple[str, str]]:
    """Return (canonical 8-digit county code, WKT polygon) for every village."""

    try:
        import shapefile
    except ImportError as exc:  # pragma: no cover - operator tooling
        raise SystemExit("pyshp is required: python -m pip install pyshp") from exc

    villages: list[tuple[str, str]] = []
    skipped: list[str] = []
    outlying_villages: list[str] = []
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(temp_dir)
        shp_path = next(Path(temp_dir).glob("VILLAGE_NLSC_*.shp"), None)
        if shp_path is None:
            raise SystemExit("VILLAGE_NLSC_*.shp not found in ZIP")

        reader = shapefile.Reader(str(shp_path), encoding="utf-8")
        try:
            for shape_record in reader.iterShapeRecords():
                record = shape_record.record.as_dict()
                county_code = _canonical_county_code(record)
                parsed = _polygon_wkt(shape_record.shape)
                if county_code is None or parsed is None:
                    skipped.append(str(record.get("VILLCODE")))
                    continue
                wkt, outlying = parsed
                if outlying:
                    outlying_villages.append(
                        f"{record.get('COUNTYNAME')}{record.get('TOWNNAME')}"
                        f"{record.get('VILLNAME')} ({record.get('VILLCODE')})"
                    )
                villages.append((county_code, wkt))
        finally:
            reader.close()

    if outlying_villages:
        print(f"villages with territory outside the core island box: {len(outlying_villages)}")
        for entry in outlying_villages:
            print(f"  kept: {entry}")
    if skipped:
        print(f"villages skipped as unparseable: {len(skipped)}")
        for entry in skipped:
            print(f"  skipped: {entry}")
    return villages


def _canonical_county_code(record: dict[str, Any]) -> str | None:
    """Map the shapefile's 5-digit COUNTYCODE onto the database's 8-digit code.

    Verified against the 22 codes migration 0035 seeds into
    `realtime_jurisdiction_signal_contracts`: the derived set matches exactly.
    """

    raw = record.get("COUNTYCODE")
    code = str(raw).strip() if raw is not None else ""
    if len(code) != 5 or not code.isdigit():
        return None
    return f"{code}000"


def _polygon_wkt(shape: Any) -> tuple[str, bool] | None:
    """Return (WKT, has_outlying_part) for one village polygon.

    Coordinates are validated as finite and on the globe. Territory outside the
    core island box is kept and reported, never dropped.
    """

    parts = [*list(shape.parts), len(shape.points)]
    rings: list[str] = []
    outlying = False
    for start, end in pairwise(parts):
        ring = shape.points[start:end]
        if len(ring) < 4:
            continue
        if ring[0] != ring[-1]:
            ring = [*ring, ring[0]]
        for x, y in ring:
            if not _valid_coordinate(x, y):
                return None
            if not _in_core_island_box(x, y):
                outlying = True
        rings.append("(" + ", ".join(f"{x!r} {y!r}" for x, y in ring) + ")")
    if not rings:
        return None
    return "POLYGON(" + ", ".join(rings) + ")", outlying


def _valid_coordinate(lng: float, lat: float) -> bool:
    return (
        isinstance(lng, (int, float))
        and isinstance(lat, (int, float))
        and math.isfinite(lng)
        and math.isfinite(lat)
        and -180.0 <= lng <= 180.0
        and -90.0 <= lat <= 90.0
    )


def _in_core_island_box(lng: float, lat: float) -> bool:
    return (
        TAIWAN_CORE_LNG_RANGE[0] <= lng <= TAIWAN_CORE_LNG_RANGE[1]
        and TAIWAN_CORE_LAT_RANGE[0] <= lat <= TAIWAN_CORE_LAT_RANGE[1]
    )


def _dissolve(
    connection: psycopg.Connection,
    villages: list[tuple[str, str]],
) -> list[tuple[str, bytes, str]]:
    """Dissolve village polygons into one valid MultiPolygon per county."""

    with connection.cursor() as cursor:
        cursor.execute(
            "CREATE TEMP TABLE _village_import (county_code text, geom geometry(Geometry, 4326)) ON COMMIT DROP"
        )
        with cursor.copy(
            "COPY _village_import (county_code, geom) FROM STDIN"
        ) as copy:
            for county_code, wkt in villages:
                copy.write_row((county_code, wkt))
        cursor.execute(
            """
            SELECT
                county_code,
                ST_AsEWKB(geom) AS ewkb,
                encode(sha256(ST_AsEWKB(geom)), 'hex') AS geom_sha256
            FROM (
                SELECT
                    county_code,
                    ST_Multi(
                        ST_CollectionExtract(
                            ST_MakeValid(ST_Union(ST_MakeValid(geom))),
                            3
                        )
                    )::geometry(MultiPolygon, 4326) AS geom
                FROM _village_import
                GROUP BY county_code
            ) dissolved
            ORDER BY county_code
            """
        )
        return [(str(row[0]), bytes(row[1]), str(row[2])) for row in cursor.fetchall()]


def _validate(boundaries: list[tuple[str, bytes, str]]) -> None:
    if len(boundaries) != EXPECTED_COUNTY_COUNT:
        raise SystemExit(
            f"dissolve produced {len(boundaries)} counties, expected {EXPECTED_COUNTY_COUNT}"
        )
    codes = [code for code, _wkb, _digest in boundaries]
    if len(set(codes)) != len(codes):
        raise SystemExit("duplicate jurisdiction_code in dissolved output")


def _manifest_sha256(
    connection: psycopg.Connection,
    boundaries: list[tuple[str, bytes, str]],
) -> str:
    """Compute the manifest digest exactly as the database contract defines it.

    The runbook pins this format: a `jsonb_agg` array of
    `[jurisdiction_code, geom_sha256]` ordered by `jurisdiction_code`, cast to
    text, hashed as UTF-8 bytes. It must be computed by PostgreSQL so the
    serializer matches the database's own, not Python's.
    """

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT jsonb_agg(
                jsonb_build_array(entry.jurisdiction_code, entry.geom_sha256)
                ORDER BY entry.jurisdiction_code
            )::text
            FROM unnest(%s::text[], %s::text[])
                AS entry(jurisdiction_code, geom_sha256)
            """,
            (
                [code for code, _wkb, _digest in boundaries],
                [digest for _code, _wkb, digest in boundaries],
            ),
        )
        row = cursor.fetchone()
    if row is None or row[0] is None:
        raise SystemExit("manifest aggregation returned no rows")
    return hashlib.sha256(str(row[0]).encode("utf-8")).hexdigest()


def _write_snapshot(
    connection: psycopg.Connection,
    *,
    boundaries: list[tuple[str, bytes, str]],
    manifest_sha256: str,
    source_revision: str,
) -> str:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO realtime_jurisdiction_boundary_snapshots (
                source_name, source_url, source_revision,
                expected_count, imported_count, manifest_sha256,
                is_complete, is_active
            )
            VALUES (%s, %s, %s, %s, %s, %s, false, false)
            RETURNING id
            """,
            (
                SOURCE_NAME,
                SOURCE_URL,
                source_revision,
                EXPECTED_COUNTY_COUNT,
                len(boundaries),
                manifest_sha256,
            ),
        )
        row = cursor.fetchone()
        if row is None:
            raise SystemExit("snapshot insert returned no id")
        snapshot_id = str(row[0])
        for code, ewkb, digest in boundaries:
            cursor.execute(
                """
                INSERT INTO realtime_jurisdiction_boundaries (
                    snapshot_id, jurisdiction_code, geom, geom_sha256
                )
                VALUES (%s, %s, ST_GeomFromEWKB(%s), %s)
                """,
                (snapshot_id, code, ewkb, digest),
            )
    return snapshot_id


if __name__ == "__main__":
    raise SystemExit(main())
