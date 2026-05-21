"""WebSocket route for symbol-level quote streaming.

Also exposes ``/api/stream/stats`` because both endpoints share the stream-hub
provider injected via ``AppDeps.get_stream_hub``.
"""
from __future__ import annotations

import contextlib
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, FastAPI, WebSocket, WebSocketDisconnect

from . import AppDeps

LOG = logging.getLogger("showme.server.websocket")


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
        origin = websocket.headers.get("origin")
        # Allow non-browser clients (no Origin header) so the Tauri sidecar
        # tester / pytest WS client still work; reject any explicitly-set
        # Origin that is not on the allowlist.
        if origin is not None and origin not in deps.ws_allowed_origins:
            await websocket.close(code=4403)
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
