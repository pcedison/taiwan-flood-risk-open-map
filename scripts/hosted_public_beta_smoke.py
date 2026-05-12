from __future__ import annotations

import argparse
import json
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "https://floodrisk.cc"
REQUIRED_GEOCODE_FIELDS = {
    "precision",
    "matched_query",
    "requires_confirmation",
    "limitations",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="No-secret hosted public beta smoke check.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    args = parser.parse_args(argv)

    base_url = args.base_url.rstrip("/")
    failures: list[str] = []

    health = request_json("GET", f"{base_url}/health")
    if health.status_code != 200:
        failures.append(f"/health returned HTTP {health.status_code}: {health.error or health.payload}")
    else:
        deployment_sha = health.payload.get("deployment_sha")
        print(
            "PASS health | "
            f"service={health.payload.get('service')} | "
            f"version={health.payload.get('version')} | "
            f"deployment_sha={deployment_sha or 'missing'}"
        )
        if not deployment_sha:
            failures.append(
                "/health does not expose deployment_sha; set DEPLOYMENT_SHA or deploy code with the new health contract"
            )

    failures.extend(
        check_geocode_candidate(
            base_url,
            label="road bundle",
            query="\u81fa\u5317\u5e02\u5927\u5b89\u5340\u4fe1\u7fa9\u8def\u4e09\u6bb5100\u865f",
            expected_precision="road_or_lane",
            expected_sources=(
                "local-open-data:moi-national-road-names",
                "postgis-open-data:moi-national-road-names",
            ),
            expected_confirmation=True,
            assess_risk=True,
        )
    )
    failures.extend(
        check_geocode_candidate(
            base_url,
            label="POI bundle",
            query="\u4e94\u5cf0\u6d3b\u52d5\u4e2d\u5fc3",
            expected_precision="poi",
            expected_sources=(
                "local-open-data:nfa-evacuation-shelter-locations",
                "postgis-open-data:nfa-evacuation-shelter-locations",
            ),
            expected_confirmation=False,
        )
    )
    failures.extend(
        check_geocode_candidate(
            base_url,
            label="admin bundle",
            query="\u65b0\u5317\u5e02\u65b0\u838a\u5340\u897f\u76db\u91cc",
            expected_precision="admin_area",
            expected_sources=(
                "local-open-data:moi-village-boundary-twd97-geographic",
                "postgis-open-data:moi-village-boundary-twd97-geographic",
            ),
            expected_confirmation=True,
        )
    )

    if failures:
        print("HOSTED_PUBLIC_BETA_SMOKE failed")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("HOSTED_PUBLIC_BETA_SMOKE passed")
    return 0


def check_geocode_candidate(
    base_url: str,
    *,
    label: str,
    query: str,
    expected_precision: str,
    expected_sources: tuple[str, ...],
    expected_confirmation: bool,
    assess_risk: bool = False,
) -> list[str]:
    result = request_json(
        "POST",
        f"{base_url}/v1/geocode",
        {"query": query, "input_type": "address", "limit": 1},
    )
    if result.status_code != 200:
        return [f"{label} geocode returned HTTP {result.status_code}: {result.error or result.payload}"]
    candidates = result.payload.get("candidates", [])
    if not candidates:
        return [f"{label} geocode returned no candidates"]
    candidate = candidates[0]
    failures = require_candidate_fields(candidate, f"{label} geocode")
    if failures:
        return failures
    if candidate.get("precision") != expected_precision:
        failures.append(
            f"{label} precision should be {expected_precision}, got {candidate.get('precision')}"
        )
    if candidate.get("source") not in expected_sources:
        failures.append(
            f"{label} source should be one of {', '.join(expected_sources)}, got {candidate.get('source')}"
        )
    if candidate.get("requires_confirmation") is not expected_confirmation:
        failures.append(f"{label} requires_confirmation should be {expected_confirmation}")
    if expected_confirmation and not candidate.get("limitations"):
        failures.append(f"{label} should include a visible beta limitation")

    if assess_risk:
        risk = request_json(
            "POST",
            f"{base_url}/v1/risk/assess",
            {
                "point": candidate["point"],
                "radius_m": 500,
                "time_context": "now",
                "location_text": query,
            },
        )
        if risk.status_code != 200:
            failures.append(f"{label} risk assessment returned HTTP {risk.status_code}: {risk.error or risk.payload}")
        elif not risk.payload.get("explanation", {}).get("summary"):
            failures.append(f"{label} risk assessment did not return an explanation summary")

    if failures:
        return failures
    print(
        f"PASS hosted {label} | "
        f"precision={candidate['precision']} | "
        f"source={candidate['source']} | "
        f"requires_confirmation={str(candidate['requires_confirmation']).lower()}"
    )
    return []


def require_candidate_fields(candidate: dict[str, Any], label: str) -> list[str]:
    missing = sorted(REQUIRED_GEOCODE_FIELDS - set(candidate))
    if missing:
        return [f"{label} is missing deployed MVP fields: {missing}"]
    return []


class JsonResponse:
    def __init__(
        self,
        *,
        status_code: int,
        payload: dict[str, Any],
        error: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.payload = payload
        self.error = error


def request_json(method: str, url: str, payload: dict[str, Any] | None = None) -> JsonResponse:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method=method,
    )
    try:
        with urlopen(request, timeout=20) as response:
            return JsonResponse(
                status_code=response.status,
                payload=json.loads(response.read().decode("utf-8")),
            )
    except HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = {}
        return JsonResponse(status_code=exc.code, payload=payload, error=str(exc))
    except (TimeoutError, URLError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return JsonResponse(status_code=0, payload={}, error=str(exc))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
