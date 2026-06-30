from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import sys
from urllib.error import HTTPError


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
        rate_limit_retries: int,
        rate_limit_retry_delay_seconds: float,
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


def test_request_json_retries_http_429_using_retry_after(monkeypatch) -> None:
    attempts = 0
    sleeps: list[float] = []

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self) -> bytes:
            return b'{"ok": true}'

    def fake_urlopen(request, timeout):  # noqa: ANN001
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise HTTPError(
                request.full_url,
                429,
                "Too Many Requests",
                {"Retry-After": "2"},
                BytesIO(b'{"error":{"code":"rate_limited"}}'),
            )
        return FakeResponse()

    monkeypatch.setattr(smoke, "urlopen", fake_urlopen)
    monkeypatch.setattr(smoke, "sleep", lambda seconds: sleeps.append(seconds))

    response = smoke.request_json(
        "GET",
        "https://example.test/health",
        timeout_seconds=1.0,
        rate_limit_retries=1,
        rate_limit_retry_delay_seconds=0.25,
    )

    assert response.status_code == 200
    assert response.payload == {"ok": True}
    assert attempts == 2
    assert sleeps == [2.0]


def test_public_beta_smoke_delays_between_samples_and_passes_retry_options(
    monkeypatch,
) -> None:
    samples = (
        TaiwanAdminArea(
            name="Sample County A",
            county="Sample County A",
            town=None,
            lat=23.5,
            lng=121.0,
            admin_code="90001",
            level="county",
            aliases=(),
        ),
        TaiwanAdminArea(
            name="Sample County B",
            county="Sample County B",
            town=None,
            lat=23.6,
            lng=121.1,
            admin_code="90002",
            level="county",
            aliases=(),
        ),
    )
    request_options: list[tuple[int, float]] = []
    sleeps: list[float] = []

    monkeypatch.setattr(
        smoke,
        "taiwan_wide_samples",
        lambda *, include_town_samples, all_towns: samples,
    )
    monkeypatch.setattr(smoke, "sleep", lambda seconds: sleeps.append(seconds))

    def fake_request_json(
        method: str,
        url: str,
        payload=None,
        *,
        timeout_seconds: float,
        rate_limit_retries: int,
        rate_limit_retry_delay_seconds: float,
    ) -> smoke.JsonResponse:
        request_options.append((rate_limit_retries, rate_limit_retry_delay_seconds))
        if url.endswith("/health"):
            return smoke.JsonResponse(status_code=200, payload={"status": "ok"})
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
            "--request-delay-seconds",
            "0.75",
            "--rate-limit-retries",
            "4",
            "--rate-limit-retry-delay-seconds",
            "1.5",
        ]
    )

    assert result == 0
    assert sleeps == [0.75]
    assert request_options == [(4, 1.5), (4, 1.5), (4, 1.5), (4, 1.5), (4, 1.5)]
