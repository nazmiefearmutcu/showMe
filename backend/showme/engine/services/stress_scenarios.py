"""Stress test scenarios — hand-set parametric shocks + custom shocks.

Each scenario is a mapping: asset-class / sector / symbol → return shock (decimal).
The engine applies the shock to a portfolio's positions, recomputing market value
under the stressed regime. Custom shocks may be combined linearly with a scaling
factor.

Bond funds in the GFC_2008 and COVID_2020 windows are the one exception to the
hand-set table: they take their own measured window return (``MEASURED_WINDOWS``),
computed by the caller from price history. When that return is unavailable the
position is left unshocked and flagged, never estimated.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Any


# Smallest shock a long position can take (a full loss of its market value).
MIN_SHOCK = -1.0

# Treasury and aggregate bond funds. They are typed ETF or FUND by the instrument
# master, but they must not take the equity-style ETF/FUND shock. Credit (HYG, JNK,
# LQD) and inflation-linked (TIP) funds are deliberately not here: the BOND row does
# not describe them and they keep their ETF/FUND bucket.
BOND_ETF_SYMBOLS: frozenset[str] = frozenset({
    "TLT", "IEF", "SHY", "GOVT", "VGLT", "VGIT", "VGSH", "SPTL", "EDV", "ZROZ",
    "BND", "AGG",
})

# Scenario windows whose bond-fund shocks are measured, not hand-set. Both ends are
# inclusive calendar dates. The caller fetches each bond fund's history over the
# window and passes the price return to ``apply_scenario(measured=...)``.
MEASURED_WINDOWS: dict[str, tuple[date, date]] = {
    "GFC_2008": (date(2008, 9, 15), date(2009, 3, 9)),
    "COVID_2020": (date(2020, 2, 19), date(2020, 3, 23)),
}

# Largest gap allowed between a window boundary and the first / last close used.
MEASURED_WINDOW_MAX_GAP_DAYS = 5


@dataclass
class StressScenario:
    name: str
    description: str
    horizon_days: int
    asset_class_shocks: dict[str, float] = field(default_factory=dict)
    sector_shocks: dict[str, float] = field(default_factory=dict)
    symbol_shocks: dict[str, float] = field(default_factory=dict)
    factor_shocks: dict[str, float] = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────
# Predefined scenarios. Shocks are hand-set parametric decimals calibrated to
# each scenario's narrative (not replayed from return history; not investment
# advice). Bond funds in GFC_2008 and COVID_2020 are measured instead (see
# MEASURED_WINDOWS), so the BOND row there is not used for them.
# ─────────────────────────────────────────────────────────────────
SCENARIOS: dict[str, StressScenario] = {
    "GFC_2008": StressScenario(
        name="GFC 2008",
        description="Global Financial Crisis — Sep 2008 to Mar 2009.",
        horizon_days=180,
        asset_class_shocks={
            "EQUITY": -0.55, "ETF": -0.50, "CRYPTO": -0.65,
            "COMMODITY": -0.50, "BOND": -0.05, "FX": -0.10,
            "FUND": -0.45, "DERIVATIVE": -0.40,
        },
        sector_shocks={
            "Financials": -0.78, "Real Estate": -0.70, "Energy": -0.55,
            "Materials": -0.50, "Consumer Discretionary": -0.45,
            "Industrials": -0.45, "Information Technology": -0.40,
            "Utilities": -0.30, "Health Care": -0.25, "Consumer Staples": -0.18,
            "Communication Services": -0.45,
        },
    ),
    "COVID_2020": StressScenario(
        name="COVID Crash 2020",
        description="Feb 19 - Mar 23 2020 pandemic crash.",
        horizon_days=33,
        asset_class_shocks={
            "EQUITY": -0.34, "ETF": -0.32, "CRYPTO": -0.55,
            "COMMODITY": -0.65, "BOND": +0.07, "FX": -0.05,
            "FUND": -0.30, "DERIVATIVE": -0.30,
        },
        sector_shocks={
            "Energy": -0.65, "Financials": -0.45, "Industrials": -0.40,
            "Real Estate": -0.40, "Consumer Discretionary": -0.35,
            "Materials": -0.30, "Communication Services": -0.25,
            "Information Technology": -0.20, "Health Care": -0.15,
            "Consumer Staples": -0.12, "Utilities": -0.30,
        },
    ),
    "CHINA_2015": StressScenario(
        name="China Devaluation 2015",
        description="Aug 11 2015 RMB devaluation + EM equity sell-off.",
        horizon_days=30,
        asset_class_shocks={
            "EQUITY": -0.12, "ETF": -0.12, "CRYPTO": -0.20,
            "COMMODITY": -0.20, "BOND": +0.02, "FX": -0.05,
            "FUND": -0.10, "DERIVATIVE": -0.15,
        },
        sector_shocks={
            "Materials": -0.20, "Energy": -0.18, "Industrials": -0.15,
            "Financials": -0.12, "Information Technology": -0.10,
            "Health Care": -0.06, "Consumer Staples": -0.04,
            "Utilities": -0.05, "Real Estate": -0.08,
            "Consumer Discretionary": -0.10,
        },
    ),
    "RATE_SHOCK_300BP": StressScenario(
        name="Rate Shock +300bp",
        description="Parallel +300bp shift on US Treasury curve over 6 months.",
        horizon_days=180,
        asset_class_shocks={
            "EQUITY": -0.18, "ETF": -0.16, "BOND": -0.20,
            "FUND": -0.15, "FX": +0.08, "CRYPTO": -0.30,
            "COMMODITY": -0.10, "DERIVATIVE": -0.20,
        },
        sector_shocks={
            "Real Estate": -0.30, "Utilities": -0.25,
            "Financials": +0.05, "Consumer Discretionary": -0.20,
            "Information Technology": -0.25,
        },
    ),
    "TECH_BUST_2022": StressScenario(
        name="Tech Bust 2022",
        description="Nasdaq -33%, growth-quality factor crash.",
        horizon_days=300,
        asset_class_shocks={
            "EQUITY": -0.20, "ETF": -0.20, "CRYPTO": -0.65,
            "COMMODITY": +0.10, "BOND": -0.13, "FX": +0.06,
            "FUND": -0.18, "DERIVATIVE": -0.25,
        },
        sector_shocks={
            "Information Technology": -0.35, "Communication Services": -0.40,
            "Consumer Discretionary": -0.30, "Real Estate": -0.25,
            "Financials": -0.15, "Energy": +0.50, "Utilities": -0.05,
            "Health Care": -0.05, "Consumer Staples": -0.05,
            "Materials": -0.10, "Industrials": -0.10,
        },
    ),
    "USD_STRENGTH": StressScenario(
        name="USD Spike +15%",
        description="Trade-weighted USD index rallies 15% (e.g. EM crisis trigger).",
        horizon_days=90,
        asset_class_shocks={
            "EQUITY": -0.08, "ETF": -0.08, "CRYPTO": -0.15,
            "COMMODITY": -0.18, "BOND": -0.05,
            "FX": -0.15, "FUND": -0.07, "DERIVATIVE": -0.10,
        },
    ),
    "OIL_SPIKE": StressScenario(
        name="Oil +60%",
        description="Brent rallies $60+ (geopolitical squeeze).",
        horizon_days=60,
        asset_class_shocks={
            "COMMODITY": +0.25, "EQUITY": -0.07,
            "ETF": -0.07, "CRYPTO": -0.05,
            "BOND": -0.04,
        },
        sector_shocks={
            "Energy": +0.30, "Industrials": -0.10,
            "Consumer Discretionary": -0.10, "Materials": +0.05,
        },
    ),
    "CRYPTO_WINTER": StressScenario(
        name="Crypto Winter",
        description="BTC -75%, broader alt drawdown >85%.",
        horizon_days=365,
        asset_class_shocks={
            "CRYPTO": -0.75, "EQUITY": -0.05,
            "ETF": -0.05, "COMMODITY": +0.05,
        },
        symbol_shocks={
            "BTCUSDT": -0.75, "ETHUSDT": -0.82, "SOLUSDT": -0.92,
            "BTC-USD": -0.75, "ETH-USD": -0.82, "SOL-USD": -0.92,
        },
    ),
}


def list_scenarios() -> list[dict[str, Any]]:
    return [
        {"key": k, "name": s.name, "description": s.description,
         "horizon_days": s.horizon_days}
        for k, s in SCENARIOS.items()
    ]


def get_scenario(key: str) -> StressScenario | None:
    return SCENARIOS.get(key.upper())


def custom_scenario(
    name: str,
    description: str = "User-defined shock",
    horizon_days: int = 30,
    *,
    asset_class_shocks: dict[str, float] | None = None,
    sector_shocks: dict[str, float] | None = None,
    symbol_shocks: dict[str, float] | None = None,
) -> StressScenario:
    return StressScenario(
        name=name,
        description=description,
        horizon_days=horizon_days,
        asset_class_shocks=asset_class_shocks or {},
        sector_shocks=sector_shocks or {},
        symbol_shocks=symbol_shocks or {},
    )


# Yahoo Finance sector labels mapped to the GICS-style keys used by
# ``StressScenario.sector_shocks``. Names already in the scenario taxonomy pass through.
_YAHOO_TO_SCENARIO_SECTOR: dict[str, str] = {
    "Technology": "Information Technology",
    "Financial Services": "Financials",
    "Consumer Cyclical": "Consumer Discretionary",
    "Consumer Defensive": "Consumer Staples",
    "Healthcare": "Health Care",
    "Basic Materials": "Materials",
}


def normalize_sector(sector: Any) -> str | None:
    """A position's sector in the scenario taxonomy, or ``None`` when unknown."""
    name = str(sector or "").strip()
    if not name:
        return None
    return _YAHOO_TO_SCENARIO_SECTOR.get(name, name)


def resolve_shock_bucket(symbol: str, asset_class: str) -> str:
    """Asset-class bucket a position is shocked under.

    Treasury and aggregate bond funds typed as ETF/FUND move to the BOND bucket.
    """
    ac = str(asset_class or "EQUITY").upper()
    if ac in {"ETF", "FUND"} and str(symbol or "").upper() in BOND_ETF_SYMBOLS:
        return "BOND"
    return ac


def measured_window_return(
    closes: Any,
    start: date,
    end: date,
    *,
    max_gap_days: int = MEASURED_WINDOW_MAX_GAP_DAYS,
) -> float | None:
    """Price return from the first to the last close inside ``[start, end]``.

    ``closes`` is an iterable of ``(date, close)``. Returns ``None`` when fewer than
    two finite positive closes fall inside the window, or when the first or last
    close sits more than ``max_gap_days`` from the window boundary (a coverage gap,
    not the window itself).
    """
    inside: list[tuple[date, float]] = []
    for day, close in closes:
        if close is None:
            continue
        value = float(close)
        if math.isfinite(value) and value > 0 and start <= day <= end:
            inside.append((day, value))
    if len(inside) < 2:
        return None
    inside.sort()
    first_day, first_close = inside[0]
    last_day, last_close = inside[-1]
    if (first_day - start).days > max_gap_days or (end - last_day).days > max_gap_days:
        return None
    return last_close / first_close - 1.0


def apply_scenario(
    positions: list[dict[str, Any]],
    scenario: StressScenario,
    *,
    sector_lookup: dict[str, str] | None = None,
    scale: float = 1.0,
    measured: dict[str, float | None] | None = None,
) -> dict[str, Any]:
    """Apply a stress scenario to a list of position dicts.

    ``positions`` items must contain: ``symbol``, ``asset_class``, ``market_value``.
    Optional: ``sector`` (or use ``sector_lookup`` keyed by symbol).

    ``measured`` is set only for a scenario in ``MEASURED_WINDOWS``. It maps each
    bond-fund symbol to its measured window return, or ``None`` when that return
    could not be obtained. A bond fund in the BOND bucket then takes the measured
    value, or is left unshocked (``shock_source == "unavailable"``) with a warning.
    Returns a stressed portfolio + per-position breakdown.
    """
    sector_lookup = sector_lookup or {}
    rows: list[dict[str, Any]] = []
    total_pre = 0.0
    total_post = 0.0
    warnings: list[str] = []
    unpriced = 0
    for p in positions:
        sym = p["symbol"]
        ac = resolve_shock_bucket(sym, p.get("asset_class", "EQUITY"))
        sector = normalize_sector(p.get("sector") or sector_lookup.get(sym))
        mv = float(p.get("market_value", 0) or 0)
        if measured is not None and ac == "BOND" and str(sym).upper() in BOND_ETF_SYMBOLS:
            shock: float | None = measured.get(sym)
            source = "measured_window" if shock is not None else "unavailable"
        else:
            # Resolve shock — symbol > sector > asset_class.
            shock = scenario.symbol_shocks.get(sym)
            if shock is None and sector:
                shock = scenario.sector_shocks.get(sector)
            source = "hand_set"
            if shock is None and ac == "BOND" and str(sym).upper() in BOND_ETF_SYMBOLS \
                    and "BOND" not in scenario.asset_class_shocks:
                # A Treasury/aggregate fund with no BOND row in this scenario must
                # neither take the equity-style ETF/FUND shock nor a silent 0.0.
                shock = None
                source = "unavailable"
            elif shock is None:
                if sector and scenario.sector_shocks and sector not in scenario.sector_shocks:
                    # Known sector, no row for it in this scenario: the asset-class
                    # shock is used, and that is reported.
                    warnings.append(
                        f"{sym}: sector {sector} has no shock in {scenario.name}; "
                        f"asset-class shock {ac} used"
                    )
                shock = scenario.asset_class_shocks.get(ac, 0.0)
        if shock is None:
            unpriced += 1
            if source == "unavailable" and measured is None:
                reason = (
                    f"{sym}: scenario {scenario.name} has no BOND shock, so the Treasury "
                    "fund shock is unavailable"
                )
            else:
                reason = f"{sym}: measured window return unavailable for {scenario.name}"
            warnings.append(f"{reason}; position left unshocked (not estimated)")
            rows.append({
                "symbol": sym, "asset_class": ac, "sector": sector,
                "shock": None, "shock_unfloored": None, "floored": False,
                "shock_source": source,
                "market_value_pre": mv,
                "market_value_post": mv,
                "pnl": 0.0,
            })
            total_pre += mv
            total_post += mv
            continue
        raw_shock = float(shock) * scale
        # A long position cannot lose more than its market value: floor the
        # scaled shock at -100% and say so, instead of returning negative MV.
        floored = raw_shock < MIN_SHOCK
        shock = max(raw_shock, MIN_SHOCK)
        if floored:
            warnings.append(
                f"{sym}: scaled shock {raw_shock:+.1%} floored to {MIN_SHOCK:+.0%} "
                "(a position cannot lose more than its market value)"
            )
        mv_post = mv * (1.0 + shock)
        rows.append({
            "symbol": sym, "asset_class": ac, "sector": sector,
            "shock": shock, "shock_unfloored": raw_shock, "floored": floored,
            "shock_source": source,
            "market_value_pre": mv,
            "market_value_post": mv_post,
            "pnl": mv_post - mv,
        })
        total_pre += mv
        total_post += mv_post
    return {
        "scenario": scenario.name,
        "description": scenario.description,
        "horizon_days": scenario.horizon_days,
        "scale": scale,
        "total_market_value_pre": total_pre,
        "total_market_value_post": total_post,
        "total_pnl": total_post - total_pre,
        "total_return_pct": (total_post / total_pre - 1.0) * 100 if total_pre else 0.0,
        "unpriced_positions": unpriced,
        "positions": rows,
        "warnings": warnings,
    }


def compare_scenarios(
    positions: list[dict[str, Any]],
    keys: list[str] | None = None,
    *,
    sector_lookup: dict[str, str] | None = None,
    scale: float = 1.0,
    measured_by_key: dict[str, dict[str, float | None]] | None = None,
) -> list[dict[str, Any]]:
    keys = keys or list(SCENARIOS)
    out = []
    for k in keys:
        sc = SCENARIOS.get(k.upper())
        if not sc:
            continue
        measured = None
        if measured_by_key is not None and k.upper() in MEASURED_WINDOWS:
            measured = measured_by_key.get(k.upper(), {})
        r = apply_scenario(
            positions, sc, sector_lookup=sector_lookup, scale=scale, measured=measured,
        )
        out.append({
            "key": k, "name": sc.name,
            "horizon_days": sc.horizon_days,
            "total_pnl": r["total_pnl"],
            "total_return_pct": r["total_return_pct"],
            "unpriced_positions": r["unpriced_positions"],
            "warnings": r["warnings"],
        })
    out.sort(key=lambda x: x["total_pnl"])
    return out
