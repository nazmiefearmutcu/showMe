"""FREDAdapter.yield_curve_observations (p2a-g04 CRVF#2) and its yield_curve shim.

Offline: ``series`` is replaced by a stub, so no HTTP is performed.
"""

from __future__ import annotations

import asyncio
import math
import sys
from pathlib import Path

import pandas as pd

_HERE = Path(__file__).resolve()
_BACKEND_DIR = _HERE.parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from showme.engine.data_sources.macro.fred_adapter import FREDAdapter  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


def _frame(value: float | None, when: str | None) -> pd.DataFrame:
    if when is None:
        return pd.DataFrame({"value": []}, index=pd.DatetimeIndex([]))
    return pd.DataFrame({"value": [value]}, index=pd.DatetimeIndex([pd.Timestamp(when)]))


def _adapter_with(series_map: dict[str, pd.DataFrame | Exception]) -> FREDAdapter:
    adapter = FREDAdapter({})

    async def fake_series(series_id, *args, **kwargs):
        outcome = series_map.get(series_id, _frame(None, None))
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    adapter.series = fake_series  # type: ignore[method-assign]
    return adapter


def test_observations_carry_the_series_own_observation_date():
    adapter = _adapter_with({"DGS10": _frame(4.84, "2026-11-05")})
    obs = _run(adapter.yield_curve_observations())
    value, when = obs["DGS10"]
    assert value == 4.84
    assert when == pd.Timestamp("2026-11-05")


def test_empty_and_failed_series_are_nan_with_no_date():
    adapter = _adapter_with({"DGS2": _frame(None, None), "DGS5": RuntimeError("down")})
    obs = _run(adapter.yield_curve_observations())
    for sid in ("DGS2", "DGS5"):
        value, when = obs[sid]
        assert math.isnan(value)
        assert when is None


def test_yield_curve_shim_keeps_values_only():
    adapter = _adapter_with({"DGS10": _frame(4.84, "2026-11-05")})
    values = _run(adapter.yield_curve())
    assert values["DGS10"] == 4.84
    assert math.isnan(values["DGS2"])
