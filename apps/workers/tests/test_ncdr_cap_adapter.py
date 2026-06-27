from __future__ import annotations

from datetime import UTC, datetime

from app.adapters.contracts import EventType, SourceFamily
from app.adapters.ncdr import NCDR_CAP_METADATA, NcdrCapAlertAdapter
from app.adapters.registry import ADAPTER_REGISTRY, enabled_adapter_keys
from app.config import load_worker_settings
from app.jobs.runtime import build_runtime_adapters


FETCHED_AT = datetime(2026, 6, 15, 3, 10, tzinfo=UTC)


def _json_alert(
    *,
    identifier: str = "NCDR-CAP-001",
    event: str = "豪雨淹水警戒",
    headline: str = "臺南市豪雨淹水警戒",
    description: str = "豪雨造成局部淹水風險升高",
    area_desc: str = "臺南市",
    expires: str = "2026-06-15T15:00:00+08:00",
    geocode_value: str | None = "67000",
    polygon: str | None = None,
) -> dict:
    area: dict[str, object] = {"areaDesc": area_desc}
    if geocode_value is not None:
        area["geocode"] = [{"valueName": "TOWNCODE", "value": geocode_value}]
    if polygon is not None:
        area["polygon"] = polygon
    return {
        "identifier": identifier,
        "sender": "ncdr@example.test",
        "sent": "2026-06-15T02:30:00+08:00",
        "status": "Actual",
        "msgType": "Alert",
        "scope": "Public",
        "info": [
            {
                "event": event,
                "headline": headline,
                "description": description,
                "effective": "2026-06-15T02:30:00+08:00",
                "expires": expires,
                "severity": "Severe",
                "certainty": "Likely",
                "urgency": "Immediate",
                "area": [area],
            }
        ],
    }


def _atom_feed_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:cap="urn:oasis:names:tc:emergency:cap:1.2">
  <title>NCDR CAP feed</title>
  <updated>2026-06-15T03:00:00+08:00</updated>
  <entry>
    <id>NCDR-CAP-ATOM-001</id>
    <title>高雄市淹水警戒</title>
    <updated>2026-06-15T02:55:00+08:00</updated>
    <cap:identifier>NCDR-CAP-ATOM-001</cap:identifier>
    <cap:sender>ncdr@example.test</cap:sender>
    <cap:sent>2026-06-15T02:55:00+08:00</cap:sent>
    <cap:status>Actual</cap:status>
    <cap:msgType>Alert</cap:msgType>
    <cap:scope>Public</cap:scope>
    <cap:event>淹水警戒</cap:event>
    <cap:headline>高雄市淹水警戒</cap:headline>
    <cap:description>豪雨導致局部積淹水</cap:description>
    <cap:effective>2026-06-15T02:55:00+08:00</cap:effective>
    <cap:expires>2026-06-15T16:00:00+08:00</cap:expires>
    <cap:severity>Extreme</cap:severity>
    <cap:certainty>Observed</cap:certainty>
    <cap:urgency>Immediate</cap:urgency>
    <cap:areaDesc>高雄市前鎮區</cap:areaDesc>
    <cap:polygon>22.6100,120.3000 22.6200,120.3200 22.6000,120.3300 22.6100,120.3000</cap:polygon>
    <cap:geocode>
      <valueName>TOWNCODE</valueName>
      <value>640000</value>
    </cap:geocode>
  </entry>
</feed>
"""


def test_ncdr_cap_json_alert_normalizes_flood_warning_and_preserves_payload() -> None:
    adapter = NcdrCapAlertAdapter(
        payload={"alerts": [_json_alert()]},
        fetched_at=FETCHED_AT,
    )

    result = adapter.run()

    assert len(result.fetched) == 1
    assert len(result.normalized) == 1
    evidence = result.normalized[0]
    raw_payload = result.fetched[0].payload
    assert evidence.event_type is EventType.FLOOD_WARNING
    assert evidence.source_family is SourceFamily.OFFICIAL
    assert evidence.source_id == "NCDR-CAP-001"
    assert raw_payload["station_id"] == "67000"
    assert raw_payload["areaDesc"] == "臺南市"
    assert raw_payload["quality_flags"]["location_inferred"] is True
    assert raw_payload["geometry"]["type"] == "Point"
    assert raw_payload["identifier"] == "NCDR-CAP-001"
    assert "精準" not in evidence.summary


def test_ncdr_cap_expired_alert_is_not_normalized() -> None:
    adapter = NcdrCapAlertAdapter(
        payload=[
            _json_alert(
                identifier="NCDR-CAP-EXPIRED",
                expires="2026-06-15T01:00:00+08:00",
            )
        ],
        fetched_at=FETCHED_AT,
    )

    result = adapter.run()

    assert len(result.fetched) == 1
    assert result.normalized == ()
    assert result.rejected == ("NCDR-CAP-EXPIRED",)


def test_ncdr_cap_non_flood_alert_is_ignored() -> None:
    adapter = NcdrCapAlertAdapter(
        payload=[
            _json_alert(
                identifier="NCDR-CAP-QUAKE",
                event="地震速報",
                headline="地震速報",
                description="地震速報",
            )
        ],
        fetched_at=FETCHED_AT,
    )

    result = adapter.run()

    assert len(result.fetched) == 1
    assert result.normalized == ()
    assert result.rejected == ("NCDR-CAP-QUAKE",)


def test_ncdr_cap_atom_feed_uses_polygon_centroid_without_inferred_flag() -> None:
    adapter = NcdrCapAlertAdapter(
        payload=_atom_feed_xml(),
        fetched_at=FETCHED_AT,
    )

    result = adapter.run()

    assert len(result.fetched) == 1
    assert len(result.normalized) == 1
    raw_payload = result.fetched[0].payload
    evidence = result.normalized[0]
    assert evidence.event_type is EventType.FLOOD_WARNING
    assert raw_payload["identifier"] == "NCDR-CAP-ATOM-001"
    assert raw_payload["polygon"].startswith("22.6100,120.3000")
    assert raw_payload["quality_flags"]["location_inferred"] is False
    assert raw_payload["geometry"]["type"] == "Point"
    assert evidence.location_text == "高雄市前鎮區"


def test_ncdr_cap_registry_and_runtime_gates_are_off_by_default() -> None:
    assert ADAPTER_REGISTRY[NCDR_CAP_METADATA.key] is NCDR_CAP_METADATA
    assert NCDR_CAP_METADATA.enabled_by_default is False

    default_settings = load_worker_settings({})
    assert default_settings.source_ncdr_cap_enabled is None
    assert default_settings.source_ncdr_cap_api_enabled is False
    assert "official.ncdr.cap" not in enabled_adapter_keys(default_settings)
    assert build_runtime_adapters(default_settings) == {}

    enabled_settings = load_worker_settings(
        {
            "SOURCE_NCDR_CAP_ENABLED": "true",
            "SOURCE_NCDR_CAP_API_ENABLED": "true",
            "NCDR_CAP_API_URL": "https://example.test/ncdr/cap.atom",
            "NCDR_CAP_TIMEOUT_SECONDS": "6",
        }
    )

    adapters = build_runtime_adapters(
        enabled_settings,
        fetched_at=FETCHED_AT,
        ncdr_cap_fetch_text=lambda url, timeout: _atom_feed_xml(),
    )

    assert tuple(adapters) == ("official.ncdr.cap",)
    assert adapters["official.ncdr.cap"].run().normalized[0].event_type is EventType.FLOOD_WARNING
