"""WETR#4-RQ — the manifest's ``provider_mode`` input is honoured by the backend.

``modeled`` must serve the labelled seasonal model (never live rows), and
``live_official`` must query the live chain. An unknown value is an explicit
input error, not a silent fallback. Network is patched with a fake adapter.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.commodity._funcs import WETRFunction


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


def _run(**params: Any) -> tuple[Any, _RecordingOpenMeteo]:
    fake = _RecordingOpenMeteo()
    result = asyncio.run(WETRFunction(FunctionDeps(open_meteo=fake)).execute(location="US_NORTHEAST", **params))
    return result, fake


def test_provider_mode_modeled_is_refused_no_synthetic_rows() -> None:
    # Data policy: the seasonal model was a generated sine curve; it is not served.
    result, fake = _run(provider_mode="modeled")
    assert fake.calls == [], "modeled mode must not query the live provider"
    assert result.data["status"] == "input_error"
    assert result.data["source_mode"] == "not_offered"
    assert result.data["rows"] == []


def test_provider_mode_live_official_queries_live_chain() -> None:
    result, fake = _run(provider_mode="live_official")
    assert fake.calls, "live_official must query the live provider"
    assert result.data["source_mode"] == "live_open_meteo"
    assert result.data["status"] == "ok"


def test_provider_mode_unknown_value_is_input_error_not_silent_live() -> None:
    result, fake = _run(provider_mode="guess")
    assert fake.calls == [], "an unknown mode must not silently run the live chain"
    assert result.data["status"] == "input_error"
    assert result.data["field"] == "provider_mode"
    assert "live_official" in result.data["allowed"] and "modeled" in result.data["allowed"]
