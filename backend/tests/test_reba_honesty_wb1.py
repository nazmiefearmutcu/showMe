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


# ── REBA#4: USD cash is part of the NAV the targets apply to ─────────────


def test_reba4_cash_only_book_is_sized_against_cash(monkeypatch):
    # The reviewer's case: a book that is all cash must not be reported as
    # "no positions"; its USD balance is the NAV the targets deploy.
    _patch_book(monkeypatch, _Book([], cash={"USD": 25_000.0}))
    res = _run(REBAFunction(FunctionDeps(yfinance=_PriceYf({"SPY": 100.0}))).execute(
        targets={"SPY": 1.0}, live_portfolio=True,
    ))
    assert res.data.get("status") is None
    assert res.data["total_value"] == pytest.approx(25_000.0)
    assert res.data["cash_usd"] == pytest.approx(25_000.0)
    assert res.data["current_weights_pct"]["CASH"] == pytest.approx(100.0)
    buy = next(o for o in res.data["orders"] if o["symbol"] == "SPY")
    assert buy["action"] == "BUY"
    assert buy["notional_delta"] == pytest.approx(25_000.0)


def test_reba4_cash_is_in_denominator_and_own_weight(monkeypatch):
    # 10 AAPL at 342.37 = 3,423.70 invested plus 25,000 cash = 28,423.70 NAV.
    _patch_book(monkeypatch, _Book([_Pos("AAPL", 10, 100.0)], cash={"USD": 25_000.0}))
    # Fractional lots isolate the cash/NAV behaviour from whole-share rounding.
    res = _run(REBAFunction(FunctionDeps(yfinance=_PriceYf({
        "AAPL": 342.37, "SPY": 100.0,
    }))).execute(targets={"AAPL": 0.2, "CASH": 0.8}, live_portfolio=True,
                 lot_rounding="fractional"))
    nav = 10 * 342.37 + 25_000.0
    assert res.data["total_value"] == pytest.approx(nav)
    assert res.data["current_weights_pct"]["AAPL"] == pytest.approx(10 * 342.37 / nav * 100)
    assert res.data["current_weights_pct"]["CASH"] == pytest.approx(25_000.0 / nav * 100)
    assert res.data["target_weights_pct"]["CASH"] == pytest.approx(80.0)
    # A CASH target is a weight to keep, not an order.
    assert all(o["symbol"] != "CASH" for o in res.data["orders"])
    aapl = next(o for o in res.data["orders"] if o["symbol"] == "AAPL")
    assert aapl["notional_delta"] == pytest.approx(0.2 * nav - 10 * 342.37)


def test_reba4_warns_when_cash_is_deployed_without_cash_target(monkeypatch):
    _patch_book(monkeypatch, _Book([_Pos("AAPL", 10, 100.0)], cash={"USD": 25_000.0}))
    res = _run(REBAFunction(FunctionDeps(yfinance=_PriceYf({"AAPL": 342.37}))).execute(
        targets={"AAPL": 1.0}, live_portfolio=True,
    ))
    assert any("CASH" in w and "USD cash" in w for w in res.warnings)


def test_reba4_non_usd_cash_is_excluded_and_named(monkeypatch):
    _patch_book(monkeypatch, _Book([_Pos("AAPL", 10, 100.0)], cash={"EUR": 500.0}))
    res = _run(REBAFunction(FunctionDeps(yfinance=_PriceYf({"AAPL": 342.37}))).execute(
        targets={"AAPL": 1.0}, live_portfolio=True,
    ))
    assert res.data["total_value"] == pytest.approx(10 * 342.37)
    assert "CASH" not in res.data["current_weights_pct"]
    assert any("EUR" in w for w in res.warnings)


# ── REBA#5: manifest controls must match the handler ─────────────────────


def test_reba5_min_trade_size_suppresses_small_orders(monkeypatch):
    # AAPL 10 @ 100 = 1,000 NAV. Targets 95/5 mean trades of 50 each.
    _patch_book(monkeypatch, _Book([_Pos("AAPL", 10, 100.0)]))
    prices = {"AAPL": 100.0, "SPY": 100.0}
    # Fractional lots so the 50-notional trades reach the min-trade check.
    res = _run(REBAFunction(FunctionDeps(yfinance=_PriceYf(prices))).execute(
        targets={"AAPL": 0.95, "SPY": 0.05}, live_portfolio=True, min_trade_size=100,
        lot_rounding="fractional",
    ))
    assert res.data["orders"] == []
    reasons = {s["symbol"]: s["reason"] for s in res.data["suppressed"]}
    assert reasons == {"AAPL": "below_min", "SPY": "below_min"}

    res2 = _run(REBAFunction(FunctionDeps(yfinance=_PriceYf(prices))).execute(
        targets={"AAPL": 0.95, "SPY": 0.05}, live_portfolio=True, min_trade_size=10,
        lot_rounding="fractional",
    ))
    assert {o["symbol"] for o in res2.data["orders"]} == {"AAPL", "SPY"}


def test_reba5_whole_lot_rounding_floors_equity_quantity(monkeypatch):
    # 1,000 of SPY at 300 = 3.33 shares -> 3 whole shares, notional 900.
    _patch_book(monkeypatch, _Book([], cash={"USD": 1_000.0}))
    res = _run(REBAFunction(FunctionDeps(yfinance=_PriceYf({"SPY": 300.0}))).execute(
        targets={"SPY": 1.0}, live_portfolio=True, lot_rounding="whole",
    ))
    order = res.data["orders"][0]
    assert order["quantity"] == pytest.approx(3.0)
    assert order["notional_delta"] == pytest.approx(900.0)


def test_reba5_fractional_lot_rounding_keeps_fraction(monkeypatch):
    _patch_book(monkeypatch, _Book([], cash={"USD": 1_000.0}))
    res = _run(REBAFunction(FunctionDeps(yfinance=_PriceYf({"SPY": 300.0}))).execute(
        targets={"SPY": 1.0}, live_portfolio=True, lot_rounding="fractional",
    ))
    assert res.data["orders"][0]["quantity"] == pytest.approx(1_000.0 / 300.0)


def test_reba5_whole_rounding_to_zero_is_suppressed(monkeypatch):
    # 100 of SPY at 300 is 0.33 shares: whole rounding gives 0, so no order.
    _patch_book(monkeypatch, _Book([], cash={"USD": 100.0}))
    res = _run(REBAFunction(FunctionDeps(yfinance=_PriceYf({"SPY": 300.0}))).execute(
        targets={"SPY": 1.0}, live_portfolio=True, min_trade_size=0,
    ))
    assert res.data["orders"] == []
    assert [s["symbol"] for s in res.data["suppressed"]] == ["SPY"]
    assert res.data["suppressed"][0]["reason"] == "below_lot"
    # Reports the intended notional that could not be executed in whole shares.
    assert res.data["suppressed"][0]["notional_delta"] == pytest.approx(100.0)


def test_reba5_crypto_stays_fractional_under_whole_rounding(monkeypatch):
    _patch_book(monkeypatch, _Book([], cash={"USD": 1_000.0}))
    res = _run(REBAFunction(FunctionDeps(yfinance=_PriceYf({"BTCUSDT": 65_000.0}))).execute(
        targets={"BTCUSDT": 1.0}, live_portfolio=True, lot_rounding="whole",
    ))
    assert res.data["orders"][0]["quantity"] == pytest.approx(1_000.0 / 65_000.0)
    assert any("BTCUSDT" in w and "fractional" in w for w in res.warnings)


def test_reba5_unsupported_contract_rounding_is_named(monkeypatch):
    _patch_book(monkeypatch, _Book([], cash={"USD": 1_000.0}))
    res = _run(REBAFunction(FunctionDeps(yfinance=_PriceYf({"SPY": 300.0}))).execute(
        targets={"SPY": 1.0}, live_portfolio=True, lot_rounding="contract",
    ))
    assert any("contract" in w for w in res.warnings)
    assert res.data["orders"][0]["quantity"] == pytest.approx(3.0)


def test_reba5_paper_mode_false_and_credential_are_not_silent(monkeypatch):
    _patch_book(monkeypatch, _Book([], cash={"USD": 1_000.0}))
    res = _run(REBAFunction(FunctionDeps(yfinance=_PriceYf({"SPY": 100.0}))).execute(
        targets={"SPY": 1.0}, live_portfolio=True, paper_mode=False,
        credential_id="cred-123",
    ))
    assert res.data["execution"] == "preview_only"
    assert any("paper_mode" in w for w in res.warnings)
    assert any("credential_id" in w and "not applied" in w for w in res.warnings)


def test_reba5_manifest_declares_only_honoured_controls():
    from showme.manifest import REGISTRY
    from showme.manifest.seeds import load_seeds

    load_seeds()
    reba = REGISTRY.get("REBA")
    by_name = {i.name: i for i in reba.inputs}
    assert "tax_aware" not in by_name, "no lot-level tax data: control cannot be honoured"
    assert "provider_mode" not in by_name, "live quotes come from yfinance only"
    assert "contract" not in (by_name["lot_rounding"].options or [])
    assert by_name["credential_id"].required is False
    assert reba.defaults["min_trade_size"] == 100
    assert reba.defaults["lot_rounding"] == "whole"
