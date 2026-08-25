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
EXPECTED_V1_BASELINE_ADAPTER_KEYS = (
    "official.cwa.rainfall",
    "official.cwa.heavy_rain_warning",
    "official.wra.water_level",
    "official.wra_iow.flood_depth",
    "official.wra.historical_flood",
    "official.ncdr.cap",
    "official.flood_potential.geojson",
    "local.tainan.flood_sensor",
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
    result = _run_task9_managed(
        _Task9EmptyWarningAdapter(adapter_key, no_active_event=True)
    )

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
def test_managed_historical_flood_preserves_event_time_with_background_freshness() -> None:
    event_observed_at = FETCHED_AT - timedelta(days=3650)
    result = _run_task9_managed(
        _Task9HistoricalAdapter(event_observed_at=event_observed_at)
    )

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
        load_worker_settings({}),
        enabled_adapter_keys=(adapter.metadata.key,),
    )

    result = run_v1_baseline_adapter_cycle(
        {adapter.metadata.key: adapter},
        settings=settings,
        staging_writer=_MemoryStagingWriter(),
        run_writer=run_writer,
        promotion_writer=promotion_writer,
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


@pytest.mark.usefixtures("task9_synthetic_registry")
def test_managed_no_active_retirement_is_not_called_when_promotion_disabled() -> None:
    adapter = _Task9EmptyWarningAdapter(
        "official.cwa.heavy_rain_warning",
        no_active_event=True,
    )
    promotion_writer = _MemoryPromotionWriter([])
    settings = replace(
        load_worker_settings({}),
        enabled_adapter_keys=(adapter.metadata.key,),
    )

    result = run_v1_baseline_adapter_cycle(
        {adapter.metadata.key: adapter},
        settings=settings,
        staging_writer=_MemoryStagingWriter(),
        run_writer=_MemoryRunWriter(),
        promotion_writer=promotion_writer,
        promote=False,
    )

    assert result.status == "succeeded"
    assert promotion_writer.retired_no_active == []


@pytest.mark.usefixtures("task9_synthetic_registry")
def test_managed_no_active_retirement_failure_returns_failed_result() -> None:
    adapter = _Task9EmptyWarningAdapter(
        "official.cwa.heavy_rain_warning",
        no_active_event=True,
    )
    settings = replace(
        load_worker_settings({}),
        enabled_adapter_keys=(adapter.metadata.key,),
    )

    result = run_v1_baseline_adapter_cycle(
        {adapter.metadata.key: adapter},
        settings=settings,
        staging_writer=_MemoryStagingWriter(),
        run_writer=_MemoryRunWriter(),
        promotion_writer=_FailingNoActiveRetirementWriter([]),
        promote=True,
    )

    assert result.status == "failed"
    assert result.reason == "no_active_event_retirement_failed"
    assert result.error_code == "RuntimeError"


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

    assert runtime_managed_jobs.V1_BASELINE_ADAPTER_KEYS == (
        EXPECTED_V1_BASELINE_ADAPTER_KEYS
    )
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
    for key, (_mapping, kwargs) in zip(
        EXPECTED_V1_BASELINE_ADAPTER_KEYS, calls, strict=True
    ):
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
    return load_worker_settings(
        {
            "WORKER_ENABLED_ADAPTER_KEYS": ",".join(adapter_keys),
            "SOURCE_SAMPLE_DATA_ENABLED": "true",
            "FRESHNESS_MAX_AGE_SECONDS": "86400",
        }
    )


def _run_task9_managed(adapter: Any):
    key = adapter.metadata.key
    settings = replace(
        load_worker_settings({}),
        enabled_adapter_keys=(key,),
        source_ncdr_cap_enabled=True,
        freshness_max_age_seconds=24 * 60 * 60,
    )
    return run_v1_baseline_adapter_cycle(
        {key: adapter},
        settings=settings,
        staging_writer=_MemoryStagingWriter(),
        run_writer=_MemoryRunWriter(),
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
        self.pipeline_statuses: list[
            tuple[tuple[str, ...], str, bool, datetime | None]
        ] = []
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
    ) -> None:
        del checked_at
        self.pipeline_statuses.append((adapter_keys, status, complete, run_at))


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
        self.payloads: list[EvidencePromotionPayload] = []
        self.retired_no_active: list[tuple[str, datetime, datetime]] = []
        self.timeline = timeline

    def fetch_accepted_staging(
        self,
        *,
        limit: int | None = None,
        adapter_keys: tuple[str, ...] | None = None,
    ) -> tuple[PromotionCandidate, ...]:
        self.requested_limit = limit
        self.requested_adapter_keys = adapter_keys
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
        self.retired_no_active.append(
            (adapter_key, generation_started_at, completed_at)
        )
        if self.timeline is not None:
            self.timeline.append("retire")
        return 0


class _FailingNoActiveRetirementWriter(_MemoryPromotionWriter):
    def retire_warning_latest_for_no_active_event(
        self,
        *,
        adapter_key: str,
        generation_started_at: datetime,
        completed_at: datetime,
    ) -> int:
        del adapter_key, generation_started_at, completed_at
        raise RuntimeError("retirement storage unavailable")


class _FailingPromotionWriter:
    def fetch_accepted_staging(
        self,
        *,
        limit: int | None = None,
        adapter_keys: tuple[str, ...] | None = None,
    ) -> tuple[PromotionCandidate, ...]:
        del limit, adapter_keys
        raise RuntimeError("promotion storage unavailable")

    def write_evidence(self, payload: EvidencePromotionPayload) -> str | None:
        del payload
        raise AssertionError("write_evidence should not be reached")


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
