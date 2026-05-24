"""Audit Q3 #9 / #10 — Sharpe r_f, Sortino denominator, Calmar floor.

Pins:
  * Sharpe subtracts annualized rf/252 from mean return before
    annualizing.
  * Sortino numerator is `mean(r) − MAR`, denominator is downside
    deviation `sqrt(mean(min(r-MAR, 0)²))`, not the std of negative
    returns.
  * Calmar is None when there's <0.25 years (~3 months) of equity, so a
    1-day backtest doesn't fabricate a million-percent CAGR.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from showme.engine.services.backtest_framework import Backtest


def _make_bars(returns: list[float]) -> pd.DataFrame:
    """Build a bars frame with `close` such that pct_change gives `returns`."""
    closes = [100.0]
    for r in returns:
        closes.append(closes[-1] * (1.0 + r))
    idx = pd.date_range("2024-01-01", periods=len(closes), freq="B")
    return pd.DataFrame({"close": closes}, index=idx)


def _flat_strategy(bars, state):
    return 0


def test_sharpe_subtracts_risk_free_before_annualizing():
    np.random.seed(0)
    returns = np.random.normal(0.0005, 0.01, 252).tolist()
    bars = _make_bars(returns)
    bt_zero = Backtest(bars, strategy=lambda b, s: 1, warmup=1, risk_free=0.0).run()
    bt_high = Backtest(bars, strategy=lambda b, s: 1, warmup=1, risk_free=0.05).run()
    # Higher rf must reduce Sharpe (otherwise the rf isn't being subtracted).
    assert bt_high.metrics["sharpe"] < bt_zero.metrics["sharpe"]


def test_sortino_formula_uses_downside_deviation():
    """Construct a series with known downside deviation and verify the
    annualized Sortino matches the formula."""
    # 3 negatives at −1%, rest zero.
    returns = [-0.01, 0.0, 0.0, -0.01, 0.0, 0.0, -0.01, 0.0, 0.0, 0.0]
    bars = _make_bars(returns * 26)  # 260 bars → ~1 yr
    bt = Backtest(bars, strategy=lambda b, s: 1, warmup=1, mar=0.0).run()
    eq = bt.equity_curve
    r = eq.pct_change().dropna()
    excess = r - 0.0
    downside_dev = math.sqrt(float((np.minimum(excess, 0.0) ** 2).mean()))
    expected_sortino = float(r.mean() / downside_dev) * math.sqrt(252)
    assert abs(bt.metrics["sortino"] - expected_sortino) < 1e-6


def test_calmar_is_none_for_one_day_backtest():
    bars = _make_bars([0.01])  # 2 bars
    bt = Backtest(bars, strategy=lambda b, s: 1, warmup=0).run()
    assert bt.metrics["calmar"] is None
    assert bt.metrics["cagr"] is None


def test_calmar_present_when_sufficient_history():
    # ~1 year of equity → calmar computable
    returns = [0.001] * 252
    bars = _make_bars(returns)
    bt = Backtest(bars, strategy=lambda b, s: 1, warmup=0).run()
    assert bt.metrics["calmar"] is not None
    assert bt.metrics["cagr"] is not None
