"""REBA review follow-up (wb1-g21): REBA#4 capital cap and REBA#5 seed contract.

* REBA#4: ``max_notional`` must not shrink the live NAV that the targets are
  applied to. The UI sends a default capital when the field is blank, so a
  cap there would silently size orders against an invented capital. A cap
  that would have bound is named in the warnings instead of applied.
* REBA#5: manifest text and provider fallbacks describe only what the handler
  does (no ccxt path, no within_tolerance reason, min_trade_size is live-only).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.core.quote import Quote
from showme.engine.functions.portfolio import reba as reba_mod
from showme.engine.functions.portfolio.reba import REBAFunction
from showme.manifest import REGISTRY
from showme.manifest.seeds import load_seeds


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
    def __init__(self, prices):
        self.prices = prices

    async def fetch(self, request):
        sym = request.instrument.symbol
        if sym not in self.prices:
            raise RuntimeError(f"no quote for {sym}")
        return Quote(symbol=sym, timestamp=datetime.now(timezone.utc), last=self.prices[sym])


def _patch_book(monkeypatch, book):
    monkeypatch.setattr(reba_mod, "PortfolioState", lambda: book)


# ── REBA#4: max_notional does not cap the live NAV ───────────────────────


def _nav_book(monkeypatch):
    # 300 AAPL at 342.37 = 102,711.00 invested, plus 25,000 USD cash: NAV 127,711.00.
    _patch_book(monkeypatch, _Book([_Pos("AAPL", 300, 100.0)], cash={"USD": 25_000.0}))
    return FunctionDeps(yfinance=_PriceYf({"AAPL": 342.37}))


def test_reba4_ui_default_capital_does_not_cap_live_nav(monkeypatch):
    deps = _nav_book(monkeypatch)
    # The shipped UI sends max_notional=100000 when the capital field is blank.
    res = _run(REBAFunction(deps).execute(
        targets={"AAPL": 0.5, "CASH": 0.5}, live_portfolio=True,
        lot_rounding="fractional", max_notional=100_000,
    ))
    nav = 300 * 342.37 + 25_000.0
    assert res.data["total_value"] == pytest.approx(nav)
    assert res.data["cash_usd"] == pytest.approx(25_000.0)
    assert res.data["current_weights_pct"]["AAPL"] == pytest.approx(300 * 342.37 / nav * 100)
    assert res.data["current_weights_pct"]["CASH"] == pytest.approx(25_000.0 / nav * 100)
    total_weight = sum(res.data["current_weights_pct"].values())
    assert total_weight == pytest.approx(100.0)
    # The cap would have bound, so the user is told it was not applied.
    assert any("max_notional" in w and "not applied" in w for w in res.warnings)


def test_reba4_live_result_is_independent_of_max_notional(monkeypatch):
    deps = _nav_book(monkeypatch)
    with_cap = _run(REBAFunction(deps).execute(
        targets={"AAPL": 0.5, "CASH": 0.5}, live_portfolio=True,
        lot_rounding="fractional", max_notional=100_000,
    ))
    without_cap = _run(REBAFunction(deps).execute(
        targets={"AAPL": 0.5, "CASH": 0.5}, live_portfolio=True,
        lot_rounding="fractional",
    ))
    assert with_cap.data["total_value"] == pytest.approx(without_cap.data["total_value"])
    assert with_cap.data["orders"] == without_cap.data["orders"]
    assert not any("max_notional" in w for w in without_cap.warnings)


def test_reba4_cap_above_nav_is_silent(monkeypatch):
    deps = _nav_book(monkeypatch)
    res = _run(REBAFunction(deps).execute(
        targets={"AAPL": 0.5, "CASH": 0.5}, live_portfolio=True,
        lot_rounding="fractional", max_notional=1_000_000,
    ))
    assert res.data["total_value"] == pytest.approx(300 * 342.37 + 25_000.0)
    assert not any("max_notional" in w for w in res.warnings)


def test_reba4_invalid_cap_is_ignored_without_error(monkeypatch):
    deps = _nav_book(monkeypatch)
    res = _run(REBAFunction(deps).execute(
        targets={"AAPL": 0.5, "CASH": 0.5}, live_portfolio=True,
        lot_rounding="fractional", max_notional="not-a-number",
    ))
    assert res.data["total_value"] == pytest.approx(300 * 342.37 + 25_000.0)


# ── REBA#5: manifest text and providers match the handler ────────────────


def _reba_entry():
    load_seeds()
    return REGISTRY.get("REBA")


def test_reba5_provider_fallbacks_exclude_unimplemented_ccxt_path():
    entry = _reba_entry()
    assert "ccxt_broker" not in entry.provider_chain.fallbacks
    reba_source = Path(reba_mod.__file__).read_text(encoding="utf-8")
    assert "ccxt" not in reba_source.lower()


def test_reba5_min_trade_size_describes_live_only():
    entry = _reba_entry()
    spec = next(i for i in entry.inputs if i.name == "min_trade_size")
    text = (spec.description or "").lower()
    assert "live preview" in text
    assert "live and model" not in text
    assert "model previews" not in text


def test_reba5_methodology_names_only_emitted_reasons():
    entry = _reba_entry()
    assert "within_tolerance" not in entry.methodology
    assert "below_min" in entry.methodology
    assert "below_lot" in entry.methodology


def test_reba5_handler_emits_only_documented_suppression_reasons(monkeypatch):
    _patch_book(monkeypatch, _Book([], cash={"USD": 1_000.0}))
    res = _run(REBAFunction(FunctionDeps(yfinance=_PriceYf({"SPY": 300.0, "QQQ": 10.0}))).execute(
        targets={"SPY": 0.9, "QQQ": 0.1}, live_portfolio=True, min_trade_size=500,
    ))
    documented = {"below_min", "below_lot"}
    emitted = {s["reason"] for s in res.data["suppressed"]}
    assert emitted <= documented
    assert emitted  # the min-trade filter must actually fire in this fixture
