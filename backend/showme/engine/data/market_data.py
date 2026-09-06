"""Market data retrieval and OHLCV DataFrame construction.

Resolution order (per plan §5):
  1. MarketCache (live WS data) — < 1 ms
  2. MarketStore (persisted DuckDB) — < 10 ms
  3. REST API (legacy fallback) — 50–200 ms

Feature-flagged via config.data_pipeline.use_ws_cache. When false, behaves
exactly as the original REST-only implementation (backward compatible).

F7 (MED): cache/store acceptance is NOT purely row-count based anymore — a
staleness TTL guards the WS-fed paths. If the newest cached candle (or funding
mark price) is older than ``WS_STALENESS_TTL_MULTIPLE × timeframe``, the data
is considered frozen (dead WS feed) and the provider falls through to REST
instead of serving plausible-but-wrong prices.
"""

from datetime import datetime, timezone
from typing import Any, Optional

import pandas as pd

from showme.engine.api.binance_client import BinanceClient
from showme.engine.utils.logger import get_logger

logger = get_logger("data.market_data")

KLINE_COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "trades", "taker_buy_base",
    "taker_buy_quote", "ignore",
]

# F7: a cached frame whose newest candle is older than N × timeframe is
# treated as frozen. A live WS feed refreshes the current (forming) candle
# continuously, so even a quiet market stays well under 1× timeframe; 3×
# tolerates a couple of missed updates before falling back to REST.
WS_STALENESS_TTL_MULTIPLE = 3

_TIMEFRAME_UNIT_MS = {"s": 1_000, "m": 60_000, "h": 3_600_000, "d": 86_400_000, "w": 604_800_000}


def _timeframe_ms(timeframe: str) -> Optional[int]:
    """Parse a Binance-style timeframe ('1m', '4h', '1d') to milliseconds."""
    try:
        unit = timeframe[-1].lower()
        value = int(timeframe[:-1])
        return value * _TIMEFRAME_UNIT_MS[unit]
    except (TypeError, ValueError, KeyError, IndexError):
        return None


class MarketDataProvider:
    """Fetches and transforms market data into OHLCV DataFrames.

    Optionally reads from MarketCache / MarketStore when use_ws_cache=true.
    Falls back to REST otherwise (legacy behavior preserved).
    """

    def __init__(
        self,
        binance_client: BinanceClient,
        config: dict[str, Any],
        cache: Optional[Any] = None,
        store: Optional[Any] = None,
    ) -> None:
        self.client = binance_client
        self.config = config
        self.timeframe = config.get("timeframe", "1h")
        self.candle_limit = config.get("candle_limit", 200)

        dp = config.get("data_pipeline", {}) or {}
        self.use_ws_cache = bool(dp.get("use_ws_cache", False))
        self.rest_fallback_enabled = bool(dp.get("rest_fallback_enabled", True))
        # When provided, the bot wires these up from BotService — drop-in safe
        self.cache = cache
        self.store = store

    def get_ohlcv(self, symbol: str) -> Optional[pd.DataFrame]:
        """Resolve OHLCV from cache → store → REST in order, per feature flag."""
        # 1. Live cache (live tick + recent closed candles)
        if self.use_ws_cache and self.cache is not None:
            df = self._from_cache(symbol)
            if (
                df is not None
                and len(df) >= max(50, int(self.candle_limit * 0.5))
                and not self._is_stale(df, symbol, source="cache")
            ):
                return self._finalize(df, symbol)

        # 2. Persistent store (DuckDB)
        if self.use_ws_cache and self.store is not None:
            df = self._from_store(symbol)
            if (
                df is not None
                and len(df) >= 50
                and not self._is_stale(df, symbol, source="store")
            ):
                return self._finalize(df, symbol)

        # 3. REST (legacy)
        if self.use_ws_cache and not self.rest_fallback_enabled:
            logger.warning(
                f"No cache/store data for {symbol} {self.timeframe} and REST fallback disabled"
            )
            return None
        return self._from_rest(symbol)

    # ── staleness TTL (F7) ─────────────────────────────────

    def _is_stale(self, df: pd.DataFrame, symbol: str, source: str = "cache") -> bool:
        """True when the newest candle is older than N × timeframe.

        Guards the WS-fed cache/store paths against a dead feed: without this
        check a frozen frame of up-to-1000 plausible candles would be served
        forever and trade/SL/TP decisions would run on a stale price. If the
        timeframe cannot be parsed or the frame carries no usable open_time,
        the check is skipped (returns False) to keep the legacy behaviour.
        """
        tf_ms = _timeframe_ms(self.timeframe)
        if tf_ms is None:
            return False
        last_open = self._last_open_time(df)
        if last_open is None:
            return False
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        age_ms = now_ms - last_open
        if age_ms > WS_STALENESS_TTL_MULTIPLE * tf_ms:
            logger.warning(
                "Stale %s data for %s %s: newest candle %s ms old "
                "(TTL %s ms) — falling through to REST",
                source, symbol, self.timeframe, age_ms,
                WS_STALENESS_TTL_MULTIPLE * tf_ms,
            )
            return True
        return False

    @staticmethod
    def _last_open_time(df: pd.DataFrame) -> Optional[int]:
        """Newest candle open_time as epoch ms, or None when unavailable."""
        if "open_time" not in df.columns or df.empty:
            return None
        try:
            value = df["open_time"].iloc[-1]
        except Exception:
            return None
        try:
            if isinstance(value, pd.Timestamp):
                return int(value.value // 1_000_000)
            if hasattr(value, "timestamp"):
                return int(value.timestamp() * 1000)
            return int(value)
        except (TypeError, ValueError):
            return None

    # ── source: cache ──────────────────────────────────────

    def _from_cache(self, symbol: str) -> Optional[pd.DataFrame]:
        try:
            df = self.cache.get_ohlcv(symbol, self.timeframe, n=self.candle_limit)
            if df is None or df.empty:
                return None
            return df
        except Exception as e:
            logger.debug("cache read failed for %s/%s: %s", symbol, self.timeframe, e)
            return None

    # ── source: store ──────────────────────────────────────

    def _from_store(self, symbol: str) -> Optional[pd.DataFrame]:
        try:
            df = self.store.query_candles(symbol, self.timeframe, limit=self.candle_limit)
            if df is None or df.empty:
                return None
            return df
        except Exception as e:
            logger.debug("store read failed for %s/%s: %s", symbol, self.timeframe, e)
            return None

    # ── source: REST (legacy) ──────────────────────────────

    def _from_rest(self, symbol: str) -> Optional[pd.DataFrame]:
        raw_klines = self.client.get_klines(
            symbol=symbol,
            interval=self.timeframe,
            limit=self.candle_limit,
        )

        if not raw_klines:
            logger.error("No kline data returned for %s", symbol)
            return None

        try:
            df = pd.DataFrame(raw_klines, columns=KLINE_COLUMNS)

            for col in ["open", "high", "low", "close", "volume", "quote_volume",
                         "taker_buy_base", "taker_buy_quote"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")

            df["trades"] = pd.to_numeric(df["trades"], errors="coerce").astype(int)
            df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
            df["close_time"] = pd.to_datetime(df["close_time"], unit="ms")

            df = df.drop(columns=["ignore"])
            df = df.dropna(subset=["open", "high", "low", "close", "volume"])
            df = df.reset_index(drop=True)

            return self._finalize(df, symbol)

        except Exception as e:
            logger.error("Error processing OHLCV data for %s: %s", symbol, e)
            return None

    def _finalize(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """Attach attrs and log. Centralizes the legacy log line."""
        df.attrs["symbol"] = symbol
        df.attrs["timeframe"] = self.timeframe

        try:
            last_close = float(df["close"].iloc[-1])
        except Exception:
            last_close = float("nan")
        logger.info(
            f"OHLCV loaded | {symbol} | {self.timeframe} | {len(df)} candles | "
            f"latest close={last_close:.6f}"
        )
        return df

    def get_current_price(self, symbol: str) -> Optional[float]:
        """Get the latest price for a symbol.

        Prefer cache funding mark price if available; fallback to ticker REST.
        F7: the cached mark price honours the same N × timeframe staleness TTL
        as the candle path — a dead WS feed must not serve a frozen price.
        """
        if self.use_ws_cache and self.cache is not None:
            f = self.cache.get_funding(symbol)
            if f and f.get("mark_price"):
                tf_ms = _timeframe_ms(self.timeframe)
                updated_ms = f.get("time")
                fresh = True
                if tf_ms is not None and updated_ms:
                    try:
                        age_ms = int(datetime.now(timezone.utc).timestamp() * 1000) - int(updated_ms)
                        fresh = age_ms <= WS_STALENESS_TTL_MULTIPLE * tf_ms
                        if not fresh:
                            logger.warning(
                                "Stale funding mark price for %s: %s ms old "
                                "(TTL %s ms) — falling through to REST ticker",
                                symbol, age_ms, WS_STALENESS_TTL_MULTIPLE * tf_ms,
                            )
                    except (TypeError, ValueError):
                        fresh = True
                if fresh:
                    return float(f["mark_price"])
        return self.client.get_ticker_price(symbol)

    def get_symbol_info(self, symbol: str) -> Optional[dict]:
        """Get symbol exchange info (filters, precision, etc.)."""
        return self.client.get_symbol_info(symbol)
