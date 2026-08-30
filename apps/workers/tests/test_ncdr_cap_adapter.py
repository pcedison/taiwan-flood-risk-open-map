from __future__ import annotations

import hashlib
import json
import ssl
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Self, cast
from urllib.error import HTTPError

import pytest

from app.adapters.contracts import SourceFamily
from app.adapters.ncdr import (
    NCDR_CAP_METADATA,
    NcdrCapAlertAdapter,
    NcdrCapAlertConfigurationError,
    NcdrCapAlertFetchError,
    NcdrCapAlertPayloadError,
    parse_ncdr_cap_payload,
)
from app.adapters.ncdr import cap_alerts as ncdr_cap_module
from app.adapters.registry import (
    ADAPTER_REGISTRY,
    adapter_is_enabled,
    enabled_adapter_keys,
)
from app.config import load_worker_settings
from app.jobs.ingestion import run_adapter_batch
from app.jobs.runtime import build_runtime_adapters
from app.pipelines.staging import build_staging_batch

FETCHED_AT = datetime(2026, 6, 15, 3, 10, tzinfo=UTC)
FIXTURES = Path(__file__).parent / "fixtures"
_DEFAULT = object()


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _index(name: str = "ncdr_datastore_active.json") -> object:
    return json.loads(_fixture(name))


def _active_feed(*entries: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<feed xmlns="http://www.w3.org/2005/Atom" '
        'xmlns:cap="urn:oasis:names:tc:emergency:cap:1.1">'
        "<id>https://alerts.ncdr.nat.gov.tw/RSS.aspx</id>"
        "<updated>2026-06-15T11:00:00+08:00</updated>"
        f"{''.join(entries)}"
        "</feed>"
    )


def _feed_entry(
    *,
    cap_id: str = "WRA_FloodWarn_20260615103000_0000",
    category: str = "淹水",
    href: str = (
        "https://alerts.ncdr.nat.gov.tw/Capstorage/WRA/2026/Flood/"
        "WRA_FloodWarn_20260615103000_0000.cap"
    ),
) -> str:
    return (
        "<entry>"
        f"<id>{cap_id}</id>"
        f'<link rel="alternate" href="{href}" />'
        f'<category term="{category}" />'
        "</entry>"
    )


def _assert_secret_free_exception(exc: BaseException, *, secret: str) -> None:
    assert secret not in str(exc)
    assert secret not in repr(exc)
    assert secret not in repr(vars(exc))
    assert "?" not in str(exc)
    assert exc.__cause__ is None
    assert exc.__context__ is None


def _adapter(
    *,
    index_payload: object = _DEFAULT,
    dumps: dict[str, str | Exception] | None = None,
    max_cap_ids_per_run: int = 50,
    api_key: str = "test-secret",
) -> NcdrCapAlertAdapter:
    resolved_index = _index() if index_payload is _DEFAULT else index_payload
    resolved_dumps = (
        {
            "CAP-001": _fixture("ncdr_dump_flood_cap.xml"),
            "CAP-002": _fixture("ncdr_dump_circle_cap.xml"),
        }
        if dumps is None
        else dumps
    )

    def fetch_json(_url: str, _params: dict[str, str], _timeout: int) -> object:
        return resolved_index

    def fetch_text(_url: str, params: dict[str, str], _timeout: int) -> str:
        result = resolved_dumps[params["capid"]]
        if isinstance(result, Exception):
            raise result
        return result

    return NcdrCapAlertAdapter(
        api_key=api_key,
        fetched_at=FETCHED_AT,
        max_cap_ids_per_run=max_cap_ids_per_run,
        fetch_json=fetch_json,
        fetch_text=fetch_text,
    )


def _entity_encoded_secret_cap(field_name: str) -> str:
    encoded_secret = "s&#51;cr3t"
    sender = encoded_secret if field_name == "sender" else "ncdr@example.test"
    identifier = encoded_secret if field_name == "identifier" else "NCDR-ENTITY-001"
    description = (
        f"decoded-{encoded_secret}-description"
        if field_name == "description"
        else "Public description"
    )
    area_desc = (
        f"decoded-{encoded_secret}-area" if field_name == "area_desc" else "Administrative area"
    )
    geocode = encoded_secret if field_name == "geocode" else "6703500"
    references = (
        f"<references>{encoded_secret},REF-001,2026-06-15T01:00:00Z</references>"
        if field_name == "references"
        else ""
    )
    return f"""\
<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">
  <identifier>{identifier}</identifier>
  <sender>{sender}</sender>
  <sent>2026-06-15T02:00:00Z</sent>
  <status>Actual</status>
  <msgType>Alert</msgType>
  <scope>Public</scope>
  {references}
  <info>
    <event>Flood audit</event>
    <description>{description}</description>
    <effective>2026-06-15T02:30:00Z</effective>
    <expires>2026-06-15T04:30:00Z</expires>
    <area>
      <areaDesc>{area_desc}</areaDesc>
      <geocode><valueName>TOWNCODE</valueName><value>{geocode}</value></geocode>
    </area>
  </info>
</alert>
"""


def test_ncdr_datastore_then_dump_uses_exact_separate_parameter_mappings() -> None:
    index_calls: list[tuple[str, dict[str, str], int]] = []
    dump_calls: list[tuple[str, dict[str, str], int]] = []

    def fetch_json(url: str, params: dict[str, str], timeout: int) -> object:
        index_calls.append((url, dict(params), timeout))
        return {"data": [{"capid": "CAP-001"}]}

    def fetch_text(url: str, params: dict[str, str], timeout: int) -> str:
        dump_calls.append((url, dict(params), timeout))
        return _fixture("ncdr_dump_flood_cap.xml")

    result = NcdrCapAlertAdapter(
        api_key="test-secret",
        fetched_at=FETCHED_AT,
        fetch_json=fetch_json,
        fetch_text=fetch_text,
    ).run()

    assert index_calls == [
        (
            "https://alerts.ncdr.nat.gov.tw/api/datastore",
            {"apikey": "test-secret", "format": "json", "limit": "200"},
            8,
        )
    ]
    assert dump_calls == [
        (
            "https://alerts.ncdr.nat.gov.tw/api/dump/datastore",
            {"apikey": "test-secret", "capid": "CAP-001", "format": "xml"},
            8,
        )
    ]
    assert len(result.normalized) == 1
    assert result.normalized[0].source_id == result.fetched[0].source_id
    assert result.fetched[0].payload["transport_capid"] == "CAP-001"
    assert "test-secret" not in result.fetched[0].source_url
    assert "test-secret" not in json.dumps(result.fetched[0].payload)


def test_ncdr_ids_are_trimmed_bounded_deduplicated_sorted_then_sliced() -> None:
    calls: list[str] = []
    overlong = "X" * 257
    index = {
        "data": [
            {"capid": " CAP-C "},
            {"capid": "CAP-A"},
            {"capid": "CAP-C"},
            {"capid": ""},
            {"capid": overlong},
            {"capid": "CAP-B"},
            {"other": "CAP-D"},
        ]
    }

    def fetch_text(_url: str, params: dict[str, str], _timeout: int) -> str:
        calls.append(params["capid"])
        return _fixture("ncdr_dump_flood_cap.xml").replace(
            "NCDR-CAP-001", f"NCDR-{params['capid']}"
        )

    NcdrCapAlertAdapter(
        api_key="test-secret",
        fetched_at=FETCHED_AT,
        max_cap_ids_per_run=2,
        fetch_json=lambda _url, _params, _timeout: index,
        fetch_text=fetch_text,
    ).run()

    assert calls == ["CAP-A", "CAP-B"]


@pytest.mark.parametrize(("configured", "expected"), ((0, "1"), (999, "200")))
def test_ncdr_max_cap_ids_is_clamped_to_inclusive_runtime_bounds(
    configured: int,
    expected: str,
) -> None:
    calls: list[dict[str, str]] = []

    def fetch_json(_url: str, params: dict[str, str], _timeout: int) -> object:
        calls.append(dict(params))
        return {"data": []}

    NcdrCapAlertAdapter(
        api_key="test-secret",
        max_cap_ids_per_run=configured,
        fetch_json=fetch_json,
        fetch_text=lambda _url, _params, _timeout: "",
    ).run()

    assert calls[0]["limit"] == expected


def test_ncdr_valid_empty_datastore_is_succeeded_no_active_event() -> None:
    result = _adapter(index_payload=_index("ncdr_datastore_empty.json")).run()
    summary = run_adapter_batch(_adapter(index_payload=_index("ncdr_datastore_empty.json")))

    assert result.fetched == ()
    assert result.rejected == ()
    assert result.no_active_event is True
    assert summary.status == "succeeded"
    assert summary.error_code == "no_active_event"


@pytest.mark.parametrize(
    "payload",
    (
        {"data": {"records": []}},
        {"data": {"items": []}},
    ),
)
def test_ncdr_valid_nested_empty_datastore_is_succeeded_no_active_event(
    payload: object,
) -> None:
    result = _adapter(index_payload=payload).run()

    assert result.fetched == ()
    assert result.rejected == ()
    assert result.no_active_event is True


@pytest.mark.parametrize(
    "record",
    (
        {"other": "CAP-001"},
        {"capid": ""},
        {"capid": "   "},
        {"capid": "X" * 257},
    ),
)
def test_ncdr_nonempty_datastore_with_only_unusable_capids_is_not_healthy_empty(
    record: dict[str, str],
) -> None:
    adapter = _adapter(index_payload={"data": [record]})

    with pytest.raises(NcdrCapAlertPayloadError):
        adapter.run()


def test_ncdr_all_unusable_capids_fail_the_adapter_batch_instead_of_retiring() -> None:
    summary = run_adapter_batch(
        _adapter(index_payload={"data": [{"capid": " "}, {"other": "CAP-001"}]})
    )

    assert summary.status == "failed"
    assert summary.error_code == "NcdrCapAlertPayloadError"
    assert summary.error_code != "no_active_event"


@pytest.mark.parametrize(
    "payload",
    (
        None,
        "not-json",
        {},
        {"data": "not-a-list"},
        {"data": [{"capid": 123}]},
    ),
)
def test_ncdr_malformed_index_is_not_healthy_empty(payload: object) -> None:
    with pytest.raises(NcdrCapAlertPayloadError):
        _adapter(index_payload=payload).run()


def test_ncdr_mixed_dump_failure_is_partial_and_uses_digest_transport_identity() -> None:
    failed_capid = "CAP-001"
    dumps = {
        failed_capid: RuntimeError("failed?apikey=test-secret&capid=CAP-001"),
        "CAP-002": _fixture("ncdr_dump_circle_cap.xml"),
    }
    result = _adapter(dumps=dumps).run()
    summary = run_adapter_batch(_adapter(dumps=dumps))
    transport_id = "ncdr-transport:" + hashlib.sha256(failed_capid.encode("utf-8")).hexdigest()[:24]

    assert transport_id in result.rejected
    failed = next(item for item in result.fetched if item.source_id == transport_id)
    rejection = next(item for item in result.source_rejections if item.source_id == transport_id)
    assert rejection.reason_code == "ncdr_dump_fetch_failed"
    assert failed.payload["transport_capid"] == failed_capid
    assert "apikey" not in json.dumps(failed.payload).lower()
    assert "test-secret" not in json.dumps(failed.payload)
    assert "?" not in str(failed.payload.get("error", ""))
    assert result.no_active_event is False
    assert summary.status == "partial"


def test_ncdr_mixed_injected_dump_429_preserves_bounded_cooldown_in_raw_audit() -> None:
    secret = "test-secret"
    attempts: list[str] = []

    def fetch_text(_url: str, params: dict[str, str], _timeout: int) -> str:
        cap_id = params["capid"]
        attempts.append(cap_id)
        if cap_id == "CAP-001":
            raise ncdr_cap_module.NcdrCapAlertRateLimitError(
                f"rate limited?apikey={secret}",
                retry_after_seconds=9999,
            )
        return _fixture("ncdr_dump_circle_cap.xml")

    adapter = NcdrCapAlertAdapter(
        api_key=secret,
        fetched_at=FETCHED_AT,
        fetch_json=lambda _url, _params, _timeout: _index(),
        fetch_text=fetch_text,
    )

    result = adapter.run()
    failed = next(item for item in result.fetched if item.payload.get("error") is not None)

    assert attempts == ["CAP-001", "CAP-002"]
    assert failed.payload["retry_after_seconds"] == 3600
    assert secret not in json.dumps(failed.payload)
    assert "?" not in json.dumps(failed.payload)
    assert result.no_active_event is False


def test_ncdr_all_injected_dump_429s_expose_max_bounded_cooldown() -> None:
    secret = "test-secret"
    attempts: list[str] = []
    cooldowns = {"CAP-001": -5, "CAP-002": 9999}

    def fetch_text(_url: str, params: dict[str, str], _timeout: int) -> str:
        cap_id = params["capid"]
        attempts.append(cap_id)
        raise ncdr_cap_module.NcdrCapAlertRateLimitError(
            f"rate limited?apikey={secret}",
            retry_after_seconds=cooldowns[cap_id],
        )

    adapter = NcdrCapAlertAdapter(
        api_key=secret,
        fetched_at=FETCHED_AT,
        fetch_json=lambda _url, _params, _timeout: _index(),
        fetch_text=fetch_text,
    )

    with pytest.raises(
        NcdrCapAlertFetchError,
        match="^all selected NCDR CAP dumps failed$",
    ) as raised:
        adapter.run()

    assert attempts == ["CAP-001", "CAP-002"]
    assert raised.value.retry_after_seconds == 3600
    _assert_secret_free_exception(raised.value, secret=secret)


def test_ncdr_builtin_dump_429_cooldown_survives_adapter_aggregation(
    monkeypatch,
) -> None:
    secret = "test-secret"
    calls = 0
    retry_at = FETCHED_AT + timedelta(hours=2)

    def fake_urlopen(request, **_kwargs: object) -> object:
        nonlocal calls
        calls += 1
        raise HTTPError(
            request.full_url,
            429,
            f"rate limited?apikey={secret}",
            {"Retry-After": retry_at.strftime("%a, %d %b %Y %H:%M:%S GMT")},
            None,
        )

    monkeypatch.setattr(ncdr_cap_module, "urlopen", fake_urlopen)
    adapter = NcdrCapAlertAdapter(
        api_key=secret,
        fetched_at=FETCHED_AT,
        fetch_json=lambda _url, _params, _timeout: {"data": [{"capid": "CAP-001"}]},
    )

    with pytest.raises(
        NcdrCapAlertFetchError,
        match="^all selected NCDR CAP dumps failed$",
    ) as raised:
        adapter.run()

    assert calls == 1
    assert raised.value.retry_after_seconds == 3600
    _assert_secret_free_exception(raised.value, secret=secret)


def test_ncdr_all_selected_dump_failures_raise_exact_failure() -> None:
    adapter = _adapter(
        dumps={
            "CAP-001": RuntimeError("test-secret"),
            "CAP-002": RuntimeError("test-secret"),
        }
    )

    with pytest.raises(
        NcdrCapAlertFetchError,
        match="^all selected NCDR CAP dumps failed$",
    ) as raised:
        adapter.run()

    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert "test-secret" not in str(raised.value)


def test_ncdr_malformed_cap_is_a_dump_failure_not_empty() -> None:
    adapter = _adapter(
        index_payload={"data": [{"capid": "CAP-001"}]},
        dumps={"CAP-001": "<feed />"},
    )

    with pytest.raises(
        NcdrCapAlertFetchError,
        match="^all selected NCDR CAP dumps failed$",
    ):
        adapter.run()


def test_ncdr_injected_fetcher_secret_message_cause_and_context_are_sanitized() -> None:
    secret = "s3cr3t-api-key"
    inner = RuntimeError(f"inner apikey={secret}")

    def fetch_json(_url: str, _params: dict[str, str], _timeout: int) -> object:
        raise RuntimeError(f"outer?apikey={secret}&format=json") from inner

    with pytest.raises(NcdrCapAlertFetchError) as raised:
        NcdrCapAlertAdapter(
            api_key=secret,
            fetch_json=fetch_json,
            fetch_text=lambda _url, _params, _timeout: "",
        ).run()

    assert secret not in str(raised.value)
    assert "?" not in str(raised.value)
    assert "[REDACTED]" in str(raised.value)
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None


@pytest.mark.parametrize(
    "field_name",
    (
        "sender",
        "identifier",
        "description",
        "area_desc",
        "geocode",
        "references",
    ),
)
def test_ncdr_entity_decoded_api_key_is_rejected_before_raw_acceptance(
    field_name: str,
) -> None:
    secret = "s3cr3t"
    xml_text = _entity_encoded_secret_cap(field_name)
    assert secret not in xml_text
    adapter = _adapter(
        api_key=secret,
        index_payload={"data": [{"capid": "CAP-ENTITY"}]},
        dumps={"CAP-ENTITY": xml_text},
    )

    with pytest.raises(NcdrCapAlertPayloadError) as raised:
        adapter.run()

    _assert_secret_free_exception(raised.value, secret=secret)


def test_ncdr_recursive_raw_guard_rejects_secret_bearing_snapshot_metadata() -> None:
    secret = "s3cr3t"
    adapter = NcdrCapAlertAdapter(
        api_key=secret,
        fetched_at=FETCHED_AT,
        raw_snapshot_key=f"snapshot/{secret}/raw",
        fetch_json=lambda _url, _params, _timeout: {"data": [{"capid": "CAP-ENTITY"}]},
        fetch_text=lambda _url, _params, _timeout: _entity_encoded_secret_cap("none"),
    )

    with pytest.raises(NcdrCapAlertPayloadError) as raised:
        adapter.run()

    _assert_secret_free_exception(raised.value, secret=secret)


def test_ncdr_recursive_raw_guard_applies_to_failed_dump_audit_rows() -> None:
    secret = "s3cr3t"

    def fail_text(_url: str, _params: dict[str, str], _timeout: int) -> str:
        raise RuntimeError("safe injected failure")

    adapter = NcdrCapAlertAdapter(
        api_key=secret,
        fetched_at=FETCHED_AT,
        raw_snapshot_key=f"snapshot/{secret}/raw",
        fetch_json=lambda _url, _params, _timeout: {"data": [{"capid": "CAP-ENTITY"}]},
        fetch_text=fail_text,
    )

    with pytest.raises(NcdrCapAlertPayloadError) as raised:
        adapter.run()

    _assert_secret_free_exception(raised.value, secret=secret)


def test_ncdr_entity_decoded_secret_fails_batch_without_raw_or_reflection() -> None:
    secret = "s3cr3t"
    adapter = _adapter(
        api_key=secret,
        index_payload={"data": [{"capid": "CAP-ENTITY"}]},
        dumps={"CAP-ENTITY": _entity_encoded_secret_cap("description")},
    )

    summary = run_adapter_batch(adapter)

    assert summary.status == "failed"
    assert summary.items_fetched == 0
    assert summary.error_code == "NcdrCapAlertPayloadError"
    assert summary.error_message is not None
    assert secret not in summary.error_message
    assert secret not in repr(vars(summary))
    assert "?" not in summary.error_message


def test_ncdr_secret_bearing_endpoint_path_fails_before_fetch_or_persistence() -> None:
    calls = 0

    def fetch_json(_url: str, _params: dict[str, str], _timeout: int) -> object:
        nonlocal calls
        calls += 1
        return {"data": []}

    with pytest.raises(ncdr_cap_module.NcdrCapAlertConfigurationError) as raised:
        NcdrCapAlertAdapter(
            api_key="test-secret",
            datastore_url="https://example.test/test-secret/datastore",
            fetch_json=fetch_json,
            fetch_text=lambda _url, _params, _timeout: "",
        ).run()

    assert calls == 0
    assert "test-secret" not in str(raised.value)
    assert "[REDACTED]" in str(raised.value)


@pytest.mark.parametrize(
    ("fetch_name", "url"),
    (
        ("index", "invalid://example.test/datastore?apikey=test-secret"),
        ("index", "https://example.test:invalid/datastore?apikey=test-secret"),
        ("index", "https://[::1/datastore?apikey=test-secret"),
        ("dump", "invalid://example.test/dump/datastore?apikey=test-secret"),
        ("dump", "https://example.test:invalid/dump/datastore?apikey=test-secret"),
        ("dump", "https://[::1/dump/datastore?apikey=test-secret"),
    ),
)
def test_ncdr_builtin_transport_invalid_url_is_sanitized_across_index_and_dump(
    fetch_name: str,
    url: str,
) -> None:
    params = (
        {"apikey": "test-secret", "format": "json", "limit": "50"}
        if fetch_name == "index"
        else {"apikey": "test-secret", "capid": "CAP-001", "format": "xml"}
    )
    fetcher = ncdr_cap_module._fetch_json if fetch_name == "index" else ncdr_cap_module._fetch_text

    with pytest.raises(NcdrCapAlertFetchError) as raised:
        fetcher(url, params, 1, now=FETCHED_AT)

    _assert_secret_free_exception(raised.value, secret="test-secret")


def test_ncdr_builtin_transport_failure_summary_is_secret_free() -> None:
    adapter = NcdrCapAlertAdapter(
        api_key="test-secret",
        datastore_url="https://example.test:invalid/datastore?apikey=test-secret",
    )

    summary = run_adapter_batch(adapter)

    assert summary.status == "failed"
    assert summary.error_code == "NcdrCapAlertFetchError"
    assert summary.error_message is not None
    assert "test-secret" not in summary.error_message
    assert "?" not in summary.error_message
    assert "test-secret" not in repr(vars(summary))


def test_ncdr_malformed_configured_url_is_a_sanitized_adapter_error() -> None:
    secret = "test-secret"

    with pytest.raises(ncdr_cap_module.NcdrCapAlertConfigurationError) as raised:
        NcdrCapAlertAdapter(
            api_key=secret,
            datastore_url=f"https://[::1/datastore?apikey={secret}",
        )

    _assert_secret_free_exception(raised.value, secret=secret)


@pytest.mark.parametrize("endpoint_name", ("datastore_url", "dump_url"))
def test_ncdr_configured_url_userinfo_is_a_sanitized_configuration_error(
    endpoint_name: str,
) -> None:
    userinfo_secret = "userinfo-password"
    endpoint = f"https://audit-user:{userinfo_secret}@example.test/ncdr?trace=private"

    with pytest.raises(ncdr_cap_module.NcdrCapAlertConfigurationError) as raised:
        NcdrCapAlertAdapter(
            api_key="different-api-key",
            **{endpoint_name: endpoint},
        )

    _assert_secret_free_exception(raised.value, secret=userinfo_secret)
    assert "audit-user" not in str(raised.value)
    assert "@" not in str(raised.value)


@pytest.mark.parametrize("fetch_name", ("index", "dump"))
def test_ncdr_direct_builtin_fetch_rejects_url_userinfo_without_request(
    fetch_name: str,
    monkeypatch,
) -> None:
    userinfo_secret = "userinfo-password"
    calls = 0

    def fail_if_called(*_args: object, **_kwargs: object) -> object:
        nonlocal calls
        calls += 1
        raise AssertionError("urlopen must not be called")

    monkeypatch.setattr(ncdr_cap_module, "urlopen", fail_if_called)
    endpoint = f"https://audit-user:{userinfo_secret}@example.test/ncdr?trace=private"
    params = (
        {"apikey": "different-api-key", "format": "json", "limit": "50"}
        if fetch_name == "index"
        else {
            "apikey": "different-api-key",
            "capid": "CAP-001",
            "format": "xml",
        }
    )
    fetcher = ncdr_cap_module._fetch_json if fetch_name == "index" else ncdr_cap_module._fetch_text

    with pytest.raises(NcdrCapAlertFetchError) as raised:
        fetcher(endpoint, params, 8, now=FETCHED_AT)

    assert calls == 0
    _assert_secret_free_exception(raised.value, secret=userinfo_secret)
    assert "audit-user" not in str(raised.value)
    assert "@" not in str(raised.value)


@pytest.mark.parametrize(
    "dump_result",
    (
        "<unused-success />",
        RuntimeError("unused failure"),
    ),
)
def test_ncdr_injected_fetchers_cannot_create_success_or_failure_raw_with_userinfo(
    dump_result: str | Exception,
) -> None:
    userinfo_secret = "userinfo-password"
    calls: list[str] = []

    def fetch_json(_url: str, _params: dict[str, str], _timeout: int) -> object:
        calls.append("index")
        return {"data": [{"capid": "CAP-001"}]}

    def fetch_text(_url: str, _params: dict[str, str], _timeout: int) -> str:
        calls.append("dump")
        if isinstance(dump_result, Exception):
            raise dump_result
        return dump_result

    with pytest.raises(ncdr_cap_module.NcdrCapAlertConfigurationError) as raised:
        NcdrCapAlertAdapter(
            api_key="different-api-key",
            dump_url=(f"https://audit-user:{userinfo_secret}@example.test/dump?trace=private"),
            fetch_json=fetch_json,
            fetch_text=fetch_text,
        ).run()

    assert calls == []
    _assert_secret_free_exception(raised.value, secret=userinfo_secret)
    assert "audit-user" not in str(raised.value)
    assert "@" not in str(raised.value)


def test_ncdr_builtin_transport_sanitizes_tls_context_failure(monkeypatch) -> None:
    secret = "test-secret"

    def fail_context() -> ssl.SSLContext:
        raise ValueError(f"TLS failed?apikey={secret}")

    monkeypatch.setattr(ncdr_cap_module, "taiwan_gov_open_data_ssl_context", fail_context)

    with pytest.raises(NcdrCapAlertFetchError) as raised:
        ncdr_cap_module._fetch_json(
            ncdr_cap_module.NCDR_DATASTORE_API_URL,
            {"apikey": secret, "format": "json", "limit": "50"},
            8,
            now=FETCHED_AT,
        )

    _assert_secret_free_exception(raised.value, secret=secret)


def test_ncdr_http_429_header_failure_is_sanitized_inside_transport_boundary(
    monkeypatch,
) -> None:
    secret = "test-secret"

    class FailingHeaders:
        def get(self, _name: str) -> str:
            raise RuntimeError(f"headers failed?apikey={secret}")

    def fake_urlopen(request, **_kwargs: object) -> object:
        raise HTTPError(
            request.full_url,
            429,
            f"rate limited?apikey={secret}",
            cast(Any, FailingHeaders()),
            None,
        )

    monkeypatch.setattr(ncdr_cap_module, "urlopen", fake_urlopen)

    with pytest.raises(NcdrCapAlertFetchError) as raised:
        ncdr_cap_module._fetch_json(
            ncdr_cap_module.NCDR_DATASTORE_API_URL,
            {"apikey": secret, "format": "json", "limit": "50"},
            8,
            now=FETCHED_AT,
        )

    _assert_secret_free_exception(raised.value, secret=secret)


def test_ncdr_builtin_transport_sanitizes_response_read_failure(monkeypatch) -> None:
    secret = "test-secret"

    class FailingResponse:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self, _limit: int = -1) -> bytes:
            raise RuntimeError(f"read failed?apikey={secret}")

    monkeypatch.setattr(ncdr_cap_module, "urlopen", lambda *_args, **_kwargs: FailingResponse())

    with pytest.raises(NcdrCapAlertFetchError) as raised:
        ncdr_cap_module._fetch_text(
            ncdr_cap_module.NCDR_DUMP_API_URL,
            {"apikey": secret, "capid": "CAP-001", "format": "xml"},
            8,
            now=FETCHED_AT,
        )

    _assert_secret_free_exception(raised.value, secret=secret)


def test_ncdr_builtin_transport_rejects_non_bytes_response_without_inspecting_it(
    monkeypatch,
) -> None:
    secret = "test-secret"

    class HostileBody:
        def __len__(self) -> int:
            raise RuntimeError(f"length failed?apikey={secret}")

    class HostileResponse:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self, _limit: int = -1) -> bytes:
            return cast(bytes, HostileBody())

    monkeypatch.setattr(ncdr_cap_module, "urlopen", lambda *_args, **_kwargs: HostileResponse())

    with pytest.raises(NcdrCapAlertFetchError) as raised:
        ncdr_cap_module._fetch_text(
            ncdr_cap_module.NCDR_DUMP_API_URL,
            {"apikey": secret, "capid": "CAP-001", "format": "xml"},
            8,
            now=FETCHED_AT,
        )

    _assert_secret_free_exception(raised.value, secret=secret)


def test_ncdr_circle_is_raw_audited_without_center_point() -> None:
    result = _adapter(
        index_payload={"data": [{"capid": "CAP-002"}]},
        dumps={"CAP-002": _fixture("ncdr_dump_circle_cap.xml")},
    ).run()

    assert result.normalized == ()
    assert result.source_rejections[0].reason_code == "ncdr_circle_geometry_unreviewed"
    payload = result.fetched[0].payload
    assert payload["circle"] == {
        "latitude": 22.9997,
        "longitude": 120.227,
        "radius_km": 1.5,
    }
    assert "geometry" not in payload
    assert "latest_point_geometry" not in payload
    assert build_staging_batch(result).accepted == ()


def test_ncdr_geocode_area_is_normalized_with_canonical_cap_identity() -> None:
    result = _adapter(
        index_payload={"data": [{"capid": "CAP-001"}]},
        dumps={"CAP-001": _fixture("ncdr_dump_flood_cap.xml")},
    ).run()

    assert len(result.normalized) == 1
    assert result.source_rejections == ()
    raw = result.fetched[0]
    assert raw.source_id.startswith("cap:")
    assert raw.source_id != "CAP-001"
    assert "CAP-001" not in raw.source_id
    assert raw.payload["cap_sender"] == "ncdr@example.test"
    assert raw.payload["cap_identifier"] == "NCDR-CAP-001"
    assert raw.payload["cap_references"] == [
        {
            "sender": "ncdr@example.test",
            "identifier": "NCDR-CAP-000",
            "sent": "2026-06-15T01:30:00+00:00",
        }
    ]
    assert raw.payload["active_from"] == "2026-06-15T02:35:00+00:00"
    assert raw.payload["active_until"] == "2026-06-15T07:00:00+00:00"
    assert raw.payload["source_geocodes"] == [{"valueName": "TOWNCODE", "value": "6703500"}]
    assert raw.payload["ncdr_geocode_profile"] == "Taiwan_Geocode_103"
    assert raw.payload["ncdr_geocode"] == "6703500"
    assert raw.payload["admin_code"] == "67035000"
    assert "geometry" not in raw.payload
    staged = build_staging_batch(
        result,
        ingestion_generation_started_at=FETCHED_AT,
        snapshot_generation_mode="complete_replace",
    ).accepted
    assert len(staged) == 1
    assert staged[0].payload["ncdr_geocode"] == "6703500"


def test_ncdr_metadata_declares_complete_active_snapshot_replacement() -> None:
    assert NCDR_CAP_METADATA.snapshot_generation_mode == "complete_replace"


def test_ncdr_official_taiwan_geocode_profile_alias_is_normalized() -> None:
    xml_text = _fixture("ncdr_dump_flood_cap.xml").replace(
        "<valueName>TOWNCODE</valueName>",
        "<valueName>Taiwan_Geocode_103</valueName>",
    )

    result = _adapter(
        index_payload={"data": [{"capid": "CAP-001"}]},
        dumps={"CAP-001": xml_text},
    ).run()

    assert len(result.normalized) == 1
    assert result.source_rejections == ()
    assert result.fetched[0].payload["ncdr_geocode_name"] == "Taiwan_Geocode_103"
    assert result.fetched[0].payload["ncdr_geocode"] == "6703500"


def test_ncdr_conflicting_reviewed_geocodes_remain_audit_only() -> None:
    xml_text = _fixture("ncdr_dump_flood_cap.xml").replace(
        "      </geocode>",
        "      </geocode>\n"
        "      <geocode><valueName>Taiwan_Geocode_103</valueName>"
        "<value>6703600</value></geocode>",
    )

    result = _adapter(
        index_payload={"data": [{"capid": "CAP-001"}]},
        dumps={"CAP-001": xml_text},
    ).run()

    assert result.normalized == ()
    assert result.source_rejections[0].reason_code == "ncdr_unreviewed_admin_geometry"
    assert "ncdr_geocode" not in result.fetched[0].payload
    assert build_staging_batch(result).accepted == ()


def test_ncdr_source_polygon_is_not_trusted_even_with_a_reviewed_geocode() -> None:
    xml_text = _fixture("ncdr_dump_flood_cap.xml").replace(
        "      <geocode>",
        "      <polygon>22.90,120.10 22.91,120.11 22.90,120.10</polygon>\n"
        "      <geocode>",
    )

    result = _adapter(
        index_payload={"data": [{"capid": "CAP-001"}]},
        dumps={"CAP-001": xml_text},
    ).run()

    assert result.normalized == ()
    assert result.source_rejections[0].reason_code == "ncdr_polygon_geometry_unreviewed"
    assert build_staging_batch(result).accepted == ()


def test_ncdr_namespaced_alerts_collection_preserves_every_unreviewed_area() -> None:
    xml_text = """\
<alerts xmlns="urn:oasis:names:tc:emergency:cap:1.2">
  <alert>
    <identifier>NCDR-MULTI-001</identifier>
    <sender>ncdr@example.test</sender>
    <sent>2026-06-15T02:00:00Z</sent>
    <status>Actual</status>
    <msgType>Alert</msgType>
    <scope>Public</scope>
    <info>
      <event>Flood polygon, circle, and admin audit</event>
      <headline>Preserve source areas</headline>
      <effective>2026-06-15T02:30:00Z</effective>
      <expires>2026-06-15T04:30:00Z</expires>
      <area>
        <areaDesc>Polygon area</areaDesc>
        <polygon>22.90,120.10 22.91,120.11 22.90,120.10</polygon>
      </area>
      <area>
        <areaDesc>Circle area</areaDesc>
        <circle>22.92,120.12 1.5</circle>
      </area>
      <area>
        <areaDesc>Administrative area</areaDesc>
        <geocode><valueName>TOWNCODE</valueName><value>6703500</value></geocode>
      </area>
    </info>
  </alert>
  <alert>
    <identifier>NCDR-MULTI-002</identifier>
    <sender>ncdr@example.test</sender>
    <sent>2026-06-15T02:05:00Z</sent>
    <status>Actual</status>
    <msgType>Alert</msgType>
    <scope>Public</scope>
    <info>
      <event>Flood message without area</event>
      <description>Message-level semantics remain available for audit.</description>
      <effective>2026-06-15T02:35:00Z</effective>
      <expires>2026-06-15T04:35:00Z</expires>
    </info>
  </alert>
</alerts>
"""
    result = _adapter(
        index_payload={"data": [{"capid": "TRANSPORT-001"}]},
        dumps={"TRANSPORT-001": xml_text},
    ).run()

    assert len(result.fetched) == 4
    assert len(result.source_rejections) == 3
    assert len(result.normalized) == 1
    assert len({item.source_id for item in result.fetched}) == 4
    assert all(item.source_id.startswith("cap:") for item in result.fetched)
    assert all(item.payload["transport_capid"] == "TRANSPORT-001" for item in result.fetched)
    assert {item.reason_code for item in result.source_rejections} == {
        "ncdr_polygon_geometry_unreviewed",
        "ncdr_circle_geometry_unreviewed",
        "ncdr_unreviewed_message_geometry",
    }

    by_area = {item.payload["areaDesc"]: item.payload for item in result.fetched}
    assert by_area["Polygon area"]["polygon"] == [
        {"latitude": 22.9, "longitude": 120.1},
        {"latitude": 22.91, "longitude": 120.11},
        {"latitude": 22.9, "longitude": 120.1},
    ]
    assert by_area["Circle area"]["circle"] == {
        "latitude": 22.92,
        "longitude": 120.12,
        "radius_km": 1.5,
    }
    assert by_area["Administrative area"]["source_geocodes"] == [
        {"valueName": "TOWNCODE", "value": "6703500"}
    ]
    assert by_area[None]["cap_identifier"] == "NCDR-MULTI-002"
    assert by_area[None]["source_geocodes"] == []
    assert len(result.normalized) == 1
    staged = build_staging_batch(
        result,
        ingestion_generation_started_at=FETCHED_AT,
        snapshot_generation_mode="complete_replace",
    )
    assert len(staged.accepted) == 1


def test_ncdr_audit_rows_over_256_across_successful_dumps_fail_closed() -> None:
    def cap(identifier: str, area_count: int) -> str:
        areas = "".join(
            f"<area><areaDesc>area-{index}</areaDesc>"
            f"<geocode><valueName>TOWNCODE</valueName><value>{index}</value></geocode>"
            "</area>"
            for index in range(area_count)
        )
        return (
            '<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">'
            f"<identifier>{identifier}</identifier><sender>ncdr@example.test</sender>"
            "<sent>2026-06-15T10:30:00+08:00</sent><status>Actual</status>"
            "<msgType>Alert</msgType><scope>Public</scope><info><event>淹水警戒</event>"
            "<effective>2026-06-15T10:30:00+08:00</effective>"
            f"<expires>2026-06-15T15:00:00+08:00</expires>{areas}</info></alert>"
        )

    adapter = _adapter(
        index_payload={"data": [{"capid": "CAP-A"}, {"capid": "CAP-B"}, {"capid": "CAP-C"}]},
        dumps={
            "CAP-A": cap("A", 128),
            "CAP-B": cap("B", 128),
            "CAP-C": cap("C", 1),
        },
    )

    with pytest.raises(NcdrCapAlertPayloadError, match="256 audited-row limit"):
        adapter.run()


def test_ncdr_mixed_transport_and_success_rows_share_256_row_audit_budget() -> None:
    failed_ids = [f"FAIL-{index:03d}" for index in range(199)]
    areas = "".join(
        f"<area><areaDesc>area-{index}</areaDesc>"
        f"<geocode><valueName>TOWNCODE</valueName><value>{index}</value></geocode>"
        "</area>"
        for index in range(58)
    )
    successful_cap = (
        '<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">'
        "<identifier>SUCCESS</identifier><sender>ncdr@example.test</sender>"
        "<sent>2026-06-15T10:30:00+08:00</sent><status>Actual</status>"
        "<msgType>Alert</msgType><scope>Public</scope><info><event>淹水警戒</event>"
        "<effective>2026-06-15T10:30:00+08:00</effective>"
        f"<expires>2026-06-15T15:00:00+08:00</expires>{areas}</info></alert>"
    )
    adapter = _adapter(
        index_payload={"data": [{"capid": cap_id} for cap_id in [*failed_ids, "SUCCESS"]]},
        dumps={
            **{cap_id: RuntimeError("failed") for cap_id in failed_ids},
            "SUCCESS": successful_cap,
        },
        max_cap_ids_per_run=200,
    )

    with pytest.raises(
        NcdrCapAlertPayloadError,
        match="NCDR CAP exceeds the 256 audited-row limit",
    ):
        adapter.run()


def test_ncdr_duplicate_prepared_rows_conservatively_consume_audit_budget() -> None:
    areas = "".join(
        f"<area><areaDesc>area-{index}</areaDesc>"
        f"<geocode><valueName>TOWNCODE</valueName><value>{index}</value></geocode>"
        "</area>"
        for index in range(128)
    )
    duplicate_cap = (
        '<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">'
        "<identifier>DUPLICATE</identifier><sender>ncdr@example.test</sender>"
        "<sent>2026-06-15T10:30:00+08:00</sent><status>Actual</status>"
        "<msgType>Alert</msgType><scope>Public</scope><info><event>淹水警戒</event>"
        "<effective>2026-06-15T10:30:00+08:00</effective>"
        f"<expires>2026-06-15T15:00:00+08:00</expires>{areas}</info></alert>"
    )
    one_row_cap = duplicate_cap.replace("DUPLICATE", "THIRD").replace(
        areas,
        "<area><areaDesc>third</areaDesc></area>",
    )
    adapter = _adapter(
        index_payload={"data": [{"capid": "CAP-A"}, {"capid": "CAP-B"}, {"capid": "CAP-C"}]},
        dumps={"CAP-A": duplicate_cap, "CAP-B": duplicate_cap, "CAP-C": one_row_cap},
    )

    with pytest.raises(NcdrCapAlertPayloadError, match="256 audited-row limit"):
        adapter.run()


def test_ncdr_atom_fixture_is_explicit_parser_regression_only() -> None:
    atom_feed = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:cap="urn:oasis:names:tc:emergency:cap:1.2">
  <entry>
    <id>NCDR-CAP-ATOM-001</id>
    <cap:identifier>NCDR-CAP-ATOM-001</cap:identifier>
    <cap:sender>ncdr@example.test</cap:sender>
    <cap:sent>2026-06-15T02:55:00+08:00</cap:sent>
    <cap:event>淹水警戒</cap:event>
    <cap:areaDesc>高雄市前鎮區</cap:areaDesc>
    <cap:circle>22.6100,120.3000 1.0</cap:circle>
  </entry>
</feed>
"""

    parsed = parse_ncdr_cap_payload(atom_feed, source_url="https://example.test/legacy")

    assert parsed[0]["identifier"] == "NCDR-CAP-ATOM-001"
    assert parsed[0]["circle"] == "22.6100,120.3000 1.0"
    assert "geometry" not in parsed[0]


def test_ncdr_http_429_retry_after_is_bounded_and_not_retried(monkeypatch) -> None:
    calls = 0
    retry_at = FETCHED_AT + timedelta(hours=2)

    def fake_urlopen(*_args: object, **_kwargs: object) -> object:
        nonlocal calls
        calls += 1
        raise HTTPError(
            ncdr_cap_module.NCDR_DATASTORE_API_URL,
            429,
            "rate limited",
            {"Retry-After": retry_at.strftime("%a, %d %b %Y %H:%M:%S GMT")},
            None,
        )

    monkeypatch.setattr(ncdr_cap_module, "urlopen", fake_urlopen)

    with pytest.raises(ncdr_cap_module.NcdrCapAlertRateLimitError) as raised:
        ncdr_cap_module._fetch_json(
            ncdr_cap_module.NCDR_DATASTORE_API_URL,
            {"apikey": "test-secret", "format": "json", "limit": "50"},
            8,
            now=FETCHED_AT,
        )

    assert calls == 1
    assert raised.value.retry_after_seconds == 3600
    assert "test-secret" not in str(raised.value)
    assert "?" not in str(raised.value)


def test_ncdr_dump_http_429_integer_retry_after_is_bounded_and_not_retried(
    monkeypatch,
) -> None:
    calls = 0

    def fake_urlopen(*_args: object, **_kwargs: object) -> object:
        nonlocal calls
        calls += 1
        raise HTTPError(
            ncdr_cap_module.NCDR_DUMP_API_URL,
            429,
            "rate limited",
            {"Retry-After": "9999"},
            None,
        )

    monkeypatch.setattr(ncdr_cap_module, "urlopen", fake_urlopen)

    with pytest.raises(ncdr_cap_module.NcdrCapAlertRateLimitError) as raised:
        ncdr_cap_module._fetch_text(
            ncdr_cap_module.NCDR_DUMP_API_URL,
            {"apikey": "test-secret", "capid": "CAP-001", "format": "xml"},
            8,
            now=FETCHED_AT,
        )

    assert calls == 1
    assert raised.value.retry_after_seconds == 3600
    assert "test-secret" not in str(raised.value)
    assert "?" not in str(raised.value)


def test_ncdr_fetch_text_uses_taiwan_gov_tls_context(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    class FakeResponse:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self, _limit: int = -1) -> bytes:
            return b'<alerts xmlns="urn:oasis:names:tc:emergency:cap:1.2" />'

    def fake_urlopen(request, *, timeout: int, context: ssl.SSLContext):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["context"] = context
        return FakeResponse()

    monkeypatch.setattr(ncdr_cap_module, "urlopen", fake_urlopen)

    result = ncdr_cap_module._fetch_text(
        ncdr_cap_module.NCDR_DUMP_API_URL,
        {"apikey": "test-secret", "capid": "CAP-001", "format": "xml"},
        6,
    )

    context = cast(ssl.SSLContext, captured["context"])
    strict = getattr(ssl, "VERIFY_X509_STRICT", 0)
    assert result.startswith("<alerts")
    assert captured["timeout"] == 6
    assert "apikey=test-secret" in captured["url"]
    assert context.verify_mode is ssl.CERT_REQUIRED
    assert context.check_hostname is True
    if strict:
        assert not context.verify_flags & strict


def test_ncdr_registry_gates_are_key_based_source_plus_contract() -> None:
    assert ADAPTER_REGISTRY[NCDR_CAP_METADATA.key] is NCDR_CAP_METADATA
    assert NCDR_CAP_METADATA.family is SourceFamily.OFFICIAL
    assert NCDR_CAP_METADATA.enabled_by_default is False
    assert (
        adapter_is_enabled(
            type(NCDR_CAP_METADATA)(
                key="official.ncdr.cap",
                family=SourceFamily.OFFICIAL,
                enabled_by_default=True,
                display_name="reconstructed",
            ),
            load_worker_settings({}),
        )
        is False
    )

    for values in (
        {"SOURCE_NCDR_CAP_ENABLED": "true"},
        {"SOURCE_NCDR_CAP_CONTRACT_ENABLED": "true"},
        {
            "SOURCE_NCDR_CAP_ENABLED": "true",
            "WORKER_ENABLED_ADAPTER_KEYS": "official.ncdr.cap",
        },
        {
            "SOURCE_NCDR_CAP_CONTRACT_ENABLED": "true",
            "WORKER_ENABLED_ADAPTER_KEYS": "official.ncdr.cap",
        },
    ):
        assert "official.ncdr.cap" not in enabled_adapter_keys(load_worker_settings(values))

    selected = load_worker_settings(
        {
            "SOURCE_NCDR_CAP_ENABLED": "true",
            "SOURCE_NCDR_CAP_CONTRACT_ENABLED": "true",
            "WORKER_ENABLED_ADAPTER_KEYS": "official.ncdr.cap",
        }
    )
    assert enabled_adapter_keys(selected) == ("official.ncdr.cap",)
    assert build_runtime_adapters(selected) == {}


def test_ncdr_runtime_adapter_requires_gates_and_uses_public_feed_without_key() -> None:
    complete = {
        "SOURCE_NCDR_CAP_ENABLED": "true",
        "SOURCE_NCDR_CAP_API_ENABLED": "true",
        "SOURCE_NCDR_CAP_CONTRACT_ENABLED": "true",
        "NCDR_ALERTS_API_KEY": "test-secret",
        "WORKER_ENABLED_ADAPTER_KEYS": "official.ncdr.cap",
    }
    for missing in (
        "SOURCE_NCDR_CAP_ENABLED",
        "SOURCE_NCDR_CAP_API_ENABLED",
        "SOURCE_NCDR_CAP_CONTRACT_ENABLED",
    ):
        values = dict(complete)
        values.pop(missing)
        assert build_runtime_adapters(load_worker_settings(values)) == {}

    def empty_feed_fetcher(_url: str, _params: dict[str, str], _timeout: int) -> str:
        return _active_feed()

    missing_key = dict(complete)
    missing_key.pop("NCDR_ALERTS_API_KEY")
    missing_key_adapters = build_runtime_adapters(
        load_worker_settings(missing_key),
        ncdr_cap_fetch_text=empty_feed_fetcher,
    )
    assert tuple(missing_key_adapters) == ("official.ncdr.cap",)
    assert missing_key_adapters["official.ncdr.cap"].run().no_active_event is True

    blank_key = {**complete, "NCDR_ALERTS_API_KEY": "   "}
    blank_key_adapters = build_runtime_adapters(
        load_worker_settings(blank_key),
        ncdr_cap_fetch_text=empty_feed_fetcher,
    )
    assert tuple(blank_key_adapters) == ("official.ncdr.cap",)
    assert blank_key_adapters["official.ncdr.cap"].run().no_active_event is True


def test_ncdr_default_runtime_builder_uses_two_stage_contract() -> None:
    index_calls: list[tuple[str, dict[str, str], int]] = []
    dump_calls: list[tuple[str, dict[str, str], int]] = []

    def fetch_json(url: str, params: dict[str, str], timeout: int) -> object:
        index_calls.append((url, dict(params), timeout))
        return {"data": [{"capid": "CAP-001"}]}

    def fetch_text(url: str, params: dict[str, str], timeout: int) -> str:
        dump_calls.append((url, dict(params), timeout))
        return _fixture("ncdr_dump_flood_cap.xml")

    adapters = build_runtime_adapters(
        load_worker_settings(
            {
                "SOURCE_NCDR_CAP_ENABLED": "true",
                "SOURCE_NCDR_CAP_API_ENABLED": "true",
                "SOURCE_NCDR_CAP_CONTRACT_ENABLED": "true",
                "NCDR_ALERTS_API_KEY": "test-secret",
                "WORKER_ENABLED_ADAPTER_KEYS": "official.ncdr.cap",
            }
        ),
        fetched_at=FETCHED_AT,
        ncdr_cap_fetch_json=fetch_json,
        ncdr_cap_fetch_text=fetch_text,
    )

    assert tuple(adapters) == ("official.ncdr.cap",)
    assert len(adapters["official.ncdr.cap"].run().normalized) == 1
    assert index_calls[0][0] == ncdr_cap_module.NCDR_DATASTORE_API_URL
    assert dump_calls[0][0] == ncdr_cap_module.NCDR_DUMP_API_URL


def test_ncdr_public_active_feed_needs_no_api_key_and_fetches_flood_cap() -> None:
    calls: list[tuple[str, dict[str, str], int]] = []

    def fetch_text(url: str, params: dict[str, str], timeout: int) -> str:
        calls.append((url, dict(params), timeout))
        if url == ncdr_cap_module.NCDR_ACTIVE_ATOM_FEED_URL:
            return _active_feed(_feed_entry())
        return _fixture("ncdr_dump_flood_cap.xml")

    result = NcdrCapAlertAdapter(
        fetched_at=FETCHED_AT,
        timeout_seconds=6,
        fetch_text=fetch_text,
    ).run()

    assert len(result.fetched) == 1
    assert len(result.normalized) == 1
    assert result.no_active_event is False
    assert result.source_rejections == ()
    assert calls == [
        (ncdr_cap_module.NCDR_ACTIVE_ATOM_FEED_URL, {}, 6),
        (
            (
                "https://alerts.ncdr.nat.gov.tw/Capstorage/WRA/2026/Flood/"
                "WRA_FloodWarn_20260615103000_0000.cap"
            ),
            {},
            6,
        ),
    ]


def test_ncdr_public_cancel_only_snapshot_is_audited_no_active_event() -> None:
    cancel_xml = _fixture("ncdr_dump_flood_cap.xml").replace(
        "<msgType>Alert</msgType>",
        "<msgType>Cancel</msgType>",
    )

    def fetch_text(url: str, _params: dict[str, str], _timeout: int) -> str:
        if url == ncdr_cap_module.NCDR_ACTIVE_ATOM_FEED_URL:
            return _active_feed(_feed_entry())
        return cancel_xml

    adapter = NcdrCapAlertAdapter(fetched_at=FETCHED_AT, fetch_text=fetch_text)
    result = adapter.run()
    summary = run_adapter_batch(adapter)

    assert len(result.fetched) == 1
    assert len(result.normalized) == 1
    assert result.rejected == ()
    assert result.no_active_event is True
    assert result.normalized[0].source_timestamp == datetime(2026, 6, 15, 2, 30, tzinfo=UTC)
    assert summary.status == "succeeded"
    assert summary.error_code == "no_active_event"
    assert summary.items_fetched == summary.items_promoted == 1
    assert summary.snapshot_generation_mode == "complete_replace"
    assert summary.snapshot_activation_eligible is True
    assert summary.raw_ref is not None
    assert summary.event_active_from_min is None
    assert summary.event_active_until_max is None


def test_ncdr_public_mixed_alert_and_cancel_snapshot_is_not_no_active_event() -> None:
    alert_href = (
        "https://alerts.ncdr.nat.gov.tw/Capstorage/WRA/2026/Flood/active-alert.cap"
    )
    cancel_href = (
        "https://alerts.ncdr.nat.gov.tw/Capstorage/WRA/2026/Flood/cancel-alert.cap"
    )
    cancel_xml = _fixture("ncdr_dump_flood_cap.xml").replace(
        "<msgType>Alert</msgType>",
        "<msgType>Cancel</msgType>",
    )

    def fetch_text(url: str, _params: dict[str, str], _timeout: int) -> str:
        if url == ncdr_cap_module.NCDR_ACTIVE_ATOM_FEED_URL:
            return _active_feed(
                _feed_entry(cap_id="ACTIVE", href=alert_href),
                _feed_entry(cap_id="CANCEL", href=cancel_href),
            )
        if url == cancel_href:
            return cancel_xml.replace("NCDR-CAP-001", "NCDR-CAP-CANCEL")
        return _fixture("ncdr_dump_flood_cap.xml")

    result = NcdrCapAlertAdapter(fetched_at=FETCHED_AT, fetch_text=fetch_text).run()

    assert len(result.fetched) == 2
    assert len(result.normalized) == 2
    assert result.rejected == ()
    assert result.no_active_event is False


def test_ncdr_public_active_feed_default_capacity_covers_widespread_event() -> None:
    entry_count = 54
    entries = tuple(
        _feed_entry(
            cap_id=f"CAP-{index}",
            href=(
                "https://alerts.ncdr.nat.gov.tw/Capstorage/WRA/2026/Flood/"
                f"CAP-{index}.cap"
            ),
        )
        for index in range(entry_count)
    )
    calls: list[str] = []

    def fetch_text(url: str, _params: dict[str, str], _timeout: int) -> str:
        calls.append(url)
        if url == ncdr_cap_module.NCDR_ACTIVE_ATOM_FEED_URL:
            return _active_feed(*entries)
        return _fixture("ncdr_dump_flood_cap.xml")

    NcdrCapAlertAdapter(fetched_at=FETCHED_AT, fetch_text=fetch_text).run()

    assert calls[0] == ncdr_cap_module.NCDR_ACTIVE_ATOM_FEED_URL
    assert len(calls) == entry_count + 1


def test_ncdr_public_active_feed_without_flood_is_healthy_empty_poll() -> None:
    calls: list[str] = []

    def fetch_text(url: str, _params: dict[str, str], _timeout: int) -> str:
        calls.append(url)
        return _active_feed(_feed_entry(category="河川高水位"))

    adapter = NcdrCapAlertAdapter(fetched_at=FETCHED_AT, fetch_text=fetch_text)
    result = adapter.run()
    summary = run_adapter_batch(adapter)

    assert result.fetched == ()
    assert result.source_rejections == ()
    assert result.no_active_event is True
    assert summary.status == "succeeded"
    assert summary.error_code == "no_active_event"
    assert calls == [
        ncdr_cap_module.NCDR_ACTIVE_ATOM_FEED_URL,
        ncdr_cap_module.NCDR_ACTIVE_ATOM_FEED_URL,
    ]


def test_ncdr_public_active_feed_deduplicates_identical_flood_entry() -> None:
    calls: list[str] = []

    def fetch_text(url: str, _params: dict[str, str], _timeout: int) -> str:
        calls.append(url)
        if url == ncdr_cap_module.NCDR_ACTIVE_ATOM_FEED_URL:
            entry = _feed_entry()
            return _active_feed(entry, entry)
        return _fixture("ncdr_dump_flood_cap.xml")

    result = NcdrCapAlertAdapter(
        fetched_at=FETCHED_AT,
        fetch_text=fetch_text,
    ).run()

    assert len(result.normalized) == 1
    assert calls == [
        ncdr_cap_module.NCDR_ACTIVE_ATOM_FEED_URL,
        (
            "https://alerts.ncdr.nat.gov.tw/Capstorage/WRA/2026/Flood/"
            "WRA_FloodWarn_20260615103000_0000.cap"
        ),
    ]


@pytest.mark.parametrize(
    ("first", "second"),
    (
        (
            _feed_entry(),
            _feed_entry(
                href=(
                    "https://alerts.ncdr.nat.gov.tw/Capstorage/WRA/2026/Flood/"
                    "same-id-different-url.cap"
                )
            ),
        ),
        (
            _feed_entry(),
            _feed_entry(
                cap_id="DIFFERENT-ID",
            ),
        ),
    ),
)
def test_ncdr_public_active_feed_rejects_conflicting_transport_identity(
    first: str,
    second: str,
) -> None:
    adapter = NcdrCapAlertAdapter(
        fetched_at=FETCHED_AT,
        fetch_text=lambda _url, _params, _timeout: _active_feed(first, second),
    )

    with pytest.raises(NcdrCapAlertPayloadError, match="conflicting flood entries"):
        adapter.run()


@pytest.mark.parametrize(
    "href",
    (
        "https://example.test/Capstorage/WRA/Flood.cap",
        "http://alerts.ncdr.nat.gov.tw/Capstorage/WRA/Flood.cap",
        "https://alerts.ncdr.nat.gov.tw/not-cap-storage/Flood.cap",
        "https://alerts.ncdr.nat.gov.tw/Capstorage/WRA/Flood.xml",
        "https://alerts.ncdr.nat.gov.tw/Capstorage/WRA/Flood.cap?token=secret",
    ),
)
def test_ncdr_public_active_feed_rejects_untrusted_flood_cap_links(href: str) -> None:
    adapter = NcdrCapAlertAdapter(
        fetched_at=FETCHED_AT,
        fetch_text=lambda _url, _params, _timeout: _active_feed(_feed_entry(href=href)),
    )

    with pytest.raises(NcdrCapAlertPayloadError, match="untrusted CAP link"):
        adapter.run()


def test_ncdr_public_active_feed_fails_instead_of_silently_truncating() -> None:
    entries = tuple(
        _feed_entry(
            cap_id=f"CAP-{index}",
            href=(f"https://alerts.ncdr.nat.gov.tw/Capstorage/WRA/2026/Flood/CAP-{index}.cap"),
        )
        for index in range(3)
    )
    adapter = NcdrCapAlertAdapter(
        fetched_at=FETCHED_AT,
        max_cap_ids_per_run=2,
        fetch_text=lambda _url, _params, _timeout: _active_feed(*entries),
    )

    with pytest.raises(NcdrCapAlertPayloadError, match="exceeds the configured run limit"):
        adapter.run()


@pytest.mark.parametrize(
    "feed_url",
    (
        "http://alerts.ncdr.nat.gov.tw/RssAtomFeeds.ashx",
        "https://example.test/RssAtomFeeds.ashx",
        "https://alerts.ncdr.nat.gov.tw:444/RssAtomFeeds.ashx",
        "https://alerts.ncdr.nat.gov.tw/RssAtomFeeds.ashx?apikey=secret",
        "https://alerts.ncdr.nat.gov.tw/other-feed.atom",
    ),
)
def test_ncdr_public_active_feed_configuration_is_pinned_to_official_https(
    feed_url: str,
) -> None:
    with pytest.raises(NcdrCapAlertConfigurationError, match=r"\[REDACTED\]"):
        NcdrCapAlertAdapter(active_feed_url=feed_url)


def test_ncdr_config_defaults_are_fail_closed() -> None:
    defaults = load_worker_settings({})

    assert defaults.source_ncdr_cap_enabled is False
    assert defaults.source_ncdr_cap_api_enabled is False
    assert defaults.source_ncdr_cap_contract_enabled is False
    assert defaults.ncdr_alerts_api_key is None
    assert defaults.ncdr_datastore_api_url is None
    assert defaults.ncdr_dump_api_url is None
    assert defaults.ncdr_max_cap_ids_per_run == 200
    assert defaults.ncdr_cap_timeout_seconds == 8


def test_production_builder_uses_explicit_public_active_feed_contract() -> None:
    adapter_source = Path(ncdr_cap_module.__file__).read_text(encoding="utf-8")
    builder_source = Path(build_runtime_adapters.__code__.co_filename).read_text(encoding="utf-8")
    config_source = Path(load_worker_settings.__code__.co_filename).read_text(encoding="utf-8")
    production = f"{builder_source}\n{config_source}"

    assert "NCDR_ACTIVE_ATOM_FEED_URL" in adapter_source
    assert "api_key=settings.ncdr_alerts_api_key" in builder_source
    assert "RssAtomFeeds.ashx" in adapter_source
    assert "NCDR_CAP_API_URL" not in production
    assert '"key"' not in adapter_source
    assert 'NCDR_DUMP_API_URL = "https://alerts.ncdr.nat.gov.tw/api/dump"' not in (adapter_source)
