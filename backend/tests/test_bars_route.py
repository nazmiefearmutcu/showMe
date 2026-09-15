"""FastAPI route tests for GET /api/bars (keyless chart-engine OHLCV).

Covers the provider seams (Binance interval mapping, Yahoo interval+range
mapping), honest empty responses (unsupported pairs, provider failures),
limit slicing / ascending order / ms timestamps, and the 5 s TTL cache.
"""
from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from showme.server import build_app
from showme.server_routes import bars as bars_mod


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    bars_mod.bars_cache_clear()
    app = build_app(engine_root=None)
    return TestClient(app)


def _bar(t: int, price: float) -> dict[str, Any]:
    return {"t": t, "o": price, "h": price + 1.0, "l": price - 1.0, "c": price + 0.5, "v": 10.0}


# ── (a) crypto Binance mapping ────────────────────────────────────────────


def test_crypto_binance_interval_mapping(client, monkeypatch):
    calls: list[tuple[str, str, int]] = []

    async def fake_fetch(symbol: str, interval: str, limit: int):
        calls.append((symbol, interval, limit))
        return [_bar(1_700_000_000_000, 34_000.0)]

    monkeypatch.setattr(bars_mod, "fetch_binance_bars", fake_fetch)
    r = client.get("/api/bars?symbol=btcusdt&interval=1D&limit=5")
    assert r.status_code == 200
    body = r.json()
    assert calls == [("BTCUSDT", "1d", 5)]
    assert body["source"] == "binance"
    assert body["symbol"] == "BTCUSDT"
    assert body["interval"] == "1d"
    assert body["bars"][0]["t"] == 1_700_000_000_000


def test_crypto_month_interval_maps_to_1mo_not_minutes(client, monkeypatch):
    calls: list[tuple[str, str, int]] = []

    async def fake_fetch(symbol: str, interval: str, limit: int):
        calls.append((symbol, interval, limit))
        return []

    monkeypatch.setattr(bars_mod, "fetch_binance_bars", fake_fetch)
    r = client.get("/api/bars?symbol=ETHUSDT&interval=1M&limit=7")
    assert r.status_code == 200
    assert r.json()["interval"] == "1M"
    assert calls == [("ETHUSDT", "1mo", 7)]


# ── (b) yahoo interval + range mapping ────────────────────────────────────


def test_normalize_interval_aliases_keep_minute_and_month_apart():
    assert bars_mod.normalize_interval("1D") == "1d"
    assert bars_mod.normalize_interval("1W") == "1w"
    assert bars_mod.normalize_interval("1m") == "1m"
    assert bars_mod.normalize_interval("1M") == "1M"
    assert bars_mod.normalize_interval("60m") == "1h"
    assert bars_mod.normalize_interval("wat") == "1m"


def test_yahoo_interval_mapping_and_range(client, monkeypatch):
    calls: list[tuple[str, str, str]] = []

    async def fake_fetch(symbol: str, interval: str, yahoo_range: str):
        calls.append((symbol, interval, yahoo_range))
        return [_bar(1_700_000_000_000, 190.0)]

    monkeypatch.setattr(bars_mod, "fetch_yahoo_bars", fake_fetch)
    r = client.get("/api/bars?symbol=AAPL&interval=1h&limit=300")
    assert r.status_code == 200
    body = r.json()
    assert calls == [("AAPL", "60m", "730d")]
    assert body["source"] == "yahoo"
    assert body["symbol"] == "AAPL"
    assert body["interval"] == "1h"


def test_yahoo_daily_interval_mapping(client, monkeypatch):
    calls: list[tuple[str, str, str]] = []

    async def fake_fetch(symbol: str, interval: str, yahoo_range: str):
        calls.append((symbol, interval, yahoo_range))
        return []

    monkeypatch.setattr(bars_mod, "fetch_yahoo_bars", fake_fetch)
    r = client.get("/api/bars?symbol=MSFT&interval=1D&limit=10")
    assert r.status_code == 200
    assert calls == [("MSFT", "1d", "10y")]


# ── (c) seconds on equity → honest empty ──────────────────────────────────


def test_seconds_interval_on_equity_returns_honest_empty(client, monkeypatch):
    async def boom(*args: Any, **kwargs: Any):
        raise AssertionError("provider must not be called for unsupported pairs")

    monkeypatch.setattr(bars_mod, "fetch_yahoo_bars", boom)
    r = client.get("/api/bars?symbol=MSFT&interval=1s")
    assert r.status_code == 200
    body = r.json()
    assert body["bars"] == []
    assert body["source"] == "yahoo"
    assert body["reason"] == "1s bars are not available for yahoo instruments"


def test_second_only_interval_is_honest_empty_for_both_sources(client, monkeypatch):
    async def boom(*args: Any, **kwargs: Any):
        raise AssertionError("provider must not be called for unsupported pairs")

    monkeypatch.setattr(bars_mod, "fetch_yahoo_bars", boom)
    monkeypatch.setattr(bars_mod, "fetch_binance_bars", boom)
    equity = client.get("/api/bars?symbol=MSFT&interval=5s")
    assert equity.status_code == 200
    assert equity.json()["bars"] == []
    assert equity.json()["reason"] == "5s bars are not available for yahoo instruments"

    crypto = client.get("/api/bars?symbol=BTCUSDT&interval=15s")
    assert crypto.status_code == 200
    assert crypto.json()["bars"] == []
    assert (
        crypto.json()["reason"]
        == "15s bars are not available for binance instruments"
    )


# ── (d) limit slicing + ascending order + t is ms ─────────────────────────


def test_limit_slicing_sorts_ascending_and_keeps_latest(client, monkeypatch):
    base = 1_700_000_000_000
    shuffled = [
        _bar(base + 4 * 60_000, 5.0),
        _bar(base, 1.0),
        _bar(base + 2 * 60_000, 3.0),
        _bar(base + 60_000, 2.0),
        _bar(base + 3 * 60_000, 4.0),
    ]

    async def fake_fetch(symbol: str, interval: str, limit: int):
        return shuffled

    monkeypatch.setattr(bars_mod, "fetch_binance_bars", fake_fetch)
    r = client.get("/api/bars?symbol=BTCUSDT&interval=1m&limit=3")
    assert r.status_code == 200
    bars = r.json()["bars"]
    assert [b["t"] for b in bars] == [
        base + 2 * 60_000,
        base + 3 * 60_000,
        base + 4 * 60_000,
    ]
    assert all(isinstance(b["t"], int) for b in bars)


def test_limit_is_bounded_by_query_validation(client):
    assert client.get("/api/bars?symbol=BTCUSDT&limit=5000").status_code == 422
    assert client.get("/api/bars?symbol=BTCUSDT&limit=0").status_code == 422


# ── (e) 5 s TTL cache ─────────────────────────────────────────────────────


def test_cache_serves_second_call_without_provider_hit(client, monkeypatch):
    calls = {"n": 0}

    async def fake_fetch(symbol: str, interval: str, limit: int):
        calls["n"] += 1
        return [_bar(1_700_000_000_000, 34_000.0)]

    monkeypatch.setattr(bars_mod, "fetch_binance_bars", fake_fetch)
    first = client.get("/api/bars?symbol=BTCUSDT&interval=1m&limit=50")
    second = client.get("/api/bars?symbol=BTCUSDT&interval=1m&limit=50")
    assert first.status_code == second.status_code == 200
    assert first.json()["bars"] == second.json()["bars"]
    assert calls["n"] == 1


# ── (f) provider exception → empty + reason ───────────────────────────────


def test_provider_exception_returns_empty_with_reason(client, monkeypatch):
    async def boom(symbol: str, interval: str, limit: int):
        raise RuntimeError("binance 503")

    monkeypatch.setattr(bars_mod, "fetch_binance_bars", boom)
    r = client.get("/api/bars?symbol=BTCUSDT&interval=1m&limit=20")
    assert r.status_code == 200
    body = r.json()
    assert body["bars"] == []
    assert body["source"] == "binance"
    assert "binance fetch failed" in body["reason"]
    assert "binance 503" in body["reason"]


def test_yahoo_provider_exception_returns_empty_with_reason(client, monkeypatch):
    async def boom(symbol: str, interval: str, yahoo_range: str):
        raise RuntimeError("yahoo down")

    monkeypatch.setattr(bars_mod, "fetch_yahoo_bars", boom)
    r = client.get("/api/bars?symbol=AAPL&interval=1m&limit=20")
    assert r.status_code == 200
    body = r.json()
    assert body["bars"] == []
    assert "yahoo fetch failed" in body["reason"]
    assert "yahoo down" in body["reason"]
