"""FX hedge engine — overlay forward contracts onto foreign exposures.

For each foreign-currency position, compute:
- raw FX exposure (notional in target currency)
- hedge ratio target (default 100%)
- forward notional + maturity

Coverage analysis:
- residual_exposure_after_hedge
- expected_carry_pnl (interest rate differential × notional × time)
- pnl scenario at +x% USD strengthen / weaken

Forward rate via covered interest parity:
    F = S × (1 + r_quote × T) / (1 + r_base × T)
where:
    base = the currency you're hedging FROM
    quote = the home currency
"""

from __future__ import annotations

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


def forward_rate(*, spot: float, home_rate: float, base_rate: float,
                 days: int) -> float:
    T = days / 365.0
    return spot * (1 + home_rate * T) / (1 + base_rate * T)


def hedge_one(
    exp: FXExposure, *,
    hedge_ratio: float = 1.0,
    days: int = 90,
    usd_shock_pct: float = 0.05,
) -> dict[str, Any]:
    fwd = forward_rate(spot=exp.spot_rate, home_rate=exp.home_rate,
                       base_rate=exp.base_rate, days=days)
    home_value_now = exp.notional * exp.spot_rate
    hedged_notional = exp.notional * hedge_ratio
    unhedged_notional = exp.notional - hedged_notional
    # Carry PnL on the hedged leg: locked-in forward minus today's spot.
    carry_pnl = (fwd - exp.spot_rate) * hedged_notional
    # Scenario: quote/home currency strengthens -> fewer home units per one
    # foreign unit; quote/home weakens -> more home units per foreign unit.
    spot_if_home_strengthens = exp.spot_rate * (1 - usd_shock_pct)
    spot_if_home_weakens = exp.spot_rate * (1 + usd_shock_pct)
    pnl_if_home_strengthens = (
        unhedged_notional * (spot_if_home_strengthens - exp.spot_rate) + carry_pnl
    )
    pnl_if_home_weakens = (
        unhedged_notional * (spot_if_home_weakens - exp.spot_rate) + carry_pnl
    )
    return {
        "currency": exp.currency, "home_currency": exp.home_currency,
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
    days: int = 90,
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
