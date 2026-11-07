"""PSC never sizes a made-up trade (strict truth audit 2026-11-07).

It used to fill every missing input with a demo value (account 10,000,
entry 100, stop 95, target 115, win rate 0.55).
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.portfolio import psc
from showme.manifest.registry import REGISTRY
from showme.manifest.seeds import load_seeds

AAPL = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)


class _YF:
    def __init__(self, last):
        self.last = last

    async def fetch(self, request):
        return SimpleNamespace(last=self.last)


def _fn(last=None):
    return psc.PSCFunction(SimpleNamespace(yfinance=_YF(last) if last else None))


def _run(fn, **params):
    return asyncio.run(fn.execute(**params))


def test_fully_specified_trade(monkeypatch):
    res = _run(_fn(), instrument=AAPL, account=50_000, risk_pct=0.02, entry=200, stop=190,
               target=230, win_rate=0.5)
    d = res.data
    assert d["risk_dollars"] == pytest.approx(1000)
    assert d["shares"] == pytest.approx(100)
    assert d["r_multiple"] == pytest.approx(3.0)
    assert d["kelly_fraction"] == pytest.approx((0.5 * 3 - 0.5) / 3)
    assert d["entry_source"] == "input" and d["account_source"] == "input"
    assert res.sources == ["position_sizing_model"]


def test_stop_is_required():
    res = _run(_fn(), instrument=AAPL, account=50_000, entry=200)
    assert res.data["status"] == "input_error"
    assert "stop" in res.data["reason"]


def test_entry_defaults_to_the_live_price():
    res = _run(_fn(last=271.5), instrument=AAPL, account=50_000, stop=260)
    assert res.data["entry"] == pytest.approx(271.5)
    assert res.data["entry_source"] == "live_quote"
    assert "yfinance" in res.sources


def test_account_defaults_to_the_portfolio_book(monkeypatch):
    monkeypatch.setattr(psc, "_portfolio_book_value", lambda: 25_000.0)
    res = _run(_fn(), instrument=AAPL, entry=200, stop=190)
    assert res.data["account"] == pytest.approx(25_000)
    assert res.data["account_source"] == "portfolio_book_value_at_cost"


def test_empty_portfolio_without_account_is_an_input_error(monkeypatch):
    monkeypatch.setattr(psc, "_portfolio_book_value", lambda: 0.0)
    res = _run(_fn(), instrument=AAPL, entry=200, stop=190)
    assert res.data["status"] == "input_error"
    assert "account" in res.data["reason"]


def test_r_and_kelly_only_with_their_inputs():
    res = _run(_fn(), instrument=AAPL, account=10_000, entry=200, stop=190)
    assert res.data["r_multiple"] is None and res.data["kelly_fraction"] is None
    res = _run(_fn(), instrument=AAPL, account=10_000, entry=200, stop=190, target=220)
    assert res.data["r_multiple"] == pytest.approx(2.0) and res.data["kelly_fraction"] is None


def test_manifest_no_longer_prefills_a_demo_trade():
    load_seeds()
    manifest = REGISTRY.get("PSC")
    for key in ("account", "entry", "stop", "target", "win_rate"):
        assert key not in manifest.defaults
    stop = next(i for i in manifest.inputs if i.name == "stop")
    assert stop.required is True
