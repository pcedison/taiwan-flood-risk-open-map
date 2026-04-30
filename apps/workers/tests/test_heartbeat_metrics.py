from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import yaml  # type: ignore[import-untyped]

from app.metrics import (
    render_prometheus_text,
    render_scheduler_heartbeat_metrics,
    render_worker_heartbeat_metrics,
    write_prometheus_textfile,
    PrometheusSample,
)


HEARTBEAT_AT = datetime(2026, 4, 30, 4, 0, 5, tzinfo=UTC)
REPO_ROOT = Path(__file__).resolve().parents[3]


def test_worker_heartbeat_metrics_render_timestamp_and_status_labels() -> None:
    text = render_worker_heartbeat_metrics(
        instance='worker-"a"',
        queue="official\nrealtime",
        heartbeat_at=HEARTBEAT_AT,
        last_run_status="failed",
        job="ingestion",
    )

    assert "# TYPE flood_risk_worker_heartbeat_timestamp_seconds gauge" in text
    assert (
        'flood_risk_worker_heartbeat_timestamp_seconds{instance="worker-\\"a\\"",'
        'queue="official\\nrealtime",service="worker"} 1777521605'
    ) in text
    assert (
        'flood_risk_worker_last_run_status{instance="worker-\\"a\\"",job="ingestion",'
        'queue="official\\nrealtime",service="worker",status="failed"} 1'
    ) in text
    assert (
        'flood_risk_worker_last_run_status{instance="worker-\\"a\\"",job="ingestion",'
        'queue="official\\nrealtime",service="worker",status="succeeded"} 0'
    ) in text


def test_scheduler_heartbeat_metrics_render_timestamp_and_status_labels() -> None:
    text = render_scheduler_heartbeat_metrics(
        instance="scheduler-1",
        scheduler="singleton",
        heartbeat_at=HEARTBEAT_AT,
        last_run_status="succeeded",
    )

    assert (
        'flood_risk_scheduler_heartbeat_timestamp_seconds{instance="scheduler-1",'
        'scheduler="singleton",service="scheduler"} 1777521605'
    ) in text
    assert (
        'flood_risk_scheduler_last_run_status{instance="scheduler-1",'
        'scheduler="singleton",service="scheduler",status="succeeded"} 1'
    ) in text


def test_prometheus_textfile_helper_writes_utf8_with_trailing_newline(tmp_path: Path) -> None:
    target = tmp_path / "collector" / "worker-heartbeat.prom"
    content = render_prometheus_text(
        [PrometheusSample(name="flood_risk_test_metric", labels={"a": "b"}, value=1)]
    )

    write_prometheus_textfile(target, content)

    assert target.read_text(encoding="utf-8") == 'flood_risk_test_metric{a="b"} 1\n'


def test_alert_rules_yaml_parse_and_reference_heartbeat_metrics() -> None:
    alert_rules = yaml.safe_load((REPO_ROOT / "infra/monitoring/alert-rules.yml").read_text())
    expressions = {
        rule["alert"]: rule["expr"]
        for group in alert_rules["groups"]
        for rule in group["rules"]
    }

    assert "vector(0) == 1" not in "\n".join(expressions.values())
    assert (
        "flood_risk_worker_heartbeat_timestamp_seconds"
        in expressions["FloodRiskWorkerHeartbeatMissing"]
    )
    assert (
        "flood_risk_scheduler_heartbeat_timestamp_seconds"
        in expressions["FloodRiskSchedulerHeartbeatMissing"]
    )
    assert "flood_risk_worker_last_run_status" in expressions["FloodRiskWorkerLastRunFailed"]
