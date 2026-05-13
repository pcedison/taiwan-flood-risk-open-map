from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.domain.history.official_disaster_points import (
    DATA_GOV_URL,
    load_official_flood_disaster_records,
    lookup_official_flood_disaster_points,
    parse_official_flood_disaster_csv,
)


def test_parse_official_flood_disaster_csv_converts_twd97_points() -> None:
    records = parse_official_flood_disaster_csv(
        "\n".join(
            (
                "FID,year,X_97,Y_97,source",
                "0,2023,172956.00,2543478.00,EMIC",
            )
        )
    )

    assert len(records) == 1
    record = records[0]
    assert record.source_type == "official"
    assert record.event_type == "flood_report"
    assert record.url == DATA_GOV_URL
    assert record.title == "2023 官方淹水災害情資點位（EMIC #0）"
    assert abs(record.lat - 22.990947) < 0.00001
    assert abs(record.lng - 120.248506) < 0.00001
    assert "dataset 130016" in record.summary


def test_lookup_official_flood_disaster_points_uses_local_snapshot(tmp_path) -> None:
    csv_path = tmp_path / "flood_points.csv"
    csv_path.write_text(
        "\n".join(
            (
                "FID,year,X_97,Y_97,source",
                "0,2023,172956.00,2543478.00,EMIC",
                "1,2023,250000.00,2760000.00,EMIC",
            )
        ),
        encoding="utf-8",
    )

    lookup = lookup_official_flood_disaster_points(
        lat=22.990947,
        lng=120.248506,
        radius_m=300,
        csv_path=str(csv_path),
        enabled=True,
        now=datetime(2026, 5, 13, 0, 0, tzinfo=timezone.utc),
    )

    assert lookup.attempted is True
    assert lookup.health_status == "healthy"
    assert len(lookup.records) == 1
    assert lookup.records[0][0].source_id == "data-gov-130016:2023:EMIC:0"
    assert lookup.records[0][1] < 5
    assert "命中 1 筆" in lookup.message


def test_lookup_official_flood_disaster_points_explains_zero_hit_scope(tmp_path) -> None:
    csv_path = tmp_path / "flood_points.csv"
    csv_path.write_text(
        "\n".join(
            (
                "FID,year,X_97,Y_97,source",
                "0,2023,172956.00,2543478.00,EMIC",
            )
        ),
        encoding="utf-8",
    )

    lookup = lookup_official_flood_disaster_points(
        lat=25.04776,
        lng=121.51706,
        radius_m=300,
        csv_path=str(csv_path),
        enabled=True,
        now=datetime(2026, 5, 13, 0, 0, tzinfo=timezone.utc),
    )

    assert lookup.health_status == "healthy"
    assert lookup.records == ()
    assert "單一官方來源半徑內 0 筆命中" in lookup.message
    assert "不代表該地點沒有淹水紀錄" in lookup.message


def test_bundled_official_flood_disaster_points_cover_taiwan_wide_extent() -> None:
    csv_path = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "data"
        / "official"
        / "flood_disaster_points_130016.csv"
    )

    records = load_official_flood_disaster_records(str(csv_path))
    latitudes = [record.lat for record in records]
    longitudes = [record.lng for record in records]

    assert len(records) >= 5000
    assert min(latitudes) <= 22.1
    assert max(latitudes) >= 25.2
    assert min(longitudes) <= 120.2
    assert max(longitudes) >= 121.8
    assert sum(1 for record in records if record.lat >= 24.5) >= 100
    assert sum(1 for record in records if 23.5 <= record.lat < 24.5) >= 100
    assert sum(1 for record in records if record.lat < 23.5 and record.lng < 120.9) >= 100
    assert sum(1 for record in records if record.lng >= 120.9 and record.lat < 23.5) >= 10
