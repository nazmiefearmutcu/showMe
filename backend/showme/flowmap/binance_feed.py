"""Binance public order-book feed with official snapshot+diff synchronization.

Port/strip of the crypto feed concept from the FlowMap reference, rebuilt on
the public Binance SPOT endpoints (no keys):

- REST snapshot ``GET /api/v3/depth?symbol=X&limit=1000``
- combined WS ``wss://stream.binance.com:9443/stream?streams=<lc>@depth@100ms/<lc>@aggTrade/<lc>@kline_1s``

The official Binance synchronization algorithm (docs "Syncing from the
order book snapshot"):

1. Open the WS and BUFFER every ``depthUpdate`` diff event.
2. Fetch the REST snapshot; note its ``lastUpdateId``.
3. Drop buffered events where ``u`` <= ``lastUpdateId``.
4. The first applied diff must satisfy ``U`` <= ``lastUpdateId+1`` <= ``u``.
5. Subsequent diffs are applied in order: each level ``[price, qty]`` sets
   the quantity (``qty`` == 0 deletes the level); a diff whose ``U`` is not
   ``lastUpdateId + 1`` means data was lost -> RESYNC from a fresh snapshot.

Emits (as an async iterator the session consumes):
- :class:`BookUpdate` — the full current book as ``dict price -> qty`` for
  both sides (rebuilt after every applied diff or snapshot),
- :class:`AggTrade` — ``(price, qty, is_buyer_maker)``,
- :class:`KlineTick` — 1 s kline aggregates,
- :class:`FeedStateEvent` — ``live`` / ``degraded`` / ``reconnecting``
  transitions (the session converts these to wire Status messages).

Crash policy: any transport/protocol failure marks the feed ``degraded``
(one FeedStateEvent), waits an exponential backoff (base 1 s, cap 15 s) and
reconnects with a fresh snapshot. The backoff resets to base once a
connection re-syncs. The WS transport and the REST getter are INJECTABLE so
tests never touch the network (mirror of showme.streams' transport seam).
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

LOG = logging.getLogger("showme.flowmap.feed")

REST_BASE = "https://api.binance.com/api/v3"
WS_STREAM_URL = (
    "wss://stream.binance.com:9443/stream?streams="
    "{lc}@depth@100ms/{lc}@aggTrade/{lc}@kline_1s"
)

DEFAULT_BACKOFF_BASE_S = 1.0
DEFAULT_BACKOFF_CAP_S = 15.0

# exchangeInfo tickSize cache: symbol -> (expires_monotonic_ns, tick)
_TICK_CACHE_TTL_NS = 24 * 3600 * 10**9
_TICK_CACHE: dict[str, tuple[int, float]] = {}


# --- feed events -----------------------------------------------------------------


@dataclass(slots=True)
class BookUpdate:
    """Full current book state after a snapshot or a diff application."""

    ts_ns: int
    bids: dict[float, float]  # price -> qty
    asks: dict[float, float]
    from_snapshot: bool = False


@dataclass(slots=True)
class AggTrade:
    ts_ns: int
    price: float
    qty: float
    is_buyer_maker: bool


@dataclass(slots=True)
class KlineTick:
    t0_ms: int
    o: float
    h: float
    l: float
    c: float
    volume: float
    closed: bool


@dataclass(slots=True)
class FeedStateEvent:
    """Feed liveness transition; the session converts it to wire Status."""

    state: str  # "live" | "degraded" | "reconnecting"


# --- symbol / tick helpers ---------------------------------------------------------


def normalize_binance_symbol(symbol: str) -> str:
    """Mirror showMe's crypto normalization: accept ``BTCUSDT``/``BTC/USDT``
    (and ``BTC-USDT``) and produce the exchange-style uppercased pair."""
    cleaned = "".join(ch for ch in str(symbol or "").strip().upper() if ch.isalnum())
    return cleaned


def fallback_tick(price: float) -> float:
    """Fallback tick when exchangeInfo is unavailable: round the price to
    4 significant figures and divide by 1e5 (contract rule)."""
    if not math.isfinite(price) or price <= 0.0:
        return 0.01
    sig4 = float(f"{price:.3e}")
    tick = sig4 / 1e5
    return tick if math.isfinite(tick) and tick > 0.0 else 0.01


async def fetch_tick_size(
    symbol: str,
    rest_get: Callable[[str, dict[str, Any]], Awaitable[Any]],
    *,
    clock: Callable[[], int] = time.monotonic_ns,
) -> float:
    """``exchangeInfo`` tickSize for ``symbol``, cached per symbol (24 h TTL).

    Falls back to the generic 0.01 floor when exchangeInfo fails (the
    per-price fallback rule lives in :func:`fallback_tick`, applied by the
    session once it has seen a real price).
    """
    sym = normalize_binance_symbol(symbol)
    now = clock()
    cached = _TICK_CACHE.get(sym)
    if cached is not None and cached[0] > now:
        return cached[1]
    try:
        info = await rest_get("/exchangeInfo", {"symbol": sym})
        tick = float(info["symbols"][0]["filters"][0]["tickSize"])
        if not (math.isfinite(tick) and tick > 0.0):
            raise ValueError(f"bad tickSize {tick!r}")
    except Exception as exc:  # noqa: BLE001 — fallback is the contract
        LOG.warning("exchangeInfo tickSize failed for %s (%s); fallback", sym, exc)
        return 0.01
    _TICK_CACHE[sym] = (now + _TICK_CACHE_TTL_NS, tick)
    return tick


def cache_tick_size(symbol: str, tick: float, *, clock: Callable[[], int] = time.monotonic_ns) -> None:
    """Pre-warm (or correct) the tick cache — used to store the fallback tick
    derived from a real price once the feed has seen one."""
    sym = normalize_binance_symbol(symbol)
    if math.isfinite(tick) and tick > 0.0:
        _TICK_CACHE[sym] = (clock() + _TICK_CACHE_TTL_NS, tick)


async def fetch_klines(
    symbol: str,
    rest_get: Callable[[str, dict[str, Any]], Awaitable[Any]],
    *,
    interval: str = "1m",
    limit: int = 1024,
    end_time_ms: int | None = None,
) -> list[dict[str, Any]]:
    """Recent klines for backfill: Candle-compatible dicts with the taker
    split (``buy_volume`` = taker buy base volume, ``sell_volume`` =
    remainder). Best-effort: any failure returns ``[]`` (cold start)."""
    sym = normalize_binance_symbol(symbol)
    params: dict[str, Any] = {"symbol": sym, "interval": interval, "limit": int(limit)}
    if end_time_ms is not None:
        params["endTime"] = int(end_time_ms)
    try:
        rows = await rest_get("/klines", params)
    except Exception as exc:  # noqa: BLE001 — backfill is best-effort
        LOG.warning("klines fetch failed for %s (%s); cold start", sym, exc)
        return []
    out: list[dict[str, Any]] = []
    for row in rows or []:
        try:
            t0_ms = int(row[0])
            o, h, l, c = (float(row[i]) for i in (1, 2, 3, 4))
            volume = float(row[5])
        except (IndexError, TypeError, ValueError):
            continue
        if not all(math.isfinite(v) for v in (o, h, l, c, volume)):
            continue
        # The taker split is OPTIONAL: an unparsable buy volume keeps the
        # candle with no split instead of dropping real OHLCV data.
        try:
            buy_volume = float(row[9])
        except (IndexError, TypeError, ValueError):
            buy_volume = None
        out.append({
            "t0_ns": t0_ms * 1_000_000,
            "o": o, "h": h, "l": l, "c": c,
            "volume": volume,
            "buy_volume": buy_volume if (buy_volume is not None and math.isfinite(buy_volume)) else None,
            "sell_volume": (volume - buy_volume)
            if (buy_volume is not None and math.isfinite(buy_volume) and volume >= buy_volume) else None,
        })
    return out


# --- the feed ----------------------------------------------------------------------


class _ResyncNeeded(Exception):
    """Internal: diff continuity broke; a fresh snapshot is required."""


RestGet = Callable[[str, dict[str, Any]], Awaitable[Any]]
Transport = Callable[[str], AsyncIterator[str | bytes]]


async def _default_rest_get(path: str, params: dict[str, Any]) -> Any:
    import httpx

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(REST_BASE + path, params=params)
        resp.raise_for_status()
        return resp.json()


async def _default_transport(url: str) -> AsyncIterator[str | bytes]:
    """Prod WS transport: the ``websockets`` package (lazy import so the
    module parses without the dep; tests inject a fake transport)."""
    import websockets

    async with websockets.connect(url, ping_interval=15) as conn:
        async for raw in conn:
            yield raw


@dataclass(slots=True)
class _Snapshot:
    last_update_id: int
    bids: dict[float, float]
    asks: dict[float, float]


class BinanceBookFeed:
    """Async-iterator feed of BookUpdate / AggTrade / KlineTick events.

    The feed owns its reconnect loop (crash -> ``degraded`` status ->
    exponential backoff, cap 15 s). ``events()`` terminates after
    :meth:`stop` (and the current backoff sleep is cut short).
    """

    def __init__(
        self,
        symbol: str,
        *,
        transport: Transport | None = None,
        rest_get: RestGet | None = None,
        clock: Callable[[], int] = time.time_ns,
        backoff_base_s: float = DEFAULT_BACKOFF_BASE_S,
        backoff_cap_s: float = DEFAULT_BACKOFF_CAP_S,
    ) -> None:
        self.symbol = normalize_binance_symbol(symbol)
        if not self.symbol:
            raise ValueError("symbol must be non-empty")
        self._transport = transport or _default_transport
        self._rest_get = rest_get or _default_rest_get
        self._clock = clock
        self._backoff_base_s = float(backoff_base_s)
        self._backoff_cap_s = float(backoff_cap_s)

        self.bids: dict[float, float] = {}
        self.asks: dict[float, float] = {}
        self.last_update_id: int | None = None
        self.synced = False
        self.state = "reconnecting"
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()  # cuts a backoff sleep short on stop()
        self._backoff_s = self._backoff_base_s

    # -- lifecycle ---------------------------------------------------------------

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    @property
    def stopping(self) -> bool:
        return self._stop.is_set()

    def consume_backoff(self) -> float:
        """Current backoff, then double it (cap); used by the crash path."""
        value = self._backoff_s
        self._backoff_s = min(self._backoff_s * 2.0, self._backoff_cap_s)
        return value

    def _reset_backoff(self) -> None:
        self._backoff_s = self._backoff_base_s

    async def events(self) -> AsyncIterator[BookUpdate | AggTrade | KlineTick | FeedStateEvent]:
        """Yield feed events forever, reconnecting with backoff on crashes."""
        while not self.stopping:
            self.synced = False
            try:
                async for ev in self._stream_once():
                    yield ev
                # Transport exhausted cleanly (server closed): treat as crash.
                raise ConnectionError("binance stream closed")
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — any crash degrades + reconnects
                if self.stopping:
                    return
                LOG.warning(
                    "binance feed %s crashed; degraded, reconnecting in next backoff",
                    self.symbol,
                )
                yield FeedStateEvent(state="degraded")
            if self.stopping:
                return
            delay = self.consume_backoff()
            yield FeedStateEvent(state="reconnecting")
            await self._sleep_backoff(delay)

    async def _sleep_backoff(self, delay: float) -> None:
        stop_task = asyncio.create_task(self._stop.wait())
        sleep_task = asyncio.create_task(asyncio.sleep(delay))
        _done, _pending = await asyncio.wait(
            {stop_task, sleep_task}, return_when=asyncio.FIRST_COMPLETED
        )
        for t in (stop_task, sleep_task):
            if not t.done():
                t.cancel()
            else:
                t.exception()  # retrieve, never leak

    # -- one connection ------------------------------------------------------------

    async def _stream_once(
        self,
    ) -> AsyncIterator[BookUpdate | AggTrade | KlineTick | FeedStateEvent]:
        url = WS_STREAM_URL.format(lc=self.symbol.lower())
        buffered: list[dict[str, Any]] = []
        snapshot_task: asyncio.Task | None = None

        async for raw in self._transport(url):
            if self.stopping:
                return
            try:
                data = json.loads(raw)
            except (TypeError, ValueError) as exc:
                raise ConnectionError(f"unparsable stream frame: {exc}") from exc
            stream = str(data.get("stream", ""))
            payload = data.get("data", data)
            event = str(payload.get("e", ""))

            if event == "depthUpdate" or stream.endswith("@depth@100ms"):
                if not self.synced:
                    buffered.append(payload)
                    if snapshot_task is None:
                        snapshot_task = asyncio.create_task(self._fetch_snapshot())
                    if snapshot_task.done():
                        self._install_snapshot(snapshot_task.result())
                        leftover = self._drain_buffer(buffered)
                        if leftover:
                            # Snapshot too old to bridge the buffered window.
                            raise _ResyncNeeded("snapshot cannot bridge buffered diffs")
                        buffered = []
                        yield self._book_update(from_snapshot=True)
                        yield FeedStateEvent(state="live")
                    continue
                self._apply_diff(payload)
                yield self._book_update()
            elif event == "aggTrade" or stream.endswith("@aggTrade"):
                yield _parse_agg_trade(payload, self._clock)
            elif event == "kline" or stream.endswith("@kline_1s"):
                tick = _parse_kline(payload)
                if tick is not None:
                    yield tick
            # unknown stream names: ignored (forward compat)

    async def _fetch_snapshot(self) -> _Snapshot:
        data = await self._rest_get("/depth", {"symbol": self.symbol, "limit": 1000})
        bids = {float(p): float(q) for p, q in data.get("bids", [])}
        asks = {float(p): float(q) for p, q in data.get("asks", [])}
        return _Snapshot(last_update_id=int(data["lastUpdateId"]), bids=bids, asks=asks)

    def _install_snapshot(self, snapshot: _Snapshot) -> None:
        self.bids = dict(snapshot.bids)
        self.asks = dict(snapshot.asks)
        self.last_update_id = snapshot.last_update_id
        self.synced = True
        self._reset_backoff()

    def _drain_buffer(self, buffered: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Official steps 3-4: drop stale diffs, require the bridging diff,
        apply buffered diffs in order. Returns events that failed to bridge
        (non-empty means the snapshot was too old and a resync is needed)."""
        assert self.last_update_id is not None
        remaining: list[dict[str, Any]] = []
        applied = False
        for diff in buffered:
            u = int(diff["u"])
            if u <= self.last_update_id:
                continue  # stale
            if not applied:
                if int(diff["U"]) > self.last_update_id + 1:
                    remaining.append(diff)  # bridge not found yet / impossible
                    continue
                self._apply_levels(diff)
                applied = True
                continue
            if int(diff["U"]) != self.last_update_id + 1:
                remaining.append(diff)
                continue
            self._apply_levels(diff)
        return remaining

    def _apply_diff(self, diff: dict[str, Any]) -> None:
        assert self.last_update_id is not None
        u = int(diff["u"])
        if u <= self.last_update_id:
            return  # stale duplicate
        if int(diff["U"]) > self.last_update_id + 1:
            raise _ResyncNeeded(
                f"diff gap: U={diff['U']} > last_update_id+1={self.last_update_id + 1}"
            )
        self._apply_levels(diff)

    def _apply_levels(self, diff: dict[str, Any]) -> None:
        for level in diff.get("b", diff.get("bids", [])):
            price, qty = float(level[0]), float(level[1])
            if qty == 0.0:
                self.bids.pop(price, None)
            else:
                self.bids[price] = qty
        for level in diff.get("a", diff.get("asks", [])):
            price, qty = float(level[0]), float(level[1])
            if qty == 0.0:
                self.asks.pop(price, None)
            else:
                self.asks[price] = qty
        self.last_update_id = int(diff["u"])

    def _book_update(self, *, from_snapshot: bool = False) -> BookUpdate:
        return BookUpdate(
            ts_ns=self._clock(),
            bids=dict(self.bids),
            asks=dict(self.asks),
            from_snapshot=from_snapshot,
        )


# --- stream payload parsers (module-level for testability) --------------------------


def _parse_agg_trade(payload: dict[str, Any], clock: Callable[[], int]) -> AggTrade:
    return AggTrade(
        ts_ns=int(payload.get("T", payload.get("E", clock() // 1_000_000))) * 1_000_000,
        price=float(payload["p"]),
        qty=float(payload["q"]),
        is_buyer_maker=bool(payload["m"]),
    )


def _parse_kline(payload: dict[str, Any]) -> KlineTick | None:
    k = payload.get("k")
    if not isinstance(k, dict):
        return None
    try:
        return KlineTick(
            t0_ms=int(k["t"]),
            o=float(k["o"]),
            h=float(k["h"]),
            l=float(k["l"]),
            c=float(k["c"]),
            volume=float(k["v"]),
            closed=bool(k.get("x", False)),
        )
    except (KeyError, TypeError, ValueError):
        return None
