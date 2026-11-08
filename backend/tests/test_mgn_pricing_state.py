"""MGN#1: the default MGN calc marks to live quotes, and an at-cost book is flagged degraded."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import showme.engine.portfolio.state as state_mod
import showme.engine.services.margin_engine as me
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.portfolio.mgn import MGNFunction
from showme.engine.portfolio.state import PortfolioPosition


def _run(coro):
    return asyncio.run(coro)


def _patch_book(monkeypatch, symbols):
    book = [
        PortfolioPosition(instrument=Instrument(symbol=s, asset_class=AssetClass.EQUITY), quantity=10, avg_cost=100)
        for s in symbols
    ]

    class _State:
        def __init__(self, *a, **k):
            self.positions = book
            self.cash = {}

        def import_legacy_crypto(self):
            pass

    monkeypatch.setattr(state_mod, "PortfolioState", _State)
    monkeypatch.setattr(me, "PortfolioState", _State)
    monkeypatch.setattr(me, "_save_config", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(me, "_load_config", lambda: {})


class _YF:
    def __init__(self, quotes):
        self.quotes = quotes

    async def fetch(self, request):
        last = self.quotes.get(request.instrument.symbol)
        return SimpleNamespace(last=last) if last is not None else None


def test_router_no_longer_forces_margin_at_average_cost():
    from showme.manifest import load_seeds
    from showme.server_routes._agent_runtime import _route_function_params

    load_seeds()
    routed = _route_function_params("MGN", {})
    assert routed.get("refresh_prices", True) is not False


def test_default_calc_marks_quoted_positions_live_and_is_not_degraded(monkeypatch):
    _patch_book(monkeypatch, ["AAPL"])
    res = _run(MGNFunction(SimpleNamespace(yfinance=_YF({"AAPL": 150.0}), symbol_registry=None)).execute())
    assert res.metadata["marked_at_cost"] == []
    assert res.metadata.get("degraded") is False
    assert res.data["accounts"][0]["market_value"] == 1500.0


def test_partially_at_cost_book_is_flagged_degraded_in_metadata(monkeypatch):
    _patch_book(monkeypatch, ["AAPL", "ZZZZ"])
    res = _run(MGNFunction(SimpleNamespace(yfinance=_YF({"AAPL": 150.0}), symbol_registry=None)).execute())
    assert res.metadata["marked_at_cost"] == ["ZZZZ"]
    assert res.metadata["degraded"] is True
    # Partial live is not a model: the pane must not read metadata.live=false here.
    assert res.metadata.get("live") is not False


def test_explicit_refresh_false_marks_everything_at_cost_and_is_degraded(monkeypatch):
    _patch_book(monkeypatch, ["AAPL"])
    res = _run(MGNFunction(SimpleNamespace(yfinance=_YF({"AAPL": 150.0}), symbol_registry=None))
               .execute(refresh_prices=False))
    assert res.metadata["degraded"] is True
    assert any("refresh_prices=false" in w for w in res.warnings)
