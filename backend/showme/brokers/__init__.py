"""showMe broker adapters.

Sub-system A: the abstraction now backs ~120 crypto exchanges (via
``CcxtBroker``) plus the original ``PaperBroker`` and ``AlpacaPaperBroker``.
Per-credential broker instances are registered at boot from the
``CredentialStore``.
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
from .catalog.loader import Catalog, CatalogEntry, CatalogError, load_catalog
from .credential_store import (
    CredentialError,
    CredentialRecord,
    CredentialStore,
    UnknownCredential,
)
from .factory import (
    close_all_brokers,
    get_broker,
    list_brokers,
    register_broker,
    register_credential,
    replay_stored_credentials,
    unregister_credential,
)
from .paper import PaperBroker

try:
    from .alpaca import AlpacaPaperBroker  # noqa: F401
except Exception:  # pragma: no cover
    import logging as _logging
    _logging.getLogger("showme.brokers").debug(
        "AlpacaPaperBroker re-export skipped (optional dep missing)"
    )
    AlpacaPaperBroker = None  # type: ignore[misc,assignment]

try:
    from .ccxt_broker import CcxtBroker  # noqa: F401
except Exception:  # pragma: no cover
    import logging as _logging
    _logging.getLogger("showme.brokers").debug("CcxtBroker import skipped")
    CcxtBroker = None  # type: ignore[misc,assignment]


__all__ = [
    "AlpacaPaperBroker",
    "BaseBroker",
    "BrokerError",
    "Catalog",
    "CatalogEntry",
    "CatalogError",
    "CcxtBroker",
    "CredentialError",
    "CredentialRecord",
    "CredentialStore",
    "NotSupported",
    "Order",
    "OrderSide",
    "OrderStatus",
    "OrderType",
    "PaperBroker",
    "Position",
    "TimeInForce",
    "UnknownCredential",
    "close_all_brokers",
    "get_broker",
    "list_brokers",
    "load_catalog",
    "register_broker",
    "register_credential",
    "replay_stored_credentials",
    "unregister_credential",
]
