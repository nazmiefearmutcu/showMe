"""WC3-G01 BTFW#3 (route path): the pane's History control reaches the backtest.

The pane sends ``window_length`` and never ``days``. The generic route merges
the agent profile, which injects ``days=120``; before this fix the injected
days silently replaced the typed window (the handler then ignored
window_length). These tests go through the real router merge
(``server._route_function_params``) and then the BTFW handler, so they fail
on the broken path, unlike the direct-execute tests in
test_btfw_inputs_wc3_g01.py.

Offline: the OHLCV fetcher and the walk-forward engine are fakes.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from showme import server
from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.portfolio import btfw as btfw_mod
from showme.engine.functions.portfolio.btfw import BTFWFunction


def _bars(n: int = 400) -> pd.DataFrame:
    rng = np.random.default_rng(11)
    close = 100 + np.cumsum(rng.normal(0.05, 1.0, n))
    idx = pd.date_range(end="2026-06-01", periods=n, freq="B")
    return pd.DataFrame({"open": close, "high": close * 1.01, "low": close * 0.99,
                         "close": close, "volume": 1_000_000.0}, index=idx)


class _RecordingYF:
    def __init__(self):
        self.requests = []

    async def fetch(self, req):
        self.requests.append(req)
        return _bars()


class _StopEngine:
    """Stands in for the walk-forward engine and stops before any fit."""

    def __init__(self, bars, strategy_name, **kwargs):
        raise ValueError("stop before fit")


def _pane_params(**typed):
    """What the BTFW pane sends on the real request path (symbol plus typed controls).

    The symbol is explicit and equity-classed so the router never resolves a
    crypto alias over the network.
    """
    return {"symbol": "AAPL", "asset_class": "EQUITY", "live": True,
            "strategy_id": "rsi_meanrev", "window_length": "1Y", **typed}


def _route(params):
    routed = server._route_function_params("BTFW", dict(params))
    routed.pop("__explicit_symbol", None)
    return routed


def test_routed_pane_window_is_not_overridden_by_injected_days():
    routed = _route(_pane_params())
    assert routed.get("window_length") == "1Y"
    assert "days" not in routed


def test_typed_window_sets_the_history_span_on_the_routed_path(monkeypatch):
    monkeypatch.setattr(btfw_mod, "WalkForwardBacktest", _StopEngine)
    yf = _RecordingYF()
    fn = BTFWFunction(FunctionDeps(yfinance=yf))
    routed = _route(_pane_params())
    inst = Instrument(symbol="TEST", asset_class=AssetClass.EQUITY)
    res = asyncio.run(fn.execute(instrument=inst, **routed))
    assert res.metadata["days"] == 365
    span = pd.Timestamp(yf.requests[0].start)
    assert abs((pd.Timestamp(datetime.now(timezone.utc)) - span).days - 365) <= 1
    assert not any("window_length is not applied" in w for w in res.warnings)


def test_caller_days_still_wins_on_the_routed_path():
    routed = _route(_pane_params(days=90))
    assert routed["days"] == 90


def test_route_without_window_injects_no_days():
    # BTFW#1 / route probe policy: no window was sent, so the route injects no
    # 120-day window; the handler's own lookback applies.
    routed = _route({"symbol": "AAPL", "asset_class": "EQUITY", "live": True})
    assert "days" not in routed
