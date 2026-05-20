"""Veryfinder bridge routes."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, FastAPI

from . import AppDeps
from ._models import VeryfinderBatchRequest

LOG = logging.getLogger("showme.server.veryfinder")


def register(app: FastAPI, deps: AppDeps) -> None:
    router = APIRouter()

    @router.get("/api/veryfinder/health")
    async def veryfinder_health() -> dict[str, Any]:
        from showme import veryfinder_bridge

        return await asyncio.to_thread(veryfinder_bridge.health)

    @router.get("/api/veryfinder/query")
    async def veryfinder_query(
        q: str | None = None,
        symbol: str | None = None,
        sample: int = 25,
        source: str = "auto",
        engine: str = "rules",
        refresh: bool = False,
    ) -> dict[str, Any]:
        from showme import veryfinder_bridge

        try:
            return await asyncio.to_thread(
                veryfinder_bridge.analyze_symbol,
                symbol,
                q=q,
                sample=sample,
                source=source,
                engine=engine,
                refresh=refresh,
            )
        except Exception as exc:  # noqa: BLE001
            LOG.warning("veryfinder query failed: %s", exc)
            return {
                "ok": False,
                "error": str(exc),
                "symbol": symbol,
                "query": q,
                "meaning": veryfinder_bridge.overlay_meaning(),
            }

    @router.post("/api/veryfinder/article")
    async def veryfinder_article(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        from showme import veryfinder_bridge

        body = payload or {}
        item = body.get("item") if isinstance(body.get("item"), dict) else body
        try:
            return await asyncio.to_thread(
                veryfinder_bridge.analyze_item,
                item,
                symbol=body.get("symbol"),
                topic=body.get("topic"),
                sample=int(body.get("sample") or 25),
                source=str(body.get("source") or "auto"),
                engine=str(body.get("engine") or "rules"),
            )
        except Exception as exc:  # noqa: BLE001
            LOG.warning("veryfinder article failed: %s", exc)
            return {
                "ok": False,
                "error": str(exc),
                "meaning": veryfinder_bridge.overlay_meaning(),
            }

    @router.post("/api/veryfinder/batch")
    async def veryfinder_batch(payload: VeryfinderBatchRequest) -> dict[str, Any]:
        from showme import veryfinder_bridge

        try:
            return await asyncio.to_thread(
                veryfinder_bridge.analyze_batch,
                payload.items,
                symbol=payload.symbol,
                topic=payload.topic,
                sample=payload.sample,
                source=payload.source,
                engine=payload.engine,
                limit=payload.limit,
            )
        except Exception as exc:  # noqa: BLE001
            LOG.warning("veryfinder batch failed: %s", exc)
            return {
                "ok": False,
                "error": str(exc),
                "items": [],
                "meaning": veryfinder_bridge.overlay_meaning(),
            }

    app.include_router(router)
