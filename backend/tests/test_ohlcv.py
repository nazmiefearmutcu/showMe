"""OHLCV fetcher tests with mocked ccxt exchange."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from showme.bots.ohlcv import BotRunnerError, fetch_ohlcv


class _FakeCcxtBroker:
    name = "ccxt:binance"

    def __init__(self, rows: list[list[float]] | None = None):
        self._ex = MagicMock()
        self._ex.fetch_ohlcv = AsyncMock(return_value=rows or [])


class _NonCcxtBroker:
    name = "paper"


@pytest.mark.asyncio
async def test_fetch_returns_dataframe():
    rows = [
        [1748000000000, 100.0, 101.0, 99.0, 100.5, 1000.0],
        [1748003600000, 100.5, 102.0, 99.5, 101.0, 1100.0],
    ]
    broker = _FakeCcxtBroker(rows)
    df = await fetch_ohlcv(broker, "BTC/USDT", "1h", 200)
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert len(df) == 2
    assert df["close"].iloc[-1] == 101.0
    assert df.index.tz is not None


@pytest.mark.asyncio
async def test_fetch_empty_returns_empty_df():
    broker = _FakeCcxtBroker([])
    df = await fetch_ohlcv(broker, "BTC/USDT", "1h", 200)
    assert df.empty
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]


@pytest.mark.asyncio
async def test_non_ccxt_raises():
    with pytest.raises(BotRunnerError, match="ccxt-backed"):
        await fetch_ohlcv(_NonCcxtBroker(), "BTC/USDT")


@pytest.mark.asyncio
async def test_fetch_exception_wrapped():
    broker = _FakeCcxtBroker()
    broker._ex.fetch_ohlcv = AsyncMock(side_effect=RuntimeError("rate limit"))
    with pytest.raises(BotRunnerError, match="fetch_ohlcv failed"):
        await fetch_ohlcv(broker, "BTC/USDT")


@pytest.mark.asyncio
async def test_passes_timeframe_and_limit():
    broker = _FakeCcxtBroker([])
    await fetch_ohlcv(broker, "ETH/USDT", "4h", 50)
    broker._ex.fetch_ohlcv.assert_called_once_with("ETH/USDT", timeframe="4h", limit=50)
