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
            {"apikey": "test-secret", "format": "json", "limit": "50"},
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
    assert result.normalized == ()
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
    transport_id = "ncdr-transport:" + hashlib.sha256(
        failed_capid.encode("utf-8")
    ).hexdigest()[:24]

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


def test_ncdr_geocode_area_is_raw_audited_with_canonical_cap_identity() -> None:
    result = _adapter(
        index_payload={"data": [{"capid": "CAP-001"}]},
        dumps={"CAP-001": _fixture("ncdr_dump_flood_cap.xml")},
    ).run()

    assert result.normalized == ()
    assert result.source_rejections[0].reason_code == "ncdr_unreviewed_admin_geometry"
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
    assert raw.payload["source_geocodes"] == [
        {"valueName": "TOWNCODE", "value": "6703500"}
    ]
    assert "geometry" not in raw.payload
    assert build_staging_batch(result).accepted == ()


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
        index_payload={
            "data": [{"capid": "CAP-A"}, {"capid": "CAP-B"}, {"capid": "CAP-C"}]
        },
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
        index_payload={
            "data": [{"capid": cap_id} for cap_id in [*failed_ids, "SUCCESS"]]
        },
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
        index_payload={
            "data": [{"capid": "CAP-A"}, {"capid": "CAP-B"}, {"capid": "CAP-C"}]
        },
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
    assert adapter_is_enabled(
        type(NCDR_CAP_METADATA)(
            key="official.ncdr.cap",
            family=SourceFamily.OFFICIAL,
            enabled_by_default=True,
            display_name="reconstructed",
        ),
        load_worker_settings({}),
    ) is False

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


def test_ncdr_runtime_builder_requires_api_gate_and_nonempty_key() -> None:
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
        "NCDR_ALERTS_API_KEY",
    ):
        values = dict(complete)
        values.pop(missing)
        assert build_runtime_adapters(load_worker_settings(values)) == {}

    blank_key = {**complete, "NCDR_ALERTS_API_KEY": "   "}
    assert build_runtime_adapters(load_worker_settings(blank_key)) == {}


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
    assert adapters["official.ncdr.cap"].run().normalized == ()
    assert index_calls[0][0] == ncdr_cap_module.NCDR_DATASTORE_API_URL
    assert dump_calls[0][0] == ncdr_cap_module.NCDR_DUMP_API_URL


def test_ncdr_config_defaults_are_fail_closed() -> None:
    defaults = load_worker_settings({})

    assert defaults.source_ncdr_cap_enabled is False
    assert defaults.source_ncdr_cap_api_enabled is False
    assert defaults.source_ncdr_cap_contract_enabled is False
    assert defaults.ncdr_alerts_api_key is None
    assert defaults.ncdr_datastore_api_url is None
    assert defaults.ncdr_dump_api_url is None
    assert defaults.ncdr_max_cap_ids_per_run == 50
    assert defaults.ncdr_cap_timeout_seconds == 8


def test_production_builder_has_no_legacy_or_ambiguous_ncdr_endpoint_contract() -> None:
    adapter_source = Path(ncdr_cap_module.__file__).read_text(encoding="utf-8")
    builder_source = Path(build_runtime_adapters.__code__.co_filename).read_text(encoding="utf-8")
    config_source = Path(load_worker_settings.__code__.co_filename).read_text(encoding="utf-8")
    production = f"{builder_source}\n{config_source}"

    assert "RssAtomFeed.ashx" not in production
    assert "NCDR_CAP_API_URL" not in production
    assert '"key"' not in adapter_source
    assert "NCDR_DUMP_API_URL = \"https://alerts.ncdr.nat.gov.tw/api/dump\"" not in (
        adapter_source
    )
