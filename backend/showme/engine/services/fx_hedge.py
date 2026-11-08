"""FX hedge engine — overlay forward contracts onto foreign exposures.

For each foreign-currency position, compute:
- raw FX exposure (notional in target currency)
- hedge ratio target (default 100%)
- forward notional + maturity

Coverage analysis:
- residual_exposure_after_hedge
- expected_carry_pnl (interest rate differential × notional × time)
- pnl scenario at +x% USD strengthen / weaken

Forward rate via covered interest parity, T = days/360 (ACT/360):
    F = S × (1 + r_quote × T) / (1 + r_base × T)
where:
    base = the currency you're hedging FROM
    quote = the home currency
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


@dataclass
class FXExposure:
    currency: str             # foreign currency code, e.g. "EUR"
    home_currency: str        # e.g. "USD"
    notional: float           # in foreign units
    spot_rate: float          # quote per base, e.g. EURUSD = 1.10
    base_rate: float = 0.04   # foreign-currency risk-free
    home_rate: float = 0.045  # home-currency risk-free
    side: str = "long_foreign"  # long_foreign (receive foreign) | short_foreign (pay foreign)


SIDE_SIGN: dict[str, float] = {"long_foreign": 1.0, "short_foreign": -1.0}


def side_sign(side: str) -> float:
    """+1 for a long-foreign exposure, -1 for short-foreign (P&L mirrors)."""
    if side not in SIDE_SIGN:
        raise ValueError(f"unknown exposure side {side!r}")
    return SIDE_SIGN[side]


#: Rate inputs are decimal annual rates (3.5 % = 0.035). Anything above this
#: magnitude is almost certainly a percent entry and is refused (XCON-6).
RATE_DECIMAL_LIMIT = 1.0


def decimal_rate_error(label: str, value: Any) -> str | None:
    """Reason a rate input is unusable, or None when it is a usable decimal.

    A blank value is not an error here (callers decide whether it is required).
    """
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return f"{label}={value!r} is not a number; rates are decimal annual (3.5 % = 0.035)."
    if not math.isfinite(number):
        return f"{label}={value!r} is not finite; rates are decimal annual (3.5 % = 0.035)."
    if abs(number) > RATE_DECIMAL_LIMIT:
        return (
            f"{label}={value:g} is above {RATE_DECIMAL_LIMIT:g}: rates are decimal annual "
            "(3.5 % = 0.035), not percent. Enter the decimal rate."
        )
    return None


#: Day-count for both rate legs: ACT/360, the house convention shared with FRD
#: and FXFC (USD and EUR money-market quotes are ACT/360). XCON-4: FXH used
#: days/365 here, so the same pair and tenor priced differently across panes.
DAY_COUNT_BASIS = 360.0


def forward_rate(*, spot: float, home_rate: float, base_rate: float,
                 days: float) -> float:
    """CIP forward, simple interest on ACT/360: F = S(1 + r_quote T)/(1 + r_base T)."""
    T = days / DAY_COUNT_BASIS
    return spot * (1 + home_rate * T) / (1 + base_rate * T)


def hedge_one(
    exp: FXExposure, *,
    hedge_ratio: float = 1.0,
    days: float = 90,
    usd_shock_pct: float = 0.05,
) -> dict[str, Any]:
    fwd = forward_rate(spot=exp.spot_rate, home_rate=exp.home_rate,
                       base_rate=exp.base_rate, days=days)
    sign = side_sign(exp.side)
    home_value_now = exp.notional * exp.spot_rate
    hedged_notional = exp.notional * hedge_ratio
    unhedged_notional = exp.notional - hedged_notional
    # Carry PnL on the hedged leg: locked-in forward minus today's spot. The
    # hedge is opposite to the exposure, so a short-foreign book mirrors it.
    carry_pnl = sign * (fwd - exp.spot_rate) * hedged_notional
    # Scenario: quote/home currency strengthens -> fewer home units per one
    # foreign unit; quote/home weakens -> more home units per foreign unit.
    spot_if_home_strengthens = exp.spot_rate * (1 - usd_shock_pct)
    spot_if_home_weakens = exp.spot_rate * (1 + usd_shock_pct)
    pnl_if_home_strengthens = (
        sign * unhedged_notional * (spot_if_home_strengthens - exp.spot_rate) + carry_pnl
    )
    pnl_if_home_weakens = (
        sign * unhedged_notional * (spot_if_home_weakens - exp.spot_rate) + carry_pnl
    )
    return {
        "currency": exp.currency, "home_currency": exp.home_currency,
        "exposure_side": exp.side,
        "hedge_direction": "sell_foreign_forward" if sign > 0 else "buy_foreign_forward",
        "notional_foreign": exp.notional,
        "spot_rate": exp.spot_rate,
        "forward_rate": fwd,
        "home_value_now": home_value_now,
        "hedge_ratio": hedge_ratio,
        "hedged_notional_foreign": hedged_notional,
        "unhedged_notional_foreign": unhedged_notional,
        "days_to_maturity": days,
        "carry_pnl_home": carry_pnl,
        "scenario_usd_strengthens_pct": usd_shock_pct * 100,
        "spot_if_home_strengthens": spot_if_home_strengthens,
        "spot_if_home_weakens": spot_if_home_weakens,
        "pnl_if_home_strengthens": pnl_if_home_strengthens,
        "pnl_if_home_weakens": pnl_if_home_weakens,
    }


def hedge_book(
    exposures: list[FXExposure], *,
    hedge_ratio: float = 1.0,
    days: float = 90,
    usd_shock_pct: float = 0.05,
) -> dict[str, Any]:
    rows = [hedge_one(e, hedge_ratio=hedge_ratio, days=days,
                       usd_shock_pct=usd_shock_pct) for e in exposures]
    total_now = sum(r["home_value_now"] for r in rows)
    total_pnl_strong = sum(r["pnl_if_home_strengthens"] for r in rows)
    total_pnl_weak = sum(r["pnl_if_home_weakens"] for r in rows)
    total_carry = sum(r["carry_pnl_home"] for r in rows)
    return {
        "exposures": rows,
        "total_home_value": total_now,
        "total_carry_pnl": total_carry,
        "total_pnl_if_home_strengthens": total_pnl_strong,
        "total_pnl_if_home_weakens": total_pnl_weak,
        "hedge_ratio": hedge_ratio,
        "days_to_maturity": days,
    }
