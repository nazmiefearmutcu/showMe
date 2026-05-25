"""Register the second batch of provider adapters with the global REGISTRY.

Owned by the batch-2 agent. Safe to import on startup — registration is
the only side-effect and constructors are network-free. Import-once
protected so re-importing the package never double-registers.

Mirrors :mod:`showme.providers.seed_register` (which handles SEC EDGAR /
FRED / TreasuryDirect / OpenFIGI) but for the four upstreams owned by
this agent: Binance, yfinance, GDELT, RSS.

If you want every adapter live, import BOTH modules at startup:

    from showme.providers import seed_register, seed_register_batch2  # noqa: F401
"""
from __future__ import annotations

from .binance import BinanceAdapter
from .gdelt import GdeltAdapter
from .registry import REGISTRY
from .rss_news import RssAdapter
from .yfinance_adapter import YfinanceAdapter

__all__ = ["register_batch2_adapters"]


def _register_if_absent(adapter):
    if adapter.name not in REGISTRY.names():
        REGISTRY.register(adapter)


def register_batch2_adapters() -> None:
    """Idempotently register the four batch-2 adapters (skip those already in REGISTRY)."""
    _register_if_absent(BinanceAdapter())
    _register_if_absent(YfinanceAdapter())
    _register_if_absent(GdeltAdapter())
    _register_if_absent(RssAdapter())


# Register on first import so callers that just write
# ``import showme.providers.seed_register_batch2`` get a populated registry.
register_batch2_adapters()
