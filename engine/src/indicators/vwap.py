"""VWAP + Standard Deviation Bands (per ShowMe audit D.2).

Rolling VWAP (not session) — works on any TF without UTC reset complexity.
Strategy:
  STRONG_BUY  : price < VWAP - 2σ AND positive divergence
  BUY         : price between -1σ and -2σ AND bullish candle (close>open)
  NEUTRAL     : price within ±1σ
  SELL        : price between +1σ and +2σ AND bearish candle
  STRONG_SELL : price > VWAP + 2σ AND high volume (>multiplier × avg)
"""

from typing import Any
import pandas as pd
import numpy as np

from src.indicators.base import BaseIndicator, IndicatorResult, Signal


class VWAPIndicator(BaseIndicator):
    @property
    def name(self) -> str:
        return "vwap"

    def calculate(self, df: pd.DataFrame) -> IndicatorResult:
        rolling_period = self.thresholds.get("rolling_period", 96)
        band_std_1 = self.thresholds.get("band_std_1", 1.0)
        band_std_2 = self.thresholds.get("band_std_2", 2.0)
        high_volume_multiplier = self.thresholds.get("high_volume_multiplier", 1.5)

        high = df["high"]
        low = df["low"]
        close = df["close"]
        open_ = df["open"]
        volume = df["volume"]

        if len(close) < rolling_period + 5:
            return self._make_result(Signal.NEUTRAL, "VWAP data insufficient")

        typical_price = (high + low + close) / 3.0

        # Rolling VWAP
        tp_vol = (typical_price * volume).rolling(window=rolling_period).sum()
        vol_sum = volume.rolling(window=rolling_period).sum().replace(0, np.nan)
        vwap = tp_vol / vol_sum

        # Standard deviation of (price − VWAP)
        diff = close - vwap
        std_dev = diff.rolling(window=rolling_period).std()

        current_close = float(close.iloc[-1])
        current_open = float(open_.iloc[-1])
        current_vwap = float(vwap.iloc[-1]) if not pd.isna(vwap.iloc[-1]) else None
        current_std = float(std_dev.iloc[-1]) if not pd.isna(std_dev.iloc[-1]) else None
        current_vol = float(volume.iloc[-1])
        avg_vol = float(volume.rolling(window=rolling_period).mean().iloc[-1])

        if current_vwap is None or current_std is None or current_std == 0:
            return self._make_result(Signal.NEUTRAL, "VWAP statistics insufficient")

        upper_1 = current_vwap + band_std_1 * current_std
        lower_1 = current_vwap - band_std_1 * current_std
        upper_2 = current_vwap + band_std_2 * current_std
        lower_2 = current_vwap - band_std_2 * current_std

        # z-score of close vs VWAP
        z = (current_close - current_vwap) / current_std

        # Candle direction
        bullish_candle = current_close > current_open
        bearish_candle = current_close < current_open

        high_volume = bool(avg_vol > 0 and current_vol > avg_vol * high_volume_multiplier)

        # Simple positive/negative divergence: is the gap (close - vwap) trending opposite to close?
        n = min(10, len(close) - 1)
        if n >= 4:
            try:
                price_slope = float(np.polyfit(range(n), close.iloc[-n:].values, 1)[0])
                gap_slope = float(np.polyfit(range(n), diff.iloc[-n:].values, 1)[0])
            except Exception:
                price_slope = 0.0
                gap_slope = 0.0
        else:
            price_slope = 0.0
            gap_slope = 0.0
        positive_divergence = price_slope < 0 and gap_slope > 0  # price↓ but gap improving
        negative_divergence = price_slope > 0 and gap_slope < 0

        raw = {
            "vwap": round(current_vwap, 6),
            "z": round(z, 3),
            "upper_1": round(upper_1, 6),
            "lower_1": round(lower_1, 6),
            "upper_2": round(upper_2, 6),
            "lower_2": round(lower_2, 6),
            "high_volume": high_volume,
            "positive_divergence": positive_divergence,
            "negative_divergence": negative_divergence,
        }

        if current_close < lower_2:
            if positive_divergence:
                return self._make_result(
                    Signal.STRONG_BUY,
                    f"Price below VWAP-2σ (z={z:.2f}) + positive divergence",
                    raw,
                )
            return self._make_result(
                Signal.BUY, f"Price below VWAP-2σ (z={z:.2f})", raw
            )
        if current_close < lower_1:
            if bullish_candle:
                return self._make_result(
                    Signal.BUY,
                    f"Price between -1σ and -2σ (z={z:.2f}) with bullish candle",
                    raw,
                )
            return self._make_result(
                Signal.NEUTRAL, f"Price between -1σ and -2σ (z={z:.2f})", raw
            )
        if current_close > upper_2:
            if high_volume:
                return self._make_result(
                    Signal.STRONG_SELL,
                    f"Price above VWAP+2σ (z={z:.2f}) on high volume",
                    raw,
                )
            return self._make_result(
                Signal.SELL, f"Price above VWAP+2σ (z={z:.2f})", raw
            )
        if current_close > upper_1:
            if bearish_candle:
                return self._make_result(
                    Signal.SELL,
                    f"Price between +1σ and +2σ (z={z:.2f}) with bearish candle",
                    raw,
                )
            return self._make_result(
                Signal.NEUTRAL, f"Price between +1σ and +2σ (z={z:.2f})", raw
            )
        return self._make_result(
            Signal.NEUTRAL, f"Price within ±1σ of VWAP (z={z:.2f})", raw
        )
