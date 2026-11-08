"""REGM history mode: a non-integer window is an explicit input_error, not a crash.

The seed's ``window`` default is ``"3m"`` (a month label), but history mode reads
the value as an integer bar count. ``int("3m")`` raised ValueError out of the
function. A bad window now returns input_error with a next action.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from showme.engine.core.base_function import FunctionDeps  # noqa: E402
from showme.engine.functions.macro.regm import REGMFunction  # noqa: E402


class _FakeYFinance:
    """Deterministic benchmark fixture (seeded random walk), not live data."""

    async def fetch(self, request):  # noqa: ANN001 - fake seam
        import numpy as np
        import pandas as pd

        rng = np.random.default_rng(7)
        close = 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.01, size=300)))
        idx = pd.date_range(end="2026-09-20", periods=300, freq="D")
        return pd.DataFrame({"close": close}, index=idx)


class _Boom:
    async def get(self, url, timeout=None):  # noqa: ANN001 - fake seam
        raise RuntimeError("network down")


def _fn() -> REGMFunction:
    fn = REGMFunction(FunctionDeps(yfinance=_FakeYFinance()))
    fn._http_client = _Boom()
    return fn


def test_history_with_month_label_window_is_input_error() -> None:
    out = asyncio.run(_fn().execute(symbol="SPY", action="history", window="3m"))

    assert out.data["status"] == "input_error", out.data
    assert "window" in out.data["reason"], out.data
    assert out.data["next_actions"], out.data


def test_history_with_integer_window_still_classifies() -> None:
    out = asyncio.run(_fn().execute(symbol="SPY", action="history", window=60))

    assert out.data.get("status") != "input_error", out.data
    assert out.data["history"], out.data
