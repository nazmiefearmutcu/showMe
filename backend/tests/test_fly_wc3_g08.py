"""FLY regression tests for wc3-g08 (offline).

* FLY#2-RQ - a non-finite numeric limit (JSON 1e400 -> float('inf')) is an
  input_error before the provider call, not an uncaught OverflowError.
* FLY#4-RQ - every card_schema slot key the seed declares is served by the
  live payload (top-level key), so the seed contract matches the handler.

The OpenSky adapter is an in-memory fake; nothing touches the network.
"""
from __future__ import annotations

import asyncio
from typing import Any

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.misc._extras import FLYFunction
from showme.manifest.seeds.fly_seed import fly

_EPOCH = 1794097110
_STATE = [
    "abc123", "THY123", "Turkey", _EPOCH, _EPOCH,
    28.9, 41.2, 10000.0, False, 230.0, 90.0, 0.0, None,
    10000.0, None, None, None,
]


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _OpenSky:
    def __init__(self) -> None:
        self.calls = 0

    async def fetch(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        self.calls += 1
        return {"time": _EPOCH, "states": [_STATE]}


def test_infinite_limit_is_input_error_and_skips_provider() -> None:
    opensky = _OpenSky()
    result = _run(FLYFunction(FunctionDeps(opensky=opensky)).execute(limit=float("inf")))
    assert result.data["status"] == "input_error", result.data
    assert "limit" in result.data["reason"]
    assert opensky.calls == 0


def test_nan_limit_is_input_error_and_skips_provider() -> None:
    opensky = _OpenSky()
    result = _run(FLYFunction(FunctionDeps(opensky=opensky)).execute(limit=float("nan")))
    assert result.data["status"] == "input_error", result.data
    assert opensky.calls == 0


def test_every_declared_card_slot_key_is_served_by_the_live_payload() -> None:
    result = _run(FLYFunction(FunctionDeps(opensky=_OpenSky())).execute())
    assert result.data["status"] == "live", result.data
    declared = [slot.key for slot in fly.card_schema.slots]
    missing = [key for key in declared if key not in result.data]
    assert not missing, f"seed declares card slots the handler does not serve: {missing}"
    assert result.data["aircraft_count"] == 1
