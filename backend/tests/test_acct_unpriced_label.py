"""ACCT-R1: symbols with no mark are named ``unpriced_symbols``, not ``stale_marks``.

``stale`` means a value exists but its as-of date is old. A symbol whose quote
failed (or that had no supplied ``last`` price) has no value at all, so the
metadata key must not claim it is stale.
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
    def __init__(self, prices: dict[str, float], fail: set[str]) -> None:
        self._prices = prices
        self._fail = fail

    async def fetch(self, request: Any) -> Quote:
        sym = request.instrument.symbol
        if sym in self._fail:
            raise RuntimeError("upstream down")
        return Quote(symbol=sym, timestamp=utcnow(), last=self._prices[sym])


def _run(coro):
    return asyncio.run(coro)


def test_failed_live_quote_is_reported_as_unpriced_not_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(acct_mod, "PortfolioState", _Book)
    fn = acct_mod.ACCTFunction(FunctionDeps(yfinance=_Yf({"TLT": 81.92, "SPY": 735.29}, fail={"TLT"})))
    res = _run(fn.execute())
    assert res.metadata["unpriced_symbols"] == ["TLT"]
    assert "stale_marks" not in res.metadata


def test_user_position_without_last_is_reported_as_unpriced_not_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Empty:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            self.positions: list[Any] = []

        def import_legacy_crypto(self, *_a: Any, **_k: Any) -> int:
            return 0

    monkeypatch.setattr(acct_mod, "PortfolioState", _Empty)
    fn = acct_mod.ACCTFunction(FunctionDeps())
    res = _run(fn.execute(positions=[
        {"symbol": "TLT", "asset_class": "ETF", "quantity": 10, "avg_cost": 90.0, "account": "main"},
    ]))
    assert res.metadata["unpriced_symbols"] == ["TLT"]
    assert "stale_marks" not in res.metadata
