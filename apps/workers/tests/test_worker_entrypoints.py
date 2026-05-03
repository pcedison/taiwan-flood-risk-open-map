from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from app import scheduler as scheduler_module
from app.config import load_worker_settings
from app.jobs.official_demo import build_official_demo_adapters
from app.jobs.queue import (
    RuntimeQueueDeadLetterJob,
    RuntimeQueueDeadLetterSummary,
    RuntimeQueueMetricsSnapshot,
    RuntimeQueueUnavailable,
)
from app.jobs.replay_audit import AuditedRuntimeQueueRequeueResult
from app.jobs.runtime import (
    RuntimeQueueProducerResult,
    RuntimeQueueWorkerResult,
    build_runtime_adapters,
)
from app.main import main
from app.scheduler import (
    MaintenanceCycleResult,
    ScheduledIngestionCycleResult,
    run_enabled_adapters_loop,
    run_enabled_adapters_once,
    run_maintenance_loop,
    run_maintenance_once,
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


def test_main_work_runtime_queue_persist_wires_runtime_writers(monkeypatch) -> None:
    captured: dict[str, object] = {}
    persistence = (
        _FakeStagingWriter(database_url="postgresql://worker:test@localhost/flood"),
        _FakeRunWriter(database_url="postgresql://worker:test@localhost/flood"),
        _FakePromotionWriter(database_url="postgresql://worker:test@localhost/flood"),
    )

    def fake_build_writers(database_url: str) -> tuple[object, object, object]:
        captured["writer_database_url"] = database_url
        return persistence

    def fake_work_once(*args: object, **kwargs: object) -> RuntimeQueueWorkerResult:
        del args
        captured["writer"] = kwargs["writer"]
        captured["run_writer"] = kwargs["run_writer"]
        captured["promotion_writer"] = kwargs["promotion_writer"]
        captured["promote"] = kwargs["promote"]
        return RuntimeQueueWorkerResult(status="succeeded", promoted=1)

    monkeypatch.setattr("app.main.build_runtime_persistence_writers", fake_build_writers)
    monkeypatch.setattr("app.main.work_runtime_queue_once", fake_work_once)

    exit_code = main(
        [
            "--work-runtime-queue",
            "--once",
            "--persist",
            "--database-url",
            "postgresql://worker:test@localhost/flood",
        ]
    )

    assert exit_code == 0
    assert captured == {
        "writer_database_url": "postgresql://worker:test@localhost/flood",
        "writer": persistence[0],
        "run_writer": persistence[1],
        "promotion_writer": persistence[2],
        "promote": True,
    }


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


def test_main_list_runtime_dead_letter_jobs_prints_json_lines(monkeypatch, capsys) -> None:
    captured: dict[str, object] = {}
    final_failed_at = datetime(2026, 4, 30, 8, 0, tzinfo=UTC)

    class FakeRuntimeQueue:
        def __init__(self, *, database_url: str) -> None:
            captured["database_url"] = database_url

        def list_dead_letter_jobs(
            self,
            *,
            queue_name: str | None = None,
            limit: int = 100,
        ) -> tuple[RuntimeQueueDeadLetterJob, ...]:
            captured["queue_name"] = queue_name
            captured["limit"] = limit
            return (
                RuntimeQueueDeadLetterJob(
                    id="job-1",
                    queue_name="runtime-adapters",
                    job_key="runtime.adapter.ingest",
                    adapter_key="official.cwa.rainfall",
                    payload={"adapter_key": "official.cwa.rainfall"},
                    attempts=3,
                    max_attempts=3,
                    last_error="source timeout",
                    final_failed_at=final_failed_at,
                    dedupe_key="runtime-adapters:runtime.adapter.ingest:official.cwa.rainfall",
                ),
            )

    monkeypatch.setenv("WORKER_DATABASE_URL", "postgresql://worker:test@localhost/flood")
    monkeypatch.setattr("app.main.PostgresRuntimeQueue", FakeRuntimeQueue)
    monkeypatch.setattr("app.main.log_event", lambda *args, **kwargs: None)

    exit_code = main(
        [
            "--list-runtime-dead-letter-jobs",
            "--dead-letter-queue-name",
            "runtime-adapters",
            "--dead-letter-limit",
            "25",
        ]
    )

    assert exit_code == 0
    assert captured == {
        "database_url": "postgresql://worker:test@localhost/flood",
        "queue_name": "runtime-adapters",
        "limit": 25,
    }
    output = capsys.readouterr().out.strip().splitlines()
    assert len(output) == 1
    row = json.loads(output[0])
    assert row["id"] == "job-1"
    assert row["attempts"] == 3
    assert row["max_attempts"] == 3
    assert row["last_error"] == "source timeout"
    assert row["final_failed_at"] == "2026-04-30T08:00:00+00:00"
    assert row["payload"] == {"adapter_key": "official.cwa.rainfall"}


def test_main_summarize_runtime_dead_letter_jobs_prints_json(monkeypatch, capsys) -> None:
    captured: dict[str, object] = {}
    oldest = datetime(2026, 4, 30, 7, 0, tzinfo=UTC)
    newest = datetime(2026, 4, 30, 8, 0, tzinfo=UTC)

    class FakeRuntimeQueue:
        def __init__(self, *, database_url: str) -> None:
            captured["database_url"] = database_url

        def summarize_dead_letter_jobs(
            self,
            *,
            queue_name: str | None = None,
        ) -> RuntimeQueueDeadLetterSummary:
            captured["queue_name"] = queue_name
            return RuntimeQueueDeadLetterSummary(
                queue_name=queue_name,
                failed_terminal_count=2,
                oldest_final_failed_at=oldest,
                newest_final_failed_at=newest,
                max_attempts_observed=5,
                max_configured_attempts=5,
            )

    monkeypatch.setenv("WORKER_DATABASE_URL", "postgresql://worker:test@localhost/flood")
    monkeypatch.setattr("app.main.PostgresRuntimeQueue", FakeRuntimeQueue)
    monkeypatch.setattr("app.main.log_event", lambda *args, **kwargs: None)

    exit_code = main(
        [
            "--summarize-runtime-dead-letter-jobs",
            "--dead-letter-queue-name",
            "runtime-adapters",
        ]
    )

    assert exit_code == 0
    assert captured == {
        "database_url": "postgresql://worker:test@localhost/flood",
        "queue_name": "runtime-adapters",
    }
    assert json.loads(capsys.readouterr().out) == {
        "available": True,
        "error": None,
        "failed_terminal_count": 2,
        "max_attempts_observed": 5,
        "max_configured_attempts": 5,
        "newest_final_failed_at": "2026-04-30T08:00:00+00:00",
        "oldest_final_failed_at": "2026-04-30T07:00:00+00:00",
        "queue_name": "runtime-adapters",
        "reason": None,
    }


def test_main_summarize_runtime_dead_letter_jobs_noops_without_database_url(
    monkeypatch,
    capsys,
) -> None:
    def fail_constructor(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("summary should not construct a queue without database URL")

    monkeypatch.delenv("WORKER_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr("app.main.PostgresRuntimeQueue", fail_constructor)

    exit_code = main(
        [
            "--summarize-runtime-dead-letter-jobs",
            "--dead-letter-queue-name",
            "runtime-adapters",
        ]
    )

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == {
        "available": False,
        "error": None,
        "failed_terminal_count": 0,
        "max_attempts_observed": None,
        "max_configured_attempts": None,
        "newest_final_failed_at": None,
        "oldest_final_failed_at": None,
        "queue_name": "runtime-adapters",
        "reason": "no_database_url",
    }


def test_main_summarize_runtime_dead_letter_jobs_reports_database_unavailable(
    monkeypatch,
    capsys,
) -> None:
    class FakeRuntimeQueue:
        def __init__(self, *, database_url: str) -> None:
            del database_url

        def summarize_dead_letter_jobs(
            self,
            *,
            queue_name: str | None = None,
        ) -> RuntimeQueueDeadLetterSummary:
            del queue_name
            raise RuntimeQueueUnavailable("database unavailable")

    monkeypatch.setenv("WORKER_DATABASE_URL", "postgresql://worker:test@localhost/flood")
    monkeypatch.setattr("app.main.PostgresRuntimeQueue", FakeRuntimeQueue)
    monkeypatch.setattr("app.main.log_event", lambda *args, **kwargs: None)

    exit_code = main(["--summarize-runtime-dead-letter-jobs"])

    assert exit_code == 1
    assert json.loads(capsys.readouterr().out) == {
        "available": False,
        "error": "database unavailable",
        "failed_terminal_count": 0,
        "max_attempts_observed": None,
        "max_configured_attempts": None,
        "newest_final_failed_at": None,
        "oldest_final_failed_at": None,
        "queue_name": None,
        "reason": "queue_unavailable",
    }


def test_main_export_runtime_queue_metrics_prints_prometheus(monkeypatch, capsys) -> None:
    captured: dict[str, object] = {}
    oldest = datetime(2026, 4, 30, 7, 0, tzinfo=UTC)

    class FakeRuntimeQueue:
        def __init__(self, *, database_url: str) -> None:
            captured["database_url"] = database_url

        def collect_metrics(
            self,
            *,
            queue_name: str | None = None,
        ) -> tuple[RuntimeQueueMetricsSnapshot, ...]:
            captured["queue_name"] = queue_name
            return (
                RuntimeQueueMetricsSnapshot(
                    queue_name=queue_name or "runtime-adapters",
                    queued_count=4,
                    running_count=2,
                    final_failed_count=1,
                    expired_lease_count=1,
                    oldest_final_failed_at=oldest,
                ),
            )

    monkeypatch.setenv("WORKER_DATABASE_URL", "postgresql://worker:test@localhost/flood")
    monkeypatch.setattr("app.main.PostgresRuntimeQueue", FakeRuntimeQueue)
    monkeypatch.setattr("app.main.log_event", lambda *args, **kwargs: None)

    exit_code = main(
        [
            "--export-runtime-queue-metrics",
            "--dead-letter-queue-name",
            "runtime-adapters",
        ]
    )

    assert exit_code == 0
    assert captured == {
        "database_url": "postgresql://worker:test@localhost/flood",
        "queue_name": "runtime-adapters",
    }
    output = capsys.readouterr().out
    assert "flood_risk_runtime_queue_metrics_available" in output
    assert "flood_risk_runtime_queue_final_failed_jobs" in output
    assert "flood_risk_runtime_queue_expired_leases" in output
    assert "dlq" not in output.lower()


def test_main_export_runtime_queue_metrics_writes_textfile(monkeypatch, tmp_path: Path) -> None:
    metrics_path = tmp_path / "runtime-queue.prom"

    class FakeRuntimeQueue:
        def __init__(self, *, database_url: str) -> None:
            del database_url

        def collect_metrics(
            self,
            *,
            queue_name: str | None = None,
        ) -> tuple[RuntimeQueueMetricsSnapshot, ...]:
            return (
                RuntimeQueueMetricsSnapshot(
                    queue_name=queue_name or "runtime-adapters",
                    queued_count=1,
                    running_count=0,
                    final_failed_count=0,
                    expired_lease_count=0,
                    oldest_final_failed_at=None,
                ),
            )

    monkeypatch.setenv("WORKER_DATABASE_URL", "postgresql://worker:test@localhost/flood")
    monkeypatch.setattr("app.main.PostgresRuntimeQueue", FakeRuntimeQueue)
    monkeypatch.setattr("app.main.log_event", lambda *args, **kwargs: None)

    exit_code = main(
        [
            "--export-runtime-queue-metrics",
            "--runtime-queue-metrics-path",
            str(metrics_path),
        ]
    )

    assert exit_code == 0
    text = metrics_path.read_text(encoding="utf-8")
    assert "flood_risk_runtime_queue_queued_jobs" in text
    assert 'queue_name="runtime-adapters"' in text


def test_main_export_runtime_queue_metrics_prints_json(monkeypatch, capsys) -> None:
    class FakeRuntimeQueue:
        def __init__(self, *, database_url: str) -> None:
            del database_url

        def collect_metrics(
            self,
            *,
            queue_name: str | None = None,
        ) -> tuple[RuntimeQueueMetricsSnapshot, ...]:
            return (
                RuntimeQueueMetricsSnapshot(
                    queue_name=queue_name or "runtime-adapters",
                    queued_count=4,
                    running_count=2,
                    final_failed_count=1,
                    expired_lease_count=1,
                    oldest_final_failed_at=datetime(2026, 4, 30, 7, 0, tzinfo=UTC),
                ),
            )

    monkeypatch.setenv("WORKER_DATABASE_URL", "postgresql://worker:test@localhost/flood")
    monkeypatch.setattr("app.main.PostgresRuntimeQueue", FakeRuntimeQueue)
    monkeypatch.setattr("app.main.log_event", lambda *args, **kwargs: None)

    exit_code = main(
        [
            "--export-runtime-queue-metrics",
            "--runtime-queue-metrics-format",
            "json",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["available"] is True
    assert payload["reason"] is None
    assert payload["queues"] == [
        {
            "expired_lease_count": 1,
            "final_failed_count": 1,
            "oldest_final_failed_at": "2026-04-30T07:00:00+00:00",
            "queue_name": "runtime-adapters",
            "queued_count": 4,
            "running_count": 2,
        }
    ]


def test_main_export_runtime_queue_metrics_noops_without_database_url(
    monkeypatch,
    capsys,
) -> None:
    def fail_constructor(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("metrics should not construct a queue without database URL")

    monkeypatch.delenv("WORKER_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr("app.main.PostgresRuntimeQueue", fail_constructor)
    monkeypatch.setattr("app.main.log_event", lambda *args, **kwargs: None)

    exit_code = main(
        [
            "--export-runtime-queue-metrics",
            "--runtime-queue-metrics-format",
            "json",
            "--dead-letter-queue-name",
            "runtime-adapters",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["available"] is False
    assert payload["reason"] == "no_database_url"
    assert payload["queues"][0]["queue_name"] == "runtime-adapters"
    assert payload["queues"][0]["final_failed_count"] == 0


def test_main_export_runtime_queue_metrics_no_db_prometheus_stdout_is_parseable(
    monkeypatch,
    capsys,
) -> None:
    def fail_constructor(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("metrics should not construct a queue without database URL")

    monkeypatch.delenv("WORKER_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr("app.main.PostgresRuntimeQueue", fail_constructor)

    exit_code = main(["--export-runtime-queue-metrics"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert output.startswith("# HELP flood_risk_runtime_queue_metrics_available")
    assert 'reason="no_database_url"' in output
    assert not output.startswith("{")


def test_main_export_runtime_queue_metrics_reports_database_unavailable(
    monkeypatch,
    capsys,
) -> None:
    class FakeRuntimeQueue:
        def __init__(self, *, database_url: str) -> None:
            del database_url

        def collect_metrics(
            self,
            *,
            queue_name: str | None = None,
        ) -> tuple[RuntimeQueueMetricsSnapshot, ...]:
            del queue_name
            raise RuntimeQueueUnavailable("database unavailable")

    monkeypatch.setenv("WORKER_DATABASE_URL", "postgresql://worker:test@localhost/flood")
    monkeypatch.setattr("app.main.PostgresRuntimeQueue", FakeRuntimeQueue)

    exit_code = main(
        [
            "--export-runtime-queue-metrics",
            "--runtime-queue-metrics-format",
            "json",
        ]
    )

    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["available"] is False
    assert payload["reason"] == "queue_unavailable"
    assert payload["error"] == "database unavailable"


def test_main_requeue_runtime_job_resets_attempts_by_default(monkeypatch, capsys) -> None:
    captured: dict[str, object] = {}

    class FakeReplayAudit:
        def __init__(self, *, database_url: str) -> None:
            captured["audit_database_url"] = database_url

        def requeue_failed_job_with_audit(
            self,
            *,
            job_id: str,
            requested_by: str,
            reason: str,
            reset_attempts: bool = True,
        ) -> AuditedRuntimeQueueRequeueResult:
            captured["job_id"] = job_id
            captured["requested_by"] = requested_by
            captured["reason"] = reason
            captured["reset_attempts"] = reset_attempts
            return AuditedRuntimeQueueRequeueResult(
                job_id=job_id,
                requeued=True,
                reset_attempts=reset_attempts,
                requested_audit_id="audit-requested",
                outcome_audit_id="audit-completed",
                attempts_before=3,
                attempts_after=0,
            )

    monkeypatch.setenv("WORKER_DATABASE_URL", "postgresql://worker:test@localhost/flood")
    monkeypatch.setattr("app.main.PostgresRuntimeQueue", _fail_constructor)
    monkeypatch.setattr("app.main.PostgresRuntimeQueueReplayAudit", FakeReplayAudit)
    monkeypatch.setattr("app.main.log_event", lambda *args, **kwargs: None)

    exit_code = main(
        [
            "--requeue-runtime-job",
            "job-1",
            "--requeue-requested-by",
            "operator@example.test",
            "--requeue-reason",
            "manual retry",
        ]
    )

    assert exit_code == 0
    assert captured["audit_database_url"] == "postgresql://worker:test@localhost/flood"
    assert captured["job_id"] == "job-1"
    assert captured["requested_by"] == "operator@example.test"
    assert captured["reason"] == "manual retry"
    assert captured["reset_attempts"] is True
    assert json.loads(capsys.readouterr().out) == {
        "attempts": 0,
        "attempts_before": 3,
        "job_id": "job-1",
        "outcome_audit_id": "audit-completed",
        "reason": None,
        "requested_audit_id": "audit-requested",
        "requeued": True,
        "reset_attempts": True,
    }


def test_main_requeue_runtime_job_can_keep_attempts_and_database_override(
    monkeypatch,
    capsys,
) -> None:
    captured: dict[str, object] = {}

    class FakeReplayAudit:
        def __init__(self, *, database_url: str) -> None:
            captured["audit_database_url"] = database_url

        def requeue_failed_job_with_audit(
            self,
            *,
            job_id: str,
            requested_by: str,
            reason: str,
            reset_attempts: bool = True,
        ) -> AuditedRuntimeQueueRequeueResult:
            captured["job_id"] = job_id
            captured["requested_by"] = requested_by
            captured["reason"] = reason
            captured["reset_attempts"] = reset_attempts
            return AuditedRuntimeQueueRequeueResult(
                job_id=job_id,
                requeued=True,
                reset_attempts=reset_attempts,
                requested_audit_id="audit-requested",
                outcome_audit_id="audit-completed",
                attempts_before=3,
                attempts_after=3,
            )

    monkeypatch.setenv("WORKER_DATABASE_URL", "postgresql://worker:test@localhost/flood")
    monkeypatch.setattr("app.main.PostgresRuntimeQueue", _fail_constructor)
    monkeypatch.setattr("app.main.PostgresRuntimeQueueReplayAudit", FakeReplayAudit)
    monkeypatch.setattr("app.main.log_event", lambda *args, **kwargs: None)

    exit_code = main(
        [
            "--requeue-runtime-job",
            "job-1",
            "--requeue-keep-attempts",
            "--requeue-requested-by",
            "operator@example.test",
            "--requeue-reason",
            "keep attempts after inspection",
            "--database-url",
            "postgresql://override:test@localhost/flood",
        ]
    )

    assert exit_code == 0
    assert captured["audit_database_url"] == "postgresql://override:test@localhost/flood"
    assert captured["job_id"] == "job-1"
    assert captured["requested_by"] == "operator@example.test"
    assert captured["reason"] == "keep attempts after inspection"
    assert captured["reset_attempts"] is False
    assert json.loads(capsys.readouterr().out) == {
        "attempts": 3,
        "attempts_before": 3,
        "job_id": "job-1",
        "outcome_audit_id": "audit-completed",
        "reason": None,
        "requested_audit_id": "audit-requested",
        "requeued": True,
        "reset_attempts": False,
    }


def test_main_requeue_runtime_job_requires_audit_context(monkeypatch) -> None:
    def fail_constructor(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("requeue must not touch DB without audit context")

    monkeypatch.setenv("WORKER_DATABASE_URL", "postgresql://worker:test@localhost/flood")
    monkeypatch.setattr("app.main.PostgresRuntimeQueue", fail_constructor)
    monkeypatch.setattr("app.main.PostgresRuntimeQueueReplayAudit", fail_constructor)
    monkeypatch.setattr("app.main.log_event", lambda *args, **kwargs: None)

    exit_code = main(["--requeue-runtime-job", "job-1"])

    assert exit_code == 1


def test_main_requeue_runtime_job_refuses_active_poison_quarantine(
    monkeypatch,
    capsys,
) -> None:
    captured: dict[str, object] = {}

    def fail_queue_constructor(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("poison-quarantined jobs must not be requeued")

    class FakeReplayAudit:
        def __init__(self, *, database_url: str) -> None:
            captured["audit_database_url"] = database_url

        def requeue_failed_job_with_audit(
            self,
            *,
            job_id: str,
            requested_by: str,
            reason: str,
            reset_attempts: bool = True,
        ) -> AuditedRuntimeQueueRequeueResult:
            captured["job_id"] = job_id
            captured["requested_by"] = requested_by
            captured["reason"] = reason
            captured["reset_attempts"] = reset_attempts
            return AuditedRuntimeQueueRequeueResult(
                job_id=job_id,
                requeued=False,
                reset_attempts=reset_attempts,
                requested_audit_id="audit-requested",
                outcome_audit_id="audit-failed",
                attempts_before=5,
                attempts_after=5,
                reason="poison_quarantine_active",
            )

    monkeypatch.setenv("WORKER_DATABASE_URL", "postgresql://worker:test@localhost/flood")
    monkeypatch.setattr("app.main.PostgresRuntimeQueue", fail_queue_constructor)
    monkeypatch.setattr("app.main.PostgresRuntimeQueueReplayAudit", FakeReplayAudit)

    exit_code = main(
        [
            "--requeue-runtime-job",
            "job-1",
            "--requeue-requested-by",
            "operator@example.test",
            "--requeue-reason",
            "manual retry",
        ]
    )

    assert exit_code == 1
    assert captured["job_id"] == "job-1"
    assert captured["requested_by"] == "operator@example.test"
    assert captured["reason"] == "manual retry"
    assert json.loads(capsys.readouterr().out) == {
        "attempts": 5,
        "attempts_before": 5,
        "job_id": "job-1",
        "outcome_audit_id": "audit-failed",
        "reason": "poison_quarantine_active",
        "requested_audit_id": "audit-requested",
        "requeued": False,
        "reset_attempts": True,
    }


def test_scheduler_maintenance_once_runs_query_heat_then_tile_jobs(monkeypatch) -> None:
    settings = load_worker_settings(
        {"WORKER_DATABASE_URL": "postgresql://worker:test@localhost/flood"}
    )
    expired_before = datetime(2026, 4, 30, 12, 0, tzinfo=UTC)
    calls: list[tuple[str, object]] = []

    class FakeQueryHeatAggregationJob:
        def __init__(self, *, database_url: str) -> None:
            calls.append(("query.init", database_url))

        def aggregate(
            self,
            *,
            periods: tuple[str, ...],
        ) -> tuple[_QueryHeatSummary, ...]:
            calls.append(("query.aggregate", periods))
            return (_QueryHeatSummary(period="P7D", buckets_upserted=2),)

        def prune_retention(
            self,
            *,
            periods: tuple[str, ...],
            retention_days: int,
        ) -> _QueryHeatRetentionSummary:
            calls.append(("query.retention", (periods, retention_days)))
            return _QueryHeatRetentionSummary(buckets_pruned=1)

    class FakeTileCacheWriter:
        def __init__(self, *, database_url: str) -> None:
            calls.append(("tile.init", database_url))

        def refresh_layer_features(
            self,
            *,
            layer_id: str,
            limit: int | None = None,
        ) -> _TileRefreshResult:
            calls.append(("tile.refresh", (layer_id, limit)))
            return _TileRefreshResult(layer_id=layer_id, refreshed=3)

        def prune_expired(
            self,
            *,
            layer_id: str | None,
            expired_before: datetime,
            limit: int,
        ) -> _TilePruneResult:
            calls.append(("tile.prune", (layer_id, expired_before, limit)))
            return _TilePruneResult(
                layer_id=layer_id,
                expired_before=expired_before,
                tile_cache_deleted=4,
                features_deleted=5,
            )

    monkeypatch.setattr(
        scheduler_module,
        "PostgresQueryHeatAggregationJob",
        FakeQueryHeatAggregationJob,
    )
    monkeypatch.setattr(scheduler_module, "PostgresTileCacheWriter", FakeTileCacheWriter)

    result = run_maintenance_once(
        settings=settings,
        periods=("P7D", "P1D", "P7D"),
        retention_days=14,
        tile_layer_id="flood-potential",
        tile_feature_limit=25,
        tile_prune_limit=50,
        tile_expired_before=expired_before,
    )

    assert result.status == "succeeded"
    assert calls == [
        ("query.init", "postgresql://worker:test@localhost/flood"),
        ("query.aggregate", ("P7D", "P1D")),
        ("query.retention", (("P7D", "P1D"), 14)),
        ("tile.init", "postgresql://worker:test@localhost/flood"),
        ("tile.refresh", ("flood-potential", 25)),
        ("tile.prune", ("flood-potential", expired_before, 50)),
    ]


def test_scheduler_maintenance_once_noops_without_database_url(monkeypatch) -> None:
    def fail_constructor(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("maintenance should no-op without a database URL")

    monkeypatch.setattr(scheduler_module, "PostgresQueryHeatAggregationJob", fail_constructor)
    monkeypatch.setattr(scheduler_module, "PostgresTileCacheWriter", fail_constructor)

    result = run_maintenance_once(settings=load_worker_settings({}))

    assert result.status == "skipped"
    assert result.reason == "no_database_url"


def test_scheduler_maintenance_loop_can_be_bounded(monkeypatch) -> None:
    calls: list[dict[str, object]] = []
    sleeps: list[int] = []

    def fake_maintenance_once(*args: object, **kwargs: object) -> MaintenanceCycleResult:
        del args
        calls.append(dict(kwargs))
        return MaintenanceCycleResult(status="succeeded")

    monkeypatch.setattr(scheduler_module, "run_maintenance_once", fake_maintenance_once)

    results = run_maintenance_loop(
        settings=load_worker_settings({}),
        max_ticks=2,
        sleep=sleeps.append,
        periods=("P1D",),
        retention_days=30,
        tile_layer_id="flood-potential",
        tile_feature_limit=25,
        tile_prune_limit=50,
    )

    assert len(results) == 2
    assert len(calls) == 2
    assert calls[0]["periods"] == ("P1D",)
    assert calls[0]["retention_days"] == 30
    assert calls[0]["tile_layer_id"] == "flood-potential"
    assert calls[0]["tile_feature_limit"] == 25
    assert calls[0]["tile_prune_limit"] == 50
    assert sleeps == [300]


def test_main_scheduler_maintenance_wires_overrides_to_bounded_loop(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_maintenance_loop(
        *args: object,
        **kwargs: object,
    ) -> tuple[MaintenanceCycleResult, ...]:
        del args
        captured.update(kwargs)
        return (MaintenanceCycleResult(status="succeeded"),)

    monkeypatch.setattr("app.main.run_maintenance_loop", fake_maintenance_loop)

    exit_code = main(
        [
            "--maintenance",
            "--scheduler",
            "--max-ticks",
            "2",
            "--query-heat-periods",
            "P7D,P1D,P7D",
            "--query-heat-retention-days",
            "14",
            "--tile-layer-id",
            "flood-potential",
            "--tile-feature-limit",
            "25",
            "--tile-prune-limit",
            "50",
        ]
    )

    assert exit_code == 0
    assert captured["max_ticks"] == 2
    assert captured["periods"] == ("P7D", "P1D")
    assert captured["retention_days"] == 14
    assert captured["tile_layer_id"] == "flood-potential"
    assert captured["tile_feature_limit"] == 25
    assert captured["tile_prune_limit"] == 50


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


def test_runtime_adapters_fixture_mode_supplies_selected_public_web_sample() -> None:
    settings = load_worker_settings(
        {
            "WORKER_ENABLED_ADAPTER_KEYS": "news.public_web.sample",
            "WORKER_RUNTIME_FIXTURES_ENABLED": "true",
            "SOURCE_SAMPLE_DATA_ENABLED": "true",
        }
    )

    adapters = build_runtime_adapters(settings)

    assert "news.public_web.sample" in adapters
    assert adapters["news.public_web.sample"].run().fetched[0].raw_snapshot_key == (
        "raw/news-public-web/sample.json"
    )


def test_runtime_adapters_fixture_mode_requires_explicit_public_web_sample() -> None:
    settings = load_worker_settings(
        {
            "WORKER_RUNTIME_FIXTURES_ENABLED": "true",
            "SOURCE_NEWS_ENABLED": "true",
            "SOURCE_SAMPLE_DATA_ENABLED": "true",
        }
    )

    adapters = build_runtime_adapters(settings)

    assert "news.public_web.sample" not in adapters
    assert set(adapters) == {
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


def test_run_enabled_adapters_once_runs_public_web_sample_fixture() -> None:
    settings = load_worker_settings(
        {
            "WORKER_ENABLED_ADAPTER_KEYS": "news.public_web.sample",
            "WORKER_RUNTIME_FIXTURES_ENABLED": "true",
            "SOURCE_SAMPLE_DATA_ENABLED": "true",
            "FRESHNESS_MAX_AGE_SECONDS": "604800",
        }
    )

    result = run_enabled_adapters_once(settings=settings, job_key="test.runtime.news")

    assert [summary.adapter_key for summary in result.summaries] == [
        "news.public_web.sample"
    ]
    assert result.summaries[0].raw_ref == "raw/news-public-web/sample.json"
    assert [check.adapter_key for check in result.freshness_checks] == [
        "news.public_web.sample"
    ]
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


def test_main_run_enabled_adapters_persist_uses_managed_runtime(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_managed_cycle(*args: object, **kwargs: object) -> object:
        del args
        captured.update(kwargs)
        return _ManagedRuntimeResult(
            status="succeeded",
            reason=None,
            promoted=2,
            evidence_ids=("evidence-1", "evidence-2"),
        )

    monkeypatch.setattr("app.main.run_managed_runtime_ingestion_cycle", fake_managed_cycle)
    monkeypatch.setattr("app.main.log_event", lambda *args, **kwargs: None)

    exit_code = main(
        [
            "--run-enabled-adapters",
            "--persist",
            "--database-url",
            "postgresql://worker:test@localhost/flood",
        ]
    )

    assert exit_code == 0
    assert captured["database_url"] == "postgresql://worker:test@localhost/flood"
    assert captured["adapter_builder"] is build_runtime_adapters
    assert captured["promote"] is True
    assert captured["job_key"] == "worker.runtime.managed_run_once"


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


def _fail_constructor(*args: object, **kwargs: object) -> object:
    del args, kwargs
    raise AssertionError("unexpected constructor call")


class _ManagedRuntimeResult:
    def __init__(
        self,
        *,
        status: str,
        reason: str | None,
        promoted: int,
        evidence_ids: tuple[str, ...],
    ) -> None:
        self.status = status
        self.reason = reason
        self.promoted = promoted
        self.evidence_ids = evidence_ids
        self.failed = status == "failed"
        self.has_alerts = False


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


class _TilePruneResult:
    def __init__(
        self,
        *,
        layer_id: str | None,
        expired_before: datetime,
        tile_cache_deleted: int,
        features_deleted: int,
    ) -> None:
        self.layer_id = layer_id
        self.expired_before = expired_before
        self.tile_cache_deleted = tile_cache_deleted
        self.features_deleted = features_deleted
