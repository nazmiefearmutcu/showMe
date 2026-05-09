"""ATR (Average True Range) risk filter — Wilder RMA smoothing.

Per ShowMe audit E.3 — Wilder smoothing applied here too for consistency
with ADX/DI. ATR remains a directional NEUTRAL filter; only volatility
classification is reported in raw_values.
"""

import pandas as pd

from showme.engine.indicators.base import BaseIndicator, IndicatorResult, Signal
from showme.engine.indicators.adx_di import wilder_rma


class ATRFilterIndicator(BaseIndicator):
    """ATR as a volatility/risk filter. Always NEUTRAL signal; raw_values carry context.

    raw_values["volatility"] in {LOW, NORMAL, HIGH} drives consensus risk.
    """

    @property
    def name(self) -> str:
        return "atr_filter"

    def calculate(self, df: pd.DataFrame) -> IndicatorResult:
        period = self.thresholds.get("period", 14)
        high_vol_multiplier = self.thresholds.get("high_volatility_multiplier", 2.0)

        high = df["high"]
        low = df["low"]
        close = df["close"]

        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        # Wilder RMA, not simple rolling
        atr = wilder_rma(tr, period)
        current_atr = atr.iloc[-1]
        current_price = close.iloc[-1]

        if pd.isna(current_atr) or current_price == 0:
            return self._make_result(Signal.NEUTRAL, "ATR data insufficient")

        atr_pct = (current_atr / current_price) * 100.0
        # Long-window mean for ratio (Wilder also)
        atr_mean = wilder_rma(tr, period * 3).iloc[-1]
        atr_ratio = current_atr / atr_mean if not pd.isna(atr_mean) and atr_mean != 0 else 1.0

        if atr_ratio > high_vol_multiplier:
            volatility = "HIGH"
        elif atr_ratio > 0.8:
            volatility = "NORMAL"
        else:
            volatility = "LOW"

        raw = {
            "atr": round(float(current_atr), 6),
            "atr_pct": round(float(atr_pct), 4),
            "atr_ratio": round(float(atr_ratio), 4),
            "volatility": volatility,
            "smoothing": "wilder_rma",
        }

        # Always NEUTRAL — ATR is a risk filter, never directional
        if volatility == "HIGH":
            return self._make_result(
                Signal.NEUTRAL,
                f"ATR={current_atr:.4f} ({atr_pct:.2f}%) HIGH volatility - reduce position",
                raw,
            )
        if volatility == "LOW":
            return self._make_result(
                Signal.NEUTRAL,
                f"ATR={current_atr:.4f} ({atr_pct:.2f}%) LOW volatility - watch for breakout",
                raw,
            )
        return self._make_result(
            Signal.NEUTRAL,
            f"ATR={current_atr:.4f} ({atr_pct:.2f}%) normal volatility",
            raw,
        )
