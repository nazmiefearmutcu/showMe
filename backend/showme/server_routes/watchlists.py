"""Multi-watchlist CRUD routes (FUNC-08 P1)."""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Path as PathParam

from . import AppDeps
from ._models import WatchlistBody


def register(app: FastAPI, deps: AppDeps) -> None:
    router = APIRouter()

    @router.get("/api/watchlists")
    async def list_watchlists_route() -> dict[str, Any]:
        from showme.engine.services.watchlist_store import list_watchlists
        try:
            rows = await asyncio.to_thread(list_watchlists)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"watchlists": rows}

    @router.put("/api/watchlists/{name}")
    async def put_watchlist(
        name: str = PathParam(..., max_length=64, pattern=r"^[A-Za-z0-9 ._\-]+$"),
        body: WatchlistBody | None = None,
    ) -> dict[str, Any]:
        from showme.engine.services.watchlist_store import save_watchlist
        payload = body or WatchlistBody()
        try:
            cleaned = await asyncio.to_thread(save_watchlist, name, payload.symbols)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"name": name, "symbols": cleaned, "ok": True}

    @router.delete("/api/watchlists/{name}")
    async def delete_watchlist_route(
        name: str = PathParam(..., max_length=64, pattern=r"^[A-Za-z0-9 ._\-]+$"),
    ) -> dict[str, Any]:
        from showme.engine.services.watchlist_store import delete_watchlist
        try:
            ok = await asyncio.to_thread(delete_watchlist, name)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"name": name, "deleted": bool(ok)}

    app.include_router(router)
