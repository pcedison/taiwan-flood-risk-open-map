from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app import scheduler as scheduler_module
from app.config import load_worker_settings
from app.jobs.official_demo import build_official_demo_adapters
from app.jobs.runtime import (
    RuntimeQueueProducerResult,
    RuntimeQueueWorkerResult,
    build_runtime_adapters,
)
from app.main import main
from app.scheduler import (
    ScheduledIngestionCycleResult,
    run_enabled_adapters_loop,
    run_enabled_adapters_once,
    run_scheduled_ingestion_cycle,
)


def test_official_demo_builder_covers_default_official_adapter_keys() -> None:
    adapters = build_official_demo_adapters(
        fetched_at=datetime(2026, 4, 30, 4, 0, tzinfo=UTC)
    )

    assert set(adapters) == {
        "official.cwa.rainfall",
        "official.wra.water_level",
        "official.flood_potential.geojson",
    }


def test_scheduler_official_demo_cycle_runs_ingestion_and_freshness() -> None:
    fetched_at = datetime.now(UTC)
    result = run_scheduled_ingestion_cycle(
        build_official_demo_adapters(fetched_at=fetched_at),
        settings=load_worker_settings({"FRESHNESS_MAX_AGE_SECONDS": "21600"}),
        job_key="test.scheduler.official_demo",
    )

    assert [summary.status for summary in result.summaries] == [
        "succeeded",
        "succeeded",
        "succeeded",
    ]
    assert [check.status for check in result.freshness_checks] == [
        "fresh",
        "fresh",
        "fresh",
    ]
    assert not result.has_alerts


def test_main_run_official_demo_is_a_cli_entrypoint() -> None:
    exit_code = main(["--run-official-demo"])

    assert exit_code == 0


def test_main_run_enabled_adapters_noops_without_runtime_fixtures() -> None:
    exit_code = main(["--run-enabled-adapters"])

    assert exit_code == 0


def test_main_scheduler_can_run_bounded_runtime_loop(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_loop(*args: object, **kwargs: object) -> tuple[ScheduledIngestionCycleResult, ...]:
        del args
        captured["max_ticks"] = kwargs["max_ticks"]
        return (
            ScheduledIngestionCycleResult(summaries=(), freshness_checks=()),
            ScheduledIngestionCycleResult(summaries=(), freshness_checks=()),
        )

    monkeypatch.setattr("app.main.run_enabled_adapters_loop", fake_loop)

    exit_code = main(["--scheduler", "--max-ticks", "2"])

    assert exit_code == 0
    assert captured["max_ticks"] == 2


def test_main_work_runtime_queue_once_is_a_cli_entrypoint(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_work_once(*args: object, **kwargs: object) -> RuntimeQueueWorkerResult:
        del args
        captured["settings"] = kwargs["settings"]
        return RuntimeQueueWorkerResult(status="skipped", reason="no_job")

    monkeypatch.setattr("app.main.work_runtime_queue_once", fake_work_once)

    exit_code = main(["--work-runtime-queue", "--once"])

    assert exit_code == 0
    assert captured["settings"] is not None


def test_main_enqueue_runtime_jobs_is_a_cli_entrypoint(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_enqueue_once(*args: object, **kwargs: object) -> RuntimeQueueProducerResult:
        del args
        captured["settings"] = kwargs["settings"]
        return RuntimeQueueProducerResult(
            status="succeeded",
            adapter_keys=("official.cwa.rainfall",),
            job_ids=("job-1",),
        )

    monkeypatch.setattr("app.main.enqueue_enabled_adapters_once", fake_enqueue_once)

    exit_code = main(["--enqueue-runtime-jobs"])

    assert exit_code == 0
    assert captured["settings"] is not None


def test_main_scheduler_enqueue_runtime_jobs_can_be_bounded(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_enqueue_loop(*args: object, **kwargs: object) -> tuple[RuntimeQueueProducerResult, ...]:
        del args
        captured["max_ticks"] = kwargs["max_ticks"]
        return (
            RuntimeQueueProducerResult(status="skipped", reason="no_database_url"),
            RuntimeQueueProducerResult(status="skipped", reason="no_database_url"),
        )

    monkeypatch.setattr("app.main.enqueue_enabled_adapters_loop", fake_enqueue_loop)

    exit_code = main(["--enqueue-runtime-jobs", "--scheduler", "--max-ticks", "2"])

    assert exit_code == 0
    assert captured["max_ticks"] == 2


def test_scheduler_cli_enqueue_runtime_jobs_uses_lease_guarded_loop(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_enqueue_loop(*args: object, **kwargs: object) -> tuple[RuntimeQueueProducerResult, ...]:
        del args
        captured["max_ticks"] = kwargs["max_ticks"]
        return (RuntimeQueueProducerResult(status="skipped", reason="no_database_url"),)

    def fail_enqueue_once(*args: object, **kwargs: object) -> RuntimeQueueProducerResult:
        del args, kwargs
        raise AssertionError("scheduler CLI producer path must use the lease-guarded loop")

    monkeypatch.setattr(scheduler_module, "enqueue_enabled_adapters_loop", fake_enqueue_loop)
    monkeypatch.setattr(scheduler_module, "enqueue_enabled_adapters_once", fail_enqueue_once)

    exit_code = scheduler_module.main(("--enqueue-runtime-jobs", "--max-ticks", "2"))

    assert exit_code == 0
    assert captured["max_ticks"] == 2


def test_main_run_official_demo_does_not_persist_by_default(monkeypatch) -> None:
    def fail_constructor(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("default official demo must not construct DB writers")

    monkeypatch.setattr("app.main.PostgresStagingBatchWriter", fail_constructor)
    monkeypatch.setattr("app.main.PostgresIngestionRunWriter", fail_constructor)
    monkeypatch.setattr("app.main.PostgresEvidencePromotionWriter", fail_constructor)

    exit_code = main(["--run-official-demo"])

    assert exit_code == 0


def test_runtime_adapters_require_fixture_mode() -> None:
    settings = load_worker_settings({})

    assert build_runtime_adapters(settings) == {}


def test_runtime_adapters_fixture_mode_supplies_official_adapters() -> None:
    settings = load_worker_settings({"WORKER_RUNTIME_FIXTURES_ENABLED": "true"})

    assert set(build_runtime_adapters(settings)) == {
        "official.cwa.rainfall",
        "official.wra.water_level",
        "official.flood_potential.geojson",
    }


def test_run_enabled_adapters_once_uses_configured_adapter_selection() -> None:
    settings = load_worker_settings(
        {
            "WORKER_ENABLED_ADAPTER_KEYS": "official.wra.water_level",
            "WORKER_RUNTIME_FIXTURES_ENABLED": "true",
            "FRESHNESS_MAX_AGE_SECONDS": "21600",
        }
    )

    result = run_enabled_adapters_once(settings=settings, job_key="test.runtime.run_once")

    assert [summary.adapter_key for summary in result.summaries] == [
        "official.wra.water_level"
    ]
    assert [check.adapter_key for check in result.freshness_checks] == [
        "official.wra.water_level"
    ]


def test_run_enabled_adapters_once_writes_worker_heartbeat_textfile(tmp_path: Path) -> None:
    metrics_path = tmp_path / "worker.prom"
    settings = load_worker_settings(
        {
            "WORKER_ENABLED_ADAPTER_KEYS": "official.cwa.rainfall",
            "WORKER_RUNTIME_FIXTURES_ENABLED": "true",
            "WORKER_INSTANCE": "test-worker",
            "WORKER_METRICS_TEXTFILE_PATH": str(metrics_path),
            "FRESHNESS_MAX_AGE_SECONDS": "21600",
        }
    )

    result = run_enabled_adapters_once(settings=settings, job_key="test.runtime.metrics")

    assert not result.has_alerts
    text = metrics_path.read_text(encoding="utf-8")
    assert "flood_risk_worker_heartbeat_timestamp_seconds" in text
    assert 'instance="test-worker"' in text
    assert 'queue="official.cwa.rainfall"' in text
    assert 'job="test.runtime.metrics"' in text
    assert 'status="succeeded"} 1' in text


def test_run_enabled_adapters_once_gracefully_noops_disabled_adapter() -> None:
    settings = load_worker_settings(
        {
            "WORKER_ENABLED_ADAPTER_KEYS": "news.public_web.sample",
            "WORKER_RUNTIME_FIXTURES_ENABLED": "true",
        }
    )

    result = run_enabled_adapters_once(settings=settings, job_key="test.runtime.noop")

    assert result.summaries == ()
    assert result.freshness_checks == ()
    assert not result.has_alerts


def test_run_enabled_adapters_loop_can_be_bounded() -> None:
    settings = load_worker_settings(
        {
            "WORKER_ENABLED_ADAPTER_KEYS": "official.cwa.rainfall",
            "WORKER_RUNTIME_FIXTURES_ENABLED": "true",
        }
    )
    sleeps: list[int] = []

    results = run_enabled_adapters_loop(settings=settings, max_ticks=2, sleep=sleeps.append)

    assert len(results) == 2
    assert sleeps == [settings.scheduler_interval_seconds]


def test_run_enabled_adapters_loop_writes_scheduler_heartbeat_textfile(tmp_path: Path) -> None:
    metrics_path = tmp_path / "scheduler.prom"
    settings = load_worker_settings(
        {
            "WORKER_ENABLED_ADAPTER_KEYS": "official.cwa.rainfall",
            "WORKER_RUNTIME_FIXTURES_ENABLED": "true",
            "WORKER_INSTANCE": "test-scheduler",
            "SCHEDULER_METRICS_TEXTFILE_PATH": str(metrics_path),
            "FRESHNESS_MAX_AGE_SECONDS": "21600",
        }
    )

    results = run_enabled_adapters_loop(settings=settings, max_ticks=1)

    assert len(results) == 1
    text = metrics_path.read_text(encoding="utf-8")
    assert "flood_risk_scheduler_heartbeat_timestamp_seconds" in text
    assert 'instance="test-scheduler"' in text
    assert 'scheduler="enabled-adapters"' in text
    assert 'status="succeeded"} 1' in text


def test_main_run_official_demo_persist_writes_staging_runs_and_promotes(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_cycle(*args: object, **kwargs: object) -> ScheduledIngestionCycleResult:
        del args
        captured["writer"] = kwargs["writer"]
        captured["run_writer"] = kwargs["run_writer"]
        return ScheduledIngestionCycleResult(summaries=(), freshness_checks=())

    def fake_promote(
        writer: object,
        *,
        adapter_keys: tuple[str, ...] | None = None,
    ) -> object:
        captured["promotion_writer"] = writer
        captured["promotion_adapter_keys"] = adapter_keys
        return _PromotionResult()

    monkeypatch.setattr("app.main.run_scheduled_ingestion_cycle", fake_cycle)
    monkeypatch.setattr("app.main.promote_accepted_staging", fake_promote)
    monkeypatch.setattr("app.main.PostgresStagingBatchWriter", _FakeStagingWriter)
    monkeypatch.setattr("app.main.PostgresIngestionRunWriter", _FakeRunWriter)
    monkeypatch.setattr("app.main.PostgresEvidencePromotionWriter", _FakePromotionWriter)

    exit_code = main(
        [
            "--run-official-demo",
            "--persist",
            "--database-url",
            "postgresql://worker:test@localhost/flood",
        ]
    )

    assert exit_code == 0
    assert isinstance(captured["writer"], _FakeStagingWriter)
    assert isinstance(captured["run_writer"], _FakeRunWriter)
    assert isinstance(captured["promotion_writer"], _FakePromotionWriter)
    writer = captured["writer"]
    assert isinstance(writer, _FakeStagingWriter)
    assert writer.database_url == "postgresql://worker:test@localhost/flood"
    assert captured["promotion_adapter_keys"] == (
        "official.cwa.rainfall",
        "official.wra.water_level",
        "official.flood_potential.geojson",
    )


def test_main_aggregate_query_heat_uses_configured_periods(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeQueryHeatAggregationJob:
        def __init__(self, *, database_url: str) -> None:
            captured["database_url"] = database_url

        def aggregate(
            self,
            *,
            periods: tuple[str, ...],
            created_at_start: datetime | None,
            created_at_end: datetime | None,
        ) -> tuple[object, ...]:
            captured["periods"] = periods
            captured["created_at_start"] = created_at_start
            captured["created_at_end"] = created_at_end
            return (_QueryHeatSummary(period="P7D", buckets_upserted=2),)

        def prune_retention(
            self,
            *,
            periods: tuple[str, ...],
            retention_days: int,
        ) -> object:
            captured["retention_periods"] = periods
            captured["retention_days"] = retention_days
            return _QueryHeatRetentionSummary(buckets_pruned=1)

    monkeypatch.setenv("WORKER_DATABASE_URL", "postgresql://worker:test@localhost/flood")
    monkeypatch.setattr("app.main.PostgresQueryHeatAggregationJob", FakeQueryHeatAggregationJob)

    exit_code = main(
        [
            "--aggregate-query-heat",
            "--query-heat-periods",
            "P7D,P1D,P7D",
            "--query-heat-created-at-start",
            "2026-04-23T00:00:00Z",
            "--query-heat-created-at-end",
            "2026-04-30T00:00:00+00:00",
            "--query-heat-retention-days",
            "14",
        ]
    )

    assert exit_code == 0
    assert captured == {
        "database_url": "postgresql://worker:test@localhost/flood",
        "periods": ("P7D", "P1D"),
        "created_at_start": datetime(2026, 4, 23, 0, 0, tzinfo=UTC),
        "created_at_end": datetime(2026, 4, 30, 0, 0, tzinfo=UTC),
        "retention_periods": ("P7D", "P1D"),
        "retention_days": 14,
    }


def test_main_aggregate_query_heat_noops_without_database_url(monkeypatch) -> None:
    def fail_constructor(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("query heat aggregation should no-op without a database URL")

    monkeypatch.delenv("WORKER_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr("app.main.PostgresQueryHeatAggregationJob", fail_constructor)

    assert main(["--aggregate-query-heat"]) == 0


def test_main_refresh_tile_features_uses_layer_and_limit(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeTileCacheWriter:
        def __init__(self, *, database_url: str) -> None:
            captured["database_url"] = database_url

        def refresh_layer_features(self, *, layer_id: str, limit: int | None = None) -> object:
            captured["layer_id"] = layer_id
            captured["limit"] = limit
            return _TileRefreshResult(layer_id=layer_id, refreshed=3)

    monkeypatch.setenv("WORKER_DATABASE_URL", "postgresql://worker:test@localhost/flood")
    monkeypatch.setattr("app.main.PostgresTileCacheWriter", FakeTileCacheWriter)

    exit_code = main(
        [
            "--refresh-tile-features",
            "--tile-layer-id",
            "flood-potential",
            "--tile-feature-limit",
            "25",
        ]
    )

    assert exit_code == 0
    assert captured == {
        "database_url": "postgresql://worker:test@localhost/flood",
        "layer_id": "flood-potential",
        "limit": 25,
    }


def test_main_refresh_tile_features_noops_without_database_url(monkeypatch) -> None:
    def fail_constructor(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("tile feature refresh should no-op without a database URL")

    monkeypatch.delenv("WORKER_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr("app.main.PostgresTileCacheWriter", fail_constructor)

    assert main(["--refresh-tile-features"]) == 0


class _FakeStagingWriter:
    def __init__(self, *, database_url: str) -> None:
        self.database_url = database_url


class _FakeRunWriter:
    def __init__(self, *, database_url: str) -> None:
        self.database_url = database_url


class _FakePromotionWriter:
    def __init__(self, *, database_url: str) -> None:
        self.database_url = database_url


class _PromotionResult:
    promoted = 1
    evidence_ids = ("evidence-1",)


class _QueryHeatSummary:
    def __init__(self, *, period: str, buckets_upserted: int) -> None:
        self.period = period
        self.buckets_upserted = buckets_upserted


class _QueryHeatRetentionSummary:
    def __init__(self, *, buckets_pruned: int) -> None:
        self.buckets_pruned = buckets_pruned


class _TileRefreshResult:
    def __init__(self, *, layer_id: str, refreshed: int) -> None:
        self.layer_id = layer_id
        self.refreshed = refreshed
