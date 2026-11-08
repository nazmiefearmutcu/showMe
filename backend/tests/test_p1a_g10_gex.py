"""P1a-g10 GEX regressions: per-side walls and spot-grid gamma flip.

GEX#1: call_wall / put_wall must be the strike with the largest absolute
dealer call / put gamma exposure, not extrema of the strike-net GEX.
GEX#2: gamma_flip must be the zero crossing of total dealer GEX re-evaluated
across a spot grid with the same chain, not a strike-cumulative sign change.
"""

from __future__ import annotations

import asyncio

from showme.engine.services.gamma_exposure import bs_gamma, chain_gex

SPOT = 100.0
T = 30 / 365


def _call(strike: float, oi: float) -> dict:
    return {"strike": strike, "openInterest": oi, "T": T, "iv": 0.30}


def _put(strike: float, oi: float) -> dict:
    return {"strike": strike, "openInterest": oi, "T": T, "iv": 0.30}


def _net_at(spot: float, calls: list[dict], puts: list[dict]) -> float:
    total = 0.0
    for c in calls:
        g = bs_gamma(spot, c["strike"], c["iv"], c["T"], 0.04, 0.0)
        total -= g * c["openInterest"] * 100 * spot * spot * 0.01
    for p in puts:
        g = bs_gamma(spot, p["strike"], p["iv"], p["T"], 0.04, 0.0)
        total += g * p["openInterest"] * 100 * spot * spot * 0.01
    return total


# --------------------------------------------------------------------------- #
# GEX#1 — walls are per-side absolute maxima
# --------------------------------------------------------------------------- #
def test_walls_are_per_side_absolute_maxima_not_net_extrema() -> None:
    # Strike 100: call-dominated (negative dealer GEX).
    # Strike 105: tiny call OI but huge put OI -> largest NET positive strike,
    # which is put-dominated and must NOT be reported as the call wall.
    calls = [_call(100, 1000), _call(105, 1)]
    puts = [_put(105, 5000), _put(95, 100)]
    out = chain_gex(spot=SPOT, calls=calls, puts=puts)

    assert out["call_wall"]["strike"] == 100
    assert out["call_wall"]["gex"] < 0, "call wall must carry the dealer call-side GEX"
    assert out["put_wall"]["strike"] == 105
    assert out["put_wall"]["gex"] > 0, "put wall must carry the dealer put-side GEX"


# --------------------------------------------------------------------------- #
# GEX#2 — gamma flip is the spot-grid zero crossing of total GEX
# --------------------------------------------------------------------------- #
def test_gamma_flip_is_spot_grid_zero_crossing_not_strike_cumulative() -> None:
    calls = [_call(100, 1000), _call(105, 1), _call(110, 3000), _call(115, 30000)]
    puts = [_put(90, 5000), _put(95, 3000), _put(105, 5000)]
    out = chain_gex(spot=SPOT, calls=calls, puts=puts)

    flip = out["gamma_flip"]
    assert flip is not None, "a total-GEX sign change exists between 0.90S and 1.10S"
    # The old strike-cumulative method returned 115 here; the real zero of
    # total dealer GEX (same chain, spot re-evaluated) sits near spot.
    assert abs(flip - 115.0) > 1.0
    assert 0.90 * SPOT <= flip <= 1.10 * SPOT
    net_at_flip = _net_at(flip, calls, puts)
    net_at_spot = _net_at(SPOT, calls, puts)
    assert abs(net_at_flip) < 0.01 * abs(net_at_spot)


def test_gamma_flip_none_when_no_crossing_in_range() -> None:
    # Only puts: total dealer GEX is positive across the whole grid.
    out = chain_gex(spot=SPOT, calls=[], puts=[_put(95, 5000), _put(105, 5000)])
    assert out["gamma_flip"] is None


def test_gex_function_payload_reports_flip_method_and_per_side_walls() -> None:
    from showme.engine.core.base_function import FunctionDeps
    from showme.engine.functions.derivative.gex import GEXFunction

    class _Chain:
        async def fetch(self, request):  # noqa: ANN001
            import pandas as pd
            from showme.engine.core.base_data_source import DataKind

            if request.kind != DataKind.OPTIONS_CHAIN:
                return None
            if request.extra.get("expiry") is None:
                return {"expiries": ["2026-12-18"]}
            calls = pd.DataFrame([
                {"strike": 100.0, "openInterest": 1000, "impliedVolatility": 0.3},
                {"strike": 105.0, "openInterest": 1, "impliedVolatility": 0.3},
                {"strike": 110.0, "openInterest": 3000, "impliedVolatility": 0.3},
                {"strike": 115.0, "openInterest": 30000, "impliedVolatility": 0.3},
            ])
            puts = pd.DataFrame([
                {"strike": 90.0, "openInterest": 5000, "impliedVolatility": 0.3},
                {"strike": 95.0, "openInterest": 3000, "impliedVolatility": 0.3},
                {"strike": 105.0, "openInterest": 5000, "impliedVolatility": 0.3},
            ])
            return {"calls": calls, "puts": puts}

    fn = GEXFunction(deps=FunctionDeps(yfinance=_Chain()))
    result = asyncio.run(fn.execute(symbol="SPY", spot=SPOT, live_options=True))
    summary = result.data["summary"]
    assert summary["call_wall"] == 115.0  # largest absolute dealer call GEX
    assert summary["put_wall"] == 105.0
    assert summary["gamma_flip_method"] == "spot_grid_zero_crossing"
    assert summary["gamma_flip"] is not None and summary["gamma_flip"] != 115.0


# --------------------------------------------------------------------------- #
# GEX#2 — the manifest documents the method the handler actually runs
# --------------------------------------------------------------------------- #
def test_gex_manifest_documents_spot_grid_gamma_flip_not_cumulative() -> None:
    from showme.manifest import REGISTRY, load_seeds

    load_seeds()
    entry = REGISTRY.get("GEX")
    flip_formula = entry.formula_dict["gamma_flip"]
    flip_text = " ".join([
        flip_formula.expression,
        *flip_formula.variables.values(),
        entry.field_dict["gamma_flip"].description,
    ]).lower()

    assert "cumulative" not in flip_text
    assert "spot" in flip_text
    assert "cumulative signed" not in entry.methodology.lower()
    assert "spot" in entry.methodology.lower()
    for test in entry.semantic_tests:
        assert "cumulative_zero_cross" not in " ".join(test.assertions)
