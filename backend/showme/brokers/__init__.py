"""showMe broker adapters.

Round 27 introduces the cross-vendor broker abstraction:

* ``BaseBroker``  — ABC every adapter implements.
* ``PaperBroker`` — in-memory paper account so the scanner pipeline can
  spin up without external credentials.
* ``AlpacaPaperBroker`` — first real adapter (paper-trading endpoint).

Use ``get_broker(name)`` to obtain the configured broker without
hard-coding a class. Future adapters (IBKR, Binance, Coinbase
Advanced) drop in via the same registry.
"""
from .base import (
    BaseBroker,
    BrokerError,
    NotSupported,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    TimeInForce,
)
from .factory import get_broker, list_brokers, register_broker
from .paper import PaperBroker

# Alpaca import is best-effort so missing optional deps (httpx) don't
# explode at module-import time. The factory module already handles the
# registration breadcrumb log; this re-export only widens the public API.
try:
    from .alpaca import AlpacaPaperBroker  # noqa: F401
except Exception:  # pragma: no cover — optional dep absent in some envs
    import logging as _logging
    _logging.getLogger("showme.brokers").debug(
        "AlpacaPaperBroker re-export skipped (optional dep missing)"
    )
    AlpacaPaperBroker = None  # type: ignore[misc,assignment]


__all__ = [
    "AlpacaPaperBroker",
    "BaseBroker",
    "BrokerError",
    "NotSupported",
    "Order",
    "OrderSide",
    "OrderStatus",
    "OrderType",
    "PaperBroker",
    "Position",
    "TimeInForce",
    "get_broker",
    "list_brokers",
    "register_broker",
]
