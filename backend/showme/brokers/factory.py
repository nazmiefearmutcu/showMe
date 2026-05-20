"""Broker registry — register and discover broker adapters.

The factory keeps the import surface tiny:

    from showme.brokers import get_broker
    broker = get_broker("paper")          # in-memory
    broker = get_broker("alpaca-paper")   # live HTTP

Registration is idempotent. ``register_broker(name, factory_fn)`` lets
new adapters drop in without touching this file.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Callable

from .base import BaseBroker
from .paper import PaperBroker


LOG = logging.getLogger("showme.brokers.factory")
_REGISTRY: dict[str, Callable[[], BaseBroker]] = {}


def register_broker(name: str, factory: Callable[[], BaseBroker]) -> None:
    """Register ``factory`` under ``name`` so :func:`get_broker` can look it up."""
    _REGISTRY[name] = factory


def list_brokers() -> list[str]:
    """Return the sorted list of registered broker names."""
    return sorted(_REGISTRY.keys())


def get_broker(name: str | None = None) -> BaseBroker:
    """Return a broker instance.

    ``name`` defaults to ``$SHOWME_BROKER`` and finally to ``"paper"``.
    Raises ``KeyError`` if the requested broker is not registered.
    """
    target = (name or os.environ.get("SHOWME_BROKER") or "paper").strip()
    factory = _REGISTRY.get(target)
    if not factory:
        raise KeyError(f"unknown broker: {target}. registered: {list_brokers()}")
    return factory()


# ── Built-in registrations ───────────────────────────────────────────────

register_broker("paper", lambda: PaperBroker())

try:
    from .alpaca import AlpacaPaperBroker

    register_broker("alpaca-paper", lambda: AlpacaPaperBroker())
except Exception as exc:  # noqa: BLE001  # pragma: no cover — optional
    # Per PY-LINT-05 P2: surface a debug breadcrumb so ``alpaca-paper not
    # registered`` reports the underlying cause to operators rather than
    # silently disappearing.
    LOG.debug("alpaca broker unavailable: %s", exc)
