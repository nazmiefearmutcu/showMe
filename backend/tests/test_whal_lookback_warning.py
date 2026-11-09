"""WHAL#2 follow-up — the coverage shortfall warning must fire for every lookback option.

Binance returns only the latest 1000 aggregate trades. With a 1h lookback and trades that
cover about 8.5 minutes, the warning was skipped because the check was
``covered < lookback_hours - 1``, which is never true for a 1h lookback. The shortfall
must be reported for 1h as it is for 6h, 24h and 72h.
"""
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import httpx

import showme.engine.functions.misc.whal as whal_mod
from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.misc.whal import WHALFunction
MINUTE_MS = 60_000


def _binance_trades(span_minutes: float, count: int = 1000) -> list[dict]:
    """count trades evenly spread over the last span_minutes."""
    end_ms = int(time.time() * 1000)
    step = span_minutes * MINUTE_MS / max(count - 1, 1)
    return [
        {"a": i, "p": "65000", "q": "0.2", "f": i, "l": i,
         "T": int(end_ms - (count - 1 - i) * step), "m": bool(i % 2)}
        for i in range(count)
    ]


class _Binance8Point5Min:
    """Serves 1000 BTCUSDT trades spread over 8.5 minutes; nothing else."""

    def __init__(self, *_a, **_k) -> None:
        self._trades = _binance_trades(8.5)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def get(self, url, params=None, **_kwargs):
        req = httpx.Request("GET", url)
        if url.endswith("/aggTrades"):
            return httpx.Response(200, json=self._trades, request=req)
        if url.endswith("/klines"):
            return httpx.Response(200, json=[], request=req)
        if url.endswith("/ticker/24hr"):
            return httpx.Response(200, json={"quoteVolume": "1000000"}, request=req)
        raise httpx.ConnectError("unexpected request in test")


def _run(monkeypatch, lookback_hours: int):
    monkeypatch.setattr(whal_mod, "httpx", SimpleNamespace(
        AsyncClient=_Binance8Point5Min, Response=httpx.Response, HTTPError=httpx.HTTPError))
    return asyncio.run(WHALFunction(FunctionDeps()).execute(
        symbol="BTCUSDT", market="CRYPTO", threshold_usd=1_000, lookback_hours=lookback_hours))


def test_one_hour_lookback_warns_when_trades_cover_only_minutes(monkeypatch) -> None:
    result = _run(monkeypatch, lookback_hours=1)
    assert result.data["lookback_hours"] == 1
    assert any("of the 1h lookback" in w for w in result.warnings), result.warnings


def test_full_coverage_for_a_one_hour_lookback_raises_no_warning(monkeypatch) -> None:
    # Trades spread over a full hour cover the lookback, so no shortfall is reported.
    class _FullHour(_Binance8Point5Min):
        def __init__(self, *_a, **_k) -> None:
            self._trades = _binance_trades(60.0)

    monkeypatch.setattr(whal_mod, "httpx", SimpleNamespace(
        AsyncClient=_FullHour, Response=httpx.Response, HTTPError=httpx.HTTPError))
    result = asyncio.run(WHALFunction(FunctionDeps()).execute(
        symbol="BTCUSDT", market="CRYPTO", threshold_usd=1_000, lookback_hours=1))
    assert not any("lookback" in w and "cover" in w for w in result.warnings), result.warnings
