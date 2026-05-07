from __future__ import annotations

import gzip
import json
from pathlib import Path

from app.jobs.taiwan_news_query_plan import (
    DEFAULT_TAIWAN_FLOOD_NEWS_QUERIES,
    TAIWAN_COUNTY_TERMS,
    build_taiwan_flood_news_queries,
    load_taiwan_geocoder_query_places,
    load_taiwan_geocoder_terms,
)


def test_default_taiwan_flood_news_queries_cover_all_counties() -> None:
    joined = " ".join(DEFAULT_TAIWAN_FLOOD_NEWS_QUERIES)

    for county in TAIWAN_COUNTY_TERMS:
        assert f'"{county}"' in joined
    assert "sourcecountry:TW" in joined
    assert "地下道淹水" in joined


def test_build_taiwan_flood_news_queries_chunks_terms() -> None:
    queries = build_taiwan_flood_news_queries(
        ("台北市", "新北市", "桃園市", "高雄市", "高雄市"),
        terms_per_query=2,
    )

    assert len(queries) == 2
    assert '"台北市" OR "新北市"' in queries[0]
    assert '"桃園市" OR "高雄市"' in queries[1]


def test_load_taiwan_geocoder_terms_can_build_village_and_road_scopes(tmp_path: Path) -> None:
    path = tmp_path / "geocoder.jsonl.gz"
    rows = [
        {
            "name": "高雄市三民區本和里",
            "place_type": "admin_area",
            "precision": "admin_area",
            "metadata": {"raw": {"source": "nlsc-village-boundary-centroid"}},
        },
        {
            "name": "高雄市三民區大豐一路",
            "place_type": "address",
            "precision": "road_or_lane",
            "metadata": {"raw": {"source": "moi-national-road-names"}},
        },
    ]
    with gzip.open(path, "wt", encoding="utf-8") as output:
        for row in rows:
            output.write(json.dumps(row, ensure_ascii=False) + "\n")

    assert load_taiwan_geocoder_terms((path,), scopes=("village",)) == (
        "高雄市三民區本和里",
    )
    assert load_taiwan_geocoder_terms((path,), scopes=("road",)) == (
        "高雄市三民區大豐一路",
    )


def test_load_taiwan_geocoder_query_places_expands_aliases_with_coordinates(
    tmp_path: Path,
) -> None:
    path = tmp_path / "geocoder.jsonl.gz"
    rows = [
        {
            "name": "高雄市三民區本和里",
            "aliases": ["三民區本和里"],
            "normalized_aliases": ["高雄市三民區本和里", "本和里"],
            "lat": 22.65646,
            "lng": 120.32574,
            "place_type": "admin_area",
            "precision": "admin_area",
            "source_key": "moi-village-boundary-twd97-geographic",
            "source_record_id": "64000052012",
            "metadata": {"raw": {"source": "nlsc-village-boundary-centroid"}},
        },
        {
            "name": "高雄市三民區大豐一路",
            "lat": 22.65646,
            "lng": 120.32574,
            "place_type": "address",
            "precision": "road_or_lane",
            "source_key": "moi-national-road-names",
            "source_record_id": "高雄市三民區:大豐一路",
            "metadata": {"raw": {"site_id": "高雄市三民區", "road": "大豐一路"}},
        },
    ]
    with gzip.open(path, "wt", encoding="utf-8") as output:
        for row in rows:
            output.write(json.dumps(row, ensure_ascii=False) + "\n")

    places = load_taiwan_geocoder_query_places((path,), scopes=("village", "road"))
    terms = {place.term: place for place in places}

    assert terms["本和里"].scope == "village"
    assert terms["本和里"].lat == 22.65646
    assert terms["大豐一路"].scope == "road"
    assert terms["大豐一路"].canonical_name == "高雄市三民區大豐一路"
