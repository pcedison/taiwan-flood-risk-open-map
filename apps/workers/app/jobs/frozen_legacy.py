"""Shared metadata response for v1-frozen legacy product paths."""

from __future__ import annotations

import json
from typing import Final

FROZEN_LEGACY_REASON: Final = "v1_legacy_product_writers_frozen"
FROZEN_LEGACY_COMMANDS: Final = (
    "aggregate_query_heat",
    "seed_risk_profiles",
    "rebuild_risk_profile",
    "work_profile_refresh_jobs",
    "refresh_tile_features",
    "run_enabled_adapters",
    "work_runtime_queue",
    "enqueue_runtime_jobs",
    "requeue_runtime_job",
    "generic_scheduler",
    "official_demo",
)


def frozen_legacy_payload() -> dict[str, object]:
    return {
        "status": "frozen",
        "reason": FROZEN_LEGACY_REASON,
        "tables_retained": True,
    }


def report_frozen_legacy() -> int:
    print(json.dumps(frozen_legacy_payload(), ensure_ascii=False, sort_keys=True))
    return 2
