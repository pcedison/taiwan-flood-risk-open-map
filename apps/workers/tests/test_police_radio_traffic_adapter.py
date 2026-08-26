from __future__ import annotations

import json
from collections import UserDict
from datetime import UTC, datetime
from email.message import Message
from pathlib import Path
from typing import Any, Self
from urllib.error import HTTPError

import pytest

from app.adapters.contracts import EventType
from app.adapters.police_radio_traffic import (
    MAX_POLICE_RADIO_RESPONSE_BYTES,
    POLICE_RADIO_LIMITATIONS,
    POLICE_RADIO_TRAFFIC_URL,
    PoliceRadioTrafficAdapter,
    PoliceRadioTrafficFetchError,
    PoliceRadioTrafficPayloadError,
    PoliceRadioTrafficRateLimitError,
)
from app.adapters.police_radio_traffic import road_incidents as police_module
from app.pipelines.staging import build_staging_batch

FIXTURES = Path(__file__).parent / "fixtures"
FETCHED_AT = datetime(2026, 8, 26, 2, 30, tzinfo=UTC)


def _fixture() -> object:
    return json.loads(
        (FIXTURES / "police_radio_traffic_flood.json").read_text(encoding="utf-8")
    )


def _record(**overrides: object) -> dict[str, object]:
    record = dict(_fixture()[0])  # type: ignore[index]
    record.update(overrides)
    return record


def _adapter(
    records: object,
    *,
    fetched_at: datetime = FETCHED_AT,
) -> PoliceRadioTrafficAdapter:
    return PoliceRadioTrafficAdapter(payload=records, fetched_at=fetched_at)


def test_fixture_normalizes_reported_flood_context_with_source_local_times() -> None:
    result = _adapter(_fixture()).run()

    assert len(result.fetched) == 1
    assert len(result.normalized) == 1
    assert result.rejected == ()
    raw = result.fetched[0]
    evidence = result.normalized[0]
    assert raw.source_id == "UID-001"
    assert raw.source_url == POLICE_RADIO_TRAFFIC_URL
    assert raw.payload["evidence_scope"] == "context"
    assert raw.payload["location_precision"] == "road_or_lane"
    assert raw.payload["context_kind"] == "reported_flood_road_incident"
    assert raw.payload["verification_status"] == "reported_unverified"
    assert raw.payload["incident_state"] == "active"
    assert raw.payload["upstream_updated_at"] == "2026-08-26T02:20:00+00:00"
    assert raw.payload["geometry"] == {
        "type": "Point",
        "coordinates": [120.1842, 23.0478],
    }
    assert raw.payload["limitations"] == list(POLICE_RADIO_LIMITATIONS)
    assert evidence.event_type is EventType.STATUS_ONLY
    assert evidence.source_timestamp == datetime(2026, 8, 26, 2, 15, tzinfo=UTC)
    assert evidence.source_id == "UID-001"


def test_staging_preserves_only_the_reviewed_context_contract() -> None:
    staged = build_staging_batch(_adapter(_fixture()).run()).accepted[0]

    assert staged.event_type == "status_only"
    assert staged.payload["evidence_scope"] == "context"
    assert staged.payload["location_precision"] == "road_or_lane"
    assert staged.payload["context_kind"] == "reported_flood_road_incident"
    assert staged.payload["verification_status"] == "reported_unverified"
    assert staged.payload["incident_state"] == "active"
    assert staged.payload["upstream_updated_at"] == "2026-08-26T02:20:00+00:00"
    assert staged.payload["limitations"] == list(POLICE_RADIO_LIMITATIONS)


@pytest.mark.parametrize("keyword", ("淹水", "積水", "水淹", "道路淹水"))
def test_only_explicit_flood_keywords_are_accepted(keyword: str) -> None:
    result = _adapter([_record(comment=f"前方{keyword}請改道")]).run()

    assert len(result.normalized) == 1


@pytest.mark.parametrize("rain_word", ("大雨", "豪雨", "下雨"))
def test_rain_only_text_is_not_promoted_to_a_flood_incident(rain_word: str) -> None:
    result = _adapter([_record(comment=f"前方{rain_word}請減速")]).run()

    assert result.normalized == ()
    assert result.rejected == ("UID-001",)
    assert result.source_rejections[0].reason_code == "police_radio_rain_only"


def test_unrelated_traffic_is_not_a_detailed_source_rejection() -> None:
    result = _adapter([_record(comment="車多壅塞，請改道")]).run()

    assert result.normalized == ()
    assert result.rejected == ("UID-001",)
    assert result.source_rejections == ()


@pytest.mark.parametrize(
    ("overrides", "reason_code"),
    (
        ({"happendate": ""}, "police_radio_invalid_source_time"),
        ({"happentime": "not-a-time"}, "police_radio_invalid_source_time"),
        (
            {"happendate": "2026-08-26", "happentime": "10:36:00"},
            "police_radio_future_source_time",
        ),
        (
            {"happendate": "2026-08-25", "happentime": "20:29:59"},
            "police_radio_stale_source_time",
        ),
        ({"modDttm": ""}, "police_radio_invalid_update_time"),
        ({"modDttm": "not-a-time"}, "police_radio_invalid_update_time"),
    ),
)
def test_invalid_future_and_stale_source_times_fail_closed(
    overrides: dict[str, object],
    reason_code: str,
) -> None:
    result = _adapter([_record(**overrides)]).run()

    assert result.normalized == ()
    assert result.source_rejections[0].reason_code == reason_code


@pytest.mark.parametrize(
    ("overrides", "reason_code"),
    (
        ({"x1": ""}, "police_radio_invalid_coordinates"),
        ({"y1": "not-a-number"}, "police_radio_invalid_coordinates"),
        ({"x1": "116.999"}, "police_radio_coordinates_outside_taiwan"),
        ({"x1": "123.501"}, "police_radio_coordinates_outside_taiwan"),
        ({"y1": "19.999"}, "police_radio_coordinates_outside_taiwan"),
        ({"y1": "27.501"}, "police_radio_coordinates_outside_taiwan"),
    ),
)
def test_coordinates_are_required_numeric_and_inside_reviewed_taiwan_bounds(
    overrides: dict[str, object],
    reason_code: str,
) -> None:
    result = _adapter([_record(**overrides)]).run()

    assert result.normalized == ()
    assert result.source_rejections[0].reason_code == reason_code


@pytest.mark.parametrize("resolved_word", ("解除", "排除", "恢復通行", "已排除"))
def test_flood_updates_with_resolution_words_remain_context_audit_rows(
    resolved_word: str,
) -> None:
    result = _adapter([_record(comment=f"道路淹水，現場{resolved_word}")]).run()

    assert result.normalized[0].event_type is EventType.STATUS_ONLY
    assert result.fetched[0].payload["incident_state"] == "resolved"


def test_resolution_without_a_flood_keyword_is_not_a_flood_incident() -> None:
    result = _adapter([_record(comment="障礙已排除，恢復通行")]).run()

    assert result.normalized == ()
    assert result.source_rejections == ()


def test_duplicate_uid_selects_only_latest_valid_update_before_validation() -> None:
    older_active = _record(modDttm="2026-08-26 10:16:00", comment="道路淹水")
    latest_resolved = _record(
        modDttm="2026-08-26 10:25:00",
        comment="道路淹水已排除",
    )

    result = _adapter([older_active, latest_resolved]).run()

    assert len(result.fetched) == 1
    assert len(result.normalized) == 1
    assert result.fetched[0].payload["incident_state"] == "resolved"
    assert result.fetched[0].payload["upstream_updated_at"] == (
        "2026-08-26T02:25:00+00:00"
    )


def test_latest_duplicate_validation_failure_does_not_fall_back_to_older_active() -> None:
    older_active = _record(modDttm="2026-08-26 10:16:00", comment="道路淹水")
    latest_invalid = _record(
        modDttm="2026-08-26 10:25:00",
        comment="道路淹水",
        x1="999",
    )

    result = _adapter([older_active, latest_invalid]).run()

    assert result.normalized == ()
    assert result.source_rejections[0].reason_code == (
        "police_radio_coordinates_outside_taiwan"
    )


def test_equal_update_time_tie_break_is_canonical_and_order_independent() -> None:
    active = _record(road="A路", comment="道路淹水")
    resolved = _record(road="Z路", comment="道路淹水已排除")

    forward = _adapter([active, resolved]).run()
    reverse = _adapter([resolved, active]).run()

    assert forward.fetched[0].payload == reverse.fetched[0].payload
    assert forward.fetched[0].payload["incident_state"] == "resolved"


@pytest.mark.parametrize("uid", (None, "", " ", "X" * 513))
def test_missing_blank_or_overlong_uid_is_payload_schema_drift(uid: object) -> None:
    with pytest.raises(PoliceRadioTrafficPayloadError, match="UID"):
        _adapter([_record(UID=uid)]).run()


@pytest.mark.parametrize(
    "payload",
    (
        None,
        {},
        {"data": []},
        {"result": {"records": []}},
        ["not-a-record"],
    ),
)
def test_unknown_root_or_record_schema_is_failure_not_healthy_empty(payload: object) -> None:
    with pytest.raises(PoliceRadioTrafficPayloadError):
        _adapter(payload).run()


def test_hostile_mapping_failure_is_sanitized_without_value_reflection() -> None:
    secret = "hostile-mapping-secret"

    class HostileRecord(UserDict[str, object]):
        def get(self, *_args: object, **_kwargs: object) -> object:
            raise RuntimeError(f"malicious parser state ?token={secret}")

    with pytest.raises(PoliceRadioTrafficPayloadError) as captured:
        _adapter([HostileRecord()]).run()

    rendered = f"{captured.value!s} {captured.value!r}"
    assert secret not in rendered
    assert "?" not in str(captured.value)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def test_explicit_none_fixture_fails_payload_validation_without_calling_fetcher() -> None:
    def forbidden_fetch(_url: str, _timeout_seconds: int) -> object:
        raise AssertionError("explicit fixture payload must not call transport")

    with pytest.raises(PoliceRadioTrafficPayloadError):
        PoliceRadioTrafficAdapter(
            payload=None,
            fetched_at=FETCHED_AT,
            fetch_json=forbidden_fetch,
        ).run()


def test_empty_fixture_pinned_list_is_healthy_no_active_event() -> None:
    result = _adapter([]).run()

    assert result.fetched == ()
    assert result.normalized == ()
    assert result.no_active_event is True


def test_detailed_candidate_rejections_are_globally_bounded_and_deterministic() -> None:
    records = [
        _record(UID=f"RAIN-{index:03d}", comment="豪雨請減速")
        for index in reversed(range(300))
    ]

    result = _adapter(records).run()

    assert len(result.rejected) == 300
    assert len(result.source_rejections) == 256
    assert result.source_rejections[0].source_id == "RAIN-000"
    assert result.source_rejections[-1].source_id == "RAIN-255"


def test_injected_fetcher_receives_only_sanitized_url_and_bounded_timeout() -> None:
    calls: list[tuple[str, int]] = []

    def fetch_json(url: str, timeout_seconds: int) -> object:
        calls.append((url, timeout_seconds))
        return _fixture()

    result = PoliceRadioTrafficAdapter(
        endpoint_url="https://example.test/police/roads",
        timeout_seconds=4,
        fetched_at=FETCHED_AT,
        fetch_json=fetch_json,
    ).run()

    assert len(result.normalized) == 1
    assert calls == [("https://example.test/police/roads", 4)]


def test_injected_fetcher_failure_is_sanitized_without_url_or_exception_reflection() -> None:
    secret = "sensitive-query-value"

    def fail(_url: str, _timeout_seconds: int) -> object:
        raise RuntimeError(f"upstream failed ?token={secret}")

    with pytest.raises(PoliceRadioTrafficFetchError) as captured:
        PoliceRadioTrafficAdapter(fetched_at=FETCHED_AT, fetch_json=fail).run()

    rendered = f"{captured.value!s} {captured.value!r} {vars(captured.value)!r}"
    assert secret not in rendered
    assert "?" not in str(captured.value)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def test_builtin_429_is_attempted_once_and_exposes_only_bounded_cooldown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    headers = Message()
    headers["Retry-After"] = "99999"

    def rate_limited(*_args: Any, **_kwargs: Any) -> object:
        nonlocal calls
        calls += 1
        raise HTTPError(POLICE_RADIO_TRAFFIC_URL, 429, "too many", headers, None)

    monkeypatch.setattr(police_module, "urlopen", rate_limited)

    with pytest.raises(PoliceRadioTrafficRateLimitError) as captured:
        PoliceRadioTrafficAdapter(fetched_at=FETCHED_AT).run()

    assert calls == 1
    assert captured.value.retry_after_seconds == 3600
    assert str(captured.value) == "police-radio traffic returned HTTP 429: [REDACTED]"
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def test_builtin_transport_rejects_overlarge_body(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, size: int) -> bytes:
            assert size == MAX_POLICE_RADIO_RESPONSE_BYTES + 1
            return b"x" * size

    monkeypatch.setattr(police_module, "urlopen", lambda *_args, **_kwargs: Response())

    with pytest.raises(PoliceRadioTrafficFetchError, match="response exceeds"):
        PoliceRadioTrafficAdapter(fetched_at=FETCHED_AT).run()
