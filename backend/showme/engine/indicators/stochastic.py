"""Stochastic Oscillator indicator."""
from __future__ import annotations


import pandas as pd

from showme.engine.indicators.base import BaseIndicator, IndicatorResult, Signal


class StochasticIndicator(BaseIndicator):
    """Stochastic Oscillator with oversold/overbought reversal detection."""

    @property
    def name(self) -> str:
        return "stochastic"

    def calculate(self, df: pd.DataFrame) -> IndicatorResult:
        k_period = self.thresholds.get("k_period", 14)
        d_period = self.thresholds.get("d_period", 3)
        oversold = self.thresholds.get("oversold", 20)
        overbought = self.thresholds.get("overbought", 80)

        high = df["high"]
        low = df["low"]
        close = df["close"]

        lowest_low = low.rolling(window=k_period).min()
        highest_high = high.rolling(window=k_period).max()

        denom = highest_high - lowest_low
        denom = denom.replace(0, float("nan"))
        k_line = 100.0 * (close - lowest_low) / denom
        d_line = k_line.rolling(window=d_period).mean()

        current_k = k_line.iloc[-1]
        current_d = d_line.iloc[-1]
        prev_k = k_line.iloc[-2] if len(k_line) >= 2 else current_k
        # Q1 HIGH fix: ``prev_d`` was a dead expression — the assignment
        # target was missing, so the value was discarded. The %K-crosses-%D
        # detection below now uses the correctly captured ``prev_d``.
        prev_d = d_line.iloc[-2] if len(d_line) >= 2 else current_d

        if pd.isna(current_k) or pd.isna(current_d):
            return self._make_result(Signal.NEUTRAL, "Stochastic data insufficient")

        # %K crosses %D — classic Lane / Stochastic confirmation.
        bullish_cross = (
            not pd.isna(prev_k) and not pd.isna(prev_d)
            and prev_k <= prev_d and current_k > current_d
        )
        bearish_cross = (
            not pd.isna(prev_k) and not pd.isna(prev_d)
            and prev_k >= prev_d and current_k < current_d
        )

        raw = {
            "k": round(current_k, 2),
            "d": round(current_d, 2),
            "prev_k": round(float(prev_k), 2) if not pd.isna(prev_k) else None,
            "prev_d": round(float(prev_d), 2) if not pd.isna(prev_d) else None,
            "bullish_cross": bool(bullish_cross),
            "bearish_cross": bool(bearish_cross),
        }

        # Oversold reversal — bullish cross in oversold zone is the
        # textbook strong-buy.
        if prev_k < oversold and current_k > prev_k and current_k > current_d:
            if bullish_cross and current_k < oversold * 0.7:
                return self._make_result(
                    Signal.STRONG_BUY,
                    f"Stochastic deeply oversold %K crosses %D K={current_k:.1f}",
                    raw,
                )
            if current_k < oversold * 0.7:
                return self._make_result(Signal.STRONG_BUY, f"Stochastic deeply oversold reversal K={current_k:.1f}", raw)
            return self._make_result(Signal.BUY, f"Stochastic oversold reversal K={current_k:.1f}", raw)

        # Overbought reversal
        if prev_k > overbought and current_k < prev_k and current_k < current_d:
            if bearish_cross and current_k > overbought + (100 - overbought) * 0.3:
                return self._make_result(
                    Signal.STRONG_SELL,
                    f"Stochastic deeply overbought %K crosses %D K={current_k:.1f}",
                    raw,
                )
            if current_k > overbought + (100 - overbought) * 0.3:
                return self._make_result(Signal.STRONG_SELL, f"Stochastic deeply overbought reversal K={current_k:.1f}", raw)
            return self._make_result(Signal.SELL, f"Stochastic overbought reversal K={current_k:.1f}", raw)

        # Still in oversold zone trending up
        if current_k < oversold and current_k > prev_k:
            return self._make_result(Signal.BUY, f"Stochastic in oversold zone, turning up K={current_k:.1f}", raw)

        # Still in overbought zone trending down
        if current_k > overbought and current_k < prev_k:
            return self._make_result(Signal.SELL, f"Stochastic in overbought zone, turning down K={current_k:.1f}", raw)

        return self._make_result(Signal.NEUTRAL, f"Stochastic neutral K={current_k:.1f} D={current_d:.1f}", raw)
