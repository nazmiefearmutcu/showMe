"""Liquidation Pressure indicator (per plan §9 — futures only).

Reads from MarketCache populated by `!forceOrder@arr` WS stream.
Strategy: large-side liquidation imbalance is a contrarian short-term
signal — heavy long liquidations often mark capitulation lows; heavy
short liquidations often mark squeeze tops.
"""

import time
from typing import Any, Optional

import pandas as pd
import numpy as np

from src.indicators.base import BaseIndicator, IndicatorResult, Signal


class LiquidationPressureIndicator(BaseIndicator):
    """Futures-only. Requires WS cache. NEUTRAL when no liq data available."""

    def __init__(
        self,
        config: dict[str, Any],
        cache: Any = None,
        store: Any = None,
    ) -> None:
        super().__init__(config)
        self.cache = cache
        self.store = store

    @property
    def name(self) -> str:
        return "liquidation_pressure"

    def calculate(self, df: pd.DataFrame) -> IndicatorResult:
        if self.config.get("market_type") != "futures":
            return self._make_result(Signal.NEUTRAL, "Liquidation N/A (spot mode)")

        symbol = df.attrs.get("symbol")
        if not symbol:
            return self._make_result(Signal.NEUTRAL, "No symbol in df.attrs")

        window_min = self.thresholds.get("window_minutes", 60)
        strong_imbalance = self.thresholds.get("strong_imbalance_ratio", 3.0)
        weak_imbalance = self.thresholds.get("weak_imbalance_ratio", 1.5)
        min_total_notional = self.thresholds.get("min_total_notional", 100_000.0)

        since_ms = int(time.time() * 1000) - window_min * 60 * 1000

        # Source preference: cache > store
        liqs: Optional[pd.DataFrame] = None
        if self.cache is not None:
            liqs = self.cache.get_liquidations(symbol, since_ms=since_ms)
        if (liqs is None or liqs.empty) and self.store is not None:
            liqs = self.store.query_liquidations(symbol, since_ms=since_ms, limit=2000)

        if liqs is None or liqs.empty:
            return self._make_result(
                Signal.NEUTRAL, f"No liquidations in last {window_min}m"
            )

        # Compute notional per side
        # In Binance forceOrder, side='BUY' means a SHORT position was liquidated (forced buy-back)
        # side='SELL' means a LONG was liquidated (forced sell)
        # So:
        #   BUY (short liquidations) → short squeeze pressure → bearish exhaustion → BUY signal
        #   SELL (long liquidations) → long capitulation → bullish reversal → BUY signal
        # We compute pure imbalance: big BUY-side liqs (shorts trapped) vs big SELL-side (longs trapped)
        try:
            liqs = liqs.copy()
            liqs["notional"] = liqs["price"].astype(float) * liqs["quantity"].astype(float)
            short_liq = float(liqs.loc[liqs["side"] == "BUY", "notional"].sum())
            long_liq = float(liqs.loc[liqs["side"] == "SELL", "notional"].sum())
        except Exception as e:
            return self._make_result(Signal.NEUTRAL, f"Liq parse error: {e}")

        total = short_liq + long_liq
        if total < min_total_notional:
            return self._make_result(
                Signal.NEUTRAL,
                f"Liq notional {total:.0f} < min {min_total_notional:.0f}",
                {"short_liq": short_liq, "long_liq": long_liq, "total": total},
            )

        # Imbalance ratio (bigger side / smaller side)
        if long_liq > short_liq:
            ratio = long_liq / max(short_liq, 1.0)
            dominant = "LONG_LIQ"
        else:
            ratio = short_liq / max(long_liq, 1.0)
            dominant = "SHORT_LIQ"

        raw = {
            "short_liq_notional": round(short_liq, 2),
            "long_liq_notional": round(long_liq, 2),
            "total": round(total, 2),
            "imbalance_ratio": round(ratio, 2),
            "dominant": dominant,
            "window_min": window_min,
        }

        # Capitulation patterns
        if dominant == "LONG_LIQ":
            # Heavy long liquidations → potential bottom (contrarian BUY)
            if ratio >= strong_imbalance:
                return self._make_result(
                    Signal.STRONG_BUY,
                    f"Heavy long capitulation ({ratio:.1f}× imbalance, {long_liq:.0f} USDT)",
                    raw,
                )
            if ratio >= weak_imbalance:
                return self._make_result(
                    Signal.BUY,
                    f"Long liquidation pressure ({ratio:.1f}× imbalance)",
                    raw,
                )
        else:  # SHORT_LIQ dominant
            if ratio >= strong_imbalance:
                return self._make_result(
                    Signal.STRONG_SELL,
                    f"Heavy short squeeze ({ratio:.1f}× imbalance, {short_liq:.0f} USDT)",
                    raw,
                )
            if ratio >= weak_imbalance:
                return self._make_result(
                    Signal.SELL,
                    f"Short liquidation pressure ({ratio:.1f}× imbalance)",
                    raw,
                )

        return self._make_result(
            Signal.NEUTRAL,
            f"Liquidations balanced (ratio={ratio:.2f})",
            raw,
        )
