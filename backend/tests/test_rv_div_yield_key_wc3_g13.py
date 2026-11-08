"""UI-6-RQ: the RV seed's ratio-unit dividend column must be the key RV actually emits.

RV emits the dividend yield as ``div_yield`` (a decimal fraction). The seed's
table column was declared as ``dividend_yield``, so its ``unit="ratio"`` never
received a value and was inert. The declared column must name the emitted field.
The network is replaced by an in-memory yfinance fake.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity.rv import RVFunction
from showme.manifest import REGISTRY, load_seeds


class _FakeYF:
    def __init__(self, raw_by_symbol):
        self._raw = raw_by_symbol

    async def fetch(self, request):
        return SimpleNamespace(market_cap=None, extras={"raw": self._raw[request.instrument.symbol]})


class _Deps:
    finnhub = None

    def __init__(self, raw_by_symbol):
        self.yfinance = _FakeYF(raw_by_symbol)


def _ratio_columns():
    load_seeds()
    return [c for c in REGISTRY.get("RV").table_schema.columns if c.unit == "ratio"]


def test_rv_ratio_unit_column_is_the_emitted_dividend_field() -> None:
    # Red before the fix: the only ratio column was keyed "dividend_yield", which RV never emits.
    keys = [c.key for c in _ratio_columns()]
    # fcf_yield is also emitted as a decimal fraction, so it carries the ratio unit too.
    assert keys == ["div_yield", "fcf_yield"]


def test_rv_declared_ratio_column_receives_a_value() -> None:
    raw = {
        "AAPL": {"dividendYield": 0.32, "dividendRate": 1.08, "currentPrice": 342.37, "trailingPE": 30.0},
        "MSFT": {"dividendYield": 0.74, "dividendRate": 3.00, "currentPrice": 405.0, "trailingPE": 25.0},
    }
    fn = RVFunction(_Deps(raw))
    inst = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
    res = asyncio.run(fn.execute(instrument=inst, peers=["MSFT"]))
    row = next(r for r in res.data["rows"] if r["symbol"] == "AAPL")
    column = next(c for c in _ratio_columns() if c.key == "div_yield")
    assert column.key in row
    assert row[column.key] == pytest.approx(0.0032)
