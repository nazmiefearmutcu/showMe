"""Market data primitives: Quote, Trade, OrderBook, OrderBookLevel.

Designed to be source-agnostic. Adapters convert their native payloads into
these types so downstream code does not care which exchange or vendor
produced the data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Quote:
    """Top-of-book / last-trade snapshot."""
    symbol: str
    timestamp: datetime
    bid: float | None = None
    ask: float | None = None
    bid_size: float | None = None
    ask_size: float | None = None
    last: float | None = None
    volume_24h: float | None = None
    open_24h: float | None = None
    high_24h: float | None = None
    low_24h: float | None = None
    close_prev: float | None = None      # previous session close (equity)
    source: str | None = None            # "binance_ws", "yfinance", "ecb"

    @property
    def mid(self) -> float | None:
        if self.bid is not None and self.ask is not None:
            return (self.bid + self.ask) / 2
        return self.last

    @property
    def spread_bps(self) -> float | None:
        if self.bid and self.ask and self.bid > 0:
            return (self.ask - self.bid) / self.mid * 10_000  # type: ignore[operator]
        return None


@dataclass
class Trade:
    """A single executed trade (tick)."""
    symbol: str
    timestamp: datetime
    price: float
    size: float
    side: str | None = None              # "BUY"|"SELL"|"UNKNOWN"
    trade_id: str | None = None
    source: str | None = None


@dataclass
class OrderBookLevel:
    """One price level in an order book."""
    price: float
    size: float
    order_count: int | None = None       # not all feeds publish order count


@dataclass
class OrderBook:
    """Full order book snapshot (or delta)."""
    symbol: str
    timestamp: datetime
    bids: list[OrderBookLevel] = field(default_factory=list)   # descending price
    asks: list[OrderBookLevel] = field(default_factory=list)   # ascending price
    sequence: int | None = None
    source: str | None = None

    @property
    def best_bid(self) -> OrderBookLevel | None:
        return self.bids[0] if self.bids else None

    @property
    def best_ask(self) -> OrderBookLevel | None:
        return self.asks[0] if self.asks else None

    @property
    def mid(self) -> float | None:
        if self.best_bid and self.best_ask:
            return (self.best_bid.price + self.best_ask.price) / 2
        return None

    @property
    def spread(self) -> float | None:
        if self.best_bid and self.best_ask:
            return self.best_ask.price - self.best_bid.price
        return None

    def depth(self, side: str, levels: int = 10) -> float:
        """Cumulative size for the top ``levels`` of the given side."""
        book = self.bids if side.upper() == "BID" else self.asks
        return sum(lvl.size for lvl in book[:levels])

    def imbalance(self, levels: int = 10) -> float | None:
        """(bid_depth - ask_depth) / (bid_depth + ask_depth) ∈ [-1, 1]."""
        b = self.depth("BID", levels)
        a = self.depth("ASK", levels)
        if (b + a) == 0:
            return None
        return (b - a) / (b + a)


def utcnow() -> datetime:
    """Helper: timezone-aware UTC now."""
    return datetime.now(timezone.utc)
