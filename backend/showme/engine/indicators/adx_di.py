"""ADX + Directional Index (DI) — Wilder RMA smoothing (per ShowMe audit E.3)."""
from __future__ import annotations


import pandas as pd
import numpy as np

from showme.engine.indicators.base import BaseIndicator, IndicatorResult, Signal


def wilder_rma(series: pd.Series, period: int) -> pd.Series:
    """Wilder's RMA: alpha = 1/period. Canonical for ADX/ATR."""
    return series.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


class ADXDIIndicator(BaseIndicator):
    """ADX with +DI/-DI for trend strength and direction. Wilder smoothing."""

    @property
    def name(self) -> str:
        return "adx_di"

    def calculate(self, df: pd.DataFrame) -> IndicatorResult:
        period = self.thresholds.get("period", 14)
        strong_trend = self.thresholds.get("strong_trend", 25)
        weak_trend = self.thresholds.get("weak_trend", 15)

        high = df["high"]
        low = df["low"]
        close = df["close"]

        plus_dm = high.diff()
        minus_dm = -low.diff()

        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        atr = wilder_rma(tr, period).replace(0, np.nan)
        plus_di = 100.0 * (wilder_rma(plus_dm, period) / atr)
        minus_di = 100.0 * (wilder_rma(minus_dm, period) / atr)

        di_sum = (plus_di + minus_di).replace(0, np.nan)
        dx = 100.0 * ((plus_di - minus_di).abs() / di_sum)
        adx = wilder_rma(dx, period)

        current_adx = adx.iloc[-1]
        current_plus_di = plus_di.iloc[-1]
        current_minus_di = minus_di.iloc[-1]

        if pd.isna(current_adx) or pd.isna(current_plus_di) or pd.isna(current_minus_di):
            return self._make_result(Signal.NEUTRAL, "ADX/DI data insufficient")

        raw = {
            "adx": round(float(current_adx), 2),
            "plus_di": round(float(current_plus_di), 2),
            "minus_di": round(float(current_minus_di), 2),
            "smoothing": "wilder_rma",
        }

        if current_adx < weak_trend:
            return self._make_result(
                Signal.NEUTRAL,
                f"ADX={current_adx:.1f} weak trend (Wilder) - no directional conviction",
                raw,
            )

        is_strong = current_adx >= strong_trend

        if current_plus_di > current_minus_di:
            if is_strong:
                return self._make_result(
                    Signal.STRONG_BUY,
                    f"ADX={current_adx:.1f} strong bullish trend (+DI>-DI, Wilder)",
                    raw,
                )
            return self._make_result(
                Signal.BUY, f"ADX={current_adx:.1f} bullish trend (+DI>-DI, Wilder)", raw
            )
        elif current_minus_di > current_plus_di:
            if is_strong:
                return self._make_result(
                    Signal.STRONG_SELL,
                    f"ADX={current_adx:.1f} strong bearish trend (-DI>+DI, Wilder)",
                    raw,
                )
            return self._make_result(
                Signal.SELL, f"ADX={current_adx:.1f} bearish trend (-DI>+DI, Wilder)", raw
            )
        else:
            return self._make_result(
                Signal.NEUTRAL, f"ADX={current_adx:.1f} DI lines converging", raw
            )
