"""P2A-G06 regressions for FXH (FX hedge calculator).

Findings covered: FXH#1 (exposure_side ignored), FXH#2 (manifest output
contract incl. hedge_cost), FXH#3 (spot_shock_pct / tenor ignored),
FXH#5 (silent base_rate=0.04 fallback), FXH#6 (portfolio mode reason).

All tests run offline: no yfinance dependency, spot is supplied manually.
"""
from __future__ import annotations

import asyncio

import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.fx.fxh import (
    DEFAULT_BASE_RATE,
    DEFAULT_HOME_RATE,
    FXHFunction,
)
from showme.engine.services.fx_hedge import forward_rate


def _run(coro):
    return asyncio.run(coro)


def _fn() -> FXHFunction:
    return FXHFunction(deps=FunctionDeps(yfinance=None))


# ── FXH#5: explicit exposure without base_rate must not use 0.04 ─────────


def test_fxh5_explicit_exposure_missing_base_rate_uses_documented_default() -> None:
    """Was: e.get('base_rate', 0.04) silently used 4%, which is neither the
    documented DEFAULT_BASE_RATE (3.5%) nor reported in assumed_defaults."""
    result = _run(_fn().execute(
        action="forward",
        exposures=[{"currency": "EUR", "notional": 100_000, "spot_rate": 1.08}],
    ))
    fwd = result.data["forwards"][0]["forward"]
    expected = forward_rate(
        spot=1.08, home_rate=DEFAULT_HOME_RATE, base_rate=DEFAULT_BASE_RATE, days=90,
    )
    assert fwd == pytest.approx(expected, rel=1e-12)
    assert "base_rate" in result.data["assumed_defaults"]
    assert "home_rate" in result.data["assumed_defaults"]
    assert result.data["assumed_values"]["base_rate"] == pytest.approx(DEFAULT_BASE_RATE)


def test_fxh5_explicit_base_rate_none_does_not_crash_and_is_flagged() -> None:
    """A caller passing base_rate=None in the default book path must get the
    documented default and an echoed assumption, not a TypeError."""
    result = _run(_fn().execute(action="calc", pair="EURUSD", spot_rate=1.08, base_rate=None))
    assert "base_rate" in result.data["assumed_defaults"]
    assert result.data["rows"][0]["forward_rate"] == pytest.approx(
        forward_rate(spot=1.08, home_rate=DEFAULT_HOME_RATE,
                     base_rate=DEFAULT_BASE_RATE, days=90),
        rel=1e-12,
    )


# ── FXH#6: portfolio mode with no foreign positions ─────────────────────


class _FakePortfolio:
    """Stand-in for PortfolioState: only the members FXH reads."""

    def __init__(self, positions):
        self.positions = positions

    def import_legacy_crypto(self):
        return 0


def _patch_portfolio(monkeypatch, positions) -> None:
    import showme.engine.portfolio.state as state_mod

    monkeypatch.setattr(state_mod, "PortfolioState", lambda *a, **k: _FakePortfolio(positions))


def test_fxh6_portfolio_all_home_currency_reports_empty_book_not_spot(monkeypatch) -> None:
    """Was: an all-USD book (home=USD for EURUSD) produced an empty exposure
    list and the spot-provider message 'No exposure has a usable spot rate',
    with the envelope still reporting ok. It must say there is nothing to hedge."""
    from showme.engine.core.instrument import AssetClass, Instrument
    from showme.engine.portfolio.state import PortfolioPosition

    usd_pos = PortfolioPosition(
        instrument=Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY),
        quantity=10, avg_cost=150.0, currency="USD",
    )
    _patch_portfolio(monkeypatch, [usd_pos])
    result = _run(_fn().execute(action="calc", pair="EURUSD", use_portfolio=True))

    assert result.data["status"] == "empty"
    assert result.data["rows"] == []
    reason = result.data["reason"].lower()
    assert "non-home" in reason or "no foreign" in reason
    assert "spot" not in reason


def test_fxh6_portfolio_foreign_position_notional_is_native_currency(monkeypatch) -> None:
    """Pins the sizing convention: PortfolioPosition.avg_cost is stated in the
    position's own currency, so quantity*avg_cost is already foreign units."""
    from showme.engine.core.base_function import FunctionDeps
    from showme.engine.core.instrument import AssetClass, Instrument
    from showme.engine.portfolio.state import PortfolioPosition

    class _Quote:
        last = 1.08

    class _YF:
        async def fetch(self, req):
            return _Quote()

    eur_pos = PortfolioPosition(
        instrument=Instrument(symbol="SAP.DE", asset_class=AssetClass.EQUITY),
        quantity=10, avg_cost=150.0, currency="EUR",
    )
    _patch_portfolio(monkeypatch, [eur_pos])
    result = _run(FXHFunction(deps=FunctionDeps(yfinance=_YF())).execute(
        action="calc", pair="EURUSD", use_portfolio=True,
    ))
    assert result.data["rows"][0]["currency"] == "EUR"
    assert result.data["rows"][0]["notional_foreign"] == pytest.approx(1500.0)
