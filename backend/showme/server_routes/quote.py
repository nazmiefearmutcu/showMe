"""Realtime quote snapshot + symbol-resolution routes."""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, FastAPI, Path as PathParam

from . import AppDeps


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
        """
        from showme.quotes import (
            QuoteFetchError,
            fetch_quote_snapshot,
            quote_cache_get,
            quote_cache_set,
        )

        cached = quote_cache_get(symbol)
        if cached is not None:
            return cached
        try:
            data = await asyncio.wait_for(fetch_quote_snapshot(symbol), timeout=5)
            payload = {"ok": True, "data": data}
        except (QuoteFetchError, TimeoutError, asyncio.TimeoutError) as exc:
            payload = {"ok": False, "error": str(exc), "data": None}
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
