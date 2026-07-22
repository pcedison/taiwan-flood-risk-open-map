from __future__ import annotations

from collections.abc import Mapping
from typing import Any


SCHEMA_VERSION = "local-source-signal-gap-evidence/v1"
COMPLETION_EFFECT = "diagnostic_only"

ACCEPTED_OFFICIAL_ADAPTER_KEYS_BY_SIGNAL_TYPE = {
    "flood_depth": (
        "official.wra_iow.flood_depth",
        "official.civil_iot.flood_sensor",
    ),
    "sewer_water_level": ("official.civil_iot.sewer_water_level",),
    "pump_or_gate_status": (
        "official.civil_iot.pump_water_level",
        "official.civil_iot.gate_water_level",
    ),
}


def build_signal_gap_official_smoke_evidence(
    *,
    plan: Mapping[str, Any],
    official_live_smoke_artifact: Mapping[str, Any],
    captured_at: str,
) -> dict[str, Any]:
    """Compare unresolved signal gaps with the latest official live-smoke counts."""

    smoke_result = _official_live_smoke_result(official_live_smoke_artifact)
    smoke_results_by_adapter = _smoke_results_by_adapter(smoke_result)
    groups = [
        _signal_group_evidence(group, smoke_results_by_adapter=smoke_results_by_adapter)
        for group in plan.get("signal_gap_priority_groups", [])
        if isinstance(group, Mapping)
    ]
    summary = _summary(groups)
    return {
        "schema_version": SCHEMA_VERSION,
        "captured_at": captured_at,
        "completion_effect": COMPLETION_EFFECT,
        "completion_note": (
            "Official live-smoke observations are discovery evidence only. "
            "They do not close completion gates until the catalog, adapter "
            "path, source contract, and production evidence are accepted."
        ),
        "official_live_smoke": {
            "schema_version": official_live_smoke_artifact.get("schema_version"),
            "captured_at": official_live_smoke_artifact.get("captured_at"),
            "healthy": smoke_result.get("healthy"),
        },
        "summary": summary,
        "signal_gap_groups": groups,
    }


def _signal_group_evidence(
    group: Mapping[str, Any],
    *,
    smoke_results_by_adapter: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    signal_type = str(group.get("signal_type", ""))
    target_counties = tuple(str(county) for county in group.get("counties", []))
    adapter_keys = ACCEPTED_OFFICIAL_ADAPTER_KEYS_BY_SIGNAL_TYPE.get(signal_type, ())
    county_reviews = [
        _county_review(
            county,
            adapter_keys=adapter_keys,
            smoke_results_by_adapter=smoke_results_by_adapter,
        )
        for county in target_counties
    ]
    observed_counties = [
        review["county"]
        for review in county_reviews
        if review["status"] == "official_smoke_observed"
    ]
    unresolved_counties = [
        review["county"]
        for review in county_reviews
        if review["status"] == "unresolved_after_official_smoke"
    ]
    return {
        "signal_type": signal_type,
        "target_county_count": len(target_counties),
        "target_counties": list(target_counties),
        "accepted_official_adapter_keys": list(adapter_keys),
        "official_smoke_observed_county_count": len(observed_counties),
        "official_smoke_observed_counties": observed_counties,
        "unresolved_county_count": len(unresolved_counties),
        "unresolved_counties": unresolved_counties,
        "county_reviews": county_reviews,
        "completion_effect": COMPLETION_EFFECT,
    }


def _county_review(
    county: str,
    *,
    adapter_keys: tuple[str, ...],
    smoke_results_by_adapter: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    observed_adapters: list[dict[str, Any]] = []
    for adapter_key in adapter_keys:
        result = smoke_results_by_adapter.get(adapter_key)
        if result is None or result.get("status") != "healthy":
            continue
        count = _county_count(result, county)
        if count <= 0:
            continue
        observed_adapters.append(
            {
                "adapter_key": adapter_key,
                "count": count,
                "smoke_status": result.get("status"),
            }
        )
    return {
        "county": county,
        "status": (
            "official_smoke_observed"
            if observed_adapters
            else "unresolved_after_official_smoke"
        ),
        "observed_official_adapters": observed_adapters,
        "completion_effect": COMPLETION_EFFECT,
    }


def _official_live_smoke_result(artifact: Mapping[str, Any]) -> Mapping[str, Any]:
    result = artifact.get("result")
    return result if isinstance(result, Mapping) else artifact


def _smoke_results_by_adapter(
    smoke_result: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    results = smoke_result.get("results")
    if not isinstance(results, list):
        return {}
    by_adapter: dict[str, Mapping[str, Any]] = {}
    for item in results:
        if not isinstance(item, Mapping):
            continue
        adapter_key = item.get("adapter_key")
        if isinstance(adapter_key, str) and adapter_key:
            by_adapter[adapter_key] = item
    return by_adapter


def _county_count(result: Mapping[str, Any], county: str) -> int:
    counts = result.get("county_counts_by_county")
    if not isinstance(counts, Mapping):
        return 0
    value = counts.get(county)
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return 0


def _summary(groups: list[dict[str, Any]]) -> dict[str, Any]:
    target_count = sum(int(group["target_county_count"]) for group in groups)
    observed_count = sum(
        int(group["official_smoke_observed_county_count"]) for group in groups
    )
    unresolved_count = sum(int(group["unresolved_county_count"]) for group in groups)
    return {
        "signal_group_count": len(groups),
        "target_signal_gap_item_count": target_count,
        "official_smoke_observed_item_count": observed_count,
        "unresolved_after_official_smoke_item_count": unresolved_count,
    }
