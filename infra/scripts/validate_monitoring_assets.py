from __future__ import annotations

from pathlib import Path
import json
import sys
from typing import Any
from urllib.parse import urlparse

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
MONITORING_DIR = REPO_ROOT / "infra" / "monitoring"
PROMETHEUS_PATH = MONITORING_DIR / "prometheus.yml"
ALERT_RULES_PATH = MONITORING_DIR / "alert-rules.yml"
DASHBOARD_PATH = MONITORING_DIR / "flood-risk-runtime-dashboard.json"
ENV_EXAMPLE_PATH = REPO_ROOT / ".env.example"
PRODUCTION_READINESS_PATH = REPO_ROOT / "docs" / "runbooks" / "production-readiness.md"
MONITORING_DASHBOARD_RUNBOOK = REPO_ROOT / "docs" / "runbooks" / "monitoring-dashboard.md"
MONITORING_ALERTS_RUNBOOK = REPO_ROOT / "docs" / "runbooks" / "monitoring-freshness-alerts.md"
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
    "Queue Final-Failed Rows",
    "Queue Expired Leases",
    "Queue Oldest Final-Failed Age",
    "Queue Metrics Available",
    "Runtime Queue Counts",
}
EXPECTED_DASHBOARD_METRICS = {
    "flood_risk_source_freshness_status",
    "flood_risk_source_freshness_stale",
    "flood_risk_source_freshness_age_seconds",
    "flood_risk_worker_heartbeat_timestamp_seconds",
    "flood_risk_scheduler_heartbeat_timestamp_seconds",
    "flood_risk_worker_last_run_status",
    "flood_risk_runtime_queue_metrics_available",
    "flood_risk_runtime_queue_queued_jobs",
    "flood_risk_runtime_queue_running_jobs",
    "flood_risk_runtime_queue_final_failed_jobs",
    "flood_risk_runtime_queue_expired_leases",
    "flood_risk_runtime_queue_oldest_final_failed_age_seconds",
}
EXPECTED_ALERT_METRICS = {
    "flood_risk_source_freshness_status",
    "flood_risk_source_freshness_stale",
    "flood_risk_worker_heartbeat_timestamp_seconds",
    "flood_risk_scheduler_heartbeat_timestamp_seconds",
    "flood_risk_worker_last_run_status",
    "flood_risk_runtime_queue_metrics_available",
    "flood_risk_runtime_queue_final_failed_jobs",
    "flood_risk_runtime_queue_expired_leases",
}
REQUIRED_PRODUCTION_READINESS_SECTIONS = {
    "## Secrets Inventory",
    "## Zeabur Environment Ownership",
    "## SLO and SLI Targets",
    "## Alert Routing",
    "## On-Call Drill",
    "## Rollback Drill",
    "## Source Kill Switch",
    "## Public Report Disable",
    "## GDELT and Forum Gates",
    "## Launch Blockers",
    "## Owner Handoff",
}
REQUIRED_SLO_TERMS = {
    "API availability",
    "Source freshness",
    "Worker heartbeat",
    "Scheduler heartbeat",
    "Queue visibility",
    "Backup restore",
}
SECRET_ENV_VARS_MUST_BE_BLANK = {
    "ABUSE_HASH_SALT",
    "ADMIN_BEARER_TOKEN",
    "CWA_API_AUTHORIZATION",
    "WRA_API_TOKEN",
}
LOCAL_ONLY_SECRET_PLACEHOLDERS = {
    "POSTGRES_PASSWORD": "change-me-local",
    "MINIO_ROOT_PASSWORD": "change-me-local",
    "GRAFANA_ADMIN_PASSWORD": "change-me-local",
}
PRODUCTION_GATES_MUST_DEFAULT_FALSE = {
    "SOURCE_CWA_ENABLED",
    "SOURCE_WRA_ENABLED",
    "SOURCE_FLOOD_POTENTIAL_ENABLED",
    "SOURCE_CWA_API_ENABLED",
    "SOURCE_WRA_API_ENABLED",
    "SOURCE_FLOOD_POTENTIAL_GEOJSON_ENABLED",
    "SOURCE_NEWS_ENABLED",
    "SOURCE_FORUM_ENABLED",
    "SOURCE_PTT_ENABLED",
    "SOURCE_DCARD_ENABLED",
    "SOURCE_TERMS_REVIEW_ACK",
    "SOURCE_SAMPLE_DATA_ENABLED",
    "USER_REPORTS_ENABLED",
}
DATABASE_URL_LOCAL_PASSWORD = "change-me-local"


def main() -> int:
    errors: list[str] = []
    prometheus = _load_yaml(PROMETHEUS_PATH, errors)
    alert_rules = _load_yaml(ALERT_RULES_PATH, errors)
    dashboard = _load_json(DASHBOARD_PATH, errors)
    env_vars = _load_env_example(errors)
    readiness_text = _load_text(PRODUCTION_READINESS_PATH, errors)
    monitoring_dashboard_text = _load_text(MONITORING_DASHBOARD_RUNBOOK, errors)
    monitoring_alerts_text = _load_text(MONITORING_ALERTS_RUNBOOK, errors)

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
        for metric in EXPECTED_ALERT_METRICS:
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
        for metric in EXPECTED_DASHBOARD_METRICS:
            if not any(metric in expr for expr in dashboard_exprs):
                errors.append(f"dashboard: missing Prometheus query for {metric}")
        runtime_queue_count_exprs = _dashboard_exprs_for_panel(panels, "Runtime Queue Counts")
        if not runtime_queue_count_exprs:
            errors.append("dashboard: Runtime Queue Counts panel must define targets")
        for expr in runtime_queue_count_exprs:
            if " or " in f" {expr} ":
                errors.append(
                    "dashboard: Runtime Queue Counts must not combine queue metrics "
                    "with PromQL set operator 'or'"
                )

    if env_vars:
        _validate_env_example(env_vars, errors)

    if readiness_text is not None:
        _validate_production_readiness_runbook(readiness_text, errors)

    if monitoring_dashboard_text is not None:
        _validate_runbook_mentions(
            MONITORING_DASHBOARD_RUNBOOK,
            monitoring_dashboard_text,
            ("SLO Alignment", "production-readiness.md"),
            errors,
        )

    if monitoring_alerts_text is not None:
        _validate_runbook_mentions(
            MONITORING_ALERTS_RUNBOOK,
            monitoring_alerts_text,
            ("production-readiness.md", "FloodRiskApiReadyDown"),
            errors,
        )

    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    print(
        "Monitoring assets valid. "
        f"dashboard_panels={len(EXPECTED_PANEL_TITLES)} "
        f"dashboard_metrics={len(EXPECTED_DASHBOARD_METRICS)} "
        f"alert_metrics={len(EXPECTED_ALERT_METRICS)} "
        "production_readiness=checked"
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


def _load_text(path: Path, errors: list[str]) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"{path.relative_to(REPO_ROOT)}: {exc}")
        return None


def _load_env_example(errors: list[str]) -> dict[str, str]:
    try:
        lines = ENV_EXAMPLE_PATH.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        errors.append(f"{ENV_EXAMPLE_PATH.relative_to(REPO_ROOT)}: {exc}")
        return {}

    env_vars: dict[str, str] = {}
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            errors.append(f".env.example:{line_number}: expected KEY=VALUE syntax")
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            errors.append(f".env.example:{line_number}: empty env var name")
            continue
        env_vars[key] = value.strip()
    return env_vars


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


def _dashboard_exprs_for_panel(panels: list[dict[str, Any]], title: str) -> list[str]:
    for panel in panels:
        if panel.get("title") != title:
            continue
        return [
            target["expr"]
            for target in _as_list(panel.get("targets"))
            if isinstance(target, dict) and isinstance(target.get("expr"), str)
        ]
    return []


def _validate_env_example(env_vars: dict[str, str], errors: list[str]) -> None:
    for key in SECRET_ENV_VARS_MUST_BE_BLANK:
        if key not in env_vars:
            errors.append(f".env.example: missing {key}")
            continue
        if env_vars[key]:
            errors.append(f".env.example: {key} must be blank; do not commit example secrets")

    for key, expected_value in LOCAL_ONLY_SECRET_PLACEHOLDERS.items():
        if env_vars.get(key) != expected_value:
            errors.append(
                f".env.example: {key} should stay at local-only placeholder {expected_value!r}"
            )

    for key in PRODUCTION_GATES_MUST_DEFAULT_FALSE:
        if env_vars.get(key) != "false":
            errors.append(f".env.example: {key} must default to false for production readiness")

    _validate_database_url_placeholder(env_vars.get("DATABASE_URL", ""), errors)


def _validate_production_readiness_runbook(text: str, errors: list[str]) -> None:
    for section in REQUIRED_PRODUCTION_READINESS_SECTIONS:
        if section not in text:
            errors.append(f"production-readiness.md: missing section {section}")

    for term in REQUIRED_SLO_TERMS:
        if term not in text:
            errors.append(f"production-readiness.md: missing SLO term {term!r}")

    for gate in PRODUCTION_GATES_MUST_DEFAULT_FALSE:
        if gate not in text:
            errors.append(f"production-readiness.md: missing production gate {gate}")

    for required_phrase in (
        "not production complete",
        "Do not commit real secrets",
        "Do not launch production beta",
        "owner",
    ):
        if required_phrase not in text:
            errors.append(f"production-readiness.md: missing phrase {required_phrase!r}")


def _validate_database_url_placeholder(database_url: str, errors: list[str]) -> None:
    if not database_url:
        errors.append(".env.example: DATABASE_URL is required for local compose")
        return

    parsed = urlparse(database_url)
    if parsed.scheme not in {"postgresql", "postgres"}:
        errors.append(".env.example: DATABASE_URL must use postgresql:// or postgres://")
    if parsed.password not in {None, DATABASE_URL_LOCAL_PASSWORD}:
        errors.append(
            ".env.example: DATABASE_URL password must be blank or the local-only "
            f"placeholder {DATABASE_URL_LOCAL_PASSWORD!r}"
        )
    if parsed.hostname not in {"postgres", "localhost", "127.0.0.1"}:
        errors.append(".env.example: DATABASE_URL host must stay local/compose scoped")


def _validate_runbook_mentions(
    path: Path,
    text: str,
    required_terms: tuple[str, ...],
    errors: list[str],
) -> None:
    for term in required_terms:
        if term not in text:
            errors.append(f"{path.relative_to(REPO_ROOT)}: missing {term!r}")


if __name__ == "__main__":
    raise SystemExit(main())
