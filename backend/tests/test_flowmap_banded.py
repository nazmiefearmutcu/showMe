"""Banded-grid regression tests (FLW live-verification findings).

Two production bugs found by probing the live ``/ws/flowmap`` route against
real Binance data, both rooted in the pre-anchor nominal frame ($100):

1. Cold-start backfill silently produced zero columns for any instrument
   priced far from the nominal frame (``columns_from_candles`` mapped every
   candle outside the 1024-row window and returned ``None``).
2. The fixed tiny step made the legacy central-70% rule re-anchor on every
   small mid wiggle (6 epochs in 30 s on BTCUSDT).

The fix ports upstream's banded regime: percentage coverage around a
reference mid, ``tick_multiple`` frozen at the first anchor, ±25% ratio
trips afterwards, and boot backfill anchoring on the newest close BEFORE
reconstruction.
"""
from __future__ import annotations

import asyncio
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from showme.flowmap import events, wire
from showme.flowmap.binance_feed import AggTrade, BookUpdate
from showme.flowmap.grid import Grid, GridCfg
from showme.flowmap.session import FeedHub
from showme.server_routes import AppDeps, flowmap_ws

# --- grid-level: banded anchor + ratio trip ------------------------------------------


def _banded_grid(p0: float = 79.52) -> Grid:
    return Grid(GridCfg(
        tick=0.01, tick_multiple=1, dt_ns=250_000_000, p0=p0,
        rows=1024, ring_columns=4096, band_up=0.5, band_down=0.5,
    ))


def test_banded_anchor_builds_percentage_frame_and_freezes_multiple():
    g = _banded_grid()
    params = g.anchor_banded(79_800.0)
    assert params is not None and params.epoch == 1
    # wide = +-50% * BAND_MARGIN(1.25) => span ~= mid * 1.25
    span = g.cfg.rows * 0.01 * params.tick_multiple
    assert params.tick_multiple > 1
    assert abs(span - 79_800.0 * 1.25) <= 0.01 * params.tick_multiple * g.cfg.rows
    # frame is centered (snapped) on the reference mid
    center = params.p0 + span / 2.0
    assert abs(center - 79_800.0) <= 0.01 * params.tick_multiple


def test_banded_wiggles_never_storm_epochs():
    g = _banded_grid()
    g.anchor_banded(79_800.0)
    fired = 0
    for i in range(2000):
        mid = 79_800.0 + ((i % 37) - 18) * 7.5  # +- ~$135 symmetric wiggle
        if g.maybe_reanchor(mid) is not None:
            fired += 1
    assert fired == 0


def test_banded_ratio_trip_is_p0_only_and_bumps_epoch_once():
    g = _banded_grid()
    first = g.anchor_banded(79_800.0)
    assert first is not None
    assert g.maybe_reanchor(79_800.0 * 1.20) is None  # inside the trip band
    second = g.maybe_reanchor(79_800.0 * 1.40)        # +40% => trip
    assert second is not None and second.epoch == first.epoch + 1
    assert second.tick_multiple == first.tick_multiple  # frozen
    span = g.cfg.rows * 0.01 * second.tick_multiple
    center = second.p0 + span / 2.0
    assert abs(center - 79_800.0 * 1.40) <= 0.01 * second.tick_multiple * g.cfg.rows
    assert g.maybe_reanchor(79_800.0 * 1.40) is None  # new anchor accepted


def test_legacy_band_still_uses_central_70_rule():
    g = Grid(GridCfg(
        tick=0.01, tick_multiple=4, dt_ns=250_000_000, p0=100.0,
        rows=1024, ring_columns=4096,
    ))
    assert g.cfg.band_up is None
    assert g.maybe_reanchor(100.0 + 0.40 * 1024 * 0.04) is None   # inside 70%
    assert g.maybe_reanchor(100.0 + 0.90 * 1024 * 0.04) is not None  # outside


def test_first_banded_anchor_mid_live_keeps_feed_alive():
    """REGRESSION (review C1): a banded grid that anchors from a LIVE state
    (cold start with failed backfill) must keep accepting books — resetting
    `_prev_ts` with `_cur_idx` set crashed `on_book` on `max(ts_ns, None)`."""
    g = _banded_grid()
    t0 = 1_800_000_000_000_000_000
    g.on_book(t0, 99.0, 1.0, 101.0, 1.0)
    assert g.maybe_reanchor(100.0) is not None  # first live anchor
    g.on_book(t0 + 250_000_000, 99.0, 1.0, 101.0, 1.0)  # used to raise
    g.on_book(t0 + 500_000_000, 99.0, 1.0, 101.0, 1.0)


def test_native_legacy_band_no_epoch_storm_at_real_price():
    """REGRESSION (review H2): the legacy fixed-span grid at a real BTC price
    with the exchange cent tick re-anchored on every wiggle (321 per 2000
    books). Upstream parity: crypto grids use the FIXED 0.5 tick — a ~$512
    span needs a real ~$150+ move to trip the central-70% rule."""
    g = Grid(GridCfg(
        tick=0.5, tick_multiple=1, dt_ns=250_000_000, p0=79.52,
        rows=2048, ring_columns=4096,
    ))
    t = 1_800_000_000_000_000_000
    fired = 0
    for i in range(2000):
        mid = 79_800.0 + ((i % 37) - 18) * 7.5  # +- ~$135 symmetric wiggle
        g.on_book(t + i * 250_000_000, mid - 1.0, 1.0, mid + 1.0, 1.0)
        if g.maybe_reanchor(mid) is not None:
            fired += 1
    # Exactly one legit re-anchor: the nominal-p0 -> real-mid jump on the
    # first book (upstream does the same). Pre-fix this was dozens.
    assert fired == 1


def test_banded_first_anchor_snapped_frame_covers_hi():
    """REGRESSION (review H3): rounding p0 onto the step grid could uncover
    the top of the requested band — the snapped frame must provably cover
    mid*(1+band_up)."""
    g = Grid(GridCfg(
        tick=0.01, tick_multiple=1, dt_ns=250_000_000, p0=79.52,
        rows=1024, ring_columns=4096, band_up=10.0, band_down=1.0,
    ))
    params = g.anchor_banded(79_800.0)
    assert params is not None
    span = params.rows * params.tick * params.tick_multiple
    assert params.p0 + span >= 79_800.0 * (1.0 + 10.0)  # covers hi exactly


def test_client_tx_never_evicts_protected_frames():
    """REGRESSION (review H1): under backpressure the drop-oldest scan could
    evict the protected Hello/snapshot frames at the queue head."""
    from showme.flowmap.session import ClientTx
    tx = ClientTx(cap=4)
    tx.offer(b"hello", protected=True)
    tx.offer(b"ep", protected=True)
    for i in range(10):
        tx.offer(b"junk", protected=False)
    frames = tx.drain(1 << 20)
    assert b"hello" in frames and b"ep" in frames


def test_wire_cold_encode_rejects_nan():
    """REGRESSION (review M3): a NaN reaching a cold payload must raise
    (msgspec fail-fast parity) instead of emitting invalid JSON."""
    import pytest
    from showme.flowmap import events, wire
    bad = events.EpochParams(
        epoch=1, tick=float("nan"), tick_multiple=1,
        dt_ns=250_000_000, p0=100.0, rows=1024,
    )
    with pytest.raises(ValueError):
        wire.encode(events.EpochStart(epoch=1, epoch_params=bad))


def test_anchor_banded_ignores_legacy_and_bad_mids():
    legacy = Grid(GridCfg(
        tick=0.01, tick_multiple=1, dt_ns=250_000_000, p0=100.0,
        rows=1024, ring_columns=4096,
    ))
    assert legacy.anchor_banded(79_800.0) is None
    banded = _banded_grid()
    assert banded.anchor_banded(float("nan")) is None
    assert banded.anchor_banded(-1.0) is None
    assert banded.anchor_banded(0.0) is None


# --- session-level: realistic-price boot backfill through the WS route ---------------


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


_MID = 79_800.0
_MINUTE = 60 * 10**9


async def _realistic_backfill(symbol: str, *, max_cols: int, now_ns: int) -> list[dict]:
    """Four 1 m candles at a REALISTIC BTC price (~$79.8k), not the nominal frame."""
    base = 1_752_710_400_000_000_000
    rows = []
    for i in range(4):
        rows.append({
            "t0_ns": base + i * _MINUTE,
            "o": _MID + i * 10.0, "h": _MID + 40.0 + i * 10.0,
            "l": _MID - 40.0 + i * 10.0, "c": _MID + 20.0 + i * 10.0,
            "volume": 100.0 + i,
            "buy_volume": 60.0, "sell_volume": 40.0 + i,
        })
    return rows


def _make_hub(max_sessions: int = 2):
    registry: dict[str, FakeFeed] = {}
    hub = FeedHub(
        feed_factory=lambda symbol: registry.setdefault(symbol, FakeFeed(symbol)),
        backfill_fn=_realistic_backfill,
        backfill_max_cols=16,
        max_sessions=max_sessions,
    )
    app = FastAPI()
    flowmap_ws.register(app, AppDeps(), hub=hub)
    return hub, registry, TestClient(app)


def _subscribe_frame(symbol: str = "BTCUSDT", band: str = "wide") -> bytes:
    return wire.encode(events.Subscribe(
        market="crypto", symbol=symbol, mode="live", band=band))


def _recv(ws, *, deadline_s: float = 5.0, until=None) -> list:
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


@pytest.fixture
def offline(monkeypatch):
    monkeypatch.setenv("SHOWME_WS_REQUIRE_ORIGIN", "0")
    monkeypatch.delenv("SHOWME_AUTH_TOKEN", raising=False)
    yield


def test_banded_boot_backfill_survives_realistic_price(offline):
    """REGRESSION: backfill at a price far from the nominal $100 frame.

    Pre-fix this handshake arrived with ZERO synth columns (the converter
    mapped every candle outside the row window and returned None) and no
    history badge — a silent cold start on every realistic instrument.
    """
    _hub, _registry, client = _make_hub()
    with client.websocket_connect("/ws/flowmap") as ws:
        ws.send_bytes(_subscribe_frame("BTCUSDT", band="wide"))
        msgs = _recv(ws, until=lambda ms: any(
            isinstance(m, events.Marker) for m in ms))
        hello = msgs[0]
        assert isinstance(hello, events.Hello)
        assert hello.capability.get("history") == "reconstructed"
        # Anchored frame: p0 near the realistic mid, coarse frozen multiple.
        ep = hello.epoch_params
        assert ep.tick_multiple > 1
        span = ep.rows * ep.tick * ep.tick_multiple
        # Coverage guarantee (snapped re-check): the frame covers the whole
        # requested +-50% band around the reference mid.
        assert ep.p0 + span >= _MID * 1.5 - ep.tick * ep.tick_multiple
        assert ep.p0 <= _MID

        depths = [m for m in msgs if isinstance(m, events.DepthColumn)]
        bars = [m for m in msgs if isinstance(m, events.BarColumn)]
        assert len(depths) == 16 and len(bars) == 16
        assert all(d.mode == events.MODE_SYNTH_PROFILE for d in depths)
        assert all(d.epoch == ep.epoch for d in depths)
        starts = [m for m in msgs if isinstance(m, events.EpochStart)]
        assert len(starts) == 1 and starts[0].epoch_params.p0 == ep.p0


def test_banded_live_books_do_not_storm_epochs(offline):
    """REGRESSION: live book updates near the anchor must not re-anchor."""
    hub, registry, client = _make_hub()
    with client.websocket_connect("/ws/flowmap") as ws:
        ws.send_bytes(_subscribe_frame("BTCUSDT", band="wide"))
        snapshot = _recv(ws, until=lambda ms: any(
            isinstance(m, events.Marker) for m in ms))
        hello = snapshot[0]
        assert isinstance(hello, events.Hello)

        feed = registry["BTCUSDT"]
        assert feed is not None
        t0 = 1_800_000_000_000_000_000
        for i in range(40):
            wiggle = (i % 9 - 4) * 30.0  # +- $120 around the anchor
            feed.push(BookUpdate(
                ts_ns=t0 + i * 250_000_000,
                bids={_MID + wiggle - 1.0: 1.5},
                asks={_MID + wiggle + 1.0: 2.5},
                from_snapshot=True,
            ))
            feed.push(AggTrade(
                ts_ns=t0 + i * 250_000_000 + 1_000_000,
                price=_MID + wiggle, qty=0.01, is_buyer_maker=bool(i % 2),
            ))
        live = _recv(ws, deadline_s=5.0, until=lambda ms: sum(
            isinstance(m, events.DepthColumn) and m.mode == events.MODE_L2
            for m in ms) >= 20)
        starts = [m for m in live if isinstance(m, events.EpochStart)]
        live_cols = [m for m in live
                     if isinstance(m, events.DepthColumn) and m.mode == events.MODE_L2]
        assert len(live_cols) >= 20
        assert all(s.epoch_params.p0 == hello.epoch_params.p0 for s in starts)
        assert hub.live_feed_count == 1
