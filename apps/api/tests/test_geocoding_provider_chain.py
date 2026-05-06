from pathlib import Path

from app.api.schemas import GeocodeRequest, LatLng, PlaceCandidate
from app.domain.geocoding import build_open_data_geocoder
from app.domain.geocoding.providers import load_taiwan_admin_areas, strip_admin_suffix


def test_provider_chain_uses_local_taiwan_provider_before_external_lookup() -> None:
    calls: list[str] = []

    def nominatim_lookup(query: str, *_args: object) -> tuple[PlaceCandidate, ...]:
        calls.append(query)
        return ()

    geocoder = build_open_data_geocoder(
        nominatim_lookup=nominatim_lookup,
        wikimedia_lookup=lambda *_args: (),
    )

    candidates = geocoder.geocode(
        GeocodeRequest(query="台北101", input_type="landmark", limit=1),
    )

    assert calls == []
    assert candidates[0].source == "local-taiwan-gazetteer"
    assert candidates[0].precision == "poi"


def test_provider_chain_uses_file_backed_open_data_before_bundled_fixtures(
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    source_path = tmp_path / "taiwan-addresses.csv"
    source_path.write_text(
        "\n".join(
            [
                "name,aliases,lat,lng,admin_code,precision,type,source",
                "新北市板橋區文化路一段1號,文化路一段1號|板橋文化路一段1號,25.01234,121.46567,65000000,exact_address,address,local-open-data-test",
                "新北市板橋區文化路一段,文化路一段,25.012,121.466,65000000,road_or_lane,address,local-open-data-test",
            ]
        ),
        encoding="utf-8",
    )

    def nominatim_lookup(query: str, *_args: object) -> tuple[PlaceCandidate, ...]:
        calls.append(query)
        return ()

    geocoder = build_open_data_geocoder(
        nominatim_lookup=nominatim_lookup,
        wikimedia_lookup=lambda *_args: (),
        open_data_paths=(str(source_path),),
    )

    candidates = geocoder.geocode(
        GeocodeRequest(query="新北市板橋區文化路一段1號", input_type="address", limit=1),
    )

    assert calls == []
    assert candidates[0].name == "新北市板橋區文化路一段1號"
    assert candidates[0].source == "local-open-data-test"
    assert candidates[0].precision == "exact_address"
    assert candidates[0].requires_confirmation is False


def test_provider_chain_prefers_project_controlled_osm_before_public_nominatim() -> None:
    public_nominatim_calls: list[str] = []

    def project_osm_lookup(query: str, *_args: object) -> tuple[PlaceCandidate, ...]:
        assert query == "斗六車站"
        return (
            PlaceCandidate(
                place_id="project-osm-place",
                name="斗六車站",
                type="landmark",
                point=LatLng(lat=23.71148, lng=120.54175),
                admin_code=None,
                source="openstreetmap-project-controlled",
                confidence=0.91,
                precision="poi",
            ),
        )

    def public_nominatim_lookup(query: str, *_args: object) -> tuple[PlaceCandidate, ...]:
        public_nominatim_calls.append(query)
        return ()

    geocoder = build_open_data_geocoder(
        project_osm_lookup=project_osm_lookup,
        nominatim_lookup=public_nominatim_lookup,
        wikimedia_lookup=lambda *_args: (),
    )

    candidates = geocoder.geocode(
        GeocodeRequest(query="斗六車站", input_type="landmark", limit=1),
    )

    assert public_nominatim_calls == []
    assert candidates[0].source == "openstreetmap-project-controlled"
    assert candidates[0].matched_query == "斗六車站"


def test_provider_chain_caps_house_number_to_lane_fallback_precision() -> None:
    queries: list[str] = []

    def nominatim_lookup(query: str, *_args: object) -> tuple[PlaceCandidate, ...]:
        queries.append(query)
        if query == "培安路305巷":
            return (
                PlaceCandidate(
                    place_id="lane-place",
                    name="培安路305巷",
                    type="address",
                    point=LatLng(lat=23.038818, lng=120.213493),
                    admin_code=None,
                    source="openstreetmap-nominatim",
                    confidence=0.9,
                    precision="unknown",
                ),
            )
        return ()

    geocoder = build_open_data_geocoder(
        nominatim_lookup=nominatim_lookup,
        wikimedia_lookup=lambda *_args: (),
    )

    candidates = geocoder.geocode(
        GeocodeRequest(query="培安路305巷5號", input_type="address", limit=1),
    )

    assert "培安路305巷" in queries
    assert candidates[0].name == "培安路305巷（由門牌定位到巷道）"
    assert candidates[0].source == "openstreetmap-nominatim-address-fallback"
    assert candidates[0].confidence == 0.78
    assert candidates[0].precision == "road_or_lane"
    assert candidates[0].requires_confirmation is False


def test_provider_chain_falls_back_to_taiwan_admin_centroid_for_unknown_address() -> None:
    nominatim_calls: list[str] = []
    wikimedia_calls: list[str] = []

    def nominatim_lookup(query: str, *_args: object) -> tuple[PlaceCandidate, ...]:
        nominatim_calls.append(query)
        return ()

    def wikimedia_lookup(query: str, *_args: object) -> tuple[PlaceCandidate, ...]:
        wikimedia_calls.append(query)
        return ()

    geocoder = build_open_data_geocoder(
        nominatim_lookup=nominatim_lookup,
        wikimedia_lookup=wikimedia_lookup,
    )

    candidates = geocoder.geocode(
        GeocodeRequest(query="高雄市苓雅區四維三路2號", input_type="address", limit=1),
    )

    assert nominatim_calls
    assert wikimedia_calls == []
    assert candidates[0].source == "taiwan-admin-centroid-fallback"
    assert candidates[0].name == "高雄市苓雅區（由地址退回行政區代表點）"
    assert candidates[0].precision == "admin_area"
    assert candidates[0].matched_query == "高雄市苓雅區"
    assert candidates[0].requires_confirmation is True
    assert candidates[0].confidence >= 0.65
    assert "退回行政區代表點" in " ".join(candidates[0].limitations)


def test_provider_chain_does_not_guess_ambiguous_town_name_without_county() -> None:
    geocoder = build_open_data_geocoder(
        nominatim_lookup=lambda *_args: (),
        wikimedia_lookup=lambda *_args: (),
    )

    candidates = geocoder.geocode(
        GeocodeRequest(query="中正區", input_type="address", limit=1),
    )

    assert candidates == []


def test_provider_chain_covers_every_taiwan_admin_area_locally_before_external_lookup() -> None:
    def external_lookup(query: str, *_args: object) -> tuple[PlaceCandidate, ...]:
        raise AssertionError(f"local admin query should not reach external lookup: {query}")

    geocoder = build_open_data_geocoder(
        nominatim_lookup=external_lookup,
        wikimedia_lookup=external_lookup,
    )
    areas = load_taiwan_admin_areas()
    counties = [area for area in areas if area.level == "county"]
    towns = [area for area in areas if area.level == "town"]

    assert len(counties) >= 20
    assert len(towns) >= 300

    failures: list[str] = []
    for area in areas:
        query = _spoken_admin_query(area.county, area.town)
        candidates = geocoder.geocode(
            GeocodeRequest(query=query, input_type="address", limit=1),
        )
        if not candidates:
            failures.append(f"{query} -> no candidate")
            continue
        candidate = candidates[0]
        if (
            candidate.name != area.name
            or candidate.source != "local-taiwan-admin-centroid"
            or candidate.precision != "admin_area"
            or candidate.type != "admin_area"
        ):
            failures.append(
                f"{query} -> name={candidate.name}, source={candidate.source}, "
                f"precision={candidate.precision}, type={candidate.type}"
            )

    assert failures == []


def test_provider_chain_uses_wikimedia_only_after_osm_misses() -> None:
    nominatim_calls: list[str] = []
    wikimedia_calls: list[str] = []

    def nominatim_lookup(query: str, *_args: object) -> tuple[PlaceCandidate, ...]:
        nominatim_calls.append(query)
        return ()

    def wikimedia_lookup(query: str, *_args: object) -> tuple[PlaceCandidate, ...]:
        wikimedia_calls.append(query)
        return (
            PlaceCandidate(
                place_id="wiki-place",
                name="知名景點",
                type="landmark",
                point=LatLng(lat=23.1, lng=120.2),
                admin_code=None,
                source="wikimedia-coordinates",
                confidence=0.84,
                precision="poi",
                matched_query=query,
                limitations=["定位結果是地標座標，不代表門牌精準位置。"],
            ),
        )

    geocoder = build_open_data_geocoder(
        nominatim_lookup=nominatim_lookup,
        wikimedia_lookup=wikimedia_lookup,
    )

    candidates = geocoder.geocode(
        GeocodeRequest(query="不在本地清單的知名景點", input_type="address", limit=1),
    )

    assert nominatim_calls
    assert wikimedia_calls == ["不在本地清單的知名景點"]
    assert candidates[0].source == "wikimedia-coordinates"


def _spoken_admin_query(county: str, town: str | None) -> str:
    if town is None:
        return county
    town_short = strip_admin_suffix(town)
    return f"{strip_admin_suffix(county)} {town_short if len(town_short) >= 2 else town}"
