"""WETR#1 — every region the manifest/pane offers must resolve to its own
coordinates, and an unknown region must be an explicit input error (never a
silent fallback to New York weather labelled as the requested region).
Network is patched through a fake Open-Meteo adapter.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.commodity._funcs import LOCATION_PRESETS, WETRFunction
from showme.manifest import REGISTRY, load_seeds

NYC = (41.01, -74.0)


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


def test_asia_east_uses_shanghai_coordinates_not_new_york() -> None:
    result, fake = _run("ASIA_EAST")
    assert fake.calls, "the live provider must be queried for the requested region"
    lat, lon = fake.calls[0]
    assert abs(lat - 31.23) < 0.05 and abs(lon - 121.47) < 0.05
    assert (lat, lon) != NYC
    assert result.data["location"] == "ASIA_EAST"
    assert abs(result.data["lat"] - 31.23) < 0.05


def test_eu_nw_uses_northwest_europe_coordinates_not_new_york() -> None:
    result, fake = _run("EU_NW")
    assert fake.calls, "the live provider must be queried for the requested region"
    lat, lon = fake.calls[0]
    assert 45.0 <= lat <= 56.0 and -5.0 <= lon <= 10.0
    assert (lat, lon) != NYC
    assert result.data["location"] == "EU_NW"


def test_brazil_se_uses_sao_paulo_coordinates() -> None:
    result, fake = _run("BRAZIL_SE")
    assert fake.calls, "the live provider must be queried for the requested region"
    lat, lon = fake.calls[0]
    assert abs(lat - (-23.55)) < 0.05 and abs(lon - (-46.63)) < 0.05
    assert result.data["location"] == "BRAZIL_SE"


def test_unknown_location_is_an_input_error_not_new_york_weather() -> None:
    result, fake = _run("MARS_BASE")
    assert fake.calls == [], "an unknown region must not query weather for New York"
    assert result.data["status"] == "input_error"
    assert result.data["rows"] == []
    assert result.data["next_actions"]


def test_every_manifest_location_option_has_a_preset() -> None:
    load_seeds(module_names=["wetr_seed"])
    entry = REGISTRY.get("WETR")
    location_input = next(i for i in entry.inputs if i.name == "location")
    missing = [opt for opt in location_input.options if opt not in LOCATION_PRESETS]
    assert missing == [], f"manifest offers regions without coordinates: {missing}"
