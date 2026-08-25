from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.request import Request

import pytest

from app.adapters.contracts import EventType, SourceFamily
from app.adapters.wra import (
    WRA_HISTORICAL_FLOOD_INDEX_URL,
    WraHistoricalFloodAdapter,
    WraHistoricalFloodPayloadError,
)
from app.adapters.wra import historical_flood as historical_flood_module
from app.config import load_worker_settings
from app.jobs.runtime import build_runtime_adapters
from app.pipelines.staging import build_staging_batch

FIXTURE_DIR = Path(__file__).parent / "fixtures"
APPROVED_KML_URL = (
    "https://opendata.wra.gov.tw/cloud/HistoricalFloodingArea/210-history.kml"
)
FETCHED_AT = datetime(2026, 8, 25, 4, 0, tzinfo=UTC)
RUN_STARTED_AT = datetime(2026, 8, 25, 3, 59, tzinfo=UTC)
CANONICAL_WRA_SCHEMA_LOCATION = (
    "http://www.opengis.net/kml/2.2 "
    "http://schemas.opengis.net/kml/2.2.0/ogckml22.xsd "
    "http://www.google.com/kml/ext/2.2 "
    "http://code.google.com/apis/kml/schema/kml22gx.xsd"
)


def _index_payload() -> object:
    return json.loads(
        (FIXTURE_DIR / "wra_historical_flood_index.json").read_text(encoding="utf-8")
    )


def _kml_text() -> str:
    return (FIXTURE_DIR / "wra_historical_flood_sample.kml").read_text(
        encoding="utf-8"
    )


def _adapter(
    *,
    index: object | None = None,
    kml: str | None = None,
) -> WraHistoricalFloodAdapter:
    return WraHistoricalFloodAdapter(
        fetched_at=FETCHED_AT,
        fetch_json=lambda _url, _timeout: _index_payload() if index is None else index,
        fetch_text=lambda _url, _timeout: _kml_text() if kml is None else kml,
    )


def _polygon_kml(
    outer: tuple[tuple[float, float], ...],
    *,
    holes: tuple[tuple[tuple[float, float], ...], ...] = (),
) -> str:
    def coordinates(ring: tuple[tuple[float, float], ...]) -> str:
        return " ".join(f"{longitude},{latitude}" for longitude, latitude in ring)

    inner_boundaries = "".join(
        "<innerBoundaryIs><LinearRing><coordinates>"
        f"{coordinates(hole)}"
        "</coordinates></LinearRing></innerBoundaryIs>"
        for hole in holes
    )
    return (
        '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
        "<name>2020-08-01</name><Placemark><name>topology contract</name><Polygon>"
        "<outerBoundaryIs><LinearRing><coordinates>"
        f"{coordinates(outer)}"
        "</coordinates></LinearRing></outerBoundaryIs>"
        f"{inner_boundaries}"
        "</Polygon></Placemark></Document></kml>"
    )


def test_fetch_resolves_metadata_then_reads_kml() -> None:
    requested_urls: list[tuple[str, int]] = []

    def fake_index(url: str, timeout_seconds: int) -> object:
        requested_urls.append((url, timeout_seconds))
        return _index_payload()

    def fake_kml(url: str, timeout_seconds: int) -> str:
        requested_urls.append((url, timeout_seconds))
        return _kml_text()

    adapter = WraHistoricalFloodAdapter(
        fetch_json=fake_index,
        fetch_text=fake_kml,
        timeout_seconds=6,
        fetched_at=FETCHED_AT,
    )

    rows = adapter.fetch()

    assert requested_urls == [
        (WRA_HISTORICAL_FLOOD_INDEX_URL, 6),
        (APPROVED_KML_URL, 6),
    ]
    assert len(rows) == 4
    assert rows[0].source_url == "https://data.gov.tw/dataset/25770"
    assert rows[0].payload["evidence_scope"] == "historical"
    assert rows[0].payload["metadata_url"] == WRA_HISTORICAL_FLOOD_INDEX_URL
    assert rows[0].payload["resolved_kml_url"] == APPROVED_KML_URL
    assert rows[0].payload["dataset_revision"] == "2018-06-08T16:26:00"
    assert "event time" in " ".join(rows[0].payload["limitations"])


def test_fetch_selects_the_latest_imported_kml_metadata_record() -> None:
    old_url = "https://opendata.wra.gov.tw/cloud/HistoricalFloodingArea/old.kml"
    current_url = "https://opendata.wra.gov.tw/cloud/HistoricalFloodingArea/current.kml"
    index = [
        {
            "createdatatime": "2020-01-01T00:00:00",
            "_importdate": "2026-01-01T00:00:00+08:00",
            "fileex": "kml",
            "sourceurl": old_url,
        },
        {
            "createdatatime": "2018-06-08T16:26:00",
            "_importdate": "2026-02-01T00:00:00+08:00",
            "fileex": "kml",
            "sourceurl": current_url,
        },
    ]
    requested: list[str] = []
    adapter = WraHistoricalFloodAdapter(
        fetched_at=FETCHED_AT,
        fetch_json=lambda _url, _timeout: index,
        fetch_text=lambda url, _timeout: requested.append(url) or _kml_text(),
    )

    rows = adapter.fetch()

    assert requested == [current_url]
    assert rows[0].payload["resolved_kml_url"] == current_url
    assert rows[0].payload["dataset_revision"] == "2018-06-08T16:26:00"


def test_normalize_marks_history_and_preserves_source_geometry() -> None:
    result = _adapter().run()

    assert len(result.normalized) == 3
    assert result.rejected == (result.fetched[-1].source_id,)
    assert result.normalized[0].event_type is EventType.FLOOD_REPORT
    assert result.normalized[0].source_family is SourceFamily.OFFICIAL
    # WRA date-only event names are Taiwan-local dates, then normalized to UTC.
    assert result.normalized[0].source_timestamp == datetime(
        2016, 9, 26, 16, 0, tzinfo=UTC
    )
    assert result.normalized[0].fetched_at == FETCHED_AT
    assert result.fetched[0].payload["location_precision"] == "polygon"
    assert result.fetched[0].payload["geometry"]["type"] == "Polygon"
    assert len(result.fetched[0].payload["geometry"]["coordinates"]) == 2
    assert result.fetched[1].payload["location_precision"] == "point"
    assert result.fetched[1].payload["geometry"] == {
        "type": "Point",
        "coordinates": [120.488, 22.682],
    }
    assert result.fetched[2].payload["geometry"]["type"] == "MultiPolygon"

    staged = build_staging_batch(
        result,
        ingestion_generation_started_at=RUN_STARTED_AT,
    ).accepted
    assert len(staged) == 3
    assert staged[0].occurred_at == datetime(2016, 9, 26, 16, 0, tzinfo=UTC)
    assert staged[0].occurred_at != FETCHED_AT
    for raw, item in zip(result.fetched[:3], staged, strict=True):
        assert item.payload["evidence_scope"] == "historical"
        assert item.payload["location_precision"] in {"point", "polygon"}
        assert item.payload["location_payload"]["geometry"] == raw.payload["geometry"]
        assert item.payload["source_url"] == WRA_HISTORICAL_FLOOD_INDEX_URL
        assert item.payload["resource_url"] == APPROVED_KML_URL


def test_source_ids_are_stable_and_exact_duplicate_placemarks_are_deduplicated() -> None:
    first = _adapter().fetch()
    second = _adapter().fetch()

    assert tuple(row.source_id for row in first) == tuple(row.source_id for row in second)
    assert len({row.source_id for row in first}) == 4
    assert [row.payload["placemark_id"] for row in first].count("P-1") == 1
    assert first[1].payload["placemark_id"] == ""


def test_parser_repairs_only_the_official_missing_xsi_namespace_defect() -> None:
    # The official producer uses xsi:schemaLocation but omits xmlns:xsi on the root.
    assert len(_adapter().fetch()) == 4

    unrelated_unbound_prefix = """\
    <kml xmlns="http://www.opengis.net/kml/2.2"><Document foo:bar="x">
      <name>105-09-27</name>
      <Placemark><name>x</name><Point><coordinates>120,23</coordinates></Point></Placemark>
    </Document></kml>
    """
    with pytest.raises(WraHistoricalFloodPayloadError, match="parseable"):
        _adapter(kml=unrelated_unbound_prefix).fetch()


@pytest.mark.parametrize(
    "kml",
    (
        """\
        <Document xmlns="http://www.opengis.net/kml/2.2"><name>2020-08-01</name>
          <Placemark><name>x</name><Point><coordinates>120,23</coordinates></Point></Placemark>
        </Document>
        """,
        """\
        <kml><Document><name>2020-08-01</name>
          <Placemark><name>x</name><Point><coordinates>120,23</coordinates></Point></Placemark>
        </Document></kml>
        """,
        """\
        <kml xmlns="urn:not-kml"><Document><name>2020-08-01</name>
          <Placemark><name>x</name><Point><coordinates>120,23</coordinates></Point></Placemark>
        </Document></kml>
        """,
    ),
)
def test_parser_requires_the_exact_kml_22_root(kml: str) -> None:
    with pytest.raises(WraHistoricalFloodPayloadError, match="KML 2.2 root"):
        _adapter(kml=kml).fetch()


def test_parser_does_not_repair_an_arbitrary_xsi_schema_location() -> None:
    kml = """\
    <kml xmlns="http://www.opengis.net/kml/2.2"><Document
      xsi:schemaLocation="http://www.opengis.net/kml/2.2 https://evil.example/kml.xsd">
      <name>2020-08-01</name>
      <Placemark><name>x</name><Point><coordinates>120,23</coordinates></Point></Placemark>
    </Document></kml>
    """

    with pytest.raises(WraHistoricalFloodPayloadError, match="parseable"):
        _adapter(kml=kml).fetch()


def test_parser_does_not_repair_extra_unbound_xsi_attributes() -> None:
    kml = f"""\
    <kml xmlns="http://www.opengis.net/kml/2.2"><Document
      xsi:schemaLocation="{CANONICAL_WRA_SCHEMA_LOCATION}" xsi:arbitrary="unsafe">
      <name>2020-08-01</name>
      <Placemark><name>x</name><Point><coordinates>120,23</coordinates></Point></Placemark>
    </Document></kml>
    """

    with pytest.raises(WraHistoricalFloodPayloadError, match="parseable"):
        _adapter(kml=kml).fetch()


@pytest.mark.parametrize(
    "redirect_target",
    (
        "http://opendata.wra.gov.tw/cloud/downgrade.kml",
        "https://evil.example/history.kml",
        "https://opendata.wra.gov.tw.evil.example/history.kml",
        "https://user@opendata.wra.gov.tw/cloud/history.kml",
        "https://opendata.wra.gov.tw:444/cloud/history.kml",
        "https://opendata.wra.gov.tw:not-a-port/cloud/history.kml",
    ),
)
def test_kml_redirect_handler_rejects_every_unapproved_hop(
    redirect_target: str,
) -> None:
    handler = historical_flood_module._WraHistoricalRedirectHandler()

    with pytest.raises(WraHistoricalFloodPayloadError, match="approved HTTPS"):
        handler.redirect_request(
            Request(APPROVED_KML_URL),
            None,
            302,
            "Found",
            {},
            redirect_target,
        )


def test_kml_redirect_handler_allows_relative_and_same_host_https_hops() -> None:
    handler = historical_flood_module._WraHistoricalRedirectHandler()
    first = handler.redirect_request(
        Request(APPROVED_KML_URL),
        None,
        302,
        "Found",
        {},
        "../next/history.kml",
    )
    assert first.full_url == "https://opendata.wra.gov.tw/cloud/next/history.kml"

    second = handler.redirect_request(
        first,
        None,
        307,
        "Temporary Redirect",
        {},
        "https://opendata.wra.gov.tw:443/cloud/final.kml",
    )
    assert second.full_url == "https://opendata.wra.gov.tw:443/cloud/final.kml"


@pytest.mark.parametrize(
    "sourceurl",
    (
        "http://opendata.wra.gov.tw/cloud/history.kml",
        "https://evil.example/history.kml",
        "https://opendata.wra.gov.tw.evil.example/history.kml",
    ),
)
def test_fetch_rejects_non_https_or_off_domain_kml_urls(sourceurl: str) -> None:
    payload = [
        {
            "createdatatime": "2018-06-08T16:26:00",
            "fileex": "kml",
            "filename": "history",
            "sourceurl": sourceurl,
        }
    ]
    called = False

    def forbidden_fetch(_url: str, _timeout: int) -> str:
        nonlocal called
        called = True
        return _kml_text()

    adapter = WraHistoricalFloodAdapter(
        fetch_json=lambda _url, _timeout: payload,
        fetch_text=forbidden_fetch,
        fetched_at=FETCHED_AT,
    )

    with pytest.raises(WraHistoricalFloodPayloadError, match="approved HTTPS"):
        adapter.fetch()
    assert called is False


def test_fetch_rejects_metadata_without_a_kml_record() -> None:
    adapter = _adapter(index=[{"fileex": "csv", "sourceurl": APPROVED_KML_URL}])

    with pytest.raises(WraHistoricalFloodPayloadError, match="KML record"):
        adapter.fetch()


@pytest.mark.parametrize(
    ("kml", "message"),
    (
        ("<kml><Placemark>", "parseable"),
        ("<kml xmlns='http://www.opengis.net/kml/2.2'><Document/></kml>", "Placemark"),
        (
            (
                "<!DOCTYPE foo [<!ENTITY xxe SYSTEM 'file:///etc/passwd'>]>"
                "<kml><Placemark><name>&xxe;</name></Placemark></kml>"
            ),
            "parseable",
        ),
    ),
)
def test_fetch_rejects_malformed_or_empty_kml(kml: str, message: str) -> None:
    with pytest.raises(WraHistoricalFloodPayloadError, match=message):
        _adapter(kml=kml).fetch()


def test_fetch_rejects_out_of_taiwan_and_invalid_geometries() -> None:
    kml = """\
    <kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>2020-08-01</name>
      <Placemark id="outside"><Point><coordinates>139.7,35.6</coordinates></Point></Placemark>
      <Placemark id="open-ring"><Polygon><outerBoundaryIs><LinearRing>
        <coordinates>120,23 121,23 121,24 120,24</coordinates>
      </LinearRing></outerBoundaryIs></Polygon></Placemark>
    </Document></kml>
    """

    with pytest.raises(WraHistoricalFloodPayloadError, match="valid Placemark"):
        _adapter(kml=kml).fetch()


def test_fetch_rejects_an_entire_multigeometry_when_any_polygon_is_invalid() -> None:
    kml = """\
    <kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>2020-08-01</name>
      <Placemark><name>partial geometry must not survive</name><MultiGeometry>
        <Polygon><outerBoundaryIs><LinearRing>
          <coordinates>120,23 120.1,23 120.1,23.1 120,23.1 120,23</coordinates>
        </LinearRing></outerBoundaryIs></Polygon>
        <Polygon><outerBoundaryIs><LinearRing>
          <coordinates>139,35 139.1,35 139.1,35.1 139,35.1 139,35</coordinates>
        </LinearRing></outerBoundaryIs></Polygon>
      </MultiGeometry></Placemark>
    </Document></kml>
    """

    with pytest.raises(WraHistoricalFloodPayloadError, match="valid Placemark"):
        _adapter(kml=kml).fetch()


def test_fetch_rejects_overlapping_multipolygon_members() -> None:
    kml = """\
    <kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>2020-08-01</name>
      <Placemark><name>overlapping members</name><MultiGeometry>
        <Polygon><outerBoundaryIs><LinearRing>
          <coordinates>120,23 120.06,23 120.06,23.06 120,23.06 120,23</coordinates>
        </LinearRing></outerBoundaryIs></Polygon>
        <Polygon><outerBoundaryIs><LinearRing>
          <coordinates>120.04,23.04 120.1,23.04 120.1,23.1 120.04,23.1 120.04,23.04</coordinates>
        </LinearRing></outerBoundaryIs></Polygon>
      </MultiGeometry></Placemark>
    </Document></kml>
    """

    with pytest.raises(WraHistoricalFloodPayloadError, match="valid Placemark"):
        _adapter(kml=kml).fetch()


@pytest.mark.parametrize(
    "outer",
    (
        (
            (120.0, 23.0),
            (120.04, 23.04),
            (120.0, 23.04),
            (120.04, 23.0),
            (120.0, 23.0),
        ),
        (
            (120.0, 23.0),
            (120.01, 23.0),
            (120.02, 23.0),
            (120.0, 23.0),
        ),
        (
            (120.0, 23.0),
            (120.04, 23.0),
            (120.04, 23.04),
            (120.02, 23.02),
            (120.0, 23.04),
            (120.02, 23.02),
            (120.0, 23.0),
        ),
    ),
)
def test_fetch_rejects_self_intersecting_zero_area_or_self_touching_rings(
    outer: tuple[tuple[float, float], ...],
) -> None:
    with pytest.raises(WraHistoricalFloodPayloadError, match="valid Placemark"):
        _adapter(kml=_polygon_kml(outer)).fetch()


SQUARE_SHELL = (
    (120.0, 23.0),
    (120.1, 23.0),
    (120.1, 23.1),
    (120.0, 23.1),
    (120.0, 23.0),
)


@pytest.mark.parametrize(
    "hole",
    (
        (
            (120.11, 23.02),
            (120.12, 23.02),
            (120.12, 23.03),
            (120.11, 23.03),
            (120.11, 23.02),
        ),
        (
            (120.0, 23.02),
            (120.02, 23.02),
            (120.02, 23.04),
            (120.0, 23.04),
            (120.0, 23.02),
        ),
        (
            (119.99, 23.02),
            (120.02, 23.02),
            (120.02, 23.04),
            (119.99, 23.04),
            (119.99, 23.02),
        ),
    ),
)
def test_fetch_rejects_holes_outside_touching_or_crossing_the_shell(
    hole: tuple[tuple[float, float], ...],
) -> None:
    with pytest.raises(WraHistoricalFloodPayloadError, match="valid Placemark"):
        _adapter(kml=_polygon_kml(SQUARE_SHELL, holes=(hole,))).fetch()


@pytest.mark.parametrize(
    "holes",
    (
        (
            ((120.02, 23.02), (120.06, 23.02), (120.06, 23.06), (120.02, 23.06), (120.02, 23.02)),
            ((120.04, 23.04), (120.08, 23.04), (120.08, 23.08), (120.04, 23.08), (120.04, 23.04)),
        ),
        (
            ((120.02, 23.02), (120.08, 23.02), (120.08, 23.08), (120.02, 23.08), (120.02, 23.02)),
            ((120.03, 23.03), (120.04, 23.03), (120.04, 23.04), (120.03, 23.04), (120.03, 23.03)),
        ),
        (
            ((120.02, 23.02), (120.04, 23.02), (120.04, 23.04), (120.02, 23.04), (120.02, 23.02)),
            ((120.04, 23.02), (120.06, 23.02), (120.06, 23.04), (120.04, 23.04), (120.04, 23.02)),
        ),
    ),
)
def test_fetch_rejects_overlapping_nested_or_touching_holes(
    holes: tuple[tuple[tuple[float, float], ...], ...],
) -> None:
    with pytest.raises(WraHistoricalFloodPayloadError, match="valid Placemark"):
        _adapter(kml=_polygon_kml(SQUARE_SHELL, holes=holes)).fetch()


def test_valid_polygon_hole_reaches_staging_unchanged() -> None:
    hole = (
        (120.02, 23.02),
        (120.04, 23.02),
        (120.04, 23.04),
        (120.02, 23.04),
        (120.02, 23.02),
    )
    result = _adapter(kml=_polygon_kml(SQUARE_SHELL, holes=(hole,))).run()

    assert len(result.normalized) == 1
    staged = build_staging_batch(
        result,
        ingestion_generation_started_at=RUN_STARTED_AT,
    ).accepted[0]
    assert staged.payload["location_payload"]["geometry"] == result.fetched[0].payload[
        "geometry"
    ]


def test_source_event_time_never_falls_back_to_dataset_revision_or_fetched_at() -> None:
    result = _adapter().run()
    rejected = result.fetched[-1]

    assert "source_timestamp" not in rejected.payload
    assert _adapter().normalize(rejected) is None
    assert rejected.fetched_at == FETCHED_AT
    assert rejected.payload["dataset_revision"] == "2018-06-08T16:26:00"


def test_config_and_runtime_require_independent_disabled_by_default_gates() -> None:
    defaults = load_worker_settings({})
    assert defaults.source_wra_historical_flood_enabled is None
    assert defaults.source_wra_historical_flood_api_enabled is False
    assert defaults.wra_historical_flood_index_url is None
    assert defaults.wra_historical_flood_timeout_seconds == 8
    assert "official.wra.historical_flood" not in build_runtime_adapters(defaults)

    only_catalog_gate = load_worker_settings(
        {
            "WORKER_ENABLED_ADAPTER_KEYS": "official.wra.historical_flood",
            "SOURCE_WRA_HISTORICAL_FLOOD_ENABLED": "true",
        }
    )
    assert "official.wra.historical_flood" not in build_runtime_adapters(
        only_catalog_gate
    )

    settings = load_worker_settings(
        {
            "WORKER_ENABLED_ADAPTER_KEYS": "official.wra.historical_flood",
            "SOURCE_WRA_HISTORICAL_FLOOD_ENABLED": "true",
            "SOURCE_WRA_HISTORICAL_FLOOD_API_ENABLED": "true",
            "WRA_HISTORICAL_FLOOD_INDEX_URL": "https://example.test/index",
            "WRA_HISTORICAL_FLOOD_TIMEOUT_SECONDS": "5",
        }
    )
    calls: list[tuple[str, int]] = []

    def fetch_json(url: str, timeout: int) -> Any:
        calls.append((url, timeout))
        return _index_payload()

    def fetch_text(url: str, timeout: int) -> str:
        calls.append((url, timeout))
        return _kml_text()

    adapters = build_runtime_adapters(
        settings,
        fetched_at=FETCHED_AT,
        wra_historical_flood_fetch_json=fetch_json,
        wra_historical_flood_fetch_text=fetch_text,
    )

    assert tuple(adapters) == ("official.wra.historical_flood",)
    assert len(adapters["official.wra.historical_flood"].run().normalized) == 3
    assert calls == [
        ("https://example.test/index", 5),
        (APPROVED_KML_URL, 5),
    ]
