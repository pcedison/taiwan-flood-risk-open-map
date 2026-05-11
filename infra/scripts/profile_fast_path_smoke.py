from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
API_APP_ROOT = REPO_ROOT / "apps" / "api"
if str(API_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(API_APP_ROOT))

from app.domain.profiles import (  # noqa: E402
    RiskProfileRepositoryUnavailable,
    fetch_best_profile_for_point,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Smoke-test the PostGIS precomputed risk profile fast path."
    )
    parser.add_argument("--database-url", default=None, help="PostGIS URL. Defaults to DATABASE_URL.")
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lng", type=float, required=True)
    parser.add_argument("--radius-m", type=int, default=500)
    parser.add_argument("--allow-missing", action="store_true")
    parser.add_argument("--evidence-json", help="Optional JSON output path.")
    args = parser.parse_args(argv)

    database_url = args.database_url or _env("DATABASE_URL") or _env("WORKER_DATABASE_URL")
    if not database_url:
        return _emit(
            {
                "schema_version": "profile-fast-path-smoke/v1",
                "status": "skipped",
                "reason": "no_database_url",
            },
            output_path=args.evidence_json,
            exit_code=0 if args.allow_missing else 1,
        )

    try:
        profile = fetch_best_profile_for_point(
            database_url=database_url,
            lat=args.lat,
            lng=args.lng,
            radius_m=args.radius_m,
            now=datetime.now(UTC),
        )
    except RiskProfileRepositoryUnavailable as exc:
        return _emit(
            {
                "schema_version": "profile-fast-path-smoke/v1",
                "status": "failed",
                "reason": "repository_unavailable",
                "error": str(exc),
            },
            output_path=args.evidence_json,
            exit_code=1,
        )

    if profile is None:
        return _emit(
            {
                "schema_version": "profile-fast-path-smoke/v1",
                "status": "missing",
                "reason": "no_matching_fresh_profile",
                "query": {"lat": args.lat, "lng": args.lng, "radius_m": args.radius_m},
            },
            output_path=args.evidence_json,
            exit_code=0 if args.allow_missing else 1,
        )

    return _emit(
        {
            "schema_version": "profile-fast-path-smoke/v1",
            "status": "passed",
            "query": {"lat": args.lat, "lng": args.lng, "radius_m": args.radius_m},
            "profile": {
                "profile_kind": profile.profile_kind,
                "profile_key": profile.profile_key,
                "profile_scope": profile.profile_scope,
                "profile_radius_m": profile.profile_radius_m,
                "score_version": profile.score_version,
                "realtime_level": profile.realtime_level,
                "historical_level": profile.historical_level,
                "confidence_level": profile.confidence_level,
                "computed_at": profile.computed_at.isoformat(),
                "expires_at": profile.expires_at.isoformat() if profile.expires_at else None,
                "distance_to_query_m": profile.distance_to_query_m,
                "missing_sources": profile.missing_sources,
                "coverage_gaps": profile.coverage_gaps,
            },
        },
        output_path=args.evidence_json,
        exit_code=0,
    )


def _env(name: str) -> str | None:
    import os

    value = os.getenv(name)
    return value.strip() if value and value.strip() else None


def _emit(payload: dict[str, Any], *, output_path: str | None, exit_code: int) -> int:
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    print(text)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
