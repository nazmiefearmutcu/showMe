"""P2A-G06 review fixes for FXH (FX hedge calculator).

Covers the reviewer problems on the group's commits: FXH#1 (top-level
exposure_side must match the computed row side), FXH#2 (manifest units),
FXH#3 (spot_shock_pct range), FXH#6 (portfolio cost-basis disclosure).

All tests run offline: spot is supplied manually or the fetcher is stubbed.
"""
from __future__ import annotations

import asyncio

import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.fx.fxh import FXHFunction


def _run(coro):
    return asyncio.run(coro)


def _fn() -> FXHFunction:
    return FXHFunction(deps=FunctionDeps(yfinance=None))


# ── FXH#1: top-level exposure_side follows the row side ─────────────────


def test_fxh1_single_short_exposure_top_level_side_matches_row() -> None:
    """Was: a single explicit exposure with side=short_foreign reported the
    request default long_foreign at top level while its row and P&L were short."""
    result = _run(_fn().execute(
        action="calc", pair="EURUSD", hedge_ratio=0.5, spot_shock_pct=5.0,
        base_rate=0.02, home_rate=0.03, bid_ask_pips=2.0,
        exposures=[{"currency": "EUR", "notional": 1_000_000, "spot_rate": 1.08,
                    "side": "short_foreign"}],
    ))
    assert result.data["rows"][0]["exposure_side"] == "short_foreign"
    assert result.data["exposure_side"] == "short_foreign"
    assert result.data["rows"][0]["pnl_unhedged"] == pytest.approx(-54_000.0)
    assert result.data["pnl_unhedged"] == pytest.approx(-54_000.0)


def test_fxh1_mixed_sides_top_level_side_is_none() -> None:
    """Two rows with different sides have no single top-level side."""
    result = _run(_fn().execute(
        action="calc", pair="EURUSD", hedge_ratio=0.5, spot_shock_pct=5.0,
        base_rate=0.02, home_rate=0.03, bid_ask_pips=2.0,
        exposures=[
            {"currency": "EUR", "notional": 100_000, "spot_rate": 1.08, "side": "long_foreign"},
            {"currency": "GBP", "notional": 50_000, "spot_rate": 1.27, "side": "short_foreign"},
        ],
    ))
    assert result.data["exposure_side"] is None


# ── FXH#2: manifest units match the home (quote) currency the handler uses ──


def test_fxh2_pnl_and_cost_units_are_home_quote_currency_not_base() -> None:
    """Was: hedge_cost/pnl_* declared unit='base_ccy' and the methodology said
    'base currency', while the handler computes them in home (quote) currency."""
    from showme.manifest.seeds.fxh_seed import fxh

    for key in ("hedge_cost", "pnl_unhedged", "pnl_hedged"):
        assert fxh.field_dict[key].unit == "quote_ccy", key
    assert "base currency" not in fxh.methodology.lower()
    assert "home" in fxh.methodology.lower()


# ── FXH#3: spot_shock_pct is a percent and must stay inside the manifest range ─


def test_fxh3_spot_shock_outside_manifest_range_is_input_error() -> None:
    """Was: spot_shock_pct=150 became a 1.5 decimal shock (spot_if_home_strengthens
    negative) with no error. The manifest range is -50..50 percent."""
    for bad in (150.0, -60.0):
        result = _run(_fn().execute(
            action="calc", pair="EURUSD", spot_rate=1.08, notional=1_000_000,
            base_rate=0.02, home_rate=0.03, spot_shock_pct=bad,
        ))
        assert result.data["status"] == "input_error", bad
        assert "spot_shock_pct" in result.data["reason"]
        assert result.data["rows"] == []


def test_fxh3_spot_shock_at_range_edge_is_accepted() -> None:
    result = _run(_fn().execute(
        action="calc", pair="EURUSD", spot_rate=1.08, notional=1_000_000,
        base_rate=0.02, home_rate=0.03, spot_shock_pct=50.0,
    ))
    assert result.data["rows"][0]["scenario_usd_strengthens_pct"] == pytest.approx(50.0)


# ── FXH#6: portfolio notionals are disclosed as historical cost basis ──────


class _FakePortfolio:
    def __init__(self, positions):
        self.positions = positions

    def import_legacy_crypto(self):
        return 0


def test_fxh6_portfolio_notional_basis_is_disclosed(monkeypatch) -> None:
    """Was: notional = quantity * avg_cost (a historical cost basis) was not
    disclosed, and the hedge does not follow price moves."""
    import showme.engine.portfolio.state as state_mod
    from showme.engine.core.instrument import AssetClass, Instrument
    from showme.engine.portfolio.state import PortfolioPosition

    eur_pos = PortfolioPosition(
        instrument=Instrument(symbol="SAP.DE", asset_class=AssetClass.EQUITY),
        quantity=10, avg_cost=150.0, currency="EUR",
    )
    monkeypatch.setattr(state_mod, "PortfolioState", lambda *a, **k: _FakePortfolio([eur_pos]))

    class _Quote:
        last = 1.08

    class _YF:
        async def fetch(self, req):
            return _Quote()

    result = _run(FXHFunction(deps=FunctionDeps(yfinance=_YF())).execute(
        action="calc", pair="EURUSD", use_portfolio=True,
    ))
    assert result.data["notional_basis"] == "portfolio_historical_cost"
    assert any("historical cost" in w for w in result.warnings)
    assert "historical cost" in result.data["methodology"]


def test_fxh6_explicit_exposure_notional_basis_is_user_supplied() -> None:
    result = _run(_fn().execute(
        action="calc", pair="EURUSD", spot_rate=1.08, notional=1_000_000,
        base_rate=0.02, home_rate=0.03,
    ))
    assert result.data["notional_basis"] == "user_supplied"
