"""MGN#5: the user can state cash (and the account it belongs to) for a saved-book calculation.

A request cash applies to the named account for that calculation only (in memory, never
written to margin_config.json: MGN#6). With one account the account may be omitted; with
several, cash without an account is not guessed onto one of them.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import showme.engine.portfolio.state as state_mod
import showme.engine.services.margin_engine as me
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.portfolio.mgn import MGNFunction
from showme.engine.portfolio.state import PortfolioPosition
from showme.manifest import REGISTRY, load_seeds


def _run(coro):
    return asyncio.run(coro)


def _patch(monkeypatch, positions, cash, stored=None):
    stored = {} if stored is None else stored
    writes: list = []

    class _State:
        def __init__(self, *a, **k):
            self.positions = positions
            self.cash = dict(cash)

        def import_legacy_crypto(self):
            pass

    def _save(cfg):
        writes.append(cfg)

    monkeypatch.setattr(state_mod, "PortfolioState", _State)
    monkeypatch.setattr(me, "PortfolioState", _State)
    monkeypatch.setattr(me, "_save_config", _save)
    monkeypatch.setattr(me, "_load_config", lambda: {"accounts": dict(stored)})
    return writes


def _line(account="main", qty=10):
    return PortfolioPosition(instrument=Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY),
                             quantity=qty, avg_cost=100, account=account)


class _YF:
    async def fetch(self, request):
        return SimpleNamespace(last=100.0)


def _deps():
    return SimpleNamespace(yfinance=_YF(), symbol_registry=None)


def test_request_cash_sets_single_account_cash_for_this_calculation(monkeypatch):
    _patch(monkeypatch, [_line()], {})
    res = _run(MGNFunction(_deps()).execute(cash=2500))
    account = res.data["accounts"][0]
    assert account["cash"] == 2500.0
    assert account["equity"] == pytest.approx(3500.0)  # 2,500 cash + 10 x 100
    assert res.metadata["cash_sources"] == {"main": "request"}
    assert not any("cash not recorded" in w.lower() for w in res.warnings)


def test_request_cash_overrides_the_recorded_book_cash(monkeypatch):
    _patch(monkeypatch, [_line()], {"USD": 5000.0})
    res = _run(MGNFunction(_deps()).execute(cash=2500))
    assert res.data["accounts"][0]["cash"] == 2500.0
    assert res.metadata["cash_sources"] == {"main": "request"}


def test_request_cash_for_named_account_only_credits_that_account(monkeypatch):
    _patch(monkeypatch, [_line("a"), _line("b")], {})
    res = _run(MGNFunction(_deps()).execute(cash=2500, account="a"))
    by_name = {a["account"]: a for a in res.data["accounts"]}
    assert by_name["a"]["cash"] == 2500.0
    assert by_name["b"]["cash"] == 0
    assert res.metadata["cash_sources"]["a"] == "request"


def test_request_cash_without_account_on_several_accounts_is_not_guessed(monkeypatch):
    _patch(monkeypatch, [_line("a"), _line("b")], {})
    res = _run(MGNFunction(_deps()).execute(cash=2500))
    assert all(a["cash"] == 0 for a in res.data["accounts"])
    assert any("account=" in w for w in res.warnings)


def test_request_cash_for_unknown_account_is_disclosed(monkeypatch):
    _patch(monkeypatch, [_line()], {})
    res = _run(MGNFunction(_deps()).execute(cash=2500, account="nope"))
    assert res.data["accounts"][0]["cash"] == 0
    assert any("nope" in w for w in res.warnings)


def test_request_cash_is_never_written_to_the_account_config(monkeypatch):
    writes = _patch(monkeypatch, [_line()], {})
    _run(MGNFunction(_deps()).execute(cash=2500))
    assert writes == []


def test_mgn_seed_declares_cash_and_account_inputs():
    load_seeds()
    names = {i.name for i in REGISTRY.get("MGN").inputs}
    assert {"cash", "account"} <= names


def test_mgn_methodology_describes_the_real_cash_sources():
    load_seeds()
    text = REGISTRY.get("MGN").methodology
    assert "(0 when none is recorded)" not in text
    assert "book" in text.lower()
