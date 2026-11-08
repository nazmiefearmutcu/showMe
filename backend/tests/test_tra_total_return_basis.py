"""TRA#2 / TRA#3: TWR must include dividends, and drawdown must use the full series.

TRA#2: TWR compounded raw closes, so dividends never entered the "total"
figure. TWR now compounds (C_t + D_t) / C_(t-1) with dividends reinvested at the
close of the ex-date, and a basis label says whether dividends were available.

TRA#3: max drawdown was computed on the ~250 sampled chart points, so
peak-to-trough moves between samples were missed. It is now computed on the full
daily total-return index server-side.

Offline: the yfinance adapter is a fake that returns a prepared frame.
"""

from __future__ import annotations

import asyncio
from typing import Any

import numpy as np
import pandas as pd
import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.portfolio._more import TRAFunction

EQ = Instrument(symbol="ABC", asset_class=AssetClass.EQUITY)


class _Yf:
    def __init__(self, frame: pd.DataFrame) -> None:
        self._frame = frame

    async def fetch(self, request: Any) -> pd.DataFrame:  # noqa: ARG002
        return self._frame


def _run(frame: pd.DataFrame, **params: Any) -> Any:
    return asyncio.run(TRAFunction(FunctionDeps(yfinance=_Yf(frame))).execute(instrument=EQ, **params))


def _frame(closes: list[float], dividends: list[float] | None) -> pd.DataFrame:
    idx = pd.date_range("2024-01-02", periods=len(closes), freq="B", tz="UTC")
    data: dict[str, Any] = {"close": closes}
    if dividends is not None:
        data["dividends"] = dividends
    return pd.DataFrame(data, index=idx)


def test_twr_includes_a_dividend_on_a_flat_price() -> None:
    # Flat price, one $1 dividend on day 1: total return is 1%, price return is 0.
    res = _run(_frame([100.0, 100.0, 100.0], [0.0, 1.0, 0.0]))
    assert res.data["price_return_total"] == pytest.approx(0.0)
    assert res.data["twr_total"] == pytest.approx(0.01)
    assert res.data["total_return_basis"] == "dividends_reinvested"


def test_twr_without_dividend_series_is_labelled_price_only() -> None:
    res = _run(_frame([100.0, 110.0, 99.0], None))
    assert res.data["twr_total"] == pytest.approx(res.data["price_return_total"])
    assert res.data["total_return_basis"] == "price_only_dividends_unavailable"
    assert res.data["dividends_total"] is None


def test_cagr_is_on_the_total_return_basis() -> None:
    # Flat price with a 1% dividend on day 1 over 2 bars: CAGR must reflect the dividend.
    res = _run(_frame([100.0, 100.0, 100.0], [0.0, 1.0, 0.0]))
    assert res.data["cagr"] > 0.0
    assert res.data["cagr"] == pytest.approx(
        (1.0 + res.data["twr_total"]) ** (1.0 / _span_years(res.data)) - 1.0,
        rel=1e-9,
    )


def _span_years(data: dict[str, Any]) -> float:
    first = pd.Timestamp(data["first_date"])
    last = pd.Timestamp(data["last_date"])
    return max((last - first).days / 365.25, 1e-6)


def test_max_drawdown_uses_the_full_daily_series_not_the_samples() -> None:
    # 600 bars: rise to 200 at bar 300, fall to 100 at bar 301 (odd index),
    # recover. The chart sampling step is 2, so bar 301 is never sampled.
    n = 600
    closes = list(np.linspace(100.0, 200.0, 301))
    closes += [100.0]
    closes += list(np.linspace(100.0, 180.0, n - len(closes)))
    # wc3-g15: the yfinance adapter always supplies a splits column (zeros when the source
    # reports none). Without it a -50% one-day move is indistinguishable from an unreported
    # 2:1 split, and the drawdown is honestly withheld. The fixture carries the column so the
    # test keeps exercising the full-series drawdown.
    frame = _frame([float(c) for c in closes], [0.0] * n)
    frame["splits"] = [0.0] * n
    res = _run(frame)
    assert res.data["max_drawdown"] == pytest.approx(100.0 / 200.0 - 1.0, rel=1e-6)


def test_series_ends_on_the_last_observation() -> None:
    n = 700
    closes = [100.0 + i * 0.1 for i in range(n)]
    res = _run(_frame(closes, [0.0] * n))
    assert res.data["series"][-1]["date"] == res.data["last_date"]


def _split_frame(closes: list[float], split_at: int | None, ratio: float = 4.0) -> pd.DataFrame:
    frame = _frame(closes, [0.0] * len(closes))
    splits = [0.0] * len(closes)
    if split_at is not None:
        splits[split_at] = ratio
    frame["splits"] = splits
    return frame


def test_drawdown_across_a_reported_split_is_not_a_phantom_loss() -> None:
    # wc3-g15 TRA#3: a 4:1 split the source reports is removed before drawdown, so a flat
    # split-adjusted price has no drawdown (not -75%).
    closes = [400.0] * 5 + [100.0] * 5 + [102.0] * 2
    res = _run(_split_frame(closes, split_at=5))
    assert res.data["split_adjusted"] is True
    assert res.data["max_drawdown"] == pytest.approx(0.0, abs=1e-12), res.data["max_drawdown"]


def test_drawdown_is_not_reported_across_an_unconfirmed_split() -> None:
    # wc3-g15 TRA#3: with no split column, a 4:1 move is an unadjusted jump. The drawdown would
    # read -75% for a price that did not fall; it must be an honest null with a reason.
    closes = [400.0] * 5 + [100.0] * 5 + [102.0] * 2
    res = _run(_frame(closes, [0.0] * len(closes)))
    assert res.data["split_adjusted"] is False
    assert res.data["max_drawdown"] is None, res.data["max_drawdown"]
    assert res.data["max_drawdown_pct"] is None, res.data["max_drawdown_pct"]
    assert any("drawdown" in w and "not reported" in w for w in res.warnings), res.warnings
