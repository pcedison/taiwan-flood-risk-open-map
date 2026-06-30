from __future__ import annotations

import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
API_APP = REPO_ROOT / "apps" / "api"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(API_APP))

from app.domain.geocoding.providers import TaiwanAdminArea  # noqa: E402
from scripts import taiwan_wide_public_beta_smoke as smoke  # noqa: E402


def test_public_beta_smoke_writes_evidence_output(
    tmp_path: Path,
    monkeypatch,
) -> None:
    sample = TaiwanAdminArea(
        name="測試縣",
        county="測試縣",
        town=None,
        lat=23.5,
        lng=121.0,
        admin_code="99999",
        level="county",
        aliases=(),
    )
    output_path = tmp_path / "public-beta-smoke.json"

    monkeypatch.setattr(
        smoke,
        "taiwan_wide_samples",
        lambda *, include_town_samples, all_towns: (sample,),
    )

    def fake_request_json(
        method: str,
        url: str,
        payload=None,
        *,
        timeout_seconds: float,
    ) -> smoke.JsonResponse:
        if url.endswith("/health"):
            return smoke.JsonResponse(
                status_code=200,
                payload={
                    "status": "ok",
                    "version": "public-beta-mvp-2026-05-04",
                    "deployment_sha": "abc123",
                },
            )
        if url.endswith("/v1/geocode"):
            return smoke.JsonResponse(
                status_code=200,
                payload={
                    "candidates": [
                        {
                            "source": "fixture",
                            "precision": "admin_area",
                            "requires_confirmation": True,
                            "point": {"lat": 23.5, "lng": 121.0},
                        }
                    ]
                },
            )
        if url.endswith("/v1/risk/assess"):
            return smoke.JsonResponse(
                status_code=200,
                payload={
                    "assessment_id": "risk-1",
                    "realtime": {"level": "低"},
                    "historical": {"level": "中"},
                    "confidence": {"level": "高"},
                    "explanation": {"summary": "fixture"},
                    "data_freshness": [],
                    "evidence": [],
                },
            )
        raise AssertionError(f"unexpected request {method} {url} {payload}")

    monkeypatch.setattr(smoke, "request_json", fake_request_json)

    result = smoke.main(
        [
            "--base-url",
            "https://example.test",
            "--evidence-output",
            str(output_path),
        ]
    )

    assert result == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload == {
        "schema_version": "taiwan-wide-public-beta-smoke/v1",
        "base_url": "https://example.test",
        "status": "passed",
        "health": {
            "status_code": 200,
            "version": "public-beta-mvp-2026-05-04",
            "deployment_sha": "abc123",
        },
        "sample_count": 1,
        "failures": [],
        "samples": [
            {
                "level": "county",
                "name": "測試縣",
                "county": "測試縣",
                "source": "fixture",
                "precision": "admin_area",
                "risk_realtime_level": "低",
                "risk_historical_level": "中",
            }
        ],
    }
