"""Challenger tests for sizing validation, trade PnL calculations, and Bollinger Bands std_dev/drift."""
from __future__ import annotations

import math
import numpy as np
import pandas as pd
import pytest

from showme.strategies.sizing import (
    resolve_quantity,
    compute_pnl,
    compute_pnl_pct,
    compute_commission,
)
from showme.bots.performance import compute_trades
from showme.bots.record import SignalEntry
from showme.engine.indicators.bollinger import BollingerBandsIndicator
from showme.strategies.compute import compute
from showme.strategies.spec import IndicatorRef


# ─────────────────────────────────────────────────────────────────────────────
# 1. Sizing Validation Boundary Values
# ─────────────────────────────────────────────────────────────────────────────

class TestSizingValidationChallenger:
    def test_sizing_value_non_positive_rejected(self):
        # Test zero and negative sizing_value for all kinds
        for kind in ["fixed_quote", "fixed_base", "risk_pct", "risk_per_trade"]:
            for bad_val in [0.0, -0.01, -100.0]:
                with pytest.raises(ValueError, match="sizing_value"):
                    resolve_quantity(
                        sizing_kind=kind,  # type: ignore[arg-type]
                        sizing_value=bad_val,
                        price=100.0,
                        equity=10_000.0,
                        stop_loss_pct=2.0 if kind == "risk_per_trade" else None,
                    )

    def test_risk_pct_boundaries(self):
        # 0.01% is valid
        qty_min = resolve_quantity(
            sizing_kind="risk_pct",
            sizing_value=0.01,
            price=100.0,
            equity=10_000.0,
        )
        assert qty_min == pytest.approx(0.01)  # (0.01 / 100) * 10,000 / 100 = 0.01

        # 100.0% is valid
        qty_max = resolve_quantity(
            sizing_kind="risk_pct",
            sizing_value=100.0,
            price=100.0,
            equity=10_000.0,
        )
        assert qty_max == pytest.approx(100.0)  # (100 / 100) * 10,000 / 100 = 100

        # 100.01% is rejected
        with pytest.raises(ValueError, match="risk_pct sizing_value must be in"):
            resolve_quantity(
                sizing_kind="risk_pct",
                sizing_value=100.01,
                price=100.0,
                equity=10_000.0,
            )

        # Negative numbers are rejected
        with pytest.raises(ValueError, match="sizing_value"):
            resolve_quantity(
                sizing_kind="risk_pct",
                sizing_value=-0.01,
                price=100.0,
                equity=10_000.0,
            )

    def test_risk_per_trade_boundaries(self):
        # 0.01% risk is valid
        qty_min = resolve_quantity(
            sizing_kind="risk_per_trade",
            sizing_value=0.01,
            price=100.0,
            equity=10_000.0,
            stop_loss_pct=1.0,
        )
        assert qty_min == pytest.approx(1.0)  # (0.01 / 100) * 10,000 / (100 * 1/100) = 1.0

        # 100.0% risk is valid (with leverage=100.0 to prevent clamping)
        qty_max = resolve_quantity(
            sizing_kind="risk_per_trade",
            sizing_value=100.0,
            price=100.0,
            equity=10_000.0,
            stop_loss_pct=1.0,
            leverage=100.0,
        )
        assert qty_max == pytest.approx(10000.0)  # (100 / 100) * 10,000 / 1.0 = 10,000

        # 100.01% risk is rejected
        with pytest.raises(ValueError, match="risk_per_trade sizing_value must be in"):
            resolve_quantity(
                sizing_kind="risk_per_trade",
                sizing_value=100.01,
                price=100.0,
                equity=10_000.0,
                stop_loss_pct=1.0,
            )

        # Negative risk is rejected
        with pytest.raises(ValueError, match="sizing_value"):
            resolve_quantity(
                sizing_kind="risk_per_trade",
                sizing_value=-0.01,
                price=100.0,
                equity=10_000.0,
                stop_loss_pct=1.0,
            )

        # stop_loss_pct boundary checks
        # stop_loss_pct <= 0 rejected
        for bad_sl in [0.0, -1.0]:
            with pytest.raises(ValueError, match="stop_loss_pct"):
                resolve_quantity(
                    sizing_kind="risk_per_trade",
                    sizing_value=2.0,
                    price=100.0,
                    equity=10_000.0,
                    stop_loss_pct=bad_sl,
                )

        # stop_loss_pct > 100 rejected
        with pytest.raises(ValueError, match="stop_loss_pct must be in"):
            resolve_quantity(
                sizing_kind="risk_per_trade",
                sizing_value=2.0,
                price=100.0,
                equity=10_000.0,
                stop_loss_pct=100.01,
            )

        # stop_loss_pct == 100 is valid
        qty_sl_100 = resolve_quantity(
            sizing_kind="risk_per_trade",
            sizing_value=2.0,
            price=100.0,
            equity=10_000.0,
            stop_loss_pct=100.0,
        )
        # risk_amount = 200. stop_distance = 100. qty = 2.0
        assert qty_sl_100 == pytest.approx(2.0)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Trade PnL under all sizing kind + side combinations
# ─────────────────────────────────────────────────────────────────────────────

class TestTradePnLChallenger:
    def _sig(self, kind: str, price: float, action: str = "shadow") -> SignalEntry:
        return SignalEntry(
            bar_index=0, bar_time="2026-06-20T10:00:00Z", kind=kind, price=price,
            action=action, timestamp="2026-06-20T10:00:00Z",
        )

    def test_compute_trades_fixed_base(self):
        # 1. Long Profit
        log_long_profit = [self._sig("entry", 100.0), self._sig("exit", 110.0)]
        trades = compute_trades(log_long_profit, sizing_value=2.5, sizing_kind="fixed_base", side="long")
        assert len(trades) == 1
        assert trades[0].qty == 2.5
        assert trades[0].pnl == pytest.approx(25.0)  # (110 - 100) * 2.5
        assert trades[0].pnl_pct == pytest.approx(10.0)

        # 2. Long Loss
        log_long_loss = [self._sig("entry", 100.0), self._sig("exit", 90.0)]
        trades = compute_trades(log_long_loss, sizing_value=2.5, sizing_kind="fixed_base", side="long")
        assert len(trades) == 1
        assert trades[0].pnl == pytest.approx(-25.0)  # (90 - 100) * 2.5
        assert trades[0].pnl_pct == pytest.approx(-10.0)

        # 3. Short Profit
        log_short_profit = [self._sig("entry", 100.0), self._sig("exit", 90.0)]
        trades = compute_trades(log_short_profit, sizing_value=2.5, sizing_kind="fixed_base", side="short")
        assert len(trades) == 1
        assert trades[0].pnl == pytest.approx(25.0)  # (100 - 90) * 2.5
        assert trades[0].pnl_pct == pytest.approx(10.0)

        # 4. Short Loss
        log_short_loss = [self._sig("entry", 100.0), self._sig("exit", 110.0)]
        trades = compute_trades(log_short_loss, sizing_value=2.5, sizing_kind="fixed_base", side="short")
        assert len(trades) == 1
        assert trades[0].pnl == pytest.approx(-25.0)  # (100 - 110) * 2.5
        assert trades[0].pnl_pct == pytest.approx(-10.0)

    def test_compute_trades_fixed_quote(self):
        # Long Profit
        log_long_profit = [self._sig("entry", 100.0), self._sig("exit", 110.0)]
        trades = compute_trades(log_long_profit, sizing_value=500.0, sizing_kind="fixed_quote", side="long")
        assert len(trades) == 1
        assert trades[0].qty == pytest.approx(5.0)  # 500 / 100
        assert trades[0].pnl == pytest.approx(50.0)  # (110 - 100) * 5
        assert trades[0].pnl_pct == pytest.approx(10.0)

        # Short Profit
        log_short_profit = [self._sig("entry", 100.0), self._sig("exit", 90.0)]
        trades = compute_trades(log_short_profit, sizing_value=500.0, sizing_kind="fixed_quote", side="short")
        assert len(trades) == 1
        assert trades[0].qty == pytest.approx(5.0)
        assert trades[0].pnl == pytest.approx(50.0)  # (100 - 90) * 5
        assert trades[0].pnl_pct == pytest.approx(10.0)

    def test_compute_trades_risk_pct(self):
        # Long Profit (5% of 10k equity = 500 budget. With leverage=4.0, budget=2000. Qty = 2000/100 = 20)
        log_long_profit = [self._sig("entry", 100.0), self._sig("exit", 110.0)]
        trades = compute_trades(
            log_long_profit,
            sizing_value=5.0,
            sizing_kind="risk_pct",
            side="long",
            equity=10_000.0,
            leverage=4.0,
        )
        assert len(trades) == 1
        assert trades[0].qty == pytest.approx(20.0)
        assert trades[0].pnl == pytest.approx(200.0)  # (110 - 100) * 20
        assert trades[0].pnl_pct == pytest.approx(10.0)

        # Short Profit (5% of 10k equity = 500 budget. With leverage=2.0, budget=1000. Qty = 1000/100 = 10)
        log_short_profit = [self._sig("entry", 100.0), self._sig("exit", 90.0)]
        trades = compute_trades(
            log_short_profit,
            sizing_value=5.0,
            sizing_kind="risk_pct",
            side="short",
            equity=10_000.0,
            leverage=2.0,
        )
        assert len(trades) == 1
        assert trades[0].qty == pytest.approx(10.0)
        assert trades[0].pnl == pytest.approx(100.0)  # (100 - 90) * 10
        assert trades[0].pnl_pct == pytest.approx(10.0)

    def test_compute_trades_risk_per_trade(self):
        # Long Profit (2% risk of 10k = 200. SL = 1% on 100 entry -> stop distance = 1.0. qty = 200. leverage=10.0)
        log_long_profit = [self._sig("entry", 100.0), self._sig("exit", 110.0)]
        trades = compute_trades(
            log_long_profit,
            sizing_value=2.0,
            sizing_kind="risk_per_trade",
            side="long",
            equity=10_000.0,
            stop_loss_pct=1.0,
            leverage=10.0,
        )
        assert len(trades) == 1
        assert trades[0].qty == pytest.approx(200.0)
        assert trades[0].pnl == pytest.approx(2000.0)  # (110 - 100) * 200
        assert trades[0].pnl_pct == pytest.approx(10.0)

        # Clamped Long Profit (leverage=1.0 caps notional at 10k -> max qty = 100)
        trades_clamped = compute_trades(
            log_long_profit,
            sizing_value=2.0,
            sizing_kind="risk_per_trade",
            side="long",
            equity=10_000.0,
            stop_loss_pct=1.0,
            leverage=1.0,
        )
        assert len(trades_clamped) == 1
        assert trades_clamped[0].qty == pytest.approx(100.0)
        assert trades_clamped[0].pnl == pytest.approx(1000.0)  # (110 - 100) * 100
        assert trades_clamped[0].pnl_pct == pytest.approx(10.0)

        # Short Profit (2% risk of 10k = 200. SL = 2% on 100 entry -> stop distance = 2.0. qty = 100. leverage=5.0)
        log_short_profit = [self._sig("entry", 100.0), self._sig("exit", 90.0)]
        trades_short = compute_trades(
            log_short_profit,
            sizing_value=2.0,
            sizing_kind="risk_per_trade",
            side="short",
            equity=10_000.0,
            stop_loss_pct=2.0,
            leverage=5.0,
        )
        assert len(trades_short) == 1
        assert trades_short[0].qty == pytest.approx(100.0)
        assert trades_short[0].pnl == pytest.approx(1000.0)  # (100 - 90) * 100
        assert trades_short[0].pnl_pct == pytest.approx(10.0)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Bollinger Bands (std_dev parameter and no signal drift)
# ─────────────────────────────────────────────────────────────────────────────

class TestBollingerBandsChallenger:
    @pytest.fixture
    def mock_df(self) -> pd.DataFrame:
        rng = np.random.default_rng(seed=123)
        n = 50
        close = 100.0 + np.cumsum(rng.normal(0, 1.5, n))
        high = close + np.abs(rng.normal(0, 0.5, n))
        low = close - np.abs(rng.normal(0, 0.5, n))
        volume = (1000 + rng.normal(0, 200, n)).clip(min=1)
        return pd.DataFrame({
            "open": close, "high": high, "low": low,
            "close": close, "volume": volume,
        }, index=pd.date_range("2026-01-01", periods=n, freq="h"))

    def test_bollinger_bands_std_dev_parameter_effects(self, mock_df):
        # Verify that passing different std_dev values correctly scales the bands
        period = 20
        sma = mock_df["close"].rolling(period).mean()
        sample_std = mock_df["close"].rolling(period).std(ddof=1)

        for std_dev in [1.5, 2.0, 2.5]:
            out = compute(mock_df, [
                IndicatorRef(alias="bbu", id="bollinger_upper", params={"period": period, "std_dev": std_dev}),
                IndicatorRef(alias="bbl", id="bollinger_lower", params={"period": period, "std_dev": std_dev}),
            ])
            expected_upper = sma + std_dev * sample_std
            expected_lower = sma - std_dev * sample_std

            pd.testing.assert_series_equal(
                out["bbu"].dropna().rename("x"), expected_upper.dropna().rename("x")
            )
            pd.testing.assert_series_equal(
                out["bbl"].dropna().rename("x"), expected_lower.dropna().rename("x")
            )

    def test_bollinger_bands_no_signal_drift(self, mock_df):
        # Assert that both compute and engine paths agree on custom std_dev
        period, std_dev = 20, 2.5
        out = compute(mock_df, [
            IndicatorRef(alias="bbu", id="bollinger_upper", params={"period": period, "std_dev": std_dev}),
            IndicatorRef(alias="bbl", id="bollinger_lower", params={"period": period, "std_dev": std_dev}),
        ])

        engine = BollingerBandsIndicator(config={
            "indicator_thresholds": {
                "bollinger": {
                    "period": period, "std_dev": std_dev,
                    "adx_period": 14, "adx_trend_floor": 20,
                    "high_volume_multiplier": 1.5, "squeeze_threshold": 0.02
                },
            },
        })
        result = engine.calculate(mock_df)
        raw = result.raw_values or {}

        # Compute's last-bar BBU/BBL must match engine's reported upper/lower precisely (no drift)
        assert out["bbu"].iloc[-1] == pytest.approx(raw["upper"], rel=1e-6)
        assert out["bbl"].iloc[-1] == pytest.approx(raw["lower"], rel=1e-6)

        # Confirm it is different from population std (ddof=0)
        pop_std = mock_df["close"].rolling(period).std(ddof=0)
        pop_upper = sma = mock_df["close"].rolling(period).mean() + std_dev * pop_std
        assert out["bbu"].dropna().iloc[-1] != pytest.approx(pop_upper.iloc[-1], rel=1e-6)
