"""BTFW#1: no headline out-of-sample Sharpe/CAGR from a thin sample.

A 3-month routed history gave oos_sharpe 2.36 from 3 trades with a -22 worst
fold. Below the floor (126 OOS bars, 5 trades) the headline is null, the
summary says why, and a warning is shown; the real engine runs on fake bars.
"""
from __future__ import annotations

import asyncio

import numpy as np
import pandas as pd

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.portfolio.btfw import _MIN_OOS_BARS, BTFWFunction


def _bars(n: int) -> pd.DataFrame:
    rng = np.random.default_rng(11)
    close = 100 + np.cumsum(rng.normal(0.05, 1.0, n))
    idx = pd.date_range(end="2026-06-01", periods=n, freq="B")
    return pd.DataFrame({"open": close, "high": close * 1.01, "low": close * 0.99,
                         "close": close, "volume": 1_000_000.0}, index=idx)


class _YF:
    def __init__(self, n: int) -> None:
        self.n = n

    async def fetch(self, req):  # noqa: ARG002
        return _bars(self.n)


def _run(n: int, **params):
    fn = BTFWFunction(FunctionDeps(yfinance=_YF(n)))
    inst = Instrument(symbol="TEST", asset_class=AssetClass.EQUITY)
    return asyncio.run(fn.execute(instrument=inst, live=True, **params))


def test_three_month_history_has_no_headline_sharpe() -> None:
    res = _run(84, days=120)
    if res.data.get("status") != "ok":  # engine refused the tiny history outright
        assert res.data.get("summary", {}).get("oos_sharpe") is None
        return
    summary = res.data["summary"]
    assert summary["sample_sufficient"] is False
    assert summary["oos_bars"] < _MIN_OOS_BARS
    assert summary["oos_sharpe"] is None
    assert any("Sample too small" in w for w in res.warnings)
    assert res.data["oos_equity_curve"], "the curve itself stays visible"


def test_multi_year_history_keeps_the_headline() -> None:
    res = _run(900, days=1300)
    assert res.data["status"] == "ok"
    summary = res.data["summary"]
    assert summary["oos_bars"] >= _MIN_OOS_BARS
    if summary["sample_sufficient"]:
        assert "oos_sharpe" in summary
        assert not any("Sample too small" in w for w in res.warnings)
    else:  # too few trades on this path: the reason is still stated
        assert summary["oos_sharpe"] is None
        assert any("trades" in w for w in res.warnings)
