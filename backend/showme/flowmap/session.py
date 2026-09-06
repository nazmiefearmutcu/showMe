"""Session lifecycle: per-client TX queues, per-symbol sessions, feed hub.

Simplified port of ``flowmap_server.core.session`` sized for the sidecar:

- :class:`ClientTx` — per-client bounded send queue of pre-encoded frames,
  drained (FIFO) up to 256 KiB per WS frame every 50 ms. Non-protected
  frames beyond the queue cap are dropped oldest-first (recoverable via
  ``HistoryRequest``); snapshot frames are protected and never evicted.
- :class:`FlowSession` — one live Binance feed + one :class:`Grid` per
  ``(symbol, band)`` key. Attach returns the pre-encoded snapshot:
  ``Hello`` -> ``EpochStart`` for every distinct epoch in the snapshot ->
  the last <=512 finalized depth+bar columns chunked <=64 columns per frame
  -> gap ``Marker``s in range -> current ``BBO``. Live events broadcast to
  every attached client; BBO comes from the book top on every column flush;
  a mid that exits the central 70 % of the span re-anchors (epoch bump +
  ``EpochStart`` broadcast BEFORE any new-epoch column). A crashed feed is
  the feed's own reconnect loop; its ``FeedStateEvent`` transitions are
  broadcast as wire ``Status``.
- :class:`FeedHub` — refcounts sessions by key and enforces the contract's
  max of 2 concurrent live feeds. Unsubscribe or last disconnect tears the
  feed down immediately (no grace period — the sidecar is loopback-only).

Everything is asyncio, single-threaded, no locks: attach/snapshot/broadcast
never await between observing grid state and enqueueing, so per-client
frame order is exactly stream order.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any

import numpy as np

from . import events, wire
from .binance_feed import AggTrade, BookUpdate, FeedStateEvent, KlineTick
from .grid import Candle, FinalizedColumn, Grid, GridCfg, columns_from_candles

__all__ = [
    "ClientTx",
    "FeedHub",
    "FlowSession",
    "SessionLimitError",
    "canonical_band",
]

LOG = logging.getLogger("showme.flowmap.session")

# --- contract constants ----------------------------------------------------------
SNAPSHOT_COLS = 512       # last N finalized columns in the attach snapshot
SNAPSHOT_CHUNK_COLS = 64  # <= N columns per snapshot WS frame
HISTORY_MAX_COLS = 256    # per-HistoryRequest clamp
_TX_QUEUE_CAP = 2000      # per-client queued frames (drop-oldest, non-protected)
_TAPE_CAP = 500           # tape depth kept for capability honesty (not replayed)

_T_MAX = 2**63 - 1
_NAN = float("nan")

# Grid geometry (contract): linear scale, 1024 rows, 250 ms columns, f16 ring.
GRID_ROWS = 1024
GRID_DT_NS = 250_000_000
RING_COLUMNS = 4096
_NOMINAL_P0 = 100.0  # re-anchored to the real mid on the first book

# Price-grid coverage presets ("native | wide | full | deep"), mirroring
# upstream core/session.py BandSpec: percentage coverage around the reference
# mid as (band_up, band_down) fractions. The tick_multiple is derived from the
# FIRST usable mid (grid.anchor_banded) and then FROZEN for the session, and
# re-anchors fire on a ±25% RATIO trip. ``native`` keeps the legacy fixed-span
# grid (central-70% rule). SIMPLIFICATION vs upstream: ``deep`` is linear here
# (upstream opts into the hybrid log-wing scale, which is not ported).
BANDS: dict[str, tuple[float, float] | None] = {
    "native": None,
    "wide": (0.5, 0.5),
    "full": (10.0, 1.0),
    "deep": (10.0, 0.99),
}
DEFAULT_BAND = "native"


def canonical_band(band: str | None) -> str:
    """Coerce a wire ``band`` to a known preset name (WS-boundary guard)."""
    return band if band in BANDS else DEFAULT_BAND


Clock = Callable[[], int]


# --- per-client bounded queue ------------------------------------------------------


class ClientTx:
    """Per-client bounded send queue of pre-encoded frames (simplified).

    ``offer`` enqueues one pre-encoded frame; ``protected`` frames (the
    attach snapshot) are exempt from the drop-oldest cap. ``drain`` pops
    frames FIFO up to ``max_bytes`` — always at least one frame when the
    queue is non-empty, so a single frame larger than the budget cannot
    wedge the queue.
    """

    def __init__(self, *, cap: int = _TX_QUEUE_CAP) -> None:
        self._q: deque[bytes] = deque()
        self._cap = max(1, cap)

    def __len__(self) -> int:
        return len(self._q)

    def offer(self, frame: bytes, *, protected: bool = False) -> None:
        if not protected and len(self._q) >= self._cap:
            self._q.popleft()  # drop-oldest; HistoryRequest can recover
        self._q.append(frame)

    def drain(self, max_bytes: int) -> list[bytes]:
        out: list[bytes] = []
        total = 0
        while self._q:
            frame = self._q[0]
            if out and total + len(frame) > max_bytes:
                break
            out.append(self._q.popleft())
            total += len(frame)
        return out


# --- session -----------------------------------------------------------------------

# async (symbol, *, max_cols, now_ns) -> candle dicts (binance_feed.fetch_klines shape)
BackfillFn = Callable[..., Awaitable[list[dict]]]


class FlowSession:
    """One live stream per (symbol, band): Binance feed + grid + clients."""

    def __init__(
        self,
        session_id: str,
        *,
        symbol: str,
        band: str,
        feed,
        grid: Grid,
        clock: Clock = time.monotonic_ns,
        wall_clock: Clock = time.time_ns,
        on_teardown: Callable[[FlowSession], None] | None = None,
    ) -> None:
        self.session_id = session_id
        self.symbol = symbol
        self.band = band
        self.feed = feed
        self.grid = grid
        self._clock = clock
        self._wall_clock = wall_clock
        self._on_teardown = on_teardown

        self.run_task: asyncio.Task | None = None
        self._started = False
        self._closed = False
        self._backfill_fn: BackfillFn | None = None
        self._backfill_max_cols = 0
        self._history_reconstructed = False

        self._clients: set[ClientTx] = set()
        self._last_col_seq: int | None = None  # dedup: grid may re-return a column
        self._feed_state = "reconnecting"
        self._bbo: events.BBO | None = None
        self._tape: deque[events.Trade] = deque(maxlen=_TAPE_CAP)
        self._markers: deque[events.Marker] = deque(maxlen=1024)

    # -- boot / lifecycle --------------------------------------------------------

    def set_backfill(self, fn: BackfillFn | None, max_cols: int) -> None:
        """Configure the injectable candle-backfill seam (boot time only)."""
        self._backfill_fn = fn
        self._backfill_max_cols = max_cols

    async def start(self) -> None:
        """Boot (backfill the cold ring) once, then start the feed task."""
        if self._started:
            return
        self._started = True
        await self._boot()
        if self._closed:
            return
        self.run_task = asyncio.create_task(
            self.run(), name=f"flowmap-session-{self.session_id}"
        )

    async def _boot(self) -> None:
        """Seed the ring with reconstructed candle history (cold subscribe).

        Any failure degrades to a clean cold start. On success the session
        advertises ``history: 'reconstructed'`` and a gap Marker sits at the
        reconstructed/live seam (inside the snapshot's marker window).
        """
        if self._backfill_fn is None or self._backfill_max_cols <= 0:
            return
        try:
            rows = await self._backfill_fn(
                self.symbol,
                max_cols=self._backfill_max_cols,
                now_ns=self._wall_clock(),
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            LOG.warning("backfill fetch failed; cold start for %s", self.session_id,
                        exc_info=True)
            return
        if not rows:
            return
        try:
            candles = [
                Candle(
                    t0_ns=int(r["t0_ns"]), o=float(r["o"]), h=float(r["h"]),
                    l=float(r["l"]), c=float(r["c"]), volume=float(r["volume"]),
                    buy_volume=r.get("buy_volume"), sell_volume=r.get("sell_volume"),
                )
                for r in rows
            ]
            anchor = None
            if candles and self.grid.cfg.band_up is not None:
                # Reference mid = newest close (<=1 candle stale): build the
                # percentage frame and freeze tick_multiple BEFORE the
                # reconstruction so backfill and live share one geometry.
                anchor = self.grid.anchor_banded(candles[-1].c)
            result = columns_from_candles(
                candles, self.grid.cfg, max_cols=self._backfill_max_cols,
                p0=anchor.p0 if anchor is not None else None,
                tick_multiple=anchor.tick_multiple if anchor is not None else None,
                epoch=anchor.epoch if anchor is not None else 0,
            )
            if result is None:
                return
            columns, epoch = result
            self.grid.preload(columns, [anchor if anchor is not None else epoch])
        except Exception:
            LOG.warning("backfill conversion failed; cold start for %s", self.session_id,
                        exc_info=True)
            return
        self._history_reconstructed = True
        gap = events.Marker(
            ts_ns=columns[-1].t0_ns + self.grid.cfg.dt_ns - 1,
            kind="gap",
            text=f"backfill seam: reconstructed history ends {columns[-1].t0_ns}",
        )
        self._markers.append(gap)
        LOG.info("session %s backfilled %d reconstructed columns", self.session_id,
                 len(columns))

    async def run(self) -> None:
        """Consume feed events into the grid and broadcast."""
        try:
            async for ev in self.feed.events():
                if isinstance(ev, BookUpdate):
                    self._on_book(ev)
                elif isinstance(ev, AggTrade):
                    self._on_trade(ev)
                elif isinstance(ev, FeedStateEvent):
                    self._set_feed_state(ev.state)
                elif isinstance(ev, KlineTick):
                    pass  # bars aggregate from aggTrades (contract); klines ignored
                else:  # forward compat: unknown feed events never kill the loop
                    LOG.debug("ignoring unknown feed event %s", type(ev).__name__)
        except asyncio.CancelledError:
            raise
        except Exception:
            LOG.exception("session %s run loop crashed", self.session_id)
            self._set_feed_state("degraded")

    def stop(self) -> None:
        """Tear down: cancel the consumer, stop the feed, drop clients."""
        self._closed = True
        stop_feed = getattr(self.feed, "stop", None)
        if stop_feed is not None:
            try:
                stop_feed()
            except Exception:  # teardown must not raise
                LOG.debug("feed.stop() raised during teardown", exc_info=True)
        if self.run_task is not None:
            self.run_task.cancel()
        self._clients.clear()

    # -- feed event handling -------------------------------------------------------

    def _on_book(self, ev: BookUpdate) -> None:
        cols = self.grid.on_book(
            ev.ts_ns,
            np.fromiter(ev.bids.keys(), dtype=np.float64, count=len(ev.bids)),
            np.fromiter(ev.bids.values(), dtype=np.float64, count=len(ev.bids)),
            np.fromiter(ev.asks.keys(), dtype=np.float64, count=len(ev.asks)),
            np.fromiter(ev.asks.values(), dtype=np.float64, count=len(ev.asks)),
        )
        self._emit_finalized(cols, ev)
        mid = self._mid_of(ev)
        if mid is not None:
            params = self.grid.maybe_reanchor(mid)
            if params is not None:
                # EpochStart FIRST: before any new-epoch column message (the
                # columns emitted above carry the old epoch).
                self._broadcast(wire.encode(
                    events.EpochStart(epoch=params.epoch, epoch_params=params)
                ), col=False)

    @staticmethod
    def _mid_of(ev: BookUpdate) -> float | None:
        if not ev.bids or not ev.asks:
            return None
        best_bid = max(ev.bids)
        best_ask = min(ev.asks)
        if best_bid <= 0.0 or best_ask <= 0.0:
            return None
        return (best_bid + best_ask) / 2.0

    def _emit_finalized(self, cols: list[FinalizedColumn], ev: BookUpdate) -> None:
        emitted = False
        for col in cols:
            # The grid re-returns the last column on a zero-span boundary
            # call — dedup by col_seq.
            if self._last_col_seq is not None and col.col_seq <= self._last_col_seq:
                continue
            self._last_col_seq = col.col_seq
            self._broadcast(wire.encode(self.grid.to_depth(col)), col=True)
            self._broadcast(wire.encode(col.bar), col=True)
            emitted = True
        if emitted:
            bbo = self._bbo_of(ev)
            if bbo is not None:
                self._bbo = bbo
                self._broadcast(wire.encode(bbo), col=False)

    @staticmethod
    def _bbo_of(ev: BookUpdate) -> events.BBO | None:
        if not ev.bids or not ev.asks:
            return None
        bid_px = max(ev.bids)
        ask_px = min(ev.asks)
        return events.BBO(
            ts_ns=ev.ts_ns,
            bid_px=bid_px, bid_sz=ev.bids[bid_px],
            ask_px=ask_px, ask_sz=ev.asks[ask_px],
        )

    def _on_trade(self, ev: AggTrade) -> None:
        # Contract bar semantics: vol_buy = qty where the maker is the SELLER
        # (``m`` == false -> buyer was the taker); vol_sell = ``m`` == true.
        side = events.SIDE_SELL if ev.is_buyer_maker else events.SIDE_BUY
        self.grid.on_trade(ev.ts_ns, ev.price, ev.qty, side)
        trade = events.Trade(
            ts_ns=ev.ts_ns, price=ev.price, size=ev.qty,
            side=side, side_src=events.SIDE_SRC_EXCHANGE, venue="binance",
        )
        self._tape.append(trade)
        self._broadcast(wire.encode(trade), col=False)

    def _set_feed_state(self, state: str) -> None:
        if state == self._feed_state:
            return
        self._feed_state = state
        self._broadcast(wire.encode(events.Status(
            feed_state=state,
            capability=self.capability(),
            latency_ms=0.0,
            clock_skew_ms=0.0,
        )), col=False)

    # -- clients / snapshot ---------------------------------------------------------

    @property
    def client_count(self) -> int:
        return len(self._clients)

    def capability(self) -> dict[str, object]:
        cap: dict[str, object] = {
            "depth": "L2" if self.feed.synced else "L2-snapshot",
            "trades": "aggTrade",  # tape availability
            "bbo": "native",
        }
        if self._history_reconstructed:
            cap["history"] = "reconstructed"
        return cap

    def attach(self, client: ClientTx) -> list[bytes]:
        """Register a client; return the pre-encoded snapshot frames.

        No await happens between snapshot capture and registration, so live
        broadcasts cannot interleave.
        """
        if self._closed:
            raise RuntimeError(f"session {self.session_id} is torn down")
        self._clients.add(client)
        return self._snapshot_frames()

    def detach(self, client: ClientTx) -> None:
        self._clients.discard(client)

    def _norm_seed(self) -> float:
        """p99 of the nonzero densities over the most recent <=64 columns."""
        cols = self.grid.history(_T_MAX, 64)
        if not cols:
            return 1.0
        vals = np.concatenate([c.bid for c in cols] + [c.ask for c in cols]).astype(np.float64)
        vals = vals[np.isfinite(vals) & (vals > 0.0)]
        if vals.size == 0:
            return 1.0
        seed = float(np.percentile(vals, 99.0))
        return seed if math.isfinite(seed) else 1.0

    def _epoch_start_msgs(self, epochs: set[int]) -> list[bytes]:
        return [
            wire.encode(events.EpochStart(
                epoch=e, epoch_params=self.grid.epoch_params_for(e)
            ))
            for e in sorted(epochs)
        ]

    def _snapshot_frames(self) -> list[bytes]:
        ep = self.grid.current_epoch_params()
        cols = self.grid.history(_T_MAX, SNAPSHOT_COLS)
        hello = events.Hello(
            protocol_version=wire.PROTO_VER,
            session_id=self.session_id,
            grid_epoch=ep.epoch,
            epoch_params=ep,
            capability=self.capability(),
            norm_seed=self._norm_seed(),
        )
        # Hello first, then EpochStart for EVERY distinct epoch appearing in
        # the snapshot's columns (plus the current one), ascending — the
        # client must hold params for each epoch before decoding its columns.
        announce = self._epoch_start_msgs({c.epoch for c in cols} | {ep.epoch})
        frames = [b"".join([wire.encode(hello), *announce])]
        for i in range(0, len(cols), SNAPSHOT_CHUNK_COLS):
            chunk = cols[i:i + SNAPSHOT_CHUNK_COLS]
            frames.append(
                b"".join(
                    wire.encode(self.grid.to_depth(c)) + wire.encode(c.bar) for c in chunk
                )
            )

        tail: list[bytes] = []
        if cols:
            lo, hi = cols[0].t0_ns, cols[-1].t0_ns + ep.dt_ns
            tail.extend(wire.encode(m) for m in self._markers if lo <= m.ts_ns < hi)
        if self._bbo is not None:
            tail.append(wire.encode(self._bbo))
        if tail:
            frames.append(b"".join(tail))
        return frames

    def handle_history(self, req: events.HistoryRequest) -> bytes:
        """Serve a HistoryRequest from the ring as ONE encoded frame (with
        the epochs the response references announced ahead of it)."""
        n = max(0, min(req.n_cols, HISTORY_MAX_COLS))
        cols = self.grid.history(req.before_t, n)
        ep = self.grid.current_epoch_params()
        markers: list[events.Marker] = []
        if cols:
            lo, hi = cols[0].t0_ns, cols[-1].t0_ns + ep.dt_ns
            markers = [m for m in self._markers if lo <= m.ts_ns < hi]
        resp = events.HistoryResponse(
            req_id=req.req_id,
            epoch=ep.epoch,
            oldest_available_t_ns=self.grid.oldest_retained_t0_ns() or 0,
            depth_cols=[self.grid.to_depth(c) for c in cols],
            bar_cols=[c.bar for c in cols],
            markers=markers,
            big_trades=[],
        )
        announce = self._epoch_start_msgs({c.epoch for c in cols})
        return b"".join([*announce, wire.encode(resp)])

    # -- broadcast -------------------------------------------------------------------

    def _broadcast(self, frame: bytes, *, col: bool) -> None:
        for client in self._clients:
            client.offer(frame, protected=False)


# --- hub --------------------------------------------------------------------------


class SessionLimitError(RuntimeError):
    """Raised when a new feed key would exceed the max concurrent feeds."""


class FeedHub:
    """Owns sessions keyed by (symbol, band); enforces the feed limit."""

    def __init__(
        self,
        *,
        feed_factory: Callable[[str], Any],
        tick_fn: Callable[[str], Awaitable[float]] | None = None,
        backfill_fn: BackfillFn | None = None,
        backfill_max_cols: int = 1024,
        clock: Clock = time.monotonic_ns,
        wall_clock: Clock = time.time_ns,
        max_sessions: int = 2,
    ) -> None:
        self._feed_factory = feed_factory
        self._tick_fn = tick_fn
        self._backfill_fn = backfill_fn
        self._backfill_max_cols = backfill_max_cols
        self._clock = clock
        self._wall_clock = wall_clock
        self._max_sessions = max(1, max_sessions)
        self._sessions: dict[tuple[str, str], FlowSession] = {}

    @property
    def live_feed_count(self) -> int:
        return len(self._sessions)

    def session_for(self, symbol: str, band: str | None = None) -> FlowSession | None:
        return self._sessions.get((symbol, canonical_band(band)))

    async def _grid_for(self, symbol: str, band: str) -> Grid:
        spec = BANDS[canonical_band(band)]
        tick = 0.01
        if self._tick_fn is not None:
            try:
                tick = float(await self._tick_fn(symbol))
            except Exception:  # noqa: BLE001 — grid falls back below
                tick = 0.01
        if not (math.isfinite(tick) and tick > 0.0):
            tick = 0.01
        step = tick * 1  # nominal placeholder frame; the real mid anchors it
        span = GRID_ROWS * step
        p0 = round((_NOMINAL_P0 - span / 2.0) / step) * step
        return Grid(GridCfg(
            tick=tick, tick_multiple=1, dt_ns=GRID_DT_NS,
            p0=p0, rows=GRID_ROWS, ring_columns=RING_COLUMNS, mode=events.MODE_L2,
            band_up=spec[0] if spec else None,
            band_down=spec[1] if spec else None,
        ))

    async def subscribe(self, sub: events.Subscribe, client: ClientTx) -> FlowSession:
        """Attach ``client`` to the session for ``sub``'s key, creating and
        starting it if needed (<= max_sessions distinct live feeds). The
        snapshot frames are enqueued into ``client`` before returning, so
        they precede every live broadcast."""
        from .binance_feed import normalize_binance_symbol

        symbol = normalize_binance_symbol(sub.symbol)
        if not symbol:
            raise ValueError("empty symbol")
        band = canonical_band(sub.band)
        key = (symbol, band)
        session = self._sessions.get(key)
        if session is None:
            if len(self._sessions) >= self._max_sessions:
                raise SessionLimitError(
                    f"feed limit reached ({self._max_sessions}); cannot open {key!r}"
                )
            feed = self._feed_factory(symbol)
            grid = await self._grid_for(symbol, band)
            session = FlowSession(
                f"flw:{symbol}:{band}:{uuid.uuid4().hex[:12]}",
                symbol=symbol, band=band, feed=feed, grid=grid,
                clock=self._clock, wall_clock=self._wall_clock,
                on_teardown=self._make_remover(key),
            )
            session.set_backfill(self._backfill_fn, self._backfill_max_cols)
            self._sessions[key] = session
        try:
            await session.start()
            frames = session.attach(client)
        except Exception:
            # A session that failed to start (or was torn down mid-boot) must
            # not stay registered as a live feed.
            if self._sessions.get(key) is session and session.client_count == 0:
                self._sessions.pop(key, None)
                session.stop()
            raise
        for frame in frames:
            # Snapshot frames are protected: cap eviction must never drop Hello.
            client.offer(frame, protected=True)
        return session

    async def unsubscribe(self, session: FlowSession, client: ClientTx) -> None:
        session.detach(client)
        if session.client_count == 0:
            # Contract: teardown that symbol's feed on the last unsubscribe.
            for key, other in list(self._sessions.items()):
                if other is session:
                    self._sessions.pop(key, None)
            session.stop()

    def _make_remover(self, key: tuple[str, str]) -> Callable[[FlowSession], None]:
        def _remove(_session: FlowSession) -> None:
            if self._sessions.get(key) is _session:
                del self._sessions[key]

        return _remove
