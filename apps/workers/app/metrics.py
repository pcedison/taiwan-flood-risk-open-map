from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from app.jobs.freshness import FreshnessCheck
from app.jobs.ingestion import AdapterBatchRunSummary
from app.jobs.queue import RuntimeQueueMetricsSnapshot


SOURCE_FRESHNESS_STATUS = "flood_risk_source_freshness_status"
SOURCE_FRESHNESS_STALE = "flood_risk_source_freshness_stale"
SOURCE_FRESHNESS_AGE_SECONDS = "flood_risk_source_freshness_age_seconds"
SOURCE_FRESHNESS_STALE_COUNT = "flood_risk_source_freshness_stale_count"
SOURCE_FRESHNESS_FAILED_COUNT = "flood_risk_source_freshness_failed_count"
ADAPTER_LAST_SUCCESS_TIMESTAMP = "flood_risk_adapter_last_success_timestamp_seconds"
WORKER_HEARTBEAT_TIMESTAMP = "flood_risk_worker_heartbeat_timestamp_seconds"
SCHEDULER_HEARTBEAT_TIMESTAMP = "flood_risk_scheduler_heartbeat_timestamp_seconds"
WORKER_LAST_RUN_STATUS = "flood_risk_worker_last_run_status"
SCHEDULER_LAST_RUN_STATUS = "flood_risk_scheduler_last_run_status"
RUNTIME_QUEUE_METRICS_AVAILABLE = "flood_risk_runtime_queue_metrics_available"
RUNTIME_QUEUE_QUEUED_JOBS = "flood_risk_runtime_queue_queued_jobs"
RUNTIME_QUEUE_RUNNING_JOBS = "flood_risk_runtime_queue_running_jobs"
RUNTIME_QUEUE_FINAL_FAILED_JOBS = "flood_risk_runtime_queue_final_failed_jobs"
RUNTIME_QUEUE_EXPIRED_LEASES = "flood_risk_runtime_queue_expired_leases"
RUNTIME_QUEUE_LAG_SECONDS = "flood_risk_runtime_queue_lag_seconds"
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
                    name=RUNTIME_QUEUE_LAG_SECONDS,
                    labels=labels,
                    value=_age_seconds(collected_at, snapshot.oldest_queued_at),
                ),
                PrometheusSample(
                    name=RUNTIME_QUEUE_OLDEST_FINAL_FAILED_AGE_SECONDS,
                    labels=labels,
                    value=_age_seconds(collected_at, snapshot.oldest_final_failed_at),
                ),
            ]
        )

    return render_prometheus_text(samples, metric_metadata=_runtime_metric_metadata())


def render_source_freshness_metrics(
    *,
    summaries: tuple[AdapterBatchRunSummary, ...],
    freshness_checks: tuple[FreshnessCheck, ...],
) -> str:
    samples: list[PrometheusSample] = []
    base_labels = {"service": "worker", "surface": "source_freshness"}
    samples.extend(
        [
            PrometheusSample(
                name=SOURCE_FRESHNESS_STALE_COUNT,
                labels=base_labels,
                value=sum(1 for check in freshness_checks if check.status == "stale"),
            ),
            PrometheusSample(
                name=SOURCE_FRESHNESS_FAILED_COUNT,
                labels=base_labels,
                value=sum(1 for check in freshness_checks if check.status == "failed"),
            ),
        ]
    )

    for check in freshness_checks:
        health_status = _freshness_health_status(check)
        source_labels = _source_labels(check.adapter_key) | {"health_status": health_status}
        samples.extend(
            [
                PrometheusSample(
                    name=SOURCE_FRESHNESS_AGE_SECONDS,
                    labels=source_labels,
                    value=_freshness_age_seconds(check),
                ),
                PrometheusSample(
                    name=SOURCE_FRESHNESS_STALE,
                    labels=source_labels,
                    value=int(check.status == "stale"),
                ),
            ]
        )
        samples.extend(
            _status_samples(
                name=SOURCE_FRESHNESS_STATUS,
                active_status=health_status,
                labels=_source_labels(check.adapter_key),
                statuses=("healthy", "degraded", "failed", "unknown", "disabled"),
            )
        )

    for summary in summaries:
        if summary.status not in {"succeeded", "partial"}:
            continue
        samples.append(
            PrometheusSample(
                name=ADAPTER_LAST_SUCCESS_TIMESTAMP,
                labels={"service": "worker", "adapter_key": summary.adapter_key},
                value=_unix_timestamp_seconds(summary.finished_at),
            )
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
    active_status: str,
    labels: dict[str, str],
    statuses: tuple[str, ...] = ("succeeded", "failed", "skipped", "running", "unknown"),
) -> list[PrometheusSample]:
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


def _freshness_health_status(check: FreshnessCheck) -> str:
    return {
        "fresh": "healthy",
        "degraded": "degraded",
        "stale": "degraded",
        "failed": "failed",
    }[check.status]


def _freshness_age_seconds(check: FreshnessCheck) -> int | float:
    if check.age_seconds is not None:
        return check.age_seconds
    if check.source_timestamp_max is None:
        return -1
    return _age_seconds(check.checked_at, check.source_timestamp_max)


def _source_labels(adapter_key: str) -> dict[str, str]:
    return {
        "source_id": adapter_key,
        "adapter_key": adapter_key,
        "source_type": _source_type_from_adapter_key(adapter_key),
    }


def _source_type_from_adapter_key(adapter_key: str) -> str:
    prefix = adapter_key.split(".", 1)[0]
    return {
        "official": "official",
        "news": "news",
        "public": "public_intake",
        "user_report": "public_intake",
    }.get(prefix, "unknown")


def _runtime_metric_metadata() -> dict[str, tuple[str, str]]:
    return {
        SOURCE_FRESHNESS_STATUS: (
            "Source health status as a labeled gauge where the active status is 1.",
            "gauge",
        ),
        SOURCE_FRESHNESS_STALE: (
            "Whether the source exceeded the freshness threshold.",
            "gauge",
        ),
        SOURCE_FRESHNESS_AGE_SECONDS: (
            "Age of the newest source timestamp used by the worker freshness check.",
            "gauge",
        ),
        SOURCE_FRESHNESS_STALE_COUNT: (
            "Number of worker-observed sources that exceeded freshness thresholds.",
            "gauge",
        ),
        SOURCE_FRESHNESS_FAILED_COUNT: (
            "Number of worker-observed sources whose latest adapter run failed.",
            "gauge",
        ),
        ADAPTER_LAST_SUCCESS_TIMESTAMP: (
            "Unix timestamp of the latest successful adapter run observed by the worker.",
            "gauge",
        ),
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
        RUNTIME_QUEUE_LAG_SECONDS: (
            "Age in seconds of the oldest queued runtime job that is ready to run.",
            "gauge",
        ),
        RUNTIME_QUEUE_OLDEST_FINAL_FAILED_AGE_SECONDS: (
            "Age in seconds of the oldest exhausted final-failed runtime queue row.",
            "gauge",
        ),
    }
