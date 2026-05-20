"""Keltner Channel + TTM Squeeze detection (per ShowMe audit D.7).

Keltner uses ATR (vs Bollinger's stddev). The "TTM Squeeze" pattern is when
Bollinger bands enter Keltner channel — releases give directional momentum bursts.
"""

from __future__ import annotations

import pandas as pd

from showme.engine.indicators.base import BaseIndicator, IndicatorResult, Signal
from showme.engine.indicators.adx_di import wilder_rma


class KeltnerIndicator(BaseIndicator):
    @property
    def name(self) -> str:
        return "keltner"

    def calculate(self, df: pd.DataFrame) -> IndicatorResult:
        ema_period = self.thresholds.get("ema_period", 20)
        atr_period = self.thresholds.get("atr_period", 10)
        multiplier = self.thresholds.get("multiplier", 2.0)
        # Bollinger references for squeeze detection
        bb_period = self.thresholds.get("bb_period", 20)
        bb_std = self.thresholds.get("bb_std", 2.0)

        high = df["high"]
        low = df["low"]
        close = df["close"]

        if len(close) < max(ema_period, atr_period, bb_period) + 5:
            return self._make_result(Signal.NEUTRAL, "Keltner data insufficient")

        mid = close.ewm(span=ema_period, adjust=False).mean()
        tr = pd.concat(
            [high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()],
            axis=1,
        ).max(axis=1)
        atr = wilder_rma(tr, atr_period)

        upper = mid + multiplier * atr
        lower = mid - multiplier * atr

        # Bollinger for squeeze detection
        bb_mid = close.rolling(window=bb_period).mean()
        bb_std_v = close.rolling(window=bb_period).std()
        bb_upper = bb_mid + bb_std * bb_std_v
        bb_lower = bb_mid - bb_std * bb_std_v

        current_close = float(close.iloc[-1])
        current_mid = float(mid.iloc[-1])
        current_upper = float(upper.iloc[-1])
        current_lower = float(lower.iloc[-1])
        current_atr = float(atr.iloc[-1])

        # Squeeze: BB inside Keltner
        squeeze_now = (
            float(bb_upper.iloc[-1]) < current_upper
            and float(bb_lower.iloc[-1]) > current_lower
        )
        squeeze_prev = (
            len(bb_upper) >= 2
            and float(bb_upper.iloc[-2]) < float(upper.iloc[-2])
            and float(bb_lower.iloc[-2]) > float(lower.iloc[-2])
        )
        squeeze_release = (not squeeze_now) and squeeze_prev

        # EMA slope (positive vs negative momentum bias)
        ema_slope = float(mid.iloc[-1] - mid.iloc[-5]) if len(mid) >= 5 else 0.0

        raw = {
            "mid": round(current_mid, 6),
            "upper": round(current_upper, 6),
            "lower": round(current_lower, 6),
            "squeeze_now": squeeze_now,
            "squeeze_release": squeeze_release,
            "ema_slope": round(ema_slope, 6),
        }

        if squeeze_release:
            if current_close > current_upper:
                return self._make_result(
                    Signal.STRONG_BUY,
                    "Keltner squeeze release UP (close > upper Keltner)",
                    raw,
                )
            if current_close < current_lower:
                return self._make_result(
                    Signal.STRONG_SELL,
                    "Keltner squeeze release DOWN (close < lower Keltner)",
                    raw,
                )

        if squeeze_now:
            return self._make_result(
                Signal.NEUTRAL, "Keltner squeeze active — awaiting release", raw
            )

        if current_close > current_upper and ema_slope > 0:
            return self._make_result(
                Signal.BUY, "Close above upper Keltner with positive slope", raw
            )
        if current_close < current_lower and ema_slope < 0:
            return self._make_result(
                Signal.SELL, "Close below lower Keltner with negative slope", raw
            )

        # Mid-band proximity → NEUTRAL
        if current_atr > 0 and abs(current_close - current_mid) < 0.5 * current_atr:
            return self._make_result(
                Signal.NEUTRAL, "Close within ±0.5 ATR of Keltner mid", raw
            )

        if current_close > current_mid:
            return self._make_result(Signal.BUY, "Close above Keltner mid", raw)
        return self._make_result(Signal.SELL, "Close below Keltner mid", raw)
