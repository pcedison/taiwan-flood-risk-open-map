"""Contract tests for the per-source v1 baseline ingestion runner.

The runner exists because the legacy `--run-enabled-adapters` entry point is
frozen. It runs one isolated cycle per source, which is what makes the reported
runtime selection easy to get wrong: each scoped cycle records only its own key.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from app.adapters.registry import ADAPTER_REGISTRY
from app.cli import runtime_cli
from app.config import load_worker_settings
from app.jobs.runtime_managed import V1_BASELINE_ADAPTER_KEYS

BACKBONE_KEYS = (
    "official.cwa.rainfall",
    "official.cwa.tide_level",
    "official.wra.water_level",
    "official.wra_iow.flood_depth",
    "official.ncdr.cap",
    "official.civil_iot.flood_sensor",
    "official.civil_iot.sewer_water_level",
    "official.civil_iot.pump_water_level",
    "official.civil_iot.gate_water_level",
    "local.tainan.flood_sensor",
)


NON_SCORING_CONTEXT_KEYS = (
    "official.npa.police_radio_traffic",
    "official.wra.flood_warning",
)


def test_every_production_backbone_source_is_in_the_v1_baseline_scope() -> None:
    """The deployed scheduler only runs sources inside this scope.

    A backbone source outside it silently never ingests, no matter how its gates
    or catalog row are set.
    """

    for adapter_key in BACKBONE_KEYS:
        assert adapter_key in V1_BASELINE_ADAPTER_KEYS, adapter_key


def test_no_registered_official_or_local_source_is_silently_left_out() -> None:
    """Drift guard: adding an adapter must be an explicit scope decision.

    Thirty-five local sources were integrated with real endpoints and then never
    ran, because nothing failed when they were absent from this tuple. This test
    is what turns that silence into a failure.
    """

    expected = {
        key
        for key in ADAPTER_REGISTRY
        if key.startswith(("official.", "local."))
        and key not in NON_SCORING_CONTEXT_KEYS
    }
    missing = sorted(expected - set(V1_BASELINE_ADAPTER_KEYS))
    unexpected = sorted(set(V1_BASELINE_ADAPTER_KEYS) - expected)

    assert missing == [], f"registered but unreachable by the runner: {missing}"
    assert unexpected == [], f"in scope but not a registered official/local source: {unexpected}"


def test_all_local_government_sources_are_reachable() -> None:
    local_registered = sorted(k for k in ADAPTER_REGISTRY if k.startswith("local."))
    local_in_scope = sorted(k for k in V1_BASELINE_ADAPTER_KEYS if k.startswith("local."))

    assert local_in_scope == local_registered
    assert len(local_in_scope) >= 36


def test_context_sources_stay_outside_the_v1_baseline_scope() -> None:
    for adapter_key in (
        "official.npa.police_radio_traffic",
        "official.wra.flood_warning",
    ):
        assert adapter_key not in V1_BASELINE_ADAPTER_KEYS, adapter_key


def test_tick_reports_every_source_it_ran_not_just_the_last_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: scoped cycles must not report each other as disabled.

    `write_runtime_selection` sets `runtime_enabled = false` for every known
    adapter outside `enabled_adapter_keys`. Because each scoped cycle passes only
    its own key, the tick must re-record the real selection for the whole tick or
    the public API reports every live source except the last one as
    "background worker recently reported this source as disabled".
    """

    ran = ["official.cwa.rainfall", "official.wra.water_level"]
    recorded: list[dict[str, Any]] = []

    class _Adapter:
        def __init__(self, key: str) -> None:
            self.metadata = type("M", (), {"key": key})()

    def fake_build(settings: Any, **_kwargs: Any) -> dict[str, Any]:
        key = settings.enabled_adapter_keys[0]
        return {key: _Adapter(key)} if key in ran else {}

    def fake_cycle(adapter_by_key: Any, **_kwargs: Any) -> Any:
        return type(
            "R",
            (),
            {"failed": False, "has_alerts": False, "status": "succeeded", "reason": None, "promoted": 0},
        )()

    def fake_record(_writer: Any, *, enabled_adapter_keys: Any, known_adapter_keys: Any) -> None:
        recorded.append(
            {"enabled": tuple(enabled_adapter_keys), "known": tuple(known_adapter_keys)}
        )

    monkeypatch.setattr(runtime_cli, "build_runtime_adapters", fake_build)
    monkeypatch.setattr(runtime_cli, "run_v1_baseline_adapter_cycle", fake_cycle)
    monkeypatch.setattr(runtime_cli, "record_runtime_selection", fake_record)
    monkeypatch.setattr(runtime_cli, "PostgresIngestionRunWriter", lambda **_kwargs: object())
    monkeypatch.setattr(
        runtime_cli, "v1_baseline_eligible_adapter_keys", lambda _settings: tuple(ran)
    )

    settings = replace(load_worker_settings({}), enabled_adapter_keys=tuple(ran))
    failed = runtime_cli._run_v1_baseline_tick(
        settings=settings,
        database_url="postgresql://example.test/flood",
        job_key="test",
    )

    assert failed is False
    assert recorded, "the tick must re-record the runtime selection"
    final = recorded[-1]
    assert final["enabled"] == tuple(ran)
    assert final["known"] == tuple(ADAPTER_REGISTRY)


def test_tick_records_nothing_when_no_source_ran(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: list[Any] = []
    monkeypatch.setattr(runtime_cli, "build_runtime_adapters", lambda *_a, **_k: {})
    monkeypatch.setattr(
        runtime_cli, "record_runtime_selection", lambda *a, **k: recorded.append(k)
    )
    monkeypatch.setattr(
        runtime_cli, "v1_baseline_eligible_adapter_keys", lambda _settings: ("official.cwa.rainfall",)
    )

    failed = runtime_cli._run_v1_baseline_tick(
        settings=load_worker_settings({}),
        database_url="postgresql://example.test/flood",
        job_key="test",
    )

    assert failed is False
    assert recorded == []
