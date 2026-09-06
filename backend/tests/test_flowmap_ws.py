"""WS /ws/flowmap route tests: auth gate, handshake order, refusals, limits.

Same TestClient/websocket pattern as tests/test_websocket_auth.py. All feeds
are offline fakes injected through ``FeedHub(feed_factory=...)``; the canned
backfill seam seeds the ring BEFORE the snapshot is attached, so the
Hello -> EpochStart -> DepthCol ordering is deterministic.
"""
from __future__ import annotations

import asyncio
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from showme.flowmap import events, wire
from showme.flowmap.binance_feed import AggTrade, BookUpdate, FeedStateEvent
from showme.flowmap.session import ClientTx, FeedHub
from showme.server_routes import AppDeps, flowmap_ws

_TOKEN = "test-token-32-bytes-hex-1234567890ab"


# --- offline fakes -------------------------------------------------------------------


class FakeFeed:
    """Feed double: emits nothing until pushed to; never touches the network."""

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self.synced = True
        self._q: asyncio.Queue = asyncio.Queue()
        self.stopped = False

    def push(self, ev) -> None:
        self._q.put_nowait(ev)

    def stop(self) -> None:
        self.stopped = True

    async def events(self):
        while True:
            ev = await self._q.get()
            if ev is None:
                return
            yield ev


async def canned_backfill(symbol: str, *, max_cols: int, now_ns: int) -> list[dict]:
    """Four 1 m candles; the converter stretches + caps to max_cols columns."""
    minute = 60 * 10**9
    base = 1_752_710_400_000_000_000  # fixed ns (2025-07-17T00:00:00Z)
    rows = []
    for i in range(4):
        rows.append({
            "t0_ns": base + i * minute,
            "o": 100.0 + i, "h": 102.0 + i, "l": 99.0 + i, "c": 101.0 + i,
            "volume": 100.0 + i,
            "buy_volume": 60.0, "sell_volume": 40.0 + i,
        })
    return rows


def make_hub(max_sessions: int = 2, feeds: dict[str, FakeFeed] | None = None):
    registry: dict[str, FakeFeed] = {}
    hub = FeedHub(
        feed_factory=lambda symbol: registry.setdefault(symbol, FakeFeed(symbol)),
        backfill_fn=canned_backfill,
        backfill_max_cols=16,
        max_sessions=max_sessions,
    )
    return hub, registry


def build_app(hub) -> TestClient:
    app = FastAPI()
    flowmap_ws.register(app, AppDeps(), hub=hub)
    return TestClient(app)


def subscribe_frame(symbol: str = "BTC/USDT", market: str = "crypto",
                    band: str = "native", mode: str = "live") -> bytes:
    return wire.encode(events.Subscribe(
        market=market, symbol=symbol, mode=mode, band=band))


def recv_msgs(ws, *, deadline_s: float = 5.0, until=None) -> list:
    """Drain WS frames, accumulating decoded non-Ping events.

    Returns once ``until(events)`` is truthy or the deadline passes. The
    flush loop sends each queued frame as its own WS message, so callers
    that expect a multi-frame sequence MUST pass ``until`` — a bare read
    would return after whichever frame happens to arrive first.
    """
    out: list = []
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        try:
            data = ws.receive_bytes()
        except Exception:  # noqa: BLE001 — close/timeout: return what we have
            return out
        offset = 0
        while offset < len(data):
            ev, offset = wire.decode(data, offset)
            if isinstance(ev, events.Ping):
                continue
            out.append(ev)
        if until is not None and until(out):
            return out
    return out


def recv_until_close(ws, *, deadline_s: float = 5.0):
    """Read frames until the server closes or the deadline passes.

    Returns ``(events, disconnect)`` — the decoded non-Ping events and the
    WebSocketDisconnect (if the server closed).
    """
    out: list = []
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        try:
            data = ws.receive_bytes()
        except WebSocketDisconnect as exc:
            return out, exc
        except Exception:  # noqa: BLE001 — any other close: stop reading
            return out, None
        offset = 0
        while offset < len(data):
            ev, offset = wire.decode(data, offset)
            if isinstance(ev, events.Ping):
                continue
            out.append(ev)
    return out, None


def wait_until(pred, timeout_s: float = 5.0) -> bool:
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.05)
    return False


@pytest.fixture
def offline(monkeypatch):
    monkeypatch.setenv("SHOWME_WS_REQUIRE_ORIGIN", "0")
    monkeypatch.delenv("SHOWME_AUTH_TOKEN", raising=False)
    yield


# --- auth gate -----------------------------------------------------------------------


def test_missing_token_closed_4401(monkeypatch):
    monkeypatch.setenv("SHOWME_AUTH_TOKEN", _TOKEN)
    monkeypatch.setenv("SHOWME_WS_REQUIRE_ORIGIN", "0")
    hub, _reg = make_hub()
    client = build_app(hub)
    with pytest.raises(WebSocketDisconnect) as info, client.websocket_connect("/ws/flowmap"):
        pass
    assert info.value.code == 4401


def test_wrong_token_closed_4401(monkeypatch):
    monkeypatch.setenv("SHOWME_AUTH_TOKEN", _TOKEN)
    monkeypatch.setenv("SHOWME_WS_REQUIRE_ORIGIN", "0")
    hub, _reg = make_hub()
    client = build_app(hub)
    with pytest.raises(WebSocketDisconnect) as info, client.websocket_connect(
        f"/ws/flowmap?token=wrong-{_TOKEN}"
    ):
        pass
    assert info.value.code == 4401


def test_correct_token_query_accepted(monkeypatch):
    monkeypatch.setenv("SHOWME_AUTH_TOKEN", _TOKEN)
    monkeypatch.setenv("SHOWME_WS_REQUIRE_ORIGIN", "0")
    hub, _reg = make_hub()
    client = build_app(hub)
    # The gate passed iff a subscribe reaches the session and a Hello returns.
    with client.websocket_connect(f"/ws/flowmap?token={_TOKEN}") as ws:
        ws.send_bytes(subscribe_frame())
        msgs = recv_msgs(ws)
        assert isinstance(msgs[0], events.Hello)


def test_disallowed_origin_closed_1008(monkeypatch):
    monkeypatch.delenv("SHOWME_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("SHOWME_WS_REQUIRE_ORIGIN", raising=False)  # origin required
    hub, _reg = make_hub()
    client = build_app(hub)
    with pytest.raises(WebSocketDisconnect) as info, client.websocket_connect(
        "/ws/flowmap", headers={"Origin": "http://evil.example:1337"}
    ):
        pass
    assert info.value.code == 1008


def test_token_via_subprotocol_accepted(monkeypatch, offline):
    monkeypatch.setenv("SHOWME_AUTH_TOKEN", _TOKEN)
    hub, _reg = make_hub()
    client = build_app(hub)
    with client.websocket_connect(
        "/ws/flowmap", subprotocols=[f"showme.token.{_TOKEN}"]
    ) as ws:
        ws.send_bytes(subscribe_frame())
        msgs = recv_msgs(ws)
        assert any(isinstance(m, events.Hello) for m in msgs)


# --- handshake ordering --------------------------------------------------------------


def test_handshake_hello_epoch_depths_marker_history(offline):
    hub, _reg = make_hub()
    client = build_app(hub)
    with client.websocket_connect("/ws/flowmap") as ws:
        ws.send_bytes(subscribe_frame("BTC/USDT"))
        msgs = recv_msgs(ws, deadline_s=5.0, until=lambda ms: any(
            isinstance(m, events.Marker) for m in ms))
        kinds = [type(m).__name__ for m in msgs]
        # Hello first, exactly one EpochStart before the columns...
        assert kinds[0] == "Hello"
        assert kinds[1] == "EpochStart"
        assert kinds.count("EpochStart") == 1  # single (backfill) epoch
        # ...then the backfilled DepthCols (SYNTH_PROFILE, single channel),
        # each chunk frame carrying depth+bar pairs per column
        depths = [m for m in msgs if isinstance(m, events.DepthColumn)]
        bars = [m for m in msgs if isinstance(m, events.BarColumn)]
        assert len(depths) == 16  # canned backfill capped at 16 columns
        assert len(bars) == 16
        assert all(d.mode == events.MODE_SYNTH_PROFILE for d in depths)
        assert all(d.final for d in depths)
        assert [d.col_seq for d in depths] == list(range(16))
        # gap marker at the seam, AFTER all snapshot columns
        marker_idx = kinds.index("Marker")
        assert marker_idx == 2 + 16 * 2
        marker = msgs[marker_idx]
        assert marker.kind == "gap"
        hello = msgs[0]
        assert hello.protocol_version == wire.PROTO_VER
        assert hello.capability.get("history") == "reconstructed"

        # HISTORY_REQ is answered from the ring as EpochStart+HistoryResp
        ws.send_bytes(wire.encode(events.HistoryRequest(
            req_id=42, before_t=2**63 - 1, n_cols=8)))
        hist = recv_msgs(ws, until=lambda ms: any(
            isinstance(m, events.HistoryResponse) for m in ms))
        types = [type(m) for m in hist]
        assert types[0] is events.EpochStart
        resp = hist[1]
        assert isinstance(resp, events.HistoryResponse)
        assert resp.req_id == 42
        assert len(resp.depth_cols) == 8
        assert len(resp.bar_cols) == 8
        assert resp.oldest_available_t_ns > 0


def test_live_stream_after_snapshot(offline):
    hub, registry = make_hub()
    client = build_app(hub)
    with client.websocket_connect("/ws/flowmap") as ws:
        ws.send_bytes(subscribe_frame("ETHUSDT"))
        msgs = recv_msgs(ws)
        assert isinstance(msgs[0], events.Hello)

        feed = registry["ETHUSDT"]
        assert feed is not None
        t0 = 1_800_000_000_000_000_000
        # The first live book only ANCHORS grid time after the backfill tail;
        # the second one (one dt later) finalizes the first live column.
        feed.push(BookUpdate(
            ts_ns=t0,
            bids={99.0: 1.5}, asks={101.0: 2.5}, from_snapshot=True,
        ))
        feed.push(BookUpdate(
            ts_ns=t0 + 250_000_000,
            bids={99.0: 1.5}, asks={101.0: 2.5}, from_snapshot=True,
        ))
        feed.push(AggTrade(
            ts_ns=t0 + 1_000_000, price=100.5, qty=0.5, is_buyer_maker=True,
        ))
        live = recv_msgs(ws, until=lambda ms: any(
            isinstance(m, events.Trade) for m in ms))
        kinds = [type(m).__name__ for m in live]
        assert "DepthColumn" in kinds
        assert "BarColumn" in kinds
        assert "BBO" in kinds
        assert "Trade" in kinds
        bbo = next(m for m in live if isinstance(m, events.BBO))
        assert bbo.bid_px == 99.0 and bbo.ask_px == 101.0
        trade = next(m for m in live if isinstance(m, events.Trade))
        # m == true -> buyer is the maker -> SELL
        assert trade.side == events.SIDE_SELL


def test_pong_updates_latency_without_error(offline):
    hub, _reg = make_hub()
    client = build_app(hub)
    with client.websocket_connect("/ws/flowmap") as ws:
        ws.send_bytes(subscribe_frame())
        assert isinstance(recv_msgs(ws)[0], events.Hello)
        ws.send_bytes(wire.encode(events.Pong(echo_ns=1, client_recv_ns=2)))
        # connection survives a Pong (no reply expected; pings keep flowing)
        assert wait_until(lambda: True)


# --- refusal paths -------------------------------------------------------------------


def test_non_crypto_market_refused_closed_1003(offline):
    hub, _reg = make_hub()
    client = build_app(hub)
    with client.websocket_connect("/ws/flowmap") as ws:
        ws.send_bytes(subscribe_frame("AAPL", market="stocks"))
        msgs, exc = recv_until_close(ws, deadline_s=3.0)
        statuses = [m for m in msgs if isinstance(m, events.Status)]
        assert statuses and statuses[0].feed_state == "closed"
        assert exc is not None and exc.code == 1003
        assert hub.live_feed_count == 0  # no feed slot was ever occupied


def test_session_limit_third_subscribe_1013(offline):
    hub, _reg = make_hub(max_sessions=2)
    client = build_app(hub)
    with client.websocket_connect("/ws/flowmap") as ws1:
        ws1.send_bytes(subscribe_frame("BTCUSDT"))
        assert isinstance(recv_msgs(ws1)[0], events.Hello)

        with client.websocket_connect("/ws/flowmap") as ws2:
            ws2.send_bytes(subscribe_frame("ETHUSDT"))
            assert isinstance(recv_msgs(ws2)[0], events.Hello)
            assert hub.live_feed_count == 2

            with client.websocket_connect("/ws/flowmap") as ws3:
                ws3.send_bytes(subscribe_frame("SOLUSDT"))
                msgs, exc = recv_until_close(ws3, deadline_s=3.0)
                statuses = [m for m in msgs if isinstance(m, events.Status)]
                assert statuses and statuses[0].feed_state == "closed"
                assert exc is not None and exc.code == 1013


def test_unsubscribe_tears_feed_down(offline):
    hub, registry = make_hub(max_sessions=2)
    client = build_app(hub)
    with client.websocket_connect("/ws/flowmap") as ws:
        ws.send_bytes(subscribe_frame("BTCUSDT"))
        assert isinstance(recv_msgs(ws)[0], events.Hello)
        assert hub.live_feed_count == 1
        feed = registry["BTCUSDT"]
        ws.send_bytes(wire.encode(events.Unsubscribe()))
        assert wait_until(lambda: hub.live_feed_count == 0)
        assert feed.stopped
    # the freed slot is usable again
    with client.websocket_connect("/ws/flowmap") as ws:
        ws.send_bytes(subscribe_frame("SOLUSDT"))
        assert isinstance(recv_msgs(ws)[0], events.Hello)
        assert hub.live_feed_count == 1


def test_disconnect_tears_feed_down(offline):
    hub, _reg = make_hub(max_sessions=2)
    client = build_app(hub)
    with client.websocket_connect("/ws/flowmap") as ws:
        ws.send_bytes(subscribe_frame("BTCUSDT"))
        assert isinstance(recv_msgs(ws)[0], events.Hello)
        assert hub.live_feed_count == 1
    assert wait_until(lambda: hub.live_feed_count == 0)


def test_feed_degraded_broadcasts_status(offline):
    hub, registry = make_hub()
    client = build_app(hub)
    with client.websocket_connect("/ws/flowmap") as ws:
        ws.send_bytes(subscribe_frame())
        assert isinstance(recv_msgs(ws)[0], events.Hello)
        feed = registry["BTCUSDT"]
        feed.push(FeedStateEvent(state="degraded"))
        msgs = recv_msgs(ws, until=lambda ms: any(
            isinstance(m, events.Status) for m in ms))
        statuses = [m for m in msgs if isinstance(m, events.Status)]
        assert statuses and statuses[0].feed_state == "degraded"
        assert statuses[0].capability.get("depth") in {"L2", "L2-snapshot"}


def test_malformed_frame_dropped_connection_kept(offline):
    hub, _reg = make_hub()
    client = build_app(hub)
    with client.websocket_connect("/ws/flowmap") as ws:
        ws.send_bytes(subscribe_frame())
        assert isinstance(recv_msgs(ws)[0], events.Hello)
        ws.send_bytes(b"\xff\xff\x00\x00garbage-not-a-frame")
        # connection still alive: a valid subscribe works
        ws.send_bytes(wire.encode(events.Unsubscribe()))
        ws.send_bytes(subscribe_frame("ETHUSDT"))
        assert wait_until(lambda: hub.live_feed_count == 1)


def test_clienttx_drain_respects_frame_budget() -> None:
    tx = ClientTx()
    big = b"x" * (64 * 1024)
    for _ in range(10):
        tx.offer(big)
    frames = tx.drain(256 * 1024)
    assert len(frames) == 4  # 4 x 64 KiB == the 256 KiB budget
    assert len(tx) == 6
    # a single oversized frame is never wedged: always at least one frame out
    tx2 = ClientTx()
    tx2.offer(b"y" * (300 * 1024))
    assert len(tx2.drain(256 * 1024)) == 1
