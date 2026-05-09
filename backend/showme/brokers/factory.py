"""Broker registry — register and discover broker adapters.

The factory keeps the import surface tiny:

    from showme.brokers import get_broker
    broker = get_broker("paper")          # in-memory
    broker = get_broker("alpaca-paper")   # live HTTP

Registration is idempotent. ``register_broker(name, factory_fn)`` lets
new adapters drop in without touching this file.
"""
from __future__ import annotations

import os
from typing import Callable

from .base import BaseBroker
from .paper import PaperBroker

_REGISTRY: dict[str, Callable[[], BaseBroker]] = {}


def register_broker(name: str, factory: Callable[[], BaseBroker]) -> None:
    _REGISTRY[name] = factory


def list_brokers() -> list[str]:
    return sorted(_REGISTRY.keys())


def get_broker(name: str | None = None) -> BaseBroker:
    """Return a broker. ``name`` defaults to ``SHOWME_BROKER`` env or paper."""
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
except Exception:  # pragma: no cover — alpaca import optional
    pass
