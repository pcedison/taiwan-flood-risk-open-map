import gzip
import json

from app.domain.geocoding.postgis_bootstrap import import_row_from_payload, iter_import_rows


def test_import_row_from_payload_preserves_source_metadata() -> None:
    row = import_row_from_payload(
        {
            "source_key": "moi-national-road-names",
            "source_record_id": "taipei:road",
            "name": "Taipei Test Road",
            "aliases": ["Taipei Test Road"],
            "normalized_aliases": ["taipeitestroad"],
            "lat": 25.0,
            "lng": 121.5,
            "precision": "road_or_lane",
            "place_type": "address",
            "confidence": 0.63,
            "limitations": ["road geometry is not provided"],
            "metadata": {"coordinate_policy": "admin_centroid"},
        },
        jsonb=lambda value: value,
    )

    assert row is not None
    assert row["source_key"] == "moi-national-road-names"
    assert row["source_record_id"] == "taipei:road"
    assert row["precision"] == "road_or_lane"
    assert row["place_type"] == "address"
    assert row["metadata"]["limitations"] == ["road geometry is not provided"]


def test_iter_import_rows_reads_gzipped_jsonl(tmp_path) -> None:
    path = tmp_path / "geocoder.jsonl.gz"
    payload = {
        "source_key": "nfa-evacuation-shelter-locations",
        "source_record_id": "1",
        "name": "Shelter",
        "aliases": ["Shelter"],
        "normalized_aliases": ["shelter"],
        "lat": 24.386,
        "lng": 121.073,
        "precision": "poi",
        "place_type": "poi",
    }
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(json.dumps(payload))
        handle.write("\n")

    rows = iter_import_rows(path, jsonb=lambda value: value)

    assert len(rows) == 1
    assert rows[0]["source_key"] == "nfa-evacuation-shelter-locations"
    assert rows[0]["normalized_aliases"] == ["shelter"]
