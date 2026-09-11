"""FIX-F1 lane regressions (2026-09-11 FX family fixes).

Covers the contracts the fixed panes depend on:

  - FXH: a synthesized book without explicit inputs must echo
    ``assumed_defaults`` (+ the concrete ``assumed_values``) so a $1M/3.5%/4.5%
    illustrative book is never presented as the caller's own exposure. The
    pane's explicit ``notional``/``base_rate``/``home_rate`` inputs clear it,
    and the seed-declared ``exposure_notional`` alias is honoured.
  - WCRS: ``spread_pips`` is JPY-aware (factor 100 for a JPY quote, else
    10000) — the pane now renders that field instead of spread*10000.
  - OVDV: ``series[]`` rows carry ``atm_vol_pct`` (the pane's ATM term
    structure reads it; the old ``vol`` alias never existed on the wire).
"""
from __future__ import annotations

import asyncio

import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.fx._funcs import OVDVFunction, WCRSFunction
from showme.engine.functions.fx.fxh import FXHFunction


def _run(coro):
    return asyncio.run(coro)


# ── FXH: assumed-defaults echo ─────────────────────────────────────────


def test_fxh_default_book_echoes_assumed_defaults() -> None:
    """With no exposure/rate params the engine models $1M @ 3.5%/4.5% and
    must say so — before this, the pane rendered those numbers as the
    user's book with no disclosure."""
    fn = FXHFunction(deps=FunctionDeps(yfinance=None))
    result = _run(fn.execute(action="calc", pair="EURUSD", spot_rate=1.08))

    data = result.data
    assert data["assumed_defaults"] == ["notional", "base_rate", "home_rate"]
    assert data["assumed_values"] == {
        "notional": 1_000_000.0,
        "base_rate": 0.035,
        "home_rate": 0.045,
    }
    row = data["rows"][0]
    assert row["notional_foreign"] == pytest.approx(1_000_000.0)
    assert row["currency"] == "EUR"


def test_fxh_explicit_inputs_clear_assumed_defaults() -> None:
    """The pane sends explicit notional + rates; nothing may be flagged."""
    fn = FXHFunction(deps=FunctionDeps(yfinance=None))
    result = _run(
        fn.execute(
            action="calc",
            pair="EURUSD",
            spot_rate=1.08,
            notional=250_000,
            base_rate=0.02,
            home_rate=0.03,
        )
    )
    data = result.data
    assert data["assumed_defaults"] == []
    assert "assumed_values" not in data
    assert data["rows"][0]["notional_foreign"] == pytest.approx(250_000.0)


def test_fxh_accepts_exposure_notional_alias() -> None:
    """The manifest declares the input as ``exposure_notional``; the handler
    must accept that spelling alongside the pane's ``notional``."""
    fn = FXHFunction(deps=FunctionDeps(yfinance=None))
    result = _run(
        fn.execute(
            action="calc",
            pair="EURUSD",
            spot_rate=1.08,
            exposure_notional=500_000,
        )
    )
    data = result.data
    assert data["rows"][0]["notional_foreign"] == pytest.approx(500_000.0)
    assert "notional" not in data["assumed_defaults"]


def test_fxh_forward_branch_also_echoes_assumptions() -> None:
    fn = FXHFunction(deps=FunctionDeps(yfinance=None))
    result = _run(fn.execute(action="forward", pair="EURUSD", spot_rate=1.08))
    assert result.data["assumed_defaults"] == ["notional", "base_rate", "home_rate"]
    assert result.data["assumed_values"]["notional"] == pytest.approx(1_000_000.0)


# ── WCRS: JPY-aware spread pips ────────────────────────────────────────


def test_wcrs_spread_pips_uses_jpy_aware_pip_factor() -> None:
    """USDJPY pips use factor 100; other quotes use 10000. The pane's old
    local math (spread*10000) rendered USDJPY 100x wide."""
    result = _run(WCRSFunction(deps=FunctionDeps()).execute(live=False))
    rows = {(row["base"], row["quote"]): row for row in result.data["rows"]}

    usdjpy = rows[("USD", "JPY")]
    expected_jpy = (usdjpy["ask"] - usdjpy["bid"]) * 100
    assert usdjpy["spread_pips"] == pytest.approx(expected_jpy, abs=1e-3)

    eurusd = rows[("EUR", "USD")]
    expected_major = (eurusd["ask"] - eurusd["bid"]) * 10000
    assert eurusd["spread_pips"] == pytest.approx(expected_major, abs=1e-3)


# ── OVDV: series[].atm_vol_pct contract ────────────────────────────────


def test_ovdv_series_ships_atm_vol_pct_matching_the_surface() -> None:
    """The pane's ATM term structure reads series[].atm_vol_pct; the field
    must exist and equal the ATM cell of the same tenor."""
    result = _run(OVDVFunction(deps=FunctionDeps()).execute(pair="EURUSD"))
    data = result.data

    atm_by_tenor = {
        row["tenor"]: float(row["vol"])
        for row in data["surface"]
        if row["delta"] == "ATM"
    }
    series = data["series"]
    assert series, "OVDV must ship the ATM term structure"
    for point in series:
        assert "atm_vol_pct" in point, "pane contract: series[].atm_vol_pct"
        assert point["atm_vol_pct"] == pytest.approx(
            atm_by_tenor[point["tenor"]], abs=1e-6
        )


# ── FXFC: manifest re-synced with the implementation ───────────────────


def test_fxfc_manifest_name_and_contract_match_the_handler() -> None:
    """The seed used to describe a consensus/bull-bear survey that was never
    implemented; the manifest must now describe the CIP forecast actually
    served (name + must_have fields present in the handler payload)."""
    from showme.engine.functions.fx._funcs import FXFCFunction
    from showme.manifest.seeds.fxfc_seed import fxfc

    assert fxfc.name == "FX Forecasts"
    assert fxfc.name == FXFCFunction.name
    assert fxfc.chart_grammar.kind.value == "tenor_curve"

    result = _run(FXFCFunction(deps=FunctionDeps()).execute(pair="EURUSD"))
    for key in fxfc.output_contract.must_have:
        assert key in result.data, f"manifest must_have missing from payload: {key}"
    # The pane reads rows from `forecast` (curve is the same ladder alias).
    assert result.data["forecast"] == result.data["curve"]

