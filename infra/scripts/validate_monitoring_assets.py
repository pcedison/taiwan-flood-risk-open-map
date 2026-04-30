from __future__ import annotations

from pathlib import Path
import json
import sys
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
MONITORING_DIR = REPO_ROOT / "infra" / "monitoring"
PROMETHEUS_PATH = MONITORING_DIR / "prometheus.yml"
ALERT_RULES_PATH = MONITORING_DIR / "alert-rules.yml"
DASHBOARD_PATH = MONITORING_DIR / "flood-risk-runtime-dashboard.json"
EXPECTED_PANEL_TITLES = {
    "API Metrics Scrape",
    "API Readiness",
    "Stale Sources",
    "Worker Last Run Failed",
    "Source Freshness Status",
    "Source Freshness Age",
    "Worker Heartbeat Age",
    "Scheduler Heartbeat Age",
    "Worker Last Run Status",
}
EXPECTED_METRICS = {
    "flood_risk_source_freshness_status",
    "flood_risk_source_freshness_stale",
    "flood_risk_source_freshness_age_seconds",
    "flood_risk_worker_heartbeat_timestamp_seconds",
    "flood_risk_scheduler_heartbeat_timestamp_seconds",
    "flood_risk_worker_last_run_status",
}


def main() -> int:
    errors: list[str] = []
    prometheus = _load_yaml(PROMETHEUS_PATH, errors)
    alert_rules = _load_yaml(ALERT_RULES_PATH, errors)
    dashboard = _load_json(DASHBOARD_PATH, errors)

    if isinstance(prometheus, dict):
        rule_files = prometheus.get("rule_files")
        if "alert-rules.yml" not in _as_list(rule_files):
            errors.append("prometheus.yml: rule_files must include alert-rules.yml")
        scrape_jobs = {
            str(config.get("job_name"))
            for config in _as_list(prometheus.get("scrape_configs"))
            if isinstance(config, dict)
        }
        if "flood-risk-api" not in scrape_jobs:
            errors.append("prometheus.yml: missing flood-risk-api scrape job")

    if isinstance(alert_rules, dict):
        alert_exprs = _collect_alert_exprs(alert_rules)
        for metric in EXPECTED_METRICS - {"flood_risk_source_freshness_age_seconds"}:
            if not any(metric in expr for expr in alert_exprs):
                errors.append(f"alert-rules.yml: missing alert expression for {metric}")

    if isinstance(dashboard, dict):
        if dashboard.get("uid") != "flood-risk-runtime":
            errors.append("dashboard: uid must be flood-risk-runtime")
        panels = [panel for panel in _as_list(dashboard.get("panels")) if isinstance(panel, dict)]
        titles = {str(panel.get("title")) for panel in panels}
        missing_titles = EXPECTED_PANEL_TITLES - titles
        if missing_titles:
            errors.append(f"dashboard: missing panels {sorted(missing_titles)}")

        dashboard_exprs = _collect_dashboard_exprs(panels)
        for metric in EXPECTED_METRICS:
            if not any(metric in expr for expr in dashboard_exprs):
                errors.append(f"dashboard: missing Prometheus query for {metric}")

    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    print(
        "Monitoring assets valid. "
        f"dashboard_panels={len(EXPECTED_PANEL_TITLES)} metrics={len(EXPECTED_METRICS)}"
    )
    return 0


def _load_yaml(path: Path, errors: list[str]) -> Any:
    try:
        with path.open(encoding="utf-8") as handle:
            return yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as exc:
        errors.append(f"{path.relative_to(REPO_ROOT)}: {exc}")
        return None


def _load_json(path: Path, errors: list[str]) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"{path.relative_to(REPO_ROOT)}: {exc}")
        return None


def _as_list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _collect_alert_exprs(alert_rules: dict[str, Any]) -> list[str]:
    exprs: list[str] = []
    for group in _as_list(alert_rules.get("groups")):
        if not isinstance(group, dict):
            continue
        for rule in _as_list(group.get("rules")):
            if isinstance(rule, dict) and isinstance(rule.get("expr"), str):
                exprs.append(rule["expr"])
    return exprs


def _collect_dashboard_exprs(panels: list[dict[str, Any]]) -> list[str]:
    exprs: list[str] = []
    for panel in panels:
        for target in _as_list(panel.get("targets")):
            if isinstance(target, dict) and isinstance(target.get("expr"), str):
                exprs.append(target["expr"])
    return exprs


if __name__ == "__main__":
    raise SystemExit(main())
