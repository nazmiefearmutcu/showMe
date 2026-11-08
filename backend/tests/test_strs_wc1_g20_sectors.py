"""STRS#2 — sector shocks reach positions: one taxonomy, on by default, no silent miss.

yfinance reports Yahoo sector labels (Technology, Financial Services, Consumer
Cyclical, ...) while the scenarios key GICS-style names (Information Technology,
Financials, ...). The sector branch must map them, sector lookup must run by default,
and a known sector that matches no scenario key must be reported, not silently
replaced by the asset-class shock.

No network: PortfolioState and the yfinance adapter are in-memory fakes.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

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
    """yfinance fake answering only REFDATA requests with a sector label."""

    def __init__(self, sectors: dict[str, str]):
        self.sectors = sectors
        self.requests: list = []

    async def fetch(self, request):
        self.requests.append(request)
        sym = request.instrument.symbol
        if sym not in self.sectors:
            raise RuntimeError(f"no refdata for {sym}")
        return SimpleNamespace(sector=self.sectors[sym])


def _row(res, symbol):
    return next(r for r in res.data["positions"] if r["symbol"] == symbol)


@pytest.mark.parametrize("raw,expected", [
    ("Technology", "Information Technology"),
    ("Financial Services", "Financials"),
    ("Consumer Cyclical", "Consumer Discretionary"),
    ("Consumer Defensive", "Consumer Staples"),
    ("Healthcare", "Health Care"),
    ("Basic Materials", "Materials"),
    ("Energy", "Energy"),
    ("Real Estate", "Real Estate"),
    ("Information Technology", "Information Technology"),
])
def test_normalize_sector_maps_yahoo_labels_to_scenario_keys(raw, expected):
    assert stress.normalize_sector(raw) == expected


def test_normalize_sector_empty_is_none():
    assert stress.normalize_sector(None) is None
    assert stress.normalize_sector("") is None
    assert stress.normalize_sector("   ") is None


def test_every_mapped_sector_is_a_scenario_key_in_some_scenario():
    keys = {k for sc in stress.SCENARIOS.values() for k in sc.sector_shocks}
    for raw in ("Technology", "Financial Services", "Consumer Cyclical",
                "Consumer Defensive", "Healthcare", "Basic Materials"):
        assert stress.normalize_sector(raw) in keys, raw


def test_apply_scenario_maps_yahoo_sector_to_sector_shock():
    positions = [{"symbol": "AAPL", "asset_class": "EQUITY", "market_value": 100.0,
                  "sector": "Technology"}]
    out = stress.apply_scenario(positions, stress.SCENARIOS["GFC_2008"])
    row = out["positions"][0]
    # GFC Information Technology sector shock, not the EQUITY asset-class shock.
    assert row["shock"] == pytest.approx(-0.40)
    assert row["shock_source"] == "hand_set"
    assert row["sector"] == "Information Technology"


def test_default_run_looks_up_sectors_and_applies_them(monkeypatch):
    # STRS#2: the pane sends no include_sectors; the default must still reach positions.
    _use_positions(monkeypatch, [_Position("AAPL", AssetClass.EQUITY, 100.0, 100.0)])
    deps = SimpleNamespace(yfinance=_FakeRefdata({"AAPL": "Technology"}))
    res = asyncio.run(strs_mod.STRSFunction(deps).execute(action="scenario", scenario="GFC_2008"))
    row = _row(res, "AAPL")
    assert row["sector"] == "Information Technology", row
    assert row["shock"] == pytest.approx(-0.40), row
    assert "yfinance" in res.sources


def test_explicit_include_sectors_false_skips_the_lookup(monkeypatch):
    _use_positions(monkeypatch, [_Position("AAPL", AssetClass.EQUITY, 100.0, 100.0)])
    fake = _FakeRefdata({"AAPL": "Technology"})
    res = asyncio.run(strs_mod.STRSFunction(SimpleNamespace(yfinance=fake)).execute(
        action="scenario", scenario="GFC_2008", include_sectors=False,
    ))
    assert fake.requests == []
    assert _row(res, "AAPL")["sector"] is None
    assert _row(res, "AAPL")["shock"] == pytest.approx(-0.55)


def test_known_sector_with_no_scenario_key_is_reported(monkeypatch):
    # RATE_SHOCK_300BP has no Communication Services row: the asset-class shock is
    # used, and that must be said, not silent.
    _use_positions(monkeypatch, [_Position("GOOGL", AssetClass.EQUITY, 100.0, 100.0)])
    deps = SimpleNamespace(yfinance=_FakeRefdata({"GOOGL": "Communication Services"}))
    res = asyncio.run(strs_mod.STRSFunction(deps).execute(
        action="scenario", scenario="RATE_SHOCK_300BP",
    ))
    row = _row(res, "GOOGL")
    assert row["shock"] == pytest.approx(-0.18)
    assert any("GOOGL" in w and "Communication Services" in w for w in res.warnings), res.warnings


def test_matched_sector_emits_no_taxonomy_warning(monkeypatch):
    _use_positions(monkeypatch, [_Position("AAPL", AssetClass.EQUITY, 100.0, 100.0)])
    deps = SimpleNamespace(yfinance=_FakeRefdata({"AAPL": "Technology"}))
    res = asyncio.run(strs_mod.STRSFunction(deps).execute(action="scenario", scenario="GFC_2008"))
    assert not [w for w in res.warnings if "sector" in w.lower()], res.warnings
