"""STRS#3-RQ — a Treasury fund with no BOND row in the scenario is never silently 0.0.

Follow-up of STRS#3: TLT/IEF-type ETFs resolve to the BOND bucket. A scenario or
custom shock without a BOND key must not turn that into a silent 0.0 shock (and must
not fall back to the equity-style ETF/FUND shock the bucket exists to avoid). The
position is left unshocked and reported as unavailable, never estimated.

No network: PortfolioState is replaced by an in-memory fake.
"""

from __future__ import annotations

import asyncio

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


def _row(res, symbol):
    return next(r for r in res.data["positions"] if r["symbol"] == symbol)


def test_crypto_winter_treasury_fund_is_unavailable_not_zero(monkeypatch):
    # CRYPTO_WINTER has no BOND row; before the fix IEF silently got shock 0.0.
    _use_positions(monkeypatch, [_Position("IEF", AssetClass.ETF, 100.0, 100.0)])
    res = asyncio.run(strs_mod.STRSFunction().execute(action="scenario", scenario="CRYPTO_WINTER"))
    row = _row(res, "IEF")
    assert row["shock"] is None, row
    assert row["shock_source"] == "unavailable", row
    assert row["market_value_post"] == row["market_value_pre"]
    assert any("IEF" in w and "BOND" in w for w in res.warnings), res.warnings
    assert res.data["unpriced_positions"] == 1


def test_custom_etf_shock_does_not_reach_treasury_fund_silently(monkeypatch):
    # A custom ETF shock must not be applied to TLT (BOND bucket) and must not become 0.0.
    _use_positions(monkeypatch, [_Position("TLT", AssetClass.ETF, 100.0, 100.0)])
    res = asyncio.run(strs_mod.STRSFunction().execute(
        action="custom", asset_class_shocks={"ETF": -0.2},
    ))
    row = _row(res, "TLT")
    assert row["shock"] is None, row
    assert row["shock_source"] == "unavailable", row
    assert any("TLT" in w for w in res.warnings), res.warnings


def test_custom_bond_row_still_drives_treasury_fund(monkeypatch):
    # An explicit BOND row in a custom shock is a hand-set shock, not unavailable.
    _use_positions(monkeypatch, [_Position("TLT", AssetClass.ETF, 100.0, 100.0)])
    res = asyncio.run(strs_mod.STRSFunction().execute(
        action="custom", asset_class_shocks={"BOND": -0.10},
    ))
    row = _row(res, "TLT")
    assert row["shock"] == -0.10
    assert row["shock_source"] == "hand_set"


def test_apply_scenario_no_bond_row_gives_unavailable_not_zero():
    positions = [{"symbol": "AGG", "asset_class": "FUND", "market_value": 100.0}]
    out = stress.apply_scenario(positions, stress.SCENARIOS["CRYPTO_WINTER"])
    row = out["positions"][0]
    assert row["shock_source"] == "unavailable"
    assert row["shock"] is None
    assert out["total_pnl"] == 0.0
    assert out["unpriced_positions"] == 1
    assert out["warnings"]
