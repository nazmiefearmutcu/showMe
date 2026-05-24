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


SizingKind = Literal["fixed_quote", "fixed_base", "risk_pct", "risk_per_trade"]
Side = Literal["long", "short"]

# Q4 audit C3 fix: default Binance taker fee (8bp = 0.08%). Per-side.
DEFAULT_COMMISSION_RATE = 0.0008


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
    leverage: float = 1.0,
    stop_loss_pct: float | None = None,
) -> float:
    """Translate a strategy's ``sizing_kind`` / ``sizing_value`` into a
    broker-ready base-currency quantity.

    * ``fixed_base``  → ``sizing_value`` is the qty directly (must be > 0).
    * ``fixed_quote`` → ``quantity = sizing_value / price``.
    * ``risk_pct``    → ``quantity = (equity * sizing_value/100 * leverage) / price``.
        Q4 audit C5 fix: ``leverage`` was missing — a "5% risk" at 20× was
        actually 100% effective notional. Now correctly multiplies in.
    * ``risk_per_trade`` → Van Tharp R-multiple sizing:
        ``quantity = (equity * sizing_value/100) / (price * stop_loss_pct/100)``.
        Requires non-null ``stop_loss_pct`` (the distance to the stop).
        Leverage clamps the notional ceiling: never exceed equity * leverage.

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
    if not _is_finite_positive(leverage):
        raise ValueError(
            f"leverage must be a finite positive number; got {leverage!r}"
        )
    sv = float(sizing_value)
    p = float(price)
    lev = float(leverage)

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
        # Q4 audit C5: leverage multiplies effective notional.
        budget = (sv / 100.0) * float(equity) * lev
        return budget / p
    if sizing_kind == "risk_per_trade":
        # Van Tharp R-multiple: bet ``sizing_value%`` of equity per "R" = stop
        # distance. qty * (price * sl_pct/100) == equity * sizing_value/100.
        if not (0.0 < sv <= 100.0):
            raise ValueError(
                f"risk_per_trade sizing_value must be in (0, 100]; got {sv!r}"
            )
        if not _is_finite_positive(equity):
            raise ValueError(
                f"equity must be a finite positive number for risk_per_trade; got {equity!r}"
            )
        if stop_loss_pct is None or not _is_finite_positive(stop_loss_pct):
            raise ValueError(
                "risk_per_trade requires position.stop_loss_pct to be set "
                f"and > 0; got {stop_loss_pct!r}"
            )
        sl = float(stop_loss_pct)
        if sl <= 0 or sl > 100:
            raise ValueError(
                f"stop_loss_pct must be in (0, 100]; got {sl!r}"
            )
        risk_amount = (sv / 100.0) * float(equity)
        stop_distance_price = p * (sl / 100.0)
        if stop_distance_price <= 0:
            raise ValueError("computed stop distance price is non-positive")
        qty = risk_amount / stop_distance_price
        # Clamp by leveraged equity ceiling (no over-exposure).
        max_notional = float(equity) * lev
        if qty * p > max_notional:
            qty = max_notional / p
        return qty
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


def compute_commission(
    *,
    entry_price: float,
    exit_price: float,
    qty: float,
    commission_rate: float = DEFAULT_COMMISSION_RATE,
) -> float:
    """Q4 audit C3: round-trip commission deducted from gross PnL.

    Charged on *both* the entry notional and the exit notional (taker).
    Returns 0.0 on bad inputs so callers can blindly subtract it.
    """
    if not _is_finite_positive(entry_price) or not _is_finite_positive(qty):
        return 0.0
    try:
        ex = float(exit_price)
        rate = float(commission_rate)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(ex) or not math.isfinite(rate) or rate < 0:
        return 0.0
    entry_notional = float(entry_price) * float(qty)
    exit_notional = ex * float(qty)
    return (entry_notional + exit_notional) * rate


def compute_funding_delta(
    *,
    position_notional: float,
    funding_rate: float,
    dt_seconds: float,
    interval_seconds: float = 8 * 3600.0,
    side: Side = "long",
) -> float:
    """Q4 audit C4: per-tick funding accrual.

    Binance perpetual: funding paid every 8h. Long pays when rate > 0;
    short receives. We pro-rate the rate over ``dt_seconds`` so a tick
    that's a small slice of the 8h window only deducts a small fraction.

    Returns a SIGNED delta: positive = position pays, negative = position
    receives. Caller subtracts from PnL: ``pnl_net = gross - funding_delta``.
    """
    if not _is_finite_positive(position_notional):
        return 0.0
    try:
        r = float(funding_rate)
        dt = float(dt_seconds)
        iv = float(interval_seconds)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(r) or not math.isfinite(dt) or iv <= 0 or dt < 0:
        return 0.0
    # Cap dt at the interval — a missing-tick gap longer than 8h should not
    # double-charge funding (the exchange only charges once per interval).
    dt_clamped = min(dt, iv)
    pro_rated_rate = r * (dt_clamped / iv)
    sign = 1.0 if side == "long" else -1.0
    return float(position_notional) * pro_rated_rate * sign
