from __future__ import annotations

from datetime import UTC, datetime

from app.adapters.contracts import AdapterRunResult, RawSourceItem
from app.ops.official_realtime_live_smoke import (
    SmokeSource,
    load_env_file,
    run_smoke_sources,
)


FETCHED_AT = datetime(2026, 6, 28, 12, 0, tzinfo=UTC)


class _FakeAdapter:
    def __init__(self, result: AdapterRunResult) -> None:
        self._result = result

    def run(self) -> AdapterRunResult:
        return self._result


def _raw(county: str | None, index: int) -> RawSourceItem:
    payload = {"station_id": f"station-{index}"}
    if county is not None:
        payload["county"] = county
    return RawSourceItem(
        source_id=f"source-{index}",
        source_url="https://example.test/source",
        fetched_at=FETCHED_AT,
        payload=payload,
    )


def _result(adapter_key: str, counties: tuple[str | None, ...]) -> AdapterRunResult:
    fetched = tuple(_raw(county, index) for index, county in enumerate(counties))
    return AdapterRunResult(
        adapter_key=adapter_key,
        fetched=fetched,
        normalized=(),
        rejected=(),
    )


def test_load_env_file_reads_simple_values_and_does_not_override_process_env(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "# comment",
                "CWA_API_AUTHORIZATION='from-file'",
                'SOURCE_CWA_ENABLED="true"',
                "EMPTY_VALUE=",
                "MALFORMED",
            ]
        ),
        encoding="utf-8",
    )

    values = load_env_file(env_file, base_env={"CWA_API_AUTHORIZATION": "from-process"})

    assert values["CWA_API_AUTHORIZATION"] == "from-process"
    assert values["SOURCE_CWA_ENABLED"] == "true"
    assert values["EMPTY_VALUE"] == ""
    assert "MALFORMED" not in values


def test_run_smoke_sources_skips_required_env_and_counts_offshore_backbone() -> None:
    result = run_smoke_sources(
        (
            SmokeSource(
                adapter_key="official.cwa.rainfall",
                build_adapter=lambda env, timeout: _FakeAdapter(
                    _result("official.cwa.rainfall", ("臺北市",))
                ),
                required_env="CWA_API_AUTHORIZATION",
            ),
            SmokeSource(
                adapter_key="official.civil_iot.sewer_water_level",
                build_adapter=lambda env, timeout: _FakeAdapter(
                    _result(
                        "official.civil_iot.sewer_water_level",
                        ("金門縣", "金門縣", "連江縣", None),
                    )
                ),
                minimum_fetched_count=1,
                minimum_normalized_count=0,
            ),
        ),
        env={},
        timeout_seconds=8,
    )

    statuses = {item.adapter_key: item for item in result.results}
    assert statuses["official.cwa.rainfall"].status == "skipped"
    assert "CWA_API_AUTHORIZATION" in (statuses["official.cwa.rainfall"].message or "")
    sewer = statuses["official.civil_iot.sewer_water_level"]
    assert sewer.status == "healthy"
    assert sewer.fetched_count == 4
    assert sewer.kinmen_count == 2
    assert sewer.lienchiang_count == 1
    assert sewer.county_counts_by_county == {"金門縣": 2, "連江縣": 1}
    assert sewer.to_dict()["county_counts_by_county"] == {"金門縣": 2, "連江縣": 1}


def test_run_smoke_sources_marks_low_volume_source_failed() -> None:
    result = run_smoke_sources(
        (
            SmokeSource(
                adapter_key="official.wra.water_level",
                build_adapter=lambda env, timeout: _FakeAdapter(
                    _result("official.wra.water_level", ())
                ),
                minimum_fetched_count=1,
                minimum_normalized_count=0,
            ),
        ),
        env={},
        timeout_seconds=8,
    )

    assert result.results[0].status == "failed"
    assert "fetched 0" in (result.results[0].message or "")
    assert result.healthy is False
