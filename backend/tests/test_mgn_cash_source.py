"""MGN#5: the saved-portfolio margin uses the book's recorded USD cash, and says so.

The saved book keeps its recorded cash (PortfolioState.cash, shown by PORT), but MGN
priced every auto-created account at cash 0, so equity and buying power ignored it. The
book's USD cash now becomes the cash of a single-account book (disclosed as
portfolio_state); with several accounts it is not guessed onto one of them and is listed
as unallocated. A zero cash that was never recorded is disclosed as a warning.
"""
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


def _patch(monkeypatch, positions, cash):
    class _State:
        def __init__(self, *a, **k):
            self.positions = positions
            self.cash = dict(cash)

        def import_legacy_crypto(self):
            pass

    monkeypatch.setattr(state_mod, "PortfolioState", _State)
    monkeypatch.setattr(me, "PortfolioState", _State)
    monkeypatch.setattr(me, "_save_config", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(me, "_load_config", lambda: {})


def _aapl(account="main"):
    return PortfolioPosition(instrument=Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY),
                             quantity=10, avg_cost=100, account=account)


class _YF:
    async def fetch(self, request):
        return SimpleNamespace(last=100.0)


def _deps():
    return SimpleNamespace(yfinance=_YF(), symbol_registry=None)


def test_single_account_book_uses_recorded_usd_cash(monkeypatch):
    _patch(monkeypatch, [_aapl()], {"USD": 5000.0})
    res = _run(MGNFunction(_deps()).execute())
    account = res.data["accounts"][0]
    assert account["cash"] == 5000.0
    assert account["equity"] == 6000.0  # cash + 10 x 100
    assert res.metadata["cash_sources"] == {"main": "portfolio_state"}


def test_multi_account_book_does_not_guess_cash_onto_one_account(monkeypatch):
    _patch(monkeypatch, [_aapl("a"), _aapl("b")], {"USD": 5000.0})
    res = _run(MGNFunction(_deps()).execute())
    assert all(a["cash"] == 0 for a in res.data["accounts"])
    assert res.data["unallocated_cash_usd"] == 5000.0
    assert any("unallocated" in w.lower() for w in res.warnings)


def test_unrecorded_cash_is_disclosed_as_a_warning(monkeypatch):
    _patch(monkeypatch, [_aapl()], {})
    res = _run(MGNFunction(_deps()).execute())
    assert res.data["accounts"][0]["cash"] == 0
    assert any("cash not recorded" in w.lower() for w in res.warnings)


def test_supplied_positions_without_cash_are_disclosed(monkeypatch):
    res = _run(MGNFunction(_deps()).execute(positions=[
        {"symbol": "AAPL", "asset_class": "EQUITY", "quantity": 10, "avg_cost": 100, "last": 100}]))
    assert any("cash not recorded" in w.lower() for w in res.warnings)
