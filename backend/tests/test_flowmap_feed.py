"""Binance feed tests: official snapshot+diff sync, fully OFFLINE.

The WS transport and REST getter are injectable; every test here feeds a fake.
"""
from __future__ import annotations

import asyncio
import json
import math

import pytest

from showme.flowmap.binance_feed import (
    AggTrade,
    BinanceBookFeed,
    BookUpdate,
    FeedStateEvent,
    KlineTick,
    _parse_agg_trade,
    _parse_kline,
    _ResyncNeeded,
    _Snapshot,
    fallback_tick,
    fetch_klines,
    fetch_tick_size,
    normalize_binance_symbol,
)

# --- symbol / tick helpers ---------------------------------------------------------


def test_normalize_accepts_both_spellings() -> None:
    assert normalize_binance_symbol("BTCUSDT") == "BTCUSDT"
    assert normalize_binance_symbol("btcusdt") == "BTCUSDT"
    assert normalize_binance_symbol("BTC/USDT") == "BTCUSDT"
    assert normalize_binance_symbol("BTC-USDT") == "BTCUSDT"
    assert normalize_binance_symbol(" eth/usdt ") == "ETHUSDT"
    assert normalize_binance_symbol("") == ""


def test_fallback_tick_is_sane_power_of_ten_scaled() -> None:
    assert fallback_tick(0) == 0.01  # degenerate input floor
    assert fallback_tick(float("nan")) == 0.01
    tick = fallback_tick(123.45)
    assert 0.0005 < tick < 0.005  # ~price/1e5
    # 4 significant figures (123.45 -> 123.5) divided by 1e5
    assert math.isclose(tick, 123.5 / 1e5)


async def test_fetch_tick_size_parses_exchange_info_and_caches() -> None:
    calls: list[str] = []

    async def rest(path, params):
        calls.append(path)
        return {"symbols": [{"symbol": "AAA1", "filters": [
            {"filterType": "PRICE_FILTER", "tickSize": "0.01000000"},
        ]}]}

    tick = await fetch_tick_size("AAA1", rest)
    assert tick == 0.01
    await fetch_tick_size("AAA1", rest)  # cached: no second call
    assert calls == ["/exchangeInfo"]


async def test_fetch_tick_size_falls_back_on_error() -> None:
    async def rest(path, params):
        raise ConnectionError("offline")

    assert await fetch_tick_size("BBB2", rest) == 0.01


async def test_fetch_klines_maps_taker_split() -> None:
    async def rest(path, params):
        assert path == "/klines"
        assert params["symbol"] == "CCC3"
        assert params["limit"] == 2
        return [
            [0, "101", "103", "100", "102", "10.0", 0, 0, 0, "6.0", 0],
            [60_000, "102", "104", "101", "104", "4.0", 0, 0, 0, "bad", 0],
        ]

    rows = await fetch_klines("CCC3", rest, limit=2)
    assert len(rows) == 2
    assert rows[0]["t0_ns"] == 0
    assert rows[0]["volume"] == 10.0
    assert rows[0]["buy_volume"] == 6.0
    assert rows[0]["sell_volume"] == 4.0
    # unparsable buy volume -> no fabricated split
    assert rows[1]["buy_volume"] is None
    assert rows[1]["sell_volume"] is None


async def test_fetch_klines_best_effort_empty_on_error() -> None:
    async def rest(path, params):
        raise ConnectionError("offline")

    assert await fetch_klines("DDD4", rest) == []


# --- sync algorithm (the official snapshot+diff dance) -------------------------------


def make_feed() -> BinanceBookFeed:
    async def transport(url):  # pragma: no cover — never iterated directly
        return
        yield  # pragma: no cover

    async def rest(path, params):  # pragma: no cover — overridden per test
        return {}

    return BinanceBookFeed("BTCUSDT", transport=transport, rest_get=rest)


def diff(u: int, U: int, bids=None, asks=None) -> dict:
    return {"u": u, "U": U, "b": bids or [], "a": asks or []}


def test_sync_drops_stale_and_applies_bridging_diff() -> None:
    feed = make_feed()
    feed._install_snapshot(_Snapshot(
        last_update_id=100,
        bids={99.0: 1.0},
        asks={101.0: 2.0},
    ))
    buffered = [
        diff(90, 80),                         # fully stale (u <= sid): dropped
        diff(100, 98),                        # stale (u == sid): dropped
        diff(101, 98, bids=[[99.0, "5.0"]]),  # bridges: U<=sid+1<=u -> applied
        diff(103, 102, asks=[[101.0, "0.0"]]),  # chains: U == prev_u+1 -> applied
    ]
    leftover = feed._drain_buffer(buffered)
    assert leftover == []
    assert feed.bids[99.0] == 5.0
    assert 101.0 not in feed.asks  # qty 0 removed the level
    assert feed.last_update_id == 103
    assert feed.synced is True


def test_sync_unbridgeable_snapshot_reports_leftover() -> None:
    feed = make_feed()
    feed._install_snapshot(_Snapshot(100, {99.0: 1.0}, {101.0: 1.0}))
    buffered = [diff(105, 104)]  # U > sid+1: the snapshot is too old
    leftover = feed._drain_buffer(buffered)
    assert leftover == buffered


def test_live_diff_gap_raises_resync() -> None:
    feed = make_feed()
    feed._install_snapshot(_Snapshot(100, {}, {}))
    feed._apply_levels(diff(101, 101))
    with pytest.raises(_ResyncNeeded, match="gap"):
        feed._apply_diff(diff(105, 105))


def test_apply_levels_zero_qty_removes_level() -> None:
    feed = make_feed()
    feed._install_snapshot(_Snapshot(10, {99.0: 1.0}, {101.0: 2.0}))
    feed._apply_levels(diff(11, 11, bids=[[99.0, "0.0"]], asks=[[100.5, "3.0"]]))
    assert 99.0 not in feed.bids
    assert feed.asks[100.5] == 3.0
    assert feed.last_update_id == 11


def test_stale_live_diff_is_ignored() -> None:
    feed = make_feed()
    feed._install_snapshot(_Snapshot(100, {}, {}))
    feed._apply_levels(diff(101, 101, bids=[[98.0, "1.0"]]))
    feed._apply_diff(diff(100, 99, bids=[[97.0, "9.0"]]))  # stale duplicate
    assert 97.0 not in feed.bids
    assert feed.last_update_id == 101


# --- the feed loop against a fake transport ------------------------------------------

_MS = 1_000_000


class FakeTransport:
    """Scripted combined-stream transport; raises before frame `explode_after`.

    Each yield is preceded by a loop tick so side tasks (the REST snapshot
    fetch) get deterministic scheduling between frames.
    """

    def __init__(self, frames: list[dict], explode_after: int | None = None) -> None:
        self.frames = [json.dumps(f) for f in frames]
        self.explode_after = explode_after
        self.urls: list[str] = []

    async def __call__(self, url: str):
        self.urls.append(url)
        for i, raw in enumerate(self.frames):
            if self.explode_after is not None and i >= self.explode_after:
                raise ConnectionError("simulated transport crash")
            await asyncio.sleep(0)
            yield raw


def depth_event(u: int, U: int, bids=None, asks=None) -> dict:
    return {"stream": "btcusdt@depth@100ms",
            "data": {"e": "depthUpdate", "u": u, "U": U, "b": bids or [], "a": asks or []}}


def trade_event(price: str, qty: str, maker: bool, ts_ms: int = 1) -> dict:
    return {"stream": "btcusdt@aggTrade",
            "data": {"e": "aggTrade", "p": price, "q": qty, "m": maker, "T": ts_ms}}


async def test_feed_buffers_then_syncs_then_streams() -> None:
    transport = FakeTransport([
        depth_event(90, 80, bids=[[99.0, "1.0"]]),   # buffered pre-snapshot
        depth_event(101, 98, bids=[[99.0, "5.0"]]),  # bridge
        trade_event("100.5", "0.25", maker=False, ts_ms=7),
        depth_event(103, 102, asks=[[101.0, "0.0"]]),  # chained live diff
    ])

    async def rest(path, params):
        assert path == "/depth"
        return {"lastUpdateId": 100,
                "bids": [["99.0", "1.0"]],
                "asks": [["101.0", "2.0"]]}

    feed = BinanceBookFeed("BTC/USDT", transport=transport, rest_get=rest)
    books: list[BookUpdate] = []
    trades: list[AggTrade] = []
    states: list[str] = []
    async for ev in feed.events():
        if isinstance(ev, BookUpdate):
            books.append(ev)
        elif isinstance(ev, AggTrade):
            trades.append(ev)
        elif isinstance(ev, FeedStateEvent):
            states.append(ev.state)
        if len(books) >= 2:
            feed.stop()
            break
    feed.stop()
    # snapshot arrives first and carries the bridged buffer
    assert books[0].from_snapshot is True
    assert books[0].bids[99.0] == 5.0
    assert books[0].asks[101.0] == 2.0
    # the chained live diff removed the ask level
    assert 101.0 not in books[1].asks
    assert feed.last_update_id == 103
    # liveness announced after the first synced book
    assert states and states[0] == "live"
    # the tape flowed
    assert len(trades) == 1
    assert trades[0].price == 100.5
    assert trades[0].is_buyer_maker is False
    assert trades[0].ts_ns == 7 * _MS
    # combined-stream URL with the lowercase symbol and all three streams
    assert transport.urls and "btcusdt@depth@100ms" in transport.urls[0]
    assert "btcusdt@aggTrade" in transport.urls[0]
    assert "btcusdt@kline_1s" in transport.urls[0]


async def test_feed_crash_degrades_and_backs_off_exponentially() -> None:
    transport = FakeTransport([], explode_after=0)  # crashes immediately

    async def rest(path, params):  # pragma: no cover — never reached
        return {"lastUpdateId": 1, "bids": [], "asks": []}

    delays: list[float] = []

    async def tracked_sleep(delay: float) -> None:
        delays.append(delay)  # do not actually wait in tests

    feed = BinanceBookFeed(
        "ETHUSDT", transport=transport, rest_get=rest,
        backoff_base_s=1.0, backoff_cap_s=15.0,
    )
    feed._sleep_backoff = tracked_sleep  # type: ignore[method-assign]

    states: list[str] = []
    it = feed.events().__aiter__()
    for _ in range(8):
        ev = await it.__anext__()
        if isinstance(ev, FeedStateEvent):
            states.append(ev.state)
        if len(delays) >= 3:
            break
    feed.stop()
    # crash -> degraded status -> exponential backoff -> reconnect
    assert states[0] == "degraded"
    assert "reconnecting" in states
    assert delays == [1.0, 2.0, 4.0]  # doubling from the base, before the cap
    # consume_backoff keeps doubling and caps at 15 s
    values = [feed.consume_backoff() for _ in range(6)]
    assert values[-1] == 15.0
    assert all(v <= 15.0 for v in values)


async def test_feed_stop_terminates_events_loop() -> None:
    transport = FakeTransport([])

    async def rest(path, params):
        return {"lastUpdateId": 1, "bids": [], "asks": []}

    feed = BinanceBookFeed("SOLUSDT", transport=transport, rest_get=rest)
    feed.stop()
    out = [ev async for ev in feed.events()]
    assert out == []


# --- stream payload parsers -----------------------------------------------------------


def test_parse_agg_trade() -> None:
    ev = _parse_agg_trade(
        {"p": "100.5", "q": "0.25", "m": True, "T": 123}, lambda: 5 * _MS,
    )
    assert ev.price == 100.5
    assert ev.qty == 0.25
    assert ev.is_buyer_maker is True
    assert ev.ts_ns == 123 * _MS


def test_parse_kline() -> None:
    tick = _parse_kline({"k": {"t": 5, "o": "1", "h": "2", "l": "0.5", "c": "1.5",
                               "v": "10", "x": True}})
    assert isinstance(tick, KlineTick)
    assert tick.closed is True
    assert tick.volume == 10.0
    assert _parse_kline({"nope": 1}) is None
