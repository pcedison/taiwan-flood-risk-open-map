from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app import scheduler
from app.config import load_worker_settings
from app.jobs import runtime as runtime_jobs
from app.jobs import runtime_managed as runtime_managed_jobs

SETTINGS = load_worker_settings(
    {
        "WORKER_DATABASE_URL": "postgresql://worker:test@localhost/flood",
        "EVIDENCE_REALTIME_RETENTION_HOURS": "72",
        "LOCATION_QUERIES_RETENTION_HOURS": "24",
        "SCHEDULER_MAX_TICKS": "1",
    }
)


class RecordingEvidenceRetentionJob:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def prune_realtime(self, *, retention_hours: int) -> object:
        self.calls.append(("prune_realtime", retention_hours))
        return SimpleNamespace(rows_deleted=2)

    def prune_location_queries(self, *, retention_hours: int) -> object:
        self.calls.append(("prune_location_queries", retention_hours))
        return SimpleNamespace(rows_deleted=3)


def test_scheduler_maintenance_keeps_privacy_retention_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        scheduler,
        "PostgresQueryHeatAggregationJob",
        lambda *_args, **_kwargs: pytest.fail("query heat writer constructed"),
    )
    monkeypatch.setattr(
        scheduler,
        "PostgresTileCacheWriter",
        lambda *_args, **_kwargs: pytest.fail("tile writer constructed"),
    )
    retention = RecordingEvidenceRetentionJob()
    monkeypatch.setattr(scheduler, "PostgresEvidenceRetentionJob", lambda **_kwargs: retention)

    result = scheduler.run_maintenance_once(settings=SETTINGS)

    assert result.status == "succeeded"
    assert result.query_heat_summaries == ()
    assert result.query_heat_retention is None
    assert result.tile_refresh is None
    assert result.tile_prune is None
    assert retention.calls == [
        ("prune_realtime", SETTINGS.evidence_realtime_retention_hours),
        ("prune_location_queries", SETTINGS.location_queries_retention_hours),
    ]


def test_scheduler_maintenance_loop_never_constructs_generic_runtime_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORKER_DATABASE_URL", SETTINGS.database_url or "")
    monkeypatch.setenv(
        "EVIDENCE_REALTIME_RETENTION_HOURS",
        str(SETTINGS.evidence_realtime_retention_hours),
    )
    monkeypatch.setenv(
        "LOCATION_QUERIES_RETENTION_HOURS",
        str(SETTINGS.location_queries_retention_hours),
    )
    monkeypatch.setattr(
        scheduler,
        "PostgresRuntimeQueue",
        lambda *_args, **_kwargs: pytest.fail("generic runtime queue constructed"),
    )
    retention = RecordingEvidenceRetentionJob()
    monkeypatch.setattr(scheduler, "PostgresEvidenceRetentionJob", lambda **_kwargs: retention)

    assert scheduler.main(("--maintenance", "--once")) == 0
    assert retention.calls == [
        ("prune_realtime", SETTINGS.evidence_realtime_retention_hours),
        ("prune_location_queries", SETTINGS.location_queries_retention_hours),
    ]


@pytest.mark.parametrize(
    "surface",
    [
        "run_scheduled_ingestion_cycle",
        "run_enabled_adapters_once",
        "run_enabled_adapters_loop",
        "enqueue_enabled_adapters_once",
        "enqueue_enabled_adapters_loop",
    ],
)
def test_public_scheduler_generic_helpers_freeze_before_construction(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    surface: str,
) -> None:
    def fail_construction(*_args: object, **_kwargs: object) -> object:
        pytest.fail(f"generic runtime construction reached from {surface}")

    monkeypatch.setattr(scheduler, "run_enabled_adapter_batches", fail_construction)
    monkeypatch.setattr(scheduler, "build_runtime_adapters", fail_construction)
    monkeypatch.setattr(scheduler, "PostgresRuntimeQueue", fail_construction)
    monkeypatch.setattr(runtime_jobs, "PostgresIngestionRunWriter", fail_construction)

    calls = {
        "run_scheduled_ingestion_cycle": lambda: scheduler.run_scheduled_ingestion_cycle(
            {}, settings=SETTINGS
        ),
        "run_enabled_adapters_once": lambda: scheduler.run_enabled_adapters_once(
            settings=SETTINGS
        ),
        "run_enabled_adapters_loop": lambda: scheduler.run_enabled_adapters_loop(
            settings=SETTINGS, max_ticks=1
        ),
        "enqueue_enabled_adapters_once": lambda: scheduler.enqueue_enabled_adapters_once(
            settings=SETTINGS
        ),
        "enqueue_enabled_adapters_loop": lambda: scheduler.enqueue_enabled_adapters_loop(
            settings=SETTINGS, max_ticks=1
        ),
    }

    assert calls[surface]() == 2
    assert json.loads(capsys.readouterr().out) == {
        "reason": "v1_legacy_product_writers_frozen",
        "status": "frozen",
        "tables_retained": True,
    }


def test_public_managed_runtime_facade_freezes_before_writer_construction(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        runtime_managed_jobs,
        "PostgresIngestionRunWriter",
        lambda *_args, **_kwargs: pytest.fail("managed runtime writer constructed"),
    )

    assert runtime_managed_jobs.run_managed_runtime_ingestion_cycle(
        settings=SETTINGS
    ) == 2
    assert json.loads(capsys.readouterr().out) == {
        "reason": "v1_legacy_product_writers_frozen",
        "status": "frozen",
        "tables_retained": True,
    }


def test_executable_generic_engines_use_private_nonlegacy_names() -> None:
    assert not hasattr(
        runtime_managed_jobs, "_legacy_run_managed_runtime_ingestion_cycle"
    )
    assert hasattr(runtime_managed_jobs, "_execute_managed_runtime_ingestion_cycle")
    for surface in (
        "run_scheduled_ingestion_cycle",
        "run_enabled_adapters_once",
        "run_enabled_adapters_loop",
        "enqueue_enabled_adapters_once",
        "enqueue_enabled_adapters_loop",
    ):
        assert not hasattr(scheduler, f"_legacy_{surface}")
        assert hasattr(scheduler, f"_execute_{surface.removeprefix('run_')}")


@pytest.mark.parametrize(
    "argv",
    [
        ("--run-enabled-adapters", "--once"),
        ("--enqueue-runtime-jobs", "--once"),
        ("--official-demo", "--once"),
        ("--maintenance", "--official-demo", "--once"),
        ("--maintenance", "--enqueue-runtime-jobs", "--once"),
        ("--once",),
    ],
)
def test_scheduler_never_dispatches_generic_runtime_paths(
    monkeypatch: pytest.MonkeyPatch,
    argv: tuple[str, ...],
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        scheduler,
        "run_enabled_adapters_once",
        lambda **_kwargs: pytest.fail("generic runtime dispatched"),
    )
    monkeypatch.setattr(
        scheduler,
        "enqueue_enabled_adapters_loop",
        lambda **_kwargs: pytest.fail("generic queue enqueued"),
    )
    monkeypatch.setattr(
        scheduler,
        "run_scheduled_ingestion_cycle",
        lambda *_args, **_kwargs: pytest.fail("official demo dispatched"),
    )
    assert scheduler.main(argv) == 2
    assert '"status": "frozen"' in capsys.readouterr().out


def test_scheduler_help_marks_legacy_maintenance_options_frozen_and_ignored(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        scheduler.main(("--help",))

    assert exc_info.value.code == 0
    help_text = capsys.readouterr().out
    normalized_help = " ".join(help_text.split()).lower()
    for option in (
        "--query-heat-periods",
        "--query-heat-retention-days",
        "--tile-layer-id",
        "--tile-feature-limit",
        "--tile-prune-limit",
    ):
        option_position = normalized_help.rfind(option)
        assert option_position >= 0
        option_help = normalized_help[option_position : option_position + 180]
        assert "frozen" in option_help
        assert "ignored" in option_help


def test_scheduler_maintenance_failure_is_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingRetentionJob(RecordingEvidenceRetentionJob):
        def prune_location_queries(self, *, retention_hours: int) -> object:
            del retention_hours
            raise scheduler.EvidenceRetentionUnavailable("retention unavailable")

    monkeypatch.setattr(
        scheduler,
        "PostgresEvidenceRetentionJob",
        lambda **_kwargs: FailingRetentionJob(),
    )

    result = scheduler.run_maintenance_once(settings=SETTINGS)

    assert result.status == "failed"
    assert result.reason == "retention unavailable"
