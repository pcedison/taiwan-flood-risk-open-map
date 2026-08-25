from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.message import Message
from pathlib import Path
from typing import Self
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

import pytest

from app.adapters.cap_xml import MAX_CAP_BYTES, CapDocumentError, parse_cap_document
from app.adapters.cwa.heavy_rain_warning import (
    CWA_HEAVY_RAIN_CAP_URL,
    CwaHeavyRainWarningAdapter,
    CwaHeavyRainWarningConfigurationError,
    CwaHeavyRainWarningFetchError,
    CwaHeavyRainWarningRateLimitError,
    unresolved_cap_area_source_id,
)
from app.pipelines.staging import build_staging_batch

FIXTURES_DIR = Path(__file__).parent / "fixtures"
FETCHED_AT = datetime(2026, 8, 26, 2, 0, tzinfo=UTC)
SAFE_AUTHORIZATION = "fixture-authorization-value"


def _fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def _adapter_for_fixture(
    name: str,
    *,
    fetched_at: datetime = FETCHED_AT,
) -> CwaHeavyRainWarningAdapter:
    return CwaHeavyRainWarningAdapter(
        authorization=SAFE_AUTHORIZATION,
        fetched_at=fetched_at,
        fetch_cap=lambda _url, _authorization, _timeout: _fixture(name),
        raw_snapshot_key="raw/cwa/heavy-rain/fixture.xml",
    )


def _alert_xml(
    *,
    identifier: str = "fixture-message",
    status: str = "Actual",
    message_type: str = "Alert",
    scope: str = "Public",
    sent: str = "2026-08-26T08:00:00+08:00",
    effective: str | None = "2026-08-26T08:00:00+08:00",
    onset: str | None = None,
    expires: str = "2026-08-26T14:00:00+08:00",
    references: str = "",
    areas: str = "<area><areaDesc>安南區</areaDesc></area>",
) -> str:
    effective_xml = f"<effective>{effective}</effective>" if effective is not None else ""
    onset_xml = f"<onset>{onset}</onset>" if onset is not None else ""
    return f"""<?xml version="1.0"?>
<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">
  <identifier>{identifier}</identifier><sender>public-warning@cwa.gov.tw</sender>
  <sent>{sent}</sent><status>{status}</status><msgType>{message_type}</msgType>
  <scope>{scope}</scope>{references}
  <info><event>大雨特報</event><headline>合成測試警報</headline>
    {effective_xml}{onset_xml}<expires>{expires}</expires>{areas}
  </info>
</alert>"""


def _adapter_for_xml(xml: str, *, fetched_at: datetime = FETCHED_AT) -> CwaHeavyRainWarningAdapter:
    return CwaHeavyRainWarningAdapter(
        authorization=SAFE_AUTHORIZATION,
        fetched_at=fetched_at,
        fetch_cap=lambda _url, _authorization, _timeout: xml,
    )


def test_cwa_town_warning_is_raw_audited_but_not_staged() -> None:
    result = _adapter_for_fixture("cwa_heavy_rain_warning_cap.xml").run()

    assert len(result.fetched) == 2
    assert result.normalized == ()
    assert result.rejected == tuple(item.source_id for item in result.fetched)
    assert {item.reason_code for item in result.source_rejections} == {
        "cwa_unreviewed_admin_geometry"
    }

    batch = build_staging_batch(result, ingestion_generation_started_at=FETCHED_AT)
    assert batch.accepted == ()
    assert batch.rejected == ()
    assert "geometry" not in result.fetched[0].payload
    assert "latest_point_geometry" not in result.fetched[0].payload
    assert "parent_county_geometry" not in result.fetched[0].payload
    assert "parent_county_code" not in result.fetched[0].payload


def test_parser_preserves_structured_cap_source_semantics_without_centroid() -> None:
    (message,) = parse_cap_document(_fixture("cwa_heavy_rain_warning_cap.xml"))

    assert message.status == "Actual"
    assert message.scope == "Public"
    assert message.message_type == "Alert"
    assert message.onset == datetime(2026, 8, 26, 0, 30, tzinfo=UTC)
    assert message.areas[0].geocodes == (("TownshipCode", "6703500"),)
    assert message.areas[0].polygon == (
        (23.1, 120.1),
        (23.2, 120.1),
        (23.2, 120.2),
        (23.1, 120.1),
    )
    assert message.areas[0].circle is None
    assert message.areas[1].circle == (23.04, 120.48, 8.0)
    assert not hasattr(message.areas[0], "geometry")
    assert not hasattr(message.areas[0], "centroid")


def test_raw_payload_uses_exact_lifecycle_fields_and_secret_free_source_url() -> None:
    result = _adapter_for_fixture("cwa_heavy_rain_warning_cap.xml").run()
    first = result.fetched[0]

    assert first.source_url == CWA_HEAVY_RAIN_CAP_URL
    assert SAFE_AUTHORIZATION not in first.source_url
    assert first.raw_snapshot_key == "raw/cwa/heavy-rain/fixture.xml"
    assert first.payload == {
        "evidence_scope": "current",
        "location_precision": "admin_area",
        "cap_sender": "public-warning@cwa.gov.tw",
        "cap_identifier": "CWA-HR-20260826-001",
        "cap_sent": "2026-08-26T00:00:00+00:00",
        "cap_references": [],
        "cap_status": "Actual",
        "cap_message_type": "Alert",
        "active_from": "2026-08-26T00:30:00+00:00",
        "active_until": "2026-08-26T06:00:00+00:00",
        "areaDesc": "安南區",
        "source_geocodes": [{"valueName": "TownshipCode", "value": "6703500"}],
    }


def test_multi_area_unresolved_identity_is_deterministic_and_distinct() -> None:
    adapter = _adapter_for_fixture("cwa_heavy_rain_warning_cap.xml")
    first = adapter.run()
    second = adapter.run()
    parsed = parse_cap_document(_fixture("cwa_heavy_rain_warning_cap.xml"))[0]

    assert tuple(item.source_id for item in first.fetched) == tuple(
        item.source_id for item in second.fetched
    )
    assert len({item.source_id for item in first.fetched}) == 2
    assert first.fetched[0].source_id == unresolved_cap_area_source_id(
        parsed, parsed.areas[0]
    )
    assert all(SAFE_AUTHORIZATION not in item.source_id for item in first.fetched)


def test_area_less_message_is_message_level_raw_audit() -> None:
    result = _adapter_for_xml(_alert_xml(areas="")).run()

    assert len(result.fetched) == 1
    assert result.fetched[0].source_id.endswith(":message")
    assert result.fetched[0].payload["areaDesc"] is None
    assert result.fetched[0].payload["source_geocodes"] == []
    assert result.source_rejections[0].reason_code == "cwa_unreviewed_message_geometry"


def test_valid_empty_collection_is_the_only_no_active_event_success() -> None:
    result = _adapter_for_fixture("cwa_heavy_rain_warning_empty.xml").run()

    assert result.fetched == ()
    assert result.normalized == ()
    assert result.rejected == ()
    assert result.source_rejections == ()
    assert result.no_active_event is True


def test_well_formed_non_cap_xml_is_schema_failure_not_empty() -> None:
    for document in (
        "<unrelated />",
        "<alerts />",
        "<alert xmlns='https://example.test/not-cap'><identifier>x</identifier></alert>",
    ):
        with pytest.raises(CapDocumentError, match="CAP"):
            _adapter_for_xml(document).run()


def test_cap_fields_must_use_the_cap_12_namespace() -> None:
    wrong_child_namespace = _alert_xml().replace(
        "<identifier>",
        "<identifier xmlns='https://example.test/not-cap'>",
        1,
    )

    with pytest.raises(CapDocumentError, match="identifier"):
        _adapter_for_xml(wrong_child_namespace).run()


@pytest.mark.parametrize(
    ("status", "scope", "message_type", "reason_code"),
    (
        ("Test", "Public", "Alert", "cwa_inactive_status"),
        ("Actual", "Restricted", "Alert", "cwa_inactive_scope"),
        ("Actual", "Public", "Cancel", "cwa_inactive_cancel"),
    ),
)
def test_non_actual_non_public_and_cancel_messages_are_raw_audited(
    status: str,
    scope: str,
    message_type: str,
    reason_code: str,
) -> None:
    references = (
        "<references>public-warning@cwa.gov.tw,CWA-HR-PRIOR,"
        "2026-08-25T22:00:00+08:00</references>"
        if message_type == "Cancel"
        else ""
    )
    result = _adapter_for_xml(
        _alert_xml(
            status=status,
            scope=scope,
            message_type=message_type,
            references=references,
        )
    ).run()

    assert len(result.fetched) == 1
    assert result.normalized == ()
    assert result.source_rejections[0].reason_code == reason_code
    assert result.no_active_event is False


def test_update_preserves_structured_reference_triples_and_remains_geometry_audited() -> None:
    references = (
        "<references>public-warning@cwa.gov.tw,CWA-HR-PRIOR," 
        "2026-08-25T22:00:00+08:00</references>"
    )
    result = _adapter_for_xml(
        _alert_xml(message_type="Update", references=references)
    ).run()

    assert result.fetched[0].payload["cap_references"] == [
        {
            "sender": "public-warning@cwa.gov.tw",
            "identifier": "CWA-HR-PRIOR",
            "sent": "2026-08-25T14:00:00+00:00",
        }
    ]
    assert result.source_rejections[0].reason_code == "cwa_unreviewed_admin_geometry"


@pytest.mark.parametrize(
    ("effective", "onset", "expires", "reason_code"),
    (
        ("2026-08-26T10:30:00+08:00", None, "2026-08-26T14:00:00+08:00", "cwa_inactive_future"),
        ("2026-08-25T08:00:00+08:00", None, "2026-08-26T09:00:00+08:00", "cwa_inactive_expired"),
    ),
)
def test_future_and_expired_messages_are_raw_audited(
    effective: str,
    onset: str | None,
    expires: str,
    reason_code: str,
) -> None:
    result = _adapter_for_xml(
        _alert_xml(effective=effective, onset=onset, expires=expires)
    ).run()

    assert result.source_rejections[0].reason_code == reason_code
    assert result.no_active_event is False


def test_invalid_lifecycle_values_and_windows_are_schema_failures_not_empty() -> None:
    invalid_documents = (
        _alert_xml(message_type="Ack"),
        _alert_xml(effective=None),
        _alert_xml(expires="2026-08-26T07:00:00+08:00"),
        _alert_xml(
            message_type="Update",
            references="<references>not-a-reference-triple</references>",
        ),
    )

    for document in invalid_documents:
        with pytest.raises(CapDocumentError):
            _adapter_for_xml(document).run()


@pytest.mark.parametrize(
    "xml",
    (
        "<alerts><alert></alerts>",
        "<!DOCTYPE alert [<!ENTITY xxe SYSTEM 'file:///nonexistent'>]><alert>&xxe;</alert>",
    ),
)
def test_malformed_and_entity_xml_are_rejected(xml: str) -> None:
    with pytest.raises(CapDocumentError):
        parse_cap_document(xml)


def test_oversize_xml_is_rejected_before_parse() -> None:
    xml = "<alerts>" + (" " * (2 * 1024 * 1024)) + "</alerts>"

    with pytest.raises(CapDocumentError, match="2 MiB"):
        parse_cap_document(xml)


def test_deep_xml_is_rejected() -> None:
    xml = "<alerts>" + ("<x>" * 32) + ("</x>" * 32) + "</alerts>"

    with pytest.raises(CapDocumentError, match="depth"):
        parse_cap_document(xml)


def test_element_message_area_reference_and_polygon_limits_are_enforced() -> None:
    too_many_elements = "<alerts>" + ("<x/>" * 20_000) + "</alerts>"
    too_many_messages = "<alerts>" + ("<alert/>" * 257) + "</alerts>"
    too_many_areas = _alert_xml(areas="<area><areaDesc>x</areaDesc></area>" * 129)
    refs = " ".join(
        f"s{i},i{i},2026-08-25T22:00:00+08:00" for i in range(65)
    )
    too_many_references = _alert_xml(
        message_type="Update", references=f"<references>{refs}</references>"
    )
    coordinates = " ".join(f"23.{i % 10},120.{i % 10}" for i in range(4097))
    too_many_coordinates = _alert_xml(
        areas=f"<area><areaDesc>x</areaDesc><polygon>{coordinates}</polygon></area>"
    )

    for xml in (
        too_many_elements,
        too_many_messages,
        too_many_areas,
        too_many_references,
        too_many_coordinates,
    ):
        with pytest.raises(CapDocumentError):
            parse_cap_document(xml)


def test_nested_alerts_cannot_evade_the_message_limit() -> None:
    nested = _alert_xml(areas="").replace(
        "</alert>",
        ("<alert/>" * 256) + "</alert>",
    )

    with pytest.raises(CapDocumentError, match="256 message"):
        parse_cap_document(nested)


def test_authorization_is_a_separate_fetch_argument_and_configured_query_is_stripped() -> None:
    calls: list[tuple[str, str, int]] = []

    def fetch_cap(url: str, authorization: str, timeout_seconds: int) -> str:
        calls.append((url, authorization, timeout_seconds))
        return _fixture("cwa_heavy_rain_warning_empty.xml")

    adapter = CwaHeavyRainWarningAdapter(
        authorization=SAFE_AUTHORIZATION,
        cap_url=(
            "https://example.test/cap?Authorization=discard-me&format=XML&channel=warning"
        ),
        timeout_seconds=7,
        fetched_at=FETCHED_AT,
        fetch_cap=fetch_cap,
    )

    assert adapter.run().no_active_event is True
    assert calls == [
        ("https://example.test/cap?format=CAP&channel=warning", SAFE_AUTHORIZATION, 7)
    ]


def test_missing_authorization_fails_before_transport_and_is_not_empty() -> None:
    calls = 0

    def fetch_cap(url: str, authorization: str, timeout_seconds: int) -> str:
        nonlocal calls
        del url, authorization, timeout_seconds
        calls += 1
        return _fixture("cwa_heavy_rain_warning_empty.xml")

    adapter = CwaHeavyRainWarningAdapter(
        authorization=" ",
        fetched_at=FETCHED_AT,
        fetch_cap=fetch_cap,
    )

    with pytest.raises(CwaHeavyRainWarningConfigurationError):
        adapter.run()
    assert calls == 0


def test_actual_request_inserts_authorization_once_and_redaction_never_leaks_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.adapters.cwa.heavy_rain_warning as module

    attempts: list[str] = []

    def failing_urlopen(request: object, *, timeout: int) -> object:
        del timeout
        request_url = request.full_url  # type: ignore[attr-defined]
        attempts.append(request_url)
        raise OSError(f"upstream echoed {request_url} and {SAFE_AUTHORIZATION}")

    monkeypatch.setattr(module, "urlopen", failing_urlopen)
    adapter = CwaHeavyRainWarningAdapter(
        authorization=SAFE_AUTHORIZATION,
        cap_url="https://example.test/cap?Authorization=discard-me",
        fetched_at=FETCHED_AT,
    )

    with pytest.raises(CwaHeavyRainWarningFetchError) as exc_info:
        adapter.run()

    request_params = parse_qs(urlparse(attempts[0]).query)
    assert request_params["Authorization"] == [SAFE_AUTHORIZATION]
    assert len(request_params["Authorization"]) == 1
    rendered = str(exc_info.value)
    assert SAFE_AUTHORIZATION not in rendered
    assert "discard-me" not in rendered
    assert "Authorization=REDACTED" in rendered
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None
    assert len(attempts) == 1


def test_transport_caps_response_read_before_parser_allocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.adapters.cwa.heavy_rain_warning as module

    read_limits: list[int] = []

    class OversizeResponse:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def read(self, limit: int = -1) -> bytes:
            read_limits.append(limit)
            return b"x" * (MAX_CAP_BYTES + 1 if limit < 0 else limit)

    monkeypatch.setattr(module, "urlopen", lambda _request, *, timeout: OversizeResponse())
    adapter = CwaHeavyRainWarningAdapter(
        authorization=SAFE_AUTHORIZATION,
        cap_url="https://example.test/cap",
        fetched_at=FETCHED_AT,
    )

    with pytest.raises(CwaHeavyRainWarningFetchError, match="2 MiB") as exc_info:
        adapter.run()

    assert read_limits == [MAX_CAP_BYTES + 1]
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None


def test_decode_failure_does_not_retain_secret_bearing_response_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.adapters.cwa.heavy_rain_warning as module

    class InvalidResponse:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def read(self, limit: int = -1) -> bytes:
            del limit
            return b"\xffAuthorization=" + SAFE_AUTHORIZATION.encode("utf-8")

    monkeypatch.setattr(module, "urlopen", lambda _request, *, timeout: InvalidResponse())
    adapter = CwaHeavyRainWarningAdapter(
        authorization=SAFE_AUTHORIZATION,
        cap_url="https://example.test/cap",
        fetched_at=FETCHED_AT,
    )

    with pytest.raises(CwaHeavyRainWarningFetchError) as exc_info:
        adapter.run()

    assert SAFE_AUTHORIZATION not in str(exc_info.value)
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None


def test_parser_failure_severs_secret_bearing_entity_exception_state() -> None:
    secret_xml = (
        "<!DOCTYPE alert [<!ENTITY leaked SYSTEM "
        f"'https://example.test/cap?Authorization={SAFE_AUTHORIZATION}'>]>"
        "<alert xmlns='urn:oasis:names:tc:emergency:cap:1.2'>&leaked;</alert>"
    )
    adapter = _adapter_for_xml(secret_xml)

    with pytest.raises(CapDocumentError) as exc_info:
        adapter.run()

    assert SAFE_AUTHORIZATION not in str(exc_info.value)
    assert SAFE_AUTHORIZATION not in repr(vars(exc_info.value))
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None


@pytest.mark.parametrize(
    ("retry_after", "expected"),
    (
        ("7200", 3600),
        ("Wed, 26 Aug 2026 02:02:00 GMT", 120),
        ("invalid", None),
    ),
)
def test_429_is_attempted_once_and_records_bounded_retry_after(
    monkeypatch: pytest.MonkeyPatch,
    retry_after: str,
    expected: int | None,
) -> None:
    import app.adapters.cwa.heavy_rain_warning as module

    attempts = 0
    headers = Message()
    headers["Retry-After"] = retry_after

    def limited_urlopen(request: object, *, timeout: int) -> object:
        nonlocal attempts
        del timeout
        attempts += 1
        raise HTTPError(request.full_url, 429, "Too Many Requests", headers, fp=None)  # type: ignore[attr-defined]

    monkeypatch.setattr(module, "urlopen", limited_urlopen)
    adapter = CwaHeavyRainWarningAdapter(
        authorization=SAFE_AUTHORIZATION,
        cap_url="https://example.test/cap",
        fetched_at=FETCHED_AT,
    )

    with pytest.raises(CwaHeavyRainWarningRateLimitError) as exc_info:
        adapter.run()

    assert attempts == 1
    assert exc_info.value.retry_after_seconds == expected
    assert SAFE_AUTHORIZATION not in str(exc_info.value)
    assert "Authorization=REDACTED" in str(exc_info.value)
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None


def test_injected_fetcher_failure_is_redacted_and_not_converted_to_empty() -> None:
    secret = SAFE_AUTHORIZATION

    def fail(url: str, authorization: str, timeout_seconds: int) -> str:
        del timeout_seconds
        raise RuntimeError(f"failed {url}?Authorization={authorization} secret={authorization}")

    adapter = CwaHeavyRainWarningAdapter(
        authorization=secret,
        cap_url="https://example.test/cap?Authorization=discard-me",
        fetched_at=FETCHED_AT + timedelta(minutes=1),
        fetch_cap=fail,
    )

    with pytest.raises(CwaHeavyRainWarningFetchError) as exc_info:
        adapter.run()

    assert secret not in str(exc_info.value)
    assert "discard-me" not in str(exc_info.value)
    assert "REDACTED" in str(exc_info.value)
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None
