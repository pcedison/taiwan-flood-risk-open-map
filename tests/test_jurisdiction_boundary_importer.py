"""Contract tests for the county boundary importer.

The importer exists so a query point can resolve to a home county. Without an
active snapshot the assessment path falls back to national sources and every
local government sensor stays invisible.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "infra" / "scripts" / "import_jurisdiction_boundaries.py"

_spec = importlib.util.spec_from_file_location("_boundary_importer", SCRIPT)
assert _spec is not None and _spec.loader is not None
importer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(importer)


def _shape(points: list[tuple[float, float]], parts: list[int] | None = None):
    return SimpleNamespace(points=points, parts=parts or [0])


SQUARE = [(120.10, 23.00), (120.12, 23.00), (120.12, 23.02), (120.10, 23.02), (120.10, 23.00)]


def test_county_code_mapping_matches_the_database_contract() -> None:
    """The shapefile carries a 5-digit COUNTYCODE; the database uses 8 digits."""

    assert importer._canonical_county_code({"COUNTYCODE": "67000"}) == "67000000"
    assert importer._canonical_county_code({"COUNTYCODE": "10013"}) == "10013000"
    assert importer._canonical_county_code({"COUNTYCODE": "09007"}) == "09007000"


def test_malformed_county_codes_are_rejected() -> None:
    for raw in (None, "", "670", "6700000", "abcde", "6700a"):
        assert importer._canonical_county_code({"COUNTYCODE": raw}) is None


def test_offshore_territory_is_kept_and_flagged_not_dropped() -> None:
    """Regression: 東沙島, 太平島 and 釣魚台列嶼 are real ROC territory.

    An earlier version filtered rings against a core-island bounding box and
    silently discarded all three. Worse, 宜蘭縣頭城鎮大溪里 is a mainland coastal
    village whose polygon reaches 釣魚台, so dropping it punched a hole in the
    Yilan county boundary and left that area unable to resolve to a county.
    """

    itu_aba = [(114.359, 10.371), (114.371, 10.371), (114.371, 10.380), (114.359, 10.380), (114.359, 10.371)]
    parsed = importer._polygon_wkt(_shape(itu_aba))

    assert parsed is not None, "offshore territory must not be dropped"
    wkt, outlying = parsed
    assert outlying is True, "offshore territory must be reported"
    assert wkt.startswith("POLYGON((")


def test_core_island_geometry_is_not_flagged_as_outlying() -> None:
    parsed = importer._polygon_wkt(_shape(SQUARE))

    assert parsed is not None
    _wkt, outlying = parsed
    assert outlying is False


def test_coordinates_off_the_globe_are_rejected() -> None:
    assert importer._valid_coordinate(120.1, 23.0) is True
    assert importer._valid_coordinate(114.36, 10.37) is True
    assert importer._valid_coordinate(181.0, 23.0) is False
    assert importer._valid_coordinate(120.1, 91.0) is False
    assert importer._valid_coordinate(float("nan"), 23.0) is False
    assert importer._valid_coordinate(float("inf"), 23.0) is False


def test_unclosed_rings_are_closed_and_degenerate_rings_dropped() -> None:
    parsed = importer._polygon_wkt(_shape(SQUARE[:-1]))
    assert parsed is not None
    assert parsed[0].count("120.1 23.0") >= 1

    assert importer._polygon_wkt(_shape([(120.1, 23.0), (120.2, 23.0)])) is None


def test_importer_expects_exactly_twenty_two_counties() -> None:
    assert importer.EXPECTED_COUNTY_COUNT == 22
