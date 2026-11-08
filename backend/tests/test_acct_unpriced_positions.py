"""ACCT regressions: a position with no live mark is never valued at cost.

Two residuals of ACCT#1 are pinned here:

* The user-supplied ``positions`` branch used to fall back to ``avg_cost``
  when a row had no ``last`` price, so the row was booked at cost as market
  value and included in totals.
* The symbol registry lookup ran outside the mark timeout, so a hanging
  resolver could stall the whole call beyond the mark budget.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.core.quote import Quote, utcnow
from showme.engine.functions.portfolio import acct as acct_mod
from showme.engine.portfolio.state import PortfolioPosition


class _EmptyBook:
    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        self.positions: list[Any] = []

    def import_legacy_crypto(self, *_args: Any, **_kwargs: Any) -> int:
        return 0


class _Yf:
    def __init__(self, prices: dict[str, float]) -> None:
        self._prices = prices

    async def fetch(self, request: Any) -> Quote:
        sym = request.instrument.symbol
        return Quote(symbol=sym, timestamp=utcnow(), last=self._prices[sym])


def _run(coro):
    return asyncio.run(coro)


def test_user_position_without_last_is_not_valued_at_cost(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(acct_mod, "PortfolioState", _EmptyBook)
    fn = acct_mod.ACCTFunction(FunctionDeps())
    positions = [
        {"symbol": "TLT", "asset_class": "ETF", "quantity": 10, "avg_cost": 90.0, "account": "main"},
        {"symbol": "SPY", "asset_class": "ETF", "quantity": 2, "avg_cost": 700.0, "last": 735.29,
         "account": "main"},
    ]
    res = _run(fn.execute(positions=positions))

    rows = {p["symbol"]: p for p in res.data["accounts"][0]["positions"]}
    # TLT has no mark: market value is unknown, never avg_cost * quantity.
    assert rows["TLT"]["market_value"] is None
    assert rows["TLT"]["priced"] is False
    assert rows["SPY"]["market_value"] == pytest.approx(2 * 735.29)
    # Totals exclude the unpriced row instead of counting it at cost.
    assert res.data["cross"]["total_mv"] == pytest.approx(2 * 735.29)
    assert "TLT" not in res.data["cross"]["by_symbol"]
    assert res.data["status"] == "partial"
    assert res.data["summary"]["total_market_value_complete"] is False
    assert any("TLT" in w for w in res.warnings)


def test_user_positions_all_priced_stay_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(acct_mod, "PortfolioState", _EmptyBook)
    fn = acct_mod.ACCTFunction(FunctionDeps())
    res = _run(fn.execute(positions=[
        {"symbol": "AAPL", "asset_class": "EQUITY", "quantity": 10, "avg_cost": 100, "last": 200,
         "account": "main"},
    ]))
    assert res.data["status"] == "ok"
    assert res.data["cross"]["total_mv"] == pytest.approx(2000.0)
    assert res.warnings == []


def test_hanging_symbol_resolver_is_bounded_by_mark_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Book:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            self.positions = [
                PortfolioPosition(instrument=Instrument(symbol="TLT", asset_class=AssetClass.ETF),
                                  quantity=10.0, avg_cost=90.0, account="main"),
                PortfolioPosition(instrument=Instrument(symbol="SPY", asset_class=AssetClass.ETF),
                                  quantity=2.0, avg_cost=700.0, account="main"),
            ]

        def import_legacy_crypto(self, *_args: Any, **_kwargs: Any) -> int:
            return 0

    class _HangingForTLT:
        async def resolve(self, sym: str) -> None:
            if sym == "TLT":
                await asyncio.sleep(5.0)
            return None

    monkeypatch.setattr(acct_mod, "PortfolioState", _Book)
    # raising=False: the pre-fix module has no MARK_TIMEOUT_* constants, so the
    # test must fail on the unbounded resolver (elapsed time), not on a missing name.
    monkeypatch.setattr(acct_mod, "MARK_TIMEOUT_FLOOR_S", 0.05, raising=False)
    monkeypatch.setattr(acct_mod, "MARK_TIMEOUT_CEIL_S", 0.05, raising=False)
    fn = acct_mod.ACCTFunction(FunctionDeps(
        yfinance=_Yf({"TLT": 81.92, "SPY": 735.29}),
        symbol_registry=_HangingForTLT(),
    ))

    started = time.monotonic()
    res = _run(fn.execute(mark_timeout=0.05))
    elapsed = time.monotonic() - started

    assert elapsed < 2.0
    rows = {p["symbol"]: p for p in res.data["accounts"][0]["positions"]}
    assert rows["TLT"]["priced"] is False
    assert "timed out" in rows["TLT"]["quote_error"]
    assert rows["TLT"]["market_value"] is None
    assert rows["SPY"]["last"] == pytest.approx(735.29)
