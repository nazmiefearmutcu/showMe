"""WHAL 24h equity window survives a closed market (WHAL#1).

Yahoo's 1d range returns only the newest session. The old code cut a wall-clock
24h window from it and returned the non-empty tail, so a session that ended more
than 23h ago (a weekend) produced zero threshold hits and a '24h' footer over
about 40 minutes of bars. The window is now cut from the 5d history, anchored at
the newest bar, and the covered span is reported.
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
STEP = 15 * 60


def _session(start: float, end: float, volume_for) -> dict:
    ts, closes, vols = [], [], []
    t = start
    while t <= end:
        ts.append(int(t))
        closes.append(200.0)
        vols.append(volume_for(t, end))
        t += STEP
    return {"timestamp": ts, "indicators": {"quote": [{
        "open": closes, "high": closes, "low": closes, "close": closes, "volume": vols,
    }]}}


class _Resp:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeAsyncClient:
    """Serves Yahoo chart data for a closed-weekend scenario; nothing else."""

    def __init__(self, *_a, **_k):
        now = time.time()
        last_end = now - 23.5 * HOUR          # newest session ended 23.5h ago
        last_start = now - 40 * HOUR
        prior_start, prior_end = now - 64 * HOUR, now - 48 * HOUR

        def high_then_thin_tail(t, end):
            # Most of the session trades heavily; the final 30 minutes are thin.
            return 100 if t > end - 30 * 60 else 50_000

        self._last = _session(last_start, last_end, high_then_thin_tail)
        self._prior = _session(prior_start, prior_end, lambda t, e: 50_000)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def get(self, _url, params=None, **_kwargs):
        rng = (params or {}).get("range")
        if rng == "1d":
            return _Resp({"chart": {"result": [self._last]}})
        if rng in {"5d", "1mo"}:
            merged = {"timestamp": self._prior["timestamp"] + self._last["timestamp"],
                      "indicators": {"quote": [{
                          k: self._prior["indicators"]["quote"][0][k] + self._last["indicators"]["quote"][0][k]
                          for k in ("open", "high", "low", "close", "volume")}]}}
            return _Resp({"chart": {"result": [merged]}})
        raise httpx.ConnectError("unexpected request in test")


def _patch_network(monkeypatch) -> None:
    monkeypatch.setattr(whal_mod, "httpx", SimpleNamespace(
        AsyncClient=_FakeAsyncClient, Response=httpx.Response, HTTPError=httpx.HTTPError))

    async def _no_sec(*_args, **_kwargs):
        return []

    monkeypatch.setattr(whal_mod, "_fetch_sec_filing_rows", _no_sec)


def test_weekend_24h_window_keeps_the_last_session(monkeypatch) -> None:
    _patch_network(monkeypatch)
    result = asyncio.run(WHALFunction(FunctionDeps()).execute(
        symbol="AAPL", market="EQUITY", threshold_usd=1_000_000, lookback_hours=24))
    # The newest session crosses $1M on most bars; the old code kept only the thin tail.
    rows = result.data["rows"]
    assert any(row.get("threshold_crossed") for row in rows), "last session crossing bars were dropped"
    history = result.data["history"]
    earliest = min(row["timestamp"] for row in history)
    last_session_start = time.time() - 40 * HOUR
    assert _iso(earliest) <= last_session_start + HOUR, "window still starts at the thin tail"


def test_window_reports_the_covered_span_honestly(monkeypatch) -> None:
    _patch_network(monkeypatch)
    result = asyncio.run(WHALFunction(FunctionDeps()).execute(
        symbol="AAPL", market="EQUITY", threshold_usd=1_000_000, lookback_hours=24))
    window = result.data.get("window") or {}
    assert window.get("lookback_hours") == 24
    # Bars inside the anchored 24h window span the last session, about 16.5h here.
    assert 15.5 <= window.get("covered_hours", 0) <= 17.5


def _iso(value: str) -> float:
    from datetime import datetime
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
