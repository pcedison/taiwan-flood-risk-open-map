from pathlib import Path

from app.api.schemas import GeocodeRequest
from app.domain.geocoding import build_open_data_geocoder
from app.domain.geocoding.normalization import (
    compact_taiwan_query_key,
    normalized_aliases,
    taiwan_address_aliases,
)


def test_compact_taiwan_query_key_normalizes_common_address_variants() -> None:
    assert compact_taiwan_query_key("臺南市 安南區 長溪路二段４１０巷１６弄１號") == (
        "台南市安南區長溪路二段410巷16弄1號"
    )


def test_taiwan_address_aliases_include_tai_and_section_variants() -> None:
    aliases = taiwan_address_aliases("臺南市安南區長溪路二段410巷16弄1號")

    assert "台南市安南區長溪路二段410巷16弄1號" in aliases
    assert "臺南市安南區長溪路2段410巷16弄1號" in aliases
    assert "台南市安南區長溪路2段410巷16弄1號" in aliases
    assert "台南市安南區長溪路2段410巷16弄1號" in normalized_aliases(*aliases)


def test_file_backed_geocoder_matches_fullwidth_tai_and_section_variants(tmp_path: Path) -> None:
    source_path = tmp_path / "tainan-addresses.csv"
    source_path.write_text(
        "\n".join(
            [
                "name,aliases,lat,lng,admin_code,precision,type,source",
                "臺南市安南區長溪路二段４１０巷１６弄１號,,23.05753,120.20144,67000000,exact_address,address,local-open-data-test",
            ]
        ),
        encoding="utf-8",
    )

    geocoder = build_open_data_geocoder(
        nominatim_lookup=lambda *_args: (),
        wikimedia_lookup=lambda *_args: (),
        open_data_paths=(str(source_path),),
    )

    candidates = geocoder.geocode(
        GeocodeRequest(query="台南市安南區長溪路2段410巷16弄1號", input_type="address", limit=1),
    )

    assert candidates[0].source == "local-open-data-test"
    assert candidates[0].precision == "exact_address"
    assert candidates[0].requires_confirmation is False
