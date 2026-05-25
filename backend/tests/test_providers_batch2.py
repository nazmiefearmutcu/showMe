"""Tests for the second batch of provider adapters.

Covers BinanceAdapter, YfinanceAdapter, GdeltAdapter, RssAdapter.

All HTTP / yfinance calls are stubbed — no real network. We monkeypatch
the shared ``httpx.AsyncClient`` returned by ``_http.get_client`` at
each adapter's binding site, and monkeypatch ``yfinance.Ticker`` itself
on the ``yfinance_adapter`` module.
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from showme.providers import _http
from showme.providers.binance import BinanceAdapter
from showme.providers.gdelt import GdeltAdapter
from showme.providers.rss_news import RssAdapter
from showme.providers.yfinance_adapter import YfinanceAdapter


# ---- fixtures / helpers --------------------------------------------------


def _fake_response(payload: Any, status: int = 200) -> MagicMock:
    """Build a httpx-Response-shaped mock."""
    resp = MagicMock()
    resp.status_code = status
    resp.json = MagicMock(return_value=payload)
    resp.text = (
        json.dumps(payload) if not isinstance(payload, str) else payload
    )
    if 200 <= status < 400:
        resp.raise_for_status = MagicMock(return_value=None)
    else:
        from httpx import HTTPStatusError, Request, Response

        req = Request("GET", "http://test")
        real = Response(status, request=req)
        err = HTTPStatusError(f"HTTP {status}", request=req, response=real)
        resp.raise_for_status = MagicMock(side_effect=err)
    return resp


def _install_fake_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    targets: list[str],
    response_map: dict[str, Any] | None = None,
    default_payload: Any = None,
    default_status: int = 200,
) -> MagicMock:
    """Patch ``get_client`` at the given binding sites.

    ``response_map`` lets a single test return different payloads for
    different URLs (used by the RSS aggregate test). The first key whose
    substring appears in the requested URL wins.
    """
    fake = MagicMock()
    fake.is_closed = False

    async def _aget(url: str, *args: Any, **kwargs: Any) -> MagicMock:
        if response_map:
            for needle, payload in response_map.items():
                if needle in url:
                    if isinstance(payload, tuple):
                        body, status = payload
                        return _fake_response(body, status)
                    return _fake_response(payload)
        return _fake_response(default_payload, default_status)

    fake.get = AsyncMock(side_effect=_aget)
    fake.post = AsyncMock(return_value=_fake_response(default_payload, default_status))
    fake.aclose = AsyncMock(return_value=None)

    async def _get_client() -> Any:
        return fake

    monkeypatch.setattr(_http, "get_client", _get_client)
    for module_path in targets:
        import importlib

        mod = importlib.import_module(module_path)
        monkeypatch.setattr(mod, "get_client", _get_client)
    return fake


# ---- BinanceAdapter ------------------------------------------------------


@pytest.mark.asyncio
async def test_binance_klines_offline(monkeypatch):
    """A canned 5-row BTCUSDT-1h kline response round-trips intact."""
    canned = [
        [
            1700000000000, "37000.00", "37500.00", "36800.00", "37200.00",
            "1234.5", 1700003599999, "45876000.00", 9876,
            "600.0", "22300000.00", "0",
        ],
        [
            1700003600000, "37200.00", "37800.00", "37100.00", "37650.00",
            "1500.2", 1700007199999, "56000000.00", 10500,
            "750.1", "27800000.00", "0",
        ],
        [
            1700007200000, "37650.00", "37700.00", "37200.00", "37300.00",
            "980.7", 1700010799999, "36700000.00", 7200,
            "440.3", "16500000.00", "0",
        ],
        [
            1700010800000, "37300.00", "37550.00", "37000.00", "37100.00",
            "1120.4", 1700014399999, "41600000.00", 8100,
            "570.0", "21200000.00", "0",
        ],
        [
            1700014400000, "37100.00", "37400.00", "36950.00", "37380.00",
            "1340.9", 1700017999999, "49900000.00", 9200,
            "680.2", "25300000.00", "0",
        ],
    ]
    _install_fake_client(
        monkeypatch,
        targets=["showme.providers.binance"],
        default_payload=canned,
    )
    adapter = BinanceAdapter()
    result = await adapter.klines("BTCUSDT", "1h", limit=5)
    assert result == canned
    assert len(result) == 5
    assert all(len(row) == 12 for row in result)
    assert adapter._last_error is None
    assert adapter._last_latency_ms is not None


@pytest.mark.asyncio
async def test_binance_ticker_24h_offline(monkeypatch):
    canned = {
        "symbol": "BTCUSDT",
        "priceChange": "210.50",
        "priceChangePercent": "0.567",
        "lastPrice": "37380.00",
        "volume": "12340.5",
    }
    _install_fake_client(
        monkeypatch,
        targets=["showme.providers.binance"],
        default_payload=canned,
    )
    adapter = BinanceAdapter()
    result = await adapter.ticker_24h("BTCUSDT")
    assert result == canned


def test_binance_ws_url_combined():
    """Combined-stream URL must match the exact Binance form."""
    adapter = BinanceAdapter()
    url = adapter.ws_url(["btcusdt@kline_1m", "ethusdt@trade"])
    assert url == "wss://stream.binance.com:9443/stream?streams=btcusdt@kline_1m/ethusdt@trade"


def test_binance_ws_url_single():
    """Single-stream URL uses the ``/ws/<stream>`` path, not the combined form."""
    adapter = BinanceAdapter()
    assert (
        adapter.ws_url(["btcusdt@kline_1m"])
        == "wss://stream.binance.com:9443/ws/btcusdt@kline_1m"
    )


def test_binance_ws_url_empty_raises():
    with pytest.raises(ValueError):
        BinanceAdapter().ws_url([])


def test_binance_capabilities_and_name():
    adapter = BinanceAdapter()
    assert adapter.name == "binance"
    assert adapter.capabilities() == {
        "klines", "ticker_24h", "exchange_info", "ws_stream_url",
    }


# ---- YfinanceAdapter -----------------------------------------------------


@pytest.mark.asyncio
async def test_yfinance_history_threaded(monkeypatch):
    """Monkeypatch ``yfinance.Ticker`` to verify ``history`` is offloaded
    to a thread and returns the supplied DataFrame untouched.
    """
    frame = pd.DataFrame(
        {
            "Open": [100.0, 101.0, 102.0],
            "High": [101.5, 102.5, 103.0],
            "Low": [99.5, 100.5, 101.5],
            "Close": [101.0, 102.0, 102.5],
            "Volume": [1_000_000, 1_100_000, 950_000],
        },
        index=pd.date_range("2026-05-20", periods=3, freq="D"),
    )

    class _FakeTicker:
        def __init__(self, symbol: str) -> None:
            self.symbol = symbol

        def history(self, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
            assert period == "1mo"
            assert interval == "1d"
            return frame

    class _FakeYfModule:
        Ticker = _FakeTicker

    monkeypatch.setitem(__import__("sys").modules, "yfinance", _FakeYfModule())
    adapter = YfinanceAdapter()
    result = await adapter.history("AAPL", period="1mo", interval="1d")
    pd.testing.assert_frame_equal(result, frame)
    assert adapter._last_error is None
    assert adapter._last_latency_ms is not None


@pytest.mark.asyncio
async def test_yfinance_info_threaded(monkeypatch):
    canned = {"shortName": "Apple Inc.", "marketCap": 3_100_000_000_000, "sector": "Technology"}

    class _FakeTicker:
        def __init__(self, symbol: str) -> None:
            self.symbol = symbol

        @property
        def info(self) -> dict[str, Any]:
            return dict(canned)

    class _FakeYfModule:
        Ticker = _FakeTicker

    monkeypatch.setitem(__import__("sys").modules, "yfinance", _FakeYfModule())
    adapter = YfinanceAdapter()
    result = await adapter.info("AAPL")
    assert result == canned


def test_yfinance_capabilities_and_name():
    adapter = YfinanceAdapter()
    assert adapter.name == "yfinance"
    assert adapter.capabilities() == {
        "history", "info", "fast_info", "earnings_dates", "get_news",
    }
    # Nominal mode is delayed_reference (yfinance scrapes free-tier feeds).
    from showme.providers import DataMode
    assert adapter.nominal_mode == DataMode.DELAYED_REFERENCE


# ---- GdeltAdapter --------------------------------------------------------


@pytest.mark.asyncio
async def test_gdelt_doc_search_offline(monkeypatch):
    canned = {
        "articles": [
            {
                "url": "https://example.com/a1",
                "title": "Fed signals rate hold",
                "seendate": "20260520T120000Z",
                "domain": "example.com",
                "language": "English",
            },
            {
                "url": "https://example.com/a2",
                "title": "Inflation print steady",
                "seendate": "20260520T110000Z",
                "domain": "example.com",
                "language": "English",
            },
        ],
    }
    _install_fake_client(
        monkeypatch,
        targets=["showme.providers.gdelt"],
        default_payload=canned,
    )
    adapter = GdeltAdapter()
    result = await adapter.doc_search("inflation", timespan="24h", maxrecords=10)
    assert result == canned
    assert len(result["articles"]) == 2
    assert adapter._last_error is None


@pytest.mark.asyncio
async def test_gdelt_timeline_volume_offline(monkeypatch):
    canned = {
        "timeline": [
            {"date": "20260514", "value": 0.42},
            {"date": "20260515", "value": 0.51},
        ],
    }
    _install_fake_client(
        monkeypatch,
        targets=["showme.providers.gdelt"],
        default_payload=canned,
    )
    adapter = GdeltAdapter()
    result = await adapter.timeline_volume("inflation", timespan="1w")
    assert result == canned


def test_gdelt_capabilities_and_name():
    adapter = GdeltAdapter()
    assert adapter.name == "gdelt"
    assert adapter.capabilities() == {"doc_search", "timeline_volume"}


# ---- RssAdapter ----------------------------------------------------------


_FEED_A = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
<title>Feed A</title>
<link>https://a.example.com/</link>
<item>
  <title>Shared headline</title>
  <link>https://example.com/shared</link>
  <pubDate>Tue, 20 May 2026 12:00:00 GMT</pubDate>
  <description>Body A</description>
</item>
<item>
  <title>Unique to A</title>
  <link>https://example.com/unique-a</link>
  <pubDate>Tue, 20 May 2026 13:00:00 GMT</pubDate>
  <description>Only in feed A</description>
</item>
</channel>
</rss>
"""

_FEED_B = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
<title>Feed B</title>
<link>https://b.example.com/</link>
<item>
  <title>Shared headline</title>
  <link>https://example.com/shared</link>
  <pubDate>Tue, 20 May 2026 12:00:00 GMT</pubDate>
  <description>Body B</description>
</item>
<item>
  <title>Unique to B</title>
  <link>https://example.com/unique-b</link>
  <pubDate>Tue, 20 May 2026 14:00:00 GMT</pubDate>
  <description>Only in feed B</description>
</item>
</channel>
</rss>
"""


@pytest.mark.asyncio
async def test_rss_aggregate_dedupe(monkeypatch):
    """Two feeds, one shared link → aggregate returns 3 unique entries."""
    _install_fake_client(
        monkeypatch,
        targets=["showme.providers.rss_news"],
        response_map={
            "feed-a": _FEED_A,
            "feed-b": _FEED_B,
        },
    )
    adapter = RssAdapter()
    entries = await adapter.aggregate(
        ["https://a.example.com/feed-a", "https://b.example.com/feed-b"],
        dedupe_by="link",
    )
    links = [e["link"] for e in entries]
    assert links.count("https://example.com/shared") == 1
    assert "https://example.com/unique-a" in links
    assert "https://example.com/unique-b" in links
    assert len(entries) == 3
    # Newest-first sort: unique-b (14:00) before unique-a (13:00) before shared (12:00).
    assert entries[0]["link"] == "https://example.com/unique-b"
    assert entries[-1]["link"] == "https://example.com/shared"


@pytest.mark.asyncio
async def test_rss_fetch_single(monkeypatch):
    _install_fake_client(
        monkeypatch,
        targets=["showme.providers.rss_news"],
        default_payload=_FEED_A,
    )
    adapter = RssAdapter()
    entries = await adapter.fetch("https://a.example.com/feed-a")
    assert len(entries) == 2
    titles = {e["title"] for e in entries}
    assert "Shared headline" in titles
    assert "Unique to A" in titles
    # All entries carry a populated source (parsed from <channel><title>).
    assert all(e["source"] for e in entries)


def test_rss_capabilities_and_name():
    adapter = RssAdapter()
    assert adapter.name == "rss"
    assert adapter.capabilities() == {"feed_fetch", "feed_aggregate"}
