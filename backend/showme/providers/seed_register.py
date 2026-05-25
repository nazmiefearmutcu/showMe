"""Register every provider adapter with the global REGISTRY.

Safe to import on startup — registration is the only side-effect, and
adapter constructors are network-free. Idempotent via REGISTRY-state check
so the test suite's REGISTRY.clear() autouse fixture can repopulate by
calling register_*() again.

Adapters registered:
- Official sources: SEC EDGAR, FRED, TreasuryDirect, OpenFIGI
- Market + news: Binance, yfinance, GDELT, RSS
"""
from __future__ import annotations

from typing import Any

from .fred import FredAdapter
from .openfigi import OpenFigiAdapter
from .registry import REGISTRY
from .sec_edgar import SecEdgarAdapter
from .treasury_direct import TreasuryDirectAdapter

__all__ = ["register_official_adapters", "register_all_adapters"]


# REGISTRY-state-aware: we skip adapters already present rather than relying
# on a module-level flag. This keeps the function idempotent under both
# repeat-import and the tests' autouse REGISTRY.clear() fixture (which used
# to silently no-op our flag-gated re-registration).
def _register_if_absent(adapter: Any) -> None:
    if adapter.name not in REGISTRY.names():
        REGISTRY.register(adapter)


def register_official_adapters() -> None:
    """Idempotently register the four official adapters (skip those already in REGISTRY)."""
    _register_if_absent(SecEdgarAdapter())
    _register_if_absent(FredAdapter())
    _register_if_absent(TreasuryDirectAdapter())
    _register_if_absent(OpenFigiAdapter())


def register_all_adapters() -> None:
    """Register both batches. Idempotent. Each batch is independently safe to call."""
    register_official_adapters()
    from . import seed_register_batch2  # noqa: F401  (registers its own adapters via the same _register_if_absent pattern when re-imported)
    # Defensive: call directly in case the module was already imported earlier.
    seed_register_batch2.register_batch2_adapters()


register_all_adapters()
