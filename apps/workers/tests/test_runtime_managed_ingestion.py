from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from app.adapters import registry as adapter_registry
from app.adapters.contracts import (
    AdapterMetadata,
    AdapterRunResult,
    EventType,
    IngestionStatus,
    NormalizedEvidence,
    RawSourceItem,
    SourceFamily,
    StationInventoryProof,
)
from app.adapters.news import SamplePublicWebNewsAdapter
from app.config import WorkerSettings, load_worker_settings
from app.jobs import ingestion as ingestion_jobs
from app.jobs import runtime_managed as runtime_managed_jobs
from app.jobs.ingestion import AdapterBatchRunSummary
from app.jobs.runtime_managed import (
    _execute_managed_runtime_ingestion_cycle,
    run_v1_baseline_adapter_cycle,
)
from app.pipelines.promotion import EvidencePromotionPayload, PromotionCandidate
from app.pipelines.staging import AdapterStagingBatch

FETCHED_AT = datetime.now(UTC)
_PRIVATE_DATABASE_ERROR = "postgresql://operator:private@example.test/flood"
EXPECTED_V1_BASELINE_ADAPTER_KEYS = (
    "official.civil_iot.flood_sensor",
    "official.civil_iot.gate_water_level",
    "official.civil_iot.pond_water_level",
    "official.civil_iot.pump_water_level",
    "official.civil_iot.river_water_level",
    "official.civil_iot.sewer_water_level",
    "official.cwa.heavy_rain_warning",
    "official.cwa.rainfall",
    "official.cwa.tide_level",
    "official.flood_potential.geojson",
    "official.ncdr.cap",
    "official.nstc.flood_disaster_points",
    "official.wra.flood_incident",
    "official.wra.historical_flood",
    "official.wra.water_level",
    "official.wra_iow.flood_depth",
    "local.changhua.flood_sensor",
    "local.chiayi_city.rainfall",
    "local.chiayi_city.water_level",
    "local.chiayi_county.flood_sensor",
    "local.hsinchu_city.flood_sensor",
    "local.hsinchu_city.sewer_water_level",
    "local.hsinchu_county.flood_sensor",
    "local.hualien.flood_sensor",
    "local.kaohsiung.flood_sensor",
    "local.kaohsiung.rainfall",
    "local.kaohsiung.sewer_water_level",
    "local.keelung.flood_sensor",
    "local.keelung.rainfall",
    "local.keelung.water_level",
    "local.kinmen.kwis_pump_station",
    "local.miaoli.flood_sensor",
    "local.nantou.sewer_water_level",
    "local.new_taipei.drainage_water_level",
    "local.new_taipei.flood_sensor",
    "local.new_taipei.rainfall",
    "local.new_taipei.water_level",
    "local.penghu.water_level",
    "local.pingtung.flood_sensor",
    "local.taichung.water_level",
    "local.tainan.flood_sensor",
    "local.taipei.pump_station",
    "local.taipei.river_water_level",
    "local.taipei.sewer_water_level",
    "local.taitung.flood_sensor",
    "local.taoyuan.flood_sensor",
    "local.taoyuan.rainfall",
    "local.taoyuan.water_level",
    "local.yilan.flood_sensor",
    "local.yilan.mobile_pump_status",
    "local.yilan.water_level",
    "local.yunlin.water_level",
)
TASK9_SYNTHETIC_ADAPTER_KEYS = (
    "official.cwa.heavy_rain_warning",
    "official.ncdr.cap",
    "official.wra.historical_flood",
)


@pytest.fixture
def task9_synthetic_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = dict(adapter_registry.ADAPTER_REGISTRY)
    for key in TASK9_SYNTHETIC_ADAPTER_KEYS:
        registry[key] = AdapterMetadata(
            key=key,
            family=SourceFamily.OFFICIAL,
            enabled_by_default=False,
            display_name=f"{key} Task 9 synthetic adapter",
        )
    monkeypatch.setattr(adapter_registry, "ADAPTER_REGISTRY", registry)
    monkeypatch.setattr(ingestion_jobs, "ADAPTER_REGISTRY", registry)
    monkeypatch.setattr(runtime_managed_jobs, "ADAPTER_REGISTRY", registry)


@pytest.mark.usefixtures("task9_synthetic_registry")
@pytest.mark.parametrize(
    "adapter_key",
    ("official.cwa.heavy_rain_warning", "official.ncdr.cap"),
)
def test_managed_valid_empty_warning_is_success_without_source_timestamp(
    adapter_key: str,
) -> None:
    result = _run_task9_managed(_Task9EmptyWarningAdapter(adapter_key, no_active_event=True))

    assert result.status == "succeeded"
    assert len(result.summaries) == 1
    assert result.summaries[0].error_code == "no_active_event"
    assert result.summaries[0].source_timestamp_max is None
    assert result.freshness_checks[0].status == "fresh"


@pytest.mark.usefixtures("task9_synthetic_registry")
@pytest.mark.parametrize(
    "adapter_key",
    ("official.cwa.heavy_rain_warning", "official.ncdr.cap"),
)
def test_plain_empty_or_failed_warning_never_uses_no_active_freshness_branch(
    adapter_key: str,
) -> None:
    plain = _run_task9_managed(
        _Task9EmptyWarningAdapter(
            adapter_key,
            no_active_event=False,
        )
    )
    failed = _run_task9_managed(_ExplodingAdapter(adapter_key))

    assert plain.status != "succeeded"
    assert plain.summaries[0].error_code != "no_active_event"
    assert failed.status == "failed"
    assert failed.summaries[0].error_code != "no_active_event"


@pytest.mark.usefixtures("task9_synthetic_registry")
def test_managed_result_key_mismatch_fails_under_configured_warning_key() -> None:
    result = _run_task9_managed(_Task9MismatchedResultKeyAdapter())

    assert result.status == "failed"
    assert result.summaries[0].adapter_key == "official.cwa.heavy_rain_warning"
    assert result.summaries[0].error_code == "ValueError"
    assert result.summaries[0].error_code != "no_active_event"


@pytest.mark.usefixtures("task9_synthetic_registry")
@pytest.mark.parametrize("malformation", ["normalized", "inventory_proof"])
def test_managed_malformed_empty_warning_never_becomes_no_active(
    malformation: str,
) -> None:
    result = _run_task9_managed(_Task9MalformedEmptyWarningAdapter(malformation))

    assert result.status != "succeeded"
    assert result.summaries[0].error_code != "no_active_event"


def test_managed_nested_warning_identity_mismatch_is_inert() -> None:
    adapter = _NestedWarningIdentityAdapter()
    staging_writer = _MemoryStagingWriter()
    promotion_writer = _StagingBackedWarningPromotionWriter(staging_writer)
    settings = replace(
        load_worker_settings({}),
        enabled_adapter_keys=(adapter.metadata.key,),
    )

    result = run_v1_baseline_adapter_cycle(
        {adapter.metadata.key: adapter},
        settings=settings,
        staging_writer=staging_writer,
        run_writer=_MemoryRunWriter(),
        promotion_writer=promotion_writer,
        promote=True,
    )

    assert result.status == "failed"
    assert result.summaries[0].status == "failed"
    assert result.summaries[0].adapter_key == "official.cwa.rainfall"
    assert result.summaries[0].error_code == "ValueError"
    assert result.summaries[0].error_message is not None
    assert "normalized adapter key mismatch" in result.summaries[0].error_message
    assert staging_writer.batches == []
    assert result.promoted == 0
    assert promotion_writer.payloads == []
    assert promotion_writer.retired_no_active == []
    assert promotion_writer.retired_references == []
    assert promotion_writer.existing_warning_latest is True


@pytest.mark.usefixtures("task9_synthetic_registry")
@pytest.mark.parametrize(
    "adapter_key",
    ("official.cwa.heavy_rain_warning", "official.ncdr.cap"),
)
def test_managed_active_long_lived_warning_uses_validated_event_window(
    adapter_key: str,
) -> None:
    sent_at = FETCHED_AT - timedelta(hours=12)
    active_from = FETCHED_AT - timedelta(hours=12)
    active_until = FETCHED_AT + timedelta(hours=3)

    result = _run_task9_managed(
        _Task9ActiveWarningAdapter(
            adapter_key,
            sent_at=sent_at,
            active_from=active_from,
            active_until=active_until,
        )
    )

    assert result.status == "succeeded"
    assert result.summaries[0].source_timestamp_max == sent_at
    assert result.summaries[0].event_active_from_min == active_from
    assert result.summaries[0].event_active_until_max == active_until
    assert result.freshness_checks[0].status == "fresh"


@pytest.mark.usefixtures("task9_synthetic_registry")
@pytest.mark.parametrize(
    "adapter_key",
    ("official.cwa.heavy_rain_warning", "official.ncdr.cap"),
)
def test_disjoint_expired_and_future_warnings_do_not_form_active_window(
    adapter_key: str,
) -> None:
    result = _run_task9_managed(
        _Task9MultiWindowWarningAdapter(
            adapter_key,
            windows=(
                (
                    FETCHED_AT - timedelta(hours=3),
                    FETCHED_AT - timedelta(hours=2),
                ),
                (
                    FETCHED_AT + timedelta(hours=2),
                    FETCHED_AT + timedelta(hours=3),
                ),
            ),
        )
    )

    assert result.summaries[0].event_active_from_min is None
    assert result.summaries[0].event_active_until_max is None
    assert result.freshness_checks[0].status == "stale"


@pytest.mark.usefixtures("task9_synthetic_registry")
def test_managed_historical_flood_preserves_event_time_with_background_freshness() -> None:
    event_observed_at = FETCHED_AT - timedelta(days=3650)
    result = _run_task9_managed(_Task9HistoricalAdapter(event_observed_at=event_observed_at))

    assert result.status == "succeeded"
    assert result.summaries[0].source_timestamp_max == event_observed_at
    assert result.freshness_checks[0].status == "fresh"
    assert result.freshness_checks[0].cadence == "static"


@pytest.mark.usefixtures("task9_synthetic_registry")
def test_managed_no_active_retirement_runs_after_summary_persistence() -> None:
    timeline: list[str] = []
    run_writer = _MemoryRunWriter(timeline=timeline)
    promotion_writer = _MemoryPromotionWriter([], timeline=timeline)
    adapter = _Task9EmptyWarningAdapter(
        "official.cwa.heavy_rain_warning",
        no_active_event=True,
    )
    settings = replace(
        _settings(adapter.metadata.key),
        enabled_adapter_keys=(adapter.metadata.key,),
    )

    result = run_v1_baseline_adapter_cycle(
        {adapter.metadata.key: adapter},
        settings=settings,
        staging_writer=_MemoryStagingWriter(),
        run_writer=run_writer,
        promotion_writer=promotion_writer,
        source_catalog_reader=_StaticCatalogReader(enabled=frozenset({adapter.metadata.key})),
        promote=True,
    )

    assert result.status == "succeeded"
    assert promotion_writer.retired_no_active == [
        (
            adapter.metadata.key,
            result.summaries[0].started_at,
            result.summaries[0].finished_at,
        )
    ]
    assert timeline.index("summary") < timeline.index("retire")
    assert promotion_writer.fetch_calls == 0


def test_managed_cancel_only_snapshot_retires_latest_and_keeps_audit_staging() -> None:
    adapter = _Task9CancelOnlyNcdrAdapter()
    staging_writer = _MemoryStagingWriter()
    promotion_writer = _MemoryPromotionWriter([])
    settings = replace(
        _settings(adapter.metadata.key),
        enabled_adapter_keys=(adapter.metadata.key,),
        source_ncdr_cap_enabled=True,
        source_ncdr_cap_contract_enabled=True,
    )

    result = run_v1_baseline_adapter_cycle(
        {adapter.metadata.key: adapter},
        settings=settings,
        staging_writer=staging_writer,
        run_writer=_MemoryRunWriter(),
        promotion_writer=promotion_writer,
        source_catalog_reader=_StaticCatalogReader(enabled=frozenset({adapter.metadata.key})),
        promote=True,
    )

    summary = result.summaries[0]
    assert result.status == "succeeded"
    assert summary.error_code == "no_active_event"
    assert summary.items_fetched == summary.items_promoted == 1
    assert summary.snapshot_activation_eligible is True
    assert result.freshness_checks[0].status == "fresh"
    assert promotion_writer.retired_no_active == [
        (adapter.metadata.key, summary.started_at, summary.finished_at)
    ]
    assert len(staging_writer.batches) == 1
    assert staging_writer.batches[0].accepted[0].payload["cap_message_type"] == "Cancel"
    assert promotion_writer.requested_raw_refs == (summary.raw_ref,)


@pytest.mark.parametrize(
    "adapter_key",
    ("official.npa.police_radio_traffic", "official.wra.flood_warning"),
)
def test_context_sources_are_fenced_out_of_the_managed_v1_baseline_cycle(
    adapter_key: str,
) -> None:
    """The two non-scoring context sources cannot run through the managed cycle.

    They are deliberately absent from ``V1_BASELINE_ADAPTER_KEYS``, so the cycle
    refuses the scope before any adapter work, and nothing is staged, promoted,
    or retired. Turning on their three runtime gates is therefore not enough to
    make them run; that is the outermost fence, and it stays shut in v1.
    """

    assert adapter_key not in runtime_managed_jobs.V1_BASELINE_ADAPTER_KEYS
    assert adapter_key not in EXPECTED_V1_BASELINE_ADAPTER_KEYS

    run_writer = _MemoryRunWriter()
    promotion_writer = _MemoryPromotionWriter([])
    staging_writer = _MemoryStagingWriter()
    adapter = _Task9EmptyWarningAdapter(adapter_key, no_active_event=True)
    settings = replace(_settings(adapter_key), enabled_adapter_keys=(adapter_key,))

    result = run_v1_baseline_adapter_cycle(
        {adapter_key: adapter},
        settings=settings,
        staging_writer=staging_writer,
        run_writer=run_writer,
        promotion_writer=promotion_writer,
        source_catalog_reader=_StaticCatalogReader(enabled=frozenset({adapter_key})),
        promote=True,
    )

    assert result.status == "failed"
    assert result.reason == "invalid_v1_baseline_scope"
    assert result.error_code == "invalid_v1_baseline_scope"
    assert result.summaries == ()
    assert result.promoted == 0
    assert promotion_writer.retired_no_active == []
    assert staging_writer.batches == []


def test_runtime_selection_override_cannot_widen_staging_or_promotion() -> None:
    adapter_key = "official.wra.water_level"
    peer_key = "official.cwa.rainfall"
    raw_ref = "raw/test/wra-water-level.json"
    adapter = _SuccessfulAdapter(
        adapter_key,
        family=SourceFamily.OFFICIAL,
        event_type=EventType.WATER_LEVEL,
        raw_ref=raw_ref,
    )
    staging_writer = _MemoryStagingWriter()
    run_writer = _MemoryRunWriter()
    promotion_writer = _MemoryPromotionWriter([_candidate()])
    settings = replace(
        load_worker_settings({}),
        enabled_adapter_keys=(adapter_key,),
    )

    result = run_v1_baseline_adapter_cycle(
        {adapter_key: adapter},
        settings=settings,
        runtime_selection_adapter_keys=(adapter_key, peer_key),
        staging_writer=staging_writer,
        run_writer=run_writer,
        promotion_writer=promotion_writer,
        promote=True,
        promotion_adapter_keys=(adapter_key,),
    )

    assert result.status == "succeeded"
    assert run_writer.runtime_selections
    assert len(run_writer.runtime_selections) == 1
    assert {
        enabled_adapter_keys
        for enabled_adapter_keys, _known_adapter_keys in run_writer.runtime_selections
    } == {(adapter_key, peer_key)}
    assert len(staging_writer.batches) == 1
    assert staging_writer.batches[0].adapter_key == adapter_key
    assert promotion_writer.requested_adapter_keys == (adapter_key,)
    assert promotion_writer.requested_raw_refs == (raw_ref,)


@pytest.mark.usefixtures("task9_synthetic_registry")
def test_managed_no_active_retirement_is_not_called_when_promotion_disabled() -> None:
    adapter = _Task9EmptyWarningAdapter(
        "official.cwa.heavy_rain_warning",
        no_active_event=True,
    )
    promotion_writer = _MemoryPromotionWriter([])
    settings = replace(
        _settings(adapter.metadata.key),
        enabled_adapter_keys=(adapter.metadata.key,),
    )

    result = run_v1_baseline_adapter_cycle(
        {adapter.metadata.key: adapter},
        settings=settings,
        staging_writer=_MemoryStagingWriter(),
        run_writer=_MemoryRunWriter(),
        promotion_writer=promotion_writer,
        source_catalog_reader=_StaticCatalogReader(enabled=frozenset({adapter.metadata.key})),
        promote=False,
    )

    assert result.status == "succeeded"
    assert promotion_writer.retired_no_active == []


@pytest.mark.usefixtures("task9_synthetic_registry")
def test_managed_no_active_retirement_failure_returns_safe_failed_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, dict[str, object]]] = []
    adapter = _Task9EmptyWarningAdapter(
        "official.cwa.heavy_rain_warning",
        no_active_event=True,
    )
    settings = replace(
        _settings(adapter.metadata.key),
        enabled_adapter_keys=(adapter.metadata.key,),
    )
    monkeypatch.setattr(
        runtime_managed_jobs,
        "log_event",
        lambda event, **fields: events.append((event, fields)),
    )

    result = run_v1_baseline_adapter_cycle(
        {adapter.metadata.key: adapter},
        settings=settings,
        staging_writer=_MemoryStagingWriter(),
        run_writer=_MemoryRunWriter(),
        promotion_writer=_FailingNoActiveRetirementWriter([]),
        source_catalog_reader=_StaticCatalogReader(enabled=frozenset({adapter.metadata.key})),
        promote=True,
    )

    assert result.status == "failed"
    assert result.reason == "no_active_event_retirement_failed"
    assert result.error_code == "RuntimeError"
    assert result.error_message == _PRIVATE_DATABASE_ERROR
    assert _PRIVATE_DATABASE_ERROR not in repr(events)
    assert (
        "runtime.managed.no_active_event_retirement.failed",
        {"error_code": "RuntimeError"},
    ) in events


@pytest.mark.parametrize(
    "mapping_keys,settings_keys,adapter_metadata_keys",
    [
        (("community.unreviewed",), ("community.unreviewed",), ("community.unreviewed",)),
        (
            ("official.cwa.rainfall", "official.wra.water_level"),
            ("official.cwa.rainfall",),
            ("official.cwa.rainfall", "official.wra.water_level"),
        ),
        (
            ("official.cwa.rainfall",),
            ("official.wra.water_level",),
            ("official.cwa.rainfall",),
        ),
        (
            ("official.cwa.rainfall",),
            ("official.cwa.rainfall", "official.wra.water_level"),
            ("official.cwa.rainfall",),
        ),
        (
            ("official.cwa.rainfall",),
            ("official.cwa.rainfall",),
            ("official.wra.water_level",),
        ),
    ],
)
def test_v1_baseline_adapter_cycle_rejects_scope_before_engine_or_writer_construction(
    monkeypatch: pytest.MonkeyPatch,
    mapping_keys: tuple[str, ...],
    settings_keys: tuple[str, ...],
    adapter_metadata_keys: tuple[str, ...],
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> object:
        pytest.fail("v1 scope rejection reached an engine or writer constructor")

    monkeypatch.setattr(
        runtime_managed_jobs,
        "_execute_managed_runtime_ingestion_cycle",
        forbidden,
        raising=False,
    )
    monkeypatch.setattr(runtime_managed_jobs, "PostgresIngestionRunWriter", forbidden)
    monkeypatch.setattr(runtime_managed_jobs, "PostgresStagingBatchWriter", forbidden)
    monkeypatch.setattr(runtime_managed_jobs, "PostgresEvidencePromotionWriter", forbidden)
    adapters = {
        key: SimpleNamespace(metadata=SimpleNamespace(key=metadata_key))
        for key, metadata_key in zip(mapping_keys, adapter_metadata_keys, strict=True)
    }
    settings = replace(
        load_worker_settings({}),
        enabled_adapter_keys=settings_keys,
        database_url="postgresql://worker:test@localhost/flood",
    )

    result = runtime_managed_jobs.run_v1_baseline_adapter_cycle(
        adapters,  # type: ignore[arg-type]
        settings=settings,
        promote=True,
    )

    assert result.status == "failed"
    assert result.reason == "invalid_v1_baseline_scope"
    assert result.error_code == "invalid_v1_baseline_scope"


def test_each_exact_v1_baseline_key_can_enter_the_scoped_injected_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[dict[str, object], dict[str, object]]] = []

    def execute(
        adapter_by_key: dict[str, object],
        **kwargs: object,
    ) -> runtime_managed_jobs.ManagedRuntimeIngestionResult:
        calls.append((adapter_by_key, kwargs))
        return runtime_managed_jobs.ManagedRuntimeIngestionResult(status="succeeded")

    monkeypatch.setattr(
        runtime_managed_jobs,
        "_execute_managed_runtime_ingestion_cycle",
        execute,
        raising=False,
    )

    assert runtime_managed_jobs.V1_BASELINE_ADAPTER_KEYS == (EXPECTED_V1_BASELINE_ADAPTER_KEYS)
    for key in EXPECTED_V1_BASELINE_ADAPTER_KEYS:
        adapter = SimpleNamespace(metadata=SimpleNamespace(key=key))
        settings = replace(load_worker_settings({}), enabled_adapter_keys=(key,))

        result = runtime_managed_jobs.run_v1_baseline_adapter_cycle(
            {key: adapter},  # type: ignore[arg-type]
            settings=settings,
            database_url="postgresql://worker:test@localhost/flood",
            staging_writer=object(),  # type: ignore[arg-type]
            run_writer=object(),  # type: ignore[arg-type]
            promotion_writer=object(),  # type: ignore[arg-type]
            promote=True,
            promotion_limit=5,
            promotion_adapter_keys=(key,),
            job_key=f"worker.v1_baseline.{key}",
        )

        assert result.status == "succeeded"

    assert [tuple(mapping) for mapping, _kwargs in calls] == [
        (key,) for key in EXPECTED_V1_BASELINE_ADAPTER_KEYS
    ]
    for key, (_mapping, kwargs) in zip(EXPECTED_V1_BASELINE_ADAPTER_KEYS, calls, strict=True):
        assert kwargs["settings"].enabled_adapter_keys == (key,)  # type: ignore[union-attr]
        assert kwargs["promotion_adapter_keys"] == (key,)
        assert kwargs["job_key"] == f"worker.v1_baseline.{key}"


def test_v1_baseline_adapter_cycle_rejects_cross_key_promotion_before_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> object:
        pytest.fail("cross-key promotion reached the managed engine")

    monkeypatch.setattr(
        runtime_managed_jobs,
        "_execute_managed_runtime_ingestion_cycle",
        forbidden,
    )
    key = "official.cwa.rainfall"
    adapter = SimpleNamespace(metadata=SimpleNamespace(key=key))
    settings = replace(load_worker_settings({}), enabled_adapter_keys=(key,))

    result = runtime_managed_jobs.run_v1_baseline_adapter_cycle(
        {key: adapter},  # type: ignore[arg-type]
        settings=settings,
        promotion_adapter_keys=("official.wra.water_level",),
    )

    assert result.status == "failed"
    assert result.error_code == "invalid_v1_baseline_scope"


def test_managed_runtime_cycle_persists_enabled_adapters_and_promotes() -> None:
    adapter = _sample_adapter()
    staging_writer = _MemoryStagingWriter()
    run_writer = _MemoryRunWriter()
    promotion_writer = _MemoryPromotionWriter([_candidate()])

    result = _execute_managed_runtime_ingestion_cycle(
        {
            adapter.metadata.key: adapter,
            "official.wra.water_level": _ExplodingAdapter("official.wra.water_level"),
        },
        settings=_settings("news.public_web.sample"),
        staging_writer=staging_writer,
        run_writer=run_writer,
        promotion_writer=promotion_writer,
        promote=True,
        promotion_limit=25,
        job_key="test.runtime.managed",
    )

    assert result.status == "succeeded"
    assert result.reason is None
    assert [summary.adapter_key for summary in result.summaries] == ["news.public_web.sample"]
    assert result.freshness_checks[0].status == "fresh"
    assert result.promoted == 1
    assert result.evidence_ids == ("evidence-1",)
    assert len(staging_writer.batches) == 1
    assert staging_writer.batches[0].accepted[0].source_id == "sample-news-001"
    assert run_writer.calls == [
        (
            result.summaries[0],
            "test.runtime.managed",
            {
                "enabled_adapter_keys": ("news.public_web.sample",),
                "available_adapter_keys": (
                    "news.public_web.sample",
                    "official.wra.water_level",
                ),
            },
        )
    ]
    assert promotion_writer.requested_limit == 25
    assert promotion_writer.requested_adapter_keys == ("news.public_web.sample",)
    assert promotion_writer.requested_raw_refs == (result.summaries[0].raw_ref,)
    assert promotion_writer.payloads[0].source_id == "sample-news-001"


def test_managed_runtime_cycle_uses_injected_adapter_builder() -> None:
    captured: dict[str, WorkerSettings] = {}
    staging_writer = _MemoryStagingWriter()
    run_writer = _MemoryRunWriter()
    settings = _settings("news.public_web.sample")

    def adapter_builder(builder_settings: WorkerSettings) -> dict[str, SamplePublicWebNewsAdapter]:
        captured["settings"] = builder_settings
        adapter = _sample_adapter(source_id="builder-news-001")
        return {adapter.metadata.key: adapter}

    result = _execute_managed_runtime_ingestion_cycle(
        settings=settings,
        adapter_builder=adapter_builder,
        staging_writer=staging_writer,
        run_writer=run_writer,
    )

    assert result.status == "succeeded"
    assert captured["settings"] == settings
    assert staging_writer.batches[0].accepted[0].source_id == "builder-news-001"


@pytest.mark.usefixtures("task9_synthetic_registry")
def test_disabled_catalog_key_never_builds_or_runs_managed_adapter() -> None:
    calls = {"build": 0, "run": 0}

    def adapter_builder(settings: WorkerSettings) -> dict[str, _CatalogCountingAdapter]:
        del settings
        calls["build"] += 1
        return {"official.cwa.heavy_rain_warning": _CatalogCountingAdapter(calls)}

    result = _execute_managed_runtime_ingestion_cycle(
        settings=_settings("official.cwa.heavy_rain_warning"),
        staging_writer=_MemoryStagingWriter(),
        run_writer=_MemoryRunWriter(),
        source_catalog_reader=_StaticCatalogReader(
            enabled=frozenset({"news.public_web.sample"})
        ),
        adapter_builder=adapter_builder,
    )

    assert result.status == "skipped"
    assert result.reason == "source_catalog_disabled"
    assert calls == {"build": 0, "run": 0}


@pytest.mark.usefixtures("task9_synthetic_registry")
def test_missing_catalog_row_never_runs_supplied_managed_adapter() -> None:
    calls = {"run": 0}
    adapter = _CatalogCountingAdapter(calls)

    result = _execute_managed_runtime_ingestion_cycle(
        {adapter.metadata.key: adapter},
        settings=_settings(adapter.metadata.key),
        staging_writer=_MemoryStagingWriter(),
        run_writer=_MemoryRunWriter(),
        source_catalog_reader=_StaticCatalogReader(
            enabled=frozenset({"news.public_web.sample"})
        ),
    )

    assert result.status == "skipped"
    assert result.reason == "source_catalog_disabled"
    assert calls == {"run": 0}


@pytest.mark.usefixtures("task9_synthetic_registry")
def test_enabled_catalog_key_runs_managed_adapter() -> None:
    calls = {"run": 0}
    adapter = _CatalogCountingAdapter(calls)

    result = _execute_managed_runtime_ingestion_cycle(
        {adapter.metadata.key: adapter},
        settings=_settings(adapter.metadata.key),
        staging_writer=_MemoryStagingWriter(),
        run_writer=_MemoryRunWriter(),
        source_catalog_reader=_StaticCatalogReader(enabled=frozenset({adapter.metadata.key})),
    )

    assert result.status == "partial"
    assert calls == {"run": 1}


@pytest.mark.usefixtures("task9_synthetic_registry")
def test_catalog_query_exception_fails_managed_cycle_without_upstream_work() -> None:
    calls = {"build": 0}

    def adapter_builder(settings: WorkerSettings) -> dict[str, _CatalogCountingAdapter]:
        del settings
        calls["build"] += 1
        return {}

    result = _execute_managed_runtime_ingestion_cycle(
        settings=_settings("official.cwa.heavy_rain_warning"),
        staging_writer=_MemoryStagingWriter(),
        run_writer=_MemoryRunWriter(),
        source_catalog_reader=_FailingCatalogReader(),
        adapter_builder=adapter_builder,
    )

    assert result.status == "failed"
    assert result.reason == "source_catalog_unavailable"
    assert result.error_code == "source_catalog_unavailable"
    assert result.error_message is None
    assert calls == {"build": 0}


@pytest.mark.usefixtures("task9_synthetic_registry")
def test_catalog_query_failure_stays_safe_when_managed_audit_writer_fails(
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls = {"build": 0}

    def adapter_builder(settings: WorkerSettings) -> dict[str, _CatalogCountingAdapter]:
        del settings
        calls["build"] += 1
        return {}

    result = _execute_managed_runtime_ingestion_cycle(
        settings=_settings("official.cwa.heavy_rain_warning"),
        staging_writer=_MemoryStagingWriter(),
        run_writer=_FailingCatalogAuditWriter(),
        source_catalog_reader=_FailingCatalogReader(),
        adapter_builder=adapter_builder,
    )

    captured = capsys.readouterr()
    assert result.status == "failed"
    assert result.reason == "source_catalog_unavailable"
    assert result.error_code == "source_catalog_unavailable"
    assert result.error_message is None
    assert calls == {"build": 0}
    assert "catalog-secret" not in captured.out
    assert "audit-secret" not in captured.out


@pytest.mark.usefixtures("task9_synthetic_registry")
def test_catalog_gate_narrows_managed_promotion_targets() -> None:
    adapter = _sample_adapter()
    promotion_writer = _MemoryPromotionWriter([_candidate()])

    result = _execute_managed_runtime_ingestion_cycle(
        {
            adapter.metadata.key: adapter,
            "official.cwa.heavy_rain_warning": _ExplodingAdapter("official.cwa.heavy_rain_warning"),
        },
        settings=_settings("news.public_web.sample", "official.cwa.heavy_rain_warning"),
        staging_writer=_MemoryStagingWriter(),
        run_writer=_MemoryRunWriter(),
        promotion_writer=promotion_writer,
        promote=True,
        promotion_adapter_keys=("news.public_web.sample", "official.cwa.heavy_rain_warning"),
        source_catalog_reader=_StaticCatalogReader(
            enabled=frozenset({"news.public_web.sample"})
        ),
    )

    assert result.status == "succeeded"
    assert promotion_writer.requested_adapter_keys == ("news.public_web.sample",)


@pytest.mark.usefixtures("task9_synthetic_registry")
def test_catalog_gate_does_not_fall_back_when_explicit_promotion_targets_are_disabled() -> None:
    adapter = _sample_adapter()
    promotion_writer = _MemoryPromotionWriter([_candidate()])

    result = _execute_managed_runtime_ingestion_cycle(
        {
            adapter.metadata.key: adapter,
            "official.cwa.heavy_rain_warning": _ExplodingAdapter("official.cwa.heavy_rain_warning"),
        },
        settings=_settings("news.public_web.sample", "official.cwa.heavy_rain_warning"),
        staging_writer=_MemoryStagingWriter(),
        run_writer=_MemoryRunWriter(),
        promotion_writer=promotion_writer,
        promote=True,
        promotion_adapter_keys=("official.cwa.heavy_rain_warning",),
        source_catalog_reader=_StaticCatalogReader(
            enabled=frozenset({"news.public_web.sample"})
        ),
    )

    assert result.status == "succeeded"
    assert promotion_writer.fetch_calls == 0
    assert promotion_writer.requested_adapter_keys is None
    assert promotion_writer.payloads == []
    assert result.promoted == 0


def test_managed_runtime_cycle_promotes_adapter_keys_from_ran_summaries() -> None:
    staging_writer = _MemoryStagingWriter()
    run_writer = _MemoryRunWriter()
    promotion_writer = _MemoryPromotionWriter([_candidate()])
    official_adapter = _SuccessfulAdapter(
        "official.wra.water_level",
        family=SourceFamily.OFFICIAL,
        event_type=EventType.WATER_LEVEL,
        raw_ref="raw/official-demo/wra-water-level.json",
    )
    sample_adapter = _sample_adapter()

    result = _execute_managed_runtime_ingestion_cycle(
        {
            official_adapter.metadata.key: official_adapter,
            sample_adapter.metadata.key: sample_adapter,
        },
        settings=_settings("official.wra.water_level", "news.public_web.sample"),
        staging_writer=staging_writer,
        run_writer=run_writer,
        promotion_writer=promotion_writer,
        promote=True,
        job_key="test.runtime.managed",
    )

    assert result.status == "succeeded"
    assert [summary.adapter_key for summary in result.summaries] == [
        "official.wra.water_level",
        "news.public_web.sample",
    ]
    assert promotion_writer.requested_adapter_keys == (
        "official.wra.water_level",
        "news.public_web.sample",
    )
    parameters = run_writer.calls[0][2]
    assert parameters is not None
    assert parameters["enabled_adapter_keys"] == (
        "official.wra.water_level",
        "news.public_web.sample",
    )


def test_managed_runtime_cycle_noops_without_database_url_before_building_adapters() -> None:
    called = False

    def adapter_builder(settings: WorkerSettings) -> dict[str, SamplePublicWebNewsAdapter]:
        nonlocal called
        called = True
        raise AssertionError("adapter builder should not run without persistence")

    result = _execute_managed_runtime_ingestion_cycle(
        settings=_settings("news.public_web.sample"),
        adapter_builder=adapter_builder,
        promote=True,
    )

    assert result.status == "skipped"
    assert result.reason == "no_database_url"
    assert called is False


def test_managed_runtime_cycle_noops_without_adapters_when_writers_are_injected() -> None:
    staging_writer = _MemoryStagingWriter()
    run_writer = _MemoryRunWriter()

    result = _execute_managed_runtime_ingestion_cycle(
        settings=_settings("news.public_web.sample"),
        staging_writer=staging_writer,
        run_writer=run_writer,
    )

    assert result.status == "skipped"
    assert result.reason == "no_adapters"
    assert staging_writer.batches == []
    assert run_writer.calls == []


def test_managed_runtime_cycle_records_empty_runtime_selection() -> None:
    run_writer = _MemoryRunWriter()
    settings = replace(_settings("news.public_web.sample"), enabled_adapter_keys=())

    result = _execute_managed_runtime_ingestion_cycle(
        settings=settings,
        run_writer=run_writer,
    )

    assert result.status == "skipped"
    assert result.reason == "no_enabled_adapters"
    assert run_writer.runtime_selections[0][0] == ()


def test_managed_runtime_cycle_marks_missing_enabled_adapter_as_pipeline_failure() -> None:
    run_writer = _MemoryRunWriter()

    result = _execute_managed_runtime_ingestion_cycle(
        {},
        settings=_settings("official.wra.water_level"),
        staging_writer=_MemoryStagingWriter(),
        run_writer=run_writer,
    )

    assert result.status == "failed"
    assert result.reason == "missing_enabled_adapters"
    assert run_writer.runtime_selections[0][0] == ("official.wra.water_level",)
    assert len(run_writer.pipeline_statuses) == 1
    adapter_keys, status, complete, run_at = run_writer.pipeline_statuses[0]
    assert adapter_keys == ("official.wra.water_level",)
    assert status == "failed"
    assert complete is False
    assert isinstance(run_at, datetime)


def test_managed_runtime_cycle_records_promotion_failure_in_public_pipeline_state() -> None:
    adapter = _sample_adapter()
    run_writer = _MemoryRunWriter()

    result = _execute_managed_runtime_ingestion_cycle(
        {adapter.metadata.key: adapter},
        settings=_settings("news.public_web.sample"),
        staging_writer=_MemoryStagingWriter(),
        run_writer=run_writer,
        promotion_writer=_FailingPromotionWriter(),
        promote=True,
    )

    assert result.status == "failed"
    assert result.reason == "promotion_failed"
    assert run_writer.pipeline_statuses[-1] == (
        ("news.public_web.sample",),
        "failed",
        False,
        result.summaries[0].started_at,
    )


def test_managed_runtime_cycle_records_safe_promotion_timeout_exception_class(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, dict[str, object]]] = []
    adapter = _sample_adapter()
    run_writer = _MemoryRunWriter()
    monkeypatch.setattr(
        runtime_managed_jobs,
        "log_event",
        lambda event, **fields: events.append((event, fields)),
    )

    result = _execute_managed_runtime_ingestion_cycle(
        {adapter.metadata.key: adapter},
        settings=_settings("news.public_web.sample"),
        staging_writer=_MemoryStagingWriter(),
        run_writer=run_writer,
        promotion_writer=_TimeoutPromotionWriter(),
        promote=True,
    )

    assert result.status == "failed"
    assert result.reason == "promotion_failed"
    assert result.error_code == "QueryCanceled"
    assert result.error_message == _PRIVATE_DATABASE_ERROR
    assert _PRIVATE_DATABASE_ERROR not in repr(events)
    assert (
        "runtime.managed.promotion.failed",
        {"error_code": "QueryCanceled"},
    ) in events
    assert run_writer.pipeline_statuses[-1] == (
        ("news.public_web.sample",),
        "failed",
        False,
        result.summaries[0].started_at,
    )


def test_managed_runtime_cycle_retries_one_transient_database_promotion_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, dict[str, object]]] = []
    adapter = _sample_adapter()
    run_writer = _MemoryRunWriter()
    promotion_writer = _RetryOncePromotionWriter([_candidate()])
    monkeypatch.setattr(
        runtime_managed_jobs,
        "log_event",
        lambda event, **fields: events.append((event, fields)),
    )

    result = _execute_managed_runtime_ingestion_cycle(
        {adapter.metadata.key: adapter},
        settings=_settings("news.public_web.sample"),
        staging_writer=_MemoryStagingWriter(),
        run_writer=run_writer,
        promotion_writer=promotion_writer,
        promote=True,
    )

    assert result.status == "succeeded"
    assert result.promoted == 1
    assert promotion_writer.fetch_calls == 2
    assert (
        "runtime.managed.promotion.retrying",
        {
            "attempt": 2,
            "max_attempts": 2,
            "error_code": "OperationalError",
        },
    ) in events
    assert run_writer.pipeline_statuses[-1][1:3] == ("succeeded", True)


def test_complete_replace_source_quality_partial_activates_only_after_full_promotion() -> None:
    adapter = _CompleteReplacePartialAdapter(valid_count=3, rejection_count=1)
    settings = replace(
        load_worker_settings({}),
        enabled_adapter_keys=(adapter.metadata.key,),
        source_wra_historical_flood_enabled=True,
        freshness_max_age_seconds=24 * 60 * 60,
    )
    full_writer = _MemoryRunWriter()

    full = _execute_managed_runtime_ingestion_cycle(
        {adapter.metadata.key: adapter},
        settings=settings,
        staging_writer=_MemoryStagingWriter(),
        run_writer=full_writer,
        promotion_writer=_MemoryPromotionWriter([]),
        promote=True,
    )

    assert full.summaries[0].status == "partial"
    assert full.summaries[0].snapshot_activation_eligible is True
    assert full_writer.snapshot_activations == [full.summaries[0].raw_ref]

    limited_writer = _MemoryRunWriter()
    _execute_managed_runtime_ingestion_cycle(
        {adapter.metadata.key: adapter},
        settings=settings,
        staging_writer=_MemoryStagingWriter(),
        run_writer=limited_writer,
        promotion_writer=_MemoryPromotionWriter([]),
        promote=True,
        promotion_limit=1,
    )

    assert limited_writer.snapshot_activations == [None]


def test_complete_replace_ineligible_partial_or_failed_promotion_preserves_marker() -> None:
    adapter = _CompleteReplacePartialAdapter(valid_count=2, rejection_count=1)
    settings = replace(
        load_worker_settings({}),
        enabled_adapter_keys=(adapter.metadata.key,),
        source_wra_historical_flood_enabled=True,
        freshness_max_age_seconds=24 * 60 * 60,
    )
    ineligible_writer = _MemoryRunWriter()

    ineligible = _execute_managed_runtime_ingestion_cycle(
        {adapter.metadata.key: adapter},
        settings=settings,
        staging_writer=_MemoryStagingWriter(),
        run_writer=ineligible_writer,
        promotion_writer=_MemoryPromotionWriter([]),
        promote=True,
    )

    assert ineligible.summaries[0].snapshot_activation_eligible is False
    assert ineligible_writer.snapshot_activations == [None]

    eligible_adapter = _CompleteReplacePartialAdapter(valid_count=3, rejection_count=1)
    failed_writer = _MemoryRunWriter()
    failed = _execute_managed_runtime_ingestion_cycle(
        {eligible_adapter.metadata.key: eligible_adapter},
        settings=settings,
        staging_writer=_MemoryStagingWriter(),
        run_writer=failed_writer,
        promotion_writer=_FailingPromotionWriter(),
        promote=True,
    )

    assert failed.reason == "promotion_failed"
    assert failed_writer.snapshot_activations == [None]


def test_complete_replace_audit_summary_failure_cannot_activate_snapshot() -> None:
    adapter = _CompleteReplacePartialAdapter(valid_count=3, rejection_count=1)
    settings = replace(
        load_worker_settings({}),
        enabled_adapter_keys=(adapter.metadata.key,),
        source_wra_historical_flood_enabled=True,
        freshness_max_age_seconds=24 * 60 * 60,
    )
    run_writer = _FailingSummaryMemoryRunWriter()

    result = _execute_managed_runtime_ingestion_cycle(
        {adapter.metadata.key: adapter},
        settings=settings,
        staging_writer=_MemoryStagingWriter(),
        run_writer=run_writer,
        promotion_writer=_MemoryPromotionWriter([]),
        promote=True,
    )

    assert result.summaries[0].status == "failed"
    assert result.summaries[0].snapshot_activation_eligible is True
    assert run_writer.snapshot_activations == [None]


def test_managed_runtime_cycle_records_builder_exception_as_pipeline_failure() -> None:
    run_writer = _MemoryRunWriter()

    def exploding_builder(settings: WorkerSettings) -> dict[str, SamplePublicWebNewsAdapter]:
        del settings
        raise RuntimeError("adapter initialization failed")

    with pytest.raises(RuntimeError, match="adapter initialization failed"):
        _execute_managed_runtime_ingestion_cycle(
            settings=_settings("news.public_web.sample"),
            staging_writer=_MemoryStagingWriter(),
            run_writer=run_writer,
            adapter_builder=exploding_builder,
        )

    assert run_writer.runtime_selections[0][0] == ("news.public_web.sample",)
    assert len(run_writer.pipeline_statuses) == 1
    adapter_keys, status, complete, run_at = run_writer.pipeline_statuses[0]
    assert adapter_keys == ("news.public_web.sample",)
    assert status == "failed"
    assert complete is False
    assert isinstance(run_at, datetime)


def _settings(*adapter_keys: str) -> WorkerSettings:
    values = {
        "WORKER_ENABLED_ADAPTER_KEYS": ",".join(adapter_keys),
        "SOURCE_SAMPLE_DATA_ENABLED": "true",
        "FRESHNESS_MAX_AGE_SECONDS": "86400",
    }
    if "official.cwa.heavy_rain_warning" in adapter_keys:
        values.update(
            {
                "SOURCE_CWA_HEAVY_RAIN_WARNING_ENABLED": "true",
                "SOURCE_CWA_HEAVY_RAIN_WARNING_API_ENABLED": "true",
                "SOURCE_CWA_HEAVY_RAIN_WARNING_CONTRACT_ENABLED": "true",
                "CWA_API_AUTHORIZATION": "fixture-authorization-value",
            }
        )
    return load_worker_settings(values)


def _run_task9_managed(adapter: Any):
    key = adapter.metadata.key
    settings = replace(
        _settings(key),
        enabled_adapter_keys=(key,),
        source_ncdr_cap_enabled=True,
        source_ncdr_cap_contract_enabled=key == "official.ncdr.cap",
        source_wra_historical_flood_enabled=(
            True if key == "official.wra.historical_flood" else None
        ),
        freshness_max_age_seconds=24 * 60 * 60,
    )
    return run_v1_baseline_adapter_cycle(
        {key: adapter},
        settings=settings,
        staging_writer=_MemoryStagingWriter(),
        run_writer=_MemoryRunWriter(),
        source_catalog_reader=_StaticCatalogReader(enabled=frozenset({key})),
        promote=False,
    )


def _sample_adapter(
    *,
    source_id: str = "sample-news-001",
) -> SamplePublicWebNewsAdapter:
    return SamplePublicWebNewsAdapter(
        [
            {
                "id": source_id,
                "url": f"https://example.test/news/{source_id}",
                "title": "Street flooding reported near riverside district",
                "summary": "Public report describes street flooding near the riverside district.",
                "published_at": FETCHED_AT.isoformat(),
                "location_text": "Riverside District",
                "confidence": 0.72,
            }
        ],
        fetched_at=FETCHED_AT,
        raw_snapshot_key="raw/news-public-web/sample.json",
    )


def _candidate() -> PromotionCandidate:
    return PromotionCandidate(
        staging_evidence_id="staging-id",
        raw_snapshot_id="raw-snapshot-id",
        raw_ref="raw/news-public-web/sample.json",
        data_source_id="data-source-id",
        source_id="sample-news-001",
        source_type="news",
        event_type="flood_report",
        title="Street flooding reported near riverside district",
        summary="Public report describes street flooding near the riverside district.",
        url="https://example.test/news/sample-news-001",
        occurred_at=FETCHED_AT,
        observed_at=FETCHED_AT,
        confidence=0.72,
        validation_status="accepted",
        payload={"adapter_key": "news.public_web.sample"},
    )


class _MemoryStagingWriter:
    def __init__(self) -> None:
        self.batches: list[AdapterStagingBatch] = []

    def write_batch(self, batch: AdapterStagingBatch) -> None:
        self.batches.append(batch)


class _MemoryRunWriter:
    def __init__(self, *, timeline: list[str] | None = None) -> None:
        self.calls: list[tuple[AdapterBatchRunSummary, str, dict[str, Any] | None]] = []
        self.runtime_selections: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
        self.pipeline_statuses: list[tuple[tuple[str, ...], str, bool, datetime | None]] = []
        self.snapshot_activations: list[str | None] = []
        self.timeline = timeline

    def write_summary(
        self,
        summary: AdapterBatchRunSummary,
        *,
        job_key: str,
        parameters: dict[str, Any] | None = None,
    ) -> None:
        self.calls.append((summary, job_key, parameters))
        if self.timeline is not None:
            self.timeline.append("summary")

    def write_runtime_selection(
        self,
        *,
        enabled_adapter_keys: tuple[str, ...],
        known_adapter_keys: tuple[str, ...],
        checked_at: datetime,
    ) -> None:
        del checked_at
        self.runtime_selections.append((enabled_adapter_keys, known_adapter_keys))

    def write_pipeline_status(
        self,
        *,
        adapter_keys: tuple[str, ...],
        status: str,
        complete: bool,
        checked_at: datetime,
        run_at: datetime | None,
        active_snapshot_raw_ref: str | None = None,
    ) -> None:
        del checked_at
        self.pipeline_statuses.append((adapter_keys, status, complete, run_at))
        self.snapshot_activations.append(active_snapshot_raw_ref)


class _FailingSummaryMemoryRunWriter(_MemoryRunWriter):
    def write_summary(
        self,
        summary: AdapterBatchRunSummary,
        *,
        job_key: str,
        parameters: dict[str, Any] | None = None,
    ) -> None:
        del summary, job_key, parameters
        raise RuntimeError("audit summary unavailable")


class _MemoryPromotionWriter:
    def __init__(
        self,
        candidates: list[PromotionCandidate],
        *,
        timeline: list[str] | None = None,
    ) -> None:
        self._candidates = tuple(candidates)
        self.requested_limit: int | None = None
        self.requested_adapter_keys: tuple[str, ...] | None = None
        self.requested_raw_refs: tuple[str, ...] | None = None
        self.fetch_calls = 0
        self.payloads: list[EvidencePromotionPayload] = []
        self.retired_no_active: list[tuple[str, datetime, datetime]] = []
        self.timeline = timeline

    def fetch_accepted_staging(
        self,
        *,
        limit: int | None = None,
        adapter_keys: tuple[str, ...] | None = None,
        raw_refs: tuple[str, ...] | None = None,
    ) -> tuple[PromotionCandidate, ...]:
        self.fetch_calls += 1
        self.requested_limit = limit
        self.requested_adapter_keys = adapter_keys
        self.requested_raw_refs = raw_refs
        return self._candidates

    def write_evidence(self, payload: EvidencePromotionPayload) -> str | None:
        self.payloads.append(payload)
        return f"evidence-{len(self.payloads)}"

    def retire_warning_latest_for_no_active_event(
        self,
        *,
        adapter_key: str,
        generation_started_at: datetime,
        completed_at: datetime,
    ) -> int:
        self.retired_no_active.append((adapter_key, generation_started_at, completed_at))
        if self.timeline is not None:
            self.timeline.append("retire")
        return 0


class _StagingBackedWarningPromotionWriter(_MemoryPromotionWriter):
    def __init__(self, staging_writer: _MemoryStagingWriter) -> None:
        super().__init__([])
        self._staging_writer = staging_writer
        self.existing_warning_latest = True
        self.retired_references: list[str] = []

    def fetch_accepted_staging(
        self,
        *,
        limit: int | None = None,
        adapter_keys: tuple[str, ...] | None = None,
        raw_refs: tuple[str, ...] | None = None,
    ) -> tuple[PromotionCandidate, ...]:
        self.requested_limit = limit
        self.requested_adapter_keys = adapter_keys
        self.requested_raw_refs = raw_refs
        if not self._staging_writer.batches:
            return ()
        staged = self._staging_writer.batches[0].accepted[0]
        return (
            PromotionCandidate(
                staging_evidence_id="nested-staging-id",
                raw_snapshot_id=None,
                raw_ref=staged.raw_ref,
                data_source_id=None,
                source_id=staged.source_id,
                source_type=staged.source_type,
                event_type=staged.event_type,
                title=staged.title,
                summary=staged.summary,
                url=staged.url,
                occurred_at=staged.occurred_at,
                observed_at=staged.observed_at,
                confidence=staged.confidence,
                validation_status=staged.validation_status,
                payload={**staged.payload, "adapter_key": staged.adapter_key},
            ),
        )

    def write_evidence(self, payload: EvidencePromotionPayload) -> str | None:
        evidence_id = super().write_evidence(payload)
        if (
            payload.adapter_key == "official.cwa.heavy_rain_warning"
            and payload.properties.get("cap_message_type") == "Update"
        ):
            self.retired_references.append("existing-warning")
            self.existing_warning_latest = False
        return evidence_id


class _FailingNoActiveRetirementWriter(_MemoryPromotionWriter):
    def retire_warning_latest_for_no_active_event(
        self,
        *,
        adapter_key: str,
        generation_started_at: datetime,
        completed_at: datetime,
    ) -> int:
        del adapter_key, generation_started_at, completed_at
        raise RuntimeError(_PRIVATE_DATABASE_ERROR)


class _FailingPromotionWriter:
    def fetch_accepted_staging(
        self,
        *,
        limit: int | None = None,
        adapter_keys: tuple[str, ...] | None = None,
        raw_refs: tuple[str, ...] | None = None,
    ) -> tuple[PromotionCandidate, ...]:
        del limit, adapter_keys, raw_refs
        raise RuntimeError("promotion storage unavailable")

    def write_evidence(self, payload: EvidencePromotionPayload) -> str | None:
        del payload
        raise AssertionError("write_evidence should not be reached")


class QueryCanceled(RuntimeError):
    pass


class _TimeoutPromotionWriter(_FailingPromotionWriter):
    def fetch_accepted_staging(
        self,
        *,
        limit: int | None = None,
        adapter_keys: tuple[str, ...] | None = None,
        raw_refs: tuple[str, ...] | None = None,
    ) -> tuple[PromotionCandidate, ...]:
        del limit, adapter_keys, raw_refs
        raise QueryCanceled(_PRIVATE_DATABASE_ERROR)


class _RetryOncePromotionWriter(_MemoryPromotionWriter):
    def fetch_accepted_staging(
        self,
        *,
        limit: int | None = None,
        adapter_keys: tuple[str, ...] | None = None,
        raw_refs: tuple[str, ...] | None = None,
    ) -> tuple[PromotionCandidate, ...]:
        if self.fetch_calls == 0:
            self.fetch_calls += 1
            import psycopg

            raise psycopg.OperationalError(_PRIVATE_DATABASE_ERROR)
        return super().fetch_accepted_staging(
            limit=limit,
            adapter_keys=adapter_keys,
            raw_refs=raw_refs,
        )


class _ExplodingAdapter:
    def __init__(self, key: str) -> None:
        self.metadata = AdapterMetadata(
            key=key,
            family=SourceFamily.OFFICIAL,
            enabled_by_default=True,
            display_name=f"{key} test adapter",
        )

    def run(self) -> AdapterRunResult:
        raise AssertionError(f"{self.metadata.key} should not run")

    def fetch(self) -> tuple[RawSourceItem, ...]:
        raise AssertionError(f"{self.metadata.key} should not fetch")

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        del raw_item
        raise AssertionError(f"{self.metadata.key} should not normalize")


class _CatalogCountingAdapter:
    metadata = AdapterMetadata(
        key="official.cwa.heavy_rain_warning",
        family=SourceFamily.OFFICIAL,
        enabled_by_default=False,
        display_name="Catalog counting warning adapter",
    )

    def __init__(self, calls: dict[str, int]) -> None:
        self.calls = calls

    def run(self) -> AdapterRunResult:
        self.calls["run"] += 1
        return AdapterRunResult(adapter_key=self.metadata.key, fetched=(), normalized=())

    def fetch(self) -> tuple[RawSourceItem, ...]:
        return ()

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        del raw_item
        return None


class _StaticCatalogReader:
    def __init__(self, *, enabled: frozenset[str]) -> None:
        self.enabled = enabled

    def enabled_keys(self, adapter_keys: tuple[str, ...]) -> frozenset[str]:
        return self.enabled.intersection(adapter_keys)


class _FailingCatalogReader:
    def enabled_keys(self, adapter_keys: tuple[str, ...]) -> frozenset[str]:
        del adapter_keys
        raise RuntimeError("postgresql://catalog-secret@catalog-unavailable")


class _FailingCatalogAuditWriter:
    def write_runtime_selection(
        self,
        *,
        enabled_adapter_keys: tuple[str, ...],
        known_adapter_keys: tuple[str, ...],
        checked_at: datetime,
    ) -> None:
        del enabled_adapter_keys, known_adapter_keys, checked_at
        raise RuntimeError("postgresql://audit-secret@catalog-unavailable")

    def write_pipeline_status(
        self,
        *,
        adapter_keys: tuple[str, ...],
        status: str,
        complete: bool,
        checked_at: datetime,
        run_at: datetime | None,
        active_snapshot_raw_ref: str | None = None,
    ) -> None:
        del adapter_keys, status, complete, checked_at, run_at, active_snapshot_raw_ref
        raise RuntimeError("postgresql://audit-secret@catalog-unavailable")


class _Task9EmptyWarningAdapter:
    def __init__(self, key: str, *, no_active_event: bool) -> None:
        self.metadata = AdapterMetadata(
            key=key,
            family=SourceFamily.OFFICIAL,
            enabled_by_default=False,
            display_name=f"{key} empty warning fixture",
        )
        self.no_active_event = no_active_event

    def run(self) -> AdapterRunResult:
        return AdapterRunResult(
            adapter_key=self.metadata.key,
            fetched=(),
            normalized=(),
            no_active_event=self.no_active_event,
        )

    def fetch(self) -> tuple[RawSourceItem, ...]:
        return ()

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        del raw_item
        return None


class _Task9CancelOnlyNcdrAdapter:
    metadata = AdapterMetadata(
        key="official.ncdr.cap",
        family=SourceFamily.OFFICIAL,
        enabled_by_default=False,
        display_name="NCDR cancel-only fixture",
        snapshot_generation_mode="complete_replace",
    )

    def run(self) -> AdapterRunResult:
        reference_sent = FETCHED_AT - timedelta(minutes=10)
        raw = RawSourceItem(
            source_id="ncdr-cancel-only",
            source_url="https://alerts.ncdr.nat.gov.tw/cancel-only.cap",
            fetched_at=FETCHED_AT,
            payload={
                "evidence_scope": "current",
                "location_precision": "admin_area",
                "admin_code": "67035000",
                "cap_sender": "ncdr@example.test",
                "cap_identifier": "ncdr-cancel-only",
                "cap_sent": FETCHED_AT.isoformat(),
                "cap_references": [
                    {
                        "sender": "ncdr@example.test",
                        "identifier": "ncdr-alert-before-cancel",
                        "sent": reference_sent.isoformat(),
                    }
                ],
                "cap_status": "Actual",
                "cap_message_type": "Cancel",
                "active_from": reference_sent.isoformat(),
                "active_until": (FETCHED_AT + timedelta(hours=1)).isoformat(),
            },
        )
        normalized = NormalizedEvidence(
            evidence_id="official.ncdr.cap:ncdr-cancel-only",
            adapter_key=self.metadata.key,
            source_family=SourceFamily.OFFICIAL,
            event_type=EventType.FLOOD_WARNING,
            source_id=raw.source_id,
            source_url=raw.source_url,
            source_title="NCDR cancellation",
            source_timestamp=FETCHED_AT,
            fetched_at=FETCHED_AT,
            summary="The previous CAP warning was cancelled.",
            location_text="臺南市安南區",
            confidence=0.95,
        )
        return AdapterRunResult(
            adapter_key=self.metadata.key,
            fetched=(raw,),
            normalized=(normalized,),
            no_active_event=True,
        )

    def fetch(self) -> tuple[RawSourceItem, ...]:
        return self.run().fetched

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        del raw_item
        return self.run().normalized[0]


class _Task9MismatchedResultKeyAdapter(_Task9EmptyWarningAdapter):
    def __init__(self) -> None:
        super().__init__("official.cwa.heavy_rain_warning", no_active_event=True)

    def run(self) -> AdapterRunResult:
        return AdapterRunResult(
            adapter_key="official.ncdr.cap",
            fetched=(),
            normalized=(),
            no_active_event=True,
        )


class _Task9MalformedEmptyWarningAdapter(_Task9EmptyWarningAdapter):
    def __init__(self, malformation: str) -> None:
        super().__init__("official.cwa.heavy_rain_warning", no_active_event=True)
        self.malformation = malformation

    def run(self) -> AdapterRunResult:
        normalized: tuple[NormalizedEvidence, ...] = ()
        inventory_proof: StationInventoryProof | None = None
        if self.malformation == "normalized":
            normalized = (
                NormalizedEvidence(
                    evidence_id="task9-malformed-empty",
                    adapter_key=self.metadata.key,
                    source_family=SourceFamily.OFFICIAL,
                    event_type=EventType.FLOOD_WARNING,
                    source_id="task9-malformed-empty",
                    source_url="https://example.test/cap",
                    source_title="Malformed empty warning",
                    source_timestamp=FETCHED_AT,
                    fetched_at=FETCHED_AT,
                    summary="Normalized evidence contradicts the empty poll marker.",
                    location_text="臺南市",
                    confidence=0.95,
                ),
            )
        else:
            inventory_proof = StationInventoryProof(
                upstream_total=0,
                pages_fetched=1,
                pagination_complete=True,
                source_items_seen=0,
                missing_station_id_count=0,
                duplicate_station_id_count=0,
                station_ids=(),
            )
        return AdapterRunResult(
            adapter_key=self.metadata.key,
            fetched=(),
            normalized=normalized,
            station_inventory_proof=inventory_proof,
            no_active_event=True,
        )


class _NestedWarningIdentityAdapter:
    metadata = AdapterMetadata(
        key="official.cwa.rainfall",
        family=SourceFamily.OFFICIAL,
        enabled_by_default=False,
        display_name="Nested warning identity mismatch fixture",
    )

    def run(self) -> AdapterRunResult:
        sent_at = FETCHED_AT
        raw_item = RawSourceItem(
            source_id="nested-warning-update",
            source_url="https://example.test/cap",
            fetched_at=FETCHED_AT,
            payload={
                "evidence_scope": "current",
                "location_precision": "admin_area",
                "admin_code": "67000000",
                "cap_sender": "sender@example.test",
                "cap_identifier": "nested-warning-update",
                "cap_sent": sent_at.isoformat(),
                "cap_references": [
                    {
                        "sender": "sender@example.test",
                        "identifier": "existing-warning",
                        "sent": (sent_at - timedelta(minutes=1)).isoformat(),
                    }
                ],
                "cap_status": "Actual",
                "cap_message_type": "Update",
                "active_from": (sent_at - timedelta(minutes=5)).isoformat(),
                "active_until": (sent_at + timedelta(hours=1)).isoformat(),
            },
        )
        normalized = NormalizedEvidence(
            evidence_id="nested-warning-update",
            adapter_key="official.cwa.heavy_rain_warning",
            source_family=SourceFamily.OFFICIAL,
            event_type=EventType.FLOOD_WARNING,
            source_id=raw_item.source_id,
            source_url=raw_item.source_url,
            source_title="Forged nested warning Update",
            source_timestamp=sent_at,
            fetched_at=FETCHED_AT,
            summary="A rainfall result must not smuggle a warning lifecycle mutation.",
            location_text="臺南市",
            confidence=0.95,
        )
        return AdapterRunResult(
            adapter_key=self.metadata.key,
            fetched=(raw_item,),
            normalized=(normalized,),
        )

    def fetch(self) -> tuple[RawSourceItem, ...]:
        return self.run().fetched

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        del raw_item
        return self.run().normalized[0]


class _Task9ActiveWarningAdapter:
    def __init__(
        self,
        key: str,
        *,
        sent_at: datetime,
        active_from: datetime,
        active_until: datetime,
    ) -> None:
        self.metadata = AdapterMetadata(
            key=key,
            family=SourceFamily.OFFICIAL,
            enabled_by_default=False,
            display_name=f"{key} active warning fixture",
        )
        self.sent_at = sent_at
        self.active_from = active_from
        self.active_until = active_until

    def run(self) -> AdapterRunResult:
        raw_item = RawSourceItem(
            source_id=f"{self.metadata.key}:warning-1",
            source_url="https://example.test/cap",
            fetched_at=FETCHED_AT,
            payload={
                "evidence_scope": "current",
                "location_precision": "admin_area",
                "admin_code": "67000000",
                "cap_sender": "sender@example.test",
                "cap_identifier": "warning-1",
                "cap_sent": self.sent_at.isoformat(),
                "cap_references": [],
                "cap_status": "Actual",
                "cap_message_type": "Alert",
                "active_from": self.active_from.isoformat(),
                "active_until": self.active_until.isoformat(),
            },
        )
        evidence = NormalizedEvidence(
            evidence_id=f"{self.metadata.key}:warning-evidence-1",
            adapter_key=self.metadata.key,
            source_family=SourceFamily.OFFICIAL,
            event_type=EventType.FLOOD_WARNING,
            source_id=raw_item.source_id,
            source_url=raw_item.source_url,
            source_title="Task 9 active warning",
            source_timestamp=self.sent_at,
            fetched_at=FETCHED_AT,
            summary="Task 9 synthetic active warning.",
            location_text="臺南市",
            confidence=0.95,
        )
        return AdapterRunResult(
            adapter_key=self.metadata.key,
            fetched=(raw_item,),
            normalized=(evidence,),
        )

    def fetch(self) -> tuple[RawSourceItem, ...]:
        return self.run().fetched

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        del raw_item
        return self.run().normalized[0]


class _Task9MultiWindowWarningAdapter:
    def __init__(
        self,
        key: str,
        *,
        windows: tuple[tuple[datetime, datetime], ...],
    ) -> None:
        self.metadata = AdapterMetadata(
            key=key,
            family=SourceFamily.OFFICIAL,
            enabled_by_default=False,
            display_name=f"{key} multi-window fixture",
        )
        self.windows = windows

    def run(self) -> AdapterRunResult:
        fetched: list[RawSourceItem] = []
        normalized: list[NormalizedEvidence] = []
        for index, (active_from, active_until) in enumerate(self.windows, start=1):
            sent_at = active_from
            raw_item = RawSourceItem(
                source_id=f"{self.metadata.key}:warning-{index}",
                source_url="https://example.test/cap",
                fetched_at=FETCHED_AT,
                payload={
                    "evidence_scope": "current",
                    "location_precision": "admin_area",
                    "admin_code": "67000000",
                    "cap_sender": "sender@example.test",
                    "cap_identifier": f"warning-{index}",
                    "cap_sent": sent_at.isoformat(),
                    "cap_references": [],
                    "cap_status": "Actual",
                    "cap_message_type": "Alert",
                    "active_from": active_from.isoformat(),
                    "active_until": active_until.isoformat(),
                },
            )
            fetched.append(raw_item)
            normalized.append(
                NormalizedEvidence(
                    evidence_id=f"{self.metadata.key}:warning-evidence-{index}",
                    adapter_key=self.metadata.key,
                    source_family=SourceFamily.OFFICIAL,
                    event_type=EventType.FLOOD_WARNING,
                    source_id=raw_item.source_id,
                    source_url=raw_item.source_url,
                    source_title="Task 9 warning window",
                    source_timestamp=sent_at,
                    fetched_at=FETCHED_AT,
                    summary="Task 9 synthetic warning window.",
                    location_text="臺南市",
                    confidence=0.95,
                )
            )
        return AdapterRunResult(
            adapter_key=self.metadata.key,
            fetched=tuple(fetched),
            normalized=tuple(normalized),
        )

    def fetch(self) -> tuple[RawSourceItem, ...]:
        return self.run().fetched

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        result = self.run()
        return next(
            (
                normalized
                for normalized in result.normalized
                if normalized.source_id == raw_item.source_id
            ),
            None,
        )


class _Task9HistoricalAdapter:
    metadata = AdapterMetadata(
        key="official.wra.historical_flood",
        family=SourceFamily.OFFICIAL,
        enabled_by_default=False,
        display_name="WRA historical flood Task 9 fixture",
    )

    def __init__(self, *, event_observed_at: datetime) -> None:
        self.event_observed_at = event_observed_at

    def run(self) -> AdapterRunResult:
        raw_item = RawSourceItem(
            source_id="wra-history-1",
            source_url="https://example.test/wra/history",
            fetched_at=FETCHED_AT,
            payload={"event_observed_at": self.event_observed_at.isoformat()},
        )
        evidence = NormalizedEvidence(
            evidence_id="wra-history-evidence-1",
            adapter_key=self.metadata.key,
            source_family=SourceFamily.OFFICIAL,
            event_type=EventType.FLOOD_REPORT,
            source_id=raw_item.source_id,
            source_url=raw_item.source_url,
            source_title="Historical flood",
            source_timestamp=self.event_observed_at,
            fetched_at=FETCHED_AT,
            summary="Historical flood record.",
            location_text="臺南市",
            confidence=0.9,
        )
        return AdapterRunResult(
            adapter_key=self.metadata.key,
            fetched=(raw_item,),
            normalized=(evidence,),
        )

    def fetch(self) -> tuple[RawSourceItem, ...]:
        return self.run().fetched

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        del raw_item
        return self.run().normalized[0]


class _CompleteReplacePartialAdapter:
    metadata = AdapterMetadata(
        key="official.wra.historical_flood",
        family=SourceFamily.OFFICIAL,
        enabled_by_default=False,
        display_name="Complete-replace partial fixture",
        snapshot_generation_mode="complete_replace",
    )

    def __init__(self, *, valid_count: int, rejection_count: int) -> None:
        self.valid_count = valid_count
        self.rejection_count = rejection_count

    def run(self) -> AdapterRunResult:
        fetched_count = self.valid_count + self.rejection_count
        fetched = tuple(
            RawSourceItem(
                source_id=f"historical-{index}",
                source_url=f"https://example.test/history/{index}",
                fetched_at=FETCHED_AT,
                payload={"dataset_revision": "revision-a"},
            )
            for index in range(fetched_count)
        )
        normalized = tuple(
            NormalizedEvidence(
                evidence_id=f"historical-evidence-{index}",
                adapter_key=self.metadata.key,
                source_family=SourceFamily.OFFICIAL,
                event_type=EventType.FLOOD_REPORT,
                source_id=fetched[index].source_id,
                source_url=fetched[index].source_url,
                source_title="Historical flood",
                source_timestamp=FETCHED_AT,
                fetched_at=FETCHED_AT,
                summary="Complete-replace source-quality partial fixture.",
                location_text="臺南市",
                confidence=0.9,
            )
            for index in range(self.valid_count)
        )
        return AdapterRunResult(
            adapter_key=self.metadata.key,
            fetched=fetched,
            normalized=normalized,
            rejected=tuple(item.source_id for item in fetched[self.valid_count :]),
        )

    def fetch(self) -> tuple[RawSourceItem, ...]:
        return self.run().fetched

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        return next(
            (
                evidence
                for evidence in self.run().normalized
                if evidence.source_id == raw_item.source_id
            ),
            None,
        )


class _SuccessfulAdapter:
    def __init__(
        self,
        key: str,
        *,
        family: SourceFamily,
        event_type: EventType,
        raw_ref: str,
    ) -> None:
        self.metadata = AdapterMetadata(
            key=key,
            family=family,
            enabled_by_default=True,
            display_name=f"{key} test adapter",
        )
        self._event_type = event_type
        self._raw_ref = raw_ref

    def run(self) -> AdapterRunResult:
        raw_item = RawSourceItem(
            source_id=f"{self.metadata.key}:source",
            source_url=f"https://example.test/{self.metadata.key}",
            fetched_at=FETCHED_AT,
            payload={"title": self.metadata.display_name},
            raw_snapshot_key=self._raw_ref,
        )
        evidence = NormalizedEvidence(
            evidence_id=f"{self.metadata.key}:evidence",
            adapter_key=self.metadata.key,
            source_family=self.metadata.family,
            event_type=self._event_type,
            source_id=raw_item.source_id,
            source_url=raw_item.source_url,
            source_title=self.metadata.display_name,
            source_timestamp=FETCHED_AT,
            fetched_at=FETCHED_AT,
            summary=f"{self.metadata.display_name} summary",
            location_text=None,
            confidence=0.8,
            status=IngestionStatus.NORMALIZED,
        )
        return AdapterRunResult(
            adapter_key=self.metadata.key,
            fetched=(raw_item,),
            normalized=(evidence,),
            rejected=(),
        )

    def fetch(self) -> tuple[RawSourceItem, ...]:
        return self.run().fetched

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        del raw_item
        return self.run().normalized[0]
