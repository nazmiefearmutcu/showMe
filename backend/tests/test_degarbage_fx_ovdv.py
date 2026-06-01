"""De-garbage tests for OVDV (FX Option Volatility Surface).

Before the fix, OVDV anchored every tenor's ATM vol to a hardcoded 0.085
constant. After the fix the ATM term structure is derived from LIVE FX
realized volatility (yfinance daily history -> annualized stdev per tenor),
with the 25d RR/BF smile overlaid around that real anchor.

The tests are network-guarded: when yfinance returns history they assert the
live-anchored contract (varying ATM curve, not the flat 0.085); when history
is unavailable they assert the honest, clearly-labelled reference fallback.
"""
from __future__ import annotations

import asyncio

import pytest

from showme.engine.functions.fx._funcs import OVDVFunction

# The pre-fix garbage pinned every tenor's ATM to this single constant.
GARBAGE_ATM_VOL_PCT = 8.5  # 0.085 * 100


def _run(coro):
    return asyncio.run(coro)


def _atm_vols_pct(surface: list[dict]) -> list[float]:
    """ATM (delta == 'ATM') vol per tenor, in percent, in tenor order."""
    out = []
    seen = set()
    for row in surface:
        if row.get("delta") == "ATM" and row["tenor"] not in seen:
            seen.add(row["tenor"])
            out.append(round(float(row["vol"]), 6))
    return out


def _is_reference_fallback(result) -> bool:
    return result.data.get("vol_source") == "reference_fx_vol_model"


def test_ovdv_contract_shape_present():
    """OVDV must satisfy the seed output contract regardless of network."""
    fn = OVDVFunction()
    result = _run(fn.execute(pair="EURUSD"))

    assert result.code == "OVDV"
    data = result.data
    # Seed must_have keys + degarbage data keys.
    for key in ("pair", "as_of", "surface", "vol_source", "data_mode",
                "rows", "series", "cards", "methodology", "field_dictionary"):
        assert key in data, f"missing required key: {key}"

    assert isinstance(data["methodology"], str) and data["methodology"].strip()
    assert data["pair"] == "EURUSD"

    # Every surface cell carries a finite vol and a source_mode tag.
    assert data["surface"], "surface must not be empty"
    for row in data["surface"]:
        assert isinstance(row["vol"], (int, float))
        assert row["vol"] == row["vol"]  # not NaN
        assert row.get("source_mode")
        assert "tenor" in row and "delta" in row

    # Card slots from card_schema.
    cards = data["cards"]
    for slot in ("pair", "atm_vol_pct", "risk_reversal_25d_pct",
                 "butterfly_25d_pct", "vol_source", "data_mode", "as_of"):
        assert slot in cards


def test_ovdv_atm_anchored_to_live_realized_vol_not_constant():
    """The ATM curve must come from real realized vol, not the 0.085 stub."""
    fn = OVDVFunction()
    result = _run(fn.execute(pair="EURUSD"))
    data = result.data

    if _is_reference_fallback(result):
        # Honest, clearly-labelled outage path.
        assert data["data_mode"] == "MODELED"
        assert result.warnings, "reference fallback must carry a warning"
        assert data.get("next_actions")
        pytest.skip("yfinance history unavailable - validated labelled reference fallback")

    # Live path: anchored to yfinance realized vol.
    assert data["vol_source"] == "live_realized_vol"
    assert data["data_mode"] == "DELAYED_REFERENCE"
    assert "yfinance" in result.sources

    atm = _atm_vols_pct(data["surface"])
    assert len(atm) >= 3, "expected a multi-tenor ATM term structure"

    # REAL data: the ATM curve must NOT be a flat line pinned to 8.5%.
    assert len(set(atm)) > 1, "ATM vol must vary across tenors (real surface)"
    flat_garbage = all(abs(v - GARBAGE_ATM_VOL_PCT) < 1e-9 for v in atm)
    assert not flat_garbage, "ATM vol is still the hardcoded 0.085 constant"

    # Realized FX vols are positive and in a sane band (well under 100%).
    for v in atm:
        assert 0.0 < v < 100.0


def test_ovdv_smile_is_anchored_around_atm():
    """For each tenor, 25C/25P straddle the ATM cell (smile is a perturbation
    of the real ATM, not independent constants)."""
    fn = OVDVFunction()
    result = _run(fn.execute(pair="GBPUSD"))
    if _is_reference_fallback(result):
        pytest.skip("yfinance history unavailable")

    surface = result.data["surface"]
    by_tenor: dict[str, dict[str, float]] = {}
    for row in surface:
        by_tenor.setdefault(row["tenor"], {})[row["delta"]] = float(row["vol_decimal"])

    assert by_tenor
    for tenor, cells in by_tenor.items():
        atm = cells["ATM"]
        # butterfly premium keeps both 25-delta wings near (not collapsed onto)
        # the ATM; they must be finite, positive vols.
        assert cells["25C"] > 0 and cells["25P"] > 0
        # average of the two 25d wings sits at/above ATM by the butterfly.
        wing_avg = 0.5 * (cells["25C"] + cells["25P"])
        assert wing_avg >= atm - 1e-9, f"{tenor}: wings below ATM minus tolerance"


def test_ovdv_explicit_atm_override_is_honoured():
    """An explicit atm_vol input bypasses the live anchor and is labelled."""
    fn = OVDVFunction()
    result = _run(fn.execute(pair="EURUSD", atm_vol=0.11))
    data = result.data
    assert data["vol_source"] == "user_inputs"
    atm = _atm_vols_pct(data["surface"])
    # First tenor ATM should reflect the 11% override (term slope adds a touch).
    assert abs(atm[0] - 11.0) < 0.5


def test_ovdv_does_not_break_sibling_fxfc():
    """Sanity: the shared module still imports and a sibling still runs."""
    from showme.engine.functions.fx._funcs import FXFCFunction

    result = _run(FXFCFunction().execute(pair="EURUSD"))
    assert result.code == "FXFC"
    assert result.data["forecast"]
