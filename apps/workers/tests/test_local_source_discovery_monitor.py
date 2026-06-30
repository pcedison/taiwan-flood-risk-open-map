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


def test_discover_local_source_candidates_summarizes_release_monitor_state() -> None:
    payload = [
        {
            "title": "連江縣大潮、豪雨易淹水地區",
            "description": "易淹水地區靜態清冊",
            "identifier": "165820",
            "distribution": [{"format": "ODS"}],
        },
        {
            "title": "金門縣水位即時監測資料",
            "description": "金門水情系統即時水位 API",
            "identifier": "kinmen-live",
            "distribution": [{"format": "JSON"}],
        },
    ]

    result = discover_local_source_candidates(
        payload,
        target_counties=("連江縣", "金門縣", "花蓮縣"),
    )

    summary = result.to_dict()["summary"]

    assert summary["target_counties_without_candidates"] == ["花蓮縣"]
    assert summary["candidate_live_read_api_count_by_county"] == {"金門縣": 1}
    assert summary["metadata_only_count_by_county"] == {"連江縣": 1}
    assert summary["by_county"]["金門縣"]["readiness_state"] == "live_candidate_found"
    assert summary["by_county"]["連江縣"]["readiness_state"] == "metadata_only"
    assert summary["by_county"]["花蓮縣"]["readiness_state"] == "no_candidate"
    assert summary["by_county"]["金門縣"]["signal_types"] == ["water_level"]
    assert summary["by_county"]["連江縣"]["signal_types"] == ["flood_prone_area"]


def test_discover_local_source_candidates_filters_required_signal_types() -> None:
    payload = [
        {
            "title": "桃園市抽水站即時運轉資料",
            "description": "桃園市抽水站與水門即時狀態 API",
            "identifier": "taoyuan-pump-live",
            "distribution": [{"format": "JSON"}],
        },
        {
            "title": "桃園市水位站即時觀測",
            "description": "桃園市水位即時觀測 API",
            "identifier": "taoyuan-water-level-live",
            "distribution": [{"format": "JSON"}],
        },
    ]

    result = discover_local_source_candidates(
        payload,
        target_counties=("桃園市",),
        required_signal_types=("pump_or_gate_status",),
    )

    assert result.to_dict()["required_signal_types"] == ["pump_or_gate_status"]
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.dataset_id == "taoyuan-pump-live"
    assert candidate.signal_types == ("pump_or_gate_status",)
    assert result.to_dict()["summary"]["by_county"]["桃園市"]["signal_types"] == [
        "pump_or_gate_status"
    ]


def test_discover_pump_station_inventory_export_is_not_live_read_api() -> None:
    payload = [
        {
            "\u8cc7\u6599\u96c6\u8b58\u5225\u78bc": 125249,
            "\u8cc7\u6599\u96c6\u540d\u7a31": (
                "\u65b0\u5317\u5e02\u5404\u62bd\u6c34\u7ad9\u8cc7\u8a0a"
            ),
            "\u8cc7\u6599\u63d0\u4f9b\u5c6c\u6027": "\u6a94\u6848\u8cc7\u6599",
            "\u6a94\u6848\u683c\u5f0f": "CSV",
            "\u8cc7\u6599\u4e0b\u8f09\u7db2\u5740": (
                "https://data.ntpc.gov.tw/api/datasets/"
                "3cdc5b9c-ce48-4dd6-8079-b9b3fa4b7296/csv/file"
            ),
            "\u8cc7\u6599\u96c6\u63cf\u8ff0": (
                "\u62bd\u6c34\u7ad9\u6240\u5728\u7684\u4f4d\u7f6e\u662f"
                "\u96e8\u6c34\u4e0b\u6c34\u9053\u7684\u672b\u7aef\uff0c"
                "\u7576\u5927\u96e8\u6216\u6f32\u6f6e\u6642\uff0c"
                "\u5c0e\u81f4\u5824\u5916\u6c34\u4f4d\u9ad8\u65bc"
                "\u5824\u5167\u6c34\u4f4d\u5c31\u8981\u95dc\u9589"
                "\u91cd\u529b\u9598\u9580\u3002"
            ),
            "\u4e3b\u8981\u6b04\u4f4d\u8aaa\u660e": (
                "title(\u62bd\u6c34\u7ad9\u540d\u7a31);"
                "year(\u7ae3\u5de5\u5e74\u5ea6);"
                "address(\u5730\u5740);river(\u6cb3\u7cfb);"
                "pump_type(\u62bd\u6c34\u6a5f\u578b\u5f0f)"
            ),
            "\u63d0\u4f9b\u6a5f\u95dc": "\u65b0\u5317\u5e02\u653f\u5e9c\u6c34\u5229\u5c40",
            "\u66f4\u65b0\u983b\u7387": "\u6bcf1\u5e74",
        }
    ]

    result = discover_local_source_candidates(
        payload,
        target_counties=("\u65b0\u5317\u5e02",),
        required_signal_types=("pump_or_gate_status",),
    )

    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.dataset_id == "125249"
    assert candidate.readiness == "metadata_only"
    assert candidate.signal_types == ("sewer_water_level", "water_level", "pump_or_gate_status")
    assert candidate.resource_urls == (
        "https://data.ntpc.gov.tw/api/datasets/"
        "3cdc5b9c-ce48-4dd6-8079-b9b3fa4b7296/csv/file",
    )
    candidate_dict = candidate.to_dict()
    assert candidate_dict["update_frequency"] == "\u6bcf1\u5e74"
    assert "year(" in candidate_dict["field_description"]


def test_discover_taichung_sewer_gis_catalog_is_not_live_read_api() -> None:
    payload = [
        {
            "\u8cc7\u6599\u96c6\u8b58\u5225\u78bc": 120801,
            "\u8cc7\u6599\u96c6\u540d\u7a31": (
                "\u81fa\u4e2d\u5e02\u96e8\u6c34\u4e0b\u6c34\u9053"
                "\u4eba\u5b54\u5716"
            ),
            "\u8cc7\u6599\u63d0\u4f9b\u5c6c\u6027": "\u6a94\u6848\u8cc7\u6599",
            "\u6a94\u6848\u683c\u5f0f": "CSV",
            "\u8cc7\u6599\u4e0b\u8f09\u7db2\u5740": (
                "https://newdatacenter.taichung.gov.tw/api/v1/"
                "no-auth/resource.download?rid=741e190d-cbb5-4061-aa56-c29c33984614"
            ),
            "\u4e3b\u8981\u6b04\u4f4d\u8aaa\u660e": (
                "\u8cc7\u6599\u96c6\u540d\u7a31;"
                "\u8cc7\u6599\u683c\u5f0f;"
                "\u8cc7\u6599\u96c6\u8a9e\u7cfb;"
                "\u4e0b\u8f09\u7db2\u5740;"
                "\u4e0a\u67b6\u65e5\u671f;"
                "\u8cc7\u6599\u8cc7\u6e90\u6b04\u4f4d"
            ),
            "\u66f4\u65b0\u983b\u7387": "\u4e0d\u5b9a\u671f\u66f4\u65b0",
        }
    ]

    result = discover_local_source_candidates(
        payload,
        target_counties=("\u81fa\u4e2d\u5e02",),
        required_signal_types=("sewer_water_level",),
    )

    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.dataset_id == "120801"
    assert candidate.readiness == "metadata_only"
    assert candidate.signal_types == ("sewer_water_level",)


def test_discover_signal_candidates_ignores_non_sensor_infrastructure_lists() -> None:
    payload = [
        {
            "title": "\u65b0\u5317\u5e02\u6297\u65f1\u6c34\u4e95",
            "description": "\u542b\u62bd\u6c34\u91cf\u8207\u6c34\u4e95\u4f4d\u7f6e",
            "identifier": "drought-well",
            "distribution": [{"format": "CSV"}],
        },
        {
            "title": "\u65b0\u5317\u5e02\u62bd\u6c34\u7ad9\u53c3\u8a2a\u8cc7\u8a0a",
            "description": "\u62bd\u6c34\u7ad9\u806f\u7d61\u4eba\u8207\u96fb\u8a71",
            "identifier": "pump-visit",
            "distribution": [{"format": "CSV"}],
        },
        {
            "title": "\u6f8e\u6e56\u7e23\u6c61\u6c34\u4e0b\u6c34\u9053\u5df2\u5efa\u8a2d\u7ba1\u7dda\u9577\u5ea6\u53ca\u8a2d\u65bd",
            "description": "\u6c61\u6c34\u8655\u7406\u8a2d\u65bd\u8207\u62bd\u6c34\u7ad9\u6578\u91cf",
            "identifier": "sewer-statistics",
            "distribution": [{"format": "CSV;JSON;XML"}],
        },
        {
            "title": "\u65b0\u5317\u5e02\u6c34\u9580\u8cc7\u6599",
            "description": "\u6c34\u9580\u540d\u7a31\u3001\u62bd\u6c34\u7ad9\u540d\u7a31\u8207\u884c\u653f\u5340",
            "identifier": "water-gate-metadata",
            "distribution": [{"format": "CSV"}],
        },
    ]

    result = discover_local_source_candidates(
        payload,
        target_counties=("\u65b0\u5317\u5e02", "\u6f8e\u6e56\u7e23"),
        required_signal_types=("pump_or_gate_status",),
    )

    assert [candidate.dataset_id for candidate in result.candidates] == [
        "water-gate-metadata"
    ]


def test_discover_candidates_does_not_cross_match_city_and_county_names() -> None:
    payload = [
        {
            "title": "\u5609\u7fa9\u7e23\u8f44\u5167\u62bd\u6c34\u7ad9",
            "description": "\u5609\u7fa9\u7e23\u62bd\u6c34\u7ad9\u6e05\u518a",
            "identifier": "chiayi-county-pump",
            "distribution": [{"format": "CSV"}],
        },
        {
            "title": "\u65b0\u7af9\u5e02\u62bd\u6c34\u7ad9\u8cc7\u8a0a",
            "description": "\u65b0\u7af9\u5e02\u62bd\u6c34\u7ad9\u6e05\u518a",
            "identifier": "hsinchu-city-pump",
            "distribution": [{"format": "CSV"}],
        },
    ]

    result = discover_local_source_candidates(
        payload,
        target_counties=("\u5609\u7fa9\u5e02", "\u65b0\u7af9\u7e23"),
        required_signal_types=("pump_or_gate_status",),
    )

    assert result.candidates == ()


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
