#!/usr/bin/env python3
"""Activate an imported county jurisdiction boundary snapshot.

Activation is the step that lets a query point resolve to a home county. Until a
snapshot is active the assessment path reports `boundary_unverified`, falls back
to national sources, and every local government sensor stays invisible.

This is deliberately a separate script from the importer. Importing is safe and
reversible; activating changes what every user sees. See
docs/runbooks/station-inventory-and-jurisdiction-review.md.

The activation runs in one transaction and refuses to commit unless:

  * the snapshot is fully imported (imported_count == expected_count),
  * a manifest digest exists and is adopted as the approved digest,
  * every stored geometry re-verifies against its recorded EWKB checksum,
  * exactly one snapshot ends up active.

Rollback is a single statement:

    UPDATE realtime_jurisdiction_boundary_snapshots SET is_active = false;
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

import psycopg


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--snapshot-id", help="Defaults to the only imported snapshot.")
    parser.add_argument(
        "--review-ref",
        required=True,
        help="Audit trail for who reviewed this activation and how.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    with psycopg.connect(args.database_url, connect_timeout=20) as connection:
        with connection.cursor() as cursor:
            snapshot_id = _resolve_snapshot(cursor, args.snapshot_id)
            _report(cursor, snapshot_id)
            _assert_checksums_reverify(cursor, snapshot_id)
            if args.dry_run:
                print("dry run: nothing activated")
                return 0
            _complete(cursor, snapshot_id, args.review_ref)
            _activate(cursor, snapshot_id)
        connection.commit()
        _report(connection.cursor(), snapshot_id)
    print("activated")
    return 0


def _resolve_snapshot(cursor: psycopg.Cursor, snapshot_id: str | None) -> str:
    if snapshot_id:
        return snapshot_id
    cursor.execute("SELECT id::text FROM realtime_jurisdiction_boundary_snapshots")
    rows = cursor.fetchall()
    if len(rows) != 1:
        raise SystemExit(
            f"expected exactly one snapshot, found {len(rows)}; pass --snapshot-id"
        )
    return str(rows[0][0])


def _report(cursor: psycopg.Cursor, snapshot_id: str) -> None:
    cursor.execute(
        """
        SELECT s.source_revision, s.expected_count, s.imported_count,
               count(b.snapshot_id), count(DISTINCT b.jurisdiction_code),
               bool_and(ST_IsValid(b.geom)), bool_and(NOT ST_IsEmpty(b.geom)),
               bool_and(GeometryType(b.geom) = 'MULTIPOLYGON'),
               s.is_complete, s.is_active
        FROM realtime_jurisdiction_boundary_snapshots s
        LEFT JOIN realtime_jurisdiction_boundaries b ON b.snapshot_id = s.id
        WHERE s.id = %s
        GROUP BY s.id
        """,
        (snapshot_id,),
    )
    row = cursor.fetchone()
    if row is None:
        raise SystemExit(f"snapshot {snapshot_id} not found")
    print(
        f"snapshot {snapshot_id} revision={row[0]} imported={row[2]}/{row[1]} "
        f"rows={row[3]} jurisdictions={row[4]} valid={row[5]} nonempty={row[6]} "
        f"multipolygon={row[7]} is_complete={row[8]} is_active={row[9]}"
    )


def _assert_checksums_reverify(cursor: psycopg.Cursor, snapshot_id: str) -> None:
    cursor.execute(
        """
        SELECT count(*) FROM realtime_jurisdiction_boundaries
        WHERE snapshot_id = %s
          AND encode(sha256(ST_AsEWKB(geom)), 'hex') <> geom_sha256
        """,
        (snapshot_id,),
    )
    row = cursor.fetchone()
    mismatched = int(row[0]) if row else -1
    if mismatched != 0:
        raise SystemExit(f"refusing to activate: {mismatched} geometry checksums disagree")
    print("every stored geometry re-verifies against its recorded EWKB checksum")


def _complete(cursor: psycopg.Cursor, snapshot_id: str, review_ref: str) -> None:
    cursor.execute(
        """
        UPDATE realtime_jurisdiction_boundary_snapshots
        SET approved_manifest_sha256 = manifest_sha256,
            is_complete = true,
            reviewed_at = %s,
            review_ref = %s
        WHERE id = %s
          AND manifest_sha256 IS NOT NULL
          AND imported_count = expected_count
        """,
        (datetime.now(UTC), review_ref, snapshot_id),
    )
    if cursor.rowcount != 1:
        raise SystemExit(
            f"refusing to activate: completion update touched {cursor.rowcount} rows"
        )


def _activate(cursor: psycopg.Cursor, snapshot_id: str) -> None:
    cursor.execute(
        "UPDATE realtime_jurisdiction_boundary_snapshots SET is_active = false WHERE id <> %s",
        (snapshot_id,),
    )
    cursor.execute(
        """
        UPDATE realtime_jurisdiction_boundary_snapshots
        SET is_active = true
        WHERE id = %s
          AND is_complete = true
          AND manifest_sha256 = approved_manifest_sha256
          AND imported_count = expected_count
        """,
        (snapshot_id,),
    )
    if cursor.rowcount != 1:
        raise SystemExit(f"refusing to activate: activation touched {cursor.rowcount} rows")
    cursor.execute(
        "SELECT count(*) FROM realtime_jurisdiction_boundary_snapshots WHERE is_active"
    )
    row = cursor.fetchone()
    active = int(row[0]) if row else -1
    if active != 1:
        raise SystemExit(f"refusing to commit: {active} snapshots would be active")


if __name__ == "__main__":
    raise SystemExit(main())
