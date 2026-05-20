"""SMA Cross v2 — fresh-cross only + divergence-based fallback (per ShowMe audit E.5).

Old logic emitted BUY/SELL on every cycle as long as short>long, polluting
consensus. v2 emits:
  STRONG_BUY/SELL : fresh cross with strong divergence
  BUY/SELL        : fresh cross OR cross-less but divergence > strong_pct
  WEAK BUY/SELL   : cross-less, weak < divergence < strong (signal_strength=0.5)
  NEUTRAL         : cross-less and |divergence| < weak_pct
"""

from __future__ import annotations

import pandas as pd

from showme.engine.indicators.base import BaseIndicator, IndicatorResult, Signal


class SMACrossIndicator(BaseIndicator):
    @property
    def name(self) -> str:
        return "sma_cross"

    def calculate(self, df: pd.DataFrame) -> IndicatorResult:
        short_period = self.thresholds.get("short_period", 10)
        long_period = self.thresholds.get("long_period", 50)
        strong_divergence_pct = self.thresholds.get("strong_divergence_pct", 0.02)
        weak_divergence_pct = self.thresholds.get("weak_divergence_pct", 0.005)

        close = df["close"]
        sma_short = close.rolling(window=short_period).mean()
        sma_long = close.rolling(window=long_period).mean()

        if len(sma_short) < 2 or len(sma_long) < 2:
            return self._make_result(Signal.NEUTRAL, "SMA data insufficient")

        current_short = sma_short.iloc[-1]
        current_long = sma_long.iloc[-1]
        prev_short = sma_short.iloc[-2]
        prev_long = sma_long.iloc[-2]

        if pd.isna(current_short) or pd.isna(current_long):
            return self._make_result(Signal.NEUTRAL, "SMA data insufficient")

        divergence = (current_short - current_long) / current_long if current_long != 0 else 0
        abs_div = abs(divergence)

        bullish_cross = prev_short <= prev_long and current_short > current_long
        bearish_cross = prev_short >= prev_long and current_short < current_long

        raw = {
            "sma_short": round(float(current_short), 6),
            "sma_long": round(float(current_long), 6),
            "divergence_pct": round(float(divergence), 5),
            "fresh_cross": bullish_cross or bearish_cross,
            "signal_strength": 1.0,
        }

        # Fresh cross
        if bullish_cross:
            if abs_div > strong_divergence_pct:
                return self._make_result(Signal.STRONG_BUY, "SMA golden cross (strong)", raw)
            return self._make_result(Signal.BUY, "SMA golden cross", raw)
        if bearish_cross:
            if abs_div > strong_divergence_pct:
                return self._make_result(Signal.STRONG_SELL, "SMA death cross (strong)", raw)
            return self._make_result(Signal.SELL, "SMA death cross", raw)

        # No cross — check divergence magnitude
        if abs_div < weak_divergence_pct:
            return self._make_result(
                Signal.NEUTRAL,
                f"SMA flat / converging (div={divergence:.5f} < {weak_divergence_pct})",
                raw,
            )

        if divergence > strong_divergence_pct:
            return self._make_result(
                Signal.BUY, f"SMA bullish, strong divergence={divergence:.4f}", raw
            )
        if divergence < -strong_divergence_pct:
            return self._make_result(
                Signal.SELL, f"SMA bearish, strong divergence={divergence:.4f}", raw
            )

        # Weak zone — emit lighter signal flagged via raw_values["signal_strength"]
        raw["signal_strength"] = 0.5
        if divergence > 0:
            return self._make_result(
                Signal.BUY,
                f"SMA bullish (weak div={divergence:.4f}, strength=0.5)",
                raw,
            )
        return self._make_result(
            Signal.SELL,
            f"SMA bearish (weak div={divergence:.4f}, strength=0.5)",
            raw,
        )
