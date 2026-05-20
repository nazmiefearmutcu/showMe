"""Round 29 — Real-time quote streaming.

Two-stage design:

1. **Source** — produces raw `Tick` events.
    * Crypto symbols (`*USDT`, `*USD`) → Binance WS bridge.
    * Equity / FX → polling fallback that re-uses the existing
      `runFunction("DES", {symbol})` path so we get the same prices
      the WATCH pane already sees, just on a sub-second cadence.

2. **Hub** — fan-out manager that lets multiple WebSocket clients
   subscribe to the same symbol and receive a single underlying tick
   stream. Reference counts cleaned up on disconnect.

Pure-Python tick parsing (``parse_binance_ticker``) is unit tested
without a network. WebSocket transport is injectable so the hub can
run in tests with deterministic fake sources.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Literal
from collections.abc import AsyncIterator, Awaitable, Callable

import requests

from showme.crypto_aliases import is_crypto_symbol as _is_crypto_symbol

LOG = logging.getLogger("showme.streams")


# ── Value object ──────────────────────────────────────────────────────────


@dataclass
class Tick:
    symbol: str
    price: float
    change_pct: float | None = None
    volume: float | None = None
    bid: float | None = None
    ask: float | None = None
    ts: float = field(default_factory=time.time)
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Source contract ───────────────────────────────────────────────────────

SourceFactory = Callable[[str], "Source"]


class Source:
    """Yields `Tick` events for a single symbol.

    Implementations override ``run`` (an async generator). The hub calls
    ``stop()`` when no more subscribers exist; sources should respond by
    cancelling their internal loop.
    """

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol.upper()
        self._stop = asyncio.Event()

    async def run(self) -> AsyncIterator[Tick]:  # pragma: no cover — abstract
        if False:
            yield Tick(symbol=self.symbol, price=0.0)
        raise NotImplementedError

    def stop(self) -> None:
        self._stop.set()

    @property
    def stopping(self) -> bool:
        return self._stop.is_set()


# ── Binance bridge ────────────────────────────────────────────────────────


def parse_binance_ticker(payload: dict[str, Any]) -> Tick:
    """Normalize the ``!ticker@arr`` 24h ticker payload to a `Tick`."""
    sym = str(payload.get("s") or payload.get("symbol") or "").upper()
    price = float(payload.get("c") or payload.get("p") or 0.0)
    pct = payload.get("P") or payload.get("pricePercent") or 0.0
    change_pct = float(pct) if pct not in (None, "") else None
    vol = payload.get("v")
    volume = float(vol) if vol not in (None, "") else None
    bid = payload.get("b")
    ask = payload.get("a")
    ts = payload.get("E") or payload.get("eventTime")
    return Tick(
        symbol=sym,
        price=price,
        change_pct=change_pct,
        volume=volume,
        bid=float(bid) if bid not in (None, "") else None,
        ask=float(ask) if ask not in (None, "") else None,
        ts=float(ts) / 1000 if isinstance(ts, (int, float)) else time.time(),
        source="binance",
    )


def is_crypto_symbol(symbol: str) -> bool:
    return _is_crypto_symbol(symbol)


class BinanceWsSource(Source):
    """Connects to ``wss://stream.binance.com:9443/ws/<symbol>@ticker``."""

    URL_TEMPLATE = "wss://stream.binance.com:9443/ws/{stream}"

    def __init__(self, symbol: str, *, transport: Callable[[str], "WsConn"] | None = None) -> None:
        super().__init__(symbol)
        self._transport = transport or _default_ws_transport

    async def run(self) -> AsyncIterator[Tick]:  # pragma: no cover — IO heavy
        url = self.URL_TEMPLATE.format(stream=f"{self.symbol.lower()}@ticker")
        conn = self._transport(url)
        async for raw in conn:
            if self.stopping:
                break
            try:
                payload = json.loads(raw)
            except Exception as exc:  # noqa: BLE001
                LOG.debug("binance ws decode failed: %s", exc)
                continue
            yield parse_binance_ticker(payload)


class WsConn:  # pragma: no cover — Protocol marker
    def __aiter__(self) -> AsyncIterator[str]:
        raise NotImplementedError


class _WebsocketsTransport:
    """Round 30 — `websockets` package transport (prod default).

    Lazy-imports ``websockets`` so the streams module still parses on
    machines without that dep — tests inject a fake transport instead.
    """

    def __init__(self, url: str) -> None:
        self._url = url

    async def __aiter__(self) -> AsyncIterator[str]:
        try:
            import websockets  # type: ignore
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "websockets package not installed; pin it in pyproject "
                "or inject a transport"
            ) from exc
        async with websockets.connect(self._url, ping_interval=15) as conn:
            async for raw in conn:
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="replace")
                yield raw


def _default_ws_transport(url: str) -> WsConn:
    return _WebsocketsTransport(url)  # type: ignore[return-value]


class BinanceHybridSource(Source):
    """Try Binance WSS first; fall back to REST polling on SSL / network error.

    Some operator environments (corporate MITM proxies, custom root CAs,
    antivirus that injects its own cert chain) can break Binance's WSS
    handshake even when plain HTTPS works — verified on 2026-05-11 against
    a live macOS install. Without a fallback the live ``/ws/quote/{symbol}``
    stream goes silent and every crypto pane shows stale data forever.

    Strategy:
      1. Try ``BinanceWsSource``. If the first tick arrives, stay on WSS.
      2. If the WSS leg raises BEFORE the first tick (SSL handshake fail,
         DNS, connection refused, …) catch the error and switch to
         ``BinanceRestSource`` (5 s polling) for the rest of this run.
      3. If WSS yielded ticks but then errors out, the outer ``_pump``
         reconnect loop handles it — we propagate the exception so the
         backoff window kicks in instead of silently downgrading.

    Set ``SHOWME_DISABLE_WSS=1`` in the env to skip the WSS attempt and
    go straight to REST polling (useful for known-bad networks).
    """

    def __init__(
        self,
        symbol: str,
        *,
        rest_interval: float = 5.0,
        skip_wss: bool | None = None,
    ) -> None:
        super().__init__(symbol)
        self._rest_interval = rest_interval
        if skip_wss is None:
            skip_wss = os.environ.get("SHOWME_DISABLE_WSS", "").lower() in {"1", "true", "yes"}
        self._skip_wss = skip_wss

    async def run(self) -> AsyncIterator[Tick]:
        if not self._skip_wss:
            wss = BinanceWsSource(self.symbol)
            wss._stop = self._stop  # share the cancellation flag
            yielded_any = False
            try:
                async for tick in wss.run():
                    yielded_any = True
                    yield tick
                # WSS exhausted cleanly — let the outer pump decide whether
                # to reconnect or move on.
                return
            except Exception as exc:  # noqa: BLE001
                if yielded_any:
                    # Don't downgrade once we've proven WSS works for this
                    # symbol — propagate so the pump's backoff kicks in.
                    raise
                LOG.warning(
                    "binance WSS failed for %s (%s) — falling back to REST polling",
                    self.symbol,
                    exc,
                )
        # REST fallback (or explicit opt-in).
        rest = BinanceRestSource(self.symbol, interval=self._rest_interval, venue="spot")
        rest._stop = self._stop
        async for tick in rest.run():
            yield tick


class BinanceRestSource(Source):
    """Polls Binance's 24h ticker endpoint for crypto pairs.

    ``venue`` selects the endpoint explicitly. Per FUNC-01 P0: do NOT
    silently fall through from spot to futures — perpetuals trade at a
    basis vs spot (often ±0.1–0.5%, spiking to 2%+ during liquidation
    cascades), so a venue change must be a deliberate caller decision.
    """

    URL = "https://api.binance.com/api/v3/ticker/24hr"
    FUTURES_URL = "https://fapi.binance.com/fapi/v1/ticker/24hr"

    def __init__(
        self,
        symbol: str,
        *,
        interval: float = 5.0,
        venue: Literal["spot", "futures"] = "spot",
    ) -> None:
        super().__init__(symbol)
        self._interval = max(1.0, float(interval))
        self._venue = venue

    async def run(self) -> AsyncIterator[Tick]:
        fetch_fn = (
            fetch_binance_futures_24h_ticker
            if self._venue == "futures"
            else fetch_binance_24h_ticker
        )
        while not self.stopping:
            try:
                tick = await asyncio.to_thread(fetch_fn, self.symbol)
                yield tick
            except Exception as exc:  # noqa: BLE001
                LOG.debug(
                    "binance rest fetch failed for %s (%s): %s",
                    self.symbol,
                    self._venue,
                    exc,
                )
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
            except asyncio.TimeoutError:
                pass


def fetch_binance_24h_ticker(symbol: str) -> Tick:
    """Fetch a Binance SPOT 24h ticker. Raises on failure (no venue swap)."""
    payload = _fetch_binance_ticker_payload(symbol, futures=False)
    tick = parse_binance_ticker({
        "s": payload.get("symbol"),
        "c": payload.get("lastPrice"),
        "P": payload.get("priceChangePercent"),
        "v": payload.get("volume"),
        "b": payload.get("bidPrice"),
        "a": payload.get("askPrice"),
        "E": payload.get("closeTime"),
    })
    tick.source = "binance"
    return tick


def fetch_binance_futures_24h_ticker(symbol: str) -> Tick:
    """Fetch a Binance USDT-M futures 24h ticker. Caller must opt in."""
    payload = _fetch_binance_ticker_payload(symbol, futures=True)
    tick = parse_binance_ticker({
        "s": payload.get("symbol"),
        "c": payload.get("lastPrice"),
        "P": payload.get("priceChangePercent"),
        "v": payload.get("volume"),
        "b": payload.get("bidPrice"),
        "a": payload.get("askPrice"),
        "E": payload.get("closeTime"),
    })
    tick.source = "binance_futures"
    return tick


def _fetch_binance_ticker_payload(symbol: str, *, futures: bool) -> dict[str, Any]:
    response = requests.get(
        BinanceRestSource.FUTURES_URL if futures else BinanceRestSource.URL,
        params={"symbol": symbol.upper()},
        headers={"User-Agent": "showMe/1.0"},
        timeout=6,
    )
    response.raise_for_status()
    payload = response.json() or {}
    if payload.get("code") is not None and payload.get("lastPrice") in (None, ""):
        raise RuntimeError(str(payload.get("msg") or payload))
    return payload


# ── Polling fallback for non-crypto symbols ───────────────────────────────


class PollingSource(Source):
    """Re-uses ``runFunction("DES", {symbol})`` to poll a price."""

    def __init__(
        self,
        symbol: str,
        *,
        fetch: Callable[[str], Awaitable[dict[str, Any]]],
        interval: float = 5.0,
    ) -> None:
        super().__init__(symbol)
        self._fetch = fetch
        self._interval = max(0.5, float(interval))

    async def run(self) -> AsyncIterator[Tick]:
        while not self.stopping:
            try:
                payload = await self._fetch(self.symbol)
            except Exception as exc:  # noqa: BLE001
                LOG.debug("polling fetch failed for %s: %s", self.symbol, exc)
                payload = {}
            if payload:
                tick = self._normalize(payload)
                if tick is not None:
                    yield tick
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
            except asyncio.TimeoutError:
                pass

    def _normalize(self, payload: dict[str, Any]) -> Tick | None:
        return quote_tick_from_payload(payload, self.symbol, source="polling")


def quote_tick_from_payload(
    payload: dict[str, Any],
    symbol: str,
    *,
    source: str,
) -> Tick | None:
    """Extract a last-price tick from flat or DES FunctionResult payloads."""
    candidates = _quote_candidates(payload)
    price = first_number(candidates, [
        "regularMarketPrice",
        "currentPrice",
        "lastPrice",
        "last",
        "price",
        "previousClose",
    ])
    if price is None:
        return None
    pct = first_number(candidates, [
        "regularMarketChangePercent",
        "priceChangePercent",
        "change_pct",
    ])
    prev = first_number(candidates, [
        "previousClose",
        "previous_close",
        "regularMarketPreviousClose",
        "prev_close",
        "close_prev",
        "openPrice",
    ])
    if pct is None and prev not in (None, 0):
        try:
            pct = (float(price) / float(prev) - 1.0) * 100.0
        except Exception:  # noqa: BLE001
            pct = None
    volume = first_number(candidates, ["regularMarketVolume", "volume", "volume_24h"])
    bid = first_number(candidates, ["bid", "bidPrice"])
    ask = first_number(candidates, ["ask", "askPrice"])
    return Tick(
        symbol=symbol.upper(),
        price=float(price),
        change_pct=pct,
        volume=volume,
        bid=bid,
        ask=ask,
        source=source,
    )


def _quote_candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        out.append(payload)
        data = payload.get("data")
        if isinstance(data, dict):
            out.insert(0, data)
            extras = data.get("extras")
            if isinstance(extras, dict):
                raw = extras.get("raw")
                if isinstance(raw, dict):
                    out.insert(0, raw)
    return out


def first_number(candidates: list[dict[str, Any]], keys: list[str]) -> float | None:
    for candidate in candidates:
        for key in keys:
            value = candidate.get(key)
            if value in (None, ""):
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            return number
    return None


# ── Hub: per-symbol fan-out ──────────────────────────────────────────────


@dataclass
class _Channel:
    symbol: str
    source: Source
    queues: list[asyncio.Queue[Tick]] = field(default_factory=list)
    task: asyncio.Task | None = None
    last_tick: Tick | None = None


class StreamHub:
    """Multi-subscriber fan-out for symbol streams.

    Caller usage:

        async with hub.subscribe("BTCUSDT") as queue:
            tick = await queue.get()

    The hub starts a single ``Source`` per symbol the first time anybody
    subscribes; later subscribers attach a `Queue`. When the last subscriber
    disconnects the source is stopped and torn down.
    """

    def __init__(
        self,
        *,
        crypto_factory: SourceFactory | None = None,
        polling_factory: SourceFactory | None = None,
    ) -> None:
        self._channels: dict[str, _Channel] = {}
        self._lock = asyncio.Lock()
        self._crypto_factory = crypto_factory or (lambda s: BinanceRestSource(s))
        self._polling_factory = polling_factory

    def stats(self) -> dict[str, Any]:
        return {
            "channels": [
                {
                    "symbol": c.symbol,
                    "subscribers": len(c.queues),
                    "last_price": c.last_tick.price if c.last_tick else None,
                    "source": c.last_tick.source if c.last_tick else None,
                }
                for c in self._channels.values()
            ],
        }

    def _build_source(self, symbol: str) -> Source:
        if is_crypto_symbol(symbol):
            return self._crypto_factory(symbol)
        if self._polling_factory is None:
            raise RuntimeError(
                f"no source registered for non-crypto symbol {symbol}; "
                f"pass polling_factory=... when constructing StreamHub"
            )
        return self._polling_factory(symbol)

    async def subscribe(self, symbol: str) -> "Subscription":
        sym = symbol.upper()
        async with self._lock:
            channel = self._channels.get(sym)
            if channel is None:
                source = self._build_source(sym)
                channel = _Channel(symbol=sym, source=source)
                channel.task = asyncio.create_task(self._pump(channel))
                self._channels[sym] = channel
            queue: asyncio.Queue[Tick] = asyncio.Queue(maxsize=128)
            channel.queues.append(queue)
            if channel.last_tick is not None:
                # Replay last value so new subscribers get an immediate paint.
                queue.put_nowait(channel.last_tick)
            return Subscription(hub=self, symbol=sym, queue=queue)

    async def _pump(self, channel: _Channel) -> None:
        # Per PERF-04 P1 / FUNC-03 P1: wrap the source iterator in a reconnect
        # loop with exponential backoff so a transient upstream drop does not
        # silently freeze the channel forever. The first successful tick after
        # a (re)connect resets the backoff window.
        backoff = 1.0
        max_backoff = 60.0
        try:
            while not channel.source.stopping:
                got_tick = False
                try:
                    async for tick in channel.source.run():
                        got_tick = True
                        backoff = 1.0
                        channel.last_tick = tick
                        for q in list(channel.queues):
                            if q.full():
                                # Drop oldest — backpressure. Subscriber is too slow.
                                try:
                                    q.get_nowait()
                                except asyncio.QueueEmpty:
                                    pass
                            try:
                                q.put_nowait(tick)
                            except asyncio.QueueFull:
                                pass
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    LOG.warning(
                        "source for %s raised (reconnect in %.1fs): %s",
                        channel.symbol, backoff, exc,
                    )
                if channel.source.stopping or not channel.queues:
                    return
                # Source exhausted (Binance 24h disconnect, network blip).
                # Sleep with exponential backoff, then rebuild the source via
                # the same factory and try again.
                if not got_tick:
                    LOG.debug(
                        "source for %s ended without a tick; reconnect in %.1fs",
                        channel.symbol, backoff,
                    )
                try:
                    await asyncio.sleep(backoff)
                except asyncio.CancelledError:
                    raise
                backoff = min(backoff * 2, max_backoff)
                # Rebuild via the hub's factory chain so we get a fresh socket.
                try:
                    channel.source.stop()
                except Exception:  # noqa: BLE001
                    pass
                channel.source = self._build_source(channel.symbol)
        except asyncio.CancelledError:
            return
        finally:
            try:
                channel.source.stop()
            except Exception:  # noqa: BLE001
                pass

    async def _release(self, symbol: str, queue: asyncio.Queue[Tick]) -> None:
        async with self._lock:
            channel = self._channels.get(symbol)
            if channel is None:
                return
            try:
                channel.queues.remove(queue)
            except ValueError:
                pass
            if not channel.queues:
                channel.source.stop()
                if channel.task and not channel.task.done():
                    channel.task.cancel()
                    try:
                        await channel.task
                    except asyncio.CancelledError:
                        # Cooperative cancellation — expected and recoverable.
                        pass
                    except Exception as exc:  # noqa: BLE001
                        # Per PY-LINT-05 P1: log unexpected pump-task failures
                        # at warning level so cleanup oddities are visible.
                        LOG.warning("stream cleanup task for %s raised: %s", symbol, exc)
                self._channels.pop(symbol, None)


@dataclass
class Subscription:
    hub: StreamHub
    symbol: str
    queue: asyncio.Queue[Tick]

    async def __aenter__(self) -> asyncio.Queue[Tick]:
        return self.queue

    async def __aexit__(self, *_: Any) -> None:
        await self.hub._release(self.symbol, self.queue)


__all__ = [
    "BinanceHybridSource",
    "BinanceWsSource",
    "BinanceRestSource",
    "PollingSource",
    "Source",
    "StreamHub",
    "Subscription",
    "Tick",
    "fetch_binance_24h_ticker",
    "is_crypto_symbol",
    "parse_binance_ticker",
    "quote_tick_from_payload",
]
