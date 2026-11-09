"""ACCT#1 regression: a failed or slow quote is never marked at average cost.

Before the fix, ``_q()`` swallowed every quote failure and returned
``avg_cost`` as the last price, so unrealized P&L read 0, market value equalled
cost, and the row looked like a live mark. The router also injects
``quote_timeout=3`` for every routed call, which made slow yfinance quotes
fall back to cost in the default pane run.
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
    """Hermetic stand-in for PortfolioState with two positions."""

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        self.positions = [
            PortfolioPosition(
                instrument=Instrument(symbol="TLT", asset_class=AssetClass.ETF),
                quantity=10.0, avg_cost=90.0, account="main",
            ),
            PortfolioPosition(
                instrument=Instrument(symbol="SPY", asset_class=AssetClass.ETF),
                quantity=2.0, avg_cost=700.0, account="main",
            ),
        ]

    def import_legacy_crypto(self, *_args: Any, **_kwargs: Any) -> int:
        return 0


class _Yf:
    def __init__(self, prices: dict[str, float], fail=(), delay=None) -> None:
        self._prices = prices
        self._fail = set(fail)
        self._delay = dict(delay or {})

    async def fetch(self, request: Any) -> Quote:
        sym = request.instrument.symbol
        if self._delay.get(sym):
            await asyncio.sleep(self._delay[sym])
        if sym in self._fail:
            raise RuntimeError("upstream down")
        return Quote(symbol=sym, timestamp=utcnow(), last=self._prices[sym])


def _run(coro):
    return asyncio.run(coro)


def _rows_by_symbol(res) -> dict[str, dict[str, Any]]:
    return {p["symbol"]: p for p in res.data["accounts"][0]["positions"]}


def test_failed_quote_is_not_marked_at_cost(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(acct_mod, "PortfolioState", _Book)
    fn = acct_mod.ACCTFunction(FunctionDeps(yfinance=_Yf({"TLT": 81.92, "SPY": 735.29}, fail={"TLT"})))
    res = _run(fn.execute())

    tlt = _rows_by_symbol(res)["TLT"]
    # The failed TLT quote must not be booked at avg_cost (90.0).
    assert tlt["last"] is None
    assert tlt["market_value"] is None
    assert tlt["unrealized_pnl"] is None
    assert tlt["priced"] is False
    assert tlt["quote_error"]

    # SPY is still marked live and totals exclude the unpriced TLT row.
    assert _rows_by_symbol(res)["SPY"]["last"] == pytest.approx(735.29)
    assert res.data["cross"]["total_mv"] == pytest.approx(2 * 735.29)
    assert "TLT" not in res.data["cross"]["by_symbol"]
    assert res.data["cross"]["unpriced_symbols"] == ["TLT"]

    # The gap is visible, not silent.
    assert res.data["status"] == "partial"
    assert res.data["summary"]["total_market_value_complete"] is False
    assert any("TLT" in w for w in res.warnings)
    # ACCT-R1: a symbol with no mark is unpriced, not stale (no as-of value exists).
    assert res.metadata["unpriced_symbols"] == ["TLT"]
    assert "stale_marks" not in res.metadata


def test_routed_default_timeout_still_gets_live_mark(monkeypatch: pytest.MonkeyPatch) -> None:
    """The router injects quote_timeout=3; a 3.5 s live quote must still be marked."""
    monkeypatch.setattr(acct_mod, "PortfolioState", _Book)
    fn = acct_mod.ACCTFunction(
        FunctionDeps(yfinance=_Yf({"TLT": 81.92, "SPY": 735.29}, delay={"TLT": 3.5}))
    )
    res = _run(fn.execute(quote_timeout=3))

    tlt = _rows_by_symbol(res)["TLT"]
    assert tlt["last"] == pytest.approx(81.92)
    assert tlt["market_value"] == pytest.approx(819.2)
    assert res.data["status"] == "ok"
    assert res.warnings == []
