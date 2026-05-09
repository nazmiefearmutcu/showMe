"""OBV (On-Balance Volume) v2 — slope correlation + z-score normalization.

v2 changes (per ShowMe audit E.4):
- z-score normalization replaces unscaled abs() denominator
- Linear-fit slope of price vs OBV for divergence (scale-independent)
- Strength tied to obv_z magnitude
"""

import pandas as pd
import numpy as np

from showme.engine.indicators.base import BaseIndicator, IndicatorResult, Signal


class OBVIndicator(BaseIndicator):
    """OBV with slope-correlation divergence and z-score trend confirmation."""

    @property
    def name(self) -> str:
        return "obv"

    def calculate(self, df: pd.DataFrame) -> IndicatorResult:
        sma_period = self.thresholds.get("sma_period", 20)
        divergence_lookback = self.thresholds.get("divergence_lookback", 10)
        slope_min = self.thresholds.get("slope_min_normalized", 0.001)

        close = df["close"]
        volume = df["volume"]

        if len(close) < sma_period + 2:
            return self._make_result(Signal.NEUTRAL, "OBV data insufficient")

        # OBV cumulative
        direction = np.where(close.diff() > 0, 1, np.where(close.diff() < 0, -1, 0))
        obv_series = pd.Series((volume * direction).cumsum().values, index=df.index)

        obv_sma = obv_series.rolling(window=sma_period).mean()
        obv_std = obv_series.rolling(window=sma_period).std()

        current_obv = float(obv_series.iloc[-1])
        current_obv_sma = float(obv_sma.iloc[-1]) if not pd.isna(obv_sma.iloc[-1]) else None
        current_obv_std = float(obv_std.iloc[-1]) if not pd.isna(obv_std.iloc[-1]) else None

        if current_obv_sma is None or current_obv_std is None or current_obv_std == 0:
            return self._make_result(Signal.NEUTRAL, "OBV statistics insufficient")

        obv_z = (current_obv - current_obv_sma) / current_obv_std

        # Slope-based divergence detection
        n = min(divergence_lookback, len(close) - 1)
        if n < 4:
            return self._make_result(
                Signal.NEUTRAL, f"OBV lookback too small ({n})"
            )

        x = np.arange(n)
        try:
            price_slope = float(np.polyfit(x, close.iloc[-n:].values, 1)[0])
            obv_slope = float(np.polyfit(x, obv_series.iloc[-n:].values, 1)[0])
        except Exception:
            price_slope = 0.0
            obv_slope = 0.0

        last_close = float(close.iloc[-1])
        price_norm = price_slope / last_close if last_close != 0 else 0.0
        # Normalize OBV slope by its rolling std (scale-free)
        obv_norm = obv_slope / current_obv_std if current_obv_std != 0 else 0.0

        bullish_div = price_norm < -slope_min and obv_norm > 0
        bearish_div = price_norm > slope_min and obv_norm < 0

        raw = {
            "obv": round(current_obv, 2),
            "obv_sma": round(current_obv_sma, 2),
            "obv_z": round(obv_z, 3),
            "price_slope_norm": round(price_norm, 6),
            "obv_slope_norm": round(obv_norm, 6),
            "bullish_divergence": bullish_div,
            "bearish_divergence": bearish_div,
        }

        # ── Divergence first (overrides z-trend) ──
        if bullish_div:
            sig = Signal.STRONG_BUY if obv_z > 0 else Signal.BUY
            return self._make_result(
                sig,
                f"OBV bullish divergence: price_slope={price_norm:.5f} < 0, obv_slope>0",
                raw,
            )
        if bearish_div:
            sig = Signal.STRONG_SELL if obv_z < 0 else Signal.SELL
            return self._make_result(
                sig,
                f"OBV bearish divergence: price_slope={price_norm:.5f} > 0, obv_slope<0",
                raw,
            )

        # ── Trend confirmation by z-score ──
        if obv_z >= 2.0 and obv_norm > 0:
            return self._make_result(
                Signal.STRONG_BUY,
                f"OBV strongly above mean (z={obv_z:.2f}) and rising",
                raw,
            )
        if obv_z >= 1.0 and obv_norm > 0:
            return self._make_result(
                Signal.BUY, f"OBV above mean (z={obv_z:.2f}), volume supports up", raw
            )
        if obv_z <= -2.0 and obv_norm < 0:
            return self._make_result(
                Signal.STRONG_SELL,
                f"OBV strongly below mean (z={obv_z:.2f}) and falling",
                raw,
            )
        if obv_z <= -1.0 and obv_norm < 0:
            return self._make_result(
                Signal.SELL, f"OBV below mean (z={obv_z:.2f}), volume supports down", raw
            )

        return self._make_result(
            Signal.NEUTRAL,
            f"OBV neutral (z={obv_z:.2f}, slope_norm={obv_norm:.5f})",
            raw,
        )
