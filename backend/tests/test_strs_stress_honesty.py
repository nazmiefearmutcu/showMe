"""STRS honesty regressions (p1a-g05).

* STRS#1 — a scaled shock must never push a position below zero market value.
* STRS#3 — bond ETFs must not take the equity-style ETF shock; TLT carries the
  measured window returns (Yahoo chart close, inclusive end dates).
* STRS#4 — the manifest must not claim historical replay that the code does not run.

All tests go through STRSFunction.execute() with PortfolioState replaced by an
in-memory fake, so no network or runtime/portfolio.json is read.
"""

from __future__ import annotations

import asyncio

import pytest

from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.portfolio import strs as strs_mod
from showme.engine.services import stress_scenarios as stress


class _Position:
    def __init__(self, symbol: str, asset_class: AssetClass, quantity: float, avg_cost: float):
        self.instrument = Instrument(symbol=symbol, asset_class=asset_class)
        self.quantity = quantity
        self.avg_cost = avg_cost


def _use_positions(monkeypatch, positions):
    class _Portfolio:
        def __init__(self):
            self.positions = positions

        def import_legacy_crypto(self):
            return None

    monkeypatch.setattr(strs_mod, "PortfolioState", _Portfolio)


def _run(coro):
    return asyncio.run(coro)


# ── STRS#1: no negative market value under scaling ──────────────────────


def test_strs1_scaled_shock_never_drives_market_value_negative(monkeypatch):
    _use_positions(monkeypatch, [_Position("AAPL", AssetClass.EQUITY, 100.0, 100.0)])
    res = _run(strs_mod.STRSFunction().execute(action="scenario", scenario="GFC_2008", scale=2))
    rows = res.data["positions"]
    assert rows[0]["market_value_post"] >= 0.0, rows[0]
    assert res.data["total_market_value_post"] >= 0.0
    assert any("AAPL" in w for w in res.warnings), res.warnings


def test_strs1_compare_path_floors_and_reports(monkeypatch):
    _use_positions(monkeypatch, [_Position("BTC-USD", AssetClass.CRYPTO, 1.0, 10_000.0)])
    res = _run(strs_mod.STRSFunction().execute(action="compare", scale=2))
    assert res.data["comparisons"]
    assert all(r["total_pnl"] >= -10_000.0 - 1e-9 for r in res.data["comparisons"])
    assert res.warnings, "floored shocks must be reported in warnings"


# ── STRS#3 and STRS#4 are appended below in their own steps ─────────────
