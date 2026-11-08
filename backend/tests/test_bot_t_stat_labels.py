"""Bot risk metrics must not label a per-trade t-statistic as an annualized Sharpe.

Regression for XCON-8: bots/performance.py computed mean(pnl)/std(pnl)*sqrt(n),
where n is the trade count, and exposed it under 'sharpe' (and the Sortino
analogue under 'sortino'). That value grows with the number of trades for a
fixed edge, so it is not comparable with the annualized engine Sharpe.
"""

from __future__ import annotations

import math

import pytest

from showme.bots.performance import Trade, compute_metrics


def _trade(net: float) -> Trade:
    return Trade(
        entry_time="2026-01-01T00:00:00Z",
        exit_time="2026-01-02T00:00:00Z",
        entry_price=100.0,
        exit_price=100.0 + net,
        qty=1.0,
        pnl=net,
        pnl_pct=net / 100.0,
        net_pnl=net,
    )


def test_bot_metrics_do_not_report_t_stat_as_sharpe_or_sortino() -> None:
    m = compute_metrics([_trade(10.0), _trade(-4.0), _trade(6.0), _trade(-2.0)])
    assert "sharpe" not in m
    assert "sortino" not in m


def test_t_stat_per_trade_is_mean_over_std_times_sqrt_n() -> None:
    pnls = [10.0, -4.0, 6.0, -2.0]
    n = len(pnls)
    mean = sum(pnls) / n
    std = math.sqrt(sum((p - mean) ** 2 for p in pnls) / (n - 1))
    m = compute_metrics([_trade(p) for p in pnls])
    assert m["t_stat_per_trade"] == pytest.approx(mean / std * math.sqrt(n), rel=1e-6)


def test_t_stat_per_trade_grows_with_trade_count_for_same_edge() -> None:
    # Same per-trade distribution repeated 4x: a Sharpe-like ratio would stay
    # put, the per-trade t-statistic scales with sqrt(number of trades).
    base = [10.0, -4.0, 6.0, -2.0]
    small = compute_metrics([_trade(p) for p in base])["t_stat_per_trade"]
    large = compute_metrics([_trade(p) for p in base * 4])["t_stat_per_trade"]
    # Growth is the point: a Sharpe-like ratio would stay near the same value.
    assert large > small * 1.9


def test_empty_metrics_expose_t_stat_keys_not_sharpe() -> None:
    m = compute_metrics([])
    assert m["t_stat_per_trade"] == 0.0
    assert "sharpe" not in m
