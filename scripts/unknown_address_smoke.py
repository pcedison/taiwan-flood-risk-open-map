from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "apps" / "api"
sys.path.insert(0, str(API_ROOT))

os.environ.setdefault("APP_ENV", "local")
os.environ.setdefault("EVIDENCE_REPOSITORY_ENABLED", "false")
os.environ.setdefault("REALTIME_OFFICIAL_ENABLED", "false")
os.environ.setdefault("HISTORICAL_NEWS_ON_DEMAND_ENABLED", "false")

from app.api.routes import public as public_routes  # noqa: E402
from app.main import create_app  # noqa: E402


public_routes._cached_nominatim_candidates = lambda *_args: ()
public_routes._cached_wikimedia_candidates = lambda *_args: ()


def main() -> int:
    client = TestClient(create_app())
    checks = (
        {
            "query": "台南市安南區長溪路二段410巷16弄1號",
            "expect_precision": "exact_address",
            "expect_assess": True,
            "expect_historical": "高",
        },
        {
            "query": "嘉義市東區林森東路151號",
            "expect_precision": "road_or_lane",
            "expect_assess": True,
            "expect_historical": None,
        },
        {
            "query": "宜蘭縣礁溪鄉",
            "expect_precision": "admin_area",
            "expect_assess": False,
            "expect_historical": None,
        },
        {
            "query": "不存在的測試地點999999",
            "expect_precision": None,
            "expect_assess": False,
            "expect_historical": None,
        },
    )

    failures: list[str] = []
    for check in checks:
        failure = run_check(client, check)
        if failure is not None:
            failures.append(failure)

    if failures:
        print("UNKNOWN_ADDRESS_SMOKE failed")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("UNKNOWN_ADDRESS_SMOKE passed")
    return 0


def run_check(client: TestClient, check: dict[str, Any]) -> str | None:
    query = check["query"]
    geocode_response = client.post(
        "/v1/geocode",
        json={"query": query, "input_type": "address", "limit": 1},
    )
    if geocode_response.status_code != 200:
        return f"{query}: geocode returned HTTP {geocode_response.status_code}"

    candidates = geocode_response.json()["candidates"]
    expected_precision = check["expect_precision"]
    if expected_precision is None:
        if candidates:
            return f"{query}: expected no geocode candidates, got {candidates[0]['name']}"
        print(f"PASS no-match | {query}")
        return None

    if not candidates:
        return f"{query}: expected a candidate with precision {expected_precision}, got none"

    candidate = candidates[0]
    if candidate["precision"] != expected_precision:
        return f"{query}: expected precision {expected_precision}, got {candidate['precision']}"

    print(
        "PASS geocode | "
        f"{query} -> {candidate['name']} | "
        f"precision={candidate['precision']} | "
        f"confidence={candidate['confidence']} | "
        f"requires_confirmation={candidate['requires_confirmation']}"
    )

    if candidate["requires_confirmation"]:
        if check["expect_assess"]:
            return f"{query}: candidate requires confirmation but check expected assessment"
        return None

    if not check["expect_assess"]:
        return None

    risk_response = client.post(
        "/v1/risk/assess",
        json={
            "point": candidate["point"],
            "radius_m": 500,
            "time_context": "now",
            "location_text": f"{query}｜{candidate['name']}",
        },
    )
    if risk_response.status_code != 200:
        return f"{query}: risk returned HTTP {risk_response.status_code}"

    risk = risk_response.json()
    expected_historical = check["expect_historical"]
    if expected_historical is not None and risk["historical"]["level"] != expected_historical:
        return (
            f"{query}: expected historical risk {expected_historical}, "
            f"got {risk['historical']['level']}"
        )

    print(
        "PASS risk | "
        f"{query} | realtime={risk['realtime']['level']} | "
        f"historical={risk['historical']['level']} | "
        f"confidence={risk['confidence']['level']} | "
        f"evidence={len(risk['evidence'])}"
    )
    return None


if __name__ == "__main__":
    raise SystemExit(main())
