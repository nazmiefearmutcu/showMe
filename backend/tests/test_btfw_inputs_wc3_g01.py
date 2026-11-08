"""WC3-G01 BTFW#3: the declared BTFW inputs reach the handler.

strategy_id, window_length, commission_bps, walk_steps (declared default 5,
matching the handler), train_pct and walk_mode are read under their manifest
names. A typed value that is not valid returns an explicit input_error, not a
silent default. Offline: the OHLCV fetcher and the walk-forward engine are fakes.
"""

from __future__ import annotations

import asyncio

import numpy as np
import pandas as pd
import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.portfolio import btfw as btfw_mod
from showme.engine.functions.portfolio.btfw import BTFWFunction
from showme.engine.services.backtest_framework import STRATEGY_REGISTRY


def _inst() -> Instrument:
    return Instrument(symbol="TEST", asset_class=AssetClass.EQUITY)


def _bars(n: int = 400) -> pd.DataFrame:
    rng = np.random.default_rng(7)
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


class _SpyEngine:
    """Records the WalkForwardBacktest arguments and stops before any fit."""
    calls: list[dict] = []

    def __init__(self, bars, strategy_name, **kwargs):
        _SpyEngine.calls.append({"strategy": strategy_name, **kwargs})
        raise ValueError("spy stop")


@pytest.fixture
def spy(monkeypatch):
    _SpyEngine.calls = []
    monkeypatch.setattr(btfw_mod, "WalkForwardBacktest", _SpyEngine)
    return _SpyEngine


def _run(yf=None, **params):
    fn = BTFWFunction(FunctionDeps(yfinance=yf or _RecordingYF()))
    return asyncio.run(fn.execute(instrument=_inst(), live=True, **params))


def test_declared_walk_steps_default_matches_the_handler(spy):
    from showme.manifest.registry import REGISTRY
    from showme.manifest.seeds import load_seeds
    load_seeds()
    declared = REGISTRY.get("BTFW").defaults["walk_steps"]
    _run()
    assert spy.calls[0]["n_splits"] == declared == 5


def test_strategy_id_is_honoured(spy):
    res = _run(strategy_id="rsi_meanrev")
    assert spy.calls[0]["strategy"] == "rsi_meanrev"
    assert res.data["status"] == "placeholder" or res.sources == ["local_backtest_model"]


def test_legacy_strategy_name_still_works(spy):
    _run(strategy="buy_and_hold")
    assert spy.calls[0]["strategy"] == "buy_and_hold"


def test_commission_bps_is_the_fee_actually_charged(spy):
    _run(commission_bps=12.5)
    assert spy.calls[0]["fee_bps"] == pytest.approx(12.5)


def test_window_length_sets_the_history_span():
    yf = _RecordingYF()
    _run(yf, window_length="1Y")
    req = yf.requests[0]
    span = pd.Timestamp(req.start)
    assert abs((pd.Timestamp.now(tz="UTC") - span).days - 365) <= 1


def test_days_takes_precedence_over_window_length_and_says_so(spy):
    res = _run(window_length="1Y", days=120)
    assert res.metadata["days"] == 120
    assert any("window_length is not applied" in w for w in res.warnings)


def test_walk_steps_and_train_pct_reach_the_engine(spy):
    _run(walk_steps=8, train_pct=0.6, walk_mode="rolling")
    call = spy.calls[0]
    assert call["n_splits"] == 8
    assert call["train_pct"] == pytest.approx(0.6)
    assert call["mode"] == "rolling"


@pytest.mark.parametrize("params", [
    {"train_pct": "abc"},
    {"train_pct": 0.99},
    {"walk_steps": 1},
    {"walk_steps": 2.5},
    {"walk_mode": "expanding"},
    {"window_length": "5Y"},
    {"commission_bps": "free"},
])
def test_invalid_typed_input_is_an_explicit_input_error(params):
    res = _run(**params)
    assert res.data["status"] == "input_error"
    assert res.data["reason"].startswith("BTFW:")
    assert res.data["summary"]["oos_sharpe"] is None
    assert res.data["equity_curve"] == []


def test_registry_strategies_are_the_selectable_options():
    from showme.manifest.registry import REGISTRY
    from showme.manifest.seeds import load_seeds
    load_seeds()
    spec = next(i for i in REGISTRY.get("BTFW").inputs if i.name == "strategy_id")
    assert set(spec.options) == set(STRATEGY_REGISTRY)
