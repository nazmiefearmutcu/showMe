"""Vendored KAOS engine — pure strategy layer for the showme bot system.

Vendored from KAOS engine (Entropy repo) pure strategy layer,
Entropy HEAD: edfa322 — parity-tested.

Modules:
* ``config``     — the shipped s20 live configuration + venue universes.
* ``indicators`` — pure-Python indicator primitives (polars-free ports,
                   EMA/RSI/MACD bit-exact, Bollinger within ~1e-15 relative).
* ``costs``      — vendored execution-cost model (entropy.bot.costs port).
* ``strategy``   — bar-driven port of the consensus strategy (pure math).
* ``adapter``    — showme integration: OHLCV frames in, bot decisions out.

Zero exchange/network IO lives here; orders flow through the EXISTING
showme broker dispatch (see ``showme.bots.runner``).
"""
from __future__ import annotations

from .config import (
    DEFAULT_KAOS_BOT_NAME,
    DEFAULT_VENUES,
    SIGMA_STOP_MULT,
    SIGMA_TP_MULT,
    KaosConfig,
    default_config,
)
from .strategy import KaosSignal, KaosStrategy

__all__ = [
    "DEFAULT_KAOS_BOT_NAME",
    "DEFAULT_VENUES",
    "SIGMA_STOP_MULT",
    "SIGMA_TP_MULT",
    "KaosConfig",
    "KaosSignal",
    "KaosStrategy",
    "default_config",
]
