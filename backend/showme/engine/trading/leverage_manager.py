"""Dynamic leverage manager - scales leverage based on confidence and exchange limits.

Reference scale (from BTC):
  - BTC max leverage on Binance Futures = 125x
  - At 100% confidence -> 100x leverage (80% of max)
  - Scale ratio = 100/125 = 0.80
  - Formula: leverage = max_leverage * SCALE_RATIO * (confidence / 100)
  - Minimum leverage = 2x (no leverageless futures trading)
"""

import time
from collections import OrderedDict
from typing import Any, Optional

from showme.engine.utils.logger import get_logger

logger = get_logger("trading.leverage_manager")

# BTC reference: 100x at full confidence on 125x max = 80%
SCALE_RATIO = 0.80
MIN_LEVERAGE = 2
DEFAULT_MAX_LEVERAGE = 20  # Fallback if exchange info unavailable

# C7 fix: max-leverage cache used to grow without bound and never expire,
# so a long-running bot session would (1) accumulate entries for every
# symbol it ever traded, (2) keep stale values forever even after Binance
# revised the bracket. Add a TTL + LRU cap.
_CACHE_TTL_S = 300.0
_CACHE_MAX_ENTRIES = 50


class LeverageManager:
    """Calculates dynamic leverage based on confidence score and exchange limits."""

    def __init__(self, config: dict[str, Any], binance_client: Any = None) -> None:
        self.config = config
        self.binance_client = binance_client
        # OrderedDict so we can evict LRU when capacity is exceeded.
        # Value layout: ``(max_leverage, expires_at_epoch)``.
        self._max_leverage_cache: "OrderedDict[str, tuple[int, float]]" = OrderedDict()
        leverage_config = config.get("leverage", {})
        self.scale_ratio = leverage_config.get("scale_ratio", SCALE_RATIO)
        self.min_leverage = leverage_config.get("min_leverage", MIN_LEVERAGE)
        self.enabled = leverage_config.get("enabled", True)
        self._cache_ttl_s = float(leverage_config.get("cache_ttl_s", _CACHE_TTL_S))
        self._cache_max_entries = int(leverage_config.get("cache_max_entries", _CACHE_MAX_ENTRIES))

    def get_max_leverage(self, symbol: str) -> int:
        """Get the maximum leverage allowed for a symbol on Binance Futures.

        Uses a bounded TTL cache to avoid repeated API calls while still
        letting bracket updates from Binance propagate in a reasonable window.
        """
        now = time.time()
        cached = self._max_leverage_cache.get(symbol)
        if cached is not None:
            value, expires_at = cached
            if expires_at > now:
                # Refresh LRU recency on hit.
                self._max_leverage_cache.move_to_end(symbol)
                return value
            # Expired — fall through and re-fetch.
            self._max_leverage_cache.pop(symbol, None)

        max_lev = DEFAULT_MAX_LEVERAGE

        if self.binance_client:
            try:
                info = self.binance_client.get_symbol_info(symbol)
                if info:
                    # Binance futures symbol info contains bracket leverage info
                    # The 'maxLeverage' is not directly in symbol info for futures,
                    # but we can check leverage brackets via the API
                    brackets = self._fetch_leverage_brackets(symbol)
                    if brackets:
                        max_lev = brackets
                    else:
                        # Fallback: use common known values
                        max_lev = self._get_known_max_leverage(symbol)
            except Exception as e:
                logger.warning(f"Failed to fetch max leverage for {symbol}: {e}")
                max_lev = self._get_known_max_leverage(symbol)
        else:
            max_lev = self._get_known_max_leverage(symbol)

        self._cache_put(symbol, max_lev, now)
        logger.info(f"Max leverage for {symbol}: {max_lev}x")
        return max_lev

    def _cache_put(self, symbol: str, value: int, now: float) -> None:
        self._max_leverage_cache[symbol] = (value, now + self._cache_ttl_s)
        self._max_leverage_cache.move_to_end(symbol)
        while len(self._max_leverage_cache) > self._cache_max_entries:
            self._max_leverage_cache.popitem(last=False)

    def _fetch_leverage_brackets(self, symbol: str) -> Optional[int]:
        """Fetch leverage brackets from Binance Futures API."""
        try:
            client = self.binance_client.client
            # futures_leverage_bracket returns bracket info per symbol
            brackets = client.futures_leverage_bracket(symbol=symbol)
            if brackets and len(brackets) > 0:
                bracket_data = brackets[0]
                bracket_list = bracket_data.get("brackets", [])
                if bracket_list:
                    # First bracket has the highest leverage (smallest notional)
                    max_lev = bracket_list[0].get("initialLeverage", DEFAULT_MAX_LEVERAGE)
                    return int(max_lev)
        except Exception as e:
            logger.debug(f"Leverage bracket API call failed for {symbol}: {e}")
        return None

    def _get_known_max_leverage(self, symbol: str) -> int:
        """Fallback: return known max leverage for popular symbols."""
        known = {
            "BTCUSDT": 125,
            "ETHUSDT": 100,
            "BNBUSDT": 75,
            "XRPUSDT": 75,
            "ADAUSDT": 75,
            "DOGEUSDT": 75,
            "SOLUSDT": 75,
            "DOTUSDT": 75,
            "AVAXUSDT": 75,
            "MATICUSDT": 75,
            "LINKUSDT": 75,
            "LTCUSDT": 75,
            "TRXUSDT": 75,
            "ATOMUSDT": 50,
            "NEARUSDT": 50,
            "UNIUSDT": 50,
            "AAVEUSDT": 50,
            "APTUSDT": 50,
            "ARBUSDT": 50,
            "OPUSDT": 50,
            "SHIBUSDT": 50,
            "PEPEUSDT": 50,
            "WIFUSDT": 50,
            "BLUAIUSDT": 25,
            "BEATUSDT": 25,
        }
        return known.get(symbol, DEFAULT_MAX_LEVERAGE)

    def calculate_leverage(
        self, symbol: str, confidence: int, sl_distance_pct: float | None = None,
    ) -> int:
        """Calculate dynamic leverage based on confidence and symbol max leverage.

        Formula:
          max_usable = max_exchange_leverage * scale_ratio
          leverage = max_usable * (confidence / 100)
          leverage = clamp(min_leverage, max_exchange_leverage)

        Q4 audit H14 fix: when ``sl_distance_pct`` is provided (e.g. 0.025 ==
        2.5%), the leverage is additionally clamped so that the liquidation
        price stays at least 2× the stop distance away from entry. Without
        this clamp, a 100× leverage paired with a 2.5% SL means the SL is
        25× past liquidation — the position liquidates before the stop fires.

        Heuristic: liquidation_distance ≈ 1/leverage, so we require
        ``1/leverage >= 2 × sl_distance_pct`` ⇒ ``leverage <= 0.5/sl_distance_pct``.
        We additionally factor a small safety buffer (0.8 instead of 1.0)
        to leave room for maintenance margin.

        Example (BTC, 125x max, scale_ratio=0.80):
          confidence=100% -> 125 * 0.80 * 1.00 = 100x
          confidence=100%, sl=2.5% -> min(100, 0.8/0.025) = min(100, 32) = 32x
        """
        if not self.enabled:
            return 1

        max_exchange = self.get_max_leverage(symbol)
        max_usable = max_exchange * self.scale_ratio
        raw_leverage = max_usable * (confidence / 100.0)

        # Q4 audit H14: SL-distance-aware leverage cap.
        if sl_distance_pct is not None and sl_distance_pct > 0:
            sl_cap = 0.8 / float(sl_distance_pct)
            if sl_cap < raw_leverage:
                logger.info(
                    f"Leverage capped by SL distance: sl={sl_distance_pct:.4%} "
                    f"⇒ max={sl_cap:.2f}x (was {raw_leverage:.2f}x)"
                )
                raw_leverage = sl_cap

        # Clamp between min and max
        leverage = int(max(self.min_leverage, min(round(raw_leverage), max_exchange)))

        logger.info(
            f"Leverage calc | {symbol} | confidence={confidence}% | "
            f"max_exchange={max_exchange}x | calculated={leverage}x"
        )
        return leverage

    def clear_cache(self) -> None:
        """Clear the max leverage cache (e.g., on symbol change)."""
        self._max_leverage_cache.clear()
