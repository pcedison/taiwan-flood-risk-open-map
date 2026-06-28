from __future__ import annotations

import json
import os
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from app.adapters.civil_iot import (
    GATE_WATER_LEVEL,
    PUMP_WATER_LEVEL,
    SEWER_WATER_LEVEL,
    FloodSensorStaApiAdapter,
    StaWaterLevelApiAdapter,
)
from app.adapters.contracts import AdapterRunResult
from app.adapters.cwa import CwaRainfallApiAdapter
from app.adapters.ncdr import NcdrCapAlertAdapter
from app.adapters.wra import WraWaterLevelApiAdapter
from app.adapters.wra_iow import WraIowFloodDepthApiAdapter


SmokeStatus = Literal["healthy", "failed", "skipped"]
AdapterBuilder = Callable[[Mapping[str, str], int], Any]


@dataclass(frozen=True)
class SmokeSource:
    adapter_key: str
    build_adapter: AdapterBuilder
    required_env: str | None = None
    minimum_fetched_count: int = 1
    minimum_normalized_count: int = 1


@dataclass(frozen=True)
class SmokeSourceResult:
    adapter_key: str
    status: SmokeStatus
    fetched_count: int = 0
    normalized_count: int = 0
    rejected_count: int = 0
    covered_county_count: int = 0
    kinmen_count: int = 0
    lienchiang_count: int = 0
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter_key": self.adapter_key,
            "status": self.status,
            "fetched_count": self.fetched_count,
            "normalized_count": self.normalized_count,
            "rejected_count": self.rejected_count,
            "covered_county_count": self.covered_county_count,
            "kinmen_count": self.kinmen_count,
            "lienchiang_count": self.lienchiang_count,
            "message": self.message,
        }


@dataclass(frozen=True)
class OfficialRealtimeSmokeResult:
    results: tuple[SmokeSourceResult, ...]

    @property
    def healthy(self) -> bool:
        return all(result.status in {"healthy", "skipped"} for result in self.results)

    def to_dict(self) -> dict[str, Any]:
        return {
            "healthy": self.healthy,
            "results": [result.to_dict() for result in self.results],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)


def load_env_file(
    env_file: Path,
    *,
    base_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    values = dict(base_env or os.environ)
    if not env_file.exists():
        return values
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in values:
            continue
        values[key] = _unquote_env_value(value.strip())
    return values


def run_official_realtime_live_smoke(
    *,
    env: Mapping[str, str] | None = None,
    timeout_seconds: int = 20,
) -> OfficialRealtimeSmokeResult:
    return run_smoke_sources(
        default_official_smoke_sources(),
        env=dict(env or os.environ),
        timeout_seconds=timeout_seconds,
    )


def run_smoke_sources(
    sources: Sequence[SmokeSource],
    *,
    env: Mapping[str, str],
    timeout_seconds: int,
) -> OfficialRealtimeSmokeResult:
    results = tuple(_run_smoke_source(source, env, timeout_seconds) for source in sources)
    return OfficialRealtimeSmokeResult(results=results)


def default_official_smoke_sources() -> tuple[SmokeSource, ...]:
    return (
        SmokeSource(
            adapter_key="official.cwa.rainfall",
            required_env="CWA_API_AUTHORIZATION",
            build_adapter=lambda env, timeout: CwaRainfallApiAdapter(
                authorization=env["CWA_API_AUTHORIZATION"],
                timeout_seconds=timeout,
            ),
        ),
        SmokeSource(
            adapter_key="official.wra.water_level",
            build_adapter=lambda env, timeout: WraWaterLevelApiAdapter(timeout_seconds=timeout),
        ),
        SmokeSource(
            adapter_key="official.wra_iow.flood_depth",
            build_adapter=lambda env, timeout: WraIowFloodDepthApiAdapter(
                timeout_seconds=timeout
            ),
        ),
        SmokeSource(
            adapter_key="official.ncdr.cap",
            build_adapter=lambda env, timeout: NcdrCapAlertAdapter(timeout_seconds=timeout),
            minimum_fetched_count=0,
            minimum_normalized_count=0,
        ),
        SmokeSource(
            adapter_key="official.civil_iot.flood_sensor",
            build_adapter=lambda env, timeout: FloodSensorStaApiAdapter(timeout_seconds=timeout),
        ),
        SmokeSource(
            adapter_key="official.civil_iot.sewer_water_level",
            build_adapter=lambda env, timeout: StaWaterLevelApiAdapter(
                SEWER_WATER_LEVEL,
                timeout_seconds=timeout,
            ),
        ),
        SmokeSource(
            adapter_key="official.civil_iot.pump_water_level",
            build_adapter=lambda env, timeout: StaWaterLevelApiAdapter(
                PUMP_WATER_LEVEL,
                timeout_seconds=timeout,
            ),
        ),
        SmokeSource(
            adapter_key="official.civil_iot.gate_water_level",
            build_adapter=lambda env, timeout: StaWaterLevelApiAdapter(
                GATE_WATER_LEVEL,
                timeout_seconds=timeout,
            ),
        ),
    )


def _run_smoke_source(
    source: SmokeSource,
    env: Mapping[str, str],
    timeout_seconds: int,
) -> SmokeSourceResult:
    if source.required_env and not env.get(source.required_env):
        return SmokeSourceResult(
            adapter_key=source.adapter_key,
            status="skipped",
            message=f"{source.required_env} is not available",
        )
    try:
        adapter = source.build_adapter(env, timeout_seconds)
        run_result: AdapterRunResult = adapter.run()
    except Exception as exc:
        return SmokeSourceResult(
            adapter_key=source.adapter_key,
            status="failed",
            message=f"{type(exc).__name__}: {exc}",
        )
    return _source_result_from_adapter_run(source, run_result)


def _source_result_from_adapter_run(
    source: SmokeSource,
    run_result: AdapterRunResult,
) -> SmokeSourceResult:
    counties = Counter(
        str(item.payload.get("county"))
        for item in run_result.fetched
        if item.payload.get("county") is not None
    )
    fetched_count = len(run_result.fetched)
    normalized_count = len(run_result.normalized)
    rejected_count = len(run_result.rejected)
    status: SmokeStatus = "healthy"
    message = None
    if fetched_count < source.minimum_fetched_count:
        status = "failed"
        message = (
            f"{source.adapter_key} fetched {fetched_count}, "
            f"expected at least {source.minimum_fetched_count}"
        )
    elif normalized_count < source.minimum_normalized_count:
        status = "failed"
        message = (
            f"{source.adapter_key} normalized {normalized_count}, "
            f"expected at least {source.minimum_normalized_count}"
        )
    return SmokeSourceResult(
        adapter_key=source.adapter_key,
        status=status,
        fetched_count=fetched_count,
        normalized_count=normalized_count,
        rejected_count=rejected_count,
        covered_county_count=len(counties),
        kinmen_count=counties.get("金門縣", 0),
        lienchiang_count=counties.get("連江縣", 0),
        message=message,
    )


def _unquote_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value
