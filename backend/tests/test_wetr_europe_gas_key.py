"""WETR residual — the EUROPE_GAS preset was labelled "Northwest Europe" but
carried Berlin coordinates. Berlin weather under a Northwest Europe label is a
mislabelled series, so the key must not resolve at all: a direct API call with
EUROPE_GAS is an explicit input error (EU_NW is the Rotterdam preset that
replaces it). Network is patched through a fake Open-Meteo adapter.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.commodity._funcs import LOCATION_PRESETS, WETRFunction


class _RecordingOpenMeteo:
    def __init__(self) -> None:
        self.calls: list[tuple[float, float]] = []

    async def onecall(self, lat: float, lon: float, days: int = 10) -> dict[str, Any]:  # noqa: ARG002
        self.calls.append((lat, lon))
        return {
            "daily": [
                {
                    "dt": datetime(2026, 11, 8, tzinfo=timezone.utc).timestamp(),
                    "temp": {"day": 12.0, "min": 8.0, "max": 16.0},
                    "precipitation": 0.0,
                }
            ]
        }


def _run(location: str) -> tuple[Any, _RecordingOpenMeteo]:
    fake = _RecordingOpenMeteo()
    result = asyncio.run(WETRFunction(FunctionDeps(open_meteo=fake)).execute(location=location))
    return result, fake


def test_europe_gas_key_is_not_a_preset() -> None:
    assert "EUROPE_GAS" not in LOCATION_PRESETS


def test_europe_gas_key_is_an_input_error_with_no_weather_query() -> None:
    result, fake = _run("EUROPE_GAS")
    assert fake.calls == [], "a mislabelled Berlin preset must not query weather"
    assert result.data["status"] == "input_error"
    assert result.data["rows"] == []
    assert "EU_NW" in " ".join(result.data["next_actions"])


def test_every_preset_label_matches_its_own_coordinates_region() -> None:
    # Guard against another mislabelled preset: a Northwest Europe label must
    # carry Northwest Europe coordinates (lat 45-56, lon -5..10).
    for key, preset in LOCATION_PRESETS.items():
        if "Northwest Europe" in preset["label"]:
            assert 45.0 <= preset["lat"] <= 56.0 and -5.0 <= preset["lon"] <= 10.0, key
