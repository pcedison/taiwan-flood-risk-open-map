from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "apps" / "api"
sys.path.insert(0, str(API_ROOT))

from app.domain.geocoding.providers import TaiwanAdminArea, load_taiwan_admin_areas  # noqa: E402


DEFAULT_BASE_URL = "https://floodrisk.cc"
TAIWAN_BOUNDS = {
    "lat_min": 21.7,
    "lat_max": 26.5,
    "lng_min": 118.0,
    "lng_max": 122.5,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Taiwan-wide public beta smoke: geocode and assess every county/city.",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument(
        "--include-town-samples",
        action="store_true",
        help="Also assess one township/district sample per county/city.",
    )
    parser.add_argument(
        "--all-towns",
        action="store_true",
        help="Assess every bundled Taiwan township/district. Use sparingly against hosted deployments.",
    )
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    parser.add_argument(
        "--evidence-output",
        help="Optional JSON file capturing deployment SHA and sampled public risk-query smoke evidence.",
    )
    args = parser.parse_args(argv)

    base_url = args.base_url.rstrip("/")
    samples = taiwan_wide_samples(
        include_town_samples=args.include_town_samples,
        all_towns=args.all_towns,
    )
    failures: list[str] = []
    evidence_samples: list[dict[str, Any]] = []
    health_evidence: dict[str, Any] = {"status_code": None}
    checked = 0

    health = request_json("GET", f"{base_url}/health", timeout_seconds=args.timeout_seconds)
    health_evidence = {
        "status_code": health.status_code,
        "version": health.payload.get("version"),
        "deployment_sha": health.payload.get("deployment_sha"),
    }
    if health.status_code != 200:
        failures.append(f"/health returned HTTP {health.status_code}: {health.error or health.payload}")
    else:
        print(
            "PASS health | "
            f"version={health.payload.get('version')} | "
            f"deployment_sha={health.payload.get('deployment_sha') or 'missing'}"
        )

    for sample in samples:
        failures.extend(
            check_sample(
                base_url,
                sample,
                timeout_seconds=args.timeout_seconds,
                evidence_samples=evidence_samples,
            )
        )
        checked += 1

    if failures:
        print(f"TAIWAN_WIDE_PUBLIC_BETA_SMOKE failed | checked={checked}")
        for failure in failures:
            print(f"- {failure}")
        _write_evidence_output(
            args.evidence_output,
            base_url=base_url,
            status="failed",
            health=health_evidence,
            sample_count=checked,
            failures=failures,
            samples=evidence_samples,
        )
        return 1

    print(f"TAIWAN_WIDE_PUBLIC_BETA_SMOKE passed | checked={checked}")
    _write_evidence_output(
        args.evidence_output,
        base_url=base_url,
        status="passed",
        health=health_evidence,
        sample_count=checked,
        failures=[],
        samples=evidence_samples,
    )
    return 0


def taiwan_wide_samples(
    *,
    include_town_samples: bool = False,
    all_towns: bool = False,
) -> tuple[TaiwanAdminArea, ...]:
    areas = load_taiwan_admin_areas()
    counties = sorted((area for area in areas if area.level == "county"), key=lambda item: item.name)
    towns = sorted((area for area in areas if area.level == "town"), key=lambda item: (item.county, item.name))
    if len(counties) != 22:
        raise RuntimeError(f"expected 22 Taiwan county/city samples, got {len(counties)}")

    selected = list(counties)
    if all_towns:
        selected.extend(towns)
    elif include_town_samples:
        first_town_by_county: dict[str, TaiwanAdminArea] = {}
        for town in towns:
            first_town_by_county.setdefault(town.county, town)
        selected.extend(first_town_by_county[county.name] for county in counties)
    return tuple(selected)


def check_sample(
    base_url: str,
    sample: TaiwanAdminArea,
    *,
    timeout_seconds: float,
    evidence_samples: list[dict[str, Any]] | None = None,
) -> list[str]:
    failures: list[str] = []
    geocode = request_json(
        "POST",
        f"{base_url}/v1/geocode",
        {"query": sample.name, "input_type": "address", "limit": 1},
        timeout_seconds=timeout_seconds,
    )
    label = f"{sample.level}:{sample.name}"
    if geocode.status_code != 200:
        return [f"{label} geocode returned HTTP {geocode.status_code}: {geocode.error or geocode.payload}"]
    candidates = geocode.payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return [f"{label} geocode returned no candidates"]

    candidate = candidates[0]
    if not isinstance(candidate, dict):
        return [f"{label} geocode returned non-object candidate: {candidate}"]

    point = candidate.get("point")
    if not isinstance(point, dict):
        failures.append(f"{label} geocode candidate has no point")
    else:
        lat = point.get("lat")
        lng = point.get("lng")
        if not isinstance(lat, int | float) or not isinstance(lng, int | float):
            failures.append(f"{label} geocode point is not numeric: {point}")
        elif not (
            TAIWAN_BOUNDS["lat_min"] <= float(lat) <= TAIWAN_BOUNDS["lat_max"]
            and TAIWAN_BOUNDS["lng_min"] <= float(lng) <= TAIWAN_BOUNDS["lng_max"]
        ):
            failures.append(f"{label} geocode point is outside Taiwan bounds: {point}")

    if candidate.get("precision") != "admin_area":
        failures.append(f"{label} should geocode as admin_area, got {candidate.get('precision')}")
    if candidate.get("requires_confirmation") is not True:
        failures.append(f"{label} admin geocode should require confirmation")

    if failures:
        return failures

    risk = request_json(
        "POST",
        f"{base_url}/v1/risk/assess",
        {
            "point": point,
            "radius_m": 500,
            "time_context": "now",
            "location_text": sample.name,
        },
        timeout_seconds=timeout_seconds,
    )
    if risk.status_code != 200:
        failures.append(f"{label} risk returned HTTP {risk.status_code}: {risk.error or risk.payload}")
    else:
        failures.extend(require_risk_fields(risk.payload, label))

    if not failures:
        print(
            "PASS sample | "
            f"{label} | source={candidate.get('source')} | "
            f"risk={risk.payload.get('realtime', {}).get('level')}/"
            f"{risk.payload.get('historical', {}).get('level')}"
        )
        if evidence_samples is not None:
            evidence_samples.append(
                {
                    "level": sample.level,
                    "name": sample.name,
                    "county": sample.county,
                    "source": candidate.get("source"),
                    "precision": candidate.get("precision"),
                    "risk_realtime_level": risk.payload.get("realtime", {}).get("level"),
                    "risk_historical_level": risk.payload.get("historical", {}).get("level"),
                }
            )
    return failures


def require_risk_fields(payload: dict[str, Any], label: str) -> list[str]:
    failures: list[str] = []
    for field in ("assessment_id", "realtime", "historical", "confidence", "explanation"):
        if field not in payload:
            failures.append(f"{label} risk missing {field}")
    if not payload.get("explanation", {}).get("summary"):
        failures.append(f"{label} risk missing explanation summary")
    if not isinstance(payload.get("data_freshness"), list):
        failures.append(f"{label} risk data_freshness should be a list")
    if not isinstance(payload.get("evidence"), list):
        failures.append(f"{label} risk evidence should be a list")
    return failures


def _write_evidence_output(
    output_path: str | None,
    *,
    base_url: str,
    status: str,
    health: dict[str, Any],
    sample_count: int,
    failures: list[str],
    samples: list[dict[str, Any]],
) -> None:
    if output_path is None:
        return
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "taiwan-wide-public-beta-smoke/v1",
        "base_url": base_url,
        "status": status,
        "health": health,
        "sample_count": sample_count,
        "failures": failures,
        "samples": samples,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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


def request_json(
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout_seconds: float,
) -> JsonResponse:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method=method,
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return JsonResponse(
                status_code=response.status,
                payload=json.loads(response.read().decode("utf-8")),
            )
    except HTTPError as exc:
        try:
            error_payload = json.loads(exc.read().decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            error_payload = {}
        return JsonResponse(status_code=exc.code, payload=error_payload, error=str(exc))
    except (TimeoutError, URLError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return JsonResponse(status_code=0, payload={}, error=str(exc))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
