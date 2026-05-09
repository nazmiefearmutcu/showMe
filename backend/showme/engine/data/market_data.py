"""Market data retrieval and OHLCV DataFrame construction.

Resolution order (per plan §5):
  1. MarketCache (live WS data) — < 1 ms
  2. MarketStore (persisted DuckDB) — < 10 ms
  3. REST API (legacy fallback) — 50–200 ms

Feature-flagged via config.data_pipeline.use_ws_cache. When false, behaves
exactly as the original REST-only implementation (backward compatible).
"""

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
            if df is not None and len(df) >= max(50, int(self.candle_limit * 0.5)):
                return self._finalize(df, symbol)

        # 2. Persistent store (DuckDB)
        if self.use_ws_cache and self.store is not None:
            df = self._from_store(symbol)
            if df is not None and len(df) >= 50:
                return self._finalize(df, symbol)

        # 3. REST (legacy)
        if self.use_ws_cache and not self.rest_fallback_enabled:
            logger.warning(
                f"No cache/store data for {symbol} {self.timeframe} and REST fallback disabled"
            )
            return None
        return self._from_rest(symbol)

    # ── source: cache ──────────────────────────────────────

    def _from_cache(self, symbol: str) -> Optional[pd.DataFrame]:
        try:
            df = self.cache.get_ohlcv(symbol, self.timeframe, n=self.candle_limit)
            if df is None or df.empty:
                return None
            return df
        except Exception as e:
            logger.debug(f"cache read failed for {symbol}/{self.timeframe}: {e}")
            return None

    # ── source: store ──────────────────────────────────────

    def _from_store(self, symbol: str) -> Optional[pd.DataFrame]:
        try:
            df = self.store.query_candles(symbol, self.timeframe, limit=self.candle_limit)
            if df is None or df.empty:
                return None
            return df
        except Exception as e:
            logger.debug(f"store read failed for {symbol}/{self.timeframe}: {e}")
            return None

    # ── source: REST (legacy) ──────────────────────────────

    def _from_rest(self, symbol: str) -> Optional[pd.DataFrame]:
        raw_klines = self.client.get_klines(
            symbol=symbol,
            interval=self.timeframe,
            limit=self.candle_limit,
        )

        if not raw_klines:
            logger.error(f"No kline data returned for {symbol}")
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
            logger.error(f"Error processing OHLCV data for {symbol}: {e}")
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
        """
        if self.use_ws_cache and self.cache is not None:
            f = self.cache.get_funding(symbol)
            if f and f.get("mark_price"):
                return float(f["mark_price"])
        return self.client.get_ticker_price(symbol)

    def get_symbol_info(self, symbol: str) -> Optional[dict]:
        """Get symbol exchange info (filters, precision, etc.)."""
        return self.client.get_symbol_info(symbol)
