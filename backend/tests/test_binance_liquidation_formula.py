"""Q4 audit H15: Binance perpetual liquidation formula.

Old (non-standard): long = entry * (1 - 1/lev) / (1 - mm)
New (Binance):       long = entry * (1 - 1/lev + mm)
                     short = entry * (1 + 1/lev - mm)

The new formula gives a slightly more conservative (closer-to-entry) liq
price, matching Binance's published reference for isolated single position
with no cross collateral.
"""
from __future__ import annotations

import pytest

from showme.engine.trading.order_models import PositionSide
from showme.engine.trading.position_manager import PositionManager


def _pm() -> PositionManager:
    return PositionManager({
        "risk": {"stop_loss_pct": 0.025, "take_profit_pct": 0.05,
                 "trailing_stop_pct": 0.02},
        "paper": {"fee_pct": 0.001},
    })


def test_long_liq_uses_standard_formula():
    pm = _pm()
    # entry 100, 10x leverage, maint 0.4%.
    # Expected liq = 100 * (1 - 1/10 + 0.004) = 100 * 0.904 = 90.4
    pos = pm.open_position(
        symbol="BTC/USDT", side=PositionSide.LONG,
        entry_price=100.0, quantity=1.0, leverage=10,
    )
    assert pos.liquidation_price == pytest.approx(90.4, rel=1e-3)


def test_short_liq_uses_standard_formula():
    pm = _pm()
    # short entry 100, 10x leverage, maint 0.4%.
    # Expected liq = 100 * (1 + 1/10 - 0.004) = 100 * 1.096 = 109.6
    pos = pm.open_position(
        symbol="BTC/USDT", side=PositionSide.SHORT,
        entry_price=100.0, quantity=1.0, leverage=10,
    )
    assert pos.liquidation_price == pytest.approx(109.6, rel=1e-3)


def test_long_higher_leverage_brings_liq_closer():
    pm = _pm()
    pos_5x = pm.open_position(
        symbol="A", side=PositionSide.LONG, entry_price=100.0,
        quantity=1.0, leverage=5,
    )
    # Clear positions between calls (PM stores in symbol-keyed dict).
    pm.positions.clear()
    pos_50x = pm.open_position(
        symbol="A", side=PositionSide.LONG, entry_price=100.0,
        quantity=1.0, leverage=50,
    )
    # Higher leverage → liq closer to entry (higher long liq, lower distance).
    assert pos_50x.liquidation_price > pos_5x.liquidation_price


def test_no_leverage_no_liq():
    pm = _pm()
    pos = pm.open_position(
        symbol="X", side=PositionSide.LONG, entry_price=100.0,
        quantity=1.0, leverage=1,
    )
    assert pos.liquidation_price is None
