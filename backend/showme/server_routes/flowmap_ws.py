"""Binary WebSocket route ``/ws/flowmap`` for the FLW (FlowMap) pane.

Auth is EXACTLY the ``/ws/quote/{symbol}`` gate (mirror of
``showme.server_routes.websocket``): Origin must be present and allow-listed
in ``deps.ws_allowed_origins`` (else close 1008), and when
``SHOWME_AUTH_TOKEN`` is set the token must arrive via ``?token=``,
``X-ShowMe-Token``, or ``Sec-WebSocket-Protocol: showme.token.<v>`` — compared
with ``hmac.compare_digest`` (else close 4401).

After the gate the upstream FlowMap handshake applies (binary protocol):

- one connection owns one :class:`~showme.flowmap.session.ClientTx` and at
  most one session subscription; a second Subscribe replaces the first;
- ``Subscribe{market != "crypto"}`` → ``Status{feed_state:"closed"}`` +
  close 1003 (unsupported); a subscribe beyond the hub's live-feed limit →
  ``Status{feed_state:"closed"}`` + close 1013 (try again later);
- three concurrent pieces per connection, all torn down together in
  ``finally`` (no task leaks): the receive loop (decode dispatch — malformed
  messages drop the REST of that frame but never the connection), the flush
  loop (drains the ClientTx every 50 ms, <=256 KiB per WS frame), and the
  ping loop (~1 Hz ``Ping``, 30 s liveness timeout on silence);
- ``HistoryRequest`` is answered directly from the session ring (one
  pre-encoded frame; history must not contend with the live queue).

The :class:`~showme.flowmap.session.FeedHub` lives on
``app.state.flowmap_hub``; ``register`` wires the production Binance feed /
tick / klines seams unless a hub is supplied (tests inject offline fakes).
"""
from __future__ import annotations

import asyncio
import contextlib
import hmac
import logging
import os
import time

from fastapi import APIRouter, FastAPI, WebSocket, WebSocketDisconnect

from . import AppDeps

LOG = logging.getLogger("showme.server.flowmap_ws")

FLUSH_INTERVAL_S = 0.05  # 20 Hz drain cadence (upstream §6.2 band)
FLUSH_MAX_BYTES = 256 * 1024  # per-WS-frame cap
PING_INTERVAL_S = 1.0
# A send that cannot complete within this window means the peer is gone or
# black-holed: abort the connection rather than stalling the loops forever.
SEND_TIMEOUT_S = 10.0
# A connection that has sent us NOTHING (not even a Pong — the FlowMap client
# answers every server Ping) for this long is dead.
LIVENESS_TIMEOUT_S = 30.0

# WS close codes
_CLOSE_UNSUPPORTED = 1003  # market has no feed / bad subscribe
_CLOSE_TRY_AGAIN_LATER = 1013  # session (live-feed) limit reached


def _extract_ws_token(websocket: WebSocket) -> str | None:
    """Pull the bearer token from any of the WS-compatible channels.

    Verbatim mirror of ``showme.server_routes.websocket._extract_ws_token``
    (SEC-13): ``?token=`` query parameter, ``X-ShowMe-Token`` header, or
    ``Sec-WebSocket-Protocol: showme.token.<value>`` subprotocol.
    """
    qs_token = websocket.query_params.get("token")
    if qs_token:
        return qs_token
    hdr_token = websocket.headers.get("x-showme-token") or websocket.headers.get(
        "X-ShowMe-Token"
    )
    if hdr_token:
        return hdr_token
    protos = websocket.headers.get("sec-websocket-protocol", "")
    for proto in (p.strip() for p in protos.split(",")):
        if proto.startswith("showme.token."):
            return proto[len("showme.token.") :]
    return None


def register(app: FastAPI, deps: AppDeps, *, hub=None) -> None:
    """Mount ``/ws/flowmap``; create the production FeedHub on first use.

    A LOCAL router (not a module-level one) is deliberate: the endpoint
    resolves the hub off ``websocket.app.state`` at request time, so several
    apps built in one process (tests) never share a hub through a stale
    closure.
    """
    if hub is None:
        from ..flowmap.binance_feed import (
            BinanceBookFeed,
            _default_rest_get,
            fetch_klines,
            fetch_tick_size,
        )
        from ..flowmap.session import FeedHub

        async def _backfill_fn(symbol: str, *, max_cols: int, now_ns: int) -> list[dict]:
            return await fetch_klines(
                symbol, _default_rest_get, limit=max_cols, end_time_ms=now_ns // 1_000_000
            )

        hub = FeedHub(
            feed_factory=lambda symbol: BinanceBookFeed(symbol),
            tick_fn=lambda symbol: fetch_tick_size(symbol, _default_rest_get),
            backfill_fn=_backfill_fn,
        )
    app.state.flowmap_hub = hub
    router = APIRouter()

    @router.websocket("/ws/flowmap")
    async def ws_flowmap(websocket: WebSocket) -> None:
        # The auth gate runs BEFORE accept, exactly like /ws/quote: a bad
        # Origin is a 1008 policy violation, a bad token a 4401 unauthorized.
        origin = websocket.headers.get("origin")
        require_origin = os.environ.get(
            "SHOWME_WS_REQUIRE_ORIGIN", "1"
        ).strip().lower() not in {"0", "false", "no", "off"}
        if require_origin and not origin:
            await websocket.close(code=1008)
            return
        if origin is not None and origin not in deps.ws_allowed_origins:
            await websocket.close(code=1008)
            return
        expected_token = os.environ.get("SHOWME_AUTH_TOKEN")
        require_token = os.environ.get(
            "SHOWME_WS_REQUIRE_TOKEN", "1"
        ).strip().lower() not in {"0", "false", "no", "off"}
        if expected_token and require_token:
            provided = _extract_ws_token(websocket) or ""
            if not hmac.compare_digest(provided, expected_token):
                await websocket.close(code=4401)
                return
        await websocket.accept()
        hub = websocket.app.state.flowmap_hub
        connection = _FlowConnection(websocket, hub)
        await connection.run()

    app.include_router(router)


class _FlowConnection:
    """Per-connection state: send queue, current session, latency estimate.

    Port of the upstream ``api/ws.py`` connection shell sized for the sidecar.
    """

    def __init__(self, ws: WebSocket, hub) -> None:
        self._ws = ws
        self._hub = hub
        from ..flowmap.session import ClientTx

        self._client = ClientTx()
        self._session = None  # FlowSession | None
        self._send_lock = asyncio.Lock()
        self.latency_ms = 0.0
        self._last_recv_ns = time.monotonic_ns()

    # -- sending ---------------------------------------------------------------

    async def _send(self, data: bytes) -> None:
        async with self._send_lock:
            await asyncio.wait_for(self._ws.send_bytes(data), SEND_TIMEOUT_S)

    async def _flush_loop(self) -> None:
        try:
            while True:
                for frame in self._client.drain(FLUSH_MAX_BYTES):
                    await self._send(frame)
                await asyncio.sleep(FLUSH_INTERVAL_S)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — dead peer: abort, receive loop unwinds
            await self._abort()

    async def _ping_loop(self) -> None:
        from ..flowmap import events, wire

        try:
            while True:
                await asyncio.sleep(PING_INTERVAL_S)
                if time.monotonic_ns() - self._last_recv_ns > LIVENESS_TIMEOUT_S * 1e9:
                    LOG.warning("ws_flowmap peer silent %.0fs: aborting", LIVENESS_TIMEOUT_S)
                    await self._abort()
                    return
                await self._send(wire.encode(
                    events.Ping(server_send_ns=time.monotonic_ns())
                ))
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — dead peer: abort
            await self._abort()

    async def _abort(self) -> None:
        """Sender-side teardown (dead peer / failed send). Closing the socket
        unwinds the receive loop; ``run``'s finally releases the session."""
        with contextlib.suppress(Exception):
            await self._ws.close()

    # -- lifecycle ---------------------------------------------------------------

    async def run(self) -> None:
        tasks = (
            asyncio.create_task(self._flush_loop(), name="flowmap-ws-flush"),
            asyncio.create_task(self._ping_loop(), name="flowmap-ws-ping"),
        )
        try:
            await self._receive_loop()
        except WebSocketDisconnect:
            pass
        finally:
            for t in tasks:
                t.cancel()
            # Retrieve cancellations AND any send-vs-close race the loops
            # lost after our close(): swallowed here, never leaked.
            await asyncio.gather(*tasks, return_exceptions=True)
            await self._drop_session()

    async def _receive_loop(self) -> None:
        while True:
            message = await self._ws.receive()
            if message["type"] == "websocket.disconnect":
                return
            self._last_recv_ns = time.monotonic_ns()
            data = message.get("bytes")
            if data is None:
                # Text frame on a binary-only protocol: log, drop the frame,
                # keep the connection (a broken intermediary is not worth
                # killing a healthy stream over).
                LOG.warning("text WS frame on flowmap binary protocol: dropped")
                continue
            if not await self._handle_frame(data):
                return

    async def _drop_session(self) -> None:
        if self._session is not None:
            with contextlib.suppress(Exception):
                await self._hub.unsubscribe(self._session, self._client)
            self._session = None

    # -- dispatch ------------------------------------------------------------------

    async def _handle_frame(self, data: bytes) -> bool:
        """Dispatch every message batched in one frame; False = closed.

        Malformed input is LOGGED, not fatal: the offset is unrecoverable
        mid-frame, so the remainder of THIS frame is dropped and the loop
        resyncs on the next frame boundary.
        """
        from ..flowmap import wire

        offset = 0
        while offset < len(data):
            try:
                ev, offset = wire.decode(data, offset)
            except ValueError as exc:
                LOG.warning("malformed client frame (%s): dropping rest of frame", exc)
                return True
            if ev is None:
                continue  # unknown msg_type: skipped via payload_len
            try:
                if not await self._dispatch(ev):
                    return False
            except Exception:
                LOG.warning(
                    "flowmap dispatch error on %s: message dropped, connection kept",
                    type(ev).__name__,
                    exc_info=True,
                )
        return True

    async def _dispatch(self, ev: object) -> bool:
        from ..flowmap import events

        if isinstance(ev, events.Subscribe):
            return await self._subscribe(ev)
        if isinstance(ev, events.Unsubscribe):
            await self._drop_session()
        elif isinstance(ev, events.HistoryRequest):
            if self._session is None:
                LOG.debug("HistoryRequest before Subscribe: ignored")
            else:
                # One pre-encoded frame (EpochStarts + HistoryResponse), sent
                # directly — history must not contend with the live queue.
                await self._send(self._session.handle_history(ev))
        elif isinstance(ev, events.Pong):
            rtt_ns = time.monotonic_ns() - ev.echo_ns
            self.latency_ms = rtt_ns / 2 / 1e6
        else:
            # Seek/SetSpeed/Pause/Resume: replay transports only — no live
            # feed consumes them at this milestone; ignore quietly.
            LOG.debug("ignoring %s on live flowmap connection", type(ev).__name__)
        return True

    async def _subscribe(self, sub) -> bool:
        from ..flowmap.session import SessionLimitError

        # Only the crypto market has a feed here. Refuse honestly BEFORE
        # touching the hub so a bad market never occupies a feed slot.
        if sub.market != "crypto":
            LOG.warning("refused subscribe: market %r has no feed -> 1003", sub.market)
            await self._refuse("closed", _CLOSE_UNSUPPORTED)
            return False
        # A second Subscribe on the same connection replaces the first: the
        # detach happens BEFORE the new subscribe so an over-limit refusal
        # cannot leave the client attached to two sessions.
        await self._drop_session()
        try:
            self._session = await self._hub.subscribe(sub, self._client)
        except SessionLimitError:
            LOG.warning("refused subscribe: feed limit reached (%s:%s) -> 1013",
                        sub.market, sub.symbol)
            await self._refuse("closed", _CLOSE_TRY_AGAIN_LATER)
            return False
        except ValueError as exc:
            LOG.warning("refused subscribe: bad subscribe (%s:%s: %s) -> 1003",
                        sub.market, sub.symbol, exc)
            await self._refuse("closed", _CLOSE_UNSUPPORTED)
            return False
        return True

    async def _refuse(self, feed_state: str, code: int) -> None:
        from ..flowmap import events, wire

        status = events.Status(
            feed_state=feed_state,  # type: ignore[arg-type]
            capability={},
            latency_ms=0.0,
            clock_skew_ms=0.0,
        )
        await self._send(wire.encode(status))
        await self._ws.close(code=code)
