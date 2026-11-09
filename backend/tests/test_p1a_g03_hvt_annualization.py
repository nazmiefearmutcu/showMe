"""P1a-g03 HVT#1 — crypto realized vol must annualize on the calendar-day basis.

HVT annualized every symbol with sqrt(252). Crypto trades every calendar day,
so BTC-USD realized vol was understated by about 1 - sqrt(252/365) = 16.9%.
These tests drive HVTFunction.execute through a fake yfinance adapter (no
network) and pin the factor per asset class.
"""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.derivative._stubs import HVTFunction


class _FakeYF:
    """OHLCV adapter returning ``n`` consecutive calendar-day closes (weekends included)."""

    def __init__(self, n: int = 400, seed: int = 11) -> None:
        rng = np.random.default_rng(seed)
        rets = rng.normal(0.0002, 0.02, n)
        self.closes = 60000.0 * np.exp(np.cumsum(rets))
        self.n = n

    async def fetch(self, request: DataRequest):  # noqa: ANN001
        assert request.kind == DataKind.OHLCV
        idx = pd.date_range(end=datetime.now(timezone.utc).date(), periods=self.n, freq="D")
        return pd.DataFrame({"close": self.closes, "open": self.closes,
                             "high": self.closes, "low": self.closes,
                             "volume": np.ones(self.n)}, index=idx)


class _Deps:
    def __init__(self, yfinance=None) -> None:
        self.yfinance = yfinance

    def __getattr__(self, item):  # pragma: no cover
        return None


def _run(symbol: str, asset: AssetClass, yf: _FakeYF):
    fn = HVTFunction(deps=_Deps(yfinance=yf))
    return asyncio.run(fn.execute(Instrument(symbol=symbol, asset_class=asset)))


def _expected_30d(closes: np.ndarray, factor: int) -> float:
    rets = pd.Series(closes).pct_change().dropna()
    return float(rets.tail(30).std() * math.sqrt(factor))


def test_crypto_realized_vol_uses_calendar_day_annualization() -> None:
    yf = _FakeYF()
    result = _run("BTC-USD", AssetClass.CRYPTO, yf)
    row30 = next(r for r in result.data["rows"] if r["window_days"] == 30)

    # RED before fix: the engine multiplied by sqrt(252) for every symbol.
    assert row30["realized_vol"] == _approx(_expected_30d(yf.closes, 365))
    assert result.data["annualization_days"] == 365
    assert "sqrt(365)" in result.data["methodology"]


def test_equity_realized_vol_keeps_trading_day_annualization() -> None:
    yf = _FakeYF()
    result = _run("AAPL", AssetClass.EQUITY, yf)
    row30 = next(r for r in result.data["rows"] if r["window_days"] == 30)

    assert row30["realized_vol"] == _approx(_expected_30d(yf.closes, 252))
    assert result.data["annualization_days"] == 252
    assert "sqrt(252)" in result.data["methodology"]


def test_crypto_rolling_history_uses_calendar_day_annualization() -> None:
    yf = _FakeYF()
    result = _run("BTC-USD", AssetClass.CRYPTO, yf)
    history = result.data["history"]
    assert history
    window = history[-1]["window_days"]
    rets = pd.Series(yf.closes).pct_change().dropna()
    expected_last = float(rets.tail(window).std() * math.sqrt(365))
    assert history[-1]["vol"] == _approx(expected_last)


def _approx(value: float):
    import pytest

    return pytest.approx(value, rel=1e-9)
