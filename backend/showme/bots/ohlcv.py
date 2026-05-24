"""OHLCV fetcher — talks to ccxt-backed brokers to pull recent candles.

Returns a pandas DataFrame with lowercase columns (open/high/low/close/volume)
and a datetime index. Non-ccxt brokers (Alpaca etc.) are NOT supported in v1.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd

from showme.brokers.base import BaseBroker

# Q4 audit C1 fix: timeframe → bar length in milliseconds. Used by the
# lookahead guard to detect a bar that hasn't closed yet.
_TF_MS: dict[str, int] = {
    "1m": 60_000,
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "1h": 60 * 60_000,
    "4h": 4 * 60 * 60_000,
    "1d": 24 * 60 * 60_000,
}

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
    *,
    drop_incomplete_last_bar: bool = True,
    now_ms: int | None = None,
) -> pd.DataFrame:
    """Fetch up to ``limit`` recent OHLCV bars for ``symbol`` on ``broker``.

    Returns DataFrame with columns [open, high, low, close, volume] and a
    UTC datetime index. Empty DataFrame if the exchange returned nothing
    (rare but possible on symbols that don't trade).

    Q4 audit C1 fix — live-mode lookahead/repaint guard:
      The OHLCV endpoint on every ccxt exchange returns the *current open*
      bar as the last row. Indicators (RSI/MACD/EMA) computed against that
      open bar repaint on every tick because the bar's close moves with
      every print. When ``drop_incomplete_last_bar=True`` (default) we
      compare the bar's OPEN-time (the ts column ccxt returns) against
      ``now_ms``; if ``now_ms < open_time + bar_length`` (bar still open),
      we drop the last row. Set ``drop_incomplete_last_bar=False`` to opt
      out (the backtest harness uses this to keep all bars).

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
    if drop_incomplete_last_bar and len(df) > 0:
        bar_len_ms = _TF_MS.get(timeframe)
        if bar_len_ms is not None:
            current_ms = int(now_ms) if now_ms is not None else int(
                datetime.now(tz=timezone.utc).timestamp() * 1000,
            )
            last_open_ms = int(df["ts"].iloc[-1])
            last_close_ms = last_open_ms + bar_len_ms
            if current_ms < last_close_ms:
                # Bar hasn't closed yet — drop to prevent repaint.
                LOG.debug(
                    "dropping incomplete %s bar for %s (open=%s closes=%s now=%s)",
                    timeframe, symbol, last_open_ms, last_close_ms, current_ms,
                )
                df = df.iloc[:-1]
                if df.empty:
                    return pd.DataFrame(
                        columns=["open", "high", "low", "close", "volume"],
                    )
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df.set_index("ts")
    return df


def bar_close_time(open_time_iso: str, timeframe: str) -> str:
    """Q4 audit H11: convert an OPEN-time ISO string to the bar's CLOSE-time.

    OHLCV `ts` is the bar's open. UI / PERF report close-time alongside so
    users can disambiguate "entry at 09:00:00" (bar opened at 09:00, closed
    at 10:00). Returns an ISO-8601 UTC string; on parse failure returns the
    input unchanged so the caller never sees ``None``.
    """
    bar_len_ms = _TF_MS.get(timeframe)
    if bar_len_ms is None or not open_time_iso:
        return open_time_iso
    try:
        ts = pd.Timestamp(open_time_iso)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        close_ts = ts + pd.Timedelta(milliseconds=bar_len_ms)
        return close_ts.isoformat()
    except Exception:  # noqa: BLE001
        return open_time_iso
