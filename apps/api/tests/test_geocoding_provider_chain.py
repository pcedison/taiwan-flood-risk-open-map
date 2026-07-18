import gzip
from pathlib import Path

from app.api.schemas import GeocodeRequest, LatLng, PlaceCandidate
from app.domain.geocoding import build_open_data_geocoder
from app.domain.geocoding.providers import (
    load_taiwan_admin_areas,
    postgis_query_aliases,
    strip_admin_suffix,
)


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


def test_provider_chain_preserves_file_backed_low_confidence_limitations(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "taiwan-roads.jsonl"
    source_path.write_text(
        "\n".join(
            [
                (
                    '{"name":"台北市大安區信義路三段","aliases":["台北市大安區信義路三段"],'
                    '"lat":25.026,"lng":121.543,"precision":"road_or_lane","type":"address",'
                    '"source":"local-open-data-road","confidence":0.63,'
                    '"limitations":["道路名稱資料未提供道路線形。"]}'
                )
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
        GeocodeRequest(query="台北市大安區信義路三段100號", input_type="address", limit=1),
    )

    assert candidates[0].source == "local-open-data-road"
    assert candidates[0].confidence == 0.63
    assert candidates[0].requires_confirmation is True
    assert "道路名稱資料未提供道路線形。" in candidates[0].limitations


def test_provider_chain_continues_past_low_confidence_road_centroid(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "taiwan-roads.jsonl"
    source_path.write_text(
        (
            '{"name":"臺南市安南區培安路","aliases":["臺南市安南區培安路"],'
            '"lat":23.04405,"lng":120.154766,"precision":"road_or_lane",'
            '"type":"address","source":"local-open-data-road","confidence":0.63,'
            '"limitations":["道路名稱資料未提供道路線形或門牌座標。"]}'
        ),
        encoding="utf-8",
    )
    nominatim_queries: list[str] = []

    def nominatim_lookup(query: str, *_args: object) -> tuple[PlaceCandidate, ...]:
        nominatim_queries.append(query)
        if query == "培安路":
            return (
                PlaceCandidate(
                    place_id="osm-peian-road",
                    name="培安路",
                    type="address",
                    point=LatLng(lat=23.0447736, lng=120.2115377),
                    admin_code=None,
                    source="openstreetmap-nominatim",
                    confidence=0.9,
                    precision="road_or_lane",
                ),
            )
        return ()

    geocoder = build_open_data_geocoder(
        nominatim_lookup=nominatim_lookup,
        wikimedia_lookup=lambda *_args: (),
        open_data_paths=(str(source_path),),
    )

    candidates = geocoder.geocode(
        GeocodeRequest(query="台南市安南區培安路", input_type="address", limit=1),
    )

    assert "培安路" in nominatim_queries
    assert candidates[0].name == "培安路（由查詢文字萃取地名）"
    assert candidates[0].source == "openstreetmap-nominatim-taiwan-normalized"
    assert candidates[0].matched_query == "培安路"
    assert candidates[0].point == LatLng(lat=23.0447736, lng=120.2115377)
    assert candidates[0].confidence == 0.82
    assert candidates[0].requires_confirmation is False


def test_provider_chain_reads_gzipped_file_backed_open_data(tmp_path: Path) -> None:
    source_path = tmp_path / "taiwan-roads.jsonl.gz"
    with gzip.open(source_path, "wt", encoding="utf-8") as handle:
        handle.write(
            '{"name":"Taipei Daan Xinyi Road Section 3",'
            '"aliases":["taipei daan xinyi road section 3"],'
            '"lat":25.026,"lng":121.543,"precision":"road_or_lane","type":"address",'
            '"source":"local-open-data-road","confidence":0.63}'
        )

    geocoder = build_open_data_geocoder(
        nominatim_lookup=lambda *_args: (),
        wikimedia_lookup=lambda *_args: (),
        open_data_paths=(str(source_path),),
    )

    candidates = geocoder.geocode(
        GeocodeRequest(query="taipei daan xinyi road section 3", input_type="address", limit=1),
    )

    assert candidates[0].source == "local-open-data-road"
    assert candidates[0].precision == "road_or_lane"
    assert candidates[0].requires_confirmation is True


def test_postgis_query_aliases_include_road_level_fallback() -> None:
    aliases = postgis_query_aliases("台北市大安區信義路三段100號")

    assert "台北市大安區信義路3段100號" in aliases
    assert "台北市大安區信義路3段" in aliases


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

    county_names = {area.name for area in counties}
    assert len(counties) == 22
    assert len(towns) >= 370
    assert {"金門縣", "連江縣", "桃園市"} <= county_names
    assert "桃園縣" not in county_names

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


def test_query_substring_aliases_cover_every_embedded_alias() -> None:
    from app.domain.geocoding.providers import query_substring_aliases

    substrings = query_substring_aliases("台北市信義區市府路45號")

    # Any stored alias of length >= 4 embedded in the query must be present.
    assert "信義區市府" in substrings
    assert "市府路45號" in substrings
    assert "台北市信義區市府路45號" in substrings
    # The old clause's minimum length is preserved: nothing shorter than 4.
    assert all(len(alias) >= 4 for alias in substrings)
    # Deduplicated.
    assert len(substrings) == len(set(substrings))


def test_query_substring_aliases_short_query_returns_empty() -> None:
    from app.domain.geocoding.providers import query_substring_aliases

    assert query_substring_aliases("北投") == ()


def test_query_substring_aliases_preserve_late_match_in_long_query() -> None:
    from app.domain.geocoding.providers import query_substring_aliases

    # A stored alias appearing only past character 64 must still be covered;
    # a fixed truncation would have dropped it.
    aliases = query_substring_aliases(("台" * 80) + "信義區市府路")
    assert "信義區市府路" in aliases


def test_query_substring_aliases_bounded_for_pathological_query() -> None:
    from app.domain.geocoding.providers import query_substring_aliases

    # A very long query drops the expansion rather than exploding the array;
    # the direct alias branch still applies at the call site.
    huge = "".join(chr(0x4E00 + (i % 5000)) for i in range(600))
    assert query_substring_aliases(huge) == ()


def test_fetch_postgis_open_data_candidates_uses_single_sargable_predicate(
    monkeypatch,
) -> None:
    from app.domain.geocoding.providers import fetch_postgis_open_data_candidates

    executed: list[tuple[str, dict]] = []

    class _Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def execute(self, sql, params):
            executed.append((sql, params))

        def fetchall(self):
            return []

    class _Connection:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def cursor(self):
            return _Cursor()

    import app.core.db as db_module

    monkeypatch.setattr(db_module, "pooled_connection", lambda _url: _Connection())

    result = fetch_postgis_open_data_candidates(
        "postgresql://example.test/flood",
        GeocodeRequest(query="台北市信義區市府路45號", input_type="address", limit=5),
        query_aliases=("台北市信義區市府路45號",),
    )

    assert result == ()
    sql, params = executed[0]
    # The non-sargable fallback is gone; one GIN-servable overlap remains.
    assert "position(" not in sql
    assert "unnest(" not in sql
    assert "normalized_aliases && %(match_aliases)s::text[]" in sql
    assert "信義區市府" in params["match_aliases"]
    assert "台北市信義區市府路45號" in params["match_aliases"]
