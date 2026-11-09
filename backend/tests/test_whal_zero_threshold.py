"""WHAL#5 — a zero threshold must not mark every trade as large, and an unknown
crypto symbol must not silently query another pair (the chain's USDT pair).
"""
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import httpx

import showme.engine.functions.misc.whal as whal_mod
from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.misc.whal import WHALFunction, _shape_binance_trades

MINUTE_MS = 60_000


def _trades(count: int = 5) -> list[dict]:
    end_ms = int(time.time() * 1000)
    return [
        {"p": "0.00001", "q": str(1_000_000 * (i + 1)), "T": end_ms - (count - i) * MINUTE_MS, "m": False}
        for i in range(count)
    ]


def test_zero_threshold_does_not_label_trades_as_large() -> None:
    rows = _shape_binance_trades(_trades(), "PEPEUSDT", "spot", 0, 25)
    assert rows, "with no threshold the top trades are still listed"
    assert all(row.get("threshold_crossed") is None for row in rows), rows
    assert all(row.get("alert_type") == "crypto_trade" for row in rows), rows
    assert all(row.get("severity") == "unrated" for row in rows), rows


class _RecordingBinance:
    """Records every Binance symbol requested; serves PEPE trades only when PEPEUSDT is asked."""

    requested: list[str] = []

    def __init__(self, *_a, **_k) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def get(self, url, params=None, **_kwargs):
        req = httpx.Request("GET", url)
        symbol = (params or {}).get("symbol", "")
        _RecordingBinance.requested.append(symbol)
        if symbol != "PEPEUSDT":
            return httpx.Response(400, json={"code": -1121, "msg": "Invalid symbol."}, request=req)
        if url.endswith("/aggTrades"):
            return httpx.Response(200, json=_trades(), request=req)
        if url.endswith("/klines"):
            return httpx.Response(200, json=[], request=req)
        return httpx.Response(200, json={"quoteVolume": "1"}, request=req)


def test_unknown_crypto_symbol_is_not_silently_rerouted_to_btc(monkeypatch) -> None:
    _RecordingBinance.requested = []
    monkeypatch.setattr(whal_mod, "httpx", SimpleNamespace(
        AsyncClient=_RecordingBinance, Response=httpx.Response, HTTPError=httpx.HTTPError))
    result = asyncio.run(WHALFunction(FunctionDeps()).execute(
        symbol="FOOBAR", market="CRYPTO", threshold_usd=1_000))
    assert "BTCUSDT" not in _RecordingBinance.requested, _RecordingBinance.requested
    # WHAL#5 follow-up: a typo is an input error with a reason, never a provider outage.
    assert result.data["status"] == "input_error"
    assert "FOOBAR" in result.data["reason"]
    assert result.data["provider_symbol"] is None


def test_zero_threshold_summary_does_not_claim_crossed_zero(monkeypatch) -> None:
    monkeypatch.setattr(whal_mod, "httpx", SimpleNamespace(
        AsyncClient=_RecordingBinance, Response=httpx.Response, HTTPError=httpx.HTTPError))
    result = asyncio.run(WHALFunction(FunctionDeps()).execute(
        symbol="PEPEUSDT", market="CRYPTO", threshold_usd=0))
    summary = result.data["summary"]
    assert "crossed $0" not in summary, summary
    assert "No USD threshold" in summary, summary
