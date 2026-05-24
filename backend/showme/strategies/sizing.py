"""Shared sizing math — single source of truth.

Per FIX_CONTRACT.md C1: both the live runner (``runner._dispatch_*``) and
the performance route (``performance.compute_trades``) MUST go through
this module so PnL / order-quantity numbers stay consistent.

V1 ships side-aware ``compute_pnl`` (long + short) and a ``resolve_quantity``
that validates sizing inputs (rejects negative, zero, NaN, out-of-range
``risk_pct``). ``risk_pct`` requires a positive equity hint; live callers
pull this via ``runner._resolve_equity()`` (C2).
"""
from __future__ import annotations

import math
from typing import Literal


SizingKind = Literal["fixed_quote", "fixed_base", "risk_pct"]
Side = Literal["long", "short"]


def _is_finite_positive(x: float) -> bool:
    """Return True iff ``x`` is a finite, strictly positive float.

    Rejects NaN, +/-inf, 0, and negatives. The runner / route layer feeds
    user-supplied numbers through this helper before doing math so a typo
    or malformed POST body can't open an unbounded position.
    """
    try:
        v = float(x)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(v):
        return False
    return v > 0


def resolve_quantity(
    *,
    sizing_kind: SizingKind,
    sizing_value: float,
    price: float,
    equity: float,
) -> float:
    """Translate a strategy's ``sizing_kind`` / ``sizing_value`` into a
    broker-ready base-currency quantity.

    * ``fixed_base``  → ``sizing_value`` is the qty directly (must be > 0).
    * ``fixed_quote`` → ``quantity = sizing_value / price``.
    * ``risk_pct``    → ``quantity = (equity * sizing_value/100) / price``;
       ``sizing_value`` must be in (0, 100] and ``equity`` must be > 0.

    Raises ``ValueError`` on invalid input. Never returns a non-positive
    quantity, NaN, or inf — callers can rely on the returned value being a
    safe argument to ``broker.submit_order(quantity=...)``.
    """
    if not _is_finite_positive(sizing_value):
        raise ValueError(
            f"sizing_value must be a finite positive number; got {sizing_value!r}"
        )
    if not _is_finite_positive(price):
        raise ValueError(
            f"price must be a finite positive number; got {price!r}"
        )
    sv = float(sizing_value)
    p = float(price)

    if sizing_kind == "fixed_base":
        return sv
    if sizing_kind == "fixed_quote":
        return sv / p
    if sizing_kind == "risk_pct":
        # sizing_value is interpreted as a percent (0 < v <= 100).
        if not (0.0 < sv <= 100.0):
            raise ValueError(
                f"risk_pct sizing_value must be in (0, 100]; got {sv!r}"
            )
        if not _is_finite_positive(equity):
            raise ValueError(
                f"equity must be a finite positive number for risk_pct sizing; got {equity!r}"
            )
        budget = (sv / 100.0) * float(equity)
        return budget / p
    raise ValueError(f"unknown sizing_kind: {sizing_kind!r}")


def compute_pnl(
    *,
    entry_price: float,
    exit_price: float,
    side: Side,
    entry_qty: float,
) -> float:
    """Absolute PnL in quote currency, side-aware.

    Long: ``(exit - entry) * qty``.
    Short: ``(entry - exit) * qty``.

    Returns 0.0 on non-positive ``entry_price`` or ``entry_qty`` (we don't
    have enough info to value the round-trip; pairing should have skipped
    it upstream but be defensive).
    """
    if not _is_finite_positive(entry_price) or not _is_finite_positive(entry_qty):
        return 0.0
    try:
        ex = float(exit_price)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(ex):
        return 0.0
    delta = (ex - entry_price) if side == "long" else (entry_price - ex)
    return float(delta) * float(entry_qty)


def compute_pnl_pct(
    *,
    entry_price: float,
    exit_price: float,
    side: Side,
) -> float:
    """Percent PnL for the round-trip, side-aware. ``0.0`` on bad input."""
    if not _is_finite_positive(entry_price):
        return 0.0
    try:
        ex = float(exit_price)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(ex):
        return 0.0
    if side == "long":
        return (ex - entry_price) / entry_price * 100.0
    return (entry_price - ex) / entry_price * 100.0
