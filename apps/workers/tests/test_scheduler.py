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
        "STAGING_EVIDENCE_RETENTION_DAYS": "7",
        "STAGING_EVIDENCE_RETENTION_MAX_BATCHES": "4",
        "STAGING_EVIDENCE_RETENTION_BATCH_SIZE": "2500",
        "STAGING_EVIDENCE_RETENTION_STATEMENT_TIMEOUT_MS": "6000",
        "SCHEDULER_MAX_TICKS": "1",
    }
)


class RecordingEvidenceRetentionJob:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []
        self.staging_max_batches: int | None = None
        self.staging_kwargs: dict[str, object] = {}

    def prune_realtime(self, *, retention_hours: int) -> object:
        self.calls.append(("prune_realtime", retention_hours))
        return SimpleNamespace(rows_deleted=2)

    def prune_location_queries(self, *, retention_hours: int) -> object:
        self.calls.append(("prune_location_queries", retention_hours))
        return SimpleNamespace(rows_deleted=3)

    def prune_expired_raw_snapshots(self) -> object:
        self.calls.append(("prune_expired_raw_snapshots", 0))
        return SimpleNamespace(rows_deleted=4)

    def prune_staging_evidence(
        self,
        *,
        retention_days: int,
        batch_size: int,
        max_batches: int,
        statement_timeout_ms: int,
        ensure_index: bool,
    ) -> object:
        self.calls.append(("prune_staging_evidence", retention_days))
        self.staging_max_batches = max_batches
        self.staging_kwargs = {
            "batch_size": batch_size,
            "statement_timeout_ms": statement_timeout_ms,
            "ensure_index": ensure_index,
        }
        return SimpleNamespace(
            deleted_rows=5,
            batches=1,
            index_state="ready",
            stopped_reason="exhausted",
        )


class RecordingIndexMaintenanceJob:
    """Stands in for the concurrent rebuild so no test opens a real socket."""

    def __init__(self, outcome: str = "skipped_outside_window") -> None:
        self.outcome = outcome
        self.calls: list[dict[str, object]] = []

    def reindex_evidence_indexes(self, **kwargs: object) -> object:
        self.calls.append(dict(kwargs))
        return SimpleNamespace(
            outcome=self.outcome,
            index=None if self.outcome != "reindexed" else "idx_evidence_geom",
        )


@pytest.fixture(autouse=True)
def _stub_index_maintenance(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default every test to a no-op rebuild pass.

    Without this the maintenance cycle would try to dial the fake database URL
    whenever the suite happens to run inside the 18:00-21:00 UTC window, which
    is a real-clock dependency no unit test should carry. Tests that care about
    the rebuild pass patch it again themselves; the later patch wins.
    """

    monkeypatch.setattr(
        scheduler,
        "PostgresIndexMaintenanceJob",
        lambda **_kwargs: RecordingIndexMaintenanceJob(),
    )


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
        ("prune_expired_raw_snapshots", 0),
        ("prune_staging_evidence", SETTINGS.staging_evidence_retention_days),
    ]
    assert retention.staging_max_batches == (
        SETTINGS.staging_evidence_retention_max_batches
    )
    assert result.staging_evidence_retention is not None
    assert result.staging_evidence_retention.deleted_rows == 5
    assert retention.staging_kwargs == {
        "batch_size": SETTINGS.staging_evidence_retention_batch_size,
        "statement_timeout_ms": (
            SETTINGS.staging_evidence_retention_statement_timeout_ms
        ),
        "ensure_index": SETTINGS.staging_evidence_retention_ensure_index,
    }


def test_scheduler_maintenance_skips_staging_retention_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = load_worker_settings(
        {
            "WORKER_DATABASE_URL": "postgresql://worker:test@localhost/flood",
            "STAGING_EVIDENCE_RETENTION_ENABLED": "false",
        }
    )
    retention = RecordingEvidenceRetentionJob()
    monkeypatch.setattr(
        scheduler, "PostgresEvidenceRetentionJob", lambda **_kwargs: retention
    )

    result = scheduler.run_maintenance_once(settings=settings)

    assert result.status == "succeeded"
    assert result.staging_evidence_retention is None
    assert "prune_staging_evidence" not in [name for name, _ in retention.calls]


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
        ("prune_expired_raw_snapshots", 0),
        ("prune_staging_evidence", 7),
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


def test_scheduler_maintenance_reindexes_after_the_staging_prune(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The rebuild is the last thing a cycle does, and it is pure housekeeping.

    A concurrent rebuild is the longest step in the cycle, so it must never sit
    in front of the retention passes that keep the node's disk bounded.
    """

    order: list[str] = []

    class OrderingRetentionJob(RecordingEvidenceRetentionJob):
        def prune_staging_evidence(self, **kwargs: object) -> object:
            order.append("staging_prune")
            return super().prune_staging_evidence(**kwargs)  # type: ignore[arg-type]

    reindex = RecordingIndexMaintenanceJob(outcome="reindexed")

    def build_reindex_job(**kwargs: object) -> RecordingIndexMaintenanceJob:
        order.append("reindex")
        assert kwargs == {"database_url": SETTINGS.database_url}
        return reindex

    monkeypatch.setattr(
        scheduler, "PostgresEvidenceRetentionJob", lambda **_kwargs: OrderingRetentionJob()
    )
    monkeypatch.setattr(scheduler, "PostgresIndexMaintenanceJob", build_reindex_job)

    result = scheduler.run_maintenance_once(settings=SETTINGS)

    assert result.status == "succeeded"
    assert order == ["staging_prune", "reindex"]
    assert result.evidence_reindex is not None
    assert result.evidence_reindex.outcome == "reindexed"
    assert reindex.calls == [
        {
            "index_names": SETTINGS.evidence_index_reindex_indexes,
            "window_utc": SETTINGS.evidence_index_reindex_window_utc,
            "interval_hours": SETTINGS.evidence_index_reindex_interval_hours,
            "min_size_bytes": SETTINGS.evidence_index_reindex_min_size_bytes,
            "max_index_bytes": SETTINGS.evidence_index_reindex_max_index_bytes,
            "lock_timeout_ms": SETTINGS.evidence_index_reindex_lock_timeout_ms,
            "statement_timeout_ms": (
                SETTINGS.evidence_index_reindex_statement_timeout_ms
            ),
        }
    ]

    completed = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if '"scheduler.maintenance.completed"' in line
    ]
    assert completed[-1]["evidence_reindex_outcome"] == "reindexed"
    assert completed[-1]["evidence_reindex_index"] == "idx_evidence_geom"
    # Backward compatible: the staging fields the runbook and dashboards read
    # are untouched.
    assert completed[-1]["staging_evidence_stopped_reason"] == "exhausted"
    assert completed[-1]["staging_evidence_rows_pruned"] == 5


def test_scheduler_maintenance_reports_a_disabled_reindex_pass(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = load_worker_settings(
        {
            "WORKER_DATABASE_URL": "postgresql://worker:test@localhost/flood",
            "EVIDENCE_INDEX_REINDEX_ENABLED": "false",
        }
    )
    monkeypatch.setattr(
        scheduler,
        "PostgresEvidenceRetentionJob",
        lambda **_kwargs: RecordingEvidenceRetentionJob(),
    )
    monkeypatch.setattr(
        scheduler,
        "PostgresIndexMaintenanceJob",
        lambda **_kwargs: pytest.fail("rebuild pass constructed while disabled"),
    )

    result = scheduler.run_maintenance_once(settings=settings)

    assert result.status == "succeeded"
    assert result.evidence_reindex is None
    completed = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if '"scheduler.maintenance.completed"' in line
    ]
    assert completed[-1]["evidence_reindex_outcome"] == "disabled"
    assert completed[-1]["evidence_reindex_index"] is None


def test_scheduler_maintenance_survives_a_misconfigured_reindex_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An operator typo in an env var must not stop retention from running."""

    settings = load_worker_settings(
        {
            "WORKER_DATABASE_URL": "postgresql://worker:test@localhost/flood",
            "EVIDENCE_INDEX_REINDEX_WINDOW_UTC": "sometime at night",
        }
    )
    retention = RecordingEvidenceRetentionJob()

    class ExplodingIndexMaintenanceJob:
        def reindex_evidence_indexes(self, **kwargs: object) -> object:
            del kwargs
            raise ValueError("invalid maintenance window 'sometime at night'")

    monkeypatch.setattr(scheduler, "PostgresEvidenceRetentionJob", lambda **_k: retention)
    monkeypatch.setattr(
        scheduler,
        "PostgresIndexMaintenanceJob",
        lambda **_kwargs: ExplodingIndexMaintenanceJob(),
    )

    result = scheduler.run_maintenance_once(settings=settings)

    assert result.status == "succeeded"
    assert result.evidence_reindex is None
    assert ("prune_staging_evidence", 7) in retention.calls
