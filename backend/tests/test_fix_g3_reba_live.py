"""G3 fix-lane regressions — REBA live_portfolio honesty (2026-09-11).

The REBA pane now surfaces `live_portfolio` (the backend parameter already
existed but was unreachable from the UI). These tests pin the live-path
honesty fixes shipped with that surfacing:

* an empty (or all-zero) live portfolio returns `ready_no_positions` instead
  of silently computing $1-notional orders (`sum(...) or 1.0`);
* an unavailable quote (0.0) falls back to average cost instead of valuing
  the book at $0;
* the model path (the unchanged default) still works off `max_notional`.
"""

from __future__ import annotations

import asyncio

import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.portfolio import reba as reba_mod
from showme.engine.functions.portfolio.reba import REBAFunction


def _run(coro):
    # Fresh event loop per test — mirrors test_fix_f3_portfolio.py.
    return asyncio.run(coro)


class _Position:
    def __init__(
        self,
        symbol: str,
        quantity: float,
        avg_cost: float,
        asset_class: AssetClass = AssetClass.EQUITY,
    ):
        self.instrument = Instrument(symbol=symbol, asset_class=asset_class)
        self.quantity = quantity
        self.avg_cost = avg_cost


class _FakePortfolio:
    def __init__(self, positions):
        self.positions = positions

    def import_legacy_crypto(self):  # pragma: no cover - not exercised here
        return 0


@pytest.fixture
def deps() -> FunctionDeps:
    return FunctionDeps()


def _patch_portfolio(monkeypatch, positions):
    monkeypatch.setattr(reba_mod, "PortfolioState", lambda: _FakePortfolio(positions))


def test_reba_live_empty_portfolio_is_honest(deps, monkeypatch):
    _patch_portfolio(monkeypatch, [])
    res = _run(REBAFunction(deps).execute(targets={"SPY": 1.0}, live_portfolio=True))
    assert res.data["status"] == "ready_no_positions"
    # The old `or 1.0` produced $1-book orders — no order may exist now.
    assert res.data["orders"] == []
    assert res.data["rows"] == []
    assert res.data["next_actions"]
    assert res.metadata.get("empty") is True
    assert res.warnings


def test_reba_live_zero_value_positions_are_honest(deps, monkeypatch):
    _patch_portfolio(monkeypatch, [_Position("AAPL", 0.0, 0.0)])
    res = _run(REBAFunction(deps).execute(targets={"SPY": 1.0}, live_portfolio=True))
    assert res.data["status"] == "ready_no_positions"
    assert res.data["orders"] == []


def test_reba_live_falls_back_to_avg_cost_when_quotes_unavailable(deps, monkeypatch):
    # `FunctionDeps()` has no yfinance provider, so `_px` returns 0.0 for the
    # symbol; the book must be valued at average cost, not $0.
    _patch_portfolio(monkeypatch, [_Position("AAPL", 10.0, 100.0)])
    res = _run(REBAFunction(deps).execute(targets={"AAPL": 1.0}, live_portfolio=True))
    assert res.data["total_value"] == pytest.approx(1000.0)
    assert res.data["current_weights_pct"]["AAPL"] == pytest.approx(100.0)


def test_reba_model_path_unchanged(deps):
    res = _run(
        REBAFunction(deps).execute(targets={"SPY": 0.6, "QQQ": 0.4}, max_notional=250_000)
    )
    assert res.data["total_value"] == pytest.approx(250_000.0)
    assert res.sources == ["rebalance_model"]
    assert res.metadata.get("live") is False
