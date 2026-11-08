"""REBA honesty regressions (wb1-g21): REBA#3, REBA#4, REBA#5.

* REBA#3: a held position without a live quote must never be valued at
  average cost inside the live weights. The preview is withheld with an
  explicit ``provider_unavailable`` state naming the unpriced positions.
* REBA#4: USD cash is part of the NAV the targets are applied to, and is
  shown as its own line in the weights.
* REBA#5: manifest controls must match the handler. ``min_trade_size`` and
  ``lot_rounding`` are honoured; controls that cannot be honoured are not
  declared.
"""

from __future__ import annotations

import asyncio
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
    """Yahoo-style fake: prices from a dict, raises for anything missing."""

    def __init__(self, prices):
        self.prices = prices

    async def fetch(self, request):
        sym = request.instrument.symbol
        if sym not in self.prices:
            raise RuntimeError(f"no quote for {sym}")
        return Quote(symbol=sym, timestamp=datetime.now(timezone.utc), last=self.prices[sym])


def _patch_book(monkeypatch, book):
    monkeypatch.setattr(reba_mod, "PortfolioState", lambda: book)


# ── REBA#3: unpriced held position is never valued at cost ───────────────


def test_reba3_unpriced_held_position_withholds_preview(monkeypatch):
    _patch_book(monkeypatch, _Book([_Pos("AAPL", 50, 180.0)]))
    # FunctionDeps() has no yfinance provider: AAPL cannot be marked.
    res = _run(REBAFunction(FunctionDeps()).execute(
        targets={"SPY": 1.0}, live_portfolio=True,
    ))
    assert res.data["status"] == "provider_unavailable"
    assert res.data["orders"] == []
    assert res.data["liquidations"] == []
    # Cost basis must not reappear as a weight or a total.
    assert "total_value" not in res.data
    assert "current_weights_pct" not in res.data
    assert [p["symbol"] for p in res.data["unpriced_positions"]] == ["AAPL"]
    assert any("AAPL" in w for w in res.warnings)
    assert res.data["next_actions"]


def test_reba3_partially_priced_book_still_withholds(monkeypatch):
    # AAPL is marked; NVDA is not. Mixing a live mark with cost in one
    # book is exactly the mixed-basis weight the defect describes.
    _patch_book(monkeypatch, _Book([_Pos("AAPL", 10, 100.0), _Pos("NVDA", 40, 135.0)]))
    res = _run(REBAFunction(FunctionDeps(yfinance=_PriceYf({"AAPL": 342.37}))).execute(
        targets={"AAPL": 0.5, "NVDA": 0.5}, live_portfolio=True,
    ))
    assert res.data["status"] == "provider_unavailable"
    assert res.data["orders"] == []
    assert [p["symbol"] for p in res.data["unpriced_positions"]] == ["NVDA"]


def test_reba3_fully_priced_book_values_at_live_marks(monkeypatch):
    _patch_book(monkeypatch, _Book([_Pos("AAPL", 10, 100.0), _Pos("NVDA", 40, 135.0)]))
    res = _run(REBAFunction(FunctionDeps(yfinance=_PriceYf({
        "AAPL": 342.37, "NVDA": 186.64,
    }))).execute(targets={"AAPL": 0.5, "NVDA": 0.5}, live_portfolio=True))
    assert res.data.get("status") is None
    assert res.data["total_value"] == pytest.approx(10 * 342.37 + 40 * 186.64)
    assert res.data["current_weights_pct"]["AAPL"] == pytest.approx(
        10 * 342.37 / (10 * 342.37 + 40 * 186.64) * 100
    )
