from __future__ import annotations

from types import SimpleNamespace

import pytest

from app import scheduler
from app.config import load_worker_settings

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
    monkeypatch.setattr(
        scheduler,
        "run_sample_job",
        lambda **_kwargs: pytest.fail("generic scheduler placeholder dispatched"),
    )

    assert scheduler.main(argv) == 2
    assert '"status": "frozen"' in capsys.readouterr().out


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
