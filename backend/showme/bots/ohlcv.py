"""OHLCV fetcher — talks to ccxt-backed brokers to pull recent candles.

Returns a pandas DataFrame with lowercase columns (open/high/low/close/volume)
and a datetime index. Non-ccxt brokers (Alpaca etc.) are NOT supported in v1.
"""
from __future__ import annotations

import logging

import pandas as pd

from showme.brokers.base import BaseBroker

LOG = logging.getLogger("showme.bots.ohlcv")


class BotRunnerError(RuntimeError):
    """Raised when the runner can't proceed (e.g. broker doesn't support OHLCV)."""


def _is_ccxt(broker: BaseBroker) -> bool:
    """Detect ccxt-backed brokers without relying on a name prefix.

    S3 fix: the original ``broker.name.startswith("ccxt:")`` happens to
    match the production ``CcxtBroker.name`` ("ccxt:{exchange_id}") but
    fails for any future adapter that conforms structurally without the
    prefix. We instead probe the structural contract that downstream code
    actually uses: a private ``_ex`` attribute exposing ``fetch_ohlcv``.
    ``isinstance(broker, CcxtBroker)`` is preferred when the import is
    available; otherwise we fall back to ``_ex`` / ``fetch_ohlcv`` duck
    typing so tests can still register ``MagicMock``-backed fakes.
    """
    try:
        from showme.brokers.ccxt_broker import CcxtBroker as _CcxtBroker
    except Exception:  # pragma: no cover — optional dep
        _CcxtBroker = None  # type: ignore[assignment]
    if _CcxtBroker is not None and isinstance(broker, _CcxtBroker):
        return True
    ex = getattr(broker, "_ex", None)
    if ex is not None and hasattr(ex, "fetch_ohlcv"):
        return True
    # Legacy fallback: keep the prefix check so existing tests that mint
    # brokers via ``factory_mod._REGISTRY`` with ``name = "ccxt:..."`` keep
    # working (see ``tests/test_bot_runner.py::_register_fake_broker``).
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
