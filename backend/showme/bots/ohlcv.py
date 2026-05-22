"""OHLCV fetcher — talks to ccxt-backed brokers to pull recent candles.

Returns a pandas DataFrame with lowercase columns (open/high/low/close/volume)
and a datetime index. Non-ccxt brokers (Alpaca etc.) are NOT supported in v1.
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from showme.brokers.base import BaseBroker

LOG = logging.getLogger("showme.bots.ohlcv")


class BotRunnerError(RuntimeError):
    """Raised when the runner can't proceed (e.g. broker doesn't support OHLCV)."""


def _is_ccxt(broker: BaseBroker) -> bool:
    return getattr(broker, "name", "").startswith("ccxt:")


async def fetch_ohlcv(
    broker: BaseBroker,
    symbol: str,
    timeframe: str = "1h",
    limit: int = 200,
) -> pd.DataFrame:
    """Fetch up to ``limit`` recent OHLCV bars for ``symbol`` on ``broker``.

    Returns DataFrame with columns [open, high, low, close, volume] and a
    UTC datetime index. Empty DataFrame if the exchange returned nothing
    (rare but possible on symbols that don't trade).

    Raises BotRunnerError for non-ccxt brokers or transport failures.
    """
    if not _is_ccxt(broker):
        raise BotRunnerError(
            f"OHLCV fetch requires a ccxt-backed broker; got {broker.name!r}",
        )
    ex = getattr(broker, "_ex", None)
    if ex is None or not hasattr(ex, "fetch_ohlcv"):
        raise BotRunnerError(f"broker {broker.name!r} has no fetch_ohlcv")
    try:
        raw = await ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    except Exception as exc:  # noqa: BLE001
        raise BotRunnerError(f"fetch_ohlcv failed: {exc}") from exc
    if not raw:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = pd.DataFrame(raw, columns=["ts", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df.set_index("ts")
    return df
