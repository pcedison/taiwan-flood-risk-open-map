from __future__ import annotations

import argparse
import json
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "https://floodrisk.zeabur.app"
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

    failures.extend(check_geocode_exact(base_url))
    failures.extend(check_geocode_admin_confirmation(base_url))
    failures.extend(check_uncovered_address_admin_fallback(base_url))

    if failures:
        print("HOSTED_PUBLIC_BETA_SMOKE failed")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("HOSTED_PUBLIC_BETA_SMOKE passed")
    return 0


def check_geocode_exact(base_url: str) -> list[str]:
    query = "台南市安南區長溪路二段410巷16弄1號"
    result = request_json(
        "POST",
        f"{base_url}/v1/geocode",
        {"query": query, "input_type": "address", "limit": 1},
    )
    if result.status_code != 200:
        return [f"exact geocode returned HTTP {result.status_code}: {result.error or result.payload}"]
    candidates = result.payload.get("candidates", [])
    if not candidates:
        return [f"exact geocode returned no candidates for {query}"]
    candidate = candidates[0]
    failures = require_candidate_fields(candidate, "exact geocode")
    if failures:
        return failures
    if candidate.get("precision") != "exact_address":
        failures.append(f"exact geocode precision should be exact_address, got {candidate.get('precision')}")
    if candidate.get("requires_confirmation") is not False:
        failures.append("exact geocode should not require confirmation")
    if abs(candidate.get("point", {}).get("lat", 0) - 23.05753) > 0.05:
        failures.append(f"exact geocode latitude looks wrong: {candidate.get('point')}")
    if failures:
        return failures

    risk = request_json(
        "POST",
        f"{base_url}/v1/risk/assess",
        {
            "point": candidate["point"],
            "radius_m": 500,
            "time_context": "now",
            "location_text": f"{query}｜{candidate['name']}",
        },
    )
    if risk.status_code != 200:
        return [f"risk assessment returned HTTP {risk.status_code}: {risk.error or risk.payload}"]
    print(
        "PASS hosted exact | "
        f"{query} -> {candidate['name']} | "
        f"historical={risk.payload['historical']['level']}"
    )
    return []


def check_geocode_admin_confirmation(base_url: str) -> list[str]:
    query = "宜蘭縣礁溪鄉"
    result = request_json(
        "POST",
        f"{base_url}/v1/geocode",
        {"query": query, "input_type": "address", "limit": 1},
    )
    if result.status_code != 200:
        return [f"admin geocode returned HTTP {result.status_code}: {result.error or result.payload}"]
    candidates = result.payload.get("candidates", [])
    if not candidates:
        return [f"admin geocode returned no candidates for {query}"]
    candidate = candidates[0]
    failures = require_candidate_fields(candidate, "admin geocode")
    if failures:
        return failures
    if candidate.get("precision") != "admin_area":
        failures.append(f"admin geocode precision should be admin_area, got {candidate.get('precision')}")
    if candidate.get("requires_confirmation") is not True:
        failures.append("admin geocode should require confirmation")
    if failures:
        return failures
    print(
        "PASS hosted admin confirmation | "
        f"{query} -> {candidate['name']} | requires_confirmation=true"
    )
    return []


def check_uncovered_address_admin_fallback(base_url: str) -> list[str]:
    query = "高雄市苓雅區四維三路2號"
    result = request_json(
        "POST",
        f"{base_url}/v1/geocode",
        {"query": query, "input_type": "address", "limit": 1},
    )
    if result.status_code != 200:
        return [f"admin fallback geocode returned HTTP {result.status_code}: {result.error or result.payload}"]
    candidates = result.payload.get("candidates", [])
    if not candidates:
        return [f"admin fallback geocode returned no candidates for {query}"]
    candidate = candidates[0]
    failures = require_candidate_fields(candidate, "admin fallback geocode")
    if failures:
        return failures
    if candidate.get("source") != "taiwan-admin-centroid-fallback":
        failures.append(f"admin fallback source should be taiwan-admin-centroid-fallback, got {candidate.get('source')}")
    if candidate.get("precision") != "admin_area":
        failures.append(f"admin fallback precision should be admin_area, got {candidate.get('precision')}")
    if candidate.get("requires_confirmation") is not True:
        failures.append("admin fallback should require confirmation")

    risk = request_json(
        "POST",
        f"{base_url}/v1/risk/assess",
        {
            "point": candidate["point"],
            "radius_m": 500,
            "time_context": "now",
            "location_text": f"{query}｜{candidate['name']}",
        },
    )
    if risk.status_code != 200:
        failures.append(f"admin fallback risk assessment returned HTTP {risk.status_code}: {risk.error or risk.payload}")
    elif not risk.payload.get("explanation", {}).get("summary"):
        failures.append("admin fallback risk assessment did not return an explanation summary")
    if failures:
        return failures
    print(
        "PASS hosted admin fallback | "
        f"{query} -> {candidate['name']} | risk={risk.payload['historical']['level']}"
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
