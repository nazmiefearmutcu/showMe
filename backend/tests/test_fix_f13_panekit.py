"""F13 fix-lane regressions — Pane-kit sweep (2026-09-11).

Evidence pins for the function-audit fixes owned by lane F13:

* PORT — the backend now emits ``totals.cost_basis`` (and stable-USD
  ``totals.cash`` + ``cash_by_currency`` when the book tracks cash). The pane's
  "Cost basis" tile and "Unrealized return" badge depended on ``cost_basis``
  but the backend never emitted it (audit A5 PORT H — field never existed).
"""

from __future__ import annotations

import asyncio

from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.portfolio.port import PORTFunction
from showme.engine.portfolio.state import PortfolioPosition, PortfolioState


def _equity_position(symbol: str, qty: float, cost: float) -> PortfolioPosition:
    return PortfolioPosition(
        instrument=Instrument(symbol=symbol, asset_class=AssetClass.EQUITY),
        quantity=qty,
        avg_cost=cost,
        currency="USD",
    )


def test_port_emits_real_cost_basis_and_stable_cash(tmp_path):
    """Portfolio path: cost_basis + stable-USD cash + per-currency map."""
    portfolio = PortfolioState(tmp_path / "portfolio.json")
    portfolio.positions = [
        _equity_position("AAPL", 10, 100.0),
        _equity_position("MSFT", 5, 200.0),
    ]
    portfolio.cash = {"USD": 100.0, "USDT": 50.0, "TRY": 500.0}

    res = asyncio.run(PORTFunction().execute(_portfolio_override=portfolio))
    totals = res.data["totals"]

    assert totals["cost_basis"] == 2000.0  # 10*100 + 5*200
    # Only stable-USD currencies sum into the USD cash figure; TRY stays in
    # the per-currency map so the terminal never converts by assumption.
    assert totals["cash"] == 150.0
    assert totals["cash_by_currency"] == {"USD": 100.0, "USDT": 50.0, "TRY": 500.0}


def test_port_positions_param_path_emits_cost_basis(tmp_path):
    """Params path: cost_basis is summed from qty × avg_cost."""
    portfolio = PortfolioState(tmp_path / "portfolio.json")
    res = asyncio.run(
        PORTFunction().execute(
            _portfolio_override=portfolio,
            positions=[
                {"symbol": "AAPL", "asset_class": "EQUITY", "quantity": 4,
                 "avg_cost": 25.0, "last": 30.0},
            ],
        )
    )
    totals = res.data["totals"]
    assert totals["cost_basis"] == 100.0
    assert totals["market_value"] == 120.0
    # No cash is tracked on this path — the field must be absent (em-dash),
    # never a confident $0.00.
    assert "cash" not in totals


def test_port_empty_book_cost_basis_zero_no_fake_cash(tmp_path):
    """Empty book: cost basis is genuinely zero; cash stays unknown (absent)."""
    portfolio = PortfolioState(tmp_path / "portfolio.json")
    res = asyncio.run(PORTFunction().execute(_portfolio_override=portfolio))
    totals = res.data["totals"]
    assert res.data["status"] == "ready_no_positions"
    assert totals["cost_basis"] == 0.0
    assert "cash" not in totals
    assert "cash_by_currency" not in totals


def test_port_non_string_cash_amounts_do_not_crash(tmp_path):
    """Malformed cash entries are dropped, never rendered as junk numbers."""
    portfolio = PortfolioState(tmp_path / "portfolio.json")
    portfolio.positions = [_equity_position("AAPL", 1, 10.0)]
    portfolio.cash = {"USD": "not-a-number", "USDT": 5.0, "BAD": None}
    res = asyncio.run(PORTFunction().execute(_portfolio_override=portfolio))
    totals = res.data["totals"]
    assert totals["cash"] == 5.0
    assert totals["cash_by_currency"] == {"USDT": 5.0}
