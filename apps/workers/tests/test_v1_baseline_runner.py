"""Contract tests for the per-source v1 baseline ingestion runner.

The runner exists because the legacy `--run-enabled-adapters` entry point is
frozen. It runs one isolated cycle per source while reporting the authoritative
whole-tick selection without widening any scoped source operation.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import signal
from types import SimpleNamespace
from typing import Any

import pytest

from app.adapters.registry import ADAPTER_REGISTRY
from app.cli import runtime_cli
from app.config import load_worker_settings
from app.jobs import runtime_managed
from app.jobs.freshness import FreshnessCheck
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
    "official.wra.historical_flood",
    "official.nstc.flood_disaster_points",
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


@pytest.fixture(autouse=True)
def _catalog_passes_requested_test_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit tick tests isolate scheduler behavior from a real PostgreSQL catalog."""

    monkeypatch.setattr(
        runtime_cli,
        "filter_catalog_enabled_adapter_keys",
        lambda adapter_keys, **_kwargs: adapter_keys,
    )


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


def test_scheduler_sigterm_unwinds_and_releases_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    previous_handler = object()

    class _Queue:
        def __init__(self, *, database_url: str) -> None:
            captured["database_url"] = database_url

        def acquire_scheduler_lease(self, **fields: object) -> bool:
            captured["acquired"] = fields
            return True

        def release_scheduler_lease(self, **fields: object) -> None:
            captured["released"] = fields

    def fake_signal(sig: signal.Signals, handler: object) -> object:
        calls = captured.setdefault("signal_calls", [])
        assert isinstance(calls, list)
        calls.append((sig, handler))
        captured["active_handler"] = handler
        return previous_handler

    def terminate_tick(**_fields: object) -> bool:
        handler = captured["active_handler"]
        assert callable(handler)
        handler(signal.SIGTERM, None)
        raise AssertionError("SIGTERM handler returned")

    monkeypatch.setattr(runtime_cli, "PostgresRuntimeQueue", _Queue)
    monkeypatch.setattr(runtime_cli.signal, "signal", fake_signal)
    monkeypatch.setattr(runtime_cli, "_run_v1_baseline_tick", terminate_tick)

    settings = replace(
        load_worker_settings({}),
        database_url="postgresql://example.test/flood",
    )
    with pytest.raises(SystemExit) as raised:
        runtime_cli.run_v1_baseline_enabled_adapters(
            settings=settings,
            database_url=None,
            scheduler=True,
            once=False,
            max_ticks=None,
        )

    assert raised.value.code == 0
    acquired = captured["acquired"]
    released = captured["released"]
    assert isinstance(acquired, dict)
    assert isinstance(released, dict)
    assert released["lease_key"] == acquired["lease_key"]
    assert released["holder_id"] == acquired["holder_id"]
    signal_calls = captured["signal_calls"]
    assert isinstance(signal_calls, list)
    assert signal_calls[0] == (signal.SIGTERM, runtime_cli._exit_scheduler_on_sigterm)
    assert signal_calls[-1] == (signal.SIGTERM, previous_handler)


def test_scheduler_runs_static_source_on_first_tick_then_defers_until_daily_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_runs: list[frozenset[str]] = []
    maintenance_databases: list[str | None] = []
    sleeps: list[float] = []
    static_key = "official.wra.historical_flood"

    class _Queue:
        def __init__(self, *, database_url: str) -> None:
            assert database_url == "postgresql://example.test/flood"

        def acquire_scheduler_lease(self, **_fields: object) -> bool:
            return True

        def release_scheduler_lease(self, **_fields: object) -> bool:
            return True

    class _Heartbeat:
        lost = False

        def __init__(self, **_fields: object) -> None:
            pass

        def __enter__(self) -> "_Heartbeat":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    def fake_tick(**fields: object) -> bool:
        captured_runs.append(fields["adapter_keys_to_run"])  # type: ignore[arg-type]
        return False

    def fake_maintenance(**fields: object) -> SimpleNamespace:
        settings = fields["settings"]
        maintenance_databases.append(getattr(settings, "database_url", None))
        return SimpleNamespace(failed=False, reason=None)

    monotonic_values = iter((0.0, 120.0, 300.0))
    monkeypatch.setattr(runtime_cli, "PostgresRuntimeQueue", _Queue)
    monkeypatch.setattr(runtime_cli, "_SchedulerLeaseHeartbeat", _Heartbeat)
    monkeypatch.setattr(runtime_cli, "_run_v1_baseline_tick", fake_tick)
    monkeypatch.setattr(
        runtime_cli,
        "run_maintenance_once",
        fake_maintenance,
    )
    monkeypatch.setattr(
        runtime_cli,
        "v1_baseline_eligible_adapter_keys",
        lambda _settings: (SOURCE_A, static_key),
    )
    monkeypatch.setattr(runtime_cli.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(runtime_cli.time, "sleep", sleeps.append)
    monkeypatch.setattr(runtime_cli.signal, "signal", lambda _sig, _handler: object())

    exit_code = runtime_cli.run_v1_baseline_enabled_adapters(
        settings=replace(
            load_worker_settings({}),
            database_url="postgresql://example.test/flood",
        ),
        database_url=None,
        scheduler=True,
        once=False,
        max_ticks=2,
    )

    assert exit_code == 0
    assert captured_runs == [
        frozenset({SOURCE_A, static_key}),
        frozenset({SOURCE_A}),
    ]
    assert maintenance_databases == [
        "postgresql://example.test/flood",
        "postgresql://example.test/flood",
    ]
    assert sleeps == [180.0]


def test_scheduler_starts_next_tick_immediately_after_interval_overrun() -> None:
    assert runtime_cli._remaining_scheduler_sleep_seconds(
        interval_seconds=300,
        tick_started_at=100.0,
        now=401.0,
    ) == 0.0


def test_deferred_static_source_stays_in_authoritative_runtime_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    static_key = "official.wra.historical_flood"
    built: list[str] = []
    writer = _install_tick_writer(monkeypatch)

    monkeypatch.setattr(
        runtime_cli,
        "v1_baseline_eligible_adapter_keys",
        lambda _settings: (SOURCE_A, static_key),
    )
    monkeypatch.setattr(
        runtime_cli,
        "filter_catalog_enabled_adapter_keys",
        lambda keys, **_kwargs: keys,
    )

    def fake_build(settings: Any) -> dict[str, _Adapter]:
        key = settings.enabled_adapter_keys[0]
        built.append(key)
        return {key: _Adapter(key)}

    monkeypatch.setattr(runtime_cli, "build_runtime_adapters", fake_build)
    monkeypatch.setattr(
        runtime_cli,
        "run_v1_baseline_adapter_cycle",
        lambda *_args, **_kwargs: _tick_result(),
    )
    monkeypatch.setattr(runtime_cli, "log_event", lambda *_args, **_kwargs: None)

    failed = runtime_cli._run_v1_baseline_tick(
        settings=replace(
            load_worker_settings({}),
            enabled_adapter_keys=(SOURCE_A, static_key),
        ),
        database_url="postgresql://example.test/flood",
        job_key="test",
        adapter_keys_to_run=frozenset({SOURCE_A}),
    )

    assert failed is False
    assert built == [SOURCE_A]
    assert writer.timeline == [("selection", (SOURCE_A, static_key))]


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
    cycle_selection_revision_flags: list[bool] = []

    class _Adapter:
        def __init__(self, key: str) -> None:
            self.metadata = type("M", (), {"key": key})()

    def fake_build(settings: Any, **_kwargs: Any) -> dict[str, Any]:
        key = settings.enabled_adapter_keys[0]
        return {key: _Adapter(key)} if key in ran else {}

    def fake_cycle(adapter_by_key: Any, **kwargs: Any) -> Any:
        cycle_selection_revision_flags.append(
            bool(kwargs.get("write_runtime_selection_revision", True))
        )
        return type(
            "R",
            (),
            {
                "failed": False,
                "has_alerts": False,
                "freshness_alerts": (),
                "status": "succeeded",
                "reason": None,
                "promoted": 0,
            },
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
    assert recorded == [
        {"enabled": tuple(ran), "known": tuple(ADAPTER_REGISTRY)}
    ]
    assert cycle_selection_revision_flags == [False, False]


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
    assert writer.timeline == [("selection", (SOURCE_A, SOURCE_B))]
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


def test_successful_historical_source_updates_county_year_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter_key = "official.nstc.flood_disaster_points"
    finished_at = datetime(2026, 9, 1, 3, 0, tzinfo=UTC)
    captured: dict[str, object] = {}
    events: list[tuple[str, dict[str, object]]] = []
    _install_tick_writer(monkeypatch)

    class _CoverageWriter:
        def __init__(self, *, database_url: str | None) -> None:
            captured["database_url"] = database_url

        def record_success(self, **fields: object) -> SimpleNamespace:
            captured["coverage_fields"] = fields
            return SimpleNamespace(
                assessed_years=(2021, 2022, 2023, 2024, 2025),
                source_check_count=110,
                attributed_record_count=8646,
                boundary_adjusted_record_count=1,
            )

    monkeypatch.setattr(
        runtime_cli,
        "build_runtime_adapters",
        lambda settings: {adapter_key: _Adapter(adapter_key)},
    )
    monkeypatch.setattr(
        runtime_cli,
        "v1_baseline_eligible_adapter_keys",
        lambda _settings: (adapter_key,),
    )
    monkeypatch.setattr(
        runtime_cli,
        "run_v1_baseline_adapter_cycle",
        lambda *_args, **_kwargs: ManagedRuntimeIngestionResult(
            status="succeeded",
            summaries=(
                SimpleNamespace(
                    adapter_key=adapter_key,
                    raw_ref="raw/official/nstc/verification.json",
                    finished_at=finished_at,
                    status="succeeded",
                ),
            ),
            promoted=8646,
        ),
    )
    monkeypatch.setattr(runtime_cli, "PostgresHistoricalCoverageWriter", _CoverageWriter)
    monkeypatch.setattr(
        runtime_cli,
        "log_event",
        lambda event, **fields: events.append((event, fields)),
    )

    failed = runtime_cli._run_v1_baseline_tick(
        settings=replace(
            load_worker_settings({}),
            enabled_adapter_keys=(adapter_key,),
        ),
        database_url="postgresql://example.test/flood",
        job_key="test",
    )

    assert failed is False
    assert captured == {
        "database_url": "postgresql://example.test/flood",
        "coverage_fields": {
            "adapter_key": adapter_key,
            "raw_ref": "raw/official/nstc/verification.json",
            "assessed_at": finished_at,
        },
    }
    coverage_event = next(
        fields
        for event, fields in events
        if event == "worker.runtime.v1_baseline.historical_coverage_completed"
    )
    assert coverage_event == {
        "adapter_key": adapter_key,
        "assessed_year_count": 5,
        "source_check_count": 110,
        "attributed_record_count": 8646,
        "boundary_adjusted_record_count": 1,
    }


def test_historical_coverage_failure_isolated_and_fails_the_source_tick(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter_key = "official.nstc.flood_disaster_points"
    writer = _install_tick_writer(monkeypatch)
    events: list[tuple[str, dict[str, object]]] = []
    summary_started_at = datetime(2026, 9, 1, 2, 59, tzinfo=UTC)

    class _CoverageWriter:
        def __init__(self, **_fields: object) -> None:
            pass

        def record_success(self, **_fields: object) -> None:
            raise RuntimeError("private-boundary-detail")

    monkeypatch.setattr(
        runtime_cli,
        "build_runtime_adapters",
        lambda settings: {adapter_key: _Adapter(adapter_key)},
    )
    monkeypatch.setattr(
        runtime_cli,
        "v1_baseline_eligible_adapter_keys",
        lambda _settings: (adapter_key,),
    )
    monkeypatch.setattr(
        runtime_cli,
        "run_v1_baseline_adapter_cycle",
        lambda *_args, **_kwargs: ManagedRuntimeIngestionResult(
            status="succeeded",
            summaries=(
                SimpleNamespace(
                    adapter_key=adapter_key,
                    raw_ref="raw/official/nstc/verification.json",
                    started_at=summary_started_at,
                    finished_at=datetime(2026, 9, 1, 3, 0, tzinfo=UTC),
                    status="succeeded",
                ),
            ),
        ),
    )
    monkeypatch.setattr(runtime_cli, "PostgresHistoricalCoverageWriter", _CoverageWriter)
    monkeypatch.setattr(
        runtime_cli,
        "log_event",
        lambda event, **fields: events.append((event, fields)),
    )

    failed = runtime_cli._run_v1_baseline_tick(
        settings=replace(
            load_worker_settings({}),
            enabled_adapter_keys=(adapter_key,),
        ),
        database_url="postgresql://example.test/flood",
        job_key="test",
    )

    assert failed is True
    assert writer.pipeline_statuses[0]["adapter_keys"] == (adapter_key,)
    assert writer.pipeline_statuses[0]["run_at"] == summary_started_at
    assert "private-boundary-detail" not in repr(events)
    failure_event = next(
        fields
        for event, fields in events
        if event == "worker.runtime.v1_baseline.source_failed"
    )
    assert failure_event["phase"] == "historical_coverage"
    assert failure_event["exception_class"] == "RuntimeError"


def test_freshness_alert_does_not_overwrite_a_completed_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = _install_tick_writer(monkeypatch)

    monkeypatch.setattr(
        runtime_cli,
        "build_runtime_adapters",
        lambda settings: {SOURCE_A: _Adapter(SOURCE_A)},
    )
    monkeypatch.setattr(
        runtime_cli,
        "v1_baseline_eligible_adapter_keys",
        lambda _settings: (SOURCE_A,),
    )
    monkeypatch.setattr(
        runtime_cli,
        "run_v1_baseline_adapter_cycle",
        lambda *_args, **_kwargs: ManagedRuntimeIngestionResult(
            status="failed",
            summaries=(SimpleNamespace(status="succeeded"),),
            freshness_checks=(
                FreshnessCheck(
                    adapter_key=SOURCE_A,
                    status="stale",
                    checked_at=datetime(2026, 8, 28, 9, 0, tzinfo=UTC),
                    max_age_seconds=600,
                ),
            ),
        ),
    )
    monkeypatch.setattr(runtime_cli, "log_event", lambda *_args, **_kwargs: None)

    failed = runtime_cli._run_v1_baseline_tick(
        settings=replace(load_worker_settings({}), enabled_adapter_keys=(SOURCE_A,)),
        database_url="postgresql://example.test/flood",
        job_key="test",
    )

    assert failed is True
    assert writer.pipeline_statuses == []


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


def test_upstream_freshness_alert_is_an_advisory_not_a_source_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = _install_tick_writer(monkeypatch)
    events: list[tuple[str, dict[str, object]]] = []

    monkeypatch.setattr(
        runtime_cli,
        "build_runtime_adapters",
        lambda settings: {SOURCE_A: _Adapter(SOURCE_A)},
    )
    monkeypatch.setattr(
        runtime_cli,
        "v1_baseline_eligible_adapter_keys",
        lambda _settings: (SOURCE_A,),
    )
    monkeypatch.setattr(
        runtime_cli,
        "run_v1_baseline_adapter_cycle",
        lambda *_args, **_kwargs: ManagedRuntimeIngestionResult(
            status="succeeded",
            summaries=(SimpleNamespace(status="succeeded"),),
            freshness_checks=(
                FreshnessCheck(
                    adapter_key=SOURCE_A,
                    status="failed",
                    checked_at=datetime(2026, 9, 3, 10, 30, tzinfo=UTC),
                    max_age_seconds=10800,
                    cadence="realtime",
                    source_timestamp_max=datetime(2026, 9, 2, 4, 29, tzinfo=UTC),
                    age_seconds=108060,
                ),
            ),
        ),
    )
    monkeypatch.setattr(
        runtime_cli,
        "log_event",
        lambda event, **fields: events.append((event, fields)),
    )

    failed = runtime_cli._run_v1_baseline_tick(
        settings=replace(load_worker_settings({}), enabled_adapter_keys=(SOURCE_A,)),
        database_url="postgresql://example.test/flood",
        job_key="test",
    )

    assert failed is False
    assert writer.pipeline_statuses == []
    advisory = next(
        fields
        for event, fields in events
        if event == "worker.runtime.v1_baseline.freshness_alert"
    )
    assert advisory["adapter_key"] == SOURCE_A
    assert advisory["freshness_status"] == "failed"
    assert advisory["age_seconds"] == 108060
    assert not [
        fields
        for event, fields in events
        if event == "worker.runtime.v1_baseline.source_failed"
    ]
    tick = next(
        fields
        for event, fields in events
        if event == "worker.runtime.v1_baseline.tick_completed"
    )
    assert tick["failed_count"] == 0
    assert tick["completed_count"] == 1


def test_source_failure_is_stamped_with_its_own_run_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failure stamped before its batch is dropped by the pipeline writer."""

    writer = _install_tick_writer(monkeypatch)
    summary_started_at = datetime(2026, 9, 3, 11, 0, tzinfo=UTC)

    monkeypatch.setattr(
        runtime_cli,
        "build_runtime_adapters",
        lambda settings: {SOURCE_A: _Adapter(SOURCE_A)},
    )
    monkeypatch.setattr(
        runtime_cli,
        "v1_baseline_eligible_adapter_keys",
        lambda _settings: (SOURCE_A,),
    )
    monkeypatch.setattr(
        runtime_cli,
        "run_v1_baseline_adapter_cycle",
        lambda *_args, **_kwargs: ManagedRuntimeIngestionResult(
            status="failed",
            summaries=(
                SimpleNamespace(
                    adapter_key=SOURCE_A,
                    started_at=summary_started_at,
                    status="failed",
                ),
            ),
        ),
    )
    monkeypatch.setattr(runtime_cli, "log_event", lambda *_args, **_kwargs: None)

    failed = runtime_cli._run_v1_baseline_tick(
        settings=replace(load_worker_settings({}), enabled_adapter_keys=(SOURCE_A,)),
        database_url="postgresql://example.test/flood",
        job_key="test",
    )

    assert failed is True
    assert writer.pipeline_statuses[0]["status"] == "failed"
    assert writer.pipeline_statuses[0]["run_at"] == summary_started_at
