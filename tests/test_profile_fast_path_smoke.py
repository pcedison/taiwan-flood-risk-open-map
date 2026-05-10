from __future__ import annotations

from datetime import datetime, timezone
import json
from types import SimpleNamespace

from infra.scripts import profile_fast_path_smoke


def test_profile_fast_path_smoke_reports_matching_profile(monkeypatch, capsys) -> None:
    computed_at = datetime(2026, 5, 8, 3, 0, tzinfo=timezone.utc)

    monkeypatch.setenv("DATABASE_URL", "postgresql://example.test/flood")
    monkeypatch.setattr(
        profile_fast_path_smoke,
        "fetch_best_profile_for_point",
        lambda **_kwargs: SimpleNamespace(
            profile_kind="risk_grid",
            profile_key="h3:842ab57ffffffff",
            profile_scope="h3:8",
            profile_radius_m=1000,
            score_version="risk-v0.1.0",
            realtime_level="unknown",
            historical_level="high",
            confidence_level="medium",
            computed_at=computed_at,
            expires_at=None,
            distance_to_query_m=18.4,
            missing_sources=("rainfall",),
            coverage_gaps=("historical_news_backfill_partial",),
        ),
    )

    exit_code = profile_fast_path_smoke.main(
        ["--lat", "22.65646", "--lng", "120.32574", "--radius-m", "500"]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "passed"
    assert payload["profile"]["profile_key"] == "h3:842ab57ffffffff"
    assert payload["profile"]["historical_level"] == "high"


def test_profile_fast_path_smoke_can_allow_missing_profiles(monkeypatch, capsys) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.test/flood")
    monkeypatch.setattr(profile_fast_path_smoke, "fetch_best_profile_for_point", lambda **_kwargs: None)

    exit_code = profile_fast_path_smoke.main(
        ["--lat", "22.65646", "--lng", "120.32574", "--allow-missing"]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "missing"
    assert payload["reason"] == "no_matching_fresh_profile"
