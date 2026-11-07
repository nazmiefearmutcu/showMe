"""TLH works on the real local portfolio only (strict truth audit 2026-11-07).

The former non-live path invented a candidate (cost 100, price 92, qty 1)
and an empty portfolio came back ``ok`` with a LIVE pill.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from showme.engine.core.base_data_source import DataKind
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.portfolio import tlh
from showme.engine.portfolio.state import PortfolioPosition


class _YF:
    def __init__(self, prices, sectors=None):
        self.prices, self.sectors = prices, sectors or {}

    async def fetch(self, request):
        sym = request.instrument.symbol
        if request.kind == DataKind.QUOTE:
            return SimpleNamespace(last=self.prices[sym]) if sym in self.prices else None
        return SimpleNamespace(sector=self.sectors.get(sym))


def _deps(prices, sectors=None):
    return SimpleNamespace(yfinance=_YF(prices, sectors), symbol_registry=None)


def _book(monkeypatch, positions):
    class _State:
        def __init__(self):
            self.positions = positions

        def import_legacy_crypto(self):
            pass

    monkeypatch.setattr(tlh, "PortfolioState", _State)


def _pos(sym, qty, cost, days_held):
    return PortfolioPosition(instrument=Instrument(symbol=sym, asset_class=AssetClass.EQUITY),
                             quantity=qty, avg_cost=cost,
                             opened_at=datetime.now(timezone.utc) - timedelta(days=days_held))


def _run(fn, **params):
    return asyncio.run(fn.execute(**params))


def test_empty_portfolio_is_an_honest_empty_state(monkeypatch):
    _book(monkeypatch, [])
    res = _run(tlh.TLHFunction(_deps({})), live_tax=False)
    assert res.data["status"] == "empty"
    assert res.data["candidates"] == []
    assert res.data["next_actions"]
    assert res.sources == ["portfolio_state"]


def test_real_losses_without_any_live_flag(monkeypatch):
    """No flag selects an invented row any more: the real loss is evaluated."""
    _book(monkeypatch, [_pos("AAPL", 10, 200.0, 30)])
    res = _run(tlh.TLHFunction(_deps({"AAPL": 180.0})))
    [row] = res.data["candidates"]
    assert row["symbol"] == "AAPL" and row["avg_cost"] == 200.0 and row["current_price"] == 180.0
    assert row["unrealized_pnl"] == pytest.approx(-200.0)
    assert row["sector"] != "model_baseline"


def test_exactly_one_year_is_still_short_term(monkeypatch):
    _book(monkeypatch, [_pos("AAPL", 1, 200.0, 365), _pos("MSFT", 1, 500.0, 366)])
    res = _run(tlh.TLHFunction(_deps({"AAPL": 150.0, "MSFT": 400.0})))
    rows = {c["symbol"]: c for c in res.data["candidates"]}
    assert rows["AAPL"]["long_term"] is False
    assert rows["MSFT"]["long_term"] is True


def test_zero_day_wash_window_is_allowed(monkeypatch):
    _book(monkeypatch, [_pos("AAPL", 1, 200.0, 30)])
    res = _run(tlh.TLHFunction(_deps({"AAPL": 150.0})), wash_sale_window_days=0)
    window = res.data["candidates"][0]["wash_sale_window"]
    assert window[0] == window[1]


def test_losses_are_ranked_with_the_right_tax_rate(monkeypatch):
    _book(monkeypatch, [_pos("AAPL", 10, 200.0, 400), _pos("MSFT", 5, 500.0, 30), _pos("NVDA", 1, 100.0, 30)])
    res = _run(tlh.TLHFunction(_deps({"AAPL": 180.0, "MSFT": 450.0, "NVDA": 120.0},
                                     {"AAPL": "Technology"})),
               tax_bracket=0.32, lt_cap_rate=0.18)
    rows = {c["symbol"]: c for c in res.data["candidates"]}
    assert set(rows) == {"AAPL", "MSFT"}
    assert rows["AAPL"]["long_term"] and rows["AAPL"]["tax_rate_applied"] == 0.18
    assert rows["AAPL"]["estimated_tax_savings"] == pytest.approx(200 * 0.18)
    assert rows["MSFT"]["tax_rate_applied"] == 0.32
    assert rows["MSFT"]["estimated_tax_savings"] == pytest.approx(250 * 0.32)
    assert res.data["candidates"][0]["symbol"] == "MSFT"  # larger saving first
    assert rows["AAPL"]["replacement_etf"] == "VGT"
    assert res.sources == ["portfolio_state", "yfinance"]


def test_manifest_inputs_are_read(monkeypatch):
    _book(monkeypatch, [_pos("AAPL", 10, 200.0, 30), _pos("MSFT", 1, 500.0, 30)])
    res = _run(tlh.TLHFunction(_deps({"AAPL": 180.0, "MSFT": 490.0})),
               min_loss_threshold=50, wash_sale_window_days=31, suggest_replacement=False)
    assert [c["symbol"] for c in res.data["candidates"]] == ["AAPL"]  # MSFT loss 10 < 50
    window = res.data["candidates"][0]["wash_sale_window"]
    span = datetime.fromisoformat(window[1]) - datetime.fromisoformat(window[0])
    assert span.days == 62
    assert res.data["candidates"][0]["replacement_etf"] is None


def test_unpriced_positions_are_reported(monkeypatch):
    _book(monkeypatch, [_pos("AAPL", 10, 200.0, 30), _pos("XYZ", 1, 50.0, 30)])
    res = _run(tlh.TLHFunction(_deps({"AAPL": 190.0})))
    assert any("XYZ" in w for w in res.warnings)


def test_no_quotes_at_all_is_provider_unavailable(monkeypatch):
    _book(monkeypatch, [_pos("AAPL", 10, 200.0, 30)])
    res = _run(tlh.TLHFunction(_deps({})))
    assert res.data["status"] == "provider_unavailable"
