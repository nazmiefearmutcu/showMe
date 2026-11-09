"""STRS#3-RQ: an asset class a scenario has no row for is not a silent 0.0 move."""
from __future__ import annotations

from showme.engine.services import stress_scenarios as ss


def _scenario():
    return next(iter(ss.SCENARIOS.values()))


def test_unmapped_asset_class_is_left_unshocked_and_reported() -> None:
    out = ss.apply_scenario([{"symbol": "ESZ6", "asset_class": "FUTURE", "market_value": 1000.0}], _scenario())
    row = out["positions"][0]
    assert row["shock"] is None
    assert row["shock_source"] == "unavailable"
    assert out["unpriced_positions"] == 1
    assert any("no shock for asset class FUTURE" in w for w in out["warnings"])


def test_cash_is_a_real_zero() -> None:
    out = ss.apply_scenario([{"symbol": "USD", "asset_class": "CASH", "market_value": 500.0}], _scenario())
    row = out["positions"][0]
    assert row["shock"] == 0.0
    assert row["shock_source"] == "cash"
    assert out["unpriced_positions"] == 0
