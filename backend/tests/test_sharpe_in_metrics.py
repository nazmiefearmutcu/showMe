"""Q4 audit H20: Sharpe / Sortino / profit_factor / max_consecutive_losses
on ``compute_metrics``.

Before this fix, the PERF leaderboard only carried total_pnl / win_rate /
max_drawdown — so a strategy with a 90% win rate but a single 50R loss
looked indistinguishable from a steady-eddie.
"""
from __future__ import annotations


import pytest

from showme.bots.performance import Trade, compute_metrics


def _t(pnl: float, net: float | None = None) -> Trade:
    return Trade(
        entry_time="t0", exit_time="t1",
        entry_price=100.0, exit_price=110.0,
        qty=1.0, pnl=pnl, pnl_pct=10.0,
        net_pnl=net if net is not None else pnl,
        side="long",
    )


def test_empty_returns_zero_for_all_new_fields():
    m = compute_metrics([])
    for key in ("sharpe", "sortino", "profit_factor", "expectancy",
                "max_consecutive_losses", "net_pnl"):
        assert key in m
    assert m["sharpe"] == 0.0
    assert m["sortino"] == 0.0
    assert m["profit_factor"] == 0.0
    assert m["max_consecutive_losses"] == 0


def test_profit_factor_computed():
    # Wins: 10, 20. Losses: -5, -3. PF = 30/8 = 3.75
    trades = [_t(10), _t(20), _t(-5), _t(-3)]
    m = compute_metrics(trades)
    assert m["profit_factor"] == pytest.approx(3.75)


def test_profit_factor_inf_when_no_losses():
    trades = [_t(10), _t(20)]
    m = compute_metrics(trades)
    # +inf JSON-safe sentinel.
    assert m["profit_factor"] == "inf"


def test_max_consecutive_losses():
    # Wins (W) and losses (L) sequence: L L W L L L W L → max 3.
    pnls = [-1, -2, 3, -4, -5, -6, 7, -8]
    trades = [_t(p) for p in pnls]
    m = compute_metrics(trades)
    assert m["max_consecutive_losses"] == 3


def test_sharpe_nonzero_on_winning_trades():
    trades = [_t(10), _t(15), _t(20), _t(12)]
    m = compute_metrics(trades)
    # All winners, std > 0 → Sharpe > 0.
    assert isinstance(m["sharpe"], float)
    assert m["sharpe"] > 0


def test_expectancy_negative_when_avg_loss_dominates():
    # 50% win rate, but avg loss > avg win.
    trades = [_t(10), _t(-100), _t(10), _t(-100)]
    m = compute_metrics(trades)
    # Expectancy = 10*0.5 - 100*0.5 = -45
    assert m["expectancy"] == pytest.approx(-45.0)


def test_net_pnl_used_when_present():
    # Gross pnl = 10, commission/funding eats 2 → net = 8.
    trades = [_t(10, net=8)]
    m = compute_metrics(trades)
    assert m["total_pnl"] == 10.0
    assert m["net_pnl"] == 8.0


def test_single_trade_returns_zero_sharpe():
    # Single trade → std undefined → Sharpe 0.
    trades = [_t(10)]
    m = compute_metrics(trades)
    assert m["sharpe"] == 0.0
