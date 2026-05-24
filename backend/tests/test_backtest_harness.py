"""Q4 audit C7: bar-by-bar backtest harness.

Validates:
1. Winning trend-following strategy produces positive PnL.
2. Losing strategy (entry on cliff) produces negative PnL.
3. SL gets hit when the bar's low crosses the stop.
4. TP gets hit when the bar's high crosses the take.
5. Equity curve compounds running equity (not flat 10k).
6. Sharpe / profit_factor / max_drawdown metrics populated.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from showme.strategies.backtest import backtest
from showme.strategies.spec import (
    IndicatorRef,
    Position,
    Rule,
    StrategySpec,
)


def _df_oscillating_uptrend(n: int = 300) -> pd.DataFrame:
    """Oscillating but net-upward price action — produces multiple EMA crosses."""
    idx = pd.date_range("2026-01-01", periods=n, freq="h")
    rng = np.random.default_rng(42)
    trend = np.linspace(100.0, 130.0, n)
    noise = rng.normal(0, 2.5, n)
    closes = trend + noise
    # Make sure closes are positive.
    closes = np.maximum(closes, 50.0)
    return pd.DataFrame({
        "open": closes,
        "high": closes + 1.0,
        "low": closes - 1.0,
        "close": closes,
        "volume": [1000.0] * n,
    }, index=idx)


def _df_downtrend(n: int = 200) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=n, freq="h")
    closes = np.linspace(200.0, 100.0, n)
    return pd.DataFrame({
        "open": closes + 0.1,
        "high": closes + 0.5,
        "low": closes - 0.5,
        "close": closes,
        "volume": [1000.0] * n,
    }, index=idx)


def _ema_crossover_spec(fast=5, slow=20) -> StrategySpec:
    return StrategySpec(
        name="ema_cross",
        indicators=[
            IndicatorRef(alias="ema_fast", id="ema", params={"period": fast}),
            IndicatorRef(alias="ema_slow", id="ema", params={"period": slow}),
        ],
        entry_rules=[Rule(kind="crosses_above", left="ema_fast", right="ema_slow")],
        exit_rules=[Rule(kind="crosses_below", left="ema_fast", right="ema_slow")],
        position=Position(side="long", sizing_kind="fixed_quote", sizing_value=100.0),
    )


def test_winning_uptrend_strategy_produces_positive_pnl():
    # Use a buy-and-hold style strat over a strong uptrend so positive PnL
    # is reliable (EMA cross in noisy markets is too sensitive to lose).
    n = 200
    idx = pd.date_range("2026-01-01", periods=n, freq="h")
    closes = np.linspace(100.0, 150.0, n)
    df = pd.DataFrame({
        "open": closes,
        "high": closes + 0.5,
        "low": closes - 0.5,
        "close": closes,
        "volume": [1000.0] * n,
    }, index=idx)
    spec = StrategySpec(
        name="buy_hold_simple",
        entry_rules=[Rule(kind="greater_than", left="close", right="literal:100")],
        exit_rules=[Rule(kind="less_than", left="close", right="literal:0")],
        position=Position(side="long", sizing_kind="fixed_quote", sizing_value=100.0),
    )
    result = backtest(spec, df, warmup_bars=5, starting_equity=10_000.0,
                      fee_rate=0.0)
    assert len(result.trades) >= 1
    # Strong uptrend → positive net PnL.
    assert result.metrics["net_pnl"] > 0
    assert result.metrics["final_equity"] > 10_000.0


def test_losing_strategy_produces_negative_pnl():
    df = _df_downtrend()
    # Long entry on rising fast EMA in a downtrend will hardly fire; let's
    # construct a deliberately-losing strat: enter when close > 150, exit when < 150.
    # In a steady downtrend from 200→100, the position opens early and
    # bleeds the whole way down.
    spec = StrategySpec(
        name="cliff_jumper",
        entry_rules=[Rule(kind="greater_than", left="close", right="literal:180")],
        exit_rules=[Rule(kind="less_than", left="close", right="literal:120")],
        position=Position(side="long", sizing_kind="fixed_quote", sizing_value=100.0),
    )
    result = backtest(spec, df, warmup_bars=5, starting_equity=10_000.0)
    assert len(result.trades) >= 1
    assert result.metrics["net_pnl"] < 0


def test_sl_hit_records_sl_exit_reason():
    # Bar 9: close=101 → entry signal. Bar 10: fills at open=101. Bar 11:
    # low=94 → triggers SL (entry=101, SL=5% → 95.95; bar low 94 < 95.95).
    n = 20
    idx = pd.date_range("2026-01-01", periods=n, freq="h")
    closes = [99.0] * 9 + [101.0, 101.0] + [95.0] * (n - 11)
    opens = list(closes)
    highs = [c + 0.5 for c in closes]
    lows = [c - 0.5 for c in closes]
    lows[11] = 94.0  # SL trigger on the bar AFTER fill
    df = pd.DataFrame({
        "open": opens, "high": highs, "low": lows, "close": closes,
        "volume": [1000.0] * n,
    }, index=idx)
    spec = StrategySpec(
        name="sl_test",
        entry_rules=[Rule(kind="greater_than", left="close", right="literal:100")],
        exit_rules=[Rule(kind="less_than", left="close", right="literal:0")],
        position=Position(
            side="long", sizing_kind="fixed_quote", sizing_value=100.0,
            stop_loss_pct=5.0,
        ),
    )
    result = backtest(spec, df, warmup_bars=5, starting_equity=10_000.0,
                      fee_rate=0.0)
    sl_trades = [t for t in result.trades if t.exit_reason == "sl_hit"]
    assert len(sl_trades) >= 1
    # entry_fill = 101 (bar 10 open). SL = 101 * 0.95 = 95.95.
    assert sl_trades[0].exit_price == pytest.approx(95.95, rel=0.01)


def test_tp_hit_records_tp_exit_reason():
    # Bar 9: entry signal (close=101). Bar 10: fill at open=101. Bar 11:
    # high=108 → TP triggers (entry=101, TP=5% → 106.05; bar high 108 > 106.05).
    n = 20
    idx = pd.date_range("2026-01-01", periods=n, freq="h")
    closes = [99.0] * 9 + [101.0, 101.0] + [108.0] * (n - 11)
    opens = list(closes)
    highs = [c + 0.5 for c in closes]
    lows = [c - 0.5 for c in closes]
    highs[11] = 108.0  # TP trigger on the bar AFTER fill
    df = pd.DataFrame({
        "open": opens, "high": highs, "low": lows, "close": closes,
        "volume": [1000.0] * n,
    }, index=idx)
    spec = StrategySpec(
        name="tp_test",
        entry_rules=[Rule(kind="greater_than", left="close", right="literal:100")],
        exit_rules=[Rule(kind="less_than", left="close", right="literal:0")],
        position=Position(
            side="long", sizing_kind="fixed_quote", sizing_value=100.0,
            take_profit_pct=5.0,
        ),
    )
    result = backtest(spec, df, warmup_bars=5, starting_equity=10_000.0,
                      fee_rate=0.0)
    tp_trades = [t for t in result.trades if t.exit_reason == "tp_hit"]
    assert len(tp_trades) >= 1


def test_equity_curve_compounds_running_equity():
    # Strong uptrend buy-and-hold: one trade, positive PnL.
    n = 200
    idx = pd.date_range("2026-01-01", periods=n, freq="h")
    closes = np.linspace(100.0, 150.0, n)
    df = pd.DataFrame({
        "open": closes, "high": closes + 0.5,
        "low": closes - 0.5, "close": closes,
        "volume": [1000.0] * n,
    }, index=idx)
    spec = StrategySpec(
        name="bh_curve",
        entry_rules=[Rule(kind="greater_than", left="close", right="literal:100")],
        exit_rules=[Rule(kind="less_than", left="close", right="literal:0")],
        position=Position(side="long", sizing_kind="fixed_quote", sizing_value=100.0),
    )
    result = backtest(spec, df, warmup_bars=5, starting_equity=10_000.0,
                      fee_rate=0.0)
    eq = result.equity_curve
    assert eq[0]["equity"] == pytest.approx(10_000.0)
    assert eq[-1]["equity"] == pytest.approx(result.metrics["final_equity"])
    assert eq[-1]["equity"] > 10_000.0


def test_metrics_include_sharpe_profit_factor_max_dd():
    df = _df_oscillating_uptrend()
    spec = _ema_crossover_spec()
    result = backtest(spec, df, warmup_bars=30, starting_equity=10_000.0,
                      fee_rate=0.0)
    m = result.metrics
    assert "sharpe" in m
    assert "sortino" in m
    assert "profit_factor" in m
    assert "max_drawdown" in m
    assert "max_consecutive_losses" in m
    assert "expectancy" in m
    assert m["trade_count"] >= 1


def test_commission_deducted_from_net_pnl():
    df = _df_oscillating_uptrend(n=300)
    spec = _ema_crossover_spec()
    no_fee = backtest(spec, df, warmup_bars=30, starting_equity=10_000.0,
                      fee_rate=0.0)
    with_fee = backtest(spec, df, warmup_bars=30, starting_equity=10_000.0,
                        fee_rate=0.001)
    # With fees, net_pnl strictly lower (or equal if zero trades).
    if no_fee.metrics["trade_count"] > 0:
        assert with_fee.metrics["net_pnl"] < no_fee.metrics["net_pnl"]


def test_empty_dataframe_returns_zero_metrics():
    spec = _ema_crossover_spec()
    df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    result = backtest(spec, df, warmup_bars=30, starting_equity=10_000.0)
    assert result.trades == []
    assert result.metrics["trade_count"] == 0
