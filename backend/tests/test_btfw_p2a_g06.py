"""P2A-G06 BTFW#4: the no-backtest placeholder must not ship a drawn equity ramp.

The template curve (30 points of cash * 1.0015^n) is invented. It is flagged
as a placeholder, but the pane charted it. The payload now carries an empty
curve, no final equity, and a next action that asks for live=true.
"""
from __future__ import annotations

import asyncio

from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.portfolio.btfw import BTFWFunction


def _placeholder():
    inst = Instrument(symbol="TEST", asset_class=AssetClass.EQUITY)
    return asyncio.run(BTFWFunction().execute(instrument=inst, live=False, strategy="sma_crossover"))


def test_btfw3_placeholder_ships_no_invented_equity_curve() -> None:
    """Was: equity_curve and oos_equity_curve held a 30-point invented ramp."""
    d = _placeholder().data
    assert d["is_placeholder"] is True
    assert d["equity_curve"] == []
    assert d["oos_equity_curve"] == []


def test_btfw3_placeholder_has_no_invented_final_equity() -> None:
    """Was: final_equity was the last point of the invented ramp."""
    d = _placeholder().data
    assert d["final_equity"] is None


def test_btfw3_placeholder_asks_for_live_run() -> None:
    d = _placeholder().data
    assert d["status"] == "placeholder"
    assert any("live=true" in a for a in d.get("next_actions", []))
