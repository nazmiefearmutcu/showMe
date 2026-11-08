"""REBA manifest and output-contract regressions (wb1-g21 follow-up, REBA#5).

* The provider chain must not advertise a cached-snapshot path the handler
  does not implement.
* Manifest ``must_have`` keys, table columns and card slots must name fields
  the handler actually emits, on both the live and model paths.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.core.quote import Quote
from showme.engine.functions.portfolio import reba as reba_mod
from showme.engine.functions.portfolio.reba import REBAFunction
from showme.manifest import REGISTRY
from showme.manifest.enums import DataMode
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


def _reba_entry():
    load_seeds()
    return REGISTRY.get("REBA")


def _live_result(monkeypatch):
    """Live path with one liquidation (AAPL not targeted) and one order (SPY)."""
    book = _Book([_Pos("AAPL", 10, 100.0)], cash={"USD": 1_000.0})
    monkeypatch.setattr(reba_mod, "PortfolioState", lambda: book)
    deps = FunctionDeps(yfinance=_PriceYf({"AAPL": 342.37, "SPY": 100.0}))
    return _run(REBAFunction(deps).execute(
        targets={"SPY": 1.0}, live_portfolio=True, lot_rounding="fractional",
        min_trade_size=0,
    ))


# ── REBA#5: manifest advertises only implemented provider paths ──────────


def test_provider_chain_has_no_cached_snapshot_path():
    entry = _reba_entry()
    assert "cached_snapshot" not in entry.provider_chain.fallbacks
    assert DataMode.CACHED_SNAPSHOT not in entry.provider_chain.acceptable_modes


# ── Output contract names fields the handler emits ───────────────────────


def test_must_have_keys_are_emitted_by_live_and_model_paths(monkeypatch):
    entry = _reba_entry()
    live = _live_result(monkeypatch)
    model = _run(REBAFunction(FunctionDeps()).execute(targets={"SPY": 1.0}, max_notional=1000))
    for key in entry.output_contract.must_have:
        assert key in live.data, f"live output missing must_have key {key}"
        assert key in model.data, f"model output missing must_have key {key}"


def test_table_columns_are_present_on_every_emitted_row(monkeypatch):
    entry = _reba_entry()
    res = _live_result(monkeypatch)
    rows = res.data["rows"]
    assert {r["action"] for r in rows} == {"BUY", "SELL"}
    for col in entry.table_schema.columns:
        for row in rows:
            assert col.key in row, f"table column {col.key} missing from row {row['symbol']}"


def test_card_slots_name_emitted_fields(monkeypatch):
    entry = _reba_entry()
    res = _live_result(monkeypatch)
    summary = res.data["summary"]
    for slot in entry.card_schema.slots:
        assert slot.key in res.data or slot.key in summary, (
            f"card slot {slot.key} is not emitted"
        )
