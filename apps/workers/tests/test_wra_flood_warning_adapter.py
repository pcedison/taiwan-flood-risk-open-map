from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.adapters.contracts import EventType
from app.adapters.wra.flood_warning import (
    MAX_WRA_FLOOD_WARNING_KML_BYTES,
    MAX_WRA_FLOOD_WARNING_PLACEMARKS,
    MAX_WRA_FLOOD_WARNING_TOTAL_COORDINATES,
    MAX_WRA_FLOOD_WARNING_XML_DEPTH,
    MAX_WRA_FLOOD_WARNING_XML_ELEMENTS,
    WRA_FLOOD_WARNING_INDEX_URL,
    WRA_FLOOD_WARNING_KML_URLS,
    WRA_FLOOD_WARNING_METADATA,
    WraFloodWarningAdapter,
    WraFloodWarningFetchError,
    WraFloodWarningPayloadError,
    WraFloodWarningRateLimitError,
    approved_wra_flood_warning_url,
    parse_wra_flood_warning_kml,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FETCHED_AT = datetime(2026, 8, 26, 2, 20, tzinfo=UTC)

FLOOD_URL = "https://fhy.wra.gov.tw/pub_web_2011/kml/KmlShare/NewstFloodWarm.kml"
WATER_URL = "https://fhy.wra.gov.tw/pub_web_2011/kml/KmlShare/NewstWaterWarm.kml"
RESERVOIR_URL = "https://fhy.wra.gov.tw/pub_web_2011/kml/KmlShare/NewstReservoirWarm.kml"
ANNOUNCE_URL = "https://fhy.wra.gov.tw/pub_web_2011/kml/KmlShare/AnnounceFlood.kml"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _index_payload() -> object:
    return json.loads(_fixture("wra_flood_warning_index.json"))


def _adapter(
    *,
    fetch_text,
    index_payload: object | None = None,
    fetched_at: datetime = FETCHED_AT,
) -> WraFloodWarningAdapter:
    payload = _index_payload() if index_payload is None else index_payload

    def fetch_json(url: str, timeout_seconds: int) -> object:
        assert url == WRA_FLOOD_WARNING_INDEX_URL
        return payload

    return WraFloodWarningAdapter(
        fetched_at=fetched_at,
        fetch_json=fetch_json,
        fetch_text=fetch_text,
    )


def _empty_map() -> dict[str, str]:
    empty = _fixture("wra_flood_warning_empty.kml")
    return {url: empty for url in WRA_FLOOD_WARNING_KML_URLS}


# ---------------------------------------------------------------- URL policy


def test_exact_index_and_kml_url_constants() -> None:
    assert WRA_FLOOD_WARNING_INDEX_URL == (
        "https://opendata.wra.gov.tw/api/v2/"
        "301c0b62-8736-4e03-95ef-55309c1a5e74"
    )
    assert WRA_FLOOD_WARNING_KML_URLS == (
        FLOOD_URL,
        WATER_URL,
        RESERVOIR_URL,
        ANNOUNCE_URL,
    )


def test_approved_url_returns_the_exact_constant() -> None:
    for url in (*WRA_FLOOD_WARNING_KML_URLS, WRA_FLOOD_WARNING_INDEX_URL):
        assert approved_wra_flood_warning_url(url) == url


def test_approved_url_upgrades_only_exact_http_matches() -> None:
    assert (
        approved_wra_flood_warning_url(
            "http://fhy.wra.gov.tw/pub_web_2011/kml/KmlShare/NewstWaterWarm.kml",
            allow_http_upgrade=True,
        )
        == WATER_URL
    )
    with pytest.raises(WraFloodWarningPayloadError):
        approved_wra_flood_warning_url(
            "http://fhy.wra.gov.tw/pub_web_2011/kml/KmlShare/NewstWaterWarm.kml",
        )


@pytest.mark.parametrize(
    "candidate",
    [
        "https://evil.example/pub_web_2011/kml/KmlShare/NewstFloodWarm.kml",
        "https://fhy.wra.gov.tw/pub_web_2011/kml/KmlShare/OtherWarm.kml",
        "https://user:pass@fhy.wra.gov.tw/pub_web_2011/kml/KmlShare/NewstFloodWarm.kml",
        "https://fhy.wra.gov.tw/pub_web_2011/kml/KmlShare/NewstFloodWarm.kml?x=1",
        "https://fhy.wra.gov.tw/pub_web_2011/kml/KmlShare/NewstFloodWarm.kml#a",
        "https://fhy.wra.gov.tw:8443/pub_web_2011/kml/KmlShare/NewstFloodWarm.kml",
        "https://fhy.wra.gov.tw/pub_web_2011/kml/KmlShare/../KmlShare/NewstFloodWarm.kml",
        "//fhy.wra.gov.tw/pub_web_2011/kml/KmlShare/NewstFloodWarm.kml",
        "ftp://fhy.wra.gov.tw/pub_web_2011/kml/KmlShare/NewstFloodWarm.kml",
        "",
        None,
    ],
)
def test_approved_url_rejects_unapproved_targets(candidate: object) -> None:
    with pytest.raises(WraFloodWarningPayloadError):
        approved_wra_flood_warning_url(candidate, allow_http_upgrade=True)


# ------------------------------------------------------- index intersection


def test_only_allowlisted_index_resources_are_fetched() -> None:
    requested: list[str] = []

    def fetch_text(url: str, timeout_seconds: int) -> str:
        requested.append(url)
        return _fixture("wra_flood_warning_empty.kml")

    _adapter(fetch_text=fetch_text).run()

    assert requested == list(WRA_FLOOD_WARNING_KML_URLS)


def test_index_without_any_allowlisted_resource_fails_closed() -> None:
    def fetch_text(url: str, timeout_seconds: int) -> str:  # pragma: no cover
        raise AssertionError("no child read is allowed")

    adapter = _adapter(
        fetch_text=fetch_text,
        index_payload=[
            {
                "fileex": "kml",
                "sourceurl": (
                    "https://fhy.wra.gov.tw/pub_web_2011/kml/KmlShare/OtherWarm.kml"
                ),
            }
        ],
    )
    with pytest.raises(WraFloodWarningPayloadError):
        adapter.run()


# ------------------------------------------------------------ valid empty


def test_valid_empty_documents_report_no_active_event() -> None:
    documents = _empty_map()

    def fetch_text(url: str, timeout_seconds: int) -> str:
        return documents[url]

    result = _adapter(fetch_text=fetch_text).run()

    assert result.no_active_event is True
    assert result.fetched == ()
    assert result.normalized == ()
    assert result.rejected == ()


def test_transport_failure_is_never_healthy_empty() -> None:
    def fetch_text(url: str, timeout_seconds: int) -> str:
        raise WraFloodWarningFetchError("upstream unavailable")

    with pytest.raises(WraFloodWarningFetchError):
        _adapter(fetch_text=fetch_text).run()


def test_partial_child_failure_is_audited_and_not_healthy_empty() -> None:
    documents = _empty_map()

    def fetch_text(url: str, timeout_seconds: int) -> str:
        if url == WATER_URL:
            raise WraFloodWarningFetchError("upstream unavailable")
        return documents[url]

    result = _adapter(fetch_text=fetch_text).run()

    assert result.no_active_event is False
    assert result.rejected == ("kml:NewstWaterWarm.kml",)
    assert [rejection.reason_code for rejection in result.source_rejections] == [
        "wra_flood_warning_child_read_failed"
    ]
    assert "unavailable" not in " ".join(result.rejected)


def test_one_failed_wrapper_never_discards_another_successful_source() -> None:
    wrapper = _fixture("wra_flood_warning_wrapper.kml").replace(
        "    </NetworkLink>",
        (
            "    </NetworkLink>\n"
            "    <NetworkLink>\n"
            "      <Link>\n"
            f"        <href>{RESERVOIR_URL}</href>\n"
            "      </Link>\n"
            "    </NetworkLink>"
        ),
        1,
    )

    def fetch_text(url: str, timeout_seconds: int) -> str:
        if url == WATER_URL:
            return _fixture("wra_flood_warning_synthetic_active.kml")
        if url == ANNOUNCE_URL:
            return wrapper
        raise WraFloodWarningFetchError("upstream unavailable")

    result = _adapter(
        fetch_text=fetch_text,
        index_payload=[
            {"fileex": "kml", "sourceurl": WATER_URL},
            {"fileex": "kml", "sourceurl": ANNOUNCE_URL},
        ],
    ).run()

    assert result.no_active_event is False
    assert [item.source_id for item in result.fetched] == [
        "NewstWaterWarm.kml:FW-1",
        "NewstWaterWarm.kml:FW-2",
    ]
    assert sorted(result.rejected) == [
        "NewstWaterWarm.kml:FW-3",
        "kml:NewstFloodWarm.kml",
        "kml:NewstReservoirWarm.kml",
    ]


# ------------------------------------------------------- context normalization


def _active_result():
    documents = _empty_map()
    documents[FLOOD_URL] = _fixture("wra_flood_warning_synthetic_active.kml")

    def fetch_text(url: str, timeout_seconds: int) -> str:
        return documents[url]

    return _adapter(fetch_text=fetch_text).run()


def test_synthetic_active_placemark_produces_pinned_context_payload() -> None:
    result = _active_result()

    raw = next(item for item in result.fetched if item.source_id.endswith("FW-1"))
    evidence = next(
        item for item in result.normalized if item.source_id == raw.source_id
    )

    assert evidence.event_type is EventType.STATUS_ONLY
    assert raw.payload["evidence_scope"] == "context"
    assert raw.payload["context_kind"] == "official_wra_warning_context"
    assert raw.payload["verification_status"] == "official_reported"
    assert raw.payload["incident_state"] == "active"
    assert raw.payload["location_precision"] in {"point", "polygon"}
    assert raw.payload["location_precision"] == "point"
    assert raw.payload["warning_kind"] == "flood_warning"
    assert raw.payload["source_filename"] == "NewstFloodWarm.kml"
    assert raw.payload["geometry"] == {
        "type": "Point",
        "coordinates": [120.1842, 23.0478],
    }
    assert raw.payload["source_timestamp"] == "2026-08-26T02:15:00+00:00"
    assert evidence.source_timestamp == datetime(2026, 8, 26, 2, 15, tzinfo=UTC)
    assert raw.payload["network_link_source_url"] is None


def test_expired_active_window_is_retained_as_resolved_context() -> None:
    result = _active_result()

    raw = next(item for item in result.fetched if item.source_id.endswith("FW-2"))

    assert raw.payload["incident_state"] == "resolved"
    assert raw.payload["location_precision"] == "polygon"
    assert raw.payload["active_from"] == "2026-08-26T01:00:00+00:00"
    assert raw.payload["active_until"] == "2026-08-26T01:30:00+00:00"


def test_placemark_without_source_time_is_rejected_and_never_uses_fetch_time() -> None:
    result = _active_result()

    assert "NewstFloodWarm.kml:FW-3" in result.rejected
    assert all(
        item.payload.get("source_timestamp") != FETCHED_AT.isoformat()
        for item in result.fetched
    )
    assert all(not item.source_id.endswith("FW-3") for item in result.fetched)
    assert [
        rejection.reason_code
        for rejection in result.source_rejections
        if rejection.source_id == "NewstFloodWarm.kml:FW-3"
    ] == ["wra_flood_warning_missing_source_time"]


def test_context_evidence_never_targets_official_realtime_latest() -> None:
    from app.pipelines import promotion

    source = Path(promotion.__file__).read_text(encoding="utf-8")

    assert "official.wra.flood_warning" not in source
    assert _active_result().normalized[0].event_type is EventType.STATUS_ONLY


# -------------------------------------------------------------- NetworkLink


def test_one_level_allowlisted_network_link_is_followed_once() -> None:
    requested: list[str] = []
    documents = _empty_map()
    documents[ANNOUNCE_URL] = _fixture("wra_flood_warning_wrapper.kml")
    documents[FLOOD_URL] = _fixture("wra_flood_warning_synthetic_active.kml")

    def fetch_text(url: str, timeout_seconds: int) -> str:
        requested.append(url)
        return documents[url]

    result = _adapter(
        fetch_text=fetch_text,
        index_payload=[{"fileex": "kml", "sourceurl": ANNOUNCE_URL}],
    ).run()

    assert requested == [ANNOUNCE_URL, FLOOD_URL]
    raw = next(item for item in result.fetched if item.source_id.endswith("FW-1"))
    assert raw.payload["network_link_source_url"] == ANNOUNCE_URL
    assert raw.payload["source_filename"] == "NewstFloodWarm.kml"


def test_network_link_targets_are_deduplicated_against_direct_reads() -> None:
    requested: list[str] = []
    documents = _empty_map()
    documents[ANNOUNCE_URL] = _fixture("wra_flood_warning_wrapper.kml")
    documents[FLOOD_URL] = _fixture("wra_flood_warning_synthetic_active.kml")

    def fetch_text(url: str, timeout_seconds: int) -> str:
        requested.append(url)
        return documents[url]

    result = _adapter(fetch_text=fetch_text).run()

    assert requested.count(FLOOD_URL) == 1
    source_ids = [item.source_id for item in result.fetched]
    assert len(source_ids) == len(set(source_ids))


def test_nested_network_link_in_a_fetched_child_is_rejected() -> None:
    documents = _empty_map()
    documents[ANNOUNCE_URL] = _fixture("wra_flood_warning_wrapper.kml")
    documents[FLOOD_URL] = _fixture("wra_flood_warning_wrapper.kml")

    def fetch_text(url: str, timeout_seconds: int) -> str:
        return documents[url]

    with pytest.raises(WraFloodWarningFetchError):
        _adapter(
            fetch_text=fetch_text,
            index_payload=[{"fileex": "kml", "sourceurl": ANNOUNCE_URL}],
        ).run()


def test_unlisted_network_link_href_is_rejected() -> None:
    wrapper = _fixture("wra_flood_warning_wrapper.kml").replace(
        FLOOD_URL,
        "https://fhy.wra.gov.tw/pub_web_2011/kml/KmlShare/OtherWarm.kml",
    )
    documents = _empty_map()
    documents[ANNOUNCE_URL] = wrapper

    def fetch_text(url: str, timeout_seconds: int) -> str:
        return documents[url]

    with pytest.raises(WraFloodWarningFetchError):
        _adapter(
            fetch_text=fetch_text,
            index_payload=[{"fileex": "kml", "sourceurl": ANNOUNCE_URL}],
        ).run()


# ------------------------------------------------------------- parser bounds


def _single_document_adapter(document: str) -> WraFloodWarningAdapter:
    documents = _empty_map()
    documents[FLOOD_URL] = document

    def fetch_text(url: str, timeout_seconds: int) -> str:
        return documents[url]

    return _adapter(
        fetch_text=fetch_text,
        index_payload=[{"fileex": "kml", "sourceurl": FLOOD_URL}],
    )


def _kml(body: str) -> str:
    return (
        '<?xml version="1.0"?>'
        f'<kml xmlns="http://www.opengis.net/kml/2.2">{body}</kml>'
    )


def test_dtd_and_entity_documents_are_rejected() -> None:
    benign = _kml("<Document><name>ok</name></Document>")
    assert parse_wra_flood_warning_kml(benign) is not None

    hostile = (
        '<?xml version="1.0"?>'
        '<!DOCTYPE kml [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
        '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
        "<name>&xxe;</name></Document></kml>"
    )
    with pytest.raises(WraFloodWarningPayloadError):
        parse_wra_flood_warning_kml(hostile)
    with pytest.raises(WraFloodWarningFetchError):
        _single_document_adapter(hostile).run()


def test_non_kml_22_root_is_rejected() -> None:
    with pytest.raises(WraFloodWarningPayloadError):
        parse_wra_flood_warning_kml(
            '<?xml version="1.0"?><kml xmlns="http://earth.google.com/kml/2.1"/>'
        )


def test_response_over_two_mebibytes_is_rejected() -> None:
    assert MAX_WRA_FLOOD_WARNING_KML_BYTES == 2 * 1024 * 1024

    def document(name_length: int) -> str:
        return _kml(f"<Document><name>{'x' * name_length}</name></Document>")

    envelope = len(document(0).encode("utf-8"))
    at_limit = document(MAX_WRA_FLOOD_WARNING_KML_BYTES - envelope)
    assert len(at_limit.encode("utf-8")) == MAX_WRA_FLOOD_WARNING_KML_BYTES
    assert parse_wra_flood_warning_kml(at_limit) is not None

    over_limit = document(MAX_WRA_FLOOD_WARNING_KML_BYTES - envelope + 1)
    with pytest.raises(WraFloodWarningPayloadError):
        parse_wra_flood_warning_kml(over_limit)
    with pytest.raises(WraFloodWarningFetchError):
        _single_document_adapter(over_limit).run()


def test_depth_over_thirty_two_is_rejected() -> None:
    assert MAX_WRA_FLOOD_WARNING_XML_DEPTH == 32

    def nested(folders: int) -> str:
        return _kml("<Folder>" * folders + "</Folder>" * folders)

    at_limit = nested(MAX_WRA_FLOOD_WARNING_XML_DEPTH - 1)
    assert parse_wra_flood_warning_kml(at_limit) is not None

    over_limit = nested(MAX_WRA_FLOOD_WARNING_XML_DEPTH)
    with pytest.raises(WraFloodWarningPayloadError):
        parse_wra_flood_warning_kml(over_limit)
    with pytest.raises(WraFloodWarningFetchError):
        _single_document_adapter(over_limit).run()


def test_element_count_over_the_limit_is_rejected() -> None:
    assert MAX_WRA_FLOOD_WARNING_XML_ELEMENTS == 20_000

    def document(folders: int) -> str:
        return _kml(f"<Document>{'<Folder/>' * folders}</Document>")

    at_limit = document(MAX_WRA_FLOOD_WARNING_XML_ELEMENTS - 2)
    assert parse_wra_flood_warning_kml(at_limit) is not None

    over_limit = document(MAX_WRA_FLOOD_WARNING_XML_ELEMENTS - 1)
    with pytest.raises(WraFloodWarningPayloadError):
        parse_wra_flood_warning_kml(over_limit)
    with pytest.raises(WraFloodWarningFetchError):
        _single_document_adapter(over_limit).run()


def test_placemark_count_over_the_limit_is_rejected() -> None:
    assert MAX_WRA_FLOOD_WARNING_PLACEMARKS == 2_000

    def document(placemarks: int) -> str:
        return _kml(f"<Document>{'<Placemark/>' * placemarks}</Document>")

    at_limit = document(MAX_WRA_FLOOD_WARNING_PLACEMARKS)
    assert parse_wra_flood_warning_kml(at_limit) is not None

    over_limit = document(MAX_WRA_FLOOD_WARNING_PLACEMARKS + 1)
    with pytest.raises(WraFloodWarningPayloadError):
        parse_wra_flood_warning_kml(over_limit)
    with pytest.raises(WraFloodWarningFetchError):
        _single_document_adapter(over_limit).run()


def test_total_coordinate_count_over_the_limit_is_rejected() -> None:
    assert MAX_WRA_FLOOD_WARNING_TOTAL_COORDINATES == 100_000

    def document(tokens: int) -> str:
        coordinates = " ".join(["120.10,23.00,0"] * tokens)
        return _kml(
            "<Document><Placemark>"
            f"<Point><coordinates>{coordinates}</coordinates></Point>"
            "</Placemark></Document>"
        )

    at_limit = document(MAX_WRA_FLOOD_WARNING_TOTAL_COORDINATES)
    assert parse_wra_flood_warning_kml(at_limit) is not None

    over_limit = document(MAX_WRA_FLOOD_WARNING_TOTAL_COORDINATES + 1)
    with pytest.raises(WraFloodWarningPayloadError):
        parse_wra_flood_warning_kml(over_limit)
    with pytest.raises(WraFloodWarningFetchError):
        _single_document_adapter(over_limit).run()


# ----------------------------------------------------------------- 429 audit


def test_rate_limit_is_not_retried_and_exposes_only_a_bounded_cooldown() -> None:
    calls: list[str] = []

    def fetch_text(url: str, timeout_seconds: int) -> str:
        calls.append(url)
        raise WraFloodWarningRateLimitError(
            "rate limited",
            retry_after_seconds=99_999,
        )

    with pytest.raises(WraFloodWarningFetchError) as excinfo:
        _adapter(fetch_text=fetch_text).run()

    assert calls == list(WRA_FLOOD_WARNING_KML_URLS)
    assert isinstance(excinfo.value, WraFloodWarningRateLimitError)
    assert excinfo.value.retry_after_seconds == 3600


# -------------------------------------------------------------- adapter meta


def test_metadata_is_context_only_and_disabled_by_default() -> None:
    assert WRA_FLOOD_WARNING_METADATA.key == "official.wra.flood_warning"
    assert WRA_FLOOD_WARNING_METADATA.enabled_by_default is False
    assert WRA_FLOOD_WARNING_METADATA.data_gov_dataset_id == "5982"
    assert WRA_FLOOD_WARNING_METADATA.resource_url == WRA_FLOOD_WARNING_INDEX_URL
    assert any(
        "active_fixture_reviewed=false" in limitation
        for limitation in WRA_FLOOD_WARNING_METADATA.limitations
    )
