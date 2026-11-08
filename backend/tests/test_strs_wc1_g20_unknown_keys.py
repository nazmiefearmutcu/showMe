"""STRS#5 — a requested scenario key the engine does not run is reported, never dropped.

No network: PortfolioState is replaced by an in-memory fake and no yfinance adapter is set.
"""

from __future__ import annotations

import asyncio

from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.portfolio import strs as strs_mod


class _Position:
    def __init__(self, symbol: str, asset_class: AssetClass, quantity: float, avg_cost: float):
        self.instrument = Instrument(symbol=symbol, asset_class=asset_class)
        self.quantity = quantity
        self.avg_cost = avg_cost


def _use_positions(monkeypatch, positions):
    class _Portfolio:
        def __init__(self):
            self.positions = positions

        def import_legacy_crypto(self):
            return None

    monkeypatch.setattr(strs_mod, "PortfolioState", _Portfolio)


def test_compare_unknown_keys_are_warned_and_known_key_still_runs(monkeypatch):
    _use_positions(monkeypatch, [_Position("AAPL", AssetClass.EQUITY, 10.0, 100.0)])
    res = asyncio.run(strs_mod.STRSFunction().execute(
        action="compare", scenarios="GFC_2008,lehman_2008,black_monday_1987",
    ))
    keys = [row["key"] for row in res.data["comparisons"]]
    assert keys == ["GFC_2008"], keys
    assert res.data["summary"]["scenarios"] == 1
    assert "unknown scenario lehman_2008: not run" in res.warnings, res.warnings
    assert "unknown scenario black_monday_1987: not run" in res.warnings, res.warnings


def test_compare_list_form_unknown_key_is_warned(monkeypatch):
    _use_positions(monkeypatch, [_Position("AAPL", AssetClass.EQUITY, 10.0, 100.0)])
    res = asyncio.run(strs_mod.STRSFunction().execute(
        action="compare", scenarios=["COVID_2020", "asia_1997"],
    ))
    assert [row["key"] for row in res.data["comparisons"]] == ["COVID_2020"]
    assert "unknown scenario asia_1997: not run" in res.warnings, res.warnings


def test_named_unknown_key_is_an_input_error_not_an_empty_success(monkeypatch):
    _use_positions(monkeypatch, [_Position("AAPL", AssetClass.EQUITY, 10.0, 100.0)])
    res = asyncio.run(strs_mod.STRSFunction().execute(action="scenario", scenario="lehman_2008"))
    assert res.data["status"] == "input_error", res.data
    assert res.data["rows"] == []
    assert "unknown scenario LEHMAN_2008" in res.warnings, res.warnings
