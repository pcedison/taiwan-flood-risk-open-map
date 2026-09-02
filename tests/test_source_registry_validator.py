from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from infra.scripts import validate_source_registry as validator


class FakeResult:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[tuple[object, ...]]:
        return self._rows


class FakeConnection:
    def __init__(self, rows: list[tuple[str, bool]]) -> None:
        self._rows = rows
        self._readiness_rows = [
            (adapter_key,)
            for adapter_key, _enabled in rows
            if adapter_key
            in {
                "official.cwa.rainfall",
                "official.cwa.tide_level",
                "official.wra.water_level",
                "official.wra_iow.flood_depth",
                "official.wra.historical_flood",
                "official.nstc.flood_disaster_points",
                "official.ncdr.cap",
                "official.civil_iot.sewer_water_level",
                "local.tainan.flood_sensor",
            }
        ]

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, query: str) -> FakeResult:
        if "SELECT adapter_key, is_enabled FROM data_sources" in query:
            return FakeResult(self._rows)
        assert "FROM ingestion_readiness_sources" in query
        return FakeResult(self._readiness_rows)


def _registry() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    contracts, sources = validator.load_source_registry()
    return dict(contracts), deepcopy(sources)


def test_checked_in_registry_covers_every_source_surface() -> None:
    contracts, sources = _registry()

    validator.validate_registry_schema(contracts, sources)
    validator.validate_static_surfaces(sources)

    assert len(sources) == 63
    assert sum(source["implementation"] == "worker" for source in sources) == 58
    assert sum(source["runtime_scope"] == "v1_baseline" for source in sources) == 52
    assert sum(source["deployment_default"] for source in sources) == 9
    assert sum(source["catalog_state"] != "absent" for source in sources) == 59


def test_static_validator_rejects_silent_deployment_default_drift() -> None:
    _, sources = _registry()
    source = next(
        item for item in sources if item["adapter_key"] == "official.wra.historical_flood"
    )
    source["deployment_default"] = False

    with pytest.raises(
        validator.SourceRegistryValidationError,
        match="entrypoint deployment defaults drift",
    ):
        validator.validate_static_surfaces(sources)


def test_static_validator_rejects_unregistered_api_history_source() -> None:
    _, sources = _registry()
    sources = [
        source
        for source in sources
        if source["adapter_key"] != "news.public_web.wiki_search"
    ]

    with pytest.raises(
        validator.SourceRegistryValidationError,
        match="API history sources lack registry decisions",
    ):
        validator.validate_static_surfaces(sources)


def test_static_validator_rejects_official_catalog_drift() -> None:
    _, sources = _registry()
    sources = [
        source
        for source in sources
        if source["adapter_key"] != "official.nstc.flood_disaster_points"
    ]

    with pytest.raises(
        validator.SourceRegistryValidationError,
        match="official source catalog drift",
    ):
        validator.validate_static_surfaces(sources)


def test_catalog_validator_rejects_enablement_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, sources = _registry()
    rows = [
        (str(source["adapter_key"]), source["catalog_state"] == "enabled")
        for source in sources
        if source["catalog_state"] != "absent"
    ]
    rows = [
        (adapter_key, False if adapter_key == "official.cwa.rainfall" else enabled)
        for adapter_key, enabled in rows
    ]
    monkeypatch.setattr(
        validator.psycopg,
        "connect",
        lambda *args, **kwargs: FakeConnection(rows),
    )

    with pytest.raises(
        validator.SourceRegistryValidationError,
        match="official.cwa.rainfall: migrated catalog enabled=False",
    ):
        validator.validate_catalog(sources, database_url="postgresql://example.invalid/flood")
