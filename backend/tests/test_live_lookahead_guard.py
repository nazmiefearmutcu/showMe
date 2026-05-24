"""Q4 audit C1: live-mode lookahead/repaint guard on ``fetch_ohlcv``.

The OHLCV endpoint on every ccxt exchange returns the CURRENT OPEN bar
as the last row. Indicators (RSI/MACD/EMA) computed against that bar
repaint on every tick because the bar's close moves with every print.
``fetch_ohlcv(..., drop_incomplete_last_bar=True)`` must drop the last
row when ``now < bar_open + bar_length``.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from showme.bots.ohlcv import bar_close_time, fetch_ohlcv


def _broker_with_bars(rows: list[list[float]]):
    broker = MagicMock()
    broker.name = "ccxt:fake"
    broker._ex = MagicMock()
    broker._ex.fetch_ohlcv = AsyncMock(return_value=rows)
    return broker


@pytest.mark.asyncio
async def test_drops_incomplete_last_bar_when_now_before_close():
    # 1h bars; last open at 09:00 UTC; close is 10:00 UTC.
    # If now=09:30, the bar is still open → drop.
    rows = [
        [1_748_000_000_000, 100.0, 101.0, 99.0, 100.5, 1000.0],  # 08:00 UTC closed
        [1_748_003_600_000, 100.5, 102.0, 99.5, 101.0, 1100.0],  # 09:00 UTC OPEN
    ]
    broker = _broker_with_bars(rows)
    # now = 09:30 UTC → bar open at 09:00 closes at 10:00; not yet closed.
    now_ms = 1_748_003_600_000 + 30 * 60_000
    df = await fetch_ohlcv(broker, "BTC/USDT", "1h", limit=200, now_ms=now_ms)
    assert len(df) == 1  # last bar dropped
    # First-bar OHLC should match (open=100.0, close=100.5)
    assert df["close"].iloc[0] == pytest.approx(100.5)


@pytest.mark.asyncio
async def test_keeps_last_bar_when_now_after_close():
    rows = [
        [1_748_000_000_000, 100.0, 101.0, 99.0, 100.5, 1000.0],
        [1_748_003_600_000, 100.5, 102.0, 99.5, 101.0, 1100.0],
    ]
    broker = _broker_with_bars(rows)
    # now = 10:01 → 09:00 bar has closed.
    now_ms = 1_748_003_600_000 + 60 * 60_000 + 60_000
    df = await fetch_ohlcv(broker, "BTC/USDT", "1h", limit=200, now_ms=now_ms)
    assert len(df) == 2
    assert df["close"].iloc[-1] == pytest.approx(101.0)


@pytest.mark.asyncio
async def test_opt_out_via_drop_incomplete_last_bar_false():
    rows = [
        [1_748_000_000_000, 100.0, 101.0, 99.0, 100.5, 1000.0],
        [1_748_003_600_000, 100.5, 102.0, 99.5, 101.0, 1100.0],
    ]
    broker = _broker_with_bars(rows)
    # Even when now is during the bar, opt-out keeps it (backtest harness use).
    df = await fetch_ohlcv(
        broker, "BTC/USDT", "1h", limit=200,
        now_ms=1_748_003_600_000 + 30 * 60_000,
        drop_incomplete_last_bar=False,
    )
    assert len(df) == 2


@pytest.mark.asyncio
async def test_unknown_timeframe_does_not_drop():
    rows = [
        [1_748_000_000_000, 100.0, 101.0, 99.0, 100.5, 1000.0],
        [1_748_003_600_000, 100.5, 102.0, 99.5, 101.0, 1100.0],
    ]
    broker = _broker_with_bars(rows)
    # Made-up TF — no entry in _TF_MS → no drop (safe default).
    df = await fetch_ohlcv(broker, "BTC/USDT", "7h", limit=200, now_ms=0)
    assert len(df) == 2


def test_bar_close_time_for_1h():
    # 09:00 UTC → 10:00 UTC for 1h bar.
    out = bar_close_time("2026-05-24T09:00:00+00:00", "1h")
    assert "10:00:00" in out


def test_bar_close_time_for_4h():
    out = bar_close_time("2026-05-24T08:00:00+00:00", "4h")
    assert "12:00:00" in out


def test_bar_close_time_unknown_tf_returns_input():
    # Unknown TF → return input unchanged.
    out = bar_close_time("2026-05-24T09:00:00+00:00", "7h")
    assert out == "2026-05-24T09:00:00+00:00"
