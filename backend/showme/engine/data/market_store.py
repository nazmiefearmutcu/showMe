"""DuckDB-backed persistent market data store (per plan §4.1).

Append-only writes for candles, agg_trades, funding_rate, open_interest,
liquidations. Single embedded file at runtime/market.db. Thread-safe via
internal lock — DuckDB connections are not multi-thread safe by default.
"""

import threading
from pathlib import Path
from typing import Any, Optional

import duckdb
import pandas as pd

from showme.engine.utils.logger import get_logger

logger = get_logger("data.market_store")


SCHEMA_DDL = [
    """
    CREATE TABLE IF NOT EXISTS candles (
        symbol VARCHAR NOT NULL,
        timeframe VARCHAR NOT NULL,
        open_time TIMESTAMP NOT NULL,
        open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
        volume DOUBLE, quote_volume DOUBLE, trades INTEGER,
        taker_buy_base DOUBLE, taker_buy_quote DOUBLE,
        PRIMARY KEY (symbol, timeframe, open_time)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS agg_trades (
        symbol VARCHAR NOT NULL,
        trade_time TIMESTAMP NOT NULL,
        price DOUBLE, quantity DOUBLE,
        is_buyer_maker BOOLEAN,
        agg_trade_id BIGINT PRIMARY KEY
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS funding_rate (
        symbol VARCHAR NOT NULL,
        funding_time TIMESTAMP NOT NULL,
        rate DOUBLE, mark_price DOUBLE,
        PRIMARY KEY (symbol, funding_time)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS open_interest (
        symbol VARCHAR NOT NULL,
        snapshot_time TIMESTAMP NOT NULL,
        oi DOUBLE, oi_value DOUBLE,
        PRIMARY KEY (symbol, snapshot_time)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS liquidations (
        symbol VARCHAR NOT NULL,
        liq_time TIMESTAMP NOT NULL,
        side VARCHAR, quantity DOUBLE, price DOUBLE,
        order_type VARCHAR
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_candles_time ON candles(symbol, timeframe, open_time);",
    "CREATE INDEX IF NOT EXISTS idx_trades_time ON agg_trades(symbol, trade_time);",
    "CREATE INDEX IF NOT EXISTS idx_liqs_time ON liquidations(symbol, liq_time);",
]


class MarketStore:
    """Embedded DuckDB persistent store for OHLCV + supplementary feeds."""

    def __init__(self, db_path: str = "runtime/market.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        # check_same_thread=False not applicable to DuckDB; we serialize via lock
        self._conn = duckdb.connect(str(self.db_path))
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            for ddl in SCHEMA_DDL:
                self._conn.execute(ddl)
        logger.info("MarketStore initialized at %s", self.db_path)

    # ── candles ──────────────────────────────────────────────

    def write_candle(self, row: dict[str, Any]) -> None:
        """Insert or replace a single candle row."""
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO candles
                (symbol, timeframe, open_time, open, high, low, close,
                 volume, quote_volume, trades, taker_buy_base, taker_buy_quote)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["symbol"], row["timeframe"], pd.to_datetime(row["open_time"], unit="ms")
                    if isinstance(row["open_time"], (int, float)) else row["open_time"],
                    row.get("open"), row.get("high"), row.get("low"), row.get("close"),
                    row.get("volume"), row.get("quote_volume"), row.get("trades"),
                    row.get("taker_buy_base"), row.get("taker_buy_quote"),
                ),
            )

    def write_candles_bulk(self, df: pd.DataFrame) -> int:
        """Bulk insert candles from a DataFrame. Returns rows written."""
        if df is None or df.empty:
            return 0
        cols = [
            "symbol", "timeframe", "open_time", "open", "high", "low", "close",
            "volume", "quote_volume", "trades", "taker_buy_base", "taker_buy_quote",
        ]
        for c in cols:
            if c not in df.columns:
                df[c] = None
        with self._lock:
            self._conn.register("incoming_candles", df[cols])
            self._conn.execute(
                "INSERT OR REPLACE INTO candles SELECT * FROM incoming_candles"
            )
            self._conn.unregister("incoming_candles")
        return len(df)

    def query_candles(
        self, symbol: str, timeframe: str, limit: int = 500
    ) -> Optional[pd.DataFrame]:
        """Return last `limit` candles for a (symbol, timeframe), oldest→newest."""
        with self._lock:
            try:
                df = self._conn.execute(
                    """
                    SELECT * FROM (
                        SELECT * FROM candles
                        WHERE symbol = ? AND timeframe = ?
                        ORDER BY open_time DESC
                        LIMIT ?
                    ) t
                    ORDER BY open_time ASC
                    """,
                    (symbol, timeframe, limit),
                ).df()
            except Exception as e:
                logger.error("query_candles failed for %s/%s: %s", symbol, timeframe, e)
                return None
        return df if not df.empty else None

    def latest_candle_time(self, symbol: str, timeframe: str) -> Optional[pd.Timestamp]:
        with self._lock:
            row = self._conn.execute(
                "SELECT MAX(open_time) FROM candles WHERE symbol=? AND timeframe=?",
                (symbol, timeframe),
            ).fetchone()
        return row[0] if row and row[0] is not None else None

    # ── agg_trades ──────────────────────────────────────────

    def write_agg_trade(self, trade: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO agg_trades
                (symbol, trade_time, price, quantity, is_buyer_maker, agg_trade_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    trade["symbol"],
                    pd.to_datetime(trade["trade_time"], unit="ms")
                    if isinstance(trade["trade_time"], (int, float)) else trade["trade_time"],
                    trade["price"], trade["quantity"],
                    trade.get("is_buyer_maker", False),
                    trade["agg_trade_id"],
                ),
            )

    def purge_old_agg_trades(self, retention_days: int) -> int:
        """Delete agg_trades older than retention_days. Returns rows affected."""
        with self._lock:
            res = self._conn.execute(
                f"""
                DELETE FROM agg_trades
                WHERE trade_time < (CURRENT_TIMESTAMP - INTERVAL '{int(retention_days)} days')
                """
            )
            return res.fetchall()[0][0] if res.description else 0

    # ── funding_rate ────────────────────────────────────────

    def write_funding(self, symbol: str, t: int, rate: float, mark_price: float) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO funding_rate
                (symbol, funding_time, rate, mark_price)
                VALUES (?, ?, ?, ?)
                """,
                (
                    symbol,
                    pd.to_datetime(t, unit="ms") if isinstance(t, (int, float)) else t,
                    rate, mark_price,
                ),
            )

    def query_funding(self, symbol: str, limit: int = 200) -> Optional[pd.DataFrame]:
        with self._lock:
            df = self._conn.execute(
                """
                SELECT * FROM funding_rate
                WHERE symbol = ?
                ORDER BY funding_time DESC
                LIMIT ?
                """,
                (symbol, limit),
            ).df()
        return df if not df.empty else None

    # ── open_interest ───────────────────────────────────────

    def write_oi(self, symbol: str, t: int, oi: float, oi_value: float) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO open_interest
                (symbol, snapshot_time, oi, oi_value)
                VALUES (?, ?, ?, ?)
                """,
                (
                    symbol,
                    pd.to_datetime(t, unit="ms") if isinstance(t, (int, float)) else t,
                    oi, oi_value,
                ),
            )

    def query_oi(self, symbol: str, limit: int = 100) -> Optional[pd.DataFrame]:
        with self._lock:
            df = self._conn.execute(
                """
                SELECT * FROM open_interest
                WHERE symbol = ?
                ORDER BY snapshot_time DESC
                LIMIT ?
                """,
                (symbol, limit),
            ).df()
        return df if not df.empty else None

    # ── liquidations ────────────────────────────────────────

    def write_liquidation(
        self, symbol: str, t: int, side: str, quantity: float,
        price: float, order_type: str = "MARKET",
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO liquidations
                (symbol, liq_time, side, quantity, price, order_type)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    symbol,
                    pd.to_datetime(t, unit="ms") if isinstance(t, (int, float)) else t,
                    side, quantity, price, order_type,
                ),
            )

    def query_liquidations(
        self, symbol: str, since_ms: Optional[int] = None, limit: int = 500
    ) -> Optional[pd.DataFrame]:
        with self._lock:
            if since_ms is not None:
                df = self._conn.execute(
                    """
                    SELECT * FROM liquidations
                    WHERE symbol = ? AND liq_time >= ?
                    ORDER BY liq_time DESC
                    LIMIT ?
                    """,
                    (symbol, pd.to_datetime(since_ms, unit="ms"), limit),
                ).df()
            else:
                df = self._conn.execute(
                    """
                    SELECT * FROM liquidations WHERE symbol = ?
                    ORDER BY liq_time DESC LIMIT ?
                    """,
                    (symbol, limit),
                ).df()
        return df if not df.empty else None

    # ── housekeeping ────────────────────────────────────────

    def get_stats(self) -> dict[str, int]:
        with self._lock:
            stats = {}
            for tbl in ["candles", "agg_trades", "funding_rate", "open_interest", "liquidations"]:
                row = self._conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()
                stats[tbl] = int(row[0]) if row else 0
        return stats

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass
