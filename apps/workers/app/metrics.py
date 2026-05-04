from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from app.jobs.queue import RuntimeQueueMetricsSnapshot


WORKER_HEARTBEAT_TIMESTAMP = "flood_risk_worker_heartbeat_timestamp_seconds"
SCHEDULER_HEARTBEAT_TIMESTAMP = "flood_risk_scheduler_heartbeat_timestamp_seconds"
WORKER_LAST_RUN_STATUS = "flood_risk_worker_last_run_status"
SCHEDULER_LAST_RUN_STATUS = "flood_risk_scheduler_last_run_status"
RUNTIME_QUEUE_METRICS_AVAILABLE = "flood_risk_runtime_queue_metrics_available"
RUNTIME_QUEUE_QUEUED_JOBS = "flood_risk_runtime_queue_queued_jobs"
RUNTIME_QUEUE_RUNNING_JOBS = "flood_risk_runtime_queue_running_jobs"
RUNTIME_QUEUE_FINAL_FAILED_JOBS = "flood_risk_runtime_queue_final_failed_jobs"
RUNTIME_QUEUE_EXPIRED_LEASES = "flood_risk_runtime_queue_expired_leases"
RUNTIME_QUEUE_OLDEST_FINAL_FAILED_AGE_SECONDS = (
    "flood_risk_runtime_queue_oldest_final_failed_age_seconds"
)

RunStatus = Literal["succeeded", "failed", "skipped", "running", "unknown"]
MetricValue = int | float


@dataclass(frozen=True)
class PrometheusSample:
    name: str
    value: MetricValue
    labels: dict[str, str] | None = None


def render_worker_heartbeat_metrics(
    *,
    instance: str,
    queue: str,
    heartbeat_at: datetime,
    last_run_status: RunStatus | None = None,
    job: str | None = None,
) -> str:
    labels = {"service": "worker", "instance": instance, "queue": queue}
    samples = [
        PrometheusSample(
            name=WORKER_HEARTBEAT_TIMESTAMP,
            labels=labels,
            value=_unix_timestamp_seconds(heartbeat_at),
        )
    ]
    if last_run_status is not None:
        samples.extend(
            _status_samples(
                name=WORKER_LAST_RUN_STATUS,
                active_status=last_run_status,
                labels=labels | {"job": job or "unknown"},
            )
        )

    return render_prometheus_text(samples, metric_metadata=_runtime_metric_metadata())


def render_scheduler_heartbeat_metrics(
    *,
    instance: str,
    heartbeat_at: datetime,
    last_run_status: RunStatus | None = None,
    scheduler: str = "singleton",
) -> str:
    labels = {"service": "scheduler", "instance": instance, "scheduler": scheduler}
    samples = [
        PrometheusSample(
            name=SCHEDULER_HEARTBEAT_TIMESTAMP,
            labels=labels,
            value=_unix_timestamp_seconds(heartbeat_at),
        )
    ]
    if last_run_status is not None:
        samples.extend(
            _status_samples(
                name=SCHEDULER_LAST_RUN_STATUS,
                active_status=last_run_status,
                labels=labels,
            )
        )

    return render_prometheus_text(samples, metric_metadata=_runtime_metric_metadata())


def render_runtime_queue_metrics(
    *,
    snapshots: tuple[RuntimeQueueMetricsSnapshot, ...],
    collected_at: datetime,
    available: bool,
    reason: str | None = None,
) -> str:
    base_labels = {"service": "worker", "surface": "runtime_queue"}
    samples = [
        PrometheusSample(
            name=RUNTIME_QUEUE_METRICS_AVAILABLE,
            labels=base_labels | {"reason": reason or "ok"},
            value=int(available),
        )
    ]

    for snapshot in snapshots:
        labels = base_labels | {"queue_name": snapshot.queue_name}
        samples.extend(
            [
                PrometheusSample(
                    name=RUNTIME_QUEUE_QUEUED_JOBS,
                    labels=labels,
                    value=snapshot.queued_count,
                ),
                PrometheusSample(
                    name=RUNTIME_QUEUE_RUNNING_JOBS,
                    labels=labels,
                    value=snapshot.running_count,
                ),
                PrometheusSample(
                    name=RUNTIME_QUEUE_FINAL_FAILED_JOBS,
                    labels=labels,
                    value=snapshot.final_failed_count,
                ),
                PrometheusSample(
                    name=RUNTIME_QUEUE_EXPIRED_LEASES,
                    labels=labels,
                    value=snapshot.expired_lease_count,
                ),
                PrometheusSample(
                    name=RUNTIME_QUEUE_OLDEST_FINAL_FAILED_AGE_SECONDS,
                    labels=labels,
                    value=_age_seconds(collected_at, snapshot.oldest_final_failed_at),
                ),
            ]
        )

    return render_prometheus_text(samples, metric_metadata=_runtime_metric_metadata())


def render_prometheus_text(
    samples: list[PrometheusSample],
    *,
    metric_metadata: dict[str, tuple[str, str]] | None = None,
) -> str:
    lines: list[str] = []
    emitted_metadata: set[str] = set()
    metadata = metric_metadata or {}

    for sample in samples:
        if sample.name in metadata and sample.name not in emitted_metadata:
            help_text, metric_type = metadata[sample.name]
            lines.append(f"# HELP {sample.name} {help_text}")
            lines.append(f"# TYPE {sample.name} {metric_type}")
            emitted_metadata.add(sample.name)
        lines.append(_render_sample(sample))

    return "\n".join(lines) + "\n"


def write_prometheus_textfile(path: str | Path, content: str) -> None:
    resolved_path = Path(path)
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_path.write_text(content, encoding="utf-8", newline="\n")


def _status_samples(
    *,
    name: str,
    active_status: RunStatus,
    labels: dict[str, str],
) -> list[PrometheusSample]:
    statuses: tuple[RunStatus, ...] = ("succeeded", "failed", "skipped", "running", "unknown")
    return [
        PrometheusSample(
            name=name,
            labels=labels | {"status": status},
            value=int(status == active_status),
        )
        for status in statuses
    ]


def _render_sample(sample: PrometheusSample) -> str:
    if not sample.labels:
        return f"{sample.name} {_format_value(sample.value)}"

    labels = ",".join(
        f'{key}="{_escape_label_value(value)}"' for key, value in sorted(sample.labels.items())
    )
    return f"{sample.name}{{{labels}}} {_format_value(sample.value)}"


def _escape_label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _format_value(value: MetricValue) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _unix_timestamp_seconds(value: datetime) -> int:
    resolved = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return int(resolved.timestamp())


def _age_seconds(collected_at: datetime, then: datetime | None) -> int:
    if then is None:
        return 0
    collected = collected_at.replace(tzinfo=UTC) if collected_at.tzinfo is None else collected_at
    previous = then.replace(tzinfo=UTC) if then.tzinfo is None else then
    return max(0, int((collected.astimezone(UTC) - previous.astimezone(UTC)).total_seconds()))


def _runtime_metric_metadata() -> dict[str, tuple[str, str]]:
    return {
        WORKER_HEARTBEAT_TIMESTAMP: (
            "Unix timestamp of the latest worker heartbeat.",
            "gauge",
        ),
        SCHEDULER_HEARTBEAT_TIMESTAMP: (
            "Unix timestamp of the latest scheduler heartbeat.",
            "gauge",
        ),
        WORKER_LAST_RUN_STATUS: (
            "One-hot status gauge for the worker's latest observed run.",
            "gauge",
        ),
        SCHEDULER_LAST_RUN_STATUS: (
            "One-hot status gauge for the scheduler's latest observed run.",
            "gauge",
        ),
        RUNTIME_QUEUE_METRICS_AVAILABLE: (
            "Whether runtime queue metrics were collected from the durable queue backend.",
            "gauge",
        ),
        RUNTIME_QUEUE_QUEUED_JOBS: (
            "Number of runtime queue rows currently queued.",
            "gauge",
        ),
        RUNTIME_QUEUE_RUNNING_JOBS: (
            "Number of runtime queue rows currently leased and running.",
            "gauge",
        ),
        RUNTIME_QUEUE_FINAL_FAILED_JOBS: (
            "Number of exhausted final-failed runtime queue rows. This is row visibility, not a replay store.",
            "gauge",
        ),
        RUNTIME_QUEUE_EXPIRED_LEASES: (
            "Number of running runtime queue rows whose lease has expired.",
            "gauge",
        ),
        RUNTIME_QUEUE_OLDEST_FINAL_FAILED_AGE_SECONDS: (
            "Age in seconds of the oldest exhausted final-failed runtime queue row.",
            "gauge",
        ),
    }
