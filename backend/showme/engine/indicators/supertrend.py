"""Supertrend indicator (per ShowMe audit D.1).

ATR-based trend follower. Less whipsaw than SMA/EMA cross in choppy markets.
Strategy:
  STRONG_BUY  : trend just flipped UP (fresh bullish flip)
  BUY         : trend UP, price ≥ 1×ATR above ST, ≥ confirmation_bars in UP
  NEUTRAL     : trend UP/DOWN but price within flip_buffer_atr × ATR of ST
  SELL        : trend DOWN, price ≥ 1×ATR below ST, ≥ confirmation_bars in DOWN
  STRONG_SELL : trend just flipped DOWN
"""

import pandas as pd
import numpy as np

from showme.engine.indicators.base import BaseIndicator, IndicatorResult, Signal
from showme.engine.indicators.adx_di import wilder_rma


class SupertrendIndicator(BaseIndicator):
    @property
    def name(self) -> str:
        return "supertrend"

    def calculate(self, df: pd.DataFrame) -> IndicatorResult:
        atr_period = self.thresholds.get("atr_period", 10)
        multiplier = self.thresholds.get("multiplier", 3.0)
        confirmation_bars = self.thresholds.get("confirmation_bars", 3)
        flip_buffer_atr = self.thresholds.get("flip_buffer_atr", 0.3)

        high = df["high"]
        low = df["low"]
        close = df["close"]

        if len(close) < atr_period + 2:
            return self._make_result(Signal.NEUTRAL, "Supertrend data insufficient")

        # ATR (Wilder)
        tr = pd.concat(
            [high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()],
            axis=1,
        ).max(axis=1)
        atr = wilder_rma(tr, atr_period)

        hl2 = (high + low) / 2.0
        basic_upper = hl2 + multiplier * atr
        basic_lower = hl2 - multiplier * atr

        n = len(close)
        final_upper = basic_upper.copy().values
        final_lower = basic_lower.copy().values
        st = np.zeros(n)
        trend = np.ones(n, dtype=int)  # +1 UP, -1 DOWN

        # Initialize first valid bar
        for i in range(1, n):
            if pd.isna(atr.iloc[i]):
                st[i] = close.iloc[i]
                trend[i] = trend[i - 1]
                continue

            # Final upper
            if basic_upper.iloc[i] < final_upper[i - 1] or close.iloc[i - 1] > final_upper[i - 1]:
                final_upper[i] = basic_upper.iloc[i]
            else:
                final_upper[i] = final_upper[i - 1]

            # Final lower
            if basic_lower.iloc[i] > final_lower[i - 1] or close.iloc[i - 1] < final_lower[i - 1]:
                final_lower[i] = basic_lower.iloc[i]
            else:
                final_lower[i] = final_lower[i - 1]

            # Trend direction
            if trend[i - 1] == 1 and close.iloc[i] < final_lower[i]:
                trend[i] = -1
            elif trend[i - 1] == -1 and close.iloc[i] > final_upper[i]:
                trend[i] = 1
            else:
                trend[i] = trend[i - 1]

            st[i] = final_lower[i] if trend[i] == 1 else final_upper[i]

        current_trend = int(trend[-1])
        prev_trend = int(trend[-2])
        current_st = float(st[-1])
        current_close = float(close.iloc[-1])
        current_atr = float(atr.iloc[-1])

        if current_atr == 0 or pd.isna(current_atr) or pd.isna(current_st):
            return self._make_result(Signal.NEUTRAL, "Supertrend not yet stabilized")

        # Distance in ATR units
        distance_atr = abs(current_close - current_st) / current_atr
        if pd.isna(distance_atr):
            return self._make_result(Signal.NEUTRAL, "Supertrend distance undefined")

        # Bars in current trend
        bars_in_trend = 1
        for i in range(n - 2, -1, -1):
            if trend[i] == current_trend:
                bars_in_trend += 1
            else:
                break

        raw = {
            "supertrend": round(current_st, 6),
            "trend": "UP" if current_trend == 1 else "DOWN",
            "distance_atr": round(distance_atr, 3),
            "bars_in_trend": bars_in_trend,
            "atr": round(current_atr, 6),
        }

        # Flip detection
        flipped_bullish = prev_trend == -1 and current_trend == 1
        flipped_bearish = prev_trend == 1 and current_trend == -1

        if flipped_bullish:
            return self._make_result(
                Signal.STRONG_BUY, "Supertrend flipped to UP — fresh bullish trend", raw
            )
        if flipped_bearish:
            return self._make_result(
                Signal.STRONG_SELL, "Supertrend flipped to DOWN — fresh bearish trend", raw
            )

        # Near-flip → NEUTRAL
        if distance_atr < flip_buffer_atr:
            return self._make_result(
                Signal.NEUTRAL,
                f"Supertrend near flip (dist={distance_atr:.2f}×ATR < {flip_buffer_atr})",
                raw,
            )

        if current_trend == 1 and distance_atr >= 1.0 and bars_in_trend >= confirmation_bars:
            return self._make_result(
                Signal.BUY,
                f"Supertrend UP confirmed: {bars_in_trend} bars, {distance_atr:.2f}×ATR above",
                raw,
            )
        if current_trend == -1 and distance_atr >= 1.0 and bars_in_trend >= confirmation_bars:
            return self._make_result(
                Signal.SELL,
                f"Supertrend DOWN confirmed: {bars_in_trend} bars, {distance_atr:.2f}×ATR below",
                raw,
            )

        return self._make_result(
            Signal.NEUTRAL,
            f"Supertrend {raw['trend']} but unconfirmed (bars={bars_in_trend}, dist={distance_atr:.2f}ATR)",
            raw,
        )
