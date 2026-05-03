"""Thread-safe in-memory cache for live market data (per plan §4.3).

Indicators consume from here directly — single-digit-microsecond reads.
WS manager is the single writer; readers are concurrent.
"""

import threading
import time
from collections import defaultdict, deque
from typing import Any, Optional

import pandas as pd

from src.utils.logger import get_logger

logger = get_logger("data.market_cache")


class MarketCache:
    """Thread-safe in-memory cache for candles, agg trades, funding, OI, liquidations."""

    def __init__(self, max_candles: int = 1000, max_trades: int = 10_000) -> None:
        self._candles: dict[tuple[str, str], deque] = defaultdict(
            lambda: deque(maxlen=max_candles)
        )
        self._agg_trades: dict[str, deque] = defaultdict(
            lambda: deque(maxlen=max_trades)
        )
        self._funding: dict[str, dict[str, Any]] = {}
        self._oi: dict[str, dict[str, Any]] = {}
        self._liquidations: dict[str, deque] = defaultdict(lambda: deque(maxlen=2000))
        self._lock = threading.RLock()
        self._max_candles = max_candles
        self._max_trades = max_trades

        # Health metrics
        self._stats = {
            "last_kline_ms": 0,
            "last_trade_ms": 0,
            "last_funding_ms": 0,
            "last_oi_ms": 0,
            "last_liq_ms": 0,
            "kline_count": 0,
            "trade_count": 0,
            "liq_count": 0,
        }

    # ── candles ──────────────────────────────────────────────

    def update_candle(self, symbol: str, timeframe: str, row: dict[str, Any]) -> None:
        """Append/replace a kline row. Same open_time → replace (live tick update)."""
        with self._lock:
            buf = self._candles[(symbol, timeframe)]
            if buf and buf[-1].get("open_time") == row.get("open_time"):
                buf[-1] = row
            else:
                buf.append(row)
            self._stats["last_kline_ms"] = int(time.time() * 1000)
            self._stats["kline_count"] += 1

    def get_ohlcv(
        self, symbol: str, timeframe: str, n: int = 500
    ) -> pd.DataFrame:
        """Return last n candles as DataFrame. Empty DataFrame if no data."""
        with self._lock:
            buf = list(self._candles[(symbol, timeframe)])[-n:]
        if not buf:
            return pd.DataFrame()
        df = pd.DataFrame(buf)
        # Standardize: ensure required columns
        for col in ["open", "high", "low", "close", "volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        if "open_time" in df.columns:
            df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", errors="coerce")
        df.attrs["symbol"] = symbol
        df.attrs["timeframe"] = timeframe
        return df.reset_index(drop=True)

    def candle_count(self, symbol: str, timeframe: str) -> int:
        with self._lock:
            return len(self._candles[(symbol, timeframe)])

    # ── agg_trades ──────────────────────────────────────────

    def update_agg_trade(self, symbol: str, trade: dict[str, Any]) -> None:
        with self._lock:
            self._agg_trades[symbol].append(trade)
            self._stats["last_trade_ms"] = int(time.time() * 1000)
            self._stats["trade_count"] += 1

    def get_agg_trades(self, symbol: str, since_ms: Optional[int] = None) -> pd.DataFrame:
        """Return trades since `since_ms` (epoch ms). All if None."""
        with self._lock:
            trades = list(self._agg_trades[symbol])
        if since_ms is not None:
            trades = [t for t in trades if t.get("trade_time", 0) >= since_ms]
        if not trades:
            return pd.DataFrame()
        return pd.DataFrame(trades)

    # ── funding rate ────────────────────────────────────────

    def update_funding(
        self, symbol: str, rate: float, mark_price: float, t: int
    ) -> None:
        with self._lock:
            self._funding[symbol] = {
                "rate": rate, "mark_price": mark_price, "time": t
            }
            self._stats["last_funding_ms"] = int(time.time() * 1000)

    def get_funding(self, symbol: str) -> Optional[dict[str, Any]]:
        with self._lock:
            return dict(self._funding[symbol]) if symbol in self._funding else None

    def get_all_funding(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {k: dict(v) for k, v in self._funding.items()}

    # ── open interest ───────────────────────────────────────

    def update_oi(self, symbol: str, oi: float, oi_value: float, t: int) -> None:
        with self._lock:
            self._oi[symbol] = {"oi": oi, "oi_value": oi_value, "time": t}
            self._stats["last_oi_ms"] = int(time.time() * 1000)

    def get_oi(self, symbol: str) -> Optional[dict[str, Any]]:
        with self._lock:
            return dict(self._oi[symbol]) if symbol in self._oi else None

    # ── liquidations ────────────────────────────────────────

    def update_liquidation(self, symbol: str, liq: dict[str, Any]) -> None:
        with self._lock:
            self._liquidations[symbol].append(liq)
            self._stats["last_liq_ms"] = int(time.time() * 1000)
            self._stats["liq_count"] += 1

    def get_liquidations(
        self, symbol: str, since_ms: Optional[int] = None
    ) -> pd.DataFrame:
        with self._lock:
            liqs = list(self._liquidations[symbol])
        if since_ms is not None:
            liqs = [l for l in liqs if l.get("liq_time", 0) >= since_ms]
        if not liqs:
            return pd.DataFrame()
        return pd.DataFrame(liqs)

    # ── health / introspection ──────────────────────────────

    def get_health(self) -> dict[str, Any]:
        """Return cache health metrics for dashboard."""
        with self._lock:
            now = int(time.time() * 1000)
            return {
                "last_kline_age_ms": now - self._stats["last_kline_ms"]
                if self._stats["last_kline_ms"] else None,
                "last_trade_age_ms": now - self._stats["last_trade_ms"]
                if self._stats["last_trade_ms"] else None,
                "last_funding_age_ms": now - self._stats["last_funding_ms"]
                if self._stats["last_funding_ms"] else None,
                "last_oi_age_ms": now - self._stats["last_oi_ms"]
                if self._stats["last_oi_ms"] else None,
                "last_liq_age_ms": now - self._stats["last_liq_ms"]
                if self._stats["last_liq_ms"] else None,
                "kline_count": self._stats["kline_count"],
                "trade_count": self._stats["trade_count"],
                "liq_count": self._stats["liq_count"],
                "tracked_symbols_candles": len(set(s for s, _ in self._candles.keys())),
                "tracked_funding": len(self._funding),
                "tracked_oi": len(self._oi),
            }

    def clear(self) -> None:
        with self._lock:
            self._candles.clear()
            self._agg_trades.clear()
            self._funding.clear()
            self._oi.clear()
            self._liquidations.clear()
            for k in self._stats:
                self._stats[k] = 0
