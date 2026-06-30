from __future__ import annotations

from app.domain.realtime.local_source_action_plan import build_local_source_action_plan
from app.domain.realtime.local_source_coverage import list_local_source_coverage
from app.domain.realtime.local_source_signal_gap_evidence import (
    build_signal_gap_official_smoke_evidence,
)


def test_signal_gap_evidence_compares_live_smoke_to_remaining_groups() -> None:
    plan = build_local_source_action_plan(list_local_source_coverage())
    smoke_artifact = {
        "schema_version": "official-realtime-live-smoke/v1",
        "captured_at": "2026-06-30T19:45:00+08:00",
        "result": {
            "healthy": True,
            "results": [
                {
                    "adapter_key": "official.civil_iot.pump_water_level",
                    "status": "healthy",
                    "county_counts_by_county": {
                        "\u5609\u7fa9\u5e02": 0,
                        "\u96f2\u6797\u7e23": 2,
                    },
                },
                {
                    "adapter_key": "official.civil_iot.gate_water_level",
                    "status": "healthy",
                    "county_counts_by_county": {
                        "\u96f2\u6797\u7e23": 6,
                    },
                },
                {
                    "adapter_key": "official.civil_iot.sewer_water_level",
                    "status": "healthy",
                    "county_counts_by_county": {
                        "\u9023\u6c5f\u7e23": 0,
                    },
                },
            ],
        },
    }

    evidence = build_signal_gap_official_smoke_evidence(
        plan=plan,
        official_live_smoke_artifact=smoke_artifact,
        captured_at="2026-06-30T20:10:00+08:00",
    )

    assert evidence["schema_version"] == "local-source-signal-gap-evidence/v1"
    assert evidence["captured_at"] == "2026-06-30T20:10:00+08:00"
    assert evidence["official_live_smoke"]["captured_at"] == (
        "2026-06-30T19:45:00+08:00"
    )
    assert evidence["summary"]["signal_group_count"] == 3
    assert evidence["summary"]["target_signal_gap_item_count"] == 17
    assert evidence["summary"]["official_smoke_observed_item_count"] == 0
    assert evidence["summary"]["unresolved_after_official_smoke_item_count"] == 17
    assert evidence["completion_effect"] == "diagnostic_only"

    groups = {group["signal_type"]: group for group in evidence["signal_gap_groups"]}
    pump = groups["pump_or_gate_status"]

    assert pump["accepted_official_adapter_keys"] == [
        "official.civil_iot.pump_water_level",
        "official.civil_iot.gate_water_level",
    ]
    assert pump["official_smoke_observed_counties"] == []
    assert "\u5609\u7fa9\u5e02" in pump["unresolved_counties"]
    assert "\u96f2\u6797\u7e23" not in pump["target_counties"]


def test_signal_gap_evidence_flags_new_official_observations_without_accepting_them() -> None:
    plan = {
        "signal_gap_priority_groups": [
            {
                "signal_type": "pump_or_gate_status",
                "county_count": 2,
                "counties": ["A County", "B County"],
            }
        ]
    }
    smoke_artifact = {
        "result": {
            "results": [
                {
                    "adapter_key": "official.civil_iot.pump_water_level",
                    "status": "healthy",
                    "county_counts_by_county": {"A County": 2},
                }
            ]
        }
    }

    evidence = build_signal_gap_official_smoke_evidence(
        plan=plan,
        official_live_smoke_artifact=smoke_artifact,
        captured_at="2026-06-30T20:15:00+08:00",
    )

    group = evidence["signal_gap_groups"][0]
    by_county = {item["county"]: item for item in group["county_reviews"]}

    assert evidence["summary"]["official_smoke_observed_item_count"] == 1
    assert evidence["summary"]["unresolved_after_official_smoke_item_count"] == 1
    assert group["official_smoke_observed_counties"] == ["A County"]
    assert group["unresolved_counties"] == ["B County"]
    assert by_county["A County"]["status"] == "official_smoke_observed"
    assert by_county["A County"]["observed_official_adapters"] == [
        {
            "adapter_key": "official.civil_iot.pump_water_level",
            "count": 2,
            "smoke_status": "healthy",
        }
    ]
    assert by_county["A County"]["completion_effect"] == "diagnostic_only"
