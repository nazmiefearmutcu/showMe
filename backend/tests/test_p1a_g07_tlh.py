"""Regression tests for TLH#1: an unpriced loss lot must never read as
"nothing to harvest" (status ok, zero candidates).

The local portfolio and the yfinance adapter are patched; no network is used.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from showme.engine.core.base_data_source import DataKind
from showme.engine.functions.portfolio import tlh
from showme.engine.portfolio.state import PortfolioPosition  # noqa: F401 - re-used by _pos
from test_tlh_real_portfolio import _YF, _book, _pos  # noqa: F401 - shared helpers


def _run(fn, **params):
    return asyncio.run(fn.execute(**params))


def _deps(yf):
    return SimpleNamespace(yfinance=yf, symbol_registry=None)


class _Flaky(_YF):
    """First QUOTE request for ``flaky_sym`` times out; later ones succeed."""

    def __init__(self, prices, flaky_sym):
        super().__init__(prices)
        self.flaky_sym = flaky_sym
        self.quote_calls = 0

    async def fetch(self, request):
        if request.kind == DataKind.QUOTE and request.instrument.symbol == self.flaky_sym:
            self.quote_calls += 1
            if self.quote_calls == 1:
                raise asyncio.TimeoutError()
        return await super().fetch(request)


def test_unpriced_loss_lot_is_not_reported_as_ok_nothing_to_harvest(monkeypatch):
    """TLT is a real loss (-1,008) but has no quote. Status must not be 'ok'."""
    _book(monkeypatch, [_pos("AAPL", 10, 150.0, 30), _pos("TLT", 10, 100.0, 30)])
    res = _run(tlh.TLHFunction(_deps(_YF({"AAPL": 190.0}))))
    assert res.data["status"] == "partial"
    assert res.data["unpriced_symbols"] == ["TLT"]
    assert res.data["summary"]["positions_unpriced"] == 1
    assert any("TLT" in w for w in res.warnings)


def test_transient_quote_timeout_is_retried_and_loss_is_found(monkeypatch):
    """A single slow quote must not silently drop a loss lot."""
    _book(monkeypatch, [_pos("XYZ", 10, 100.0, 30)])
    yf = _Flaky({"XYZ": 80.0}, "XYZ")
    res = _run(tlh.TLHFunction(_deps(yf)))
    assert yf.quote_calls >= 2
    [row] = res.data["candidates"]
    assert row["symbol"] == "XYZ"
    assert res.data["status"] == "ok"
    assert res.data["unpriced_symbols"] == []


def test_fully_priced_book_without_losses_stays_ok(monkeypatch):
    _book(monkeypatch, [_pos("AAPL", 10, 150.0, 30)])
    res = _run(tlh.TLHFunction(_deps(_YF({"AAPL": 190.0}))))
    assert res.data["status"] == "ok"
    assert res.data["candidates"] == []
    assert res.data["unpriced_symbols"] == []
