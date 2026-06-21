"""Adversarial challenger tests for sizing validation, trade PnL calculations, and Bollinger Bands."""
from __future__ import annotations

import math
import numpy as np
import pandas as pd
import pytest

from showme.strategies.sizing import (
    resolve_quantity,
    compute_pnl,
    compute_pnl_pct,
)
from showme.bots.performance import compute_trades, SignalEntry
from showme.engine.indicators.bollinger import BollingerBandsIndicator
from showme.strategies.compute import compute
from showme.strategies.spec import IndicatorRef


# ==============================================================================
# SIZING VALIDATION BOUNDARY VALUE TESTS
# ==============================================================================

class TestSizingValidationBoundaries:
    """Stress tests boundary values for sizing validation (C-API-1 and related constraints)."""

    @pytest.mark.parametrize("sizing_kind", ["fixed_base", "fixed_quote", "risk_pct", "risk_per_trade"])
    @pytest.mark.parametrize("invalid_val", [0.0, -1.0, -0.0001, float("nan"), float("inf"), float("-inf")])
    def test_sizing_value_less_than_or_equal_to_zero_and_non_finite_rejected(self, sizing_kind, invalid_val):
        """Reject non-positive or non-finite sizing values for all sizing kinds."""
        with pytest.raises(ValueError, match="sizing_value"):
            resolve_quantity(
                sizing_kind=sizing_kind,
                sizing_value=invalid_val,
                price=100.0,
                equity=10_000.0,
                stop_loss_pct=1.0 if sizing_kind == "risk_per_trade" else None,
            )

    @pytest.mark.parametrize("sizing_kind", ["risk_pct", "risk_per_trade"])
    def test_percentage_sizing_upper_boundaries(self, sizing_kind):
        """Verify upper boundary limits (100 is allowed, 100.01 is rejected) for percentage-based kinds."""
        # 100% risk is allowed
        qty = resolve_quantity(
            sizing_kind=sizing_kind,
            sizing_value=100.0,
            price=100.0,
            equity=10_000.0,
            stop_loss_pct=1.0 if sizing_kind == "risk_per_trade" else None,
            leverage=1.0,
        )
        assert qty > 0

        # 100.01% risk is rejected
        with pytest.raises(ValueError, match=f"{sizing_kind} sizing_value must be in \\(0, 100\\]"):
            resolve_quantity(
                sizing_kind=sizing_kind,
                sizing_value=100.01,
                price=100.0,
                equity=10_000.0,
                stop_loss_pct=1.0 if sizing_kind == "risk_per_trade" else None,
            )

    @pytest.mark.parametrize("sizing_kind", ["risk_pct", "risk_per_trade"])
    def test_percentage_sizing_lower_boundaries(self, sizing_kind):
        """Verify lower boundary limits (0.01 is allowed, 0 is rejected) for percentage-based kinds."""
        # Very small risk percent is allowed
        qty = resolve_quantity(
            sizing_kind=sizing_kind,
            sizing_value=0.01,
            price=100.0,
            equity=10_000.0,
            stop_loss_pct=1.0 if sizing_kind == "risk_per_trade" else None,
            leverage=1.0,
        )
        assert qty > 0

        # Negative is rejected
        with pytest.raises(ValueError):
            resolve_quantity(
                sizing_kind=sizing_kind,
                sizing_value=-0.01,
                price=100.0,
                equity=10_000.0,
                stop_loss_pct=1.0 if sizing_kind == "risk_per_trade" else None,
            )


# ==============================================================================
# TRADE PNL & COMPUTE_TRADES PARITY TESTS
# ==============================================================================

class TestTradePnLCorrectness:
    """Verifies that compute_trades gets the correct PnL for all combinations of sizing kind and side."""

    def _make_signal_log(self, entry_price: float, exit_price: float) -> list[SignalEntry]:
        return [
            SignalEntry(bar_index=0, bar_time="t1", kind="entry", price=entry_price, action="shadow", timestamp="t1"),
            SignalEntry(bar_index=1, bar_time="t2", kind="exit", price=exit_price, action="shadow", timestamp="t2"),
        ]

    @pytest.mark.parametrize("side", ["long", "short"])
    def test_fixed_base_pnl(self, side):
        """fixed_base: qty = sizing_value. PnL = (exit - entry) * qty (long) or (entry - exit) * qty (short)."""
        log = self._make_signal_log(100.0, 110.0)
        trades = compute_trades(log, sizing_value=2.5, sizing_kind="fixed_base", side=side, equity=10_000.0)
        assert len(trades) == 1
        t = trades[0]
        assert t.qty == 2.5
        if side == "long":
            assert t.pnl == pytest.approx(25.0)
            assert t.pnl_pct == pytest.approx(10.0)
        else:
            assert t.pnl == pytest.approx(-25.0)
            assert t.pnl_pct == pytest.approx(-10.0)

    @pytest.mark.parametrize("side", ["long", "short"])
    def test_fixed_quote_pnl(self, side):
        """fixed_quote: qty = sizing_value / entry_price."""
        log = self._make_signal_log(100.0, 110.0)
        trades = compute_trades(log, sizing_value=250.0, sizing_kind="fixed_quote", side=side, equity=10_000.0)
        assert len(trades) == 1
        t = trades[0]
        assert t.qty == pytest.approx(2.5)
        if side == "long":
            assert t.pnl == pytest.approx(25.0)
            assert t.pnl_pct == pytest.approx(10.0)
        else:
            assert t.pnl == pytest.approx(-25.0)
            assert t.pnl_pct == pytest.approx(-10.0)

    @pytest.mark.parametrize("side", ["long", "short"])
    def test_risk_pct_pnl(self, side):
        """risk_pct: qty = (equity * sizing_value/100 * leverage) / entry_price."""
        log = self._make_signal_log(100.0, 110.0)
        # 5% risk of $10,000 equity with 4x leverage -> $2,000 notional budget -> 20 shares at $100 entry price.
        trades = compute_trades(
            log,
            sizing_value=5.0,
            sizing_kind="risk_pct",
            side=side,
            equity=10_000.0,
            leverage=4.0,
        )
        assert len(trades) == 1
        t = trades[0]
        assert t.qty == pytest.approx(20.0)
        if side == "long":
            assert t.pnl == pytest.approx(200.0)
            assert t.pnl_pct == pytest.approx(10.0)
        else:
            assert t.pnl == pytest.approx(-200.0)
            assert t.pnl_pct == pytest.approx(-10.0)

    @pytest.mark.parametrize("side", ["long", "short"])
    def test_risk_per_trade_pnl(self, side):
        """risk_per_trade: qty = (equity * sizing_value/100) / (entry_price * stop_loss_pct/100) (subject to leverage clamp)."""
        log = self._make_signal_log(100.0, 110.0)
        # 2% risk of $10k equity = $200 risk amount. SL pct is 1% -> stop distance price = $1.
        # Qty = $200 / $1 = 200 shares. Notional = 200 * $100 = $20k.
        # Leverage of 5x allows up to $50k notional. No clamping.
        trades = compute_trades(
            log,
            sizing_value=2.0,
            sizing_kind="risk_per_trade",
            side=side,
            equity=10_000.0,
            stop_loss_pct=1.0,
            leverage=5.0,
        )
        assert len(trades) == 1
        t = trades[0]
        assert t.qty == pytest.approx(200.0)
        if side == "long":
            assert t.pnl == pytest.approx(2000.0)
            assert t.pnl_pct == pytest.approx(10.0)
        else:
            assert t.pnl == pytest.approx(-2000.0)
            assert t.pnl_pct == pytest.approx(-10.0)

    @pytest.mark.parametrize("side", ["long", "short"])
    def test_risk_per_trade_leverage_clamping_pnl(self, side):
        """risk_per_trade with leverage clamping: qty * entry_price <= equity * leverage."""
        log = self._make_signal_log(100.0, 110.0)
        # 2% risk of $10k equity = $200 risk amount. SL pct is 0.1% -> stop distance price = $0.1.
        # Unclamped qty = $200 / $0.1 = 2000 shares (Notional = $200k).
        # Leverage is 1.0x -> max notional is $10k -> clamped qty = $10k / $100 = 100 shares.
        trades = compute_trades(
            log,
            sizing_value=2.0,
            sizing_kind="risk_per_trade",
            side=side,
            equity=10_000.0,
            stop_loss_pct=0.1,
            leverage=1.0,
        )
        assert len(trades) == 1
        t = trades[0]
        assert t.qty == pytest.approx(100.0)  # Clamped!
        if side == "long":
            assert t.pnl == pytest.approx(1000.0)
        else:
            assert t.pnl == pytest.approx(-1000.0)


# ==============================================================================
# BOLLINGER BANDS PARAMETERS & SIGNAL DRIFT TESTS
# ==============================================================================

class TestBollingerBandsChallenger:
    """Verifies Bollinger Bands behaviour when passing custom std_dev and checks for signal drift/leakage."""

    @pytest.fixture
    def sample_data(self) -> pd.DataFrame:
        np.random.seed(42)
        n = 100
        close = 100.0 + np.cumsum(np.random.normal(0, 1.0, n))
        high = close + np.abs(np.random.normal(0, 0.5, n))
        low = close - np.abs(np.random.normal(0, 0.5, n))
        volume = np.random.uniform(100, 1000, n)
        return pd.DataFrame({
            "open": close, "high": high, "low": low,
            "close": close, "volume": volume
        }, index=pd.date_range("2026-01-01", periods=n, freq="h"))

    def test_std_dev_parameter_propagates_correctly(self, sample_data):
        """Verify that passing different std_dev parameters scale the bands correctly in both paths."""
        period = 20
        # 1. Compute path
        out_2 = compute(sample_data, [
            IndicatorRef(alias="bbu_2", id="bollinger_upper", params={"period": period, "std_dev": 2.0}),
            IndicatorRef(alias="bbl_2", id="bollinger_lower", params={"period": period, "std_dev": 2.0}),
        ])
        out_3 = compute(sample_data, [
            IndicatorRef(alias="bbu_3", id="bollinger_upper", params={"period": period, "std_dev": 3.0}),
            IndicatorRef(alias="bbl_3", id="bollinger_lower", params={"period": period, "std_dev": 3.0}),
        ])

        sma = sample_data["close"].rolling(period).mean()
        std = sample_data["close"].rolling(period).std(ddof=1)

        # Assert correct scaling in compute path
        pd.testing.assert_series_equal(out_2["bbu_2"].dropna(), (sma + 2.0 * std).dropna(), check_names=False)
        pd.testing.assert_series_equal(out_3["bbu_3"].dropna(), (sma + 3.0 * std).dropna(), check_names=False)
        assert (out_3["bbu_3"].dropna() > out_2["bbu_2"].dropna()).all()

        # 2. Engine path
        engine_2 = BollingerBandsIndicator(config={
            "indicator_thresholds": {
                "bollinger": {"period": period, "std_dev": 2.0}
            }
        })
        engine_3 = BollingerBandsIndicator(config={
            "indicator_thresholds": {
                "bollinger": {"period": period, "std_dev": 3.0}
            }
        })

        res_2 = engine_2.calculate(sample_data)
        res_3 = engine_3.calculate(sample_data)

        raw_2 = res_2.raw_values
        raw_3 = res_3.raw_values

        assert raw_2["upper"] == pytest.approx(sma.iloc[-1] + 2.0 * std.iloc[-1], abs=1e-5)
        assert raw_3["upper"] == pytest.approx(sma.iloc[-1] + 3.0 * std.iloc[-1], abs=1e-5)
        assert raw_3["upper"] > raw_2["upper"]

    def test_no_lookahead_drift(self, sample_data):
        """Verify that there is no lookahead signal drift.

        Evaluating the indicator incrementally at bar i (using only data from 0..i)
        must yield the exact same values and signals at bar i as executing on the
        entire dataset and looking at index i.
        """
        period = 20
        std_dev = 2.0

        # We evaluate the indicators incrementally from index 30 to the end
        for i in range(30, len(sample_data)):
            subset_df = sample_data.iloc[:i+1]
            
            # 1. Compute path: verify last value of rolling calculation
            out_full = compute(sample_data, [
                IndicatorRef(alias="bbu", id="bollinger_upper", params={"period": period, "std_dev": std_dev}),
                IndicatorRef(alias="bbl", id="bollinger_lower", params={"period": period, "std_dev": std_dev}),
            ])
            out_incremental = compute(subset_df, [
                IndicatorRef(alias="bbu", id="bollinger_upper", params={"period": period, "std_dev": std_dev}),
                IndicatorRef(alias="bbl", id="bollinger_lower", params={"period": period, "std_dev": std_dev}),
            ])
            
            # Incremental end value must match full dataset value at index i
            assert out_incremental["bbu"].iloc[-1] == pytest.approx(out_full["bbu"].iloc[i], abs=1e-9)
            assert out_incremental["bbl"].iloc[-1] == pytest.approx(out_full["bbl"].iloc[i], abs=1e-9)

            # 2. Engine path: verify statelessness and causality
            engine = BollingerBandsIndicator(config={
                "indicator_thresholds": {
                    "bollinger": {"period": period, "std_dev": std_dev}
                }
            })
            res_incremental = engine.calculate(subset_df)
            raw_inc = res_incremental.raw_values

            # Verify that calculating it on the full dataset up to i matches
            res_full_i = engine.calculate(sample_data.iloc[:i+1])
            raw_full_i = res_full_i.raw_values

            assert raw_inc["upper"] == pytest.approx(raw_full_i["upper"])
            assert raw_inc["lower"] == pytest.approx(raw_full_i["lower"])
            assert res_incremental.signal == res_full_i.signal

    def test_indicator_statelessness(self, sample_data):
        """Verify that BollingerBandsIndicator does not carry over state between calculate() calls.

        If it carries state, consecutive calls on different DataFrames will bleed info.
        """
        period = 20
        std_dev = 2.0
        engine = BollingerBandsIndicator(config={
            "indicator_thresholds": {
                "bollinger": {"period": period, "std_dev": std_dev}
            }
        })

        # Calculate on one dataset
        res_a1 = engine.calculate(sample_data)

        # Calculate on a completely different dataset (shifted close)
        alt_data = sample_data.copy()
        alt_data["close"] = alt_data["close"] * 1.5
        alt_data["high"] = alt_data["high"] * 1.5
        alt_data["low"] = alt_data["low"] * 1.5
        
        res_b = engine.calculate(alt_data)

        # Calculate again on the original dataset
        res_a2 = engine.calculate(sample_data)

        # The results for the first and second run on sample_data must be identical
        assert res_a1.raw_values["upper"] == pytest.approx(res_a2.raw_values["upper"])
        assert res_a1.raw_values["lower"] == pytest.approx(res_a2.raw_values["lower"])
        assert res_a1.signal == res_a2.signal
