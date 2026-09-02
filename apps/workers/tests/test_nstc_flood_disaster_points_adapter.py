from __future__ import annotations

from datetime import UTC, datetime
import ssl

import pytest

from app.adapters.nstc import (
    NSTC_FLOOD_DISASTER_POINTS_METADATA,
    NstcFloodDisasterPointsAdapter,
    NstcFloodDisasterPointsPayloadError,
    parse_nstc_flood_disaster_csv,
)
from app.config import load_worker_settings
from app.jobs.runtime import build_runtime_adapters
from app.adapters.nstc import flood_disaster_points as adapter_module


CSV = """FID,year,X_97,Y_97,source
1,2022,250000,2650000,EMIC
2,2021,300000,2600000,NCDR
"""


def test_parser_converts_twd97_points_and_preserves_year_only_semantics() -> None:
    rows = parse_nstc_flood_disaster_csv(CSV)

    assert len(rows) == 2
    assert rows[0]["source_id"] == "data-gov-130016:2022:EMIC:1"
    assert str(rows[0]["source_record_key"]).startswith("2022:")
    assert "source_timestamp" not in rows[0]
    geometry = rows[0]["geometry"]
    assert isinstance(geometry, dict)
    assert geometry["type"] == "Point"
    lng, lat = geometry["coordinates"]
    assert lng == pytest.approx(121.0, abs=0.01)
    assert lat == pytest.approx(23.95, abs=0.05)


def test_parser_rejects_wrong_schema_and_empty_valid_snapshot() -> None:
    with pytest.raises(NstcFloodDisasterPointsPayloadError, match="missing required"):
        parse_nstc_flood_disaster_csv("FID,year\n1,2022\n")
    with pytest.raises(NstcFloodDisasterPointsPayloadError, match="no valid"):
        parse_nstc_flood_disaster_csv(
            "FID,year,X_97,Y_97,source\n1,not-a-year,0,0,EMIC\n"
        )


def test_adapter_normalizes_official_historical_points() -> None:
    fetched_at = datetime(2026, 9, 1, tzinfo=UTC)
    adapter = NstcFloodDisasterPointsAdapter(
        fetched_at=fetched_at,
        fetch_text=lambda _url, _timeout: CSV,
    )

    result = adapter.run()

    assert result.adapter_key == "official.nstc.flood_disaster_points"
    assert len(result.fetched) == 2
    assert len(result.normalized) == 2
    assert result.rejected == ()
    assert result.normalized[0].source_timestamp is None
    assert result.fetched[0].payload["event_year"] == 2022
    assert result.fetched[0].payload["temporal_precision"] == "year"
    assert result.normalized[0].event_type.value == "flood_report"
    assert result.fetched[0].payload["evidence_scope"] == "historical"
    assert result.fetched[0].payload["location_precision"] == "point"
    assert result.fetched[0].payload["dataset_revision"]
    assert result.normalized[0].source_url == "https://data.gov.tw/dataset/130016"


def test_adapter_retains_revisions_instead_of_replacing_older_years() -> None:
    assert NSTC_FLOOD_DISASTER_POINTS_METADATA.snapshot_generation_mode is None


def test_backfill_can_pin_dataset_revision_to_the_exact_input_byte_digest() -> None:
    revision = "a" * 64
    result = NstcFloodDisasterPointsAdapter(
        fetched_at=datetime(2026, 9, 1, tzinfo=UTC),
        fetch_text=lambda _url, _timeout: CSV,
        dataset_revision_sha256=revision,
    ).run()

    assert {item.payload["dataset_revision"] for item in result.fetched} == {
        revision
    }


def test_backfill_rejects_an_invalid_dataset_revision_digest() -> None:
    with pytest.raises(ValueError, match="dataset_revision_sha256"):
        NstcFloodDisasterPointsAdapter(
            fetch_text=lambda _url, _timeout: CSV,
            dataset_revision_sha256="not-a-sha256",
        )


def test_partial_snapshot_preserves_every_invalid_source_row_as_rejected() -> None:
    adapter = NstcFloodDisasterPointsAdapter(
        fetched_at=datetime(2026, 9, 1, tzinfo=UTC),
        fetch_text=lambda _url, _timeout: """FID,year,X_97,Y_97,source
1,2022,250000,2650000,EMIC
2,not-a-year,250000,2650000,EMIC
3,2022,0,0,EMIC
1,2022,250000,2650000,EMIC
""",
    )

    result = adapter.run()

    assert len(result.fetched) == 4
    assert len(result.normalized) == 1
    assert len(result.rejected) == 3
    assert set(result.rejected) == {
        "data-gov-130016:rejected:row-3",
        "data-gov-130016:rejected:row-4",
        "data-gov-130016:rejected:row-5",
    }
    assert {rejection.reason_code for rejection in result.source_rejections} == {
        "nstc_duplicate_source_id",
        "nstc_invalid_required_value",
        "nstc_outside_taiwan_bounds",
    }


def test_runtime_requires_both_explicit_source_and_api_gates() -> None:
    key = NSTC_FLOOD_DISASTER_POINTS_METADATA.key
    base = {
        "WORKER_ENABLED_ADAPTER_KEYS": key,
        "SOURCE_NSTC_FLOOD_DISASTER_POINTS_ENABLED": "true",
    }

    assert key not in build_runtime_adapters(load_worker_settings(base))
    settings = load_worker_settings(
        {**base, "SOURCE_NSTC_FLOOD_DISASTER_POINTS_API_ENABLED": "true"}
    )
    adapters = build_runtime_adapters(
        settings,
        fetched_at=datetime(2026, 9, 1, tzinfo=UTC),
        nstc_flood_disaster_points_fetch_text=lambda _url, _timeout: CSV,
    )

    assert tuple(adapters) == (key,)
    assert len(adapters[key].run().normalized) == 2


def test_source_specific_legacy_cipher_context_keeps_peer_verification() -> None:
    context = adapter_module._nstc_ssl_context()

    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
