"""Realtime quote snapshot + symbol-resolution routes."""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, FastAPI, Path as PathParam

from . import AppDeps


def _build_quote_envelope(
    *,
    ok: bool,
    data: dict[str, Any] | None,
    error: str | None,
    synthetic: bool = False,
) -> dict[str, Any]:
    """S07 — wrap a quote result with truthful UI/debug metadata.

    Keeps the legacy ``{ok, data, error}`` keys intact so existing callers
    continue to work; adds the observability fields the UI needs to render
    live / stale / offline state instead of guessing.
    """
    if ok and isinstance(data, dict):
        source_kind = data.get("source")
        return {
            "ok": True,
            "data": data,
            "cache_hit": False,
            "data_state": "ok",
            "transport_state": "snapshot",
            "freshness_ms": 0.0,
            "source_kind": source_kind,
            "degraded": False,
            "synthetic": bool(synthetic),
        }
    return {
        "ok": False,
        "error": error or "quote unavailable",
        "data": None,
        "cache_hit": False,
        "data_state": "unavailable",
        "transport_state": "offline",
        "freshness_ms": None,
        "source_kind": None,
        "degraded": True,
        "synthetic": bool(synthetic),
    }


def register(app: FastAPI, deps: AppDeps) -> None:
    from showme.server import _canonical_route_symbol, default_asset_class_name

    router = APIRouter()

    @router.get("/api/quote/{symbol}")
    async def quote_snapshot(
        symbol: str = PathParam(..., max_length=32, pattern=r"^[A-Za-z0-9._:=\-^]+$"),
    ) -> dict[str, Any]:
        """Fast last-price endpoint used by WATCH and quote streams.

        Per PERF-05 P1: a 5–15 s TTL is applied so concurrent panes
        requesting the same symbol within the window share one upstream
        provider call instead of fanning out N times.

        S07: response now carries truthful metadata —
        ``cache_hit``, ``data_state`` (ok|stale|unavailable),
        ``transport_state`` (snapshot|offline), ``freshness_ms``,
        ``source_kind``, ``degraded`` — so the UI can distinguish a live
        snapshot from a cached or failed one without guessing.
        """
        from showme.quotes import (
            QuoteFetchError,
            fetch_quote_snapshot,
            quote_cache_freshness_ms,
            quote_cache_get,
            quote_cache_set,
        )

        cached = quote_cache_get(symbol)
        if cached is not None:
            # Shallow-copy so cache stays clean — task: "Cached responses
            # must show cache_hit:true without mutating cached data
            # unexpectedly."
            response = dict(cached)
            response["cache_hit"] = True
            response["freshness_ms"] = quote_cache_freshness_ms(symbol)
            return response

        try:
            data = await asyncio.wait_for(fetch_quote_snapshot(symbol), timeout=5)
            payload = _build_quote_envelope(ok=True, data=data, error=None)
        except (QuoteFetchError, TimeoutError, asyncio.TimeoutError) as exc:
            payload = _build_quote_envelope(ok=False, data=None, error=str(exc))
        quote_cache_set(symbol, payload)
        return payload

    @router.get("/api/symbol/resolve")
    async def resolve_symbol(symbol: str, asset_class: str | None = None) -> dict[str, Any]:
        canonical = _canonical_route_symbol(symbol, asset_class)
        inferred = default_asset_class_name(canonical, asset_class)
        return {
            "input": symbol,
            "symbol": canonical,
            "asset_class": inferred,
            "changed": canonical != str(symbol or "").strip().upper(),
        }

    app.include_router(router)
