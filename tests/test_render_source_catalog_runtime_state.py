from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from infra.scripts import render_source_catalog_runtime_state as renderer
from infra.scripts import validate_source_registry as validator

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "config" / "source-registry.yaml"
CATALOG_PATH = REPO_ROOT / "docs" / "data-sources" / "official" / "official-source-catalog.yaml"


def _read(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


def _without_runtime_state(text: str) -> str:
    return "\n".join(line for line in text.split("\n") if "runtime_state:" not in line)


def _catalog_sources(text: str) -> dict[str, dict[str, object]]:
    payload = yaml.safe_load(text)
    return {source["key"]: source for source in payload["sources"]}


def _copies(tmp_path: Path, *, rendered: bool = False) -> tuple[Path, Path]:
    """Copy the real registry and catalog; the catalog starts un-rendered by default."""
    registry = tmp_path / "source-registry.yaml"
    catalog = tmp_path / "official-source-catalog.yaml"
    registry.write_bytes(REGISTRY_PATH.read_bytes())
    catalog_text = _read(CATALOG_PATH)
    if not rendered:
        catalog_text = _without_runtime_state(catalog_text)
    catalog.write_bytes(catalog_text.encode("utf-8"))
    return registry, catalog


def test_mapping_covers_every_enablement_decision_used_by_the_registry() -> None:
    registry = yaml.safe_load(_read(REGISTRY_PATH))
    used = {str(source["enablement_decision"]) for source in registry["sources"]}

    assert used, "registry must declare enablement decisions"
    assert used <= set(renderer.RUNTIME_STATE_BY_ENABLEMENT_DECISION)


def test_unknown_enablement_decision_is_listed_and_exits_non_zero(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    registry, catalog = _copies(tmp_path)
    registry.write_bytes(
        _read(registry)
        .replace("enablement_decision: production_backbone", "enablement_decision: brand_new", 1)
        .encode("utf-8")
    )

    with pytest.raises(renderer.RuntimeStateRenderError) as excinfo:
        renderer.load_runtime_states_by_adapter_key(registry)
    assert "brand_new" in str(excinfo.value)

    assert renderer.main(["--check", "--registry", str(registry), "--catalog", str(catalog)]) == 1
    assert "brand_new" in capsys.readouterr().err


def test_check_fails_when_runtime_state_is_missing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    registry, catalog = _copies(tmp_path)

    assert renderer.main(["--check", "--registry", str(registry), "--catalog", str(catalog)]) == 1
    stderr = capsys.readouterr().err
    assert "official.cwa.rainfall: missing runtime_state" in stderr


def test_check_fails_when_a_runtime_state_value_disagrees_with_the_registry(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    registry, catalog = _copies(tmp_path, rendered=True)
    catalog.write_bytes(
        _read(catalog).replace("runtime_state: live", "runtime_state: retired", 1).encode("utf-8")
    )

    assert renderer.main(["--check", "--registry", str(registry), "--catalog", str(catalog)]) == 1
    stderr = capsys.readouterr().err
    assert "runtime_state 'retired', expected 'live'" in stderr


def test_render_makes_check_pass_and_is_idempotent(tmp_path: Path) -> None:
    registry, catalog = _copies(tmp_path)

    assert renderer.render_catalog_file(catalog_path=catalog, registry_path=registry) is True
    assert renderer.main(["--check", "--registry", str(registry), "--catalog", str(catalog)]) == 0

    rendered = _read(catalog)
    assert renderer.render_catalog_file(catalog_path=catalog, registry_path=registry) is False
    assert _read(catalog) == rendered
    assert rendered == _read(CATALOG_PATH)


def test_render_only_adds_runtime_state_lines_and_keeps_review_status(tmp_path: Path) -> None:
    registry, catalog = _copies(tmp_path)
    before = _read(catalog)
    renderer.render_catalog_file(catalog_path=catalog, registry_path=registry)
    after = _read(catalog)

    assert _without_runtime_state(after) == before
    assert "\r\n" not in after

    before_sources = _catalog_sources(before)
    after_sources = _catalog_sources(after)
    assert set(before_sources) == set(after_sources)
    for key, source in before_sources.items():
        assert after_sources[key]["status"] == source["status"], key
        assert {k: v for k, v in after_sources[key].items() if k != "runtime_state"} == source


def test_render_derives_states_from_the_registry_decisions(tmp_path: Path) -> None:
    registry, catalog = _copies(tmp_path)
    renderer.render_catalog_file(catalog_path=catalog, registry_path=registry)
    payload = yaml.safe_load(_read(catalog))
    sources = {source["key"]: source for source in payload["sources"]}

    # official.ncdr.cap is `disabled_by_default` in the reviewed status field but the
    # registry enables it, so the derived runtime state must follow the registry.
    assert sources["official.ncdr.cap"]["status"] == "disabled_by_default"
    assert sources["official.ncdr.cap"]["runtime_state"] == "live"
    assert sources["official.cwa.heavy_rain_warning"]["runtime_state"] == "retired"
    assert sources["official.wra.flood_incident"]["runtime_state"] == "blocked"
    assert sources["official.flood_potential.geojson"]["runtime_state"] == "reference"
    assert sources["geocoder.moi.village_boundary"]["runtime_state"] == (
        renderer.UNREGISTERED_RUNTIME_STATE
    )

    # `gaps` entries are review notes, not sources, and must stay untouched.
    assert {gap["key"] for gap in payload["gaps"]} == {
        "historical_news",
        "national_doorplate_coordinates",
    }
    assert all("runtime_state" not in gap for gap in payload["gaps"])


def test_source_registry_validator_rejects_a_stale_catalog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stale = tmp_path / "official-source-catalog.yaml"
    stale.write_bytes(_without_runtime_state(_read(CATALOG_PATH)).encode("utf-8"))
    monkeypatch.setattr(validator, "OFFICIAL_SOURCE_CATALOG_PATH", stale)

    with pytest.raises(validator.SourceRegistryValidationError) as excinfo:
        validator.validate_catalog_runtime_state()
    assert "render_source_catalog_runtime_state" in str(excinfo.value)


def test_checked_in_catalog_matches_the_registry() -> None:
    assert renderer.check_catalog_runtime_state() == []
    assert renderer.main(["--check"]) == 0
    validator.validate_catalog_runtime_state()
