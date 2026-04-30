from __future__ import annotations

from datetime import UTC, datetime

from app.config import load_worker_settings
from app.jobs.official_demo import build_official_demo_adapters
from app.main import main
from app.scheduler import ScheduledIngestionCycleResult, run_scheduled_ingestion_cycle


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
    fetched_at = datetime(2026, 4, 30, 4, 0, tzinfo=UTC)
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


def test_main_run_official_demo_does_not_persist_by_default(monkeypatch) -> None:
    def fail_constructor(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("default official demo must not construct DB writers")

    monkeypatch.setattr("app.main.PostgresStagingBatchWriter", fail_constructor)
    monkeypatch.setattr("app.main.PostgresIngestionRunWriter", fail_constructor)
    monkeypatch.setattr("app.main.PostgresEvidencePromotionWriter", fail_constructor)

    exit_code = main(["--run-official-demo"])

    assert exit_code == 0


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
