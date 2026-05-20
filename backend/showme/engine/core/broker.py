"""BaseBroker ABC — common contract for every brokerage adapter.

Used by EMSX/AIM/TSOX/FXGO/BBGT functions and by execution algos. Each
concrete broker (Binance, Alpaca, IBKR, OANDA, Saxo) implements this.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, AsyncIterator

from showme.engine.core.instrument import Instrument


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"
    TRAILING_STOP = "TRAILING_STOP"


class TimeInForce(str, Enum):
    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"
    DAY = "DAY"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


@dataclass
class BrokerOrder:
    """Universal cross-broker order envelope."""
    instrument: Instrument
    side: OrderSide
    quantity: float
    order_type: OrderType = OrderType.MARKET
    price: float | None = None
    stop_price: float | None = None
    time_in_force: TimeInForce = TimeInForce.GTC
    client_order_id: str | None = None
    leverage: int | None = None
    reduce_only: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class BrokerFill:
    order_id: str
    instrument: Instrument
    side: OrderSide
    quantity: float
    price: float
    fee: float = 0.0
    fee_currency: str = "USD"
    timestamp: datetime = field(default_factory=_now_utc)


@dataclass
class BrokerPosition:
    instrument: Instrument
    quantity: float
    avg_price: float
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    leverage: int | None = None
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass
class BrokerBalance:
    currency: str
    total: float
    available: float
    locked: float = 0.0


class BaseBroker(ABC):
    name: str = "base_broker"
    supports_short: bool = False
    supports_leverage: bool = False
    supported_asset_classes: tuple[str, ...] = ()

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self._connected = False

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def place_order(self, order: BrokerOrder) -> str: ...

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool: ...

    @abstractmethod
    async def get_open_orders(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def get_positions(self) -> list[BrokerPosition]: ...

    @abstractmethod
    async def get_balance(self) -> list[BrokerBalance]: ...

    async def stream_fills(self) -> AsyncIterator[BrokerFill]:
        """Optional — only brokers with WS user-data streams override."""
        raise NotImplementedError(f"{self.name} has no fill stream")
        if False:  # pragma: no cover
            yield
