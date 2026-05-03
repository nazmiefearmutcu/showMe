"""Funding Rate indicator (per ShowMe audit D.4) — futures only.

Contrarian signal: extreme positive funding = longs crowded = squeeze risk.
Uses z-score over a 30-day rolling window of the 8-hour funding cycles.
"""

import time
from typing import Any
import pandas as pd
import numpy as np

from src.indicators.base import BaseIndicator, IndicatorResult, Signal


class FundingRateIndicator(BaseIndicator):
    """Futures-only sentiment indicator. NEUTRAL in spot mode."""

    # Per-process cache: {symbol: (timestamp, list_of_dicts)}
    _cache: dict[str, tuple[float, list[dict]]] = {}
    _cache_ttl_sec = 60 * 30  # 30 minutes — funding cycle is 8h, 30min refresh fine

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
        return "funding_rate"

    def calculate(self, df: pd.DataFrame) -> IndicatorResult:
        # Spot mode → no funding rate
        if self.config.get("market_type") != "futures":
            return self._make_result(Signal.NEUTRAL, "Funding rate N/A (spot mode)")

        symbol = df.attrs.get("symbol")
        if not symbol:
            return self._make_result(Signal.NEUTRAL, "Funding rate: no symbol in df.attrs")

        history_days = self.thresholds.get("history_days", 30)
        z_strong = self.thresholds.get("z_score_strong", 2.5)
        z_normal = self.thresholds.get("z_score_normal", 1.5)

        # 8-hour cycles → 3 per day
        limit = max(history_days * 3, 50)

        # Source preference: store > REST (cache holds only latest tick, not 8h cycles)
        rates: list[float] = []
        if self.store is not None:
            try:
                df_hist = self.store.query_funding(symbol, limit=limit)
                if df_hist is not None and len(df_hist) >= 10:
                    rates = [float(r) for r in df_hist["rate"].tolist() if r is not None]
            except Exception:
                rates = []

        if not rates and self.binance_client is not None:
            history = self._get_funding(symbol, limit=limit)
            if history and len(history) >= 10:
                rates = [float(r.get("fundingRate", 0)) for r in history]

        if not rates and self.cache is not None:
            f = self.cache.get_funding(symbol)
            if f and f.get("rate") is not None:
                rates = [float(f["rate"])]

        if len(rates) < 10:
            return self._make_result(
                Signal.NEUTRAL, f"Funding rate history insufficient ({len(rates)})"
            )
        rates = [r for r in rates if not np.isnan(r)]
        if len(rates) < 10:
            return self._make_result(Signal.NEUTRAL, "Funding rate cleaned series too small")

        current_fr = rates[-1]
        history_window = rates[-history_days * 3 :] if len(rates) >= 30 else rates
        avg = float(np.mean(history_window))
        std = float(np.std(history_window))
        fr_z = (current_fr - avg) / std if std > 0 else 0.0

        raw = {
            "current_fr": round(current_fr, 8),
            "fr_avg": round(avg, 8),
            "fr_std": round(std, 8),
            "fr_z": round(fr_z, 3),
            "history_count": len(history_window),
        }

        # Contrarian: positive funding = longs crowded = SELL bias
        if fr_z > z_strong:
            return self._make_result(
                Signal.STRONG_SELL,
                f"Funding extreme positive (z={fr_z:.2f}) — longs squeeze risk",
                raw,
            )
        if fr_z > z_normal:
            return self._make_result(
                Signal.SELL, f"Funding elevated (z={fr_z:.2f}) — long crowding", raw
            )
        if fr_z < -z_strong:
            return self._make_result(
                Signal.STRONG_BUY,
                f"Funding extreme negative (z={fr_z:.2f}) — shorts squeeze risk",
                raw,
            )
        if fr_z < -z_normal:
            return self._make_result(
                Signal.BUY, f"Funding depressed (z={fr_z:.2f}) — short crowding", raw
            )
        return self._make_result(
            Signal.NEUTRAL, f"Funding within normal range (z={fr_z:.2f})", raw
        )

    def _get_funding(self, symbol: str, limit: int) -> list[dict]:
        """Fetch with per-symbol cache."""
        now = time.time()
        cached = self._cache.get(symbol)
        if cached and now - cached[0] < self._cache_ttl_sec:
            return cached[1]
        try:
            data = self.binance_client.get_funding_rate(symbol, limit=limit)
        except Exception:
            data = []
        if data:
            self._cache[symbol] = (now, data)
        return data
