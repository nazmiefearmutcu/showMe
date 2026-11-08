"""BMTX: a requested strategy that is not registered is reported, never dropped silently."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.portfolio.bmtx import BMTXFunction


def _run(coro):
    return asyncio.run(coro)


def _ohlcv(days: int = 400, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    periods = pd.date_range(end=datetime.now(timezone.utc).date(), periods=days, freq="B")
    close = np.abs(100 + np.cumsum(rng.normal(0.05, 1.0, len(periods)))) + 10
    return pd.DataFrame({
        "open": close * 0.999, "high": close * 1.01, "low": close * 0.99,
        "close": close, "volume": 1_000_000.0,
    }, index=periods)


class _Yf:
    async def fetch(self, request: Any) -> pd.DataFrame:
        return _ohlcv()


def _fn() -> BMTXFunction:
    return BMTXFunction(FunctionDeps(yfinance=_Yf()))


def test_unknown_strategy_is_named_in_data_and_warnings() -> None:
    res = _run(_fn().execute(symbols=["AAPL"], strategies=["buy_and_hold", "does_not_exist"],
                             live_backtest=True))

    assert res.data["unknown_strategies"] == ["does_not_exist"]
    assert any("does_not_exist" in w for w in res.warnings)
    assert res.data["status"] == "partial"
    assert {c["strategy"] for c in res.data["cells"]} == {"buy_and_hold"}


def test_only_unknown_strategies_is_input_error_and_names_them() -> None:
    res = _run(_fn().execute(symbols=["AAPL"], strategies=["does_not_exist"], live_backtest=True))

    # The OHLCV provider worked; the caller's strategy name is what failed.
    assert res.data["status"] == "input_error"
    assert res.data["cells"] == []
    assert "does_not_exist" in res.data["reason"]
    assert any("does_not_exist" in w for w in res.warnings)
    assert res.data["next_actions"]
    assert res.metadata["provider_errors"] == []


def test_strategy_run_that_raises_is_empty_with_reason_not_provider_outage(monkeypatch: pytest.MonkeyPatch) -> None:
    import showme.engine.functions.portfolio.bmtx as bmtx_mod

    class _RaisingBacktest:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def run(self) -> None:
            raise ValueError("bad signal")

    monkeypatch.setattr(bmtx_mod, "Backtest", _RaisingBacktest)
    res = _run(_fn().execute(symbols=["AAPL"], strategies=["buy_and_hold", "does_not_exist"],
                             live_backtest=True))

    assert res.data["status"] == "empty"
    assert res.data["cells"] == []
    assert "buy_and_hold" in res.data["reason"] and "bad signal" in res.data["reason"]
    assert "does_not_exist" in res.data["reason"]
    assert any("bad signal" in w for w in res.warnings)
    assert res.metadata["provider_errors"] == []
