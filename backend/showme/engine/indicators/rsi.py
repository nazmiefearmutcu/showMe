"""RSI (Relative Strength Index) v2 — regime-aware + divergence detection.

v2 changes (per ShowMe audit report E.1):
- Regime detection via embedded ADX/+DI/-DI: TREND vs RANGE
- TREND mode: shifted thresholds to avoid trend-trap (RSI staying 70+ in bull)
- RANGE mode: classic mean-reversion thresholds
- Divergence layer: price LL/HH vs RSI LL/HH over last N bars
- RSI 9-EMA cross as additional confirmation
"""

import pandas as pd
import numpy as np

from showme.engine.indicators.base import BaseIndicator, IndicatorResult, Signal


def _wilder_rma(series: pd.Series, period: int) -> pd.Series:
    """Wilder's RMA (running moving average) — alpha = 1/period."""
    return series.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


class RSIIndicator(BaseIndicator):
    """Regime-aware RSI with divergence and EMA-cross confirmation."""

    @property
    def name(self) -> str:
        return "rsi"

    def calculate(self, df: pd.DataFrame) -> IndicatorResult:
        period = self.thresholds.get("period", 14)
        # Range-mode thresholds (mean-reversion)
        strong_buy = self.thresholds.get("strong_buy", 25)
        buy = self.thresholds.get("buy", 35)
        sell = self.thresholds.get("sell", 65)
        strong_sell = self.thresholds.get("strong_sell", 80)
        # Divergence lookback
        divergence_lookback = self.thresholds.get("divergence_lookback", 14)

        close = df["close"]
        high = df["high"]
        low = df["low"]

        delta = close.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)

        avg_gain = _wilder_rma(gain, period)
        avg_loss = _wilder_rma(loss, period)

        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100.0 - (100.0 / (1.0 + rs))
        current_rsi = rsi.iloc[-1]

        if pd.isna(current_rsi):
            return self._make_result(Signal.NEUTRAL, "RSI data insufficient", {"rsi": None})

        # --- Embedded ADX/+DI/-DI for regime detection ---
        adx_value, plus_di, minus_di = self._compute_adx(high, low, close, period)
        in_trend = bool(not pd.isna(adx_value) and adx_value >= 25)
        plus_dominant = bool(
            not pd.isna(plus_di) and not pd.isna(minus_di) and plus_di > minus_di
        )

        # --- Divergence detection ---
        bullish_div, bearish_div = self._detect_divergence(
            close, rsi, divergence_lookback
        )

        # --- RSI 9-EMA cross ---
        rsi_ema = rsi.ewm(span=9, adjust=False).mean()
        rsi_above_ema = bool(current_rsi > rsi_ema.iloc[-1]) if not pd.isna(rsi_ema.iloc[-1]) else False

        raw = {
            "rsi": round(current_rsi, 2),
            "rsi_ema9": round(float(rsi_ema.iloc[-1]), 2) if not pd.isna(rsi_ema.iloc[-1]) else None,
            "adx": round(float(adx_value), 2) if not pd.isna(adx_value) else None,
            "regime": "TREND" if in_trend else "RANGE",
            "plus_di_dominant": plus_dominant,
            "bullish_divergence": bullish_div,
            "bearish_divergence": bearish_div,
        }

        # --- Determine base signal by regime ---
        if in_trend:
            if plus_dominant:  # Bull trend
                if current_rsi <= 30:
                    signal = Signal.STRONG_BUY
                    reason = f"Trend-mode bull pullback: RSI={current_rsi:.1f} ≤30"
                elif current_rsi <= 40:
                    signal = Signal.BUY
                    reason = f"Trend-mode bull pullback: RSI={current_rsi:.1f} ≤40"
                elif current_rsi >= 80:
                    signal = Signal.SELL
                    reason = f"Trend-mode bull overbought: RSI={current_rsi:.1f} ≥80"
                else:
                    signal = Signal.NEUTRAL
                    reason = f"Trend-mode bull neutral: RSI={current_rsi:.1f}"
            else:  # Bear trend
                if current_rsi >= 70:
                    signal = Signal.STRONG_SELL
                    reason = f"Trend-mode bear rally: RSI={current_rsi:.1f} ≥70"
                elif current_rsi >= 60:
                    signal = Signal.SELL
                    reason = f"Trend-mode bear rally: RSI={current_rsi:.1f} ≥60"
                elif current_rsi <= 20:
                    signal = Signal.BUY
                    reason = f"Trend-mode bear oversold: RSI={current_rsi:.1f} ≤20"
                else:
                    signal = Signal.NEUTRAL
                    reason = f"Trend-mode bear neutral: RSI={current_rsi:.1f}"
        else:
            # RANGE mode — classic mean-reversion thresholds
            if current_rsi <= strong_buy:
                signal = Signal.STRONG_BUY
                reason = f"Range-mode RSI={current_rsi:.1f} extremely oversold"
            elif current_rsi <= buy:
                signal = Signal.BUY
                reason = f"Range-mode RSI={current_rsi:.1f} oversold"
            elif current_rsi >= strong_sell:
                signal = Signal.STRONG_SELL
                reason = f"Range-mode RSI={current_rsi:.1f} extremely overbought"
            elif current_rsi >= sell:
                signal = Signal.SELL
                reason = f"Range-mode RSI={current_rsi:.1f} overbought"
            else:
                signal = Signal.NEUTRAL
                reason = f"Range-mode RSI={current_rsi:.1f} neutral"

        # --- Divergence boost (one degree stronger if direction matches) ---
        signal = self._apply_divergence(signal, bullish_div, bearish_div)
        if bullish_div and signal in (Signal.BUY, Signal.STRONG_BUY):
            reason += " | bullish divergence"
        if bearish_div and signal in (Signal.SELL, Signal.STRONG_SELL):
            reason += " | bearish divergence"

        # --- EMA-cross confirmation: dampen contrary signals ---
        if signal in (Signal.BUY, Signal.STRONG_BUY) and not rsi_above_ema:
            # RSI is below its EMA — buy signal is weaker
            if signal == Signal.STRONG_BUY:
                signal = Signal.BUY
                reason += " | (downgraded — RSI<EMA9)"
        elif signal in (Signal.SELL, Signal.STRONG_SELL) and rsi_above_ema:
            if signal == Signal.STRONG_SELL:
                signal = Signal.SELL
                reason += " | (downgraded — RSI>EMA9)"

        return self._make_result(signal, reason, raw)

    # ───── helpers ─────

    @staticmethod
    def _compute_adx(
        high: pd.Series, low: pd.Series, close: pd.Series, period: int
    ) -> tuple[float, float, float]:
        """Inline Wilder ADX/+DI/-DI computation. Returns (adx, +di, -di) at last bar."""
        plus_dm = high.diff()
        minus_dm = -low.diff()
        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        atr = _wilder_rma(tr, period).replace(0, np.nan)
        plus_di = 100.0 * (_wilder_rma(plus_dm, period) / atr)
        minus_di = 100.0 * (_wilder_rma(minus_dm, period) / atr)

        di_sum = (plus_di + minus_di).replace(0, np.nan)
        dx = 100.0 * ((plus_di - minus_di).abs() / di_sum)
        adx = _wilder_rma(dx, period)

        return float(adx.iloc[-1]), float(plus_di.iloc[-1]), float(minus_di.iloc[-1])

    @staticmethod
    def _detect_divergence(
        close: pd.Series, rsi: pd.Series, lookback: int
    ) -> tuple[bool, bool]:
        """Detect bullish/bearish RSI divergence over last `lookback` bars.

        Bullish: price made lower-low, RSI made higher-low.
        Bearish: price made higher-high, RSI made lower-high.
        """
        if len(close) < lookback + 2 or rsi.iloc[-lookback:].isna().any():
            return False, False

        close_window = close.iloc[-lookback:]
        rsi_window = rsi.iloc[-lookback:]

        # Compare last value to lookback-window extremum (skip last 2 bars to avoid noise)
        if lookback < 4:
            return False, False
        # Bullish: price lower-low, RSI higher-low
        price_min_idx = close_window.iloc[:-1].idxmin()
        rsi_at_price_min = rsi_window.loc[price_min_idx]
        bullish_div = (
            close.iloc[-1] < close_window.loc[price_min_idx]
            and rsi.iloc[-1] > rsi_at_price_min
        )

        # Bearish: price higher-high, RSI lower-high
        price_max_idx = close_window.iloc[:-1].idxmax()
        rsi_at_price_max = rsi_window.loc[price_max_idx]
        bearish_div = (
            close.iloc[-1] > close_window.loc[price_max_idx]
            and rsi.iloc[-1] < rsi_at_price_max
        )

        return bool(bullish_div), bool(bearish_div)

    @staticmethod
    def _apply_divergence(signal: Signal, bullish: bool, bearish: bool) -> Signal:
        """Strengthen signal one degree if divergence aligns with direction."""
        if bullish:
            if signal == Signal.NEUTRAL:
                return Signal.BUY
            if signal == Signal.BUY:
                return Signal.STRONG_BUY
        if bearish:
            if signal == Signal.NEUTRAL:
                return Signal.SELL
            if signal == Signal.SELL:
                return Signal.STRONG_SELL
        return signal
