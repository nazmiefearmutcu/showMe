"""WebSocket route for symbol-level quote streaming.

Also exposes ``/api/stream/stats`` because both endpoints share the stream-hub
provider injected via ``AppDeps.get_stream_hub``.
"""
from __future__ import annotations

import contextlib
import hmac
import logging
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, FastAPI, WebSocket, WebSocketDisconnect

from . import AppDeps

LOG = logging.getLogger("showme.server.websocket")


def _extract_ws_token(websocket: WebSocket) -> str | None:
    """SEC-13: pull the bearer token from any of the WS-compatible channels.

    Browser ``new WebSocket(url)`` API can't set arbitrary HTTP headers,
    so we accept the token via three transports (any one wins):
    1. ``?token=...`` query parameter (most common, easy from JS)
    2. ``X-ShowMe-Token`` header (Tauri shell can inject this)
    3. ``Sec-WebSocket-Protocol: showme.token.<value>`` subprotocol token
       (RFC 6455 standard; survives URL-stripping proxies)
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


def _empty_stream_stats_envelope() -> dict[str, Any]:
    """S07: honest empty envelope returned when no stream-hub provider is wired."""
    return {
        "ok": True,
        "hub_present": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stale_threshold_ms": 0,
        "totals": {
            "channel_count": 0,
            "subscriber_count": 0,
            "live_count": 0,
            "stale_count": 0,
            "reconnecting_count": 0,
            "error_count": 0,
            "dropped_tick_count": 0,
        },
        "channels": [],
    }


def register(app: FastAPI, deps: AppDeps) -> None:
    router = APIRouter()

    @router.get("/api/stream/stats")
    async def stream_stats() -> dict[str, Any]:
        """Return live stream-hub telemetry (S07 envelope).

        Never collapses to a no-op shape when a hub provider is wired —
        callers can always trust ``totals``/``channels`` to reflect reality.
        """
        if deps.get_stream_hub is None:
            return _empty_stream_stats_envelope()
        hub = deps.get_stream_hub()
        if hub is None:
            return _empty_stream_stats_envelope()
        try:
            stats = hub.stats()
        except Exception as exc:  # noqa: BLE001
            LOG.warning("hub.stats() raised: %s", exc)
            envelope = _empty_stream_stats_envelope()
            envelope["hub_present"] = True
            envelope["ok"] = False
            envelope["error"] = str(exc) or exc.__class__.__name__
            return envelope
        if not isinstance(stats, dict):
            envelope = _empty_stream_stats_envelope()
            envelope["hub_present"] = True
            envelope["ok"] = False
            envelope["error"] = "hub.stats() returned non-dict"
            return envelope
        stats["hub_present"] = True
        return stats

    @router.websocket("/ws/quote/{symbol}")
    async def ws_quote(websocket: WebSocket, symbol: str) -> None:
        """Round 29 — Symbol-level real-time quote stream."""
        # Validate symbol cheaply before doing any work.
        if not symbol or len(symbol) > 32 or not all(
            ch.isalnum() or ch in "._:=^-" for ch in symbol
        ):
            await websocket.close(code=4400)
            return
        # QA-fix: Origin header is now MANDATORY for the /ws/quote stream.
        # Previously a missing header was treated as "non-browser client" and
        # passed through, which let any local process bypass the CORS-style
        # allowlist. Browser/Tauri clients always send Origin; legitimate
        # internal test code can set SHOWME_WS_REQUIRE_ORIGIN=0 to opt out.
        origin = websocket.headers.get("origin")
        require_origin = os.environ.get(
            "SHOWME_WS_REQUIRE_ORIGIN", "1"
        ).strip().lower() not in {"0", "false", "no", "off"}
        if require_origin and not origin:
            LOG.warning("ws_quote %s rejected: missing Origin header", symbol)
            # 1008 = policy violation (RFC 6455). Tests assert this code.
            await websocket.close(code=1008)
            return
        if origin is not None and origin not in deps.ws_allowed_origins:
            LOG.warning(
                "ws_quote %s rejected: Origin %r not in allowlist", symbol, origin
            )
            await websocket.close(code=1008)
            return
        # SEC-13: AUTH gate. The HTTP auth_token_middleware only matches
        # /api/* paths, so /ws/quote was previously unauthenticated — any
        # local process could tap the live tick stream by knowing the port.
        # When SHOWME_AUTH_TOKEN is set we require a matching token via
        # query param, X-ShowMe-Token header, or Sec-WebSocket-Protocol
        # ``showme.token.<value>`` subprotocol. Browsers can only use the
        # query/subprotocol forms because the WebSocket constructor has no
        # custom-header API. Set SHOWME_WS_REQUIRE_TOKEN=0 to opt out in
        # internal test setups.
        expected_token = os.environ.get("SHOWME_AUTH_TOKEN")
        require_token = os.environ.get(
            "SHOWME_WS_REQUIRE_TOKEN", "1"
        ).strip().lower() not in {"0", "false", "no", "off"}
        if expected_token and require_token:
            provided = _extract_ws_token(websocket) or ""
            if not hmac.compare_digest(provided, expected_token):
                LOG.warning(
                    "ws_quote %s rejected: missing or invalid token", symbol
                )
                # 4401 = app-specific "unauthorized" (close codes 4000-4999
                # are reserved for application use per RFC 6455 §7.4.2).
                await websocket.close(code=4401)
                return
        await websocket.accept()
        hub = deps.get_stream_hub() if deps.get_stream_hub else None
        if hub is None:
            await websocket.send_json({"error": "stream hub unavailable"})
            await websocket.close()
            return
        try:
            sub = await hub.subscribe(symbol)
        except Exception as exc:  # noqa: BLE001
            await websocket.send_json({"error": str(exc)})
            await websocket.close()
            return
        async with sub as queue:
            try:
                while True:
                    tick = await queue.get()
                    await websocket.send_json(tick.to_dict())
            except WebSocketDisconnect:
                return
            except Exception as exc:  # noqa: BLE001
                LOG.warning("ws_quote %s: %s", symbol, exc)
                with contextlib.suppress(Exception):
                    await websocket.close()

    app.include_router(router)
