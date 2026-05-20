"""Bollinger Bands v2 — ADX/volume regime split (per ShowMe audit E.2).

v2 changes:
- ADX < 20 (range) → mean-reversion semantics (price < lower = STRONG_BUY)
- ADX ≥ 20 (trend) → breakout semantics REVERSED (price > upper + high vol = STRONG_BUY)
- Pure squeeze without breakout = NEUTRAL ("watching for breakout")
"""

from __future__ import annotations

import pandas as pd
import numpy as np

from showme.engine.indicators.base import BaseIndicator, IndicatorResult, Signal


def _wilder_rma(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


class BollingerBandsIndicator(BaseIndicator):
    """Bollinger with regime-aware breakout/mean-reversion split."""

    @property
    def name(self) -> str:
        return "bollinger"

    def calculate(self, df: pd.DataFrame) -> IndicatorResult:
        period = self.thresholds.get("period", 20)
        std_dev = self.thresholds.get("std_dev", 2.0)
        squeeze_threshold = self.thresholds.get("squeeze_threshold", 0.02)
        # New v2 thresholds
        adx_period = self.thresholds.get("adx_period", 14)
        adx_trend_floor = self.thresholds.get("adx_trend_floor", 20)
        high_volume_multiplier = self.thresholds.get("high_volume_multiplier", 1.5)

        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"]

        sma = close.rolling(window=period).mean()
        rolling_std = close.rolling(window=period).std()
        upper_band = sma + (rolling_std * std_dev)
        lower_band = sma - (rolling_std * std_dev)

        current_close = close.iloc[-1]
        current_upper = upper_band.iloc[-1]
        current_lower = lower_band.iloc[-1]
        current_sma = sma.iloc[-1]

        if pd.isna(current_upper) or pd.isna(current_lower):
            return self._make_result(Signal.NEUTRAL, "Bollinger data insufficient")

        band_width = (current_upper - current_lower) / current_sma if current_sma != 0 else 0
        position = (
            (current_close - current_lower) / (current_upper - current_lower)
            if (current_upper - current_lower) != 0
            else 0.5
        )

        # Squeeze: current band width is in the lowest 25% of the last 20 bars
        recent_bw = (upper_band - lower_band) / sma.replace(0, np.nan)
        bw_quantile = recent_bw.iloc[-20:].quantile(0.25) if len(recent_bw) >= 20 else None
        is_squeeze = band_width < squeeze_threshold or (
            bw_quantile is not None and not pd.isna(bw_quantile) and band_width <= bw_quantile
        )

        # Volume context
        vol_avg = volume.rolling(window=period).mean().iloc[-1]
        current_vol = volume.iloc[-1]
        high_volume = bool(
            not pd.isna(vol_avg) and vol_avg > 0 and current_vol >= vol_avg * high_volume_multiplier
        )
        # Per FUNC-07 P0: compute once, with NaN fallback when vol_avg is 0/NaN.
        # The f-strings below would otherwise hit ZeroDivisionError on flat-volume bars.
        vol_ratio = current_vol / vol_avg if vol_avg else float("nan")

        # ADX for regime detection (inline Wilder)
        adx_value = self._compute_adx(high, low, close, adx_period)
        in_trend = bool(not pd.isna(adx_value) and adx_value >= adx_trend_floor)

        raw = {
            "upper": round(current_upper, 6),
            "lower": round(current_lower, 6),
            "sma": round(current_sma, 6),
            "band_width": round(band_width, 4),
            "position": round(position, 4),
            "is_squeeze": is_squeeze,
            "high_volume": high_volume,
            "adx": round(float(adx_value), 2) if not pd.isna(adx_value) else None,
            "regime": "TREND" if in_trend else "RANGE",
        }

        # ── BREAKOUT REGIME (ADX ≥ 20) ──
        if in_trend:
            if current_close > current_upper:
                if high_volume:
                    return self._make_result(
                        Signal.STRONG_BUY,
                        f"Trend breakout up: close>upper, vol×{vol_ratio:.1f} (ADX={adx_value:.0f})",
                        raw,
                    )
                return self._make_result(
                    Signal.BUY,
                    f"Trend breakout up: close>upper (ADX={adx_value:.0f})",
                    raw,
                )
            if current_close < current_lower:
                if high_volume:
                    return self._make_result(
                        Signal.STRONG_SELL,
                        f"Trend breakout down: close<lower, vol×{vol_ratio:.1f} (ADX={adx_value:.0f})",
                        raw,
                    )
                return self._make_result(
                    Signal.SELL,
                    f"Trend breakout down: close<lower (ADX={adx_value:.0f})",
                    raw,
                )
            # In trend regime, mid-band moves track trend bias
            if position > 0.65:
                return self._make_result(
                    Signal.BUY,
                    f"Trend regime upper-half (pos={position:.2f}, ADX={adx_value:.0f})",
                    raw,
                )
            if position < 0.35:
                return self._make_result(
                    Signal.SELL,
                    f"Trend regime lower-half (pos={position:.2f}, ADX={adx_value:.0f})",
                    raw,
                )
            zone = "trend mid-band"
            if is_squeeze:
                zone += " (squeeze — awaiting breakout)"
            return self._make_result(Signal.NEUTRAL, f"Bollinger {zone}", raw)

        # ── RANGE REGIME (ADX < 20) — mean-reversion ──
        if current_close < current_lower:
            if is_squeeze:
                return self._make_result(
                    Signal.BUY,
                    "Range: price below lower during squeeze — partial mean-reversion",
                    raw,
                )
            return self._make_result(Signal.STRONG_BUY, "Range: price below lower band", raw)
        if position < 0.15:
            return self._make_result(
                Signal.BUY, f"Range: near lower band (pos={position:.2f})", raw
            )
        if current_close > current_upper:
            if is_squeeze:
                return self._make_result(
                    Signal.SELL,
                    "Range: price above upper during squeeze — partial mean-reversion",
                    raw,
                )
            return self._make_result(Signal.STRONG_SELL, "Range: price above upper band", raw)
        if position > 0.85:
            return self._make_result(
                Signal.SELL, f"Range: near upper band (pos={position:.2f})", raw
            )
        zone = "range mid-band neutral"
        if is_squeeze:
            zone = "squeeze — awaiting breakout"
        return self._make_result(Signal.NEUTRAL, f"Bollinger {zone} (pos={position:.2f})", raw)

    @staticmethod
    def _compute_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> float:
        plus_dm = high.diff()
        minus_dm = -low.diff()
        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)
        tr = pd.concat(
            [high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()],
            axis=1,
        ).max(axis=1)
        atr = _wilder_rma(tr, period).replace(0, np.nan)
        plus_di = 100.0 * (_wilder_rma(plus_dm, period) / atr)
        minus_di = 100.0 * (_wilder_rma(minus_dm, period) / atr)
        di_sum = (plus_di + minus_di).replace(0, np.nan)
        dx = 100.0 * ((plus_di - minus_di).abs() / di_sum)
        adx = _wilder_rma(dx, period)
        return float(adx.iloc[-1])
