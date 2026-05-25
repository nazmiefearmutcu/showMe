"""showMe provider adapter layer.

Public surface: the ``DataMode`` enum, ``ProviderAdapter`` ABC, the
global ``REGISTRY`` + ``chain()`` helper, and every concrete adapter so
callers can ``from showme.providers import SecEdgarAdapter`` without
needing to know which submodule it lives in.

Importing this package does NOT auto-register the adapters — callers who
want a populated registry should import ``showme.providers.seed_register``
(or call ``register_all_adapters()`` on it).
"""
from __future__ import annotations

from ._http import DEFAULT_USER_AGENT, aclose_shared, get_client
from .base import AdapterError, DataMode, ProviderAdapter
from .binance import BinanceAdapter
from .fred import FredAdapter
from .gdelt import GdeltAdapter
from .openfigi import OpenFigiAdapter
from .registry import REGISTRY, AdapterRegistry, chain
from .rss_news import RssAdapter
from .sec_edgar import SecEdgarAdapter
from .treasury_direct import TreasuryDirectAdapter
from .yfinance_adapter import YfinanceAdapter

__all__ = [
    # Base
    "DataMode",
    "ProviderAdapter",
    "AdapterError",
    # Registry
    "AdapterRegistry",
    "REGISTRY",
    "chain",
    # HTTP plumbing
    "DEFAULT_USER_AGENT",
    "get_client",
    "aclose_shared",
    # Concrete adapters — official sources
    "SecEdgarAdapter",
    "FredAdapter",
    "TreasuryDirectAdapter",
    "OpenFigiAdapter",
    # Concrete adapters — market + news
    "BinanceAdapter",
    "YfinanceAdapter",
    "GdeltAdapter",
    "RssAdapter",
]
