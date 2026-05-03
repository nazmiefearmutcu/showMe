"""ROC (Rate of Change) v2 — momentum acceleration check (per ShowMe audit E.6).

Old logic emitted BUY whenever ROC > weak_threshold even when momentum was
decelerating (peak indicator). v2 requires momentum to be accelerating
to emit a directional signal.
"""

from typing import Any
import pandas as pd

from src.indicators.base import BaseIndicator, IndicatorResult, Signal


class ROCIndicator(BaseIndicator):
    @property
    def name(self) -> str:
        return "roc"

    def calculate(self, df: pd.DataFrame) -> IndicatorResult:
        period = self.thresholds.get("period", 12)
        strong_threshold = self.thresholds.get("strong_threshold", 5.0)
        weak_threshold = self.thresholds.get("weak_threshold", 1.0)

        close = df["close"]
        prev_close = close.shift(period)
        roc = ((close - prev_close) / prev_close) * 100.0

        if len(roc) < 2:
            return self._make_result(Signal.NEUTRAL, "ROC data insufficient")

        current_roc = roc.iloc[-1]
        prev_roc = roc.iloc[-2]

        if pd.isna(current_roc) or pd.isna(prev_roc):
            return self._make_result(Signal.NEUTRAL, "ROC data insufficient")

        accelerating = current_roc > prev_roc
        decelerating = current_roc < prev_roc

        raw = {
            "roc": round(float(current_roc), 3),
            "roc_prev": round(float(prev_roc), 3),
            "accelerating": accelerating,
            "decelerating": decelerating,
        }

        # Positive ROC
        if current_roc > strong_threshold:
            if accelerating:
                return self._make_result(
                    Signal.STRONG_BUY,
                    f"ROC={current_roc:.2f}% strong + accelerating",
                    raw,
                )
            return self._make_result(
                Signal.NEUTRAL,
                f"ROC={current_roc:.2f}% strong but decelerating (peak risk)",
                raw,
            )
        if current_roc > weak_threshold:
            if accelerating:
                return self._make_result(
                    Signal.BUY,
                    f"ROC={current_roc:.2f}% positive + accelerating",
                    raw,
                )
            return self._make_result(
                Signal.NEUTRAL,
                f"ROC={current_roc:.2f}% positive but decelerating",
                raw,
            )

        # Negative ROC
        if current_roc < -strong_threshold:
            if decelerating:
                return self._make_result(
                    Signal.STRONG_SELL,
                    f"ROC={current_roc:.2f}% strongly negative + falling",
                    raw,
                )
            return self._make_result(
                Signal.NEUTRAL,
                f"ROC={current_roc:.2f}% strongly negative but recovering (bottom risk)",
                raw,
            )
        if current_roc < -weak_threshold:
            if decelerating:
                return self._make_result(
                    Signal.SELL,
                    f"ROC={current_roc:.2f}% negative + falling",
                    raw,
                )
            return self._make_result(
                Signal.NEUTRAL,
                f"ROC={current_roc:.2f}% negative but recovering",
                raw,
            )

        return self._make_result(Signal.NEUTRAL, f"ROC={current_roc:.2f}% flat", raw)
