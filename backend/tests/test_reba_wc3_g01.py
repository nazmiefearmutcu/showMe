"""WC3-G01 REBA regressions: REBA#1, REBA#2 and the NaN-quote follow-up (REBA#3-RQ).

* REBA#1: the default model mode must not invent holdings or prices, so it
  sizes no orders and reports no current weights.
* REBA#2: live current weights use NAV (positions plus cash) as the only
  denominator, so they sum to 100 percent.
* REBA#3-RQ: a non-finite quote (NaN) is treated as unpriced, the same as a
  missing quote. It must never propagate into weights or order sizes.

Offline: the portfolio book and the quote provider are fakes.
"""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timezone

import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.core.quote import Quote
from showme.engine.functions.portfolio import reba as reba_mod
from showme.engine.functions.portfolio.reba import REBAFunction


def _run(coro):
    return asyncio.run(coro)


class _Pos:
    def __init__(self, symbol, quantity, avg_cost, asset_class=AssetClass.EQUITY):
        self.instrument = Instrument(symbol=symbol, asset_class=asset_class)
        self.quantity = quantity
        self.avg_cost = avg_cost


class _Book:
    def __init__(self, positions, cash=None):
        self.positions = positions
        self.cash = dict(cash or {})

    def import_legacy_crypto(self):  # pragma: no cover - not exercised
        return 0


class _PriceYf:
    """Quote fake: returns the configured last price, raises for any other symbol."""

    def __init__(self, prices):
        self.prices = prices

    async def fetch(self, request):
        sym = request.instrument.symbol
        if sym not in self.prices:
            raise RuntimeError(f"no quote for {sym}")
        return Quote(symbol=sym, timestamp=datetime.now(timezone.utc), last=self.prices[sym])


def _patch_book(monkeypatch, book):
    monkeypatch.setattr(reba_mod, "PortfolioState", lambda: book)


def _deps(prices):
    return FunctionDeps(yfinance=_PriceYf(prices))


# ── REBA#1: model mode invents nothing ───────────────────────────────────


def test_reba1_default_model_mode_sizes_no_orders_and_no_weights():
    res = _run(REBAFunction(FunctionDeps()).execute(
        targets={"SPY": 0.4, "QQQ": 0.25, "TLT": 0.2, "GLD": 0.15},
    ))
    assert res.data["status"] == "needs_input"
    assert res.data["orders"] == []
    assert res.data["rows"] == []
    assert "current_weights_pct" not in res.data
    assert "total_value" not in res.data
    assert res.metadata.get("live") is False


# ── REBA#2: live weights use NAV as the only denominator ─────────────────


def test_reba2_live_current_weights_sum_to_one_hundred_percent(monkeypatch):
    # The book is worth more than max_notional; the old code divided the full
    # book by the capped total and reported weights above 100 percent.
    book = _Book(
        [_Pos("AAPL", 10, 100.0), _Pos("SPY", 20, 400.0)],
        cash={"USD": 1_000.0},
    )
    _patch_book(monkeypatch, book)
    res = _run(REBAFunction(_deps({"AAPL": 150.0, "SPY": 500.0})).execute(
        targets={"AAPL": 0.5, "SPY": 0.5}, live_portfolio=True, max_notional=100_000,
    ))
    assert "status" not in res.data  # a computed preview, not a withheld state
    weights = res.data["current_weights_pct"]
    assert sum(weights.values()) == pytest.approx(100.0, abs=1e-6)
    # AAPL 1500 + SPY 10000 + USD 1000 = 12500 NAV.
    assert res.data["total_value"] == pytest.approx(12_500.0)
    assert weights["AAPL"] == pytest.approx(1_500.0 / 12_500.0 * 100)


# ── REBA#3-RQ: a NaN quote is unpriced, not a number ─────────────────────


def test_reba3rq_nan_quote_withholds_preview_like_a_missing_quote(monkeypatch):
    _patch_book(monkeypatch, _Book([_Pos("AAPL", 10, 100.0)]))
    res = _run(REBAFunction(_deps({"AAPL": float("nan")})).execute(
        targets={"AAPL": 1.0}, live_portfolio=True,
    ))
    assert res.data["status"] == "provider_unavailable"
    assert res.data["orders"] == []
    assert "total_value" not in res.data
    assert "current_weights_pct" not in res.data
    assert [p["symbol"] for p in res.data["unpriced_positions"]] == ["AAPL"]


def test_reba3rq_nan_target_quote_never_reaches_an_order(monkeypatch):
    # AAPL is priced; the target SPY has a NaN quote and no holding. The NaN
    # must not size an order for SPY.
    _patch_book(monkeypatch, _Book([_Pos("AAPL", 10, 100.0)], cash={"USD": 5_000.0}))
    res = _run(REBAFunction(_deps({"AAPL": 100.0, "SPY": float("nan")})).execute(
        targets={"AAPL": 0.5, "SPY": 0.5}, live_portfolio=True,
    ))
    assert "status" not in res.data  # a computed preview, not a withheld state
    for row in res.data["orders"] + res.data["liquidations"]:
        for key in ("quantity", "notional_delta", "price"):
            value = row.get(key)
            if value is not None:
                assert math.isfinite(value), (row["symbol"], key, value)
    spy = [o for o in res.data["orders"] if o["symbol"] == "SPY"]
    assert all(o["price_unavailable"] for o in spy)
