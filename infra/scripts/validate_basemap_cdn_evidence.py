from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = (
    REPO_ROOT / "docs" / "runbooks" / "basemap-cdn-evidence.example.yaml"
)

SCHEMA_VERSION = "basemap-cdn-evidence/v1"
PUBLIC_OSM_TILE_HOST = "tile.openstreetmap.org"

REQUIRED_TOP_LEVEL_FIELDS = {
    "schema_version",
    "production_complete",
    "basemap_kind",
    "style_url",
    "style_url_source",
    "pmtiles_url",
    "pmtiles_url_source",
    "attribution",
    "provider",
    "license",
    "cadence",
    "range_request",
    "cors",
    "cache_control",
    "browser_network_log_ref",
    "desktop_screenshot_ref",
    "mobile_screenshot_ref",
    "no_public_osm_tile_request",
}

ALLOWED_BASEMAP_KINDS = {"pmtiles", "style", "raster", "hosted-style"}

PLACEHOLDER_TOKENS = (
    "placeholder",
    "replace-with",
    "template-only",
    "template only",
    "not-run",
    "not run",
    "todo",
    "tbd",
    "example.com",
    "example.invalid",
    "your-",
    "set-in",
    "missing",
)

TEMPLATE_OWNER_VALUES = {
    "basemap-owner",
    "cdn-owner",
    "data-owner",
    "license-owner",
    "owner",
    "platform-owner",
    "web-owner",
}

LOCAL_OR_NON_PRODUCTION_HOSTS = {
    "localhost",
    "127.0.0.1",
    "::1",
}

KNOWN_DEMO_URL_FRAGMENTS = (
    "demo-bucket.protomaps.com",
    "protomaps-sample-datasets",
    "sample",
    "demo",
)

RUNBOOK_ONLY_EVIDENCE_PREFIXES = (
    "docs/",
    "./docs/",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate production PMTiles/CDN evidence YAML/JSON."
    )
    parser.add_argument(
        "evidence_path",
        nargs="?",
        default=str(DEFAULT_EVIDENCE_PATH),
        help="Evidence YAML/JSON path. Defaults to the checked-in example template.",
    )
    parser.add_argument(
        "--production-complete",
        action="store_true",
        help=(
            "Require production_complete: true and real operator-provided CDN "
            "evidence. The default mode accepts the checked-in demo/template."
        ),
    )
    parser.add_argument(
        "--probe",
        metavar="PMTILES_URL",
        help=(
            "Issue stdlib HEAD and Range requests to a PMTiles URL and print a "
            "JSON evidence fragment instead of validating an evidence file."
        ),
    )
    parser.add_argument(
        "--origin",
        default="https://flood-risk.example.invalid",
        help="Origin header to send with --probe for CORS evidence.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=20.0,
        help="Network timeout for --probe requests.",
    )
    args = parser.parse_args(argv)

    if args.probe:
        fragment = probe_pmtiles_url(
            args.probe,
            origin=args.origin,
            timeout_seconds=args.timeout_seconds,
        )
        print(json.dumps(fragment, indent=2, sort_keys=True))
        return 0 if "error" not in fragment else 1

    evidence_path = Path(args.evidence_path)
    errors = validate_evidence_file(
        evidence_path,
        require_production_complete=args.production_complete,
    )
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    try:
        display_path = evidence_path.resolve().relative_to(REPO_ROOT)
    except ValueError:
        display_path = evidence_path
    print(f"Basemap CDN evidence valid: {display_path}")
    return 0


def validate_evidence_file(
    path: Path,
    *,
    require_production_complete: bool = False,
) -> list[str]:
    errors: list[str] = []
    evidence = _load_evidence(path, errors)
    if isinstance(evidence, dict):
        validate_evidence(
            evidence,
            errors,
            require_production_complete=require_production_complete,
        )
    return errors


def validate_evidence(
    evidence: dict[str, Any],
    errors: list[str],
    *,
    require_production_complete: bool = False,
) -> None:
    missing = REQUIRED_TOP_LEVEL_FIELDS - set(evidence)
    if missing:
        errors.append(f"missing required fields: {sorted(missing)}")

    if evidence.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION!r}")

    production_complete = evidence.get("production_complete")
    if not isinstance(production_complete, bool):
        errors.append("production_complete must be true or false")
        production_complete = require_production_complete

    if require_production_complete and production_complete is not True:
        errors.append("production_complete must be true when --production-complete is used")

    production_acceptance = production_complete is True or require_production_complete

    if production_acceptance and evidence.get("demo_mode") is True:
        errors.append("demo_mode must be false or absent when production_complete is true")

    _validate_basemap_identity(
        evidence,
        errors,
        production_acceptance=production_acceptance,
    )
    _validate_provider_license_cadence(
        evidence,
        errors,
        production_acceptance=production_acceptance,
    )
    _validate_range_request(
        evidence.get("range_request"),
        errors,
        production_acceptance=production_acceptance,
    )
    _validate_cors(
        evidence.get("cors"),
        errors,
        production_acceptance=production_acceptance,
    )
    _validate_cache_control(
        evidence.get("cache_control"),
        errors,
        production_acceptance=production_acceptance,
    )
    _validate_browser_refs(
        evidence,
        errors,
        production_acceptance=production_acceptance,
    )
    _validate_no_public_osm_tile_request(
        evidence.get("no_public_osm_tile_request"),
        errors,
        production_acceptance=production_acceptance,
    )


def probe_pmtiles_url(
    url: str,
    *,
    origin: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    headers = {
        "Origin": origin,
        "User-Agent": "flood-risk-basemap-cdn-evidence/1.0",
    }
    head = _request_headers(url, method="HEAD", headers=headers, timeout_seconds=timeout_seconds)
    ranged = _request_headers(
        url,
        method="GET",
        headers={**headers, "Range": "bytes=0-16383"},
        timeout_seconds=timeout_seconds,
    )

    fragment: dict[str, Any] = {
        "pmtiles_url": url,
        "range_request": {
            "method": "GET",
            "request_header": "Range: bytes=0-16383",
            "status": ranged.get("status"),
            "content_range": ranged.get("headers", {}).get("content-range"),
            "accept_ranges": ranged.get("headers", {}).get("accept-ranges"),
        },
        "cors": {
            "request_origin": origin,
            "access_control_allow_origin": ranged.get("headers", {}).get(
                "access-control-allow-origin"
            )
            or head.get("headers", {}).get("access-control-allow-origin"),
            "access_control_allow_methods": ranged.get("headers", {}).get(
                "access-control-allow-methods"
            )
            or head.get("headers", {}).get("access-control-allow-methods"),
            "access_control_allow_headers": ranged.get("headers", {}).get(
                "access-control-allow-headers"
            )
            or head.get("headers", {}).get("access-control-allow-headers"),
            "validated": bool(
                ranged.get("headers", {}).get("access-control-allow-origin")
                or head.get("headers", {}).get("access-control-allow-origin")
            ),
        },
        "cache_control": {
            "header": ranged.get("headers", {}).get("cache-control")
            or head.get("headers", {}).get("cache-control"),
            "etag": ranged.get("headers", {}).get("etag") or head.get("headers", {}).get("etag"),
            "last_modified": ranged.get("headers", {}).get("last-modified")
            or head.get("headers", {}).get("last-modified"),
            "validated": bool(
                ranged.get("headers", {}).get("cache-control")
                or head.get("headers", {}).get("cache-control")
            ),
        },
        "probe": {
            "head_status": head.get("status"),
            "range_status": ranged.get("status"),
            "captured_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        },
    }

    errors = [
        result.get("error")
        for result in (head, ranged)
        if isinstance(result.get("error"), str)
    ]
    if errors:
        fragment["error"] = "; ".join(errors)
    return fragment


def _load_evidence(path: Path, errors: list[str]) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"{path}: {exc}")
        return None

    try:
        if path.suffix.lower() == ".json":
            return json.loads(text)
        return yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        errors.append(f"{path}: {exc}")
        return None


def _validate_basemap_identity(
    evidence: dict[str, Any],
    errors: list[str],
    *,
    production_acceptance: bool,
) -> None:
    basemap_kind = evidence.get("basemap_kind")
    if basemap_kind not in ALLOWED_BASEMAP_KINDS:
        errors.append(f"basemap_kind must be one of {sorted(ALLOWED_BASEMAP_KINDS)}")

    for field in ("style_url", "pmtiles_url"):
        value = evidence.get(field)
        if not _non_empty_string(value):
            errors.append(f"{field} is required")
        elif production_acceptance:
            _validate_real_http_url(value, field, errors)

    for field in ("style_url_source", "pmtiles_url_source", "attribution"):
        value = evidence.get(field)
        if not _non_empty_string(value):
            errors.append(f"{field} is required")
        elif production_acceptance:
            _validate_not_placeholder(value, field, errors)


def _validate_provider_license_cadence(
    evidence: dict[str, Any],
    errors: list[str],
    *,
    production_acceptance: bool,
) -> None:
    required_fields = {
        "provider": ("name", "owner"),
        "license": ("name", "owner"),
        "cadence": ("update_frequency", "owner"),
    }
    for section, fields in required_fields.items():
        value = evidence.get(section)
        if not isinstance(value, dict):
            errors.append(f"{section} must be an object")
            continue
        for field in fields:
            if not _non_empty_string(value.get(field)):
                errors.append(f"{section}.{field} is required")
        owner = value.get("owner")
        if production_acceptance and _non_empty_string(owner):
            _validate_real_owner(owner, f"{section}.owner", errors)
        if production_acceptance:
            _validate_production_evidence_ref(
                value.get("evidence_ref"),
                f"{section}.evidence_ref",
                errors,
            )


def _validate_range_request(
    value: Any,
    errors: list[str],
    *,
    production_acceptance: bool,
) -> None:
    if not isinstance(value, dict):
        errors.append("range_request must be an object")
        return

    status = _status_code(value.get("status"))
    if status is None:
        errors.append("range_request.status is required")
    elif production_acceptance and status != 206:
        errors.append("range_request.status must be 206 when production_complete is true")

    content_range = value.get("content_range")
    if not _non_empty_string(content_range):
        errors.append("range_request.content_range is required")
    elif production_acceptance and not _looks_like_content_range(content_range):
        errors.append("range_request.content_range must look like a bytes Content-Range header")

    if production_acceptance:
        request_header = value.get("request_header")
        if not _non_empty_string(request_header) or "range:" not in request_header.lower():
            errors.append("range_request.request_header must include a Range header")
        elif "bytes=" not in request_header.lower():
            errors.append("range_request.request_header must request a byte range")

        accept_ranges = value.get("accept_ranges")
        if _non_empty_string(accept_ranges) and "bytes" not in accept_ranges.lower():
            errors.append("range_request.accept_ranges must indicate bytes if present")

        _validate_production_evidence_ref(
            value.get("evidence_ref"),
            "range_request.evidence_ref",
            errors,
        )


def _validate_cors(
    value: Any,
    errors: list[str],
    *,
    production_acceptance: bool,
) -> None:
    if not isinstance(value, dict):
        errors.append("cors must be an object")
        return

    origin = value.get("access_control_allow_origin")
    if not _non_empty_string(origin):
        errors.append("cors.access_control_allow_origin is required")
    elif production_acceptance:
        _validate_not_placeholder(origin, "cors.access_control_allow_origin", errors)

    if production_acceptance and value.get("validated") is not True:
        errors.append("cors.validated must be true when production_complete is true")
    if production_acceptance:
        _validate_production_evidence_ref(value.get("evidence_ref"), "cors.evidence_ref", errors)


def _validate_cache_control(
    value: Any,
    errors: list[str],
    *,
    production_acceptance: bool,
) -> None:
    if not isinstance(value, dict):
        errors.append("cache_control must be an object")
        return

    header = value.get("header")
    if not _non_empty_string(header):
        errors.append("cache_control.header is required")
    elif production_acceptance:
        _validate_not_placeholder(header, "cache_control.header", errors)

    if production_acceptance and value.get("validated") is not True:
        errors.append("cache_control.validated must be true when production_complete is true")
    if production_acceptance:
        _validate_production_evidence_ref(
            value.get("evidence_ref"),
            "cache_control.evidence_ref",
            errors,
        )


def _validate_browser_refs(
    evidence: dict[str, Any],
    errors: list[str],
    *,
    production_acceptance: bool,
) -> None:
    for field in (
        "browser_network_log_ref",
        "desktop_screenshot_ref",
        "mobile_screenshot_ref",
    ):
        value = evidence.get(field)
        if not _non_empty_string(value):
            errors.append(f"{field} is required")
        elif production_acceptance:
            _validate_production_evidence_ref(value, field, errors)


def _validate_no_public_osm_tile_request(
    value: Any,
    errors: list[str],
    *,
    production_acceptance: bool,
) -> None:
    if not isinstance(value, dict):
        errors.append("no_public_osm_tile_request must be an object")
        return

    if production_acceptance and value.get("validated") is not True:
        errors.append(
            "no_public_osm_tile_request.validated must be true when production_complete is true"
        )

    if production_acceptance and _contains_public_osm_tile_host(value):
        errors.append(
            "no_public_osm_tile_request production request log must not include "
            f"{PUBLIC_OSM_TILE_HOST}"
        )


def _request_headers(
    url: str,
    *,
    method: str,
    headers: dict[str, str],
    timeout_seconds: float,
) -> dict[str, Any]:
    request = Request(url, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return {
                "status": response.status,
                "headers": {key.lower(): value for key, value in response.headers.items()},
            }
    except HTTPError as exc:
        return {
            "status": exc.code,
            "headers": {key.lower(): value for key, value in exc.headers.items()},
            "error": f"{method} returned HTTP {exc.code}",
        }
    except (OSError, URLError) as exc:
        return {"status": None, "headers": {}, "error": f"{method} failed: {exc}"}


def _status_code(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _looks_like_content_range(value: str) -> bool:
    text = value.strip().lower()
    return text.startswith("bytes ") and "/" in text and "-" in text


def _validate_real_http_url(value: Any, field: str, errors: list[str]) -> None:
    _validate_not_placeholder(value, field, errors)
    if not _non_empty_string(value):
        return

    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        errors.append(f"{field} must be an absolute http(s) URL")
        return

    host = parsed.hostname or ""
    if host.lower() in LOCAL_OR_NON_PRODUCTION_HOSTS:
        errors.append(f"{field} must not be a localhost/non-production URL")
    if any(fragment in value.lower() for fragment in KNOWN_DEMO_URL_FRAGMENTS):
        errors.append(f"{field} must be operator-provided production infrastructure, not a demo URL")


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_real_owner(value: Any, field: str, errors: list[str]) -> None:
    if _is_placeholder_owner(value):
        errors.append(f"{field} must name a real production owner, not a template placeholder")


def _validate_not_placeholder(value: Any, field: str, errors: list[str]) -> None:
    if _contains_placeholder(value):
        errors.append(f"{field} must not be a template placeholder")


def _validate_production_evidence_ref(value: Any, field: str, errors: list[str]) -> None:
    if not _non_empty_string(value):
        errors.append(f"{field} is required")
        return
    _validate_not_placeholder(value, field, errors)
    if value.strip().lower().startswith(RUNBOOK_ONLY_EVIDENCE_PREFIXES):
        errors.append(f"{field} must reference production evidence, not only runbook instructions")


def _contains_placeholder(value: Any) -> bool:
    if not _non_empty_string(value):
        return False
    text = value.strip().lower()
    return any(token in text for token in PLACEHOLDER_TOKENS)


def _is_placeholder_owner(value: Any) -> bool:
    if not _non_empty_string(value):
        return False
    text = value.strip().lower()
    return (
        text in TEMPLATE_OWNER_VALUES
        or text.endswith("-owner")
        or _contains_placeholder(text)
    )


def _contains_public_osm_tile_host(value: Any) -> bool:
    if isinstance(value, str):
        return PUBLIC_OSM_TILE_HOST in value.lower()
    if isinstance(value, list):
        return any(_contains_public_osm_tile_host(item) for item in value)
    if isinstance(value, dict):
        return any(_contains_public_osm_tile_host(item) for item in value.values())
    return False


if __name__ == "__main__":
    raise SystemExit(main())
