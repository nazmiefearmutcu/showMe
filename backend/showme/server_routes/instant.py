"""Instant-line firehose routes."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, FastAPI, Query

from . import AppDeps


def register(app: FastAPI, deps: AppDeps) -> None:
    router = APIRouter()

    @router.get("/api/instant/status")
    async def instant_line_status() -> dict[str, Any]:
        from showme.instant_line import instant_status

        return await instant_status()

    @router.get("/api/instant/events")
    async def instant_line_events(limit: int = Query(100, ge=1, le=1000)) -> dict[str, Any]:
        from showme.instant_line import instant_events
        from showme.finbert_analyzer import stamp_items as _finbert_stamp_items

        payload = await instant_events(limit=limit)
        events = payload.get("events")
        if isinstance(events, list) and events:
            # Stamp FinBERT sentiment on every event title+summary.
            # `stamp_items` preserves any sentiment field a downstream
            # already set (e.g. xsen events carry their own classifier
            # output), so this only fills the gaps. Failures are
            # non-fatal — a warning is added to the payload.
            _, finbert_warning = await _finbert_stamp_items(events)
            if finbert_warning:
                existing = payload.get("warning")
                payload["warning"] = (
                    f"{existing}; {finbert_warning}" if existing else finbert_warning
                )
        return payload

    @router.get("/api/instant/health")
    async def instant_line_health() -> dict[str, Any]:
        from showme.instant_line import instant_health

        return await instant_health()

    @router.get("/api/instant/performance")
    async def instant_line_performance() -> dict[str, Any]:
        from showme.instant_line import instant_performance

        return await instant_performance()

    @router.post("/api/instant/backfill")
    async def instant_line_backfill(limit: int = Query(15, ge=1, le=200)) -> dict[str, Any]:
        from showme.instant_line import instant_backfill

        return await instant_backfill(limit=limit)

    app.include_router(router)
