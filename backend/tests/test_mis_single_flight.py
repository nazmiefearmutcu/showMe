"""2026-09-17: MIS scans are single-flight and OHLCV fetches are TTL-cached.

The route used to start a new sweep per POST. Timed-out clients (the
sidecar default is 15 s) kept spawning rivals that fought over the 24-slot
semaphore and the shared thread pool — two concurrent sweeps crawled at
~1 fetch/s. Concurrent callers now join the in-flight scan. Frames are
cached per (market, symbol, timeframe) so a repeat scan inside the TTL does
not refetch, and callers can never mutate the cached copy.
"""
from __future__ import annotations

import asyncio

import pandas as pd

import showme.mis as mis
from showme.mis import MisScanRequest, MisScanResult


def _fresh_scan_state(monkeypatch) -> None:
    monkeypatch.setattr(mis, "_ACTIVE_SCAN", None)


async def test_concurrent_scans_join_single_flight(monkeypatch) -> None:
    calls = {"n": 0}

    async def fake_scan(req, deps):
        calls["n"] += 1
        await asyncio.sleep(0.05)
        return MisScanResult(markets=list(req.markets))

    monkeypatch.setattr(mis, "_run_mis_scan", fake_scan)
    _fresh_scan_state(monkeypatch)

    req = MisScanRequest(markets=["CRYPTO"])
    a, b = await asyncio.gather(
        mis.run_mis_scan(req, None),
        mis.run_mis_scan(req, None),
    )
    assert calls["n"] == 1
    assert a is b


async def test_new_scan_after_completion_runs_again(monkeypatch) -> None:
    calls = {"n": 0}

    async def fake_scan(req, deps):
        calls["n"] += 1
        return MisScanResult(markets=list(req.markets))

    monkeypatch.setattr(mis, "_run_mis_scan", fake_scan)
    _fresh_scan_state(monkeypatch)

    req = MisScanRequest(markets=["CRYPTO"])
    await mis.run_mis_scan(req, None)
    await mis.run_mis_scan(req, None)
    assert calls["n"] == 2


async def test_failed_scan_does_not_pin_single_flight(monkeypatch) -> None:
    calls = {"n": 0}

    async def fake_scan(req, deps):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return MisScanResult()

    monkeypatch.setattr(mis, "_run_mis_scan", fake_scan)
    _fresh_scan_state(monkeypatch)

    req = MisScanRequest(markets=["CRYPTO"])
    try:
        await mis.run_mis_scan(req, None)
    except RuntimeError:
        pass
    result = await mis.run_mis_scan(req, None)
    assert isinstance(result, MisScanResult)
    assert calls["n"] == 2


async def test_ohlcv_cache_returns_copies(monkeypatch) -> None:
    mis._FETCH_CACHE.clear()
    fetches = {"n": 0}

    class _Adapter:
        async def fetch(self, request):
            fetches["n"] += 1
            return pd.DataFrame({
                "open": [1.0, 2.0], "high": [1.5, 2.5], "low": [0.5, 1.5],
                "close": [1.2, 2.2], "volume": [10.0, 20.0],
            })

    class _Deps:
        ccxt_failover = _Adapter()

    try:
        df1 = await mis._fetch_ohlcv(_Deps(), "BTCUSDT", "CRYPTO", "1h", 45)
        df2 = await mis._fetch_ohlcv(_Deps(), "BTCUSDT", "CRYPTO", "1h", 45)
        assert fetches["n"] == 1          # second call was a cache hit
        assert df1 is not df2             # handed out as copies

        # A mutating caller must not poison the cached frame.
        df1.loc[0, "close"] = 99.0
        df3 = await mis._fetch_ohlcv(_Deps(), "BTCUSDT", "CRYPTO", "1h", 45)
        assert float(df3.iloc[0]["close"]) == 1.2
    finally:
        mis._FETCH_CACHE.clear()
