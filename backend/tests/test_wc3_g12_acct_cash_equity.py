"""ACCT#2 — account equity includes the saved cash book, per currency.

The saved cash book (PortfolioState.cash) was never read, so the account total
was positions only. Cash is per currency and portfolio-wide, so it is reported
once; equity per currency is priced market value plus cash; a currency with an
unpriced position has no equity; one number is given only for a single
currency. Network and the portfolio book are replaced by fakes.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.core.quote import Quote, utcnow
from showme.engine.functions.portfolio import acct as acct_mod
from showme.engine.portfolio.state import PortfolioPosition


class _Book:
    def __init__(self, positions: list[PortfolioPosition], cash: Any) -> None:
        self.positions = positions
        self.cash = cash

    def import_legacy_crypto(self, *_args: Any, **_kwargs: Any) -> int:
        return 0


class _Yf:
    def __init__(self, prices: dict[str, float], fail: tuple[str, ...] = ()) -> None:
        self._prices = prices
        self._fail = set(fail)

    async def fetch(self, request: Any) -> Quote:
        sym = request.instrument.symbol
        if sym in self._fail:
            raise RuntimeError("upstream down")
        return Quote(symbol=sym, timestamp=utcnow(), last=self._prices[sym])


def _pos(symbol: str, qty: float, cost: float, currency: str = "USD") -> PortfolioPosition:
    return PortfolioPosition(
        instrument=Instrument(symbol=symbol, asset_class=AssetClass.ETF),
        quantity=qty, avg_cost=cost, account="main", currency=currency,
    )


def _run(monkeypatch, positions, cash, prices, fail=()) -> dict[str, Any]:
    monkeypatch.setattr(acct_mod, "PortfolioState", lambda *a, **k: _Book(positions, cash))
    fn = acct_mod.ACCTFunction(FunctionDeps(yfinance=_Yf(prices, fail)))
    return asyncio.run(fn.execute()).data


def test_equity_is_market_value_plus_saved_cash(monkeypatch) -> None:
    data = _run(
        monkeypatch,
        [_pos("TLT", 10.0, 90.0), _pos("SPY", 2.0, 700.0)],
        {"USD": 25000.0},
        {"TLT": 100.0, "SPY": 735.0},
    )
    market_value = 10.0 * 100.0 + 2.0 * 735.0
    summary = data["summary"]
    assert summary["cash_by_currency"] == {"USD": 25000.0}
    assert summary["equity_by_currency"] == {"USD": pytest.approx(market_value + 25000.0)}
    assert summary["total_equity"] == pytest.approx(market_value + 25000.0)
    assert data["total_equity"] == pytest.approx(market_value + 25000.0)
    # Positions-only market value is unchanged.
    assert summary["total_market_value"] == pytest.approx(market_value)


def test_unpriced_position_in_a_currency_leaves_its_equity_null(monkeypatch) -> None:
    data = _run(
        monkeypatch,
        [_pos("TLT", 10.0, 90.0), _pos("SPY", 2.0, 700.0)],
        {"USD": 25000.0},
        {"TLT": 100.0, "SPY": 735.0},
        fail=("SPY",),
    )
    summary = data["summary"]
    assert summary["cash_by_currency"] == {"USD": 25000.0}
    assert summary["equity_by_currency"] == {"USD": None}
    assert summary["total_equity"] is None
    assert data["status"] == "partial"


def test_two_currencies_are_not_summed_into_one_total(monkeypatch) -> None:
    data = _run(
        monkeypatch,
        [_pos("TLT", 10.0, 90.0, "USD"), _pos("BMW", 1.0, 80.0, "EUR")],
        {"USD": 100.0, "EUR": 50.0},
        {"TLT": 100.0, "BMW": 90.0},
    )
    summary = data["summary"]
    assert summary["equity_by_currency"] == {
        "EUR": pytest.approx(90.0 + 50.0),
        "USD": pytest.approx(1000.0 + 100.0),
    }
    assert summary["total_equity"] is None


def test_non_numeric_cash_is_unknown_not_zero(monkeypatch) -> None:
    # ACCT#2: unreadable cash makes that currency's equity unknown; it is not
    # served as market value + 0.
    data = _run(
        monkeypatch,
        [_pos("TLT", 10.0, 90.0)],
        {"USD": "n/a"},
        {"TLT": 100.0},
    )
    summary = data["summary"]
    assert summary["cash_by_currency"] == {}
    assert summary["unreadable_cash_currencies"] == ["USD"]
    assert summary["equity_by_currency"] == {"USD": None}
    assert summary["total_equity"] is None


def test_supplied_positions_state_that_cash_is_not_read(monkeypatch) -> None:
    monkeypatch.setattr(acct_mod, "PortfolioState", lambda *a, **k: _Book([], {"USD": 25000.0}))
    fn = acct_mod.ACCTFunction(FunctionDeps(yfinance=None))
    result = asyncio.run(fn.execute(positions=[
        {"symbol": "TLT", "asset_class": "ETF", "quantity": 1, "avg_cost": 90, "last": 100, "account": "main"},
    ]))
    summary = result.data["summary"]
    assert summary["cash_by_currency"] == {}
    assert summary["equity_by_currency"] == {}
    assert summary["total_equity"] is None
