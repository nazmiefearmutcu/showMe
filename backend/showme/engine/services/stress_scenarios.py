"""Stress test scenarios — predefined historical shocks + custom shocks.

Each scenario is a mapping: asset-class / sector / symbol → return shock (decimal).
The engine applies the shock to a portfolio's positions, recomputing market value
under the stressed regime. Custom shocks may be combined linearly with a scaling
factor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
# Predefined scenarios. Numbers are calibrated to peak-trough drawdowns
# observed historically (rough decimals — not investment advice).
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


def apply_scenario(
    positions: list[dict[str, Any]],
    scenario: StressScenario,
    *,
    sector_lookup: dict[str, str] | None = None,
    scale: float = 1.0,
) -> dict[str, Any]:
    """Apply a stress scenario to a list of position dicts.

    ``positions`` items must contain: ``symbol``, ``asset_class``, ``market_value``.
    Optional: ``sector`` (or use ``sector_lookup`` keyed by symbol).
    Returns a stressed portfolio + per-position breakdown.
    """
    sector_lookup = sector_lookup or {}
    rows: list[dict[str, Any]] = []
    total_pre = 0.0
    total_post = 0.0
    for p in positions:
        sym = p["symbol"]
        ac = p.get("asset_class", "EQUITY").upper()
        sector = p.get("sector") or sector_lookup.get(sym)
        mv = float(p.get("market_value", 0) or 0)
        # Resolve shock — symbol > sector > asset_class.
        shock = scenario.symbol_shocks.get(sym)
        if shock is None and sector:
            shock = scenario.sector_shocks.get(sector)
        if shock is None:
            shock = scenario.asset_class_shocks.get(ac, 0.0)
        shock = float(shock) * scale
        mv_post = mv * (1.0 + shock)
        rows.append({
            "symbol": sym, "asset_class": ac, "sector": sector,
            "shock": shock, "market_value_pre": mv,
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
        "positions": rows,
    }


def compare_scenarios(
    positions: list[dict[str, Any]],
    keys: list[str] | None = None,
    *,
    sector_lookup: dict[str, str] | None = None,
    scale: float = 1.0,
) -> list[dict[str, Any]]:
    keys = keys or list(SCENARIOS)
    out = []
    for k in keys:
        sc = SCENARIOS.get(k.upper())
        if not sc:
            continue
        r = apply_scenario(positions, sc, sector_lookup=sector_lookup, scale=scale)
        out.append({
            "key": k, "name": sc.name,
            "horizon_days": sc.horizon_days,
            "total_pnl": r["total_pnl"],
            "total_return_pct": r["total_return_pct"],
        })
    out.sort(key=lambda x: x["total_pnl"])
    return out
