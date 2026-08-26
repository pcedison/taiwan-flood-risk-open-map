from __future__ import annotations

from collections import UserList
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from email.message import Message
from pathlib import Path
from typing import Any, Self, cast
from urllib.error import HTTPError
from urllib.parse import parse_qs, quote, quote_plus, urlparse

import pytest

from app.adapters.cap_xml import (
    MAX_CAP_BYTES,
    CapDocumentError,
    ParsedCapMessage,
    parse_cap_document,
)
from app.adapters.contracts import RawSourceItem
from app.adapters.cwa import heavy_rain_warning as cwa_cap_module
from app.adapters.cwa.heavy_rain_warning import (
    CWA_HEAVY_RAIN_CAP_URL,
    CwaHeavyRainWarningAdapter,
    CwaHeavyRainWarningConfigurationError,
    CwaHeavyRainWarningFetchError,
    CwaHeavyRainWarningRateLimitError,
    unresolved_cap_area_source_id,
)
from app.jobs.ingestion import run_adapter_batch
from app.pipelines.staging import build_staging_batch

FIXTURES_DIR = Path(__file__).parent / "fixtures"
FETCHED_AT = datetime(2026, 8, 26, 2, 0, tzinfo=UTC)
SAFE_AUTHORIZATION = "fixture-authorization-value"


def _assert_secret_free_exception(exc: BaseException, *, secret: str) -> None:
    rendered = (str(exc), repr(exc), repr(vars(exc)))
    for reflected in {secret, quote(secret, safe=""), quote_plus(secret)}:
        assert all(reflected not in value for value in rendered)
    assert "?" not in str(exc)
    assert exc.__cause__ is None
    assert exc.__context__ is None


def _entity_encoded_secret_cap(field_name: str, reference: str) -> str:
    encoded_secret = f"fixture-auth{reference}marker"
    sender = encoded_secret if field_name == "sender" else "public-warning@cwa.gov.tw"
    identifier = encoded_secret if field_name == "identifier" else "CWA-ENTITY-001"
    reference_sender = (
        encoded_secret if field_name == "reference_sender" else "prior@cwa.gov.tw"
    )
    reference_identifier = (
        encoded_secret if field_name == "reference_identifier" else "CWA-PRIOR-001"
    )
    event = encoded_secret if field_name == "event" else "Synthetic heavy-rain audit"
    headline = encoded_secret if field_name == "headline" else "Synthetic headline"
    description = (
        encoded_secret if field_name == "description" else "Synthetic description"
    )
    scope = encoded_secret if field_name == "scope" else "Public"
    area_desc = encoded_secret if field_name == "area_desc" else "Synthetic district"
    geocode_name = encoded_secret if field_name == "geocode_name" else "TownshipCode"
    geocode_value = encoded_secret if field_name == "geocode_value" else "6703500"
    return f"""\
<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">
  <identifier>{identifier}</identifier>
  <sender>{sender}</sender>
  <sent>2026-08-26T08:00:00+08:00</sent>
  <status>Actual</status>
  <msgType>Update</msgType>
  <scope>{scope}</scope>
  <references>{reference_sender},{reference_identifier},2026-08-26T07:00:00+08:00</references>
  <info>
    <event>{event}</event>
    <headline>{headline}</headline>
    <description>{description}</description>
    <effective>2026-08-26T08:00:00+08:00</effective>
    <expires>2026-08-26T14:00:00+08:00</expires>
    <area>
      <areaDesc>{area_desc}</areaDesc>
      <geocode><valueName>{geocode_name}</valueName><value>{geocode_value}</value></geocode>
    </area>
  </info>
</alert>
"""


@dataclass(frozen=True)
class _FutureParsedCapMessage(ParsedCapMessage):
    future_metadata: object = None


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


def test_cap_collection_rejects_wrapper_unknown_child_and_nested_alert() -> None:
    alert = _alert_xml().split("\n", 1)[1]
    wrapped = (
        "<wrapper xmlns='urn:oasis:names:tc:emergency:cap:1.2'>"
        f"{alert}</wrapper>"
    )
    unknown_child = (
        "<alerts xmlns='urn:oasis:names:tc:emergency:cap:1.2'><unknown /></alerts>"
    )
    nested = _alert_xml().replace("</alert>", f"{alert}</alert>", 1)

    for document in (wrapped, unknown_child, nested):
        with pytest.raises(CapDocumentError):
            parse_cap_document(document)


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


@pytest.mark.parametrize(
    "cap_url",
    (
        "https://audit-user:fixture-userinfo-password@example.test/cap?trace=private",
        "https://audit%2Duser:fixture%2Duserinfo%2Dpassword@example.test/cap?trace=private",
        "https://[::1/cap?trace=private",
        "https://example.test:invalid/cap?trace=private",
    ),
)
def test_configured_url_authority_and_parse_failures_are_generic_and_clean(
    cap_url: str,
) -> None:
    with pytest.raises(CwaHeavyRainWarningConfigurationError) as raised:
        CwaHeavyRainWarningAdapter(
            authorization=SAFE_AUTHORIZATION,
            cap_url=cap_url,
        )

    rendered = str(raised.value)
    assert "fixture-userinfo-password" not in rendered
    assert "fixture%2Duserinfo%2Dpassword" not in rendered
    assert "audit-user" not in rendered
    assert "audit%2Duser" not in rendered
    assert "private" not in rendered
    assert "@" not in rendered
    _assert_secret_free_exception(raised.value, secret=SAFE_AUTHORIZATION)


@pytest.mark.parametrize(
    "sensitive_key",
    (
        "apikey",
        "api%5Fkey",
        "token",
        "access%5Ftoken",
        "password",
        "secret",
        "client%5Fsecret",
    ),
)
def test_configured_url_rejects_decoded_sensitive_query_keys(
    sensitive_key: str,
) -> None:
    with pytest.raises(CwaHeavyRainWarningConfigurationError) as raised:
        CwaHeavyRainWarningAdapter(
            authorization=SAFE_AUTHORIZATION,
            cap_url=f"https://example.test/cap?{sensitive_key}=fixture-private-query",
        )

    assert "fixture-private-query" not in str(raised.value)
    assert sensitive_key not in str(raised.value)
    _assert_secret_free_exception(raised.value, secret=SAFE_AUTHORIZATION)


@pytest.mark.parametrize("location", ("name", "value"))
def test_configured_url_rejects_encoded_exact_authorization_in_benign_query(
    location: str,
) -> None:
    secret = "fixture authorization+/value"
    encoded = quote_plus(secret)
    query = (
        f"trace-{encoded}=public"
        if location == "name"
        else f"trace=public-{encoded}-value"
    )

    with pytest.raises(CwaHeavyRainWarningConfigurationError) as raised:
        CwaHeavyRainWarningAdapter(
            authorization=secret,
            cap_url=f"https://example.test/cap?{query}",
        )

    _assert_secret_free_exception(raised.value, secret=secret)


def test_configured_url_is_fragment_free_and_canonical_for_fetch_and_raw() -> None:
    calls: list[tuple[str, str, int]] = []

    def fetch_cap(url: str, authorization: str, timeout_seconds: int) -> str:
        calls.append((url, authorization, timeout_seconds))
        return _alert_xml()

    result = CwaHeavyRainWarningAdapter(
        authorization=SAFE_AUTHORIZATION,
        cap_url=(
            "https://example.test/cap?channel=warning&FoRmAt=XML&format=json"
            "&AUTHORIZATION=discard-me#fixture-private-fragment"
        ),
        fetched_at=FETCHED_AT,
        fetch_cap=fetch_cap,
    ).run()

    expected_url = "https://example.test/cap?channel=warning&format=CAP"
    assert calls == [(expected_url, SAFE_AUTHORIZATION, 8)]
    assert result.fetched[0].source_url == expected_url
    assert "discard-me" not in result.fetched[0].source_url
    assert "fixture-private-fragment" not in result.fetched[0].source_url


def test_secret_bearing_raw_snapshot_key_fails_before_fetch_and_log_fields() -> None:
    secret = "fixture-snapshot-authorization"
    calls = 0

    def fetch_cap(_url: str, _authorization: str, _timeout: int) -> str:
        nonlocal calls
        calls += 1
        return _alert_xml()

    adapter = CwaHeavyRainWarningAdapter(
        authorization=secret,
        fetched_at=FETCHED_AT,
        fetch_cap=fetch_cap,
        raw_snapshot_key=f"raw/cwa/{secret}/fixture.xml",
    )

    summary = run_adapter_batch(adapter)

    assert calls == 0
    assert summary.status == "failed"
    assert summary.error_code == "CwaHeavyRainWarningConfigurationError"
    assert summary.raw_ref is None
    assert secret not in repr(vars(summary))
    assert secret not in repr(summary.log_fields())
    assert summary.error_message is not None
    assert "[REDACTED]" in summary.error_message
    assert "?" not in summary.error_message


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
    assert "[REDACTED]" in rendered
    assert "?" not in rendered
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None
    assert len(attempts) == 1


@pytest.mark.parametrize(
    "url",
    (
        "invalid://example.test/cap?trace=fixture-private-query",
        "https://example.test:invalid/cap?trace=fixture-private-query",
        "https://[::1/cap?trace=fixture-private-query",
    ),
)
def test_direct_builtin_transport_invalid_urls_are_generic_and_clean(
    monkeypatch: pytest.MonkeyPatch,
    url: str,
) -> None:
    secret = "fixture transport+/authorization"
    attempts = 0

    def fail_if_called(*_args: object, **_kwargs: object) -> object:
        nonlocal attempts
        attempts += 1
        raise RuntimeError(
            f"transport reflected {secret} {quote(secret, safe='')} {quote_plus(secret)}"
        )

    monkeypatch.setattr(cwa_cap_module, "urlopen", fail_if_called)

    with pytest.raises(CwaHeavyRainWarningFetchError) as raised:
        cwa_cap_module._fetch_cap(url, secret, 1, now=FETCHED_AT)

    assert attempts <= 1
    assert "fixture-private-query" not in str(raised.value)
    assert "[REDACTED]" in str(raised.value)
    _assert_secret_free_exception(raised.value, secret=secret)


def test_builtin_request_construction_failure_is_generic_and_clean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "fixture request+/authorization"

    def failing_request(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError(
            f"request reflected {secret} {quote(secret, safe='')} {quote_plus(secret)}"
        )

    monkeypatch.setattr(cwa_cap_module, "Request", failing_request)
    adapter = CwaHeavyRainWarningAdapter(
        authorization=secret,
        cap_url="https://example.test/cap?channel=fixture-private-query",
        fetched_at=FETCHED_AT,
    )

    with pytest.raises(CwaHeavyRainWarningFetchError) as raised:
        adapter.run()

    assert "fixture-private-query" not in str(raised.value)
    assert "[REDACTED]" in str(raised.value)
    _assert_secret_free_exception(raised.value, secret=secret)


@pytest.mark.parametrize("phase", ("enter", "read", "exit"))
def test_builtin_response_context_failures_are_generic_and_clean(
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    secret = "fixture response+/authorization"
    attempts = 0

    class HostileResponse:
        def __enter__(self) -> Self:
            if phase == "enter":
                raise RuntimeError(f"enter reflected {quote_plus(secret)}")
            return self

        def __exit__(self, *args: object) -> None:
            del args
            if phase == "exit":
                raise RuntimeError(f"exit reflected {quote(secret, safe='')}")

        def read(self, _limit: int = -1) -> bytes:
            if phase == "read":
                raise RuntimeError(f"read reflected {secret}")
            return _fixture("cwa_heavy_rain_warning_empty.xml").encode()

    def fake_urlopen(*_args: object, **_kwargs: object) -> HostileResponse:
        nonlocal attempts
        attempts += 1
        return HostileResponse()

    monkeypatch.setattr(cwa_cap_module, "urlopen", fake_urlopen)
    adapter = CwaHeavyRainWarningAdapter(
        authorization=secret,
        cap_url="https://example.test/cap?channel=fixture-private-query",
        fetched_at=FETCHED_AT,
    )

    with pytest.raises(CwaHeavyRainWarningFetchError) as raised:
        adapter.run()

    assert attempts == 1
    assert "fixture-private-query" not in str(raised.value)
    assert "[REDACTED]" in str(raised.value)
    _assert_secret_free_exception(raised.value, secret=secret)


def test_builtin_429_hostile_headers_are_contained_by_transport_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "fixture headers+/authorization"
    attempts = 0

    class HostileHeaders:
        def get(self, _name: str) -> str:
            raise RuntimeError(f"headers reflected {quote_plus(secret)}")

    def fake_urlopen(request: object, **_kwargs: object) -> object:
        nonlocal attempts
        attempts += 1
        raise HTTPError(
            request.full_url,  # type: ignore[attr-defined]
            429,
            f"rate limited {secret}",
            cast(Any, HostileHeaders()),
            None,
        )

    monkeypatch.setattr(cwa_cap_module, "urlopen", fake_urlopen)
    adapter = CwaHeavyRainWarningAdapter(
        authorization=secret,
        cap_url="https://example.test/cap?channel=fixture-private-query",
        fetched_at=FETCHED_AT,
    )

    with pytest.raises(CwaHeavyRainWarningFetchError) as raised:
        adapter.run()

    assert attempts == 1
    assert not isinstance(raised.value, CwaHeavyRainWarningRateLimitError)
    assert "fixture-private-query" not in str(raised.value)
    assert "[REDACTED]" in str(raised.value)
    _assert_secret_free_exception(raised.value, secret=secret)


def test_builtin_transport_rejects_non_bytes_without_inspecting_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "fixture body+/authorization"

    class HostileBody:
        def __len__(self) -> int:
            raise RuntimeError(f"body length reflected {secret}")

    class HostileResponse:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def read(self, _limit: int = -1) -> bytes:
            return cast(bytes, HostileBody())

    monkeypatch.setattr(
        cwa_cap_module,
        "urlopen",
        lambda *_args, **_kwargs: HostileResponse(),
    )
    adapter = CwaHeavyRainWarningAdapter(
        authorization=secret,
        cap_url="https://example.test/cap?channel=fixture-private-query",
        fetched_at=FETCHED_AT,
    )

    with pytest.raises(CwaHeavyRainWarningFetchError) as raised:
        adapter.run()

    assert "fixture-private-query" not in str(raised.value)
    assert "[REDACTED]" in str(raised.value)
    _assert_secret_free_exception(raised.value, secret=secret)


def test_builtin_transport_failure_batch_summary_is_secret_free(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "fixture batch+/authorization"

    def failing_request(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError(f"request reflected {quote_plus(secret)}")

    monkeypatch.setattr(cwa_cap_module, "Request", failing_request)
    adapter = CwaHeavyRainWarningAdapter(
        authorization=secret,
        cap_url="https://example.test/cap?channel=fixture-private-query",
        fetched_at=FETCHED_AT,
    )

    summary = run_adapter_batch(adapter)
    logged = capsys.readouterr().out

    assert summary.status == "failed"
    assert summary.items_fetched == 0
    assert summary.raw_ref is None
    assert summary.error_code == "CwaHeavyRainWarningFetchError"
    assert summary.error_message is not None
    assert "fixture-private-query" not in summary.error_message
    for reflected in {secret, quote(secret, safe=""), quote_plus(secret)}:
        assert reflected not in repr(vars(summary))
        assert reflected not in repr(summary.log_fields())
        assert reflected not in logged


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
        cap_url="https://example.test/cap?channel=fixture-private-query",
        fetched_at=FETCHED_AT,
    )

    with pytest.raises(CwaHeavyRainWarningFetchError, match="2 MiB") as exc_info:
        adapter.run()

    assert read_limits == [MAX_CAP_BYTES + 1]
    assert "fixture-private-query" not in str(exc_info.value)
    assert "[REDACTED]" in str(exc_info.value)
    assert "?" not in str(exc_info.value)
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
        cap_url="https://example.test/cap?channel=fixture-private-query",
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


def test_injected_cap_error_hostile_str_is_sanitized_without_context() -> None:
    secret = "fixture-parser-auth-marker"

    class HostileCapDocumentError(CapDocumentError):
        def __str__(self) -> str:
            raise RuntimeError(f"hostile parser reflected {secret}")

    def parse_cap(_xml: str) -> tuple[ParsedCapMessage, ...]:
        raise HostileCapDocumentError()

    adapter = CwaHeavyRainWarningAdapter(
        authorization=secret,
        fetched_at=FETCHED_AT,
        fetch_cap=lambda _url, _authorization, _timeout: _alert_xml(),
        parse_cap=parse_cap,
    )

    with pytest.raises(CapDocumentError) as raised:
        adapter.run()

    assert "[REDACTED]" in str(raised.value)
    _assert_secret_free_exception(raised.value, secret=secret)


@pytest.mark.parametrize(
    "field_name",
    (
        "sender",
        "identifier",
        "reference_sender",
        "reference_identifier",
        "event",
        "headline",
        "description",
        "scope",
        "area_desc",
        "geocode_name",
        "geocode_value",
    ),
)
@pytest.mark.parametrize("reference", ("&#45;", "&#x2d;"))
def test_entity_decoded_authorization_is_rejected_before_identity_or_raw_rows(
    monkeypatch: pytest.MonkeyPatch,
    field_name: str,
    reference: str,
) -> None:
    secret = "fixture-auth-marker"
    xml_text = _entity_encoded_secret_cap(field_name, reference)
    prepare_calls = 0
    original_prepare = cwa_cap_module._prepare_row

    def observing_prepare(*args: Any, **kwargs: Any) -> tuple[RawSourceItem, str]:
        nonlocal prepare_calls
        prepare_calls += 1
        return original_prepare(*args, **kwargs)

    monkeypatch.setattr(cwa_cap_module, "_prepare_row", observing_prepare)
    adapter = CwaHeavyRainWarningAdapter(
        authorization=secret,
        fetched_at=FETCHED_AT,
        fetch_cap=lambda _url, _authorization, _timeout: xml_text,
    )

    with pytest.raises(CapDocumentError) as raised:
        adapter.run()

    assert prepare_calls == 0
    assert "[REDACTED]" in str(raised.value)
    _assert_secret_free_exception(raised.value, secret=secret)


def test_entity_decoded_authorization_fails_batch_without_raw_or_log_reflection(
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "fixture-auth-marker"
    adapter = CwaHeavyRainWarningAdapter(
        authorization=secret,
        fetched_at=FETCHED_AT,
        raw_snapshot_key="raw/cwa/synthetic-safe.xml",
        fetch_cap=lambda _url, _authorization, _timeout: (
            _entity_encoded_secret_cap("description", "&#45;")
        ),
    )

    summary = run_adapter_batch(adapter)
    logged = capsys.readouterr().out

    assert summary.status == "failed"
    assert summary.items_fetched == 0
    assert summary.items_rejected == 0
    assert summary.raw_ref is None
    assert summary.error_code == "CapDocumentError"
    assert summary.error_message is not None
    assert "[REDACTED]" in summary.error_message
    assert secret not in repr(vars(summary))
    assert secret not in repr(summary.log_fields())
    assert secret not in logged


@pytest.mark.parametrize("geometry_field", ("polygon", "circle"))
def test_recursive_parsed_guard_checks_nested_polygon_and_circle_strings(
    geometry_field: str,
) -> None:
    secret = "fixture-auth-marker"
    parsed = parse_cap_document(_alert_xml())[0]
    poisoned_geometry: object = (
        ((cast(Any, secret), 120.1),)
        if geometry_field == "polygon"
        else (23.1, cast(Any, secret), 1.0)
    )
    poisoned_area = replace(
        parsed.areas[0],
        **{geometry_field: poisoned_geometry},
    )
    poisoned_message = replace(parsed, areas=(poisoned_area,))
    adapter = CwaHeavyRainWarningAdapter(
        authorization=secret,
        fetched_at=FETCHED_AT,
        fetch_cap=lambda _url, _authorization, _timeout: _alert_xml(),
        parse_cap=lambda _xml: (poisoned_message,),
    )

    with pytest.raises(CapDocumentError) as raised:
        adapter.run()

    assert "[REDACTED]" in str(raised.value)
    _assert_secret_free_exception(raised.value, secret=secret)


def test_recursive_parsed_guard_checks_future_dataclass_fields() -> None:
    secret = "fixture-auth-marker"
    parsed = parse_cap_document(_alert_xml())[0]
    future_message = _FutureParsedCapMessage(
        **vars(parsed),
        future_metadata={"nested": ("public", [secret])},
    )
    adapter = CwaHeavyRainWarningAdapter(
        authorization=secret,
        fetched_at=FETCHED_AT,
        fetch_cap=lambda _url, _authorization, _timeout: _alert_xml(),
        parse_cap=lambda _xml: (future_message,),
    )

    with pytest.raises(CapDocumentError) as raised:
        adapter.run()

    assert "[REDACTED]" in str(raised.value)
    _assert_secret_free_exception(raised.value, secret=secret)


def test_recursive_parsed_guard_checks_general_sequence_fields() -> None:
    secret = "fixture-auth-marker"
    parsed = parse_cap_document(_alert_xml())[0]
    future_message = _FutureParsedCapMessage(
        **vars(parsed),
        future_metadata=UserList(["public", secret]),
    )
    adapter = CwaHeavyRainWarningAdapter(
        authorization=secret,
        fetched_at=FETCHED_AT,
        fetch_cap=lambda _url, _authorization, _timeout: _alert_xml(),
        parse_cap=lambda _xml: (future_message,),
    )

    with pytest.raises(CapDocumentError) as raised:
        adapter.run()

    assert "[REDACTED]" in str(raised.value)
    _assert_secret_free_exception(raised.value, secret=secret)


@pytest.mark.parametrize("poisoned_field", ("source_id", "source_url", "payload"))
def test_recursive_pre_persistence_guard_rejects_secret_in_prepared_raw(
    monkeypatch: pytest.MonkeyPatch,
    poisoned_field: str,
) -> None:
    secret = "fixture-auth-marker"
    original_prepare = cwa_cap_module._prepare_row

    def poisoned_prepare(*args: Any, **kwargs: Any) -> tuple[RawSourceItem, str]:
        raw, reason = original_prepare(*args, **kwargs)
        replacement: object
        if poisoned_field == "payload":
            replacement = {"future": {"nested": ["public", secret]}}
        else:
            replacement = f"synthetic-{poisoned_field}-{secret}"
        return replace(raw, **{poisoned_field: replacement}), reason

    monkeypatch.setattr(cwa_cap_module, "_prepare_row", poisoned_prepare)
    adapter = CwaHeavyRainWarningAdapter(
        authorization=secret,
        fetched_at=FETCHED_AT,
        fetch_cap=lambda _url, _authorization, _timeout: _alert_xml(),
    )

    with pytest.raises(CapDocumentError) as raised:
        adapter.run()

    assert "[REDACTED]" in str(raised.value)
    _assert_secret_free_exception(raised.value, secret=secret)


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
        cap_url="https://example.test/cap?channel=fixture-private-query",
        fetched_at=FETCHED_AT,
    )

    with pytest.raises(CwaHeavyRainWarningRateLimitError) as exc_info:
        adapter.run()

    assert attempts == 1
    assert exc_info.value.retry_after_seconds == expected
    assert SAFE_AUTHORIZATION not in str(exc_info.value)
    assert "fixture-private-query" not in str(exc_info.value)
    assert "[REDACTED]" in str(exc_info.value)
    assert "?" not in str(exc_info.value)
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
    assert "[REDACTED]" in str(exc_info.value)
    assert "?" not in str(exc_info.value)
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None


def test_injected_adapter_error_with_secret_chain_is_sanitized() -> None:
    def fail(url: str, authorization: str, timeout_seconds: int) -> str:
        del url, timeout_seconds
        try:
            raise RuntimeError(f"nested secret={authorization}")
        except RuntimeError as exc:
            raise CwaHeavyRainWarningFetchError(
                f"adapter secret={authorization}"
            ) from exc

    adapter = CwaHeavyRainWarningAdapter(
        authorization=SAFE_AUTHORIZATION,
        cap_url="https://example.test/cap",
        fetched_at=FETCHED_AT,
        fetch_cap=fail,
    )

    with pytest.raises(CwaHeavyRainWarningFetchError) as exc_info:
        adapter.run()

    assert SAFE_AUTHORIZATION not in str(exc_info.value)
    assert SAFE_AUTHORIZATION not in repr(vars(exc_info.value))
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None


def test_injected_fetcher_encoded_secret_message_chain_and_batch_are_sanitized(
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "fixture injected+/authorization"
    encoded = quote(secret, safe="")
    plus_encoded = quote_plus(secret)

    def fail(_url: str, _authorization: str, _timeout_seconds: int) -> str:
        inner = RuntimeError(f"inner encoded={encoded}")
        raise CwaHeavyRainWarningFetchError(
            f"outer plus-encoded={plus_encoded}"
        ) from inner

    adapter = CwaHeavyRainWarningAdapter(
        authorization=secret,
        cap_url="https://example.test/cap?channel=fixture-private-query",
        fetched_at=FETCHED_AT,
        fetch_cap=fail,
    )

    with pytest.raises(CwaHeavyRainWarningFetchError) as raised:
        adapter.run()

    assert "fixture-private-query" not in str(raised.value)
    assert "[REDACTED]" in str(raised.value)
    _assert_secret_free_exception(raised.value, secret=secret)

    summary = run_adapter_batch(adapter)
    logged = capsys.readouterr().out
    assert summary.status == "failed"
    assert summary.items_fetched == 0
    assert summary.raw_ref is None
    for reflected in {secret, encoded, plus_encoded}:
        assert reflected not in repr(vars(summary))
        assert reflected not in repr(summary.log_fields())
        assert reflected not in logged
