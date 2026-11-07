"""MGN computes margin for real positions only (strict truth audit 2026-11-07)."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import showme.engine.portfolio.state as state_mod
from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.portfolio.mgn import MGNFunction
from showme.engine.portfolio.state import PortfolioPosition


def _run(coro):
    return asyncio.run(coro)


def test_supplied_positions_default_to_zero_cash_not_10000():
    positions = [{"symbol": "AAPL", "asset_class": "EQUITY", "quantity": 10, "avg_cost": 100,
                  "last": 110, "currency": "USD"}]
    res = _run(MGNFunction(FunctionDeps()).execute(positions=positions))
    account = res.data["accounts"][0]
    assert account["cash"] == 0
    assert account["market_value"] == pytest.approx(1100)
    assert res.sources == ["margin_engine"]


def test_saved_portfolio_is_marked_live_and_unquoted_symbols_are_disclosed(monkeypatch, tmp_path):
    book = [
        PortfolioPosition(instrument=Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY), quantity=10, avg_cost=100),
        PortfolioPosition(instrument=Instrument(symbol="ZZZZ", asset_class=AssetClass.EQUITY), quantity=5, avg_cost=20),
    ]

    class _State:
        def __init__(self, *a, **k):
            self.positions = book
            self.cash = {}

        def import_legacy_crypto(self):
            pass

    monkeypatch.setattr(state_mod, "PortfolioState", _State)
    # margin_engine binds its own PortfolioState at import: patch it too so
    # the valuation really runs on this book (review 2026-11-08).
    import showme.engine.services.margin_engine as me
    monkeypatch.setattr(me, "PortfolioState", _State)
    monkeypatch.setattr(me, "_save_config", lambda *a, **k: None, raising=False)

    class _YF:
        async def fetch(self, request):
            return SimpleNamespace(last=150.0) if request.instrument.symbol == "AAPL" else None

    deps = SimpleNamespace(yfinance=_YF(), symbol_registry=None)
    res = _run(MGNFunction(deps).execute())
    assert res.data["marked_at_cost"] == ["ZZZZ"]
    assert any("ZZZZ" in w and "average cost" in w for w in res.warnings)
    assert res.sources == ["portfolio_state", "margin_engine", "yfinance"]
    marks = {p["symbol"]: p["last"] for a in res.data["accounts"] for p in a.get("positions", [])}
    assert marks["AAPL"] == pytest.approx(150.0)   # live quote, not the 100 cost
    assert marks["ZZZZ"] == pytest.approx(20.0)    # disclosed cost mark


def test_supplied_positions_without_a_price_are_disclosed():
    positions = [{"symbol": "AAPL", "asset_class": "EQUITY", "quantity": 10, "avg_cost": 100, "last": 110},
                 {"symbol": "MSFT", "asset_class": "EQUITY", "quantity": 5, "avg_cost": 300}]
    res = _run(MGNFunction(FunctionDeps()).execute(positions=positions))
    assert res.metadata["marked_at_cost"] == ["MSFT"]
    assert any("MSFT" in w for w in res.warnings)
