"""CCXT-based backup data sources (per plan §4.6).

Activated only when Binance is in extended outage (>ccxt_outage_threshold_seconds
without successful WS messages or REST responses). Fetches OHLCV via Bybit
and OKX as fallback so the bot doesn't go fully blind.
"""

import time
from typing import Any, Optional

import pandas as pd

from showme.engine.utils.logger import get_logger

logger = get_logger("data.backup_sources")


class BackupExchange:
    """Lazy-instantiated CCXT exchanges. Spot/swap usable for OHLCV fallback only.

    Order books / order placement are NOT routed here — Binance remains the
    execution venue. This is purely a read-side fallback.
    """

    def __init__(self) -> None:
        self._bybit: Optional[Any] = None
        self._okx: Optional[Any] = None

    def _ensure_bybit(self):
        if self._bybit is None:
            try:
                import ccxt
                self._bybit = ccxt.bybit({
                    "options": {"defaultType": "swap"},
                    "enableRateLimit": True,
                })
            except Exception as e:
                logger.warning("Bybit init failed: %s", e)
                self._bybit = False
        return self._bybit if self._bybit else None

    def _ensure_okx(self):
        if self._okx is None:
            try:
                import ccxt
                self._okx = ccxt.okx({
                    "options": {"defaultType": "swap"},
                    "enableRateLimit": True,
                })
            except Exception as e:
                logger.warning("OKX init failed: %s", e)
                self._okx = False
        return self._okx if self._okx else None

    @staticmethod
    def _to_ccxt_symbol(binance_symbol: str) -> str:
        """BTCUSDT → BTC/USDT:USDT (swap notation used by CCXT)."""
        sym = binance_symbol.upper()
        if sym.endswith("USDT"):
            base = sym[:-4]
            return f"{base}/USDT:USDT"
        if sym.endswith("USDC"):
            base = sym[:-4]
            return f"{base}/USDC:USDC"
        return binance_symbol

    def fetch_ohlcv_fallback(
        self, symbol: str, timeframe: str = "1h", limit: int = 200
    ) -> Optional[pd.DataFrame]:
        """Try Bybit first, OKX second. Returns OHLCV DataFrame or None."""
        ccxt_sym = self._to_ccxt_symbol(symbol)

        for exch_name, getter in (("bybit", self._ensure_bybit), ("okx", self._ensure_okx)):
            ex = getter()
            if not ex:
                continue
            try:
                ohlcv = ex.fetch_ohlcv(ccxt_sym, timeframe, limit=limit)
                if not ohlcv:
                    continue
                df = pd.DataFrame(
                    ohlcv,
                    columns=["open_time", "open", "high", "low", "close", "volume"],
                )
                df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
                df["quote_volume"] = df["volume"] * df["close"]
                df["trades"] = 0
                df["taker_buy_base"] = df["volume"] * 0.5  # unknown — assume 50/50
                df["taker_buy_quote"] = df["quote_volume"] * 0.5
                df.attrs["symbol"] = symbol
                df.attrs["timeframe"] = timeframe
                df.attrs["source"] = exch_name
                logger.info("Backup OHLCV from %s: %s/%s %s rows", exch_name, symbol, timeframe, len(df))
                return df
            except Exception as e:
                logger.debug("%s fetch failed for %s: %s", exch_name, ccxt_sym, e)
                continue

        logger.warning("All CCXT backups failed for %s/%s", symbol, timeframe)
        return None


class FailoverState:
    """Tracks Binance health vs threshold, decides when to fail over."""

    def __init__(self, threshold_seconds: int = 180) -> None:
        self.threshold_seconds = threshold_seconds
        self._last_success_ts = time.time()
        self._failover_active = False

    def record_success(self) -> None:
        self._last_success_ts = time.time()
        if self._failover_active:
            logger.info("Binance recovery detected, deactivating CCXT failover")
            self._failover_active = False

    def record_failure(self) -> None:
        if not self._failover_active and self._is_outage():
            self._failover_active = True
            logger.warning(
                f"Binance outage >{self.threshold_seconds}s detected, activating CCXT failover"
            )

    def _is_outage(self) -> bool:
        return (time.time() - self._last_success_ts) > self.threshold_seconds

    @property
    def in_failover(self) -> bool:
        return self._failover_active or self._is_outage()
