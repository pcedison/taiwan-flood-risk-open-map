#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import ssl
import sys
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
API_APP = ROOT / "apps" / "api"
sys.path.insert(0, str(API_APP))

from app.domain.realtime.local_source_action_plan import (  # noqa: E402
    build_local_source_action_plan,
)
from app.domain.realtime.local_source_contract_probe import (  # noqa: E402
    ProbeHttpResponse,
    build_public_api_contract_probe,
)
from app.domain.realtime.local_source_coverage import (  # noqa: E402
    list_local_source_coverage,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Probe public API contract review candidates and emit normalized "
            "evidence showing whether any candidate exposes a production-ready "
            "latest-observation read API contract."
        )
    )
    parser.add_argument("--captured-at")
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    parser.add_argument(
        "--allow-insecure-tls",
        action="store_true",
        help=(
            "Allow probing public government pages whose certificate chain is "
            "rejected by Python's strict TLS verifier. The artifact records this "
            "as tls_verification=disabled."
        ),
    )
    parser.add_argument(
        "--fixture-response-json",
        help=(
            "Optional test fixture mapping URL or 'default' to "
            "status_code/content_type/text/error."
        ),
    )
    parser.add_argument("--output", help="Optional JSON evidence output path.")
    parser.add_argument(
        "--fail-on-live-candidate",
        action="store_true",
        help=(
            "Exit 1 when a candidate_live_read_api is found, so a caller can "
            "stop and implement/verify an adapter instead of leaving the source "
            "in contract review."
        ),
    )
    args = parser.parse_args(argv)

    fixture = _load_fixture(args.fixture_response_json)
    fetcher = (
        _fixture_fetcher(fixture)
        if fixture is not None
        else _http_fetcher(verify_tls=not args.allow_insecure_tls)
    )
    artifact = build_public_api_contract_probe(
        build_local_source_action_plan(list_local_source_coverage()),
        captured_at=args.captured_at,
        timeout_seconds=args.timeout_seconds,
        fetcher=fetcher,
    )
    artifact["summary"]["tls_verification"] = (
        "disabled" if args.allow_insecure_tls else "enabled"
    )
    content = json.dumps(artifact, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")
        print(f"Wrote {output_path}", file=sys.stderr)
    else:
        print(content, end="")

    if args.fail_on_live_candidate and artifact["conclusion"] == "candidate_live_read_api_found":
        print("candidate_live_read_api_found", file=sys.stderr)
        return 1
    return 0


def _http_fetcher(*, verify_tls: bool):
    def fetch(url: str, timeout_seconds: float) -> ProbeHttpResponse:
        return _fetch_url(url, timeout_seconds, verify_tls=verify_tls)

    return fetch


def _fetch_url(
    url: str,
    timeout_seconds: float,
    *,
    verify_tls: bool,
) -> ProbeHttpResponse:
    request = Request(url, headers={"User-Agent": "FloodRiskContractProbe/0.1"})
    context = None if verify_tls else ssl._create_unverified_context()
    try:
        with urlopen(request, timeout=timeout_seconds, context=context) as response:
            raw = response.read()
            encoding = response.headers.get_content_charset() or "utf-8"
            try:
                text = raw.decode(encoding)
            except UnicodeDecodeError:
                text = raw.decode("utf-8", errors="replace")
            return ProbeHttpResponse(
                url=url,
                status_code=response.status,
                content_type=response.headers.get("Content-Type", ""),
                text=text[:200_000],
                error=None,
            )
    except HTTPError as exc:
        return ProbeHttpResponse(
            url=url,
            status_code=exc.code,
            content_type=exc.headers.get("Content-Type", ""),
            text="",
            error=str(exc),
        )
    except (TimeoutError, URLError, OSError) as exc:
        return ProbeHttpResponse(
            url=url,
            status_code=0,
            content_type="",
            text="",
            error=str(exc),
        )


def _load_fixture(path: str | None) -> dict[str, Any] | None:
    if path is None:
        return None
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("--fixture-response-json must be a JSON object")
    return payload


def _fixture_fetcher(fixture: Mapping[str, Any]):
    def fetch(url: str, timeout_seconds: float) -> ProbeHttpResponse:
        item = fixture.get(url, fixture.get("default"))
        if not isinstance(item, Mapping):
            return ProbeHttpResponse(
                url=url,
                status_code=0,
                content_type="",
                text="",
                error="fixture response missing",
            )
        return ProbeHttpResponse(
            url=url,
            status_code=int(item.get("status_code", 0)),
            content_type=str(item.get("content_type", "")),
            text=str(item.get("text", "")),
            error=str(item["error"]) if item.get("error") else None,
        )

    return fetch


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
