"""CVD — Cumulative Volume Delta (per ShowMe audit D.3).

Uses Binance taker_buy_base from kline data (already in MarketDataProvider).
delta = taker_buy − taker_sell  →  CVD = cumsum(delta)
Detects order-flow imbalance and divergences.
"""

import pandas as pd

from showme.engine.indicators.base import BaseIndicator, IndicatorResult, Signal


class CVDIndicator(BaseIndicator):
    @property
    def name(self) -> str:
        return "cvd"

    def calculate(self, df: pd.DataFrame) -> IndicatorResult:
        cvd_ema_period = self.thresholds.get("cvd_ema_period", 20)
        slope_lookback = self.thresholds.get("slope_lookback", 5)
        divergence_lookback = self.thresholds.get("divergence_lookback", 10)
        divergence_pct_threshold = self.thresholds.get("divergence_pct_threshold", 0.02)

        if "taker_buy_base" not in df.columns:
            return self._make_result(Signal.NEUTRAL, "CVD requires taker_buy_base column")

        if len(df) < cvd_ema_period + 5:
            return self._make_result(Signal.NEUTRAL, "CVD data insufficient")

        close = df["close"]
        volume = df["volume"]
        taker_buy = df["taker_buy_base"]
        taker_sell = volume - taker_buy
        delta = taker_buy - taker_sell
        cvd = delta.cumsum()
        cvd_ema = cvd.ewm(span=cvd_ema_period, adjust=False).mean()

        current_cvd = float(cvd.iloc[-1])
        current_cvd_ema = float(cvd_ema.iloc[-1])

        # Slope of CVD over slope_lookback bars (use EMA for noise reduction)
        if len(cvd_ema) < slope_lookback + 1:
            return self._make_result(Signal.NEUTRAL, "CVD slope window too small")

        cvd_slope = float(cvd_ema.iloc[-1] - cvd_ema.iloc[-slope_lookback - 1])
        # Normalize slope by recent CVD std to make it scale-free
        cvd_std = float(cvd.rolling(window=cvd_ema_period).std().iloc[-1])
        slope_z = cvd_slope / cvd_std if cvd_std and cvd_std != 0 else 0.0

        # Divergence detection
        n = min(divergence_lookback, len(close) - 1)
        if n < 4:
            return self._make_result(Signal.NEUTRAL, "CVD divergence lookback too small")

        # HH/LL on price vs CVD over n bars
        price_window = close.iloc[-n - 1 : -1]
        cvd_window = cvd.iloc[-n - 1 : -1]
        if len(price_window) < 2 or len(cvd_window) < 2:
            return self._make_result(Signal.NEUTRAL, "CVD window empty")

        price_min = float(price_window.min())
        price_max = float(price_window.max())
        cvd_at_price_min = float(cvd_window.loc[price_window.idxmin()])
        cvd_at_price_max = float(cvd_window.loc[price_window.idxmax()])

        last_close = float(close.iloc[-1])

        # Bullish divergence: price LL but CVD HL
        bullish_div = (
            last_close < price_min * (1 - divergence_pct_threshold)
            and current_cvd > cvd_at_price_min
        )
        # Bearish divergence: price HH but CVD LH
        bearish_div = (
            last_close > price_max * (1 + divergence_pct_threshold)
            and current_cvd < cvd_at_price_max
        )

        raw = {
            "cvd": round(current_cvd, 2),
            "cvd_ema": round(current_cvd_ema, 2),
            "cvd_slope": round(cvd_slope, 2),
            "slope_z": round(slope_z, 3),
            "bullish_divergence": bullish_div,
            "bearish_divergence": bearish_div,
        }

        # Divergence first
        if bullish_div and cvd_slope > 0:
            return self._make_result(
                Signal.STRONG_BUY,
                f"CVD bullish divergence: price LL but CVD rising (slope_z={slope_z:.2f})",
                raw,
            )
        if bearish_div and cvd_slope < 0:
            return self._make_result(
                Signal.STRONG_SELL,
                f"CVD bearish divergence: price HH but CVD falling (slope_z={slope_z:.2f})",
                raw,
            )

        # Non-divergence cases — order flow trend
        if abs(slope_z) < 0.3:
            return self._make_result(
                Signal.NEUTRAL,
                f"CVD slope flat (z={slope_z:.2f}) — no fresh order flow info",
                raw,
            )
        if current_cvd > current_cvd_ema and cvd_slope > 0:
            return self._make_result(
                Signal.BUY,
                f"CVD above EMA, accelerating up (slope_z={slope_z:.2f})",
                raw,
            )
        if current_cvd < current_cvd_ema and cvd_slope < 0:
            return self._make_result(
                Signal.SELL,
                f"CVD below EMA, accelerating down (slope_z={slope_z:.2f})",
                raw,
            )
        return self._make_result(
            Signal.NEUTRAL, f"CVD mixed signals (slope_z={slope_z:.2f})", raw
        )
