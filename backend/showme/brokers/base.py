"""BaseBroker ABC + value objects shared across adapters."""
from __future__ import annotations

import abc
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class TimeInForce(str, Enum):
    DAY = "day"
    GTC = "gtc"
    IOC = "ioc"
    FOK = "fok"


class OrderStatus(str, Enum):
    NEW = "new"
    ACCEPTED = "accepted"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


@dataclass
class Order:
    id: str
    symbol: str
    side: OrderSide
    quantity: float
    order_type: OrderType
    time_in_force: TimeInForce
    limit_price: float | None = None
    stop_price: float | None = None
    status: OrderStatus = OrderStatus.NEW
    filled_quantity: float = 0.0
    avg_fill_price: float | None = None
    submitted_at: str = field(default_factory=lambda: datetime.now(tz=timezone.utc).isoformat())
    filled_at: str | None = None
    notes: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["side"] = self.side.value
        d["order_type"] = self.order_type.value
        d["time_in_force"] = self.time_in_force.value
        d["status"] = self.status.value
        return d


@dataclass
class Position:
    symbol: str
    side: OrderSide
    quantity: float
    entry_price: float | None = None
    current_price: float | None = None
    unrealized_pnl: float | None = None
    realized_pnl: float = 0.0
    opened_at: str = field(default_factory=lambda: datetime.now(tz=timezone.utc).isoformat())
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["side"] = self.side.value
        return d


class BrokerError(RuntimeError):
    """Raised when a broker call fails."""


class NotSupported(BrokerError):
    """Raised when the adapter does not implement a feature."""


class BaseBroker(abc.ABC):
    """Cross-vendor broker contract.

    Adapters expose async methods so any HTTP transport (httpx, websockets)
    can plug in without changing call sites. Synchronous adapters can wrap
    their work in ``asyncio.to_thread`` if needed.
    """

    name: str = "abstract"
    """Stable identifier (used by ``get_broker(name)``)."""

    @abc.abstractmethod
    async def account(self) -> dict[str, Any]:
        """Return cash, equity, buying_power, day P&L."""

    @abc.abstractmethod
    async def list_positions(self) -> list[Position]:
        ...

    @abc.abstractmethod
    async def list_orders(
        self, *, status: str = "open", limit: int = 100,
    ) -> list[Order]:
        ...

    @abc.abstractmethod
    async def submit_order(
        self,
        *,
        symbol: str,
        side: OrderSide | str,
        quantity: float,
        order_type: OrderType | str = OrderType.MARKET,
        time_in_force: TimeInForce | str = TimeInForce.DAY,
        limit_price: float | None = None,
        stop_price: float | None = None,
        notes: str = "",
    ) -> Order:
        ...

    @abc.abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        ...

    @abc.abstractmethod
    async def close_position(self, symbol: str, *, quantity: float | None = None) -> Order:
        ...

    # ── Helpers used by adapters ──────────────────────────────────────────
    @staticmethod
    def coerce_side(side: OrderSide | str) -> OrderSide:
        return side if isinstance(side, OrderSide) else OrderSide(str(side).lower())

    @staticmethod
    def coerce_type(t: OrderType | str) -> OrderType:
        return t if isinstance(t, OrderType) else OrderType(str(t).lower())

    @staticmethod
    def coerce_tif(t: TimeInForce | str) -> TimeInForce:
        return t if isinstance(t, TimeInForce) else TimeInForce(str(t).lower())
