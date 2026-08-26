"""Contract tests for the boundary snapshot activation script.

Activation is what makes jurisdiction resolution live for every user, so its
refusal conditions are the safety-relevant part. These tests drive the script
against a fake cursor to prove it refuses rather than committing a bad state.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "infra" / "scripts" / "activate_jurisdiction_boundary_snapshot.py"

_spec = importlib.util.spec_from_file_location("_boundary_activation", SCRIPT)
assert _spec is not None and _spec.loader is not None
activation = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(activation)

SNAPSHOT = "acc0cdb5-7419-4d9a-8e27-216e784bbd03"


class _Cursor:
    """Minimal cursor stub returning scripted results per call."""

    def __init__(self, results: list[Any], rowcounts: list[int] | None = None) -> None:
        self._results = list(results)
        self._rowcounts = list(rowcounts or [])
        self.rowcount = 0
        self.statements: list[str] = []

    def execute(self, sql: str, params: Any = None) -> None:
        del params
        self.statements.append(sql)
        self._last = self._results.pop(0) if self._results else None
        self.rowcount = self._rowcounts.pop(0) if self._rowcounts else 1

    def fetchone(self) -> Any:
        return self._last

    def fetchall(self) -> Any:
        return self._last


def test_checksum_reverification_passes_when_nothing_disagrees() -> None:
    cursor = _Cursor([(0,)])

    activation._assert_checksums_reverify(cursor, SNAPSHOT)

    assert "encode(sha256(ST_AsEWKB(geom)), 'hex') <> geom_sha256" in cursor.statements[0]


def test_activation_refuses_when_a_stored_geometry_checksum_disagrees() -> None:
    cursor = _Cursor([(1,)])

    with pytest.raises(SystemExit) as excinfo:
        activation._assert_checksums_reverify(cursor, SNAPSHOT)

    assert "checksums disagree" in str(excinfo.value)


def test_completion_refuses_when_the_snapshot_is_not_fully_imported() -> None:
    """The UPDATE is guarded by imported_count = expected_count, so a partial
    import matches zero rows and must abort rather than silently continue."""

    cursor = _Cursor([None], rowcounts=[0])

    with pytest.raises(SystemExit) as excinfo:
        activation._complete(cursor, SNAPSHOT, "ref")

    assert "touched 0 rows" in str(excinfo.value)


def test_activation_refuses_when_the_guarded_update_matches_nothing() -> None:
    cursor = _Cursor([None, None], rowcounts=[1, 0])

    with pytest.raises(SystemExit) as excinfo:
        activation._activate(cursor, SNAPSHOT)

    assert "activation touched 0 rows" in str(excinfo.value)


def test_activation_refuses_to_leave_more_than_one_active_snapshot() -> None:
    cursor = _Cursor([None, None, (2,)], rowcounts=[1, 1, 1])

    with pytest.raises(SystemExit) as excinfo:
        activation._activate(cursor, SNAPSHOT)

    assert "2 snapshots would be active" in str(excinfo.value)


def test_activation_deactivates_every_other_snapshot_first() -> None:
    cursor = _Cursor([None, None, (1,)], rowcounts=[1, 1, 1])

    activation._activate(cursor, SNAPSHOT)

    # Order matters: deactivating others first means a crash between the two
    # statements leaves zero active snapshots (fail closed) rather than two.
    assert "SET is_active = false WHERE id <> %s" in cursor.statements[0]
    assert "SET is_active = true" in cursor.statements[1]
    assert "is_active = true" not in cursor.statements[0]


def test_snapshot_resolution_requires_an_explicit_id_when_ambiguous() -> None:
    cursor = _Cursor([[("a",), ("b",)]])

    with pytest.raises(SystemExit) as excinfo:
        activation._resolve_snapshot(cursor, None)

    assert "--snapshot-id" in str(excinfo.value)
