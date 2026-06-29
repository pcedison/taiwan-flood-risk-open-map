from __future__ import annotations

from app.ops.local_source_discovery_monitor import (
    DiscoveryResult,
    LocalSourceCandidate,
)
from app.ops.official_realtime_live_smoke import (
    OfficialRealtimeSmokeResult,
    SmokeSourceResult,
)
from app.ops.realtime_source_gate import evaluate_realtime_source_gate


def _coverage_summary() -> dict:
    return {
        "local_direct_complete_count": 20,
        "local_direct_incomplete_count": 2,
        "central_backbone_minimum_complete_count": 22,
        "central_backbone_minimum_incomplete_count": 0,
        "local_direct_incomplete_counties": ["金門縣", "連江縣"],
        "counties_missing_hydrologic_backbone": [],
    }


def test_realtime_source_gate_passes_with_healthy_backbone_and_no_live_candidates() -> None:
    result = evaluate_realtime_source_gate(
        coverage_summary=_coverage_summary(),
        smoke_result=OfficialRealtimeSmokeResult(
            results=(
                SmokeSourceResult("official.cwa.rainfall", "skipped"),
                SmokeSourceResult("official.wra.water_level", "healthy", fetched_count=1),
            )
        ),
        discovery_result=DiscoveryResult(
            target_counties=("金門縣", "連江縣"),
            candidates=(
                LocalSourceCandidate(
                    county="連江縣",
                    title="連江縣大潮、豪雨易淹水地區",
                    dataset_id="165820",
                    dataset_url="https://data.gov.tw/dataset/165820",
                    readiness="metadata_only",
                    signal_types=("flood_prone_area",),
                    matched_keywords=("易淹水",),
                    resource_formats=("ODS",),
                    resource_urls=(),
                ),
            ),
        ),
    )

    assert result.passed is True
    assert result.to_dict()["coverage"]["local_direct_remaining_count"] == 2
    assert result.to_dict()["discovery"]["candidate_live_read_api_count"] == 0
    assert result.to_dict()["discovery"]["summary"]["by_county"]["連江縣"][
        "readiness_state"
    ] == "metadata_only"
    assert result.to_dict()["discovery"]["summary"][
        "metadata_only_count_by_county"
    ] == {"連江縣": 1}


def test_realtime_source_gate_fails_on_failed_central_backbone_source() -> None:
    result = evaluate_realtime_source_gate(
        coverage_summary=_coverage_summary(),
        smoke_result=OfficialRealtimeSmokeResult(
            results=(SmokeSourceResult("official.wra.water_level", "failed"),)
        ),
        discovery_result=DiscoveryResult(target_counties=("金門縣",), candidates=()),
    )

    assert result.passed is False
    assert any("official.wra.water_level" in failure for failure in result.failures)


def test_realtime_source_gate_can_fail_when_new_live_candidates_are_found() -> None:
    result = evaluate_realtime_source_gate(
        coverage_summary=_coverage_summary(),
        smoke_result=OfficialRealtimeSmokeResult(
            results=(SmokeSourceResult("official.wra.water_level", "healthy"),)
        ),
        discovery_result=DiscoveryResult(
            target_counties=("金門縣",),
            candidates=(
                LocalSourceCandidate(
                    county="金門縣",
                    title="金門縣水位即時資料",
                    dataset_id="kinmen-live",
                    dataset_url="https://data.gov.tw/dataset/kinmen-live",
                    readiness="candidate_live_read_api",
                    signal_types=("water_level",),
                    matched_keywords=("即時", "水位"),
                    resource_formats=("JSON",),
                    resource_urls=("https://example.test/kinmen.json",),
                ),
            ),
        ),
        fail_on_live_candidate=True,
    )

    assert result.passed is False
    assert "candidate_live_read_api" in result.failures[0]
