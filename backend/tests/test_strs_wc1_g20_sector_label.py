"""STRS#2 — the provider's sector label is kept beside the scenario-taxonomy key.

Yahoo reports "Technology"; the scenario taxonomy is GICS-style "Information Technology".
The normalized name is what the shock lookup matches on, but the row must still carry the
label the provider actually returned, so the displayed label is never mistaken for the
provider's own.

No network: PortfolioState and the yfinance adapter are in-memory fakes.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from showme.engine.core.base_data_source import DataKind
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.portfolio import strs as strs_mod
from showme.engine.services import stress_scenarios as stress


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


class _FakeRefdata:
    def __init__(self, sectors: dict[str, str]):
        self.sectors = sectors

    async def fetch(self, request):
        if request.kind == DataKind.REFDATA and request.instrument.symbol in self.sectors:
            return SimpleNamespace(sector=self.sectors[request.instrument.symbol])
        raise RuntimeError("no refdata")


def test_yahoo_label_is_kept_beside_the_normalized_scenario_key():
    positions = [{"symbol": "AAPL", "asset_class": "EQUITY", "market_value": 1000.0,
                  "sector": "Technology"}]
    out = stress.apply_scenario(positions, stress.SCENARIOS["GFC_2008"])
    row = out["positions"][0]
    assert row["sector"] == "Information Technology"
    assert row["sector_provider_label"] == "Technology"
    assert row["shock_source"] == "hand_set"
    assert row["shock"] == -0.40  # the Information Technology GFC shock, matched on the key


def test_unmapped_label_is_its_own_provider_label():
    positions = [{"symbol": "NEE", "asset_class": "EQUITY", "market_value": 1000.0,
                  "sector": "Utilities"}]
    row = stress.apply_scenario(positions, stress.SCENARIOS["GFC_2008"])["positions"][0]
    assert row["sector"] == "Utilities"
    assert row["sector_provider_label"] == "Utilities"


def test_missing_sector_has_no_provider_label():
    positions = [{"symbol": "XYZ", "asset_class": "EQUITY", "market_value": 1000.0}]
    row = stress.apply_scenario(positions, stress.SCENARIOS["GFC_2008"])["positions"][0]
    assert row["sector"] is None
    assert row["sector_provider_label"] is None


def test_handler_carries_the_provider_label_from_the_refdata_lookup(monkeypatch):
    _use_positions(monkeypatch, [_Position("AAPL", AssetClass.EQUITY, 10.0, 100.0)])
    deps = SimpleNamespace(yfinance=_FakeRefdata({"AAPL": "Technology"}))
    res = asyncio.run(strs_mod.STRSFunction(deps).execute(action="scenario", scenario="GFC_2008"))
    row = next(r for r in res.data["positions"] if r["symbol"] == "AAPL")
    assert row["sector"] == "Information Technology"
    assert row["sector_provider_label"] == "Technology"
