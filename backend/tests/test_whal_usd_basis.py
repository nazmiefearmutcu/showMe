"""WHAL#3 — rows without a USD value must not be reported as threshold-tested.

FX and index rows carry no USD notional, and SEC filings carry none either, so
no Min USD test can run on them. The summary must say so instead of "none
crossed $1,000,000", and those rows must not be marked as tested (False).
"""
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import httpx

import showme.engine.functions.misc.whal as whal_mod
from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.misc.whal import WHALFunction

HOUR = 3600


def _fx_bars() -> list[dict]:
    """Zero-volume FX bars with one sharp price impulse (volume missing, so no USD notional)."""
    start = time.time() - 6 * HOUR
    closes = [1.1000] * 20 + [1.1060] + [1.1000] * 10
    return [
        {"timestamp": _iso(start + i * 300), "open": c, "high": c, "low": c,
         "close": c, "volume": 0, "interval": "5m", "range": "5d"}
        for i, c in enumerate(closes)
    ]


def _iso(epoch: float) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


async def _fx_bars_fetch(*_args, **_kwargs):
    return _fx_bars()


def test_fx_summary_says_no_usd_basis_instead_of_none_crossed(monkeypatch) -> None:
    monkeypatch.setattr(whal_mod, "_fetch_yahoo_bars", _fx_bars_fetch)
    result = asyncio.run(WHALFunction(FunctionDeps()).execute(
        symbol="EURUSD", market="FX", threshold_usd=1_000_000))
    summary = result.data["summary"]
    assert "none crossed" not in summary, summary
    assert "could not be tested" in summary, summary
    rows = result.data["rows"]
    assert rows, "the FX impulse row should still be listed"
    assert all(row.get("threshold_crossed") is None for row in rows), rows


class _SecClient:
    """SEC EDGAR only: AAPL ticker map plus a submissions list with 3 ownership filings."""

    def __init__(self, *_a, **_k) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def get(self, url, params=None, **_kwargs):
        req = httpx.Request("GET", url)
        if url == whal_mod.SEC_TICKERS:
            return httpx.Response(200, json={"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}, request=req)
        if "submissions" in url:
            recent = {
                "form": ["4", "4", "8-K", "4"],
                "filingDate": ["2026-11-05", "2026-11-03", "2026-11-01", "2026-10-30"],
                "accessionNumber": ["0001-26-000001", "0001-26-000002", "0001-26-000003", "0001-26-000004"],
                "primaryDocument": ["a.xml", "b.xml", "c.htm", "d.xml"],
            }
            return httpx.Response(200, json={"filings": {"recent": recent}}, request=req)
        raise httpx.ConnectError("unexpected request in test")


def test_sec_filings_are_not_counted_as_threshold_tested(monkeypatch) -> None:
    monkeypatch.setattr(whal_mod, "httpx", SimpleNamespace(
        AsyncClient=_SecClient, Response=httpx.Response, HTTPError=httpx.HTTPError))

    async def _no_bars(*_args, **_kwargs):
        return []

    monkeypatch.setattr(whal_mod, "_fetch_yahoo_bars", _no_bars)
    # Route the module-level SEC cache through monkeypatch so the AAPL-only map
    # this test stores is undone afterwards and cannot leak into later tests.
    monkeypatch.setitem(whal_mod._SEC_TICKERS_CACHE, "fetched_at", 0.0)
    monkeypatch.setitem(whal_mod._SEC_TICKERS_CACHE, "by_ticker", {})

    result = asyncio.run(WHALFunction(FunctionDeps()).execute(
        symbol="AAPL", market="EQUITY", threshold_usd=1_000_000))
    rows = result.data["rows"]
    assert len(rows) == 3, rows
    assert all(row.get("threshold_crossed") is None for row in rows), rows
    summary = result.data["summary"]
    assert "none crossed" not in summary, summary
    assert "SEC filing" in summary and "without a USD value" in summary, summary
