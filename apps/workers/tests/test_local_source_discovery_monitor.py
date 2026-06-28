from __future__ import annotations

from app.ops.local_source_discovery_monitor import (
    DEFAULT_TARGET_COUNTIES,
    DataGovDataset,
    discover_local_source_candidates,
)


def test_discover_local_source_candidates_flags_live_read_candidates() -> None:
    payload = [
        {
            "title": "金門縣智慧水位即時監測資料",
            "description": "金門水情系統即時水位 API",
            "identifier": "kinmen-live-water-level",
            "url": "https://data.gov.tw/dataset/kinmen-live-water-level",
            "distribution": [
                {
                    "format": "JSON",
                    "downloadURL": "https://example.test/kinmen/water-level.json",
                }
            ],
        },
        {
            "title": "金門縣觀光景點",
            "description": "旅遊資料",
            "identifier": "kinmen-tourism",
            "distribution": [{"format": "JSON"}],
        },
    ]

    result = discover_local_source_candidates(payload)

    assert result.target_counties == DEFAULT_TARGET_COUNTIES
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.county == "金門縣"
    assert candidate.dataset_id == "kinmen-live-water-level"
    assert candidate.readiness == "candidate_live_read_api"
    assert "water_level" in candidate.signal_types
    assert "JSON" in candidate.resource_formats
    assert candidate.resource_urls == ("https://example.test/kinmen/water-level.json",)


def test_discover_local_source_candidates_keeps_static_metadata_visible() -> None:
    payload = [
        {
            "title": "連江縣大潮、豪雨易淹水地區",
            "description": "易淹水地區靜態清冊",
            "identifier": "165820",
            "url": "https://data.gov.tw/dataset/165820",
            "distribution": [{"format": "ODS", "downloadURL": "https://example.test/flood.ods"}],
        }
    ]

    result = discover_local_source_candidates(payload)

    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.county == "連江縣"
    assert candidate.readiness == "metadata_only"
    assert candidate.signal_types == ("flood_prone_area",)
    assert candidate.resource_formats == ("ODS",)


def test_data_gov_dataset_parser_accepts_common_export_aliases() -> None:
    item = DataGovDataset.from_mapping(
        {
            "資料集名稱": "連江縣雨水下水道水位即時資料",
            "資料集描述": "含水位站觀測時間",
            "資料集識別碼": "lienchiang-sewer",
            "資料集網址": "https://data.gov.tw/dataset/lienchiang-sewer",
            "檔案格式": "CSV",
            "下載網址": "https://example.test/lienchiang/sewer.csv",
        }
    )

    assert item.title == "連江縣雨水下水道水位即時資料"
    assert item.identifier == "lienchiang-sewer"
    assert item.resource_formats == ("CSV",)
    assert item.resource_urls == ("https://example.test/lienchiang/sewer.csv",)


def test_discover_local_source_candidates_ignores_drought_and_subsidy_datasets() -> None:
    payload = [
        {
            "title": "枯旱預警",
            "description": "供水情勢包含金門縣及連江縣地區",
            "identifier": "36695",
            "distribution": [{"format": "CSV;JSON;XML"}],
        },
        {
            "title": "水利署補助款蓄水建造物更新及改善計畫",
            "description": "金門縣閘門改善計畫",
            "identifier": "132064",
            "distribution": [{"format": "CSV;JSON;XML"}],
        },
    ]

    result = discover_local_source_candidates(payload)

    assert result.candidates == ()
