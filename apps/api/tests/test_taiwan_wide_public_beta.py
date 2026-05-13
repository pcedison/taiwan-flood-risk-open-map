from collections.abc import Iterator
from datetime import datetime

from fastapi.testclient import TestClient
import pytest

from app.api.routes import public as public_routes
from app.core.config import get_settings
from app.domain.geocoding.providers import TaiwanAdminArea, load_taiwan_admin_areas
from app.domain.realtime import OfficialRealtimeBundle, OfficialRealtimeSourceStatus
from app.main import create_app


TAIWAN_BOUNDS = {
    "lat_min": 21.7,
    "lat_max": 26.5,
    "lng_min": 118.0,
    "lng_max": 122.5,
}


@pytest.fixture()
def no_network_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    get_settings.cache_clear()
    public_routes._cached_nominatim_candidates.cache_clear()
    public_routes._cached_wikimedia_candidates.cache_clear()
    public_routes._ASSESSMENT_EVIDENCE_CACHE.clear()
    public_routes._RISK_ASSESSMENT_RESPONSE_CACHE.clear()

    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("EVIDENCE_REPOSITORY_ENABLED", "false")
    monkeypatch.setenv("REALTIME_OFFICIAL_ENABLED", "false")
    monkeypatch.setenv("SOURCE_CWA_API_ENABLED", "false")
    monkeypatch.setenv("SOURCE_WRA_API_ENABLED", "false")
    monkeypatch.setenv("SOURCE_NEWS_ENABLED", "false")
    monkeypatch.setenv("SOURCE_TERMS_REVIEW_ACK", "false")
    monkeypatch.setenv("HISTORICAL_NEWS_ON_DEMAND_ENABLED", "false")
    monkeypatch.setenv("OFFICIAL_FLOOD_DISASTER_POINTS_ENABLED", "true")
    monkeypatch.setenv("GEOCODER_BUNDLED_OPEN_DATA_ENABLED", "false")
    monkeypatch.setenv("GEOCODER_POSTGIS_ENABLED", "false")
    get_settings.cache_clear()

    def external_geocoder_lookup(*_args: object) -> tuple[object, ...]:
        raise AssertionError("Taiwan admin smoke should not use external geocoding")

    monkeypatch.setattr(public_routes, "_cached_nominatim_candidates", external_geocoder_lookup)
    monkeypatch.setattr(public_routes, "_cached_wikimedia_candidates", external_geocoder_lookup)
    monkeypatch.setattr(
        public_routes,
        "fetch_official_realtime_bundle",
        lambda **_kwargs: _empty_realtime_bundle(),
    )
    monkeypatch.setattr(
        public_routes,
        "query_nearby_evidence",
        lambda **_kwargs: pytest.fail("DB evidence should stay disabled in Taiwan smoke"),
    )
    monkeypatch.setattr(
        public_routes,
        "persist_risk_assessment",
        lambda **_kwargs: pytest.fail("risk persistence should stay disabled in Taiwan smoke"),
    )
    monkeypatch.setattr(
        public_routes,
        "fetch_query_heat_snapshot",
        lambda **_kwargs: pytest.fail("query heat DB should stay disabled in Taiwan smoke"),
    )
    monkeypatch.setattr(public_routes, "nearest_public_news_location_text", lambda **_kwargs: None)

    try:
        yield TestClient(create_app())
    finally:
        get_settings.cache_clear()
        public_routes._ASSESSMENT_EVIDENCE_CACHE.clear()
        public_routes._RISK_ASSESSMENT_RESPONSE_CACHE.clear()


def test_taiwan_wide_admin_samples_are_complete() -> None:
    samples = _county_and_one_town_per_county_samples()
    counties = [area for area in samples if area.level == "county"]
    towns = [area for area in samples if area.level == "town"]

    assert len(counties) == 22
    assert len(towns) == 22
    assert {town.county for town in towns} == {county.name for county in counties}


def test_public_api_geocodes_and_assesses_all_taiwan_admin_samples(
    no_network_client: TestClient,
) -> None:
    failures: list[str] = []

    for sample in _county_and_one_town_per_county_samples():
        geocode_response = no_network_client.post(
            "/v1/geocode",
            json={"query": sample.name, "input_type": "address", "limit": 1},
        )
        if geocode_response.status_code != 200:
            failures.append(f"{sample.name} geocode HTTP {geocode_response.status_code}")
            continue
        candidates = geocode_response.json()["candidates"]
        if not candidates:
            failures.append(f"{sample.name} geocode returned no candidates")
            continue
        candidate = candidates[0]
        point = candidate["point"]
        if candidate["source"] != "local-taiwan-admin-centroid":
            failures.append(f"{sample.name} geocode source={candidate['source']}")
        if candidate["precision"] != "admin_area":
            failures.append(f"{sample.name} geocode precision={candidate['precision']}")
        if candidate["requires_confirmation"] is not True:
            failures.append(f"{sample.name} should require confirmation")
        if not _within_taiwan(point):
            failures.append(f"{sample.name} point outside Taiwan bounds: {point}")

        risk_response = no_network_client.post(
            "/v1/risk/assess",
            json={
                "point": point,
                "radius_m": 500,
                "time_context": "now",
                "location_text": sample.name,
            },
        )
        if risk_response.status_code != 200:
            failures.append(f"{sample.name} risk HTTP {risk_response.status_code}")
            continue
        payload = risk_response.json()
        for field in ("assessment_id", "realtime", "historical", "confidence", "explanation"):
            if field not in payload:
                failures.append(f"{sample.name} risk missing {field}")
        if not payload.get("explanation", {}).get("summary"):
            failures.append(f"{sample.name} risk missing explanation summary")
        if not isinstance(payload.get("data_freshness"), list):
            failures.append(f"{sample.name} risk data_freshness should be a list")
        else:
            official_history = [
                item
                for item in payload["data_freshness"]
                if item.get("source_id") == "official-flood-disaster-points"
            ]
            if len(official_history) != 1:
                failures.append(f"{sample.name} missing official flood disaster source status")
            elif official_history[0].get("health_status") not in {"healthy", "degraded"}:
                failures.append(
                    f"{sample.name} official flood disaster source status="
                    f"{official_history[0].get('health_status')}"
                )
            elif "快照" not in str(official_history[0].get("name")):
                failures.append(f"{sample.name} official flood disaster source should be labeled as a snapshot")
        if not isinstance(payload.get("evidence"), list):
            failures.append(f"{sample.name} risk evidence should be a list")

    assert failures == []


def _county_and_one_town_per_county_samples() -> tuple[TaiwanAdminArea, ...]:
    areas = load_taiwan_admin_areas()
    counties = sorted((area for area in areas if area.level == "county"), key=lambda item: item.name)
    towns = sorted((area for area in areas if area.level == "town"), key=lambda item: (item.county, item.name))
    first_town_by_county: dict[str, TaiwanAdminArea] = {}
    for town in towns:
        first_town_by_county.setdefault(town.county, town)
    return (*counties, *(first_town_by_county[county.name] for county in counties))


def _within_taiwan(point: dict[str, float]) -> bool:
    return (
        TAIWAN_BOUNDS["lat_min"] <= float(point["lat"]) <= TAIWAN_BOUNDS["lat_max"]
        and TAIWAN_BOUNDS["lng_min"] <= float(point["lng"]) <= TAIWAN_BOUNDS["lng_max"]
    )


def _empty_realtime_bundle() -> OfficialRealtimeBundle:
    observed_at = datetime.fromisoformat("2026-04-29T03:00:00+00:00")
    return OfficialRealtimeBundle(
        observations=(),
        source_statuses=(
            OfficialRealtimeSourceStatus(
                source_id="cwa-rainfall",
                name="CWA rainfall",
                health_status="healthy",
                observed_at=observed_at,
                ingested_at=observed_at,
                message="disabled in no-network Taiwan-wide smoke",
            ),
            OfficialRealtimeSourceStatus(
                source_id="wra-water-level",
                name="WRA water level",
                health_status="healthy",
                observed_at=observed_at,
                ingested_at=observed_at,
                message="disabled in no-network Taiwan-wide smoke",
            ),
        ),
    )
