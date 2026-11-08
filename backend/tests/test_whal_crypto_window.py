"""WHAL#2 — the crypto path must disclose the window its trades really cover.

Binance returns only the latest ``trade_limit`` aggregate trades per venue. For
BTCUSDT that is about 8.5 minutes, yet the pane labelled the result as a 24h
lookback. The payload now carries the covered window next to the requested
lookback, and a warning says the earlier part of the lookback is not checked.
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
    """``count`` trades evenly spread over the last ``span_minutes``, each ~$13k."""
    end_ms = int(time.time() * 1000)
    step = span_minutes * MINUTE_MS / max(count - 1, 1)
    return [
        {"a": i, "p": "65000", "q": "0.2", "f": i, "l": i,
         "T": int(end_ms - (count - 1 - i) * step), "m": bool(i % 2)}
        for i in range(count)
    ]


class _FakeBinance:
    """Serves Binance public endpoints for BTCUSDT only; nothing else."""

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


def _patch_binance(monkeypatch) -> None:
    monkeypatch.setattr(whal_mod, "httpx", SimpleNamespace(
        AsyncClient=_FakeBinance, Response=httpx.Response, HTTPError=httpx.HTTPError))


def test_crypto_window_reports_the_covered_span(monkeypatch) -> None:
    _patch_binance(monkeypatch)
    result = asyncio.run(WHALFunction(FunctionDeps()).execute(
        symbol="BTCUSDT", market="CRYPTO", threshold_usd=1_000, lookback_hours=24))
    assert result.data["lookback_hours"] == 24
    window = result.data.get("window") or {}
    assert window.get("lookback_hours") == 24
    covered = window.get("covered_hours")
    assert covered is not None, "crypto payload reports no covered window"
    assert 0.1 <= covered <= 0.2, f"8.5 minutes of trades reported as {covered}h"


def test_crypto_short_coverage_raises_a_warning(monkeypatch) -> None:
    _patch_binance(monkeypatch)
    result = asyncio.run(WHALFunction(FunctionDeps()).execute(
        symbol="BTCUSDT", market="CRYPTO", threshold_usd=1_000, lookback_hours=24))
    assert any("of the 24h lookback" in w and "0.1h" in w for w in result.warnings), result.warnings
