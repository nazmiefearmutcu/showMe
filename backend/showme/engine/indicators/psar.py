"""Parabolic SAR v2 — flip-only signals + distance-based NEUTRAL (per ShowMe audit E.5).

Old logic emitted BUY/SELL every cycle while in trend. v2 emits:
  BUY/SELL on flip, BUY/SELL on distance > 2% (strong trend continuation),
  WEAK BUY/SELL on 0.5%-2% (signal_strength=0.5),
  NEUTRAL on distance < 0.5% (flip risk).
"""

from __future__ import annotations

import pandas as pd
import numpy as np

from showme.engine.indicators.base import BaseIndicator, IndicatorResult, Signal


class PSARIndicator(BaseIndicator):
    @property
    def name(self) -> str:
        return "psar"

    def calculate(self, df: pd.DataFrame) -> IndicatorResult:
        af_start = self.thresholds.get("af_start", 0.02)
        af_increment = self.thresholds.get("af_increment", 0.02)
        af_max = self.thresholds.get("af_max", 0.20)
        weak_distance_pct = self.thresholds.get("weak_distance_pct", 0.5)
        strong_distance_pct = self.thresholds.get("strong_distance_pct", 2.0)

        high = df["high"].values
        low = df["low"].values
        close = df["close"].values
        n = len(close)

        if n < 3:
            return self._make_result(Signal.NEUTRAL, "PSAR data insufficient")

        psar = np.zeros(n)
        af = np.zeros(n)
        ep = np.zeros(n)
        trend = np.ones(n)

        psar[0] = low[0]
        af[0] = af_start
        ep[0] = high[0]
        trend[0] = 1

        for i in range(1, n):
            prev_psar = psar[i - 1]
            prev_af = af[i - 1]
            prev_ep = ep[i - 1]
            prev_trend = trend[i - 1]

            if prev_trend == 1:
                psar[i] = prev_psar + prev_af * (prev_ep - prev_psar)
                psar[i] = min(psar[i], low[i - 1])
                if i >= 2:
                    psar[i] = min(psar[i], low[i - 2])
                if low[i] < psar[i]:
                    trend[i] = -1
                    psar[i] = prev_ep
                    ep[i] = low[i]
                    af[i] = af_start
                else:
                    trend[i] = 1
                    if high[i] > prev_ep:
                        ep[i] = high[i]
                        af[i] = min(prev_af + af_increment, af_max)
                    else:
                        ep[i] = prev_ep
                        af[i] = prev_af
            else:
                psar[i] = prev_psar + prev_af * (prev_ep - prev_psar)
                psar[i] = max(psar[i], high[i - 1])
                if i >= 2:
                    psar[i] = max(psar[i], high[i - 2])
                if high[i] > psar[i]:
                    trend[i] = 1
                    psar[i] = prev_ep
                    ep[i] = high[i]
                    af[i] = af_start
                else:
                    trend[i] = -1
                    if low[i] < prev_ep:
                        ep[i] = low[i]
                        af[i] = min(prev_af + af_increment, af_max)
                    else:
                        ep[i] = prev_ep
                        af[i] = prev_af

        current_trend = trend[-1]
        prev_trend = trend[-2]
        current_psar = psar[-1]
        current_close = close[-1]

        # Guard a zero/None close so a delisted-feed glitch can't ZeroDivisionError
        # the whole consensus run. Audit FUNC-07 P0.
        distance_pct = (
            abs(current_close - current_psar) / current_close * 100.0
            if current_close
            else 0.0
        )

        raw = {
            "psar": round(float(current_psar), 6),
            "trend": "UP" if current_trend == 1 else "DOWN",
            "distance_pct": round(float(distance_pct), 4),
            "signal_strength": 1.0,
        }

        flipped_bullish = prev_trend == -1 and current_trend == 1
        flipped_bearish = prev_trend == 1 and current_trend == -1

        if flipped_bullish:
            return self._make_result(Signal.BUY, "PSAR fresh bullish flip", raw)
        if flipped_bearish:
            return self._make_result(Signal.SELL, "PSAR fresh bearish flip", raw)

        # Near-flip → NEUTRAL
        if distance_pct < weak_distance_pct:
            return self._make_result(
                Signal.NEUTRAL,
                f"PSAR {raw['trend']} but near flip (dist={distance_pct:.2f}% < {weak_distance_pct}%)",
                raw,
            )

        # Strong trend continuation
        if current_trend == 1:
            if distance_pct >= strong_distance_pct:
                return self._make_result(
                    Signal.BUY,
                    f"PSAR uptrend confirmed (dist={distance_pct:.2f}%)",
                    raw,
                )
            raw["signal_strength"] = 0.5
            return self._make_result(
                Signal.BUY,
                f"PSAR uptrend (weak dist={distance_pct:.2f}%, strength=0.5)",
                raw,
            )

        if current_trend == -1:
            if distance_pct >= strong_distance_pct:
                return self._make_result(
                    Signal.SELL,
                    f"PSAR downtrend confirmed (dist={distance_pct:.2f}%)",
                    raw,
                )
            raw["signal_strength"] = 0.5
            return self._make_result(
                Signal.SELL,
                f"PSAR downtrend (weak dist={distance_pct:.2f}%, strength=0.5)",
                raw,
            )

        return self._make_result(Signal.NEUTRAL, "PSAR indeterminate", raw)
