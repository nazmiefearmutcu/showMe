"""Open Interest divergence indicator (per ShowMe audit D.5) — futures only.

4-scenario classification combining price change and OI change over N bars:
  PRICE↑ + OI↑ → healthy bull → BUY (≥strong_pct → STRONG_BUY)
  PRICE↑ + OI↓ → short squeeze (unsustainable) → SELL
  PRICE↓ + OI↑ → healthy bear (new shorts) → SELL
  PRICE↓ + OI↓ → long liquidation ending → BUY
  |both changes| < normal_pct → NEUTRAL
"""

from __future__ import annotations

import time
from typing import Any
import pandas as pd

from showme.engine.indicators.base import BaseIndicator, IndicatorResult, Signal


class OpenInterestIndicator(BaseIndicator):
    """Futures-only OI vs price divergence."""

    _cache: dict[tuple[str, str], tuple[float, list[dict]]] = {}
    _cache_ttl_sec = 60 * 5  # 5 minutes

    def __init__(
        self,
        config: dict[str, Any],
        binance_client: Any = None,
        cache: Any = None,
        store: Any = None,
    ) -> None:
        super().__init__(config)
        self.binance_client = binance_client
        self.cache = cache
        self.store = store

    @property
    def name(self) -> str:
        return "open_interest"

    def calculate(self, df: pd.DataFrame) -> IndicatorResult:
        if self.config.get("market_type") != "futures":
            return self._make_result(Signal.NEUTRAL, "OI N/A (spot mode)")

        symbol = df.attrs.get("symbol")
        if not symbol:
            return self._make_result(Signal.NEUTRAL, "OI: no symbol in df.attrs")

        period = self.thresholds.get("period", "1h")
        lookback_bars = self.thresholds.get("lookback_bars", 5)
        strong_pct = self.thresholds.get("strong_threshold_pct", 5.0) / 100.0
        normal_pct = self.thresholds.get("normal_threshold_pct", 2.0) / 100.0

        limit = max(lookback_bars + 10, 30)

        # Source preference: store > REST > cache (cache only has latest)
        oi_values: list[float] = []
        if self.store is not None:
            try:
                df_hist = self.store.query_oi(symbol, limit=limit)
                if df_hist is not None and len(df_hist) >= lookback_bars + 1:
                    # query_oi returns DESC; sort to ASC for lookback
                    df_hist = df_hist.sort_values("snapshot_time")
                    oi_values = [float(v) for v in df_hist["oi"].tolist()]
            except Exception:
                oi_values = []

        if not oi_values and self.binance_client is not None:
            history = self._get_oi(symbol, period=period, limit=limit)
            if not history or len(history) < lookback_bars + 1:
                return self._make_result(
                    Signal.NEUTRAL,
                    f"OI history insufficient ({len(history) if history else 0})",
                )
            try:
                oi_values = [float(r["sumOpenInterest"]) for r in history]
            except Exception:
                return self._make_result(Signal.NEUTRAL, "OI parse failed")

        if not oi_values:
            return self._make_result(Signal.NEUTRAL, "OI data unavailable")

        if len(oi_values) < lookback_bars + 1:
            return self._make_result(Signal.NEUTRAL, "OI series too short")

        oi_now = oi_values[-1]
        oi_then = oi_values[-lookback_bars - 1]
        if oi_then == 0:
            return self._make_result(Signal.NEUTRAL, "OI base zero")

        oi_change = (oi_now - oi_then) / oi_then

        # Price change over same lookback (from kline df)
        if len(df) < lookback_bars + 1:
            return self._make_result(Signal.NEUTRAL, "Price lookback too short for OI")
        price_now = float(df["close"].iloc[-1])
        price_then = float(df["close"].iloc[-lookback_bars - 1])
        if price_then == 0:
            return self._make_result(Signal.NEUTRAL, "Price base zero")
        price_change = (price_now - price_then) / price_then

        raw = {
            "oi_now": round(oi_now, 2),
            "oi_change_pct": round(oi_change * 100, 3),
            "price_change_pct": round(price_change * 100, 3),
            "lookback_bars": lookback_bars,
        }

        # Both small → NEUTRAL
        if abs(price_change) < normal_pct and abs(oi_change) < normal_pct:
            return self._make_result(
                Signal.NEUTRAL,
                f"OI flat: Δprice={price_change*100:.2f}% ΔOI={oi_change*100:.2f}%",
                raw,
            )

        # 4-scenario classification
        is_strong = abs(price_change) >= strong_pct or abs(oi_change) >= strong_pct

        if price_change > 0 and oi_change > 0:
            sig = Signal.STRONG_BUY if is_strong else Signal.BUY
            reason = f"Healthy bull: Δprice={price_change*100:.2f}%↑ ΔOI={oi_change*100:.2f}%↑"
        elif price_change > 0 and oi_change < 0:
            sig = Signal.STRONG_SELL if is_strong else Signal.SELL
            reason = "Short squeeze pump (unsustainable): Δprice↑ ΔOI↓"
        elif price_change < 0 and oi_change > 0:
            sig = Signal.STRONG_SELL if is_strong else Signal.SELL
            reason = "Healthy bear (new shorts): Δprice↓ ΔOI↑"
        elif price_change < 0 and oi_change < 0:
            sig = Signal.STRONG_BUY if is_strong else Signal.BUY
            reason = "Long liquidation ending: Δprice↓ ΔOI↓"
        else:
            sig = Signal.NEUTRAL
            reason = "OI mixed"

        return self._make_result(sig, reason, raw)

    def _get_oi(self, symbol: str, period: str, limit: int) -> list[dict]:
        key = (symbol, period)
        now = time.time()
        cached = self._cache.get(key)
        if cached and now - cached[0] < self._cache_ttl_sec:
            return cached[1]
        try:
            data = self.binance_client.get_open_interest_hist(
                symbol, period=period, limit=limit
            )
        except Exception:
            data = []
        if data:
            self._cache[key] = (now, data)
        return data
