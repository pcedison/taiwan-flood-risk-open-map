"""Contract tests for the per-source v1 baseline ingestion runner.

The runner exists because the legacy `--run-enabled-adapters` entry point is
frozen. It runs one isolated cycle per source while reporting the authoritative
whole-tick selection without widening any scoped source operation.
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest

from app.adapters.registry import ADAPTER_REGISTRY
from app.cli import runtime_cli
from app.config import load_worker_settings
from app.jobs import runtime_managed
from app.jobs.runtime_managed import (
    V1_BASELINE_ADAPTER_KEYS,
    ManagedRuntimeIngestionResult,
)

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

SOURCE_A = "official.cwa.rainfall"
SOURCE_B = "official.wra.water_level"


class _Adapter:
    def __init__(self, key: str) -> None:
        self.metadata = SimpleNamespace(key=key)


class _RunWriter:
    def __init__(self, timeline: list[tuple[str, object]] | None = None) -> None:
        self.timeline = timeline if timeline is not None else []
        self.pipeline_statuses: list[dict[str, object]] = []

    def write_runtime_selection(
        self,
        *,
        enabled_adapter_keys: tuple[str, ...],
        known_adapter_keys: tuple[str, ...],
        checked_at: object,
    ) -> None:
        del known_adapter_keys, checked_at
        self.timeline.append(("selection", enabled_adapter_keys))

    def write_pipeline_status(self, **fields: object) -> None:
        self.pipeline_statuses.append(fields)


def _install_tick_writer(
    monkeypatch: pytest.MonkeyPatch,
    *,
    timeline: list[tuple[str, object]] | None = None,
) -> _RunWriter:
    writer = _RunWriter(timeline)
    monkeypatch.setattr(
        runtime_cli,
        "PostgresIngestionRunWriter",
        lambda **_kwargs: writer,
    )
    return writer


def _tick_result(status: str = "succeeded") -> ManagedRuntimeIngestionResult:
    return ManagedRuntimeIngestionResult(
        status=status,  # type: ignore[arg-type]
        error_code="TimeoutError" if status == "failed" else None,
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


def test_tick_reports_every_runnable_source_not_just_the_last_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: scoped cycles must not report each other as disabled.

    `write_runtime_selection` sets `runtime_enabled = false` for every known
    adapter outside `enabled_adapter_keys`. The tick must preflight and record
    the whole runnable selection before scoped cycles begin, or the public API
    can report peers as disabled while they are still running.
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
    assert recorded, "the tick must record the authoritative runtime selection"
    final = recorded[-1]
    assert final["enabled"] == tuple(ran)
    assert final["known"] == tuple(ADAPTER_REGISTRY)


def test_tick_records_empty_selection_when_no_source_is_runnable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    assert recorded[0]["enabled_adapter_keys"] == ()


def test_tick_continues_when_first_adapter_builder_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built: list[str] = []
    ran: list[str] = []
    events: list[tuple[str, dict[str, object]]] = []
    writer = _install_tick_writer(monkeypatch)

    def fake_build(settings: Any) -> dict[str, _Adapter]:
        adapter_key = settings.enabled_adapter_keys[0]
        built.append(adapter_key)
        if adapter_key == SOURCE_A:
            raise RuntimeError("private-builder-detail")
        return {adapter_key: _Adapter(adapter_key)}

    def fake_cycle(adapter_by_key: Any, **_kwargs: Any) -> Any:
        ran.extend(adapter_by_key)
        return _tick_result()

    monkeypatch.setattr(runtime_cli, "build_runtime_adapters", fake_build)
    monkeypatch.setattr(runtime_cli, "run_v1_baseline_adapter_cycle", fake_cycle)
    monkeypatch.setattr(
        runtime_cli,
        "v1_baseline_eligible_adapter_keys",
        lambda _settings: (SOURCE_A, SOURCE_B),
    )
    monkeypatch.setattr(
        runtime_cli,
        "log_event",
        lambda event, **fields: events.append((event, fields)),
    )

    failed = runtime_cli._run_v1_baseline_tick(
        settings=replace(
            load_worker_settings({}),
            enabled_adapter_keys=(SOURCE_A, SOURCE_B),
        ),
        database_url="postgresql://example.test/flood",
        job_key="test",
    )

    assert failed is True
    assert built == [SOURCE_A, SOURCE_B]
    assert ran == [SOURCE_B]
    assert writer.pipeline_statuses[0]["adapter_keys"] == (SOURCE_A,)
    assert writer.pipeline_statuses[0]["status"] == "failed"
    assert writer.pipeline_statuses[0]["complete"] is False
    assert "private-builder-detail" not in repr(events)
    assert (
        "worker.runtime.v1_baseline.source_failed",
        {
            "adapter_key": SOURCE_A,
            "phase": "adapter_construction",
            "exception_class": "RuntimeError",
        },
    ) in events
    tick_fields = next(
        fields
        for event, fields in events
        if event == "worker.runtime.v1_baseline.tick_completed"
    )
    assert tick_fields["configured_count"] == 2
    assert tick_fields["runnable_count"] == 1
    assert tick_fields["completed_count"] == 1
    assert tick_fields["failed_count"] == 1
    assert tick_fields["gated_off_count"] == 0
    assert isinstance(tick_fields["elapsed_ms"], int)
    assert tick_fields["elapsed_ms"] >= 0
    completed_fields = next(
        fields
        for event, fields in events
        if event == "worker.runtime.v1_baseline.source_completed"
    )
    assert isinstance(completed_fields["elapsed_ms"], int)
    assert completed_fields["elapsed_ms"] >= 0


def test_tick_continues_when_first_source_cycle_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ran: list[str] = []
    events: list[tuple[str, dict[str, object]]] = []
    writer = _install_tick_writer(monkeypatch)

    def fake_build(settings: Any) -> dict[str, _Adapter]:
        adapter_key = settings.enabled_adapter_keys[0]
        return {adapter_key: _Adapter(adapter_key)}

    def fake_cycle(adapter_by_key: Any, **_kwargs: Any) -> Any:
        adapter_key = next(iter(adapter_by_key))
        ran.append(adapter_key)
        if adapter_key == SOURCE_A:
            raise TimeoutError("private-cycle-detail")
        return _tick_result()

    monkeypatch.setattr(runtime_cli, "build_runtime_adapters", fake_build)
    monkeypatch.setattr(runtime_cli, "run_v1_baseline_adapter_cycle", fake_cycle)
    monkeypatch.setattr(
        runtime_cli,
        "v1_baseline_eligible_adapter_keys",
        lambda _settings: (SOURCE_A, SOURCE_B),
    )
    monkeypatch.setattr(
        runtime_cli,
        "log_event",
        lambda event, **fields: events.append((event, fields)),
    )

    failed = runtime_cli._run_v1_baseline_tick(
        settings=replace(
            load_worker_settings({}),
            enabled_adapter_keys=(SOURCE_A, SOURCE_B),
        ),
        database_url="postgresql://example.test/flood",
        job_key="test",
    )

    assert failed is True
    assert ran == [SOURCE_A, SOURCE_B]
    assert writer.pipeline_statuses[0]["adapter_keys"] == (SOURCE_A,)
    assert "private-cycle-detail" not in repr(events)
    failed_fields = next(
        fields
        for event, fields in events
        if event == "worker.runtime.v1_baseline.source_failed"
        and fields["adapter_key"] == SOURCE_A
    )
    assert failed_fields["phase"] == "managed_cycle"
    assert failed_fields["exception_class"] == "TimeoutError"
    assert isinstance(failed_fields["elapsed_ms"], int)
    assert failed_fields["elapsed_ms"] >= 0


def test_source_audit_failure_is_public_safe_and_does_not_stop_next_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ran: list[str] = []
    events: list[tuple[str, dict[str, object]]] = []
    writer = _install_tick_writer(monkeypatch)

    def fail_audit(**_fields: object) -> None:
        raise RuntimeError("private-audit-detail")

    writer.write_pipeline_status = fail_audit  # type: ignore[method-assign]

    def fake_build(settings: Any) -> dict[str, _Adapter]:
        adapter_key = settings.enabled_adapter_keys[0]
        if adapter_key == SOURCE_A:
            raise RuntimeError("private-builder-detail")
        return {adapter_key: _Adapter(adapter_key)}

    def fake_cycle(adapter_by_key: Any, **_kwargs: Any) -> Any:
        ran.extend(adapter_by_key)
        return _tick_result()

    monkeypatch.setattr(runtime_cli, "build_runtime_adapters", fake_build)
    monkeypatch.setattr(runtime_cli, "run_v1_baseline_adapter_cycle", fake_cycle)
    monkeypatch.setattr(
        runtime_cli,
        "v1_baseline_eligible_adapter_keys",
        lambda _settings: (SOURCE_A, SOURCE_B),
    )
    monkeypatch.setattr(
        runtime_cli,
        "log_event",
        lambda event, **fields: events.append((event, fields)),
    )

    failed = runtime_cli._run_v1_baseline_tick(
        settings=replace(
            load_worker_settings({}),
            enabled_adapter_keys=(SOURCE_A, SOURCE_B),
        ),
        database_url="postgresql://example.test/flood",
        job_key="test",
    )

    assert failed is True
    assert ran == [SOURCE_B]
    assert "private-audit-detail" not in repr(events)
    assert any(
        event == "worker.runtime.v1_baseline.audit_unavailable"
        and fields == {
            "adapter_key": SOURCE_A,
            "exception_class": "RuntimeError",
        }
        for event, fields in events
    )


def test_tick_continues_when_first_source_returns_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ran: list[str] = []
    events: list[tuple[str, dict[str, object]]] = []
    writer = _install_tick_writer(monkeypatch)

    def fake_build(settings: Any) -> dict[str, _Adapter]:
        adapter_key = settings.enabled_adapter_keys[0]
        return {adapter_key: _Adapter(adapter_key)}

    def fake_cycle(adapter_by_key: Any, **_kwargs: Any) -> Any:
        adapter_key = next(iter(adapter_by_key))
        ran.append(adapter_key)
        return _tick_result("failed" if adapter_key == SOURCE_A else "succeeded")

    monkeypatch.setattr(runtime_cli, "build_runtime_adapters", fake_build)
    monkeypatch.setattr(runtime_cli, "run_v1_baseline_adapter_cycle", fake_cycle)
    monkeypatch.setattr(
        runtime_cli,
        "v1_baseline_eligible_adapter_keys",
        lambda _settings: (SOURCE_A, SOURCE_B),
    )
    monkeypatch.setattr(
        runtime_cli,
        "log_event",
        lambda event, **fields: events.append((event, fields)),
    )

    failed = runtime_cli._run_v1_baseline_tick(
        settings=replace(
            load_worker_settings({}),
            enabled_adapter_keys=(SOURCE_A, SOURCE_B),
        ),
        database_url="postgresql://example.test/flood",
        job_key="test",
    )

    assert failed is True
    assert ran == [SOURCE_A, SOURCE_B]
    assert writer.pipeline_statuses[0]["adapter_keys"] == (SOURCE_A,)
    tick_fields = next(
        fields
        for event, fields in events
        if event == "worker.runtime.v1_baseline.tick_completed"
    )
    assert tick_fields["completed_count"] == 1
    assert tick_fields["failed_count"] == 1
    failed_fields = next(
        fields
        for event, fields in events
        if event == "worker.runtime.v1_baseline.source_failed"
        and fields["adapter_key"] == SOURCE_A
    )
    assert failed_fields["phase"] == "managed_cycle"
    assert failed_fields["exception_class"] == "TimeoutError"
    assert isinstance(failed_fields["elapsed_ms"], int)
    assert failed_fields["elapsed_ms"] >= 0


def test_tick_records_full_selection_before_first_source_starts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timeline: list[tuple[str, object]] = []
    _install_tick_writer(monkeypatch, timeline=timeline)

    def fake_build(settings: Any) -> dict[str, _Adapter]:
        adapter_key = settings.enabled_adapter_keys[0]
        return {adapter_key: _Adapter(adapter_key)}

    def fake_cycle(adapter_by_key: Any, **_kwargs: Any) -> Any:
        timeline.append(("cycle", next(iter(adapter_by_key))))
        return _tick_result()

    def capture_event(event: str, **fields: object) -> None:
        if event == "worker.runtime.v1_baseline.source_started":
            timeline.append(("source_started", fields["adapter_key"]))

    monkeypatch.setattr(runtime_cli, "build_runtime_adapters", fake_build)
    monkeypatch.setattr(runtime_cli, "run_v1_baseline_adapter_cycle", fake_cycle)
    monkeypatch.setattr(
        runtime_cli,
        "v1_baseline_eligible_adapter_keys",
        lambda _settings: (SOURCE_A, SOURCE_B),
    )
    monkeypatch.setattr(runtime_cli, "log_event", capture_event)

    failed = runtime_cli._run_v1_baseline_tick(
        settings=replace(
            load_worker_settings({}),
            enabled_adapter_keys=(SOURCE_A, SOURCE_B),
        ),
        database_url="postgresql://example.test/flood",
        job_key="test",
    )

    assert failed is False
    assert timeline[0] == ("selection", (SOURCE_A, SOURCE_B))
    assert timeline[1] == ("source_started", SOURCE_A)


def test_every_scoped_cycle_reports_the_same_full_tick_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reported: list[tuple[str, ...] | None] = []
    _install_tick_writer(monkeypatch)

    def fake_build(settings: Any) -> dict[str, _Adapter]:
        adapter_key = settings.enabled_adapter_keys[0]
        return {adapter_key: _Adapter(adapter_key)}

    def fake_cycle(_adapter_by_key: Any, **kwargs: Any) -> Any:
        reported.append(kwargs.get("runtime_selection_adapter_keys"))
        return _tick_result()

    monkeypatch.setattr(runtime_cli, "build_runtime_adapters", fake_build)
    monkeypatch.setattr(runtime_cli, "run_v1_baseline_adapter_cycle", fake_cycle)
    monkeypatch.setattr(
        runtime_cli,
        "v1_baseline_eligible_adapter_keys",
        lambda _settings: (SOURCE_A, SOURCE_B),
    )
    monkeypatch.setattr(runtime_cli, "log_event", lambda *_args, **_kwargs: None)

    failed = runtime_cli._run_v1_baseline_tick(
        settings=replace(
            load_worker_settings({}),
            enabled_adapter_keys=(SOURCE_A, SOURCE_B),
        ),
        database_url="postgresql://example.test/flood",
        job_key="test",
    )

    assert failed is False
    assert reported == [
        (SOURCE_A, SOURCE_B),
        (SOURCE_A, SOURCE_B),
    ]


def test_tick_preflight_excludes_catalog_disabled_and_gate_off_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog_disabled = "official.ncdr.cap"
    gate_off = "official.cwa.tide_level"
    built: list[str] = []
    reported: list[tuple[str, ...] | None] = []
    writer = _install_tick_writer(monkeypatch)

    def fake_catalog_filter(
        adapter_keys: tuple[str, ...],
        *,
        source_catalog_reader: object,
    ) -> tuple[str, ...]:
        del source_catalog_reader
        assert adapter_keys == (catalog_disabled, SOURCE_A, gate_off)
        return (SOURCE_A, gate_off)

    def fake_build(settings: Any) -> dict[str, _Adapter]:
        adapter_key = settings.enabled_adapter_keys[0]
        built.append(adapter_key)
        return {} if adapter_key == gate_off else {adapter_key: _Adapter(adapter_key)}

    def fake_cycle(_adapter_by_key: Any, **kwargs: Any) -> Any:
        reported.append(kwargs.get("runtime_selection_adapter_keys"))
        return _tick_result()

    monkeypatch.setattr(
        runtime_cli,
        "filter_catalog_enabled_adapter_keys",
        fake_catalog_filter,
    )
    monkeypatch.setattr(
        runtime_cli,
        "resolve_source_catalog_reader",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(runtime_cli, "build_runtime_adapters", fake_build)
    monkeypatch.setattr(runtime_cli, "run_v1_baseline_adapter_cycle", fake_cycle)
    monkeypatch.setattr(
        runtime_cli,
        "v1_baseline_eligible_adapter_keys",
        lambda _settings: (catalog_disabled, SOURCE_A, gate_off),
    )
    monkeypatch.setattr(runtime_cli, "log_event", lambda *_args, **_kwargs: None)

    failed = runtime_cli._run_v1_baseline_tick(
        settings=replace(
            load_worker_settings({}),
            enabled_adapter_keys=(catalog_disabled, SOURCE_A, gate_off),
        ),
        database_url="postgresql://example.test/flood",
        job_key="test",
    )

    assert failed is False
    assert built == [SOURCE_A, gate_off]
    assert writer.timeline == [("selection", (SOURCE_A,))]
    assert reported == [(SOURCE_A,)]


def test_runtime_selection_override_cannot_widen_staging_or_promotion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_execute(adapter_by_key: Any, **kwargs: Any) -> Any:
        captured["adapter_keys"] = tuple(adapter_by_key)
        captured.update(kwargs)
        return _tick_result()

    monkeypatch.setattr(
        runtime_managed,
        "_execute_managed_runtime_ingestion_cycle",
        fake_execute,
    )
    scoped_settings = replace(
        load_worker_settings({}),
        enabled_adapter_keys=(SOURCE_A,),
    )

    result = runtime_managed.run_v1_baseline_adapter_cycle(
        {SOURCE_A: _Adapter(SOURCE_A)},
        settings=scoped_settings,
        promote=True,
        promotion_adapter_keys=(SOURCE_A,),
        runtime_selection_adapter_keys=(SOURCE_A, SOURCE_B),
    )

    assert result.status == "succeeded"
    assert captured["adapter_keys"] == (SOURCE_A,)
    assert captured["settings"] == scoped_settings
    assert captured["promotion_adapter_keys"] == (SOURCE_A,)
    assert captured["runtime_selection_adapter_keys"] == (SOURCE_A, SOURCE_B)


def test_runtime_selection_override_rejects_unknown_or_gate_off_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []
    monkeypatch.setattr(
        runtime_managed,
        "_execute_managed_runtime_ingestion_cycle",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    scoped_settings = replace(
        load_worker_settings({}),
        enabled_adapter_keys=(SOURCE_A,),
    )

    unknown = runtime_managed.run_v1_baseline_adapter_cycle(
        {SOURCE_A: _Adapter(SOURCE_A)},
        settings=scoped_settings,
        runtime_selection_adapter_keys=(SOURCE_A, "news.public_web.sample"),
    )
    missing_scoped = runtime_managed.run_v1_baseline_adapter_cycle(
        {SOURCE_A: _Adapter(SOURCE_A)},
        settings=scoped_settings,
        runtime_selection_adapter_keys=(SOURCE_B,),
    )
    empty = runtime_managed.run_v1_baseline_adapter_cycle(
        {SOURCE_A: _Adapter(SOURCE_A)},
        settings=scoped_settings,
        runtime_selection_adapter_keys=(),
    )

    assert unknown.reason == "invalid_v1_baseline_scope"
    assert missing_scoped.reason == "invalid_v1_baseline_scope"
    assert empty.reason == "invalid_v1_baseline_scope"
    assert calls == []
