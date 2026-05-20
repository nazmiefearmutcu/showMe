"""Heikin-Ashi Trend Filter (per ShowMe audit D.6).

Smoothed candles for trend confirmation. Consecutive same-color HA candles
indicate strong trend; doji or wicks-on-both-sides → indecision.
"""

from __future__ import annotations

import pandas as pd
import numpy as np

from showme.engine.indicators.base import BaseIndicator, IndicatorResult, Signal
from showme.engine.indicators.adx_di import wilder_rma


class HeikinAshiIndicator(BaseIndicator):
    @property
    def name(self) -> str:
        return "heikin_ashi"

    def calculate(self, df: pd.DataFrame) -> IndicatorResult:
        confirmation_bars = self.thresholds.get("confirmation_bars", 3)
        strong_bars = self.thresholds.get("strong_confirmation_bars", 5)
        doji_atr_ratio = self.thresholds.get("doji_atr_ratio", 0.2)

        if len(df) < strong_bars + 5:
            return self._make_result(Signal.NEUTRAL, "Heikin-Ashi data insufficient")

        open_ = df["open"].values
        high = df["high"].values
        low = df["low"].values
        close = df["close"].values
        n = len(close)

        ha_close = (open_ + high + low + close) / 4.0
        ha_open = np.zeros(n)
        ha_high = np.zeros(n)
        ha_low = np.zeros(n)

        ha_open[0] = (open_[0] + close[0]) / 2.0
        ha_high[0] = max(high[0], ha_open[0], ha_close[0])
        ha_low[0] = min(low[0], ha_open[0], ha_close[0])
        for i in range(1, n):
            ha_open[i] = (ha_open[i - 1] + ha_close[i - 1]) / 2.0
            ha_high[i] = max(high[i], ha_open[i], ha_close[i])
            ha_low[i] = min(low[i], ha_open[i], ha_close[i])

        # ATR (Wilder) for doji magnitude
        tr = pd.concat(
            [
                df["high"] - df["low"],
                (df["high"] - df["close"].shift(1)).abs(),
                (df["low"] - df["close"].shift(1)).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr = wilder_rma(tr, 14)
        current_atr = float(atr.iloc[-1]) if not pd.isna(atr.iloc[-1]) else None

        # Count consecutive same-color HA candles ending at last bar
        green = ha_close > ha_open
        last_color = bool(green[-1])
        run = 1
        for i in range(n - 2, -1, -1):
            if bool(green[i]) == last_color:
                run += 1
            else:
                break

        body = abs(ha_close[-1] - ha_open[-1])
        upper_shadow = ha_high[-1] - max(ha_close[-1], ha_open[-1])
        lower_shadow = min(ha_close[-1], ha_open[-1]) - ha_low[-1]

        is_doji = (
            current_atr is not None
            and current_atr > 0
            and (body / current_atr) < doji_atr_ratio
        )

        # Strong: no opposing shadow on the recent candles
        no_lower_shadow = lower_shadow < (body * 0.1) if body > 0 else False
        no_upper_shadow = upper_shadow < (body * 0.1) if body > 0 else False

        raw = {
            "consecutive_run": run,
            "color": "GREEN" if last_color else "RED",
            "body": round(float(body), 6),
            "upper_shadow": round(float(upper_shadow), 6),
            "lower_shadow": round(float(lower_shadow), 6),
            "is_doji": is_doji,
        }

        if is_doji:
            return self._make_result(
                Signal.NEUTRAL, f"Heikin-Ashi doji (body/ATR<{doji_atr_ratio})", raw
            )

        if last_color and run >= strong_bars and no_lower_shadow:
            return self._make_result(
                Signal.STRONG_BUY,
                f"HA strong bull: {run} green candles, no lower shadow",
                raw,
            )
        if last_color and run >= confirmation_bars:
            return self._make_result(
                Signal.BUY, f"HA bull confirmation: {run} green candles", raw
            )
        if (not last_color) and run >= strong_bars and no_upper_shadow:
            return self._make_result(
                Signal.STRONG_SELL,
                f"HA strong bear: {run} red candles, no upper shadow",
                raw,
            )
        if (not last_color) and run >= confirmation_bars:
            return self._make_result(
                Signal.SELL, f"HA bear confirmation: {run} red candles", raw
            )
        return self._make_result(
            Signal.NEUTRAL, f"HA mixed (run={run} {raw['color']})", raw
        )
