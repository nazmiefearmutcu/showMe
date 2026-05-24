"""Q4 audit H12: lot/tick precision rounding via ccxt.

Live runner submits qty/price via ``ccxt.amount_to_precision`` /
``ccxt.price_to_precision``. For non-ccxt brokers or unknown symbols
(no `_ex` attribute), fall back to 8-decimal round.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from showme.bots.runner import _round_price_to_precision, _round_qty_to_precision


@pytest.mark.asyncio
async def test_qty_routed_through_ccxt_amount_to_precision():
    broker = MagicMock()
    broker._ex = MagicMock()
    # Mock returns a string like ccxt would; the wrapper casts to float.
    broker._ex.amount_to_precision = MagicMock(return_value="0.001")
    result = await _round_qty_to_precision(broker, "BTC/USDT", 0.00123456)
    assert result == pytest.approx(0.001)
    broker._ex.amount_to_precision.assert_called_once_with("BTC/USDT", 0.00123456)


@pytest.mark.asyncio
async def test_price_routed_through_ccxt_price_to_precision():
    broker = MagicMock()
    broker._ex = MagicMock()
    broker._ex.price_to_precision = MagicMock(return_value="50000.5")
    result = await _round_price_to_precision(broker, "BTC/USDT", 50000.51234)
    assert result == pytest.approx(50000.5)


@pytest.mark.asyncio
async def test_qty_falls_back_to_8dp_when_no_ex_attr():
    broker = MagicMock(spec=[])  # no _ex
    result = await _round_qty_to_precision(broker, "BTC/USDT", 0.123456789)
    assert result == pytest.approx(round(0.123456789, 8))


@pytest.mark.asyncio
async def test_qty_falls_back_when_ccxt_amount_to_precision_raises():
    broker = MagicMock()
    broker._ex = MagicMock()
    broker._ex.amount_to_precision = MagicMock(side_effect=RuntimeError("boom"))
    result = await _round_qty_to_precision(broker, "BTC/USDT", 0.123456789)
    # Falls back to round(8).
    assert result == pytest.approx(round(0.123456789, 8))


@pytest.mark.asyncio
async def test_price_falls_back_when_no_price_to_precision_fn():
    broker = MagicMock()
    broker._ex = MagicMock(spec=[])  # has _ex but no price_to_precision
    result = await _round_price_to_precision(broker, "BTC/USDT", 50000.123)
    assert result == pytest.approx(round(50000.123, 8))
