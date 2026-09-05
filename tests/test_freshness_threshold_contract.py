"""Keep the realtime freshness policy identical in both apps and the catalog.

Three places decide whether an official realtime feed counts as fresh:

- the worker monitor (apps/workers/app/jobs/freshness.py), which pages on stale,
- the admin diagnostics (apps/api/app/api/routes/admin.py), and
- the ``data_sources.metadata->>'freshness_threshold_seconds'`` values the
  public evidence/coverage queries read, seeded by infra/migrations.

They drifted once already: the catalog carried no threshold for the ten-minute
networks, so the public health view fell back to a ten-minute window and
reported "fresh 0" for every CWA rainfall, WRA water level and Civil IoT sewer
station while the feeds were current.  This test pins the three together.

The two apps are separate regular packages that both expose a top-level ``app``
package, so they cannot be imported into one interpreter reliably (see
tests/support/dual_parse_extract.py).  Each side's constants are therefore read
in a subprocess whose cwd is that app's root.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
WORKERS_ROOT = REPO_ROOT / "apps" / "workers"
MIGRATION = (
    REPO_ROOT / "infra" / "migrations" / "0061_realtime_freshness_thresholds.sql"
)

_DUMP = (
    "import json;"
    "from {module} import ("
    "REALTIME_FRESH_SECONDS as fresh,"
    "REALTIME_DEGRADED_SECONDS as degraded,"
    "REALTIME_STALE_SECONDS as stale,"
    "REALTIME_THRESHOLDS_BY_ADAPTER as by_adapter);"
    "print(json.dumps({{"
    "'fresh': fresh, 'degraded': degraded, 'stale': stale,"
    "'by_adapter': {{key: list(value) for key, value in by_adapter.items()}}"
    "}}, sort_keys=True))"
)


def _constants(app_root: Path, module: str) -> dict[str, Any]:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    result = subprocess.run(
        [sys.executable, "-c", _DUMP.format(module=module)],
        cwd=str(app_root),
        capture_output=True,
        env=env,
    )
    stderr = result.stderr.decode("utf-8", errors="replace")
    assert result.returncode == 0, f"{module} constant dump failed:\n{stderr}"
    return json.loads(result.stdout.decode("utf-8"))


def _api_constants() -> dict[str, Any]:
    return _constants(API_ROOT, "app.api.routes.admin")


def _worker_constants() -> dict[str, Any]:
    return _constants(WORKERS_ROOT, "app.jobs.freshness")


def _migration_thresholds() -> dict[str, int]:
    sql = MIGRATION.read_text(encoding="utf-8")
    thresholds: dict[str, int] = {}
    for statement in sql.split(";"):
        seconds_match = re.search(r"to_jsonb\((\d+)\)", statement)
        if seconds_match is None:
            continue
        where_clause = statement.split("WHERE", 1)
        assert len(where_clause) == 2, f"UPDATE without a WHERE clause:\n{statement}"
        for adapter_key in re.findall(r"'([a-z0-9_.]+)'", where_clause[1]):
            assert adapter_key not in thresholds, f"{adapter_key} set twice"
            thresholds[adapter_key] = int(seconds_match.group(1))
    assert thresholds, "migration 0061 set no freshness thresholds"
    return thresholds


def test_api_and_worker_realtime_thresholds_are_identical() -> None:
    assert _api_constants() == _worker_constants()


def test_migration_thresholds_match_the_shared_realtime_policy() -> None:
    constants = _worker_constants()
    default_fresh = constants["fresh"]
    by_adapter = constants["by_adapter"]

    for adapter_key, seconds in _migration_thresholds().items():
        expected = (
            by_adapter[adapter_key][0] if adapter_key in by_adapter else default_fresh
        )
        assert seconds == expected, (
            f"{adapter_key}: migration 0061 seeds {seconds}s but the shared "
            f"realtime policy treats it as fresh for {expected}s"
        )


def test_api_fallback_thresholds_match_the_seeded_catalog_value() -> None:
    """The DB-less fallbacks must agree with what the migration seeds.

    A source row whose metadata is missing the key falls back to these, and a
    fallback shorter than the seeded window is exactly the bug that made the
    public health view report "fresh 0".
    """

    fallbacks = json.loads(
        subprocess.run(
            [
                sys.executable,
                "-c",
                "import json;"
                "from app.domain.evidence.repository import "
                "_DEFAULT_FRESHNESS_THRESHOLD_SECONDS as evidence;"
                "from app.domain.realtime.nearby_coverage import "
                "_DEFAULT_SOURCE_FRESHNESS_THRESHOLD_SECONDS as coverage;"
                "print(json.dumps({'evidence': evidence, 'coverage': coverage}))",
            ],
            cwd=str(API_ROOT),
            capture_output=True,
            check=True,
            env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
        ).stdout.decode("utf-8")
    )

    expected = _api_constants()["fresh"]
    assert fallbacks["evidence"] == expected
    assert fallbacks["coverage"] == expected
